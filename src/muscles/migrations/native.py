"""Compatibility imports for optional backend-specific migration packages."""

__all__ = ["RedisJournal", "RedisMigrationBackend", "MongoJournal", "MongoMigrationBackend"]


def __getattr__(name):
    if name in {"RedisJournal", "RedisMigrationBackend"}:
        from muscles.data.redis import migrations
        return getattr(migrations, name)
    if name in {"MongoJournal", "MongoMigrationBackend"}:
        from muscles.data.mongodb import migrations
        return getattr(migrations, name)
    raise AttributeError(name)
