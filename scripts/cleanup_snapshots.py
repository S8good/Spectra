import argparse
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".nanosense", "nanosense_data.db")

TIMESTAMP_FORMATS: Tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)


@dataclass
class CleanupCandidate:
    record_id: int
    timestamp: Optional[str]
    fingerprint: Optional[str]


@dataclass
class CleanupStats:
    candidates: List[CleanupCandidate]
    updated_count: int
    table_exists: bool = True


def parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        for fmt in TIMESTAMP_FORMATS:
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return None


def normalize_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    query = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?"
    return conn.execute(query, (table,)).fetchone() is not None


def fetch_reference_counts(conn: sqlite3.Connection, queries: Iterable[str]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for query in queries:
        for row in conn.execute(query):
            key = row["ref_id"]
            if key is None:
                continue
            counts[key] = counts.get(key, 0) + row["ref_count"]
    return counts


def find_cleanup_candidates(
    conn: sqlite3.Connection,
    table: str,
    id_column: str,
    timestamp_column: str,
    fingerprint_column: Optional[str],
    reference_queries: Iterable[str],
    window_start: Optional[datetime],
    latest_allowed: Optional[datetime],
) -> List[CleanupCandidate]:
    ref_counts = fetch_reference_counts(conn, reference_queries)

    sql = f"""
        SELECT {id_column} AS record_id, {timestamp_column} AS ts,
               {fingerprint_column if fingerprint_column else 'NULL'} AS fp
        FROM {table}
        WHERE is_active = 1
    """

    cursor = conn.execute(sql)
    candidates: List[CleanupCandidate] = []
    for row in cursor.fetchall():
        record_id = row["record_id"]
        if ref_counts.get(record_id, 0) > 0:
            continue
        ts_value = row["ts"]
        parsed_ts = parse_timestamp(ts_value)
        if parsed_ts:
            if window_start and parsed_ts < window_start:
                continue
            if latest_allowed and parsed_ts > latest_allowed:
                continue
        elif window_start or latest_allowed:
            # Skip records with unknown timestamp when a window is enforced.
            continue

        candidates.append(
            CleanupCandidate(
                record_id=record_id,
                timestamp=ts_value,
                fingerprint=row["fp"] if fingerprint_column else None,
            )
        )
    return candidates


def apply_updates(
    conn: sqlite3.Connection,
    table: str,
    id_column: str,
    candidates: List[CleanupCandidate],
    dry_run: bool,
) -> int:
    if dry_run or not candidates:
        return 0
    ids = [candidate.record_id for candidate in candidates]
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"UPDATE {table} SET is_active = 0 WHERE {id_column} IN ({placeholders})",
        ids,
    )
    return len(ids)


def format_candidates(candidates: List[CleanupCandidate]) -> str:
    lines = []
    for candidate in candidates:
        line = f"- ID {candidate.record_id}"
        if candidate.timestamp:
            line += f", timestamp={candidate.timestamp}"
        if candidate.fingerprint:
            line += f", fingerprint={candidate.fingerprint}"
        lines.append(line)
    return "\n".join(lines) if lines else "(none)"


