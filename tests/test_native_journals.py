import os
import hashlib
import json
from uuid import uuid4

import pytest

from muscles.migrations.native import RedisJournal, MongoJournal, RedisMigrationBackend, MongoMigrationBackend
from muscles.migrations.versioned import Migration, MigrationStateError, VersionedMigrationBackend


def test_legacy_backends_reexport_adapter_implementations():
    from muscles.data.mongodb.migrations import MongoMigrationBackend as MongoBackend
    from muscles.data.redis.migrations import RedisMigrationBackend as RedisBackend

    assert MongoMigrationBackend is MongoBackend
    assert RedisMigrationBackend is RedisBackend


class RedisFake:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, script, count, key, token):
        if self.values.get(key) == token:
            del self.values[key]
            return 1
        return 0

    def scan_iter(self, match):
        from fnmatch import fnmatch
        return iter([key for key in self.values if fnmatch(key, match)])


class CollectionFake:
    def __init__(self):
        self.values = {}

    def find_one(self, query):
        return self.values.get(query["_id"])

    def find(self, query, projection=None):
        return [dict(value) for value in self.values.values()
                if all(value.get(key) == expected for key, expected in query.items())]

    def insert_one(self, doc):
        if doc["_id"] in self.values:
            raise ValueError("duplicate")
        self.values[doc["_id"]] = dict(doc)

    def update_one(self, query, update):
        from types import SimpleNamespace
        doc = self.values.get(query["_id"])
        matched = doc is not None and all(doc.get(k) == v for k, v in query.items())
        if matched:
            doc.update(update["$set"])
        return SimpleNamespace(matched_count=int(matched))

    def delete_one(self, query):
        from types import SimpleNamespace
        doc = self.values.get(query["_id"])
        matched = doc is not None and all(doc.get(k) == v for k, v in query.items())
        if matched:
            del self.values[query["_id"]]
        return SimpleNamespace(deleted_count=int(matched))


@pytest.mark.parametrize("journal", [RedisJournal(RedisFake(), "test"), MongoJournal(CollectionFake(), "test")])
def test_native_journal_records_versions(journal):
    calls = []
    backend = VersionedMigrationBackend(journal, [Migration("001", "checksum", lambda: calls.append(1))])
    backend.upgrade()
    backend.upgrade()
    assert calls == [1]
    assert journal.get("001") == ("checksum", "complete")


def test_sources_are_isolated():
    client = RedisFake()
    one, two = RedisJournal(client, "a"), RedisJournal(client, "b")
    one.begin("001", "checksum")
    assert two.get("001") is None


def test_redis_legacy_journal_identity_is_preserved():
    client = RedisFake()
    old_id = hashlib.sha256(json.dumps(["test", "001"], ensure_ascii=False).encode()).hexdigest()
    client.values[f"muscles:migrations:{old_id}"] = json.dumps({"checksum": "checksum", "state": "complete"})
    calls = []
    backend = RedisMigrationBackend(client, "test", [Migration("001", "checksum", lambda: calls.append("up"))])
    backend.upgrade()
    assert backend.status()["current"] == ["001"]
    assert not calls


def test_redis_unattributable_legacy_history_requires_reconciliation():
    client = RedisFake()
    old_id = hashlib.sha256(json.dumps(["other", "001"], ensure_ascii=False).encode()).hexdigest()
    client.values[f"muscles:migrations:{old_id}"] = json.dumps({"checksum": "hash", "state": "complete"})
    backend = RedisMigrationBackend(client, "test", [])
    with pytest.raises(MigrationStateError, match="reconcile"):
        backend.status()


def test_redis_journal_rejects_glob_metacharacters_in_prefix():
    with pytest.raises(ValueError, match="prefix"):
        RedisMigrationBackend(RedisFake(), "test", [], prefix="shared:*")


@pytest.mark.parametrize("backend", [
    RedisMigrationBackend(RedisFake(), "test", []),
    MongoMigrationBackend(CollectionFake(), "test", []),
])
def test_backend_prevents_concurrent_run_and_releases_lock(backend):
    calls = []
    def run():
        with pytest.raises(Exception):
            backend.upgrade()
        calls.append(1)
    backend.migrations = (Migration("001", "checksum", run),)
    backend.upgrade()
    backend.upgrade()
    assert calls == [1]


