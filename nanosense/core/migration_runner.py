# nanosense/core/migration_runner.py
"""
Lightweight migration runner for the embedded SQLite database.

This module provides schema version tracking that can be invoked both from the
application bootstrap (see `DatabaseManager`) and from the stand-alone CLI
script under `scripts/migrate_db.py`.
"""

import datetime
import sqlite3
from typing import Callable, Iterable, List, Sequence, Set, Tuple

from .migrations import MIGRATIONS

MigrationFunc = Callable[[sqlite3.Connection], None]
MigrationDescriptor = Tuple[str, MigrationFunc]

SCHEMA_MIGRATIONS_TABLE = "schema_migrations"


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    """Create the bookkeeping table if it does not exist yet."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATIONS_TABLE} (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _fetch_applied_migrations(conn: sqlite3.Connection) -> Set[str]:
    cursor = conn.execute(
        f"SELECT migration_id FROM {SCHEMA_MIGRATIONS_TABLE} ORDER BY migration_id"
    )
    return {row[0] for row in cursor.fetchall()}


def get_pending_migrations(
    conn: sqlite3.Connection,
) -> List[MigrationDescriptor]:
    """
    Return migration descriptors that have not yet been applied.

    The connection is expected to be open and managed by the caller.
    """
    _ensure_schema_migrations_table(conn)
    applied = _fetch_applied_migrations(conn)
    return [
        (migration_id, migration_fn)
        for migration_id, migration_fn in MIGRATIONS
        if migration_id not in applied
    ]


def run_migrations(
    conn: sqlite3.Connection,
    logger: Callable[[str], None] = print,
    dry_run: bool = False,
) -> Sequence[str]:
    """
    Apply pending migrations sequentially.

    Returns the ordered list of migration IDs that were processed. When
    `dry_run` is True, no changes are committed and only the list of pending
    migrations is returned.
    """
    pending = get_pending_migrations(conn)
    if dry_run:
        for migration_id, _ in pending:
            logger(f"[dry-run] Pending migration: {migration_id}")
        return [migration_id for migration_id, _ in pending]

    processed: List[str] = []
    for migration_id, migration_fn in pending:
        logger(f"Applying migration {migration_id}...")
        try:
            with conn:
                migration_fn(conn)
                conn.execute(
                    f"INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (migration_id, applied_at) "
                    "VALUES (?, ?)",
                    (migration_id, datetime.datetime.utcnow().isoformat()),
                )
            processed.append(migration_id)
            logger(f"Migration {migration_id} completed.")
        except Exception as exc:
            logger(f"Migration {migration_id} failed: {exc}")
            raise
    if not processed:
        logger("No pending migrations. Schema is up to date.")
    return processed


__all__ = [
    "MigrationFunc",
    "MigrationDescriptor",
    "get_pending_migrations",
    "run_migrations",
]
