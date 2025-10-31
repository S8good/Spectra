# nanosense/core/migrations/__init__.py
"""
Registry for database migrations.

Each migration module should expose a callable `apply(conn: sqlite3.Connection)`
and register itself by appending `(migration_id, apply)` to `MIGRATIONS`.
`migration_id` must be unique and sortable (e.g. zero-padded numeric prefixes).
"""

from typing import Callable, List, Tuple
import sqlite3

from . import migration_0001_prepare_phase1_schema

MigrationFunc = Callable[[sqlite3.Connection], None]
MigrationDescriptor = Tuple[str, MigrationFunc]

MIGRATIONS: List[MigrationDescriptor] = [
    (
        migration_0001_prepare_phase1_schema.MIGRATION_ID,
        migration_0001_prepare_phase1_schema.apply,
    ),
]

__all__ = ["MIGRATIONS", "MigrationFunc", "MigrationDescriptor"]
