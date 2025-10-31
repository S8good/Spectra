#!/usr/bin/env python
"""
Standalone migration runner for the nanosense SQLite database.

Usage:
    python scripts/migrate_db.py --db path/to/database.db
    python scripts/migrate_db.py --dry-run  # list pending migrations only
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nanosense.core.migration_runner import get_pending_migrations, run_migrations  # noqa: E402

try:
    from nanosense.utils.config_manager import load_settings  # noqa: E402
except ImportError:  # pragma: no cover - optional dependency during early bootstrap
    load_settings = None  # type: ignore


def _resolve_db_path(explicit_path: Optional[str]) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    if load_settings:
        try:
            settings = load_settings()
            candidate = settings.get("database_path")
            if candidate:
                return Path(candidate).expanduser().resolve()
        except Exception:
            pass
    raise ValueError("无法确定数据库路径，请通过 --db 指定或在配置中设置 database_path。")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run pending database migrations.")
    parser.add_argument(
        "--db",
        dest="db_path",
        help="SQLite 数据库文件路径（默认读取配置文件中的 database_path）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列出待执行迁移，不实际修改数据库。",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="安静模式，仅输出必要信息。",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        db_path = _resolve_db_path(args.db_path)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    if not db_path.exists():
        parser.error(f"数据库文件不存在：{db_path}")
        return 2

    conn = sqlite3.connect(db_path)

    def _log(message: str) -> None:
        if not args.quiet:
            print(message)

    if args.dry_run:
        pending = get_pending_migrations(conn)
        if not pending:
            _log("No pending migrations. Schema is up to date.")
            return 0
        _log("Pending migrations:")
        for migration_id, _ in pending:
            _log(f"  - {migration_id}")
        return 0

    run_migrations(conn, logger=_log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
