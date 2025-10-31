#!/usr/bin/env python
"""
Migration validation helper.

This script inspects the SQLite database to verify that Phase 1 schema changes
and data migrations were applied successfully. It performs the following checks:

1. Ensures required tables/views/columns exist.
2. Confirms spectra data has migrated (legacy view count vs original table).
3. Checks analysis_results rows are linked to analysis_runs.
4. Provides sampling output for manual inspection.

Usage:
    python scripts/validate_migration.py --db path/to/database.db
    python scripts/validate_migration.py  # autodetect via config.json
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from nanosense.utils.config_manager import load_settings  # type: ignore
except ImportError:
    load_settings = None


REQUIRED_TABLES = {
    "projects",
    "experiments",
    "spectra",
    "analysis_results",
    "spectrum_sets",
    "spectrum_data",
    "analysis_runs",
    "analysis_metrics",
    "experiment_versions",
}

REQUIRED_VIEWS = {
    "legacy_spectrum_sets_view",
    "legacy_analysis_runs_view",
}

REQUIRED_COLUMNS = {
    "spectra": {"spectrum_set_id", "data_id", "quality_flag"},
    "analysis_results": {"analysis_run_id"},
}


def resolve_db_path(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    if load_settings:
        try:
            settings = load_settings()
            candidate = settings.get("database_path")
            if candidate:
                return Path(candidate).expanduser().resolve()
        except Exception:
            pass
    raise ValueError("未指定数据库路径，请使用 --db 或在配置文件中设置 database_path。")


def fetch_set(conn: sqlite3.Connection, query: str) -> set[str]:
    cursor = conn.execute(query)
    return {row[0] for row in cursor.fetchall()}


def check_tables(conn: sqlite3.Connection) -> list[str]:
    tables = fetch_set(conn, "SELECT name FROM sqlite_master WHERE type='table'")
    missing = sorted(REQUIRED_TABLES - tables)
    return missing


def check_views(conn: sqlite3.Connection) -> list[str]:
    views = fetch_set(conn, "SELECT name FROM sqlite_master WHERE type='view'")
    missing = sorted(REQUIRED_VIEWS - views)
    return missing


def check_columns(conn: sqlite3.Connection, table: str, required: Iterable[str]) -> list[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    missing = sorted(set(required) - existing)
    return missing


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
    return cursor.fetchone()[0]


def sample_rows(conn: sqlite3.Connection, table: str, columns: Sequence[str], limit: int = 5) -> list:
    cols = ", ".join(columns)
    cursor = conn.execute(f"SELECT {cols} FROM {table} LIMIT {limit}")
    return cursor.fetchall()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 1 migration state.")
    parser.add_argument("--db", dest="db_path", help="SQLite database file path")
    args = parser.parse_args(argv)

    try:
        db_path = resolve_db_path(args.db_path)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    if not db_path.exists():
        parser.error(f"数据库文件不存在：{db_path}")
        return 2

    conn = sqlite3.connect(db_path)

    errors: list[str] = []
    warnings: list[str] = []

    # Structural checks
    missing_tables = check_tables(conn)
    if missing_tables:
        errors.append(f"缺少表：{', '.join(missing_tables)}")

    missing_views = check_views(conn)
    if missing_views:
        errors.append(f"缺少视图：{', '.join(missing_views)}")

    for table, columns in REQUIRED_COLUMNS.items():
        missing = check_columns(conn, table, columns)
        if missing:
            errors.append(f"{table} 缺少列：{', '.join(missing)}")

    # Count checks
    try:
        legacy_count = count_rows(conn, "legacy_spectrum_sets_view")
        spectra_count = count_rows(conn, "spectra")
        if legacy_count != spectra_count:
            warnings.append(
                f"视图记录数 {legacy_count} 与 spectra 数量 {spectra_count} 不一致，检查是否存在未迁移或质量标记。"
            )
    except sqlite3.OperationalError:
        warnings.append("无法统计 legacy_spectrum_sets_view 行数（视图可能缺失）。")

    # Analysis linkage
    try:
        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM analysis_results
            WHERE analysis_run_id IS NULL
            """
        )
        missing_links = cursor.fetchone()[0]
        if missing_links:
            errors.append(f"{missing_links} 条 analysis_results 未关联到 analysis_runs。")
    except sqlite3.OperationalError:
        warnings.append("无法检查 analysis_results 关联，表可能缺失。")

    # Sampling for manual inspection
    try:
        samples = sample_rows(
            conn,
            "legacy_spectrum_sets_view",
            ["experiment_id", "type", "timestamp"],
            limit=3,
        )
        print("legacy_spectrum_sets_view 示例:", samples)
    except sqlite3.OperationalError:
        print("无法读取 legacy_spectrum_sets_view 示例。")

    try:
        samples = sample_rows(
            conn,
            "legacy_analysis_runs_view",
            ["experiment_id", "analysis_type", "timestamp"],
            limit=3,
        )
        print("legacy_analysis_runs_view 示例:", samples)
    except sqlite3.OperationalError:
        print("无法读取 legacy_analysis_runs_view 示例。")

    conn.close()

    if errors:
        print("\n[ERROR] 发现以下问题：")
        for err in errors:
            print(" -", err)
        return 1

    if warnings:
        print("\n[WARN] 警告：")
        for warn in warnings:
            print(" -", warn)

    print("\n[OK] 迁移结构检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
