# Legacy Tables Freeze & Backfill SOP

## Scope
- 针对 Phase 1 迁移后仍保留的旧表：`spectra`、`analysis_results`、（如存在）其他 legacy 兼容视图所依赖的原始表。
- 目标：在确保业务读操作可用的前提下，完成只读切换、备份归档、历史元数据补齐及软删除治理。

## 1. 准备检查
- 确认核心脚本已更新到最新版本：
  - `scripts/report_snapshots.py`
  - `scripts/cleanup_snapshots.py`
  - `scripts/migrate_db.py`
- 运行迁移检查（干跑即可）：
  ```bash
  python scripts/migrate_db.py --db <path-to-db> --dry-run
  ```
- 生成最新快照报表，作为冻结前的基线：
  ```bash
  python scripts/report_snapshots.py --db <path-to-db> --output-dir docs/reports
  ```

## 2. 维护窗口申请
- 约定 30~60 分钟窗口，通知采集/分析业务暂停写入。
- 保障人员：一名应用维护 + 一名数据库/运维。

## 3. 备份策略
- 制作完整文件备份（推荐 zip + 时间戳）：
  ```powershell
  Copy-Item <path-to-db> "<backup-dir>/nanosense_data_<yyyymmddHHMM>.db"
  ```
- 导出关键表 CSV/JSON（供快速 diff）：
  ```bash
  sqlite3 <path-to-db> -csv "SELECT * FROM spectra" > backups/spectra_<timestamp>.csv
  sqlite3 <path-to-db> -csv "SELECT * FROM analysis_results" > backups/analysis_results_<timestamp>.csv
  ```
- 记录备份位置于 `docs/reports/backup_inventory.md`（若首次需创建）。

## 4. 只读切换流程
1. 重启应用前端/采集服务，确保新的写入逻辑指向结构化表（确认 `DatabaseManager` 版本 >= snapshot reuse 变更）。
2. 通过迁移脚本确保 Schema 最新：
   ```bash
   python scripts/migrate_db.py --db <path-to-db>
   ```
3. 将旧表权限设为只读（SQLite 可通过应用层约束）：
   - 在数据访问层加入写操作屏蔽；若使用 CLI 手动操作，需提醒禁止直接 `INSERT/UPDATE`。
4. 运行软删除治理（先干跑，再执行）：
   ```bash
   python scripts/cleanup_snapshots.py --db <path-to-db> --dry-run
   python scripts/cleanup_snapshots.py --db <path-to-db>
   ```
5. 回写审计日志（示例 SQL）：
   ```sql
   INSERT INTO audit_logs (entity_type, entity_id, action, payload_json)
   VALUES ('migration', 0, 'legacy_freeze', json_object('timestamp', datetime('now')));
   ```

## 5. 历史元数据回填
- 目标：为旧实验补齐 `instrument_states` / `processing_snapshots` 引用，减少 `legacy_unknown` 占比。
- 步骤建议：
  1. 收集历史仪器配置原始资料（日志、配置文件）。
  2. 批处理脚本（待开发）：扫描旧 `spectra`/`analysis_results` JSON，提取可识别参数组合，统一插入结构化快照。
  3. 对无法自动匹配的实验，导出人工处理清单（CSV），并在完成后将 `is_active` 标记恢复。
- 填充完成后再次运行 `report_snapshots.py` 以确认快照去重效果。

## 6. 验证清单
- `scripts/validate_migration.py --db <path-to-db> --strict`（待新版实现）。
- UI 冒烟：在 Database Explorer 中确认结构化视图可读，Legacy 视图保持查询但无新增写入。
- 对比备份与现状（随机抽样 5~10 条）确保数据一致。

## 7. 回滚预案
- 若出现严重问题：停止新数据写入 → 使用备份数据库文件覆盖 → 重新运行迁移脚本 → 恢复采集/分析服务。
- 记录回滚原因、影响范围与处理人，并更新本 SOP。

## 8. 操作记录模板
- 建议维护 `docs/reports/legacy_freeze_log.md`（或工单系统），记录：
  - 操作时间、责任人
  - 备份位置
  - 执行的命令及摘要
  - 验证结果
  - 遇到的问题及解决方案

---

> 后续计划：Phase 2 将考虑将 `analysis_results` 重构为只读视图，并在界面/脚本层全面切换至结构化数据源。
