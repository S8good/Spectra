# Phase 1 Data Migration Plan

本文档针对现有 SQLite 数据库的历史数据，给出迁移到阶段 1 新结构的详细步骤。设计依据 `docs/数据库升级阶段1设计.md`。

## 1. 总体流程

1. **准备阶段**
   - 校验源数据库：`PRAGMA integrity_check; PRAGMA foreign_key_check;`
   - 统计基础数据量：实验数、光谱数、分析结果数，为迁移后对比做 baseline。
   - 将源库备份（文件复制 + 关键表导出 JSON/CSV）。

2. **构建新结构**
   - 执行 `0001_schema_ddl.sql` 中的 DDL（或对应的迁移脚本）。
   - 确保 `schema_migrations` 已记录 `0001_prepare_phase1_schema`。

3. **数据搬运**
   - **实验与项目**：补全时间戳、状态、版本；挂接默认 `batch_run_id`（NULL）与 `sample_id`（NULL）。
   - **光谱拆分**：将 `spectra` 中的 JSON 拆为 `spectrum_sets + spectrum_data`，保留 `legacy_spectrum_id`。
   - **分析结果**：将 `analysis_results` JSON 拆分为 `analysis_runs + analysis_metrics`。
   - **附属信息**：创建默认 `processing_snapshots`、`instrument_states` 记录，填充引用字段。

4. **校验与回滚点**
   - 对比记录数、哈希、关键指标，生成迁移报告。
   - 出现异常可回滚到备份文件。

## 2. 迁移细节

### 2.1 Projects / Experiments

- 新增列填充规则：
  | 列 | 填充值 |
  | --- | --- |
  | `projects.status` | 默认 `'active'` |
  | `projects.owner_user_id` | NULL（后续人工指定） |
  | `projects.metadata_json` | `NULL` 或根据业务填充 |
  | `experiments.status` | `'completed'`（如 `timestamp` 早于当前）；未完成实验可根据业务规则判断 |
  | `experiments.created_at` | 若有 `timestamp`，取 `timestamp`; 否则 `datetime('now')` |
  | `experiments.updated_at` | 等同 `created_at` |
  | `experiments.processing_config_id` | 指向默认快照 ID（见下） |

- 为每个实验生成 `experiment_versions` 版本 1：
  ```sql
  INSERT INTO experiment_versions (experiment_id, version_no, snapshot_json, created_at)
  VALUES (?, 1, json_object('legacy', 1), datetime('now'));
  ```
  后续可在脚本中替换 `snapshot_json` 为包含旧字段的 JSON。

### 2.2 Processing Snapshots & Instrument States

- 建立一个默认快照记录：
  ```sql
  INSERT INTO processing_snapshots (name, version, parameters_json, created_at)
  VALUES ('legacy_default', '1.0', json_object('source', 'pre-phase1'), datetime('now'));
  ```
  获取其 `processing_config_id`，用于所有旧实验引用。

- 对于 `instrument_states`，可选策略：
  1. 统一创建单条 `legacy_unknown` 记录，所有光谱引用同一 ID；
  2. 若旧配置可解析（如 config_snapshot），解析后写入多条记录。

### 2.3 Spectrum 拆分

1. **分组逻辑**：
   - 以 `(experiment_id, timestamp)` 为 key，将同一时间的多条 `spectra` 记录视为一次保存事件。
   - 对于 `Result_*` 类型，拆分 `Result` 与 `variant`。
   - ✅ 已在 `migration_0001_prepare_phase1_schema.py` 中实现逐行迁移逻辑（`capture_label` 等同原 `type`，`Result_*` 自动拆分为 `Result` + `variant`）。

2. **数据写入顺序**：
   1. 将 `wavelengths` 字符串解析为数组，写入 `spectrum_data`（序列化为 NPY/BLOB，或保持 JSON -> BLOB）。
   2. 创建 `spectrum_sets` 记录，填充 `capture_label`、`spectrum_role`、`result_variant`、`captured_at`。
   3. 更新原 `spectra` 表：写入 `spectrum_set_id`、`data_id`、`quality_flag`。

3. **哈希与验证**：
   - 计算 `hash = SHA256(wavelengths_blob || intensities_blob)`；迁移前后 hash 应一致。
   - 若数据点数量不一致需记录告警。
   - 兼容实现中使用 `storage_format='json'`，等待后续引入更高效的 NPY/HDF5 方案。

