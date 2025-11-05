# 迁移治理作业排期（生效日期：2025-11-04）

为确保批量采集数据库迁移后的结构化数据持续稳定，现制定如下治理与验证节奏，可在周会或值班排班中落地执行。

## 周期性快照治理
- **每周一 10:00**：运行 `python scripts/report_snapshots.py --db data/nanosense_data.db --top-duplicates 20 --output-dir docs/reports/`，生成最新的指纹重复度、引用关系与时间分布报表，并在团队站会上通报异常。
- **每周三 14:00**：根据报表结果执行 `python scripts/cleanup_snapshots.py --db data/nanosense_data.db --table instrument_states --days 90 --dry-run` 预览治理范围；确认后去掉 `--dry-run` 执行正式清理，必要时附带 `--utc-window-start/--utc-window-end` 控制时间窗口。
- **每周五 16:00**：复核 `docs/reports/snapshot_summary.csv` 与 `docs/reports/snapshot_duplicates.csv` 的差异曲线，记录在周报中；若发现连续两周重复率上升，立即安排额外快照采集优化。

## Legacy 表只读与回填演练
- **每月第二个周二 15:00**：按照 `docs/operations/legacy_tables.md` 章节执行只读切换演练，使用沙箱库验证备份与回滚脚本可用性。
- **每季度首月第一周**：补齐 `legacy_unknown` 实验的历史仪器 / 处理数据，完成后执行一次全面迁移校验（见下节），并将结果存档至 `docs/reports/legacy_backfill_*.md`。
- 演练结束后一小时内，需归档 CLI 输出与数据库变更摘要，确保审计留档齐备。

## 迁移验证脚本调用节奏
- **每晚 02:00（可由任务计划程序触发）**：运行 `python scripts/run_validation_report.py --sample-rate 0.05 --batch-status --strict`。默认输出覆盖 `docs/reports/validation_summary.txt` 并追加 `docs/reports/validation_history.csv`。
- **每次执行结构迁移、批量导入或快照清理之后**：手动重跑 `scripts/run_validation_report.py` 以捕捉即时状态，结果需在对应工单中备注。
- 如验证脚本返回非零退出码，需在 24 小时内定位原因并追加备注，再次运行直至通过。

> 提示：若在异地环境运行，请提前设置 `PYTHONPATH` 指向项目根目录，或在虚拟环境中执行，以便脚本正确导入 `nanosense` 模块。
