#!/usr/bin/env python3
"""Generate validation trend plots from validation_history.csv."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

try:
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover
    plt = None


def read_history(path: Path) -> List[Tuple[datetime, int, int, int]]:
    records: List[Tuple[datetime, int, int, int]] = []
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                ts = datetime.fromisoformat(row["timestamp"])
                errors = int(row["errors"])
                warnings = int(row["warnings"])
                exit_code = int(row["exit_code"])
            except (KeyError, ValueError):
                continue
            records.append((ts, errors, warnings, exit_code))
    return records


def plot_trends(records: List[Tuple[datetime, int, int, int]], output: Path) -> None:
    if plt is None:
        raise SystemExit("matplotlib is required to generate trend plots (pip install matplotlib)")
    if not records:
        raise SystemExit("No records available in history file")

    records.sort(key=lambda item: item[0])
    timestamps = [rec[0] for rec in records]
    errors = [rec[1] for rec in records]
    warnings = [rec[2] for rec in records]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(timestamps, errors, marker="o", label="Errors")
    ax.plot(timestamps, warnings, marker="o", label="Warnings")
    ax.set_title("Migration Validation Trends")
    ax.set_xlabel("Timestamp")
    ax.set_ylabel("Count")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend()
    fig.autofmt_xdate()

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot validation trend chart from history CSV.")
    parser.add_argument(
        "--history",
        default="docs/reports/validation_history.csv",
        help="Path to validation history CSV (default: docs/reports/validation_history.csv).",
    )
    parser.add_argument(
        "--output",
        default="docs/reports/validation_trends.png",
        help="Output image path (default: docs/reports/validation_trends.png).",
    )
    args = parser.parse_args()

    history_path = Path(args.history).expanduser().resolve()
    if not history_path.exists():
        raise SystemExit(f"History file not found: {history_path}")

    records = read_history(history_path)
    output_path = Path(args.output).expanduser().resolve()
    plot_trends(records, output_path)
    print(f"Trend chart saved to: {output_path}")


if __name__ == "__main__":
    main()
