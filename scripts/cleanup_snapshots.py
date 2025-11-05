import argparse
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

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
    cutoff: datetime,
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
        if parsed_ts and parsed_ts > cutoff:
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


def main() -> None:
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
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Only report candidates without writing changes.",
    )

    args = parser.parse_args()

    if not os.path.exists(args.db_path):
        raise SystemExit(f"Database file not found: {args.db_path}")

    if args.before_date:
        cutoff = parse_timestamp(args.before_date)
        if cutoff is None:
            raise SystemExit(f"Invalid --before timestamp: {args.before_date}")
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.age_days)

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row

    try:
        summary: Dict[str, Dict[str, object]] = {}

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
                cutoff=cutoff,
            )
            updated = apply_updates(
                conn,
                table="instrument_states",
                id_column="instrument_state_id",
                candidates=instrument_candidates,
                dry_run=args.dry_run,
            )
            summary["instrument_states"] = {
                "candidate_count": len(instrument_candidates),
                "updated_count": updated,
                "details": format_candidates(instrument_candidates),
            }

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
                cutoff=cutoff,
            )
            updated = apply_updates(
                conn,
                table="processing_snapshots",
                id_column="processing_config_id",
                candidates=snapshot_candidates,
                dry_run=args.dry_run,
            )
            summary["processing_snapshots"] = {
                "candidate_count": len(snapshot_candidates),
                "updated_count": updated,
                "details": format_candidates(snapshot_candidates),
            }

        if not args.dry_run:
            conn.commit()

        cutoff_label = args.before_date or cutoff.isoformat()
        print(f"Cutoff timestamp: {cutoff_label}")
        print(f"Dry-run mode: {'ON' if args.dry_run else 'OFF'}")
        for table, info in summary.items():
            print(f"\n[{table}] candidates: {info['candidate_count']}, updated: {info['updated_count']}")
            print(info["details"])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
