-- Phase 1 schema draft for SQLite
-- Generated from docs/数据库升级阶段1设计.md

BEGIN TRANSACTION;

-- ============================================================================
-- 0. Safety toggles
-- ============================================================================
PRAGMA foreign_keys = OFF;

-- ============================================================================
-- 1. New core entities
-- ============================================================================

-- Users and roles (foundation for ownership and permissions)
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS roles (
    role_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    preferences_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Projects enhancements (must run after users table is present)
ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE projects ADD COLUMN owner_user_id INTEGER REFERENCES users(user_id);
ALTER TABLE projects ADD COLUMN metadata_json TEXT;

-- Samples
CREATE TABLE IF NOT EXISTS samples (
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
);

CREATE INDEX IF NOT EXISTS idx_samples_project ON samples(project_id);
CREATE INDEX IF NOT EXISTS idx_samples_external_id ON samples(external_id);

-- Batch runs and items
CREATE TABLE IF NOT EXISTS batch_runs (
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
);

CREATE INDEX IF NOT EXISTS idx_batch_runs_project ON batch_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_batch_runs_status ON batch_runs(status);

CREATE TABLE IF NOT EXISTS batch_run_items (
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
    UNIQUE(batch_run_id, position_label, planned_stage)
);

CREATE INDEX IF NOT EXISTS idx_batch_run_items_batch ON batch_run_items(batch_run_id);
CREATE INDEX IF NOT EXISTS idx_batch_run_items_experiment ON batch_run_items(experiment_id);

-- Instrument states and processing snapshots
CREATE TABLE IF NOT EXISTS instrument_states (
    instrument_state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT,
    integration_time_ms REAL,
    averaging INTEGER,
    temperature REAL,
    config_json TEXT,
    captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processing_snapshots (
    processing_config_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT,
    parameters_json TEXT NOT NULL,
    created_by INTEGER REFERENCES users(user_id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Spectrum restructuring
CREATE TABLE IF NOT EXISTS spectrum_data (
    data_id INTEGER PRIMARY KEY AUTOINCREMENT,
    wavelengths_blob BLOB NOT NULL,
    intensities_blob BLOB NOT NULL,
    points_count INTEGER NOT NULL,
    hash TEXT,
    storage_format TEXT NOT NULL DEFAULT 'npy',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spectrum_sets (
    spectrum_set_id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    batch_run_item_id INTEGER REFERENCES batch_run_items(item_id) ON DELETE SET NULL,
    capture_label TEXT NOT NULL, -- Signal/Background/Reference/Result etc.
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
);

CREATE INDEX IF NOT EXISTS idx_spectrum_sets_experiment ON spectrum_sets(experiment_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_spectrum_sets_label ON spectrum_sets(capture_label);

-- Analysis runs
CREATE TABLE IF NOT EXISTS analysis_runs (
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
    UNIQUE(experiment_id, analysis_type, started_at)
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_type ON analysis_runs(analysis_type);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_started ON analysis_runs(started_at);

CREATE TABLE IF NOT EXISTS analysis_metrics (
    analysis_run_id INTEGER REFERENCES analysis_runs(analysis_run_id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    metric_value TEXT,
    unit TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (analysis_run_id, metric_key)
);

CREATE TABLE IF NOT EXISTS analysis_artifacts (
    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id INTEGER REFERENCES analysis_runs(analysis_run_id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    file_path TEXT,
    data_blob BLOB,
    mime_type TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT
);

-- Attachments and tagging
CREATE TABLE IF NOT EXISTS attachments (
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
);

CREATE INDEX IF NOT EXISTS idx_attachments_entity ON attachments(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS tags (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS entity_tags (
    tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    applied_by INTEGER REFERENCES users(user_id),
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tag_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_tags_entity ON entity_tags(entity_type, entity_id);

-- Experiment versions and audit logs
CREATE TABLE IF NOT EXISTS experiment_versions (
    experiment_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_by INTEGER REFERENCES users(user_id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    diff_summary TEXT,
    UNIQUE (experiment_id, version_no)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(user_id),
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);

-- ============================================================================
-- 2. Alter existing tables
-- ============================================================================

ALTER TABLE experiments ADD COLUMN batch_run_id INTEGER REFERENCES batch_runs(batch_run_id);
ALTER TABLE experiments ADD COLUMN sample_id INTEGER REFERENCES samples(sample_id);
ALTER TABLE experiments ADD COLUMN status TEXT NOT NULL DEFAULT 'draft';
ALTER TABLE experiments ADD COLUMN created_at TEXT;
ALTER TABLE experiments ADD COLUMN updated_at TEXT;
ALTER TABLE experiments ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE experiments ADD COLUMN processing_config_id INTEGER REFERENCES processing_snapshots(processing_config_id);

CREATE INDEX IF NOT EXISTS idx_experiments_timestamp ON experiments(timestamp);
CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);

ALTER TABLE spectra ADD COLUMN spectrum_set_id INTEGER REFERENCES spectrum_sets(spectrum_set_id);
ALTER TABLE spectra ADD COLUMN data_id INTEGER REFERENCES spectrum_data(data_id);
ALTER TABLE spectra ADD COLUMN quality_flag TEXT DEFAULT 'good';
ALTER TABLE spectra ADD COLUMN created_at TEXT;

CREATE INDEX IF NOT EXISTS idx_spectra_experiment ON spectra(experiment_id);
CREATE INDEX IF NOT EXISTS idx_spectra_set ON spectra(spectrum_set_id);

ALTER TABLE analysis_results ADD COLUMN analysis_run_id INTEGER REFERENCES analysis_runs(analysis_run_id);

-- ============================================================================
-- 3. Derived views (to be materialized later; placeholders only)
-- ============================================================================
-- NOTE: views will be created after data backfill is complete.

-- ============================================================================
-- 4. Cleanup
-- ============================================================================
PRAGMA foreign_keys = ON;
COMMIT;
