#!/usr/bin/env python3
"""
Weekly snapshot governance helper.

Combines snapshot report generation, optional cleanup, and a Markdown summary so the
operations team can run a single command during the recurring maintenance slot.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cleanup_snapshots  # noqa: E402
import report_snapshots  # noqa: E402

DEFAULT_DB = Path.home() / ".nanosense" / "nanosense_data.db"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "reports"


def _format_snapshot_stats(analysis: Dict[str, Optional[Dict[str, object]]], limit: int = 3) -> List[str]:
    lines: List[str] = []
    for table, stats in analysis.items():
        if not stats:
            lines.append(f"- `{table}`: table missing or empty.")
            continue
        duplicate_pct = stats["duplicate_ratio"] * 100
        lines.append(
            f"- `{table}` total={stats['total_records']} unique={stats['unique_fingerprints']} "
            f"duplicates={stats['duplicate_records']} ({duplicate_pct:.2f}%) unreferenced={stats['unreferenced_records']}"
        )
        duplicates = stats.get("top_duplicates") or []
        if duplicates:
            lines.append("  - Top fingerprints:")
            for entry in duplicates[:limit]:
                fingerprint = entry["fingerprint"]
                count = entry["count"]
                refs = entry["reference_count"]
                lines.append(f"    - `{fingerprint}` (records={count}, references={refs})")
    return lines


def _format_cleanup_section(results: Dict[str, cleanup_snapshots.CleanupStats], dry_run: bool) -> List[str]:
    if not results:
        return ["- Cleanup skipped."]

    lines: List[str] = [f"- Mode: {'dry-run' if dry_run else 'apply'}"]
    for table, stats in results.items():
        if not stats.table_exists:
            lines.append(f"- `{table}` table missing; skipped.")
            continue
        lines.append(
            f"- `{table}` candidates={len(stats.candidates)} updated={stats.updated_count}"
        )
        if stats.candidates:
            preview = ", ".join(str(item.record_id) for item in stats.candidates[:5])
            lines.append(f"  - Preview IDs: {preview}")
    return lines


def _write_summary(
    summary_path: Path,
    *,
    db_path: Path,
    analysis: Dict[str, Optional[Dict[str, object]]],
    cleanup_results: Dict[str, cleanup_snapshots.CleanupStats],
    cleanup_dry_run: bool,
    generated_files: List[Path],
) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        f"# Snapshot Governance Summary ({timestamp})",
        "",
        "## Context",
        f"- Database: `{db_path}`",
    ]

    lines.append("")
    lines.append("## Snapshot Statistics")
    lines.extend(_format_snapshot_stats(analysis))

    lines.append("")
    lines.append("## Cleanup")
    lines.extend(_format_cleanup_section(cleanup_results, cleanup_dry_run))

    lines.append("")
    lines.append("## Files")
    for path in generated_files:
        lines.append(f"- {path}")

    summary_path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run snapshot report + cleanup and emit a Markdown summary."
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"SQLite database path (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory for snapshot artifacts (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--summary-file",
        help="Optional explicit summary path. Defaults to docs/reports/snapshot_governance_<timestamp>.md",
    )
    parser.add_argument(
        "--top-duplicates",
        type=int,
        default=10,
        help="Number of duplicate fingerprints to include in snapshot_report.md (default: 10).",
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Only generate reports without running cleanup.",
    )
    parser.add_argument(
        "--cleanup-dry-run",
        action="store_true",
        help="Preview cleanup candidates without updating is_active.",
    )
    parser.add_argument(
        "--cleanup-age-days",
        type=int,
        default=180,
        help="Age threshold (days) used when cleanup windows are not specified.",
    )
    parser.add_argument(
        "--cleanup-before",
        help="ISO timestamp; only records older than this value are considered for cleanup.",
    )
    parser.add_argument(
        "--cleanup-window-start",
        help="ISO timestamp; skip cleanup for records before this value.",
    )
    parser.add_argument(
        "--cleanup-window-end",
        help="ISO timestamp; hard upper bound for cleanup (overrides --cleanup-before).",
    )
    parser.add_argument(
        "--cleanup-table",
        action="append",
        choices=("instrument_states", "processing_snapshots"),
        help="Limit cleanup to one or more tables (can be repeated).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_path = Path(args.db).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    summary_path = (
        Path(args.summary_file).expanduser().resolve()
        if args.summary_file
        else output_dir / f"snapshot_governance_{run_stamp}.md"
    )

    analysis = report_snapshots.generate_snapshot_reports(
        str(db_path),
        str(output_dir),
        args.top_duplicates,
    )

    cleanup_results: Dict[str, cleanup_snapshots.CleanupStats] = {}
    if not args.skip_cleanup:
        before_dt = cleanup_snapshots.parse_timestamp(args.cleanup_before) if args.cleanup_before else None
        window_start_dt = cleanup_snapshots.parse_timestamp(args.cleanup_window_start) if args.cleanup_window_start else None
        window_end_dt = cleanup_snapshots.parse_timestamp(args.cleanup_window_end) if args.cleanup_window_end else None
        latest_allowed = window_end_dt or before_dt
        cleanup_results = cleanup_snapshots.perform_cleanup(
            str(db_path),
            tables=args.cleanup_table,
            age_days=args.cleanup_age_days,
            window_start=window_start_dt,
            latest_allowed=latest_allowed,
            dry_run=args.cleanup_dry_run,
        )
    else:
        print("Cleanup skipped by flag.")

    generated_files = [
        output_dir / "snapshot_report.md",
        output_dir / "snapshot_summary.csv",
        output_dir / "snapshot_duplicates.csv",
        summary_path,
    ]

    _write_summary(
        summary_path,
        db_path=db_path,
        analysis=analysis,
        cleanup_results=cleanup_results,
        cleanup_dry_run=args.cleanup_dry_run,
        generated_files=generated_files,
    )

    print(f"Summary written to: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
