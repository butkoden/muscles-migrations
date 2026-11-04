import pytest

from muscles.migrations import MigrationRegistry, MigrationSource


def test_legacy_imports_share_the_data_contract():
    from muscles.data.migrations import MigrationRegistry as DataRegistry, MigrationSource as DataSource

    assert MigrationRegistry is DataRegistry
    assert MigrationSource is DataSource


class Backend:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    def upgrade(self, target="head"):
        self.calls.append((self.name, target))


def test_sources_run_after_dependencies():
    calls = []
    registry = MigrationRegistry()
    registry.register(MigrationSource("sites", Backend("sites", calls), ("accounts",)))
    registry.register(MigrationSource("accounts", Backend("accounts", calls)))
    registry.upgrade()
    assert calls == [("accounts", "head"), ("sites", "head")]


def test_missing_or_cyclic_dependencies_fail_before_upgrade():
    calls = []
    registry = MigrationRegistry()
    registry.register(MigrationSource("a", Backend("a", calls), ("b",)))
    with pytest.raises(ValueError):
        registry.upgrade()
    registry.register(MigrationSource("b", Backend("b", calls), ("a",)))
    with pytest.raises(ValueError):
        registry.upgrade()
    assert not calls
