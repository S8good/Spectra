# 批量采集数据库迁移进度追踪（2025-10-31）

## 已完成
1. **阶段一结构迁移**：迁移脚本 `migration_0001_prepare_phase1_schema` 创建 `spectrum_sets/spectrum_data`、`analysis_runs/analysis_metrics`、`batch_runs/batch_run_items` 等结构，并为旧表补充兼容列。
2. **实时采集写入重构**：`DatabaseManager.save_spectrum/save_analysis_result` 同步写入结构化表与旧表，GUI 流程已切换至新 API。
3. **批量采集落库**：`BatchAcquisitionWorker` 与批次汇总逻辑写入批次/孔位明细和背景/参考/信号/结果光谱。
4. **验证工具**：新增 `scripts/validate_migration.py` 及 `docs/migrations/phase1/0001_data_migration_plan.md`，覆盖结构校验与排错指引。
5. **CLI 导入链路**：`scripts/import_spectra.py` 支持 Excel/CSV/TXT 导入，同时记录项目、实验及谱线元数据。
6. **仪器与处理元数据写入**：`DatabaseManager.save_spectrum` 支持 `instrument_info`/`processing_info`，`MeasurementWidget`、`BatchAcquisitionWorker`、CLI 导入都已落盘对应快照。
7. **GUI 导入持久化**：单谱、三文件、文件夹、多列文件等导入流程会自动创建“Imported Data”实验并写入结构化表，保留来源路径与参数。

## 待处理
1. **仪器/处理快照治理**：制定快照去重、清理与报表方案，补齐历史数据，方便审计与追踪。
2. **数据库浏览 UI 增强**：扩展 `DatabaseExplorerDialog` 等界面，支持查看批次、孔位、结构化谱线及其元数据。
3. **自动化验证扩展**：为 `validate_migration.py` 增加性能指标、批次状态、一致性抽检，并规划 CI 集成。
4. **Legacy 表归档策略**：明确旧表只读/归档流程，完善备份、回滚、应急演练指导。
5. **批量流程后续计划**：排期自动化采集整合、状态追踪写入、UI 打磨、验证增强等后续特性。

_最近更新：2025-10-31 by Codex_