@pytest.mark.parametrize("backend", [
    RedisMigrationBackend(RedisFake(), "test", []),
    MongoMigrationBackend(CollectionFake(), "test", []),
])
def test_backend_status_and_downgrade_track_nontransactional_reversion(backend):
    calls = []
    backend.migrations = (Migration("001", "checksum", lambda: calls.append("up"), lambda: calls.append("down")),)
    assert backend.plan() == ["001"]
    backend.upgrade()
    assert backend.status()["current"] == ["001"]
    backend.downgrade("base")
    assert backend.status()["current"] == []
    assert calls == ["up", "down"]


@pytest.mark.parametrize("backend", [
    RedisMigrationBackend(RedisFake(), "test", []),
    MongoMigrationBackend(CollectionFake(), "test", []),
])
def test_completed_journal_records_application_time(backend):
    backend.migrations = (Migration("001", "checksum", lambda: None),)
    backend.upgrade()
    if isinstance(backend, RedisMigrationBackend):
        entry = json.loads(backend.client.get(backend.journal._key("001")))
    else:
        entry = backend.collection.find_one({"_id": next(key for key in backend.collection.values if not key.startswith("lock:"))})
    assert entry.get("applied_at") is not None


@pytest.mark.parametrize("backend", [
    RedisMigrationBackend(RedisFake(), "test", []),
    MongoMigrationBackend(CollectionFake(), "test", []),
])
def test_interrupted_rollback_is_not_retried_automatically(backend):
    def fail():
        raise RuntimeError("interrupted")

    backend.migrations = (Migration("001", "checksum", lambda: None, fail),)
    backend.upgrade()
    with pytest.raises(RuntimeError, match="interrupted"):
        backend.downgrade("base")
    assert backend.journal.get("001") == ("checksum", "reverting")
    with pytest.raises(MigrationStateError, match="interrupted"):
        backend.status()


@pytest.mark.parametrize("backend", [
    RedisMigrationBackend(RedisFake(), "test", []),
    MongoMigrationBackend(CollectionFake(), "test", []),
])
def test_missing_previously_applied_migration_is_rejected(backend):
    backend.migrations = (Migration("001", "first", lambda: None), Migration("002", "second", lambda: None))
    backend.upgrade()
    backend.migrations = backend.migrations[:1]
    with pytest.raises(MigrationStateError, match="missing"):
        backend.status()


@pytest.mark.parametrize("backend", [
    RedisMigrationBackend(RedisFake(), "test", []),
    MongoMigrationBackend(CollectionFake(), "test", []),
])
def test_lost_lock_ownership_is_reported(backend):
    with pytest.raises(MigrationStateError, match="lock"):
        with backend._lock():
            if isinstance(backend, RedisMigrationBackend):
                backend.client.set(backend.lock_key, "other-owner")
            else:
                backend.collection.values[backend.lock_id]["token"] = "other-owner"


@pytest.mark.skipif(not os.getenv("MUSCLES_MIGRATION_TEST_REDIS"), reason="isolated Redis not configured")
def test_redis_migration_lifecycle_against_real_server():
    from redis import Redis

    client = Redis.from_url(os.environ["MUSCLES_MIGRATION_TEST_REDIS"])
    prefix = f"muscles:example:{uuid4().hex}"
    key = f"{prefix}:data"
    backend = RedisMigrationBackend(client, "example", [
        Migration("001", "checksum", lambda: client.set(key, "value"), lambda: client.delete(key))
    ], prefix=prefix)
    try:
        backend.upgrade()
        assert client.get(key) == b"value"
        assert backend.status()["current"] == ["001"]
        backend.downgrade("base")
        assert client.get(key) is None
        assert backend.status()["current"] == []
    finally:
        client.close()


@pytest.mark.skipif(not os.getenv("MUSCLES_MIGRATION_TEST_MONGODB"), reason="isolated MongoDB not configured")
def test_mongodb_migration_lifecycle_against_real_server():
    from pymongo import MongoClient

    client = MongoClient(os.environ["MUSCLES_MIGRATION_TEST_MONGODB"], serverSelectionTimeoutMS=5000)
    database = client[f"muscles_test_{uuid4().hex}"]
    backend = MongoMigrationBackend(database.journal, "example", [
        Migration("001", "checksum", lambda: database.data.insert_one({"_id": "one"}),
                  lambda: database.data.delete_one({"_id": "one"}))
    ])
    try:
        backend.upgrade()
        assert database.data.find_one({"_id": "one"}) is not None
        assert backend.status()["current"] == ["001"]
        backend.downgrade("base")
        assert database.data.find_one({"_id": "one"}) is None
        assert backend.status()["current"] == []
    finally:
        client.close()
