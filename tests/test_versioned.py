import pytest
import importlib.util

from muscles.migrations.versioned import Migration, MigrationStateError, VersionedMigrationBackend


class Journal:
    def __init__(self):
        self.entries = {}

    def get(self, version):
        return self.entries.get(version)

    def begin(self, version, checksum):
        self.entries[version] = (checksum, "running")

    def complete(self, version, checksum):
        self.entries[version] = (checksum, "complete")


def test_applies_once_and_detects_changed_migration():
    calls = []
    journal = Journal()
    backend = VersionedMigrationBackend(journal, [Migration("001", "checksum", lambda: calls.append(1))])
    backend.upgrade()
    backend.upgrade()
    assert calls == [1]
    with pytest.raises(MigrationStateError):
        VersionedMigrationBackend(journal, [Migration("001", "changed", lambda: None)]).upgrade()


def test_failure_leaves_running_state_and_does_not_rerun():
    journal = Journal()

    def fail():
        raise RuntimeError("failure")

    backend = VersionedMigrationBackend(journal, [Migration("001", "checksum", fail)])
    with pytest.raises(RuntimeError):
        backend.upgrade()
    with pytest.raises(MigrationStateError):
        backend.upgrade()


def test_changed_file_after_discovery_is_not_executed(tmp_path):
    path = tmp_path / "m001.py"
    path.write_text("revision = '001'\ndef upgrade():\n    pass\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("test_non_sql_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    migration = Migration.from_module(module)
    path.write_text(path.read_text() + "# changed\n", encoding="utf-8")
    with pytest.raises(MigrationStateError, match="changed"):
        VersionedMigrationBackend(Journal(), [migration]).upgrade()


def test_migration_module_receives_explicit_resource(tmp_path):
    path = tmp_path / "m002.py"
    path.write_text("revision = '002'\ndef upgrade(resource):\n    resource.append('up')\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("test_non_sql_migration_resource", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    resource = []
    migration = Migration.from_module(module, resource=resource)
    VersionedMigrationBackend(Journal(), [migration]).upgrade()
    assert resource == ["up"]
