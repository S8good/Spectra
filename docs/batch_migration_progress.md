# 批量采集数据库迁移进度追踪（更新日期：2025-11-04）

## 已完成工作
1. **阶段一结构迁移**：通过 `migration_0001_prepare_phase1_schema` 创建 `spectrum_sets/spectrum_data`、`analysis_runs/analysis_metrics`、`batch_runs/batch_run_items` 等核心结构化表，并为传统表补充兼容列。
2. **实时入库重构**：`DatabaseManager.save_spectrum/save_analysis_result` 同步写入新旧结构，GUI 与脚本均已切换至新接口。
3. **批量采集落库**：批量任务可写入批次头、孔位明细、背景参数、信号与结果光谱信息。
4. **迁移校验工具**：提供 `scripts/validate_migration.py` 与 `docs/migrations/phase1/0001_data_migration_plan.md`，覆盖结构校验和排错路径。
5. **导入链路完善**：`scripts/import_spectra.py` 支持 Excel/CSV/TXT 导入并记录项目、实验、光谱元数据。
6. **仪器 / 处理元数据补录**：GUI、批量任务与 CLI 导入均会落盘仪器状态和处理配置快照。
7. **GUI 导入固化**：所有导入流程自动创建 “Imported Data” 实验，写入结构化表并保留来源元数据。
8. **快照软删除与治理工具**：已执行 `migration_0002_snapshot_soft_delete`，`instrument_states`/`processing_snapshots` 引入 `is_active` 标记并补齐历史数据。
9. **快照报表与清理脚本**：`scripts/report_snapshots.py`、`scripts/cleanup_snapshots.py` 与 `nanosense/core/snapshot_utils.py` 支持重复指纹统计、软删除窗口清理及指纹复用；最新报表已输出至 `docs/reports/`。
10. **数据访问与演示基建**：`nanosense/core/data_access.py`、`tests/test_data_access.py`、`docs/ui/database_explorer_demo.md`、`scripts/generate_demo_database.py` 为数据库浏览器提供查询聚合与示例数据。
11. **Legacy 操作手册**：`docs/operations/legacy_tables.md` 明确只读切换、备份回滚、审计流程与脚本准备。
12. **数据库浏览器增强（阶段一）**：界面新增实验状态/操作员筛选、查询耗时提示与 CSV 导出，并补充“实验详情 / 光谱集合 / 批次概览”标签页自动联动展示；最新版本引入 QtConcurrent + QFutureWatcher 异步加载机制并为批次概览增加状态/孔位过滤器，避免查询/详情阻塞同时提升大板位定位效率，相关逻辑已同步更新 `nanosense/gui/database_explorer.py`、`nanosense/core/data_access.py`、`nanosense/core/database_manager.py`。
13. **治理自动化脚本补齐**：新增 `scripts/run_snapshot_governance.py`（一键生成快照报表、可选清理与 Markdown 摘要）以及 `scripts/legacy_freeze.py`（备份、回填、冻结报告），并在 `tests/test_legacy_freeze.py` 覆盖关键校验逻辑。

## 待处理事项
1. **仪器 / 处理快照治理迭代**：在 `run_snapshot_governance.py` 的基础上补充趋势分析、CI 告警与审批记录沉淀，确保历史数据可审计。
2. **数据库浏览器优化（后续）**：收集用户反馈、完善批次/孔位筛选、缓存策略与更多导出模板。
3. **验证自动化拓展**：补充单元测试、CI 集成与长期指标监控，持续评估迁移质量。
4. **Legacy 表冻结执行**：以 `legacy_freeze.py` 为入口结合 SOP 推进只读切换、备份演练与回填验收，持续保障旧表治理落地。
5. **批量流程后续路线**：规划批量任务自动化整合、状态追踪与 UI 打磨。

## 推进计划

### 快照治理迭代
- 使用 `python scripts/run_snapshot_governance.py --db <db> [--skip-cleanup]` 统一生成报表、Markdown 摘要与可选清理结果。
- 在脚本输出的 `snapshot_governance_*.md` 中追加趋势数据，结合 `docs/reports/` 差异形成周报。
- 扩展重复指纹告警到 CI，结合 `is_active` 标记生成治理待办，并保留审批记录。
- 设计趋势图生成脚本，辅助分析快照增长与清理效果。

### Legacy 表只读与回填
- 以 `python scripts/legacy_freeze.py --freeze-after <ts> --backup-dir <dir>` 执行只读切换演练、备份与 CSV 导出，并产出 `legacy_freeze_*.md` 审计记录。
- 使用脚本 `--backfill-missing` 选项补齐 `legacy_unknown` 实验的仪器 / 处理数据，确保兼容视图一致。
- 结合脚本输出与 `scripts/validate_migration.py` 制定回填后的数据验收流程，锁定异常并在工单中备案。

### 数据库浏览器 UI
- 收集演示版与真实用户反馈，针对层级导航与懒加载进行优化。
- 增强批次/孔位筛选、导出及缓存策略，降低重复查询成本。
- 评估与 `ExplorerDataAccess` 的接口扩展，满足更多业务检索场景。

### 迁移验证自动化
- 定期运行 `scripts/validate_migration.py`，并使用 `--report-file`、`--history-file` 持续沉淀指标。
- 在 `.github/workflows/validation.yml` 中加入趋势汇总与附件上传，方便回溯。
- 结合抽样参数（`--sample-rate`、`--max-latency`、`--batch-status`）规划不同阶段的校验策略。