### 2.4 Analysis 数据拆分

1. **映射表**（示例）：
   | `analysis_type` | 指标映射 | 备注 |
   | --- | --- | --- |
   | `Affinity_KD` | `KD`, `R_max`, `r_squared`, 可选 `n` | 保存单位 nm、无量纲 |
   | `Calibration` | `slope`, `intercept`, `r_squared`, `lod`, `loq` | 单位写入 |
   | `Sensitivity` | `LOD`, `LOQ`, `R_squared` | ... |
   | 其他 | 将 JSON 全量存入 `analysis_metrics` (`metric_key='payload'`) 供后续处理 |

2. **迁移步骤**：
   - 为每条 `analysis_results` 创建 `analysis_runs`：
     ```
     INSERT INTO analysis_runs (..., analysis_type, algorithm_version, started_at, finished_at, input_context)
     ```
     `algorithm_version` 可置 `'legacy'`，`input_context` 包含原 `source_spectrum_ids`。
   - 将 `result_data` JSON 解包为多个 `analysis_metrics`。
   - 更新 `analysis_results.analysis_run_id`，保留旧数据以兼容旧 UI。
   - ✅ 已在 `migration_0001_prepare_phase1_schema.py` 实现自动迁移：支持 Affinity/Calibration 等类型字段映射，解析失败时会以 `raw_payload` 形式记录，并回填 `analysis_results.analysis_run_id`。

### 2.5 附件与标签

- 当前迁移无需马上生成附件、标签，保留为空。
- 若旧数据包含文件路径，可写入 `attachments` 并挂接 `entity_type='experiment'` 等。

### 2.6 审计与日志

- 迁移过程中，为重要操作写入 `audit_logs`：
  ```
  INSERT INTO audit_logs (entity_type, entity_id, action, payload_json)
  VALUES ('migration', experiment_id, 'phase1_backfill', json_object(...));
  ```

## 3. 验证方案

1. **数量对比**：原表与新表记录数量对齐（如 `spectra` 的行数 == 新增 `spectrum_sets` 行数）。
2. **哈希校验**：随机抽样比对迁移前后光谱 hash。
3. **业务冒烟**：
   - 使用旧 UI 导出实验，验证视图/兼容层可正常读取。
   - 通过 `scripts/migrate_db.py --dry-run` 确认无待迁移项。
4. **报告**：
   - 输出 JSON/Markdown，总结迁移耗时、处理数量、告警列表。

## 6. 兼容视图

- `legacy_spectrum_sets_view`：基于 `spectrum_sets` + `spectrum_data` 输出 Legacy 结构需要的字段（`type/timestamp/wavelengths/intensities`），供旧逻辑读取。
- `legacy_analysis_runs_view`：将 `analysis_runs` 与 `analysis_metrics` 拼接为行式数据，方便聚合为旧版 `analysis_results` 的 JSON。
- `DatabaseManager.get_full_experiment_data` 会优先读取上述视图，若不存在或无数据则回退到旧表，确保兼容未迁移的历史版本。
- 可通过 `sqlite3 <db> "SELECT COUNT(*) FROM legacy_spectrum_sets_view"` 验证视图是否已创建并填充。

## 7. 验证脚本（计划）

- `scripts/validate_migration.py`（待实现）主要检查：
  1. 关键表/视图是否存在，核心列是否齐全。
  2. `spectra` vs `spectrum_sets` 记录数与数据哈希抽样对比。
  3. `analysis_results` 是否全部关联到 `analysis_runs`，并输出缺失列表。
  4. 兼容视图行数统计、采样展示前后数据对照。
- 脚本需生成终端汇总报告，失败时返回非零退出码，便于 CI 集成。

## 4. 回滚机制

- 所有迁移操作封装在事务中，遇到异常 `ROLLBACK`。
- 迁移成功后仍保留原 SQLite 文件，以便快速恢复。
- 若需要降级，可删除新增表（或恢复备份）并移除 `schema_migrations` 中新增记录。

## 5. 后续优化

- 在 Phase 2 中将 `analysis_results` 替换为视图，确保新数据全部写入结构化表。
- 迁移脚本可拆分为多个步骤（结构、数据、视图），便于调试与重试。
