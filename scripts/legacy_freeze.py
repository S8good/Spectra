#!/usr/bin/env python3
"""
Legacy table freeze audit & backfill helper.

Provides a single entry point to:
1. Backup the SQLite database and optionally export CSV snapshots of legacy tables.
2. Check whether legacy tables (spectra / analysis_results) still receive new writes.
3. Optionally invoke the Phase 1 backfill routine to populate missing structured references.
4. Emit a Markdown report that can be attached to the monthly freeze review.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DB = Path.home() / ".nanosense" / "nanosense_data.db"
DEFAULT_REPORT_DIR = REPO_ROOT / "docs" / "reports"
DEFAULT_BACKUP_DIR = DEFAULT_REPORT_DIR / "backups"


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO timestamp: {value}") from exc


def normalize_ts(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cursor.fetchone() is not None


def get_columns(conn: sqlite3.Connection, table: str) -> Sequence[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def count_rows(conn: sqlite3.Connection, query: str, params: Sequence[object] | None = None) -> int:
    cursor = conn.execute(query, params or [])
    value = cursor.fetchone()
    return int(value[0]) if value else 0


def analyze_table(
    conn: sqlite3.Connection,
    *,
    table: str,
    pending_sql: Optional[str],
    pending_columns: Sequence[str],
    recent_columns: Sequence[str],
    freeze_after: Optional[str],
) -> Dict[str, Optional[int]]:
    result: Dict[str, Optional[int]] = {
        "total": None,
        "pending": None,
        "recent": None,
        "exists": False,
    }
    if not table_exists(conn, table):
        return result
    result["exists"] = True
    result["total"] = count_rows(conn, f"SELECT COUNT(*) FROM {table}")

    columns = set(get_columns(conn, table))
    if pending_sql and set(pending_columns).issubset(columns):
        result["pending"] = count_rows(conn, pending_sql)

    if freeze_after:
        for column in recent_columns:
            if column in columns:
                result["recent"] = count_rows(
                    conn,
                    f"""
                    SELECT COUNT(*) FROM {table}
                    WHERE {column} IS NOT NULL AND {column} > ?
                    """,
                    (freeze_after,),
                )
                break
    return result


def analyze_legacy_tables(conn: sqlite3.Connection, freeze_after: Optional[str]) -> Dict[str, Dict[str, Optional[int]]]:
    return {
        "spectra": analyze_table(
            conn,
            table="spectra",
            pending_sql="""
                SELECT COUNT(*) FROM spectra
                WHERE spectrum_set_id IS NULL OR data_id IS NULL
            """,
            pending_columns=("spectrum_set_id", "data_id"),
            recent_columns=("created_at", "timestamp"),
            freeze_after=freeze_after,
        ),
        "analysis_results": analyze_table(
            conn,
            table="analysis_results",
            pending_sql="""
                SELECT COUNT(*) FROM analysis_results
                WHERE analysis_run_id IS NULL
            """,
            pending_columns=("analysis_run_id",),
            recent_columns=("created_at", "timestamp"),
            freeze_after=freeze_after,
        ),
    }


def build_warnings(stats: Dict[str, Dict[str, Optional[int]]], freeze_after: Optional[str]) -> List[str]:
    warnings: List[str] = []
    spectra = stats["spectra"]
    analysis = stats["analysis_results"]

    if spectra["exists"]:
        if spectra["pending"]:
            warnings.append(f"{spectra['pending']} spectra rows are still missing structured pointers.")
        if freeze_after and spectra["recent"]:
            warnings.append(f"{spectra['recent']} spectra rows created after freeze threshold {freeze_after}.")
    else:
        warnings.append("spectra table missing; cannot verify freeze status.")

    if analysis["exists"]:
        if analysis["pending"]:
            warnings.append(f"{analysis['pending']} analysis_results rows still lack analysis_run_id.")
        if freeze_after and analysis["recent"]:
            warnings.append(f"{analysis['recent']} analysis_results rows were written after freeze threshold {freeze_after}.")
    else:
        warnings.append("analysis_results table missing; cannot verify freeze status.")

    return warnings


def run_backfill(conn: sqlite3.Connection) -> Dict[str, int]:
    from nanosense.core.migrations import migration_0001_prepare_phase1_schema as phase1

    before = analyze_legacy_tables(conn, freeze_after=None)
    phase1._migrate_spectra(conn)
    phase1._migrate_analysis_results(conn)
    after = analyze_legacy_tables(conn, freeze_after=None)

    return {
        "spectra_fixed": max(0, (before["spectra"]["pending"] or 0) - (after["spectra"]["pending"] or 0)),
        "analysis_fixed": max(0, (before["analysis_results"]["pending"] or 0) - (after["analysis_results"]["pending"] or 0)),
    }


def backup_database(db_path: Path, backup_dir: Path, run_stamp: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{db_path.stem}_{run_stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def export_table_to_csv(conn: sqlite3.Connection, table: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    cursor = conn.execute(f"SELECT * FROM {table}")
    headers = [col[0] for col in cursor.description or []]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if headers:
            writer.writerow(headers)
        for row in cursor.fetchall():
            writer.writerow(row)
    return destination


def write_report(
    report_path: Path,
    *,
    freeze_after: Optional[str],
    before_stats: Dict[str, Dict[str, Optional[int]]],
    after_stats: Dict[str, Dict[str, Optional[int]]],
    warnings: List[str],
    backup_path: Optional[Path],
    csv_paths: List[Path],
    backfill_summary: Optional[Dict[str, int]],
) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        f"# Legacy Freeze Audit ({timestamp})",
        "",
        f"- Freeze threshold: `{freeze_after or 'n/a'}`",
        f"- Backup: `{backup_path}`" if backup_path else "- Backup: skipped",
    ]
    if csv_paths:
        lines.append("- CSV exports:")
        for path in csv_paths:
            lines.append(f"  - {path}")
    else:
        lines.append("- CSV exports: skipped")

    def _metric(table: str, key: str, stats: Dict[str, Dict[str, Optional[int]]]) -> str:
        value = stats[table].get(key)
        return str(value) if value is not None else "-"

    rows = [
        "| Metric | Before | After |",
        "| --- | --- | --- |",
        f"| Spectra total | {_metric('spectra', 'total', before_stats)} | {_metric('spectra', 'total', after_stats)} |",
        f"| Spectra pending | {_metric('spectra', 'pending', before_stats)} | {_metric('spectra', 'pending', after_stats)} |",
        f"| Spectra recent | {_metric('spectra', 'recent', before_stats)} | {_metric('spectra', 'recent', after_stats)} |",
        f"| Analysis total | {_metric('analysis_results', 'total', before_stats)} | {_metric('analysis_results', 'total', after_stats)} |",
        f"| Analysis pending | {_metric('analysis_results', 'pending', before_stats)} | {_metric('analysis_results', 'pending', after_stats)} |",
        f"| Analysis recent | {_metric('analysis_results', 'recent', before_stats)} | {_metric('analysis_results', 'recent', after_stats)} |",
    ]

    lines.append("")
    lines.append("## Metrics")
    lines.extend(rows)

    lines.append("")
    lines.append("## Warnings")
    if warnings:
        for item in warnings:
            lines.append(f"- {item}")
    else:
        lines.append("- None")

    lines.append("")
    lines.append("## Backfill")
    if backfill_summary:
        lines.append(
            f"- spectra rows fixed: {backfill_summary['spectra_fixed']}, "
            f"analysis rows fixed: {backfill_summary['analysis_fixed']}"
        )
    else:
        lines.append("- Not requested.")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit legacy tables, optionally run backfill, and emit a Markdown report.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"Path to SQLite database (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--freeze-after",
        help="ISO timestamp representing the date after which legacy tables must not receive writes.",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(DEFAULT_BACKUP_DIR),
        help=f"Directory for database backups (default: {DEFAULT_BACKUP_DIR}).",
    )
    parser.add_argument(
        "--export-csv-dir",
        help="Directory for CSV dumps of spectra/analysis_results (optional).",
    )
    parser.add_argument(
        "--backfill-missing",
        action="store_true",
        help="Invoke the Phase 1 migration helper to backfill missing structured references.",
    )
    parser.add_argument(
        "--report-file",
        help="Path to the Markdown report. Defaults to docs/reports/legacy_freeze_<timestamp>.md",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 when warnings are present.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"Database file not found: {db_path}")

    freeze_after_dt = normalize_ts(parse_iso(args.freeze_after)) if args.freeze_after else None
    freeze_after_str = freeze_after_dt.strftime("%Y-%m-%d %H:%M:%S") if freeze_after_dt else None

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_path = (
        Path(args.report_file).expanduser().resolve()
        if args.report_file
        else DEFAULT_REPORT_DIR / f"legacy_freeze_{run_stamp}.md"
    )

    backup_path: Optional[Path] = None
    if args.backup_dir:
        backup_path = backup_database(db_path, Path(args.backup_dir).expanduser().resolve(), run_stamp)
        print(f"Backup created at: {backup_path}")

    conn = sqlite3.connect(db_path)

    csv_paths: List[Path] = []
    try:
        if args.export_csv_dir:
            export_dir = Path(args.export_csv_dir).expanduser().resolve()
            for table in ("spectra", "analysis_results"):
                if table_exists(conn, table):
                    csv_path = export_table_to_csv(conn, table, export_dir / f"{table}_{run_stamp}.csv")
                    csv_paths.append(csv_path)
                    print(f"Exported {table} to: {csv_path}")

        before_stats = analyze_legacy_tables(conn, freeze_after_str)
        after_stats = before_stats
        backfill_summary: Optional[Dict[str, int]] = None

        if args.backfill_missing:
            backfill_summary = run_backfill(conn)
            conn.commit()
            after_stats = analyze_legacy_tables(conn, freeze_after_str)

        warnings = build_warnings(after_stats, freeze_after_str)
    finally:
        conn.close()

    write_report(
        report_path,
        freeze_after=freeze_after_str,
        before_stats=before_stats,
        after_stats=after_stats,
        warnings=warnings,
        backup_path=backup_path,
        csv_paths=csv_paths,
        backfill_summary=backfill_summary,
    )
    print(f"Report written to: {report_path}")

    if warnings and args.strict:
        return 1
    return 0


__all__ = [
    "analyze_legacy_tables",
    "build_warnings",
]


if __name__ == "__main__":
    raise SystemExit(main())
