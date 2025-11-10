# 迁移治理作业排期（生效日期：2025-11-04）

为确保批量采集数据库迁移后的结构化数据持续稳定，制定如下治理与验证节奏。可结合周会或值班排班表执行，并将输出沉淀到 `docs/reports/` 目录。

> **CI 自动执行**：GitHub Actions 工作流 `Snapshot & Legacy Governance`（`.github/workflows/governance.yml`）已配置为每天 02:00 UTC 运行，自动生成 Demo 库的快照治理摘要与 Legacy 冻结报告，并上传为构建工件，便于远程审阅。

## 周期性快照治理
- **每周一 10:00**：运行  
  ```bash
  python scripts/run_snapshot_governance.py --db data/nanosense_data.db --top-duplicates 20 --cleanup-dry-run
  ```  
  生成最新的指纹重复度、引用关系与预估清理范围，同时在站会上通报 `snapshot_governance_*.md` 中的异常。
- **每周三 14:00**：依据周一的摘要确认窗口后，执行  
  ```bash
  python scripts/run_snapshot_governance.py --db data/nanosense_data.db --cleanup-window-start <start> --cleanup-window-end <end>
  ```  
  去掉 `--cleanup-dry-run` 以正式清理，同时保留 `snapshot_report.md` 与 CSV 差异。
- **每周五 16:00**：复盘 `snapshot_summary.csv`、`snapshot_duplicates.csv` 以及当周的 `snapshot_governance_*.md`，如重复率连续两周上升，立即安排额外快照/配置优化任务。

## Legacy 表只读与回填演练
- **每月第二个周三 15:00**：按照 `docs/operations/legacy_tables.md` 执行只读切换演练，推荐命令：  
  ```bash
  python scripts/legacy_freeze.py --db data/nanosense_data.db --freeze-after 2025-10-01 --backup-dir backups --export-csv-dir docs/reports/exports
  ```  
  生成数据库备份、Legacy CSV 导出以及 `legacy_freeze_<timestamp>.md` 审计记录。
- **每季度首月第一周**：在沙箱库运行 `python scripts/legacy_freeze.py --db <db> --freeze-after <ts> --backfill-missing --strict`，补齐 `legacy_unknown` 实验的历史仪器 / 处理数据，并把报告归档到 `docs/reports/legacy_backfill_*.md`。
- 演练结束后一小时内，需归档脚本输出、数据库变更摘要与人工确认情况，保证审计留档齐备。

## 迁移验证脚本调用节奏
- **每日 02:00（任务计划程序）**：运行  
  ```bash
  python scripts/run_validation_report.py --sample-rate 0.05 --batch-status --strict
  ```  
  默认覆盖 `docs/reports/validation_summary.txt` 并追记 `docs/reports/validation_history.csv`。
- **每次执行结构迁移、批量导入或快照清理之后**：手动重复 `scripts/run_validation_report.py` 以捕捉即时状态，并在对应工单中记录 `validation_summary.txt` 节选。
- 若验证脚本返回非零退出码，需在 24 小时内定位原因、追加备注，并再次运行直至通过。

> 提示：在异地或 CI 环境运行上述脚本前，请确保 `PYTHONPATH` 指向项目根目录或在虚拟环境中执行，以便脚本正确导入 `nanosense` 模块。
