import argparse
import csv
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from nanosense.core.snapshot_utils import (
    canonicalize_instrument_info,
    canonicalize_processing_info,
    compute_fingerprint,
    serialize_payload,
)
DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".nanosense", "nanosense_data.db")


def parse_json_blob(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    query = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?"
    return conn.execute(query, (table_name,)).fetchone() is not None


def fetch_reference_counts(conn: sqlite3.Connection, queries: List[str]) -> Dict[int, int]:
    counts: Dict[int, int] = defaultdict(int)
    for query in queries:
        for row in conn.execute(query):
            ref_id = row["ref_id"]
            if ref_id is None:
                continue
            counts[ref_id] += row["ref_count"]
    return counts


def analyze_instrument_states(conn: sqlite3.Connection, top_n: int) -> Optional[Dict[str, Any]]:
    if not table_exists(conn, "instrument_states"):
        return None

    rows = conn.execute(
        """
        SELECT instrument_state_id, device_serial, integration_time_ms, averaging,
               temperature, config_json, captured_at
        FROM instrument_states
        """
    ).fetchall()

    ref_counts = fetch_reference_counts(
        conn,
        [
            """
            SELECT instrument_state_id AS ref_id, COUNT(*) AS ref_count
            FROM spectrum_sets
            WHERE instrument_state_id IS NOT NULL
            GROUP BY instrument_state_id
            """
        ],
    )

    fingerprint_map: Dict[str, Dict[str, Any]] = {}
    referenced_ids = set()
    timestamps: List[str] = []

    for row in rows:
        state_id = row["instrument_state_id"]
        payload = canonicalize_instrument_info(
            {
                "device_serial": row["device_serial"],
                "integration_time_ms": row["integration_time_ms"],
                "averaging": row["averaging"],
                "temperature": row["temperature"],
                "config": parse_json_blob(row["config_json"]),
            }
        )
        fingerprint = compute_fingerprint(payload)
        ref_count = ref_counts.get(state_id, 0)

        entry = fingerprint_map.setdefault(
            fingerprint,
            {
                "count": 0,
                "record_ids": [],
                "reference_count": 0,
                "representative": payload,
                "first_timestamp": None,
                "last_timestamp": None,
            },
        )

        entry["count"] += 1
        entry["record_ids"].append(state_id)
        entry["reference_count"] += ref_count

        captured_at = row["captured_at"]
        if captured_at:
            timestamps.append(captured_at)
            if not entry["first_timestamp"] or captured_at < entry["first_timestamp"]:
                entry["first_timestamp"] = captured_at
            if not entry["last_timestamp"] or captured_at > entry["last_timestamp"]:
                entry["last_timestamp"] = captured_at

        if ref_count > 0:
            referenced_ids.add(state_id)

    total_records = len(rows)
    unique_fingerprints = len(fingerprint_map)
    duplicate_records = total_records - unique_fingerprints
    duplicate_ratio = (duplicate_records / total_records) if total_records else 0.0
    referenced_records = len(referenced_ids)
    unreferenced_records = total_records - referenced_records
    date_range = (
        min(timestamps) if timestamps else None,
        max(timestamps) if timestamps else None,
    )

    duplicates = sorted(
        (fp, data) for fp, data in fingerprint_map.items() if data["count"] > 1
    )
    duplicates.sort(key=lambda item: item[1]["count"], reverse=True)
    top_duplicates = [
        {
            "fingerprint": fingerprint,
            "count": data["count"],
            "record_ids": data["record_ids"],
            "reference_count": data["reference_count"],
            "representative": data["representative"],
            "first_timestamp": data["first_timestamp"],
            "last_timestamp": data["last_timestamp"],
        }
        for fingerprint, data in duplicates[:top_n]
    ]

    return {
        "table": "instrument_states",
        "total_records": total_records,
        "unique_fingerprints": unique_fingerprints,
        "duplicate_records": duplicate_records,
        "duplicate_ratio": duplicate_ratio,
        "referenced_records": referenced_records,
        "unreferenced_records": unreferenced_records,
        "date_range": date_range,
        "top_duplicates": top_duplicates,
    }


def analyze_processing_snapshots(conn: sqlite3.Connection, top_n: int) -> Optional[Dict[str, Any]]:
    if not table_exists(conn, "processing_snapshots"):
        return None

    rows = conn.execute(
        """
        SELECT processing_config_id, name, version, parameters_json, created_by, created_at
        FROM processing_snapshots
        """
    ).fetchall()

    ref_counts = fetch_reference_counts(
        conn,
        [
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
    )

    fingerprint_map: Dict[str, Dict[str, Any]] = {}
    referenced_ids = set()
    timestamps: List[str] = []

    for row in rows:
        config_id = row["processing_config_id"]
        parameters_raw = parse_json_blob(row["parameters_json"])
        processing_info: Dict[str, Any] = {
            "name": row["name"],
            "version": row["version"],
        }
        if isinstance(parameters_raw, dict):
            processing_info.update(parameters_raw)
        elif parameters_raw is not None:
            processing_info["payload"] = parameters_raw
        payload = canonicalize_processing_info(processing_info)
        fingerprint = compute_fingerprint(payload)
        ref_count = ref_counts.get(config_id, 0)

        entry = fingerprint_map.setdefault(
            fingerprint,
            {
                "count": 0,
                "record_ids": [],
                "reference_count": 0,
                "representative": {
                    "name": row["name"],
                    "version": row["version"],
                    "created_by": row["created_by"],
                    "parameters": payload.get("parameters"),
                },
                "first_timestamp": None,
                "last_timestamp": None,
            },
        )

        entry["count"] += 1
        entry["record_ids"].append(config_id)
        entry["reference_count"] += ref_count

        created_at = row["created_at"]
        if created_at:
            timestamps.append(created_at)
            if not entry["first_timestamp"] or created_at < entry["first_timestamp"]:
                entry["first_timestamp"] = created_at
            if not entry["last_timestamp"] or created_at > entry["last_timestamp"]:
                entry["last_timestamp"] = created_at

        if ref_count > 0:
            referenced_ids.add(config_id)

    total_records = len(rows)
    unique_fingerprints = len(fingerprint_map)
    duplicate_records = total_records - unique_fingerprints
    duplicate_ratio = (duplicate_records / total_records) if total_records else 0.0
    referenced_records = len(referenced_ids)
    unreferenced_records = total_records - referenced_records
    date_range = (
        min(timestamps) if timestamps else None,
        max(timestamps) if timestamps else None,
    )

    duplicates = sorted(
        (fp, data) for fp, data in fingerprint_map.items() if data["count"] > 1
    )
    duplicates.sort(key=lambda item: item[1]["count"], reverse=True)
    top_duplicates = [
        {
            "fingerprint": fingerprint,
            "count": data["count"],
            "record_ids": data["record_ids"],
            "reference_count": data["reference_count"],
            "representative": data["representative"],
            "first_timestamp": data["first_timestamp"],
            "last_timestamp": data["last_timestamp"],
        }
        for fingerprint, data in duplicates[:top_n]
    ]

    return {
        "table": "processing_snapshots",
        "total_records": total_records,
        "unique_fingerprints": unique_fingerprints,
        "duplicate_records": duplicate_records,
        "duplicate_ratio": duplicate_ratio,
        "referenced_records": referenced_records,
        "unreferenced_records": unreferenced_records,
        "date_range": date_range,
        "top_duplicates": top_duplicates,
    }


def write_markdown_report(analysis: Dict[str, Dict[str, Any]], output_path: str) -> None:
    lines: List[str] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"# Snapshot Governance Report ({timestamp})")
    lines.append("")

    name_map = {
        "instrument_states": "Instrument States (instrument_states)",
        "processing_snapshots": "Processing Snapshots (processing_snapshots)",
    }

    for table, stats in analysis.items():
        title = name_map.get(table, table)
        lines.append(f"## {title}")
        if not stats:
            lines.append("Table not present in database.")
            lines.append("")
            continue

        date_range = stats["date_range"]
        if date_range[0] and date_range[1]:
            date_range_str = f"{date_range[0]} -> {date_range[1]}"
        else:
            date_range_str = "N/A"

        lines.append("| Metric | Value |")
        lines.append("| --- | --- |")
        lines.append(f"| Total records | {stats['total_records']} |")
        lines.append(f"| Unique fingerprints | {stats['unique_fingerprints']} |")
        lines.append(f"| Duplicate records | {stats['duplicate_records']} |")
        lines.append(f"| Duplicate ratio | {stats['duplicate_ratio']:.2%} |")
        lines.append(f"| Referenced records | {stats['referenced_records']} |")
        lines.append(f"| Unreferenced records | {stats['unreferenced_records']} |")
        lines.append(f"| Time range | {date_range_str} |")
        lines.append("")

        duplicates = stats["top_duplicates"]
        if duplicates:
            lines.append(f"### Duplicate fingerprints Top {len(duplicates)}")
            lines.append("| Fingerprint | Records | References | Record IDs | Representative | Time range |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for dup in duplicates:
                record_ids = ", ".join(str(rid) for rid in dup['record_ids'])
                representative = serialize_payload({k: v for k, v in dup['representative'].items() if v is not None})
                if dup['first_timestamp'] and dup['last_timestamp']:
                    timerange = f"{dup['first_timestamp']} -> {dup['last_timestamp']}"
                else:
                    timerange = "N/A"
                lines.append(
                    f"| `{dup['fingerprint']}` | {dup['count']} | {dup['reference_count']} | "
                    f"{record_ids} | `{representative}` | {timerange} |"
                )
            lines.append("")

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

def write_csv_reports(analysis: Dict[str, Dict[str, Any]], output_dir: str) -> None:
    summary_path = os.path.join(output_dir, "snapshot_summary.csv")
    duplicates_path = os.path.join(output_dir, "snapshot_duplicates.csv")

    with open(summary_path, "w", newline="", encoding="utf-8") as summary_file:
        writer = csv.writer(summary_file)
        writer.writerow(["table", "metric", "value"])
        for table, stats in analysis.items():
            if not stats:
                writer.writerow([table, "status", "table missing"])
                continue
            writer.writerow([table, "total_records", stats["total_records"]])
            writer.writerow([table, "unique_fingerprints", stats["unique_fingerprints"]])
            writer.writerow([table, "duplicate_records", stats["duplicate_records"]])
            writer.writerow([table, "duplicate_ratio", f"{stats['duplicate_ratio']:.4f}"])
            writer.writerow([table, "referenced_records", stats["referenced_records"]])
            writer.writerow([table, "unreferenced_records", stats["unreferenced_records"]])
            range_label = (
                f"{stats['date_range'][0]} -> {stats['date_range'][1]}"
                if stats["date_range"][0] and stats["date_range"][1]
                else ""
            )
            writer.writerow([table, "date_range", range_label])

    with open(duplicates_path, "w", newline="", encoding="utf-8") as duplicates_file:
        writer = csv.writer(duplicates_file)
        writer.writerow(
            [
                "table",
                "fingerprint",
                "count",
                "reference_count",
                "record_ids",
                "representative",
                "first_timestamp",
                "last_timestamp",
            ]
        )
        for table, stats in analysis.items():
            if not stats:
                continue
            for dup in stats["top_duplicates"]:
                writer.writerow(
                    [
                        table,
                        dup["fingerprint"],
                        dup["count"],
                        dup["reference_count"],
                        ";".join(str(rid) for rid in dup["record_ids"]),
                        serialize_payload(
                            {k: v for k, v in dup["representative"].items() if v is not None}
                        ),
                        dup["first_timestamp"] or "",
                        dup["last_timestamp"] or "",
                    ]
                )


def ensure_output_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate statistics for instrument_states and processing_snapshots tables."
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default=DEFAULT_DB_PATH,
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=os.path.join("docs", "reports"),
        help="Directory to store generated reports.",
    )
    parser.add_argument(
        "--top",
        dest="top_n",
        type=int,
        default=10,
        help="Number of duplicate fingerprints to include per table.",
    )

    args = parser.parse_args()

    if not os.path.exists(args.db_path):
        raise SystemExit(f"Database file not found: {args.db_path}")

    ensure_output_dir(args.output_dir)

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row

    try:
        analysis: Dict[str, Optional[Dict[str, Any]]] = {
            "instrument_states": analyze_instrument_states(conn, args.top_n),
            "processing_snapshots": analyze_processing_snapshots(conn, args.top_n),
        }

        markdown_path = os.path.join(args.output_dir, "snapshot_report.md")
        write_markdown_report(analysis, markdown_path)
        write_csv_reports(analysis, args.output_dir)

        print(f"Markdown report written to: {markdown_path}")
        print(f"CSV summaries written to: {args.output_dir}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