def perform_cleanup(
    db_path: str,
    *,
    tables: Optional[Sequence[str]] = None,
    age_days: Optional[int] = 180,
    window_start: Optional[datetime] = None,
    latest_allowed: Optional[datetime] = None,
    dry_run: bool = False,
) -> Dict[str, CleanupStats]:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    valid_tables = ("instrument_states", "processing_snapshots")
    if tables:
        invalid = sorted(set(tables) - set(valid_tables))
        if invalid:
            raise ValueError(f"Unsupported table(s): {', '.join(invalid)}")
        selection: List[str] = list(dict.fromkeys(tables))
    else:
        selection = list(valid_tables)

    latest_allowed = normalize_naive(latest_allowed)
    window_start = normalize_naive(window_start)
    if latest_allowed is None and age_days is not None:
        latest_allowed = normalize_naive(datetime.now(timezone.utc) - timedelta(days=age_days))
    if window_start and latest_allowed and window_start > latest_allowed:
        raise ValueError("window_start must not be later than the cutoff/window end")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    results: Dict[str, CleanupStats] = {}

    try:
        if "instrument_states" in selection:
            if table_exists(conn, "instrument_states"):
                instrument_candidates = find_cleanup_candidates(
                    conn,
                    table="instrument_states",
                    id_column="instrument_state_id",
                    timestamp_column="captured_at",
                    fingerprint_column=None,
                    reference_queries=[
                        """
                        SELECT instrument_state_id AS ref_id, COUNT(*) AS ref_count
                        FROM spectrum_sets
                        WHERE instrument_state_id IS NOT NULL
                        GROUP BY instrument_state_id
                        """
                    ],
                    window_start=window_start,
                    latest_allowed=latest_allowed,
                )
                updated = apply_updates(
                    conn,
                    table="instrument_states",
                    id_column="instrument_state_id",
                    candidates=instrument_candidates,
                    dry_run=dry_run,
                )
                results["instrument_states"] = CleanupStats(
                    candidates=instrument_candidates,
                    updated_count=updated,
                )
            else:
                results["instrument_states"] = CleanupStats([], 0, table_exists=False)

        if "processing_snapshots" in selection:
            if table_exists(conn, "processing_snapshots"):
                snapshot_candidates = find_cleanup_candidates(
                    conn,
                    table="processing_snapshots",
                    id_column="processing_config_id",
                    timestamp_column="created_at",
                    fingerprint_column=None,
                    reference_queries=[
                        """
                        SELECT processing_config_id AS ref_id, COUNT(*) AS ref_count
                        FROM spectrum_sets
                        WHERE processing_config_id IS NOT NULL
                        GROUP BY processing_config_id
                        """,
                        """
                        SELECT processing_config_id AS ref_id, COUNT(*) AS ref_count
                        FROM experiments
                        WHERE processing_config_id IS NOT NULL
                        GROUP BY processing_config_id
                        """,
                    ],
                    window_start=window_start,
                    latest_allowed=latest_allowed,
                )
                updated = apply_updates(
                    conn,
                    table="processing_snapshots",
                    id_column="processing_config_id",
                    candidates=snapshot_candidates,
                    dry_run=dry_run,
                )
                results["processing_snapshots"] = CleanupStats(
                    candidates=snapshot_candidates,
                    updated_count=updated,
                )
            else:
                results["processing_snapshots"] = CleanupStats([], 0, table_exists=False)

        if not dry_run:
            conn.commit()
        return results
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deactivate unused instrument/process snapshots by setting is_active = 0."
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default=DEFAULT_DB_PATH,
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--age-days",
        "--days",
        dest="age_days",
        type=int,
        default=180,
        help="Minimum age (in days) required before deactivation.",
    )
    parser.add_argument(
        "--before",
        dest="before_date",
        help="Deactivate records created before this ISO timestamp (overrides --age-days).",
    )
    parser.add_argument(
        "--utc-window-start",
        dest="window_start",
        help="Optional ISO timestamp; only records newer than or equal to this value are considered.",
    )
    parser.add_argument(
        "--utc-window-end",
        dest="window_end",
        help="Optional ISO timestamp; overrides cutoff/latest allowed timestamp.",
    )
    parser.add_argument(
        "--table",
        dest="tables",
        action="append",
        choices=("instrument_states", "processing_snapshots"),
        help="Limit cleanup to specific tables (can be specified multiple times).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Only report candidates without writing changes.",
    )

    args = parser.parse_args(argv)

    before_dt = parse_timestamp(args.before_date) if args.before_date else None
    window_start_dt = parse_timestamp(args.window_start) if args.window_start else None
    window_end_dt = parse_timestamp(args.window_end) if args.window_end else None
    latest_allowed = window_end_dt or before_dt

    try:
        results = perform_cleanup(
            args.db_path,
            tables=args.tables,
            age_days=args.age_days,
            window_start=window_start_dt,
            latest_allowed=latest_allowed,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))

    cutoff_label = (
        (latest_allowed or normalize_naive(datetime.now(timezone.utc) - timedelta(days=args.age_days))).isoformat()
        if args.age_days is not None
        else (latest_allowed.isoformat() if latest_allowed else "N/A")
    )
    print(f"Cutoff timestamp: {cutoff_label}")
    print(f"Dry-run mode: {'ON' if args.dry_run else 'OFF'}")
    for table, stats in results.items():
        if not stats.table_exists:
            print(f"\n[{table}] table not found; skipping.")
            continue
        print(f"\n[{table}] candidates: {len(stats.candidates)}, updated: {stats.updated_count}")
        print(format_candidates(stats.candidates))

    return 0


__all__ = ["CleanupCandidate", "CleanupStats", "perform_cleanup"]


if __name__ == "__main__":
    raise SystemExit(main())
