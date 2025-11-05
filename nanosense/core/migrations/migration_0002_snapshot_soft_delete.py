"""
Migration 0002: introduce soft-delete flag for instrument/process snapshots.
"""

import sqlite3

MIGRATION_ID = "0002_snapshot_soft_delete"


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column_definition: str, column_name: str
) -> bool:
    if _column_exists(conn, table, column_name):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_definition}")
    return True


def _ensure_flag_initialized(
    conn: sqlite3.Connection, table: str, column_name: str
) -> None:
    conn.execute(f"UPDATE {table} SET {column_name} = 1 WHERE {column_name} IS NULL")


def apply(conn: sqlite3.Connection) -> None:
    updated = [
        _add_column_if_missing(
            conn,
            "instrument_states",
            "is_active INTEGER NOT NULL DEFAULT 1",
            "is_active",
        ),
        _add_column_if_missing(
            conn,
            "processing_snapshots",
            "is_active INTEGER NOT NULL DEFAULT 1",
            "is_active",
        ),
    ]

    if any(updated):
        _ensure_flag_initialized(conn, "instrument_states", "is_active")
        _ensure_flag_initialized(conn, "processing_snapshots", "is_active")


__all__ = ["MIGRATION_ID", "apply"]
