"""Compatibility exports; migration orchestration lives in muscles-data."""

from muscles.data.migrations import MigrationBackend, MigrationRegistry, MigrationSource

__all__ = ["MigrationBackend", "MigrationRegistry", "MigrationSource"]
