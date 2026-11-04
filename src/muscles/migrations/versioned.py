"""Compatibility imports for the shared versioned migration contract."""
from muscles.data.versioned_migrations import (
    Migration, MigrationJournal, MigrationStateError, VersionedMigrationBackend,
)

__all__ = ["Migration", "MigrationJournal", "MigrationStateError", "VersionedMigrationBackend"]
