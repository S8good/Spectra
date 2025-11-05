#!/usr/bin/env python3
"""
Phase 1 migration验证脚本。

该脚本用于检查 SQLite 数据库是否满足 Phase 1 架构要求，并提供可选的报告、历史记录与
抽样输出功能。核心检查包括：

1. 必要表 / 视图 / 列是否存在；
2. legacy 视图与旧表数据量是否一致；
3. analysis_results 是否全部关联 analysis_runs；
4. （可选）光谱写入延迟、批量运行状态等治理指标。

示例：
    python scripts/validate_migration.py --db data/nanosense_data.db --max-latency 600 --batch-status
    python scripts/validate_migration.py --db data/nanosense_data.db --report-file docs/reports/validation_summary.txt
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from nanosense.utils.config_manager import load_settings  # type: ignore
except ImportError:  # pragma: no cover - 可选依赖
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

REQUIRED_VIEWS = {"legacy_spectrum_sets_view", "legacy_analysis_runs_view"}

REQUIRED_COLUMNS = {
    "spectra": {"spectrum_set_id", "data_id", "quality_flag"},
    "analysis_results": {"analysis_run_id"},
}

TIMESTAMP_FORMATS: Tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
)


def resolve_db_path(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    if load_settings:
        try:
            settings = load_settings()
            candidate = settings.get("database_path")
            if candidate:
                return Path(candidate).expanduser().resolve()
        except Exception:  # pragma: no cover - 容错
            pass
    raise ValueError("未指定数据库路径，请使用 --db 或在配置文件中设置 database_path。")


def fetch_set(conn: sqlite3.Connection, query: str) -> set[str]:
    cursor = conn.execute(query)
    return {row[0] for row in cursor.fetchall()}


def check_tables(conn: sqlite3.Connection) -> List[str]:
    tables = fetch_set(conn, "SELECT name FROM sqlite_master WHERE type='table'")
    return sorted(REQUIRED_TABLES - tables)


def check_views(conn: sqlite3.Connection) -> List[str]:
    views = fetch_set(conn, "SELECT name FROM sqlite_master WHERE type='view'")
    return sorted(REQUIRED_VIEWS - views)


def check_columns(conn: sqlite3.Connection, table: str, required: Iterable[str]) -> List[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    return sorted(set(required) - existing)


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
    value = cursor.fetchone()
    return int(value[0]) if value else 0


def sample_rows(
    conn: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    limit: int,
    random_order: bool = False,
) -> List[Tuple]:
    cols = ", ".join(columns)
    order_clause = "ORDER BY RANDOM()" if random_order else ""
    cursor = conn.execute(f"SELECT {cols} FROM {table} {order_clause} LIMIT ?", (limit,))
    return cursor.fetchall()


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def check_latency(conn: sqlite3.Connection, threshold: timedelta) -> List[Tuple[int, float, str, str]]:
    """返回超过阈值的 (spectrum_set_id, latency_seconds, captured_at, created_at)。"""
    cursor = conn.execute(
        """
        SELECT spectrum_set_id, captured_at, created_at
        FROM spectrum_sets
        WHERE captured_at IS NOT NULL AND created_at IS NOT NULL
        """
    )
    offenders: List[Tuple[int, float, str, str]] = []
    for spectrum_set_id, captured_at, created_at in cursor.fetchall():
        start = parse_timestamp(captured_at)
        end = parse_timestamp(created_at)
        if not start or not end:
            continue
        latency = (end - start).total_seconds()
        if latency > threshold.total_seconds():
            offenders.append((spectrum_set_id, latency, captured_at, created_at))
    return offenders


def check_batch_status(conn: sqlite3.Connection) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    """
    返回：
        - 已完成但仍有未完成明细的批次列表 (batch_run_id, open_items)
        - 进行中但没有未完成明细的批次列表 (batch_run_id, total_items)
    """
    completed_with_open: List[Tuple[int, int]] = []
    stalled_runs: List[Tuple[int, int]] = []

    cursor = conn.execute(
        """
        SELECT br.batch_run_id,
               SUM(CASE WHEN bri.status IN ('pending', 'in_progress') THEN 1 ELSE 0 END) AS open_items
        FROM batch_runs br
        JOIN batch_run_items bri ON bri.batch_run_id = br.batch_run_id
        GROUP BY br.batch_run_id
        HAVING br.status = 'completed' AND open_items > 0
        """
    )
    completed_with_open.extend((row[0], row[1]) for row in cursor.fetchall())

    cursor = conn.execute(
        """
        SELECT br.batch_run_id,
               COUNT(*) AS total_items,
               SUM(CASE WHEN bri.status IN ('pending', 'in_progress') THEN 1 ELSE 0 END) AS open_items
        FROM batch_runs br
        JOIN batch_run_items bri ON bri.batch_run_id = br.batch_run_id
        GROUP BY br.batch_run_id
        HAVING br.status IN ('in_progress', 'running') AND open_items = 0
        """
    )
    for batch_run_id, total_items, _ in cursor.fetchall():
        stalled_runs.append((batch_run_id, total_items))

    return completed_with_open, stalled_runs


def write_report(report_path: Path, errors: List[str], warnings: List[str], strict: bool) -> datetime:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC)
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write(f"Timestamp: {timestamp.isoformat()}\n")
        if errors:
            handle.write("\n[ERROR]\n")
            for item in errors:
                handle.write(f"- {item}\n")
        if warnings:
            handle.write("\n[WARN]\n")
            for item in warnings:
                handle.write(f"- {item}\n")
        if not errors and not warnings:
            handle.write("\n[OK] Validation completed.\n")
        if strict and warnings:
            handle.write("\n[STRICT] Warnings treated as failures.\n")
    return timestamp


def append_history(
    history_path: Path,
    timestamp: datetime,
    errors: List[str],
    warnings: List[str],
    exit_code: int,
) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not history_path.exists()
    with history_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(["timestamp", "errors", "warnings", "exit_code"])
        writer.writerow([timestamp.isoformat(), len(errors), len(warnings), exit_code])


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 1 migration state.")
    parser.add_argument("--db", dest="db_path", help="SQLite 数据库文件路径（默认读取配置文件）。")
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=0.0,
        help="随机抽样比例（0~1），用于打印 spectrum_sets / analysis_runs 的示例数据。",
    )
    parser.add_argument(
        "--max-latency",
        type=int,
        default=None,
        help="光谱写入允许的最大延迟（秒），超出将计入警告。",
    )
    parser.add_argument(
        "--batch-status",
        action="store_true",
        help="启用批量运行状态一致性检查。",
    )
    parser.add_argument(
        "--report-file",
        type=str,
        help="（可选）输出 Markdown/文本报告路径。",
    )
    parser.add_argument(
        "--history-file",
        type=str,
        help="（可选）将结果追加到 CSV 历史记录文件。",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="将警告视为失败（exit code = 1）。",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        db_path = resolve_db_path(args.db_path)
    except ValueError as exc:  # pragma: no cover - argparse 已处理
        parser.error(str(exc))
        return 2

    if not db_path.exists():
        parser.error(f"数据库文件不存在：{db_path}")
        return 2

    conn = sqlite3.connect(db_path)

    errors: List[str] = []
    warnings: List[str] = []

    missing_tables = check_tables(conn)
    if missing_tables:
        errors.append(f"缺少表：{', '.join(missing_tables)}")

    missing_views = check_views(conn)
    if missing_views:
        errors.append(f"缺少视图：{', '.join(missing_views)}")

    for table, required in REQUIRED_COLUMNS.items():
        missing_cols = check_columns(conn, table, required)
        if missing_cols:
            errors.append(f"{table} 缺少列：{', '.join(missing_cols)}")

    try:
        legacy_count = count_rows(conn, "legacy_spectrum_sets_view")
        spectra_count = count_rows(conn, "spectra")
        if legacy_count != spectra_count:
            warnings.append(
                f"legacy_spectrum_sets_view 数量 {legacy_count} 与 spectra {spectra_count} 不一致"
            )
    except sqlite3.OperationalError:
        warnings.append("无法读取 legacy_spectrum_sets_view，视图可能缺失。")

    try:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM analysis_results WHERE analysis_run_id IS NULL"
        )
        missing_links = cursor.fetchone()[0]
        if missing_links:
            errors.append(f"{missing_links} 条 analysis_results 未关联到 analysis_runs。")
    except sqlite3.OperationalError:
        warnings.append("无法检查 analysis_results 关联，表或列可能缺失。")

    # 抽样输出
    sample_rate = max(0.0, min(args.sample_rate, 1.0))
    if sample_rate > 0:
        try:
            total = count_rows(conn, "spectrum_sets")
            limit = max(1, min(int(total * sample_rate), 10))
            print(f"\n[SAMPLE] spectrum_sets (limit={limit})")
            for row in sample_rows(
                conn,
                "spectrum_sets",
                ["spectrum_set_id", "experiment_id", "capture_label", "captured_at"],
                limit=limit,
                random_order=True,
            ):
                print("  ", row)
        except sqlite3.OperationalError:
            print("[SAMPLE] 无法抽样 spectrum_sets。")

        try:
            total = count_rows(conn, "analysis_runs")
            limit = max(1, min(int(total * sample_rate), 10))
            print(f"\n[SAMPLE] analysis_runs (limit={limit})")
            for row in sample_rows(
                conn,
                "analysis_runs",
                ["analysis_run_id", "experiment_id", "analysis_type", "started_at"],
                limit=limit,
                random_order=True,
            ):
                print("  ", row)
        except sqlite3.OperationalError:
            print("[SAMPLE] 无法抽样 analysis_runs。")

    # 延迟检查
    if args.max_latency and args.max_latency > 0:
        offenders = check_latency(conn, timedelta(seconds=args.max_latency))
        if offenders:
            warnings.append(
                f"{len(offenders)} 条 spectrum_sets 超过延迟阈值（>{args.max_latency}s）"
            )
            print("\n[WARN] Latency offenders (前 5 项)：")
            for spectrum_set_id, latency, captured_at, created_at in offenders[:5]:
                print(
                    f"  spectrum_set_id={spectrum_set_id}, latency={latency:.1f}s, "
                    f"captured_at={captured_at}, created_at={created_at}"
                )

    # 批量状态检查
    if args.batch_status:
        completed_with_open, stalled_runs = check_batch_status(conn)
        if completed_with_open:
            warnings.append(
                f"{len(completed_with_open)} 个已完成批次仍存在未完成的孔位"
            )
            print("\n[WARN] Completed batches with open items：")
            for batch_run_id, open_items in completed_with_open[:10]:
                print(f"  batch_run_id={batch_run_id}, open_items={open_items}")
        if stalled_runs:
            warnings.append(
                f"{len(stalled_runs)} 个进行中批次没有未完成孔位（可能卡住）"
            )
            print("\n[WARN] In-progress batches without open items：")
            for batch_run_id, total_items in stalled_runs[:10]:
                print(f"  batch_run_id={batch_run_id}, total_items={total_items}")

    conn.close()

    exit_code = 0
    if errors:
        print("\n[ERROR] Validation failed:")
        for item in errors:
            print(" -", item)
        exit_code = 1

    if warnings:
        print("\n[WARN] Validation warnings:")
        for item in warnings:
            print(" -", item)
        if args.strict:
            print("\n[STRICT] Warnings treated as failures.")
            exit_code = 1

    if exit_code == 0:
        print("\n[OK] Validation completed.")

    # 报告与历史记录
    report_timestamp = datetime.now(UTC)
    if args.report_file:
        report_timestamp = write_report(Path(args.report_file), errors, warnings, args.strict)
    if args.history_file:
        append_history(Path(args.history_file), report_timestamp, errors, warnings, exit_code)

    return exit_code


__all__ = [
    "check_tables",
    "check_views",
    "check_columns",
    "check_latency",
    "check_batch_status",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())

