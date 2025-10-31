# 数据库结构概览（带中文说明）

> 数据库文件：`C:/Users/Spc/.nanosense/nanosense_data.db`  
> 以下按照 **表（Tables）→ 视图（Views）→ 索引（Indexes）** 的顺序列出主要结构，并对用途做中文说明。

---

## 表（Tables）

### analysis_artifacts
> 存放分析运行生成的附件（图像、报告、原始输出文件等），用于追溯分析成果。
```sql
CREATE TABLE analysis_artifacts (
            artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_run_id INTEGER REFERENCES analysis_runs(analysis_run_id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL,
            file_path TEXT,
            data_blob BLOB,
            mime_type TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            description TEXT
        )
```

### analysis_metrics
> 存储单次分析运行产出的结构化指标（如 KD、R²、LOD 等），`metric_key` / `metric_value` 为键值对。
```sql
CREATE TABLE analysis_metrics (
            analysis_run_id INTEGER REFERENCES analysis_runs(analysis_run_id) ON DELETE CASCADE,
            metric_key TEXT NOT NULL,
            metric_value TEXT,
            unit TEXT,
            is_primary INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (analysis_run_id, metric_key)
        )
```

### analysis_results
> 旧版分析结果表，保存 JSON 格式的结果及来源光谱 ID；迁移后 `analysis_run_id` 指向新结构以兼容历史数据。
```sql
CREATE TABLE analysis_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER,
                analysis_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                result_data TEXT,
                source_spectrum_ids TEXT, analysis_run_id INTEGER REFERENCES analysis_runs(analysis_run_id),
                FOREIGN KEY (experiment_id) REFERENCES experiments (experiment_id)
            )
```

### analysis_runs
> 新的分析运行主表，每次算法执行都会记录类型、时间、算法版本及输入上下文，可追溯到实验或批量孔位。
```sql
CREATE TABLE analysis_runs (
            analysis_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER REFERENCES experiments(experiment_id) ON DELETE CASCADE,
            batch_run_item_id INTEGER REFERENCES batch_run_items(item_id) ON DELETE SET NULL,
            analysis_type TEXT NOT NULL,
            algorithm_version TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            initiated_by INTEGER REFERENCES users(user_id),
            input_context TEXT,
            UNIQUE (experiment_id, analysis_type, started_at)
        )
```

### attachments
> 通用附件表，可关联任意实体（实验、批次、分析等）并描述文件信息、哈希、上传者等。
```sql
CREATE TABLE attachments (
            attachment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            file_path TEXT,
            file_hash TEXT,
            mime_type TEXT,
            size_bytes INTEGER,
            uploaded_by INTEGER REFERENCES users(user_id),
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
```

### audit_logs
> 操作审计日志，记录实体类型、动作、执行者及 payload，用于排查关键操作。
```sql
CREATE TABLE audit_logs (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor_id INTEGER REFERENCES users(user_id),
            payload_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
```

### batch_run_items
> 批量采集明细表，每个孔位/采集点对应一条记录；包含计划阶段、实际阶段、关联实验、采集次数等信息。
```sql
CREATE TABLE batch_run_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_run_id INTEGER NOT NULL REFERENCES batch_runs(batch_run_id) ON DELETE CASCADE,
            position_label TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            sample_id INTEGER REFERENCES samples(sample_id),
            planned_stage TEXT,
            actual_stage TEXT,
            experiment_id INTEGER REFERENCES experiments(experiment_id) ON DELETE SET NULL,
            capture_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            last_captured_at TEXT,
            metadata_json TEXT,
            UNIQUE (batch_run_id, position_label, planned_stage)
        )
```

### batch_runs
> 批量采集主表，记录批次名称、关联项目、布局 JSON、操作员及状态（进行中、完成、失败等）。
```sql
CREATE TABLE batch_runs (
            batch_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(project_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            layout_reference TEXT,
            operator TEXT,
            instrument_config_id INTEGER,
            start_time TEXT,
            end_time TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT
        )
```

### entity_tags
> 多实体标签关联表，实现多对多标签体系（tag -> 实体类型/ID）。
```sql
CREATE TABLE entity_tags (
            tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            applied_by INTEGER REFERENCES users(user_id),
            applied_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (tag_id, entity_type, entity_id)
        )
```

### experiment_versions
> 实验版本快照，记录每次实验元数据的完整 JSON，用于版本对比与回溯。
```sql
CREATE TABLE experiment_versions (
            experiment_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
            version_no INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_by INTEGER REFERENCES users(user_id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            diff_summary TEXT,
            UNIQUE (experiment_id, version_no)
        )
```

