#!/usr/bin/env python3
"""
Convenience wrapper for scheduling migration validation runs.

Example:
    python scripts/run_validation_report.py --sample-rate 0.1 --batch-status --strict
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_SCRIPT = REPO_ROOT / "scripts" / "validate_migration.py"
DEFAULT_DB = REPO_ROOT / "data" / "nanosense_data.db"
DEFAULT_REPORT = REPO_ROOT / "docs" / "reports" / "validation_summary.txt"
DEFAULT_HISTORY = REPO_ROOT / "docs" / "reports" / "validation_history.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the migration validation script with standard repo defaults."
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help="SQLite 数据库路径（默认：data/nanosense_data.db）。",
    )
    parser.add_argument(
        "--report-file",
        default=str(DEFAULT_REPORT),
        help="验证摘要输出路径（默认：docs/reports/validation_summary.txt）。",
    )
    parser.add_argument(
        "--history-file",
        default=str(DEFAULT_HISTORY),
        help="验证历史 CSV 路径（默认：docs/reports/validation_history.csv）。",
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=0.05,
        help="抽样比例，范围 (0, 1]（默认：0.05）。",
    )
    parser.add_argument(
        "--max-latency",
        type=float,
        default=None,
        help="允许的 captured_at 与 created_at 最大延迟（秒），未设置则跳过。",
    )
    parser.add_argument(
        "--batch-status",
        action="store_true",
        help="启用批量任务与明细状态一致性检查。",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="开启严格模式，将警告视为失败。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = [
        sys.executable,
        str(VALIDATION_SCRIPT),
        "--db",
        args.db,
        "--report-file",
        args.report_file,
        "--history-file",
        args.history_file,
        "--sample-rate",
        str(args.sample_rate),
    ]

    if args.max_latency is not None:
        command.extend(["--max-latency", str(args.max_latency)])
    if args.batch_status:
        command.append("--batch-status")
    if args.strict:
        command.append("--strict")

    result = subprocess.run(command, text=True)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
