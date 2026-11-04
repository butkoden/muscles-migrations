# muscles-migrations

Compatibility package: new code should import the registry and source contracts
from `muscles-data`. SQL migration backends live in `muscles-data-sql`; Redis and
MongoDB backends live in their respective data adapter packages. This package
keeps legacy imports available for existing projects. See
`muscles-data/docs/migrations.en.md` for discovery, command integration, locks
and migration history.

Register migration sources with a backend implementing `upgrade(target)`.
The registry validates dependencies before applying sources in dependency order.
Backends own their version tracking, concurrency handling and rollback semantics.

```python
import os

from muscles.data import MigrationRegistry, MigrationSource, discover_migration_modules
from muscles.data.sql.native_migrations import NativeSqlMigration, NativeSqlMigrationSourceBackend

registry = MigrationRegistry()
modules = discover_migration_modules("myapp.migrations")
migrations = [NativeSqlMigration.from_module(module) for module in modules]
registry.register(MigrationSource(
    name="accounts",
    backend=NativeSqlMigrationSourceBackend(
        os.environ["DATABASE_URL"], "accounts", migrations
    ),
))
registry.upgrade()
```

`DATABASE_URL` must point to a SQLite or PostgreSQL database supported by the
native SQL migration backend. The application should create one registry in
its composition root and pass it to its CLI/runtime integration; packages
should not create duplicate registries or connection managers.

## Experimental Redis and MongoDB backends

Redis and MongoDB migration backends are provided by their respective data
adapter packages. Their backend configuration and migration object types are
owned by those adapters; the shared registry contract remains in `muscles-data`.

Locks deliberately do not expire: an expired lease could allow a second runner
to overlap a long-running migration. If a process dies, an operator must first
confirm it is no longer running and inspect the migration state before manually
clearing the lock. A migration left in `running` requires manual recovery; it is
never automatically retried. The backing journal must itself be durable and
protected against eviction or deletion.
Repository: https://github.com/butkoden/muscles-migrations