### experiments
> 实验主表，记录单次实验的元数据（名称、类型、时间、操作人、配置快照等）；迁移后新增批次/样品/状态等字段。
```sql
CREATE TABLE experiments (
                experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                name TEXT NOT NULL,
                type TEXT,
                timestamp TEXT NOT NULL,
                operator TEXT,
                notes TEXT,
                config_snapshot TEXT,
                FOREIGN KEY (project_id) REFERENCES projects (project_id)
            );

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                name TEXT NOT NULL,
                type TEXT,
                timestamp TEXT NOT NULL,
                operator TEXT,
                notes TEXT,
                config_snapshot TEXT,
                FOREIGN KEY (project_id) REFERENCES projects (project_id)
            );
            """)
```

### instrument_states
> 记录仪器状态快照（序列号、积分时间、温度等），可在单次/批量采集中引用，用于还原采集条件。
```sql
CREATE TABLE instrument_states (
            instrument_state_id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_serial TEXT,
            integration_time_ms REAL,
            averaging INTEGER,
            temperature REAL,
            config_json TEXT,
            captured_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
```

### processing_snapshots
> 数据处理配置快照，保存算法参数、预处理设置等，分析运行或采集时可引用。
```sql
CREATE TABLE processing_snapshots (
            processing_config_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            version TEXT,
            parameters_json TEXT NOT NULL,
            created_by INTEGER REFERENCES users(user_id),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
```

### projects
> 项目主表，用于组织实验；新增 `status`、`owner_user_id`、`metadata_json` 支持归档与扩展属性。
```sql
CREATE TABLE projects (
                project_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                creation_date TEXT NOT NULL
            , status TEXT NOT NULL DEFAULT 'active', owner_user_id INTEGER REFERENCES users(user_id), metadata_json TEXT)
```

### samples
> 样品主表，记录浓度、来源等，用于批量采集或分析。
```sql
CREATE TABLE samples (
            sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(project_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            external_id TEXT,
            type TEXT,
            concentration REAL,
            concentration_unit TEXT,
            source TEXT,
            storage_conditions TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT
        )
```

### schema_migrations
> 记录已执行的迁移 ID 与时间，实现 schema 版本控制。
```sql
CREATE TABLE schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
```

### spectra
> 保留旧格式的光谱表，存储原始 Signal/Background 等 JSON 数据；迁移后新增 `spectrum_set_id`、`data_id` 等字段指向新结构。
```sql
CREATE TABLE spectra (
                spectrum_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER,
                type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                wavelengths TEXT,
                intensities TEXT, spectrum_set_id INTEGER REFERENCES spectrum_sets(spectrum_set_id), data_id INTEGER REFERENCES spectrum_data(data_id), quality_flag TEXT DEFAULT 'good', created_at TEXT,
                FOREIGN KEY (experiment_id) REFERENCES experiments (experiment_id)
            )
```

### spectrum_data
> 新的光谱数据表，以 BLOB 方式存储波长/强度数组，可支持多格式（json/npz 等）。
```sql
CREATE TABLE spectrum_data (
            data_id INTEGER PRIMARY KEY AUTOINCREMENT,
            wavelengths_blob BLOB NOT NULL,
            intensities_blob BLOB NOT NULL,
            points_count INTEGER NOT NULL,
            hash TEXT,
            storage_format TEXT NOT NULL DEFAULT 'npy',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
```

### spectrum_sets
> 光谱集合表，描述一次保存事件；包含捕获标签、角色、变体、关联的数据 ID 及批次明细。
```sql
CREATE TABLE spectrum_sets (
            spectrum_set_id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER REFERENCES experiments(experiment_id) ON DELETE CASCADE,
            batch_run_item_id INTEGER REFERENCES batch_run_items(item_id) ON DELETE SET NULL,
            capture_label TEXT NOT NULL,
            spectrum_role TEXT,
            result_variant TEXT,
            data_id INTEGER NOT NULL REFERENCES spectrum_data(data_id) ON DELETE CASCADE,
            instrument_state_id INTEGER REFERENCES instrument_states(instrument_state_id),
            processing_config_id INTEGER REFERENCES processing_snapshots(processing_config_id),
            captured_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            region_start_nm REAL,
            region_end_nm REAL,
            note TEXT,
            quality_flag TEXT DEFAULT 'good'
        )
```

### tags
> 标签字典表，定义可供实体使用的标签及颜色。
```sql
CREATE TABLE tags (
            tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT,
            description TEXT
        )
```

### user_preferences
> 用户偏好设置（界面语言、默认路径等），与 `users` 关联。
```sql
CREATE TABLE user_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            preferences_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
```

### user_roles
> 用户与角色的关联表，实现权限体系。
```sql
CREATE TABLE user_roles (
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            role_id INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
            assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, role_id)
        )
```

### users
> 用户主表，存储账户信息、状态与创建时间。
```sql
CREATE TABLE users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT,
            email TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT
        )
```

---

## 视图（Views）

### legacy_analysis_runs_view
> 兼容旧版分析结果的视图，将分析运行与指标行式展开，便于转换回传统结构。
```sql
CREATE VIEW legacy_analysis_runs_view AS
            SELECT
                ar.analysis_run_id,
                ar.experiment_id,
                ar.analysis_type,
                ar.started_at AS timestamp,
                am.metric_key,
                am.metric_value,
                am.unit,
                ar.input_context
            FROM analysis_runs ar
            LEFT JOIN analysis_metrics am ON am.analysis_run_id = ar.analysis_run_id
```

### legacy_spectrum_sets_view
> 兼容旧版 `spectra` 的视图，将 `spectrum_sets + spectrum_data` 展开成旧格式字段。
```sql
CREATE VIEW legacy_spectrum_sets_view AS
            SELECT
                ss.spectrum_set_id,
                ss.experiment_id,
                CASE
                    WHEN ss.spectrum_role = 'Result' AND ss.result_variant IS NOT NULL
                        THEN 'Result_' || ss.result_variant
                    ELSE COALESCE(ss.capture_label, ss.spectrum_role, 'Unknown')
                END AS type,
                ss.captured_at AS timestamp,
                CASE WHEN sd.storage_format = 'json' THEN CAST(sd.wavelengths_blob AS TEXT) ELSE NULL END AS wavelengths,
                CASE WHEN sd.storage_format = 'json' THEN CAST(sd.intensities_blob AS TEXT) ELSE NULL END AS intensities,
                sd.storage_format
            FROM spectrum_sets ss
            JOIN spectrum_data sd ON sd.data_id = ss.data_id
```

---

## 索引（Indexes）

- **idx_analysis_runs_started** -> 表: analysis_runs  
  用于按开始时间检索分析运行。
  ```sql
CREATE INDEX idx_analysis_runs_started ON analysis_runs(started_at)
  ```
- **idx_analysis_runs_type** -> 表: analysis_runs  
  支持按分析类型快速筛选。
  ```sql
CREATE INDEX idx_analysis_runs_type ON analysis_runs(analysis_type)
  ```
- **idx_attachments_entity** -> 表: attachments  
  加速实体与附件的关联查询。
  ```sql
CREATE INDEX idx_attachments_entity ON attachments(entity_type, entity_id)
  ```
- **idx_audit_logs_action** / **idx_audit_logs_entity** -> 表: audit_logs  
  支持按动作或实体查询审计日志。
  ```sql
CREATE INDEX idx_audit_logs_action ON audit_logs(action)
  ```
  ```sql
CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_type, entity_id)
  ```
- **idx_batch_run_items_batch** / **idx_batch_run_items_experiment** -> 表: batch_run_items  
  分别用于按批次或实验 ID 检索批量明细。
  ```sql
CREATE INDEX idx_batch_run_items_batch ON batch_run_items(batch_run_id)
  ```
  ```sql
CREATE INDEX idx_batch_run_items_experiment ON batch_run_items(experiment_id)
  ```
- **idx_batch_runs_project** / **idx_batch_runs_status** -> 表: batch_runs  
  支持按项目或状态检索批量任务。
  ```sql
CREATE INDEX idx_batch_runs_project ON batch_runs(project_id)
  ```
  ```sql
CREATE INDEX idx_batch_runs_status ON batch_runs(status)
  ```
- **idx_entity_tags_entity** -> 表: entity_tags  
  加速实体标签关联查询。
  ```sql
CREATE INDEX idx_entity_tags_entity ON entity_tags(entity_type, entity_id)
  ```
- **idx_experiments_status** / **idx_experiments_timestamp** -> 表: experiments  
  常用筛选条件（状态、时间）的辅助索引。
  ```sql
CREATE INDEX idx_experiments_status ON experiments(status)
  ```
  ```sql
CREATE INDEX idx_experiments_timestamp ON experiments(timestamp)
  ```
- **idx_samples_external_id** / **idx_samples_project** -> 表: samples  
  支持按外部编号或项目检索样品。
  ```sql
CREATE INDEX idx_samples_external_id ON samples(external_id)
  ```
  ```sql
CREATE INDEX idx_samples_project ON samples(project_id)
  ```
- **idx_spectra_experiment** / **idx_spectra_set** -> 表: spectra  
  旧表上的辅助索引，便于按实验或 `spectrum_set_id` 查询。
  ```sql
CREATE INDEX idx_spectra_experiment ON spectra(experiment_id)
  ```
  ```sql
CREATE INDEX idx_spectra_set ON spectra(spectrum_set_id)
  ```
- **idx_spectrum_sets_experiment** / **idx_spectrum_sets_label** -> 表: spectrum_sets  
  分别用于按实验+时间或捕获标签查询光谱集合。
  ```sql
CREATE INDEX idx_spectrum_sets_experiment ON spectrum_sets(experiment_id, captured_at)
  ```
  ```sql
CREATE INDEX idx_spectrum_sets_label ON spectrum_sets(capture_label)
  ```
- **sqlite_autoindex\*** 系列  
  SQLite 自动生成的唯一/主键索引（如 projects、tags、users 等），无须手动维护。
