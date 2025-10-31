# nanosense/core/migrations/migration_0001_prepare_phase1_schema.py
"""
Phase 1 schema preparation migration.

Implements the structural changes drafted in `docs/数据库升级阶段1设计.md` by
creating the new tables/indexes and extending existing ones. Data backfill will
be handled in subsequent migrations.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

MIGRATION_ID = "0001_prepare_phase1_schema"


# -----------------------------------------------------------------------------
# Helper utilities
# -----------------------------------------------------------------------------

def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    try:
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
    except sqlite3.Error:
        return False
    return any(row[1] == column_name for row in cursor.fetchall())


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    )
    return cursor.fetchone() is not None


def _experiment_exists(conn: sqlite3.Connection, experiment_id: int) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM experiments WHERE experiment_id = ? LIMIT 1",
        (experiment_id,),
    )
    return cursor.fetchone() is not None


def _create_tables(conn: sqlite3.Connection, statements: List[Tuple[str, str]]) -> None:
    for table_name, ddl in statements:
        if not _table_exists(conn, table_name):
            conn.execute(ddl)


def _add_columns(conn: sqlite3.Connection, statements: List[Tuple[str, str, str]]) -> None:
    for table_name, column_name, ddl in statements:
        if _table_exists(conn, table_name) and not _column_exists(conn, table_name, column_name):
            conn.execute(ddl)


def _create_indexes(
    conn: sqlite3.Connection,
    statements: Iterable[Tuple[str, str, Optional[str]]],
) -> None:
    for index_name, ddl, table_name in statements:
        if table_name and not _table_exists(conn, table_name):
            continue
        if not _index_exists(conn, index_name):
            conn.execute(ddl)


# -----------------------------------------------------------------------------
# DDL definitions
# -----------------------------------------------------------------------------

NEW_TABLES: List[Tuple[str, str]] = [
    (
        "users",
        """
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT,
            email TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT
        )
        """,
    ),
    (
        "roles",
        """
        CREATE TABLE roles (
            role_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
        """,
    ),
    (
        "user_roles",
        """
        CREATE TABLE user_roles (
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            role_id INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
            assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, role_id)
        )
        """,
    ),
    (
        "user_preferences",
        """
        CREATE TABLE user_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            preferences_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ),
    (
        "samples",
        """
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
        """,
    ),
    (
        "batch_runs",
        """
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
        """,
    ),
    (
        "batch_run_items",
        """
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
        """,
    ),
    (
        "instrument_states",
        """
        CREATE TABLE instrument_states (
            instrument_state_id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_serial TEXT,
            integration_time_ms REAL,
            averaging INTEGER,
            temperature REAL,
            config_json TEXT,
            captured_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ),
    (
        "processing_snapshots",
        """
        CREATE TABLE processing_snapshots (
            processing_config_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            version TEXT,
            parameters_json TEXT NOT NULL,
            created_by INTEGER REFERENCES users(user_id),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ),
    (
        "spectrum_data",
        """
        CREATE TABLE spectrum_data (
            data_id INTEGER PRIMARY KEY AUTOINCREMENT,
            wavelengths_blob BLOB NOT NULL,
            intensities_blob BLOB NOT NULL,
            points_count INTEGER NOT NULL,
            hash TEXT,
            storage_format TEXT NOT NULL DEFAULT 'npy',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ),
    (
        "spectrum_sets",
        """
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
        """,
    ),
    (
        "analysis_runs",
        """
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
        """,
    ),
    (
        "analysis_metrics",
        """
        CREATE TABLE analysis_metrics (
            analysis_run_id INTEGER REFERENCES analysis_runs(analysis_run_id) ON DELETE CASCADE,
            metric_key TEXT NOT NULL,
            metric_value TEXT,
            unit TEXT,
            is_primary INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (analysis_run_id, metric_key)
        )
        """,
    ),
    (
        "analysis_artifacts",
        """
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
        """,
    ),
    (
        "attachments",
        """
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
        """,
    ),
    (
        "tags",
        """
        CREATE TABLE tags (
            tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT,
            description TEXT
        )
        """,
    ),
    (
        "entity_tags",
        """
        CREATE TABLE entity_tags (
            tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            applied_by INTEGER REFERENCES users(user_id),
            applied_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (tag_id, entity_type, entity_id)
        )
        """,
    ),
    (
        "experiment_versions",
        """
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
        """,
    ),
    (
        "audit_logs",
        """
        CREATE TABLE audit_logs (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor_id INTEGER REFERENCES users(user_id),
            payload_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ),
]

NEW_INDEXES: List[Tuple[str, str, Optional[str]]] = [
    ("idx_samples_project", "CREATE INDEX idx_samples_project ON samples(project_id)", "samples"),
    ("idx_samples_external_id", "CREATE INDEX idx_samples_external_id ON samples(external_id)", "samples"),
    ("idx_batch_runs_project", "CREATE INDEX idx_batch_runs_project ON batch_runs(project_id)", "batch_runs"),
    ("idx_batch_runs_status", "CREATE INDEX idx_batch_runs_status ON batch_runs(status)", "batch_runs"),
    ("idx_batch_run_items_batch", "CREATE INDEX idx_batch_run_items_batch ON batch_run_items(batch_run_id)", "batch_run_items"),
    (
        "idx_batch_run_items_experiment",
        "CREATE INDEX idx_batch_run_items_experiment ON batch_run_items(experiment_id)",
        "batch_run_items",
    ),
    (
        "idx_spectrum_sets_experiment",
        "CREATE INDEX idx_spectrum_sets_experiment ON spectrum_sets(experiment_id, captured_at)",
        "spectrum_sets",
    ),
    ("idx_spectrum_sets_label", "CREATE INDEX idx_spectrum_sets_label ON spectrum_sets(capture_label)", "spectrum_sets"),
    ("idx_analysis_runs_type", "CREATE INDEX idx_analysis_runs_type ON analysis_runs(analysis_type)", "analysis_runs"),
    ("idx_analysis_runs_started", "CREATE INDEX idx_analysis_runs_started ON analysis_runs(started_at)", "analysis_runs"),
    ("idx_attachments_entity", "CREATE INDEX idx_attachments_entity ON attachments(entity_type, entity_id)", "attachments"),
    ("idx_entity_tags_entity", "CREATE INDEX idx_entity_tags_entity ON entity_tags(entity_type, entity_id)", "entity_tags"),
    ("idx_audit_logs_entity", "CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_type, entity_id)", "audit_logs"),
    ("idx_audit_logs_action", "CREATE INDEX idx_audit_logs_action ON audit_logs(action)", "audit_logs"),
]

ALTER_COLUMNS: List[Tuple[str, str, str]] = [
    ("projects", "status", "ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"),
    ("projects", "owner_user_id", "ALTER TABLE projects ADD COLUMN owner_user_id INTEGER REFERENCES users(user_id)"),
    ("projects", "metadata_json", "ALTER TABLE projects ADD COLUMN metadata_json TEXT"),
    (
        "experiments",
        "batch_run_id",
        "ALTER TABLE experiments ADD COLUMN batch_run_id INTEGER REFERENCES batch_runs(batch_run_id)",
    ),
    ("experiments", "sample_id", "ALTER TABLE experiments ADD COLUMN sample_id INTEGER REFERENCES samples(sample_id)"),
    ("experiments", "status", "ALTER TABLE experiments ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'"),
    ("experiments", "created_at", "ALTER TABLE experiments ADD COLUMN created_at TEXT"),
    ("experiments", "updated_at", "ALTER TABLE experiments ADD COLUMN updated_at TEXT"),
    ("experiments", "version", "ALTER TABLE experiments ADD COLUMN version INTEGER NOT NULL DEFAULT 1"),
    (
        "experiments",
        "processing_config_id",
        "ALTER TABLE experiments ADD COLUMN processing_config_id INTEGER REFERENCES processing_snapshots(processing_config_id)",
    ),
    (
        "spectra",
        "spectrum_set_id",
        "ALTER TABLE spectra ADD COLUMN spectrum_set_id INTEGER REFERENCES spectrum_sets(spectrum_set_id)",
    ),
    ("spectra", "data_id", "ALTER TABLE spectra ADD COLUMN data_id INTEGER REFERENCES spectrum_data(data_id)"),
    ("spectra", "quality_flag", "ALTER TABLE spectra ADD COLUMN quality_flag TEXT DEFAULT 'good'"),
    ("spectra", "created_at", "ALTER TABLE spectra ADD COLUMN created_at TEXT"),
    (
        "analysis_results",
        "analysis_run_id",
        "ALTER TABLE analysis_results ADD COLUMN analysis_run_id INTEGER REFERENCES analysis_runs(analysis_run_id)",
    ),
]

LEGACY_INDEXES: List[Tuple[str, str, Optional[str]]] = [
    ("idx_experiments_timestamp", "CREATE INDEX idx_experiments_timestamp ON experiments(timestamp)", "experiments"),
    ("idx_experiments_status", "CREATE INDEX idx_experiments_status ON experiments(status)", "experiments"),
    ("idx_spectra_experiment", "CREATE INDEX idx_spectra_experiment ON spectra(experiment_id)", "spectra"),
    ("idx_spectra_set", "CREATE INDEX idx_spectra_set ON spectra(spectrum_set_id)", "spectra"),
]

ANALYSIS_METRIC_UNITS = {
    "Affinity_KD": {
        "KD": "nM",
        "R_max": None,
        "r_squared": None,
        "n": None,
    },
    "Calibration": {
        "slope": None,
        "intercept": None,
        "r_squared": None,
        "lod": None,
        "loq": None,
    },
    "Sensitivity": {
        "LOD": None,
        "LOQ": None,
        "r_squared": None,
    },
}


# -----------------------------------------------------------------------------
# Data migration helpers
# -----------------------------------------------------------------------------

def _normalize_timestamp(value: Optional[str]) -> str:
    if value and value.strip():
        return value
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_default_processing_snapshot(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        SELECT processing_config_id
        FROM processing_snapshots
        WHERE name = ? AND version = ?
        """,
        ("legacy_default", "1.0"),
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor = conn.execute(
        """
        INSERT INTO processing_snapshots (name, version, parameters_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            "legacy_default",
            "1.0",
            json.dumps({"source": "pre_phase1"}),
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    return cursor.lastrowid


def _ensure_default_instrument_state(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        SELECT instrument_state_id
        FROM instrument_states
        WHERE config_json LIKE ?
        ORDER BY instrument_state_id
        LIMIT 1
        """,
        ('%"legacy_default"%',),
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor = conn.execute(
        """
        INSERT INTO instrument_states (device_serial, integration_time_ms, averaging, temperature, config_json, captured_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy_unknown",
            None,
            None,
            None,
            json.dumps({"source": "legacy_default"}),
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    return cursor.lastrowid


def _populate_experiment_metadata(conn: sqlite3.Connection) -> None:
    now_value = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        UPDATE experiments
        SET created_at = COALESCE(created_at, timestamp, ?),
            updated_at = COALESCE(updated_at, timestamp, ?)
        """,
        (now_value, now_value),
    )
    conn.execute(
        """
        UPDATE experiments
        SET status = 'completed'
        WHERE status IS NULL OR TRIM(status) = '' OR status = 'draft'
        """
    )


def _seed_experiment_versions(conn: sqlite3.Connection) -> None:
    now_value = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT OR IGNORE INTO experiment_versions (experiment_id, version_no, snapshot_json, created_at)
        SELECT experiment_id, 1, json_object('legacy_seed', 1), ?
        FROM experiments
        """,
        (now_value,),
    )


def _parse_numeric_array(payload: Optional[str]) -> List[float]:
    if payload is None or payload.strip() == "":
        return []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(data, list):
        raise ValueError("invalid_json")
    parsed: List[float] = []
    for item in data:
        try:
            parsed.append(float(item))
        except (TypeError, ValueError) as exc:
            raise ValueError("non_numeric") from exc
    return parsed


def _derive_capture_role(spec_type: str) -> Tuple[str, str, Optional[str]]:
    capture_label = spec_type or "Unknown"
    result_variant: Optional[str] = None
    spectrum_role = capture_label

    if capture_label.lower() in {"signal", "background", "reference"}:
        spectrum_role = capture_label.capitalize()
    elif capture_label.startswith("Result_"):
        spectrum_role = "Result"
        result_variant = capture_label.split("Result_", 1)[1] or None
    return capture_label, spectrum_role, result_variant


def _parse_json_payload(value: Optional[str]) -> Tuple[Optional[object], bool]:
    if value is None:
        return None, False
    stripped = value.strip()
    if not stripped:
        return None, False
    try:
        return json.loads(stripped), True
    except json.JSONDecodeError:
        return value, False


def _prepare_metric_value(value: object) -> Tuple[Optional[str], bool]:
    if value is None:
        return None, False
    if isinstance(value, bool):
        return ("1" if value else "0"), True
    if isinstance(value, (int, float)):
        return str(value), True
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False), False
    return str(value), False


def _migrate_spectra(conn: sqlite3.Connection) -> None:
    cursor = conn.execute(
        """
        SELECT spectrum_id, experiment_id, type, timestamp, wavelengths, intensities,
               data_id, spectrum_set_id, created_at
        FROM spectra
        WHERE data_id IS NULL OR spectrum_set_id IS NULL
        ORDER BY spectrum_id
        """
    )
    rows = cursor.fetchall()
    if not rows:
        return

    processing_id = _ensure_default_processing_snapshot(conn)
    instrument_id = _ensure_default_instrument_state(conn)
    migrated = 0
    skipped = 0

    for (
        spectrum_id,
        experiment_id,
        spec_type,
        timestamp_value,
        wavelengths_json,
        intensities_json,
        existing_data_id,
        existing_set_id,
        created_at_value,
    ) in rows:
        created_ts = _normalize_timestamp(created_at_value or timestamp_value)
        quality_flag = "good"

        data_id = existing_data_id
        set_id = existing_set_id

        if experiment_id is None or not _experiment_exists(conn, experiment_id):
            quality_flag = "missing_experiment"
            conn.execute(
                """
                UPDATE spectra
                SET quality_flag = ?, created_at = COALESCE(created_at, ?)
                WHERE spectrum_id = ?
                """,
                (quality_flag, created_ts, spectrum_id),
            )
            skipped += 1
            continue

        if data_id is None:
            try:
                wavelengths = _parse_numeric_array(wavelengths_json)
                intensities = _parse_numeric_array(intensities_json)
            except ValueError as exc:
                quality_flag = str(exc)
                skipped += 1
                conn.execute(
                    """
                    UPDATE spectra
                    SET quality_flag = ?, created_at = COALESCE(created_at, ?)
                    WHERE spectrum_id = ?
                    """,
                    (quality_flag, created_ts, spectrum_id),
                )
                continue

            if len(wavelengths) != len(intensities):
                quality_flag = "length_mismatch"
                min_len = min(len(wavelengths), len(intensities))
                wavelengths = wavelengths[:min_len]
                intensities = intensities[:min_len]

            points_count = len(wavelengths)
            storage_format = "json"
            wave_blob = json.dumps(wavelengths, separators=(",", ":")).encode("utf-8")
            inten_blob = json.dumps(intensities, separators=(",", ":")).encode("utf-8")
            checksum = hashlib.sha256(wave_blob + b"|" + inten_blob).hexdigest()

            data_cursor = conn.execute(
                """
                INSERT INTO spectrum_data (wavelengths_blob, intensities_blob, points_count, hash, storage_format, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sqlite3.Binary(wave_blob),
                    sqlite3.Binary(inten_blob),
                    points_count,
                    checksum,
                    storage_format,
                    created_ts,
                ),
            )
            data_id = data_cursor.lastrowid

        capture_label, spectrum_role, result_variant = _derive_capture_role(spec_type or "")
        captured_at = _normalize_timestamp(timestamp_value)

        if set_id is None and data_id is not None:
            set_cursor = conn.execute(
                """
                INSERT INTO spectrum_sets (
                    experiment_id,
                    batch_run_item_id,
                    capture_label,
                    spectrum_role,
                    result_variant,
                    data_id,
                    instrument_state_id,
                    processing_config_id,
                    captured_at,
                    created_at,
                    quality_flag
                ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    capture_label,
                    spectrum_role,
                    result_variant,
                    data_id,
                    instrument_id,
                    processing_id,
                    captured_at,
                    created_ts,
                    quality_flag,
                ),
            )
            set_id = set_cursor.lastrowid

        if data_id is not None:
            conn.execute(
                """
                UPDATE spectra
                SET spectrum_set_id = ?,
                    data_id = ?,
                    quality_flag = ?,
                    created_at = COALESCE(created_at, ?)
                WHERE spectrum_id = ?
                """,
                (set_id, data_id, quality_flag, created_ts, spectrum_id),
            )
            migrated += 1
        else:
            skipped += 1

    print(f"[Database] Spectra migration completed: migrated={migrated}, skipped={skipped}")


def _migrate_analysis_results(conn: sqlite3.Connection) -> None:
    cursor = conn.execute(
        """
        SELECT result_id,
               experiment_id,
               analysis_type,
               timestamp,
               result_data,
               source_spectrum_ids,
               analysis_run_id
        FROM analysis_results
        WHERE analysis_run_id IS NULL
        ORDER BY result_id
        """
    )
    rows = cursor.fetchall()
    if not rows:
        return

    migrated = 0
    skipped = 0

    for (
        result_id,
        experiment_id,
        analysis_type,
        timestamp_value,
        result_data,
        source_ids,
        existing_run_id,
    ) in rows:
        if existing_run_id:
            continue

        if experiment_id is None or not _experiment_exists(conn, experiment_id):
            skipped += 1
            continue

        started_at = _normalize_timestamp(timestamp_value)
        finished_at = started_at
        analysis_type = analysis_type or "Unknown"

        input_context = {"legacy_result_id": result_id}
        source_payload, _ = _parse_json_payload(source_ids)
        if source_payload is not None:
            input_context["source_spectrum_ids"] = source_payload
        if result_data:
            input_context["raw_result_data"] = result_data

        input_context_json = json.dumps(input_context, ensure_ascii=False)

        run_id = None
        adjustment_suffix = 0
        while run_id is None:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO analysis_runs (
                        experiment_id,
                        batch_run_item_id,
                        analysis_type,
                        algorithm_version,
                        status,
                        started_at,
                        finished_at,
                        initiated_by,
                        input_context
                    ) VALUES (?, NULL, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        experiment_id,
                        analysis_type,
                        "legacy",
                        "completed",
                        started_at,
                        finished_at,
                        input_context_json,
                    ),
                )
                run_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                adjustment_suffix += 1
                started_at = f"{_normalize_timestamp(timestamp_value)}+{result_id}-{adjustment_suffix}"
                finished_at = started_at
                if adjustment_suffix > 5:
                    run_id = None
                    break

        if run_id is None:
            skipped += 1
            continue

        result_payload, parsed_as_json = _parse_json_payload(result_data)
        metrics_inserted = 0
        unit_map = ANALYSIS_METRIC_UNITS.get(analysis_type, {})
        primary_assigned = False

        if isinstance(result_payload, dict):
            for key, value in result_payload.items():
                metric_value, is_numeric = _prepare_metric_value(value)
                if metric_value is None:
                    continue
                is_primary = 0
                if not primary_assigned and is_numeric:
                    is_primary = 1
                    primary_assigned = True
                conn.execute(
                    """
                    INSERT INTO analysis_metrics (analysis_run_id, metric_key, metric_value, unit, is_primary)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(key),
                        metric_value,
                        unit_map.get(str(key)),
                        is_primary,
                    ),
                )
                metrics_inserted += 1
        elif parsed_as_json and isinstance(result_payload, list):
            for index, item in enumerate(result_payload):
                metric_value, is_numeric = _prepare_metric_value(item)
                if metric_value is None:
                    continue
                is_primary = 1 if not primary_assigned and is_numeric else 0
                primary_assigned = primary_assigned or bool(is_primary)
                conn.execute(
                    """
                    INSERT INTO analysis_metrics (analysis_run_id, metric_key, metric_value, unit, is_primary)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        f"item_{index}",
                        metric_value,
                        None,
                        is_primary,
                    ),
                )
                metrics_inserted += 1
        else:
            metric_value, _ = _prepare_metric_value(result_payload)
            if metric_value is not None:
                conn.execute(
                    """
                    INSERT INTO analysis_metrics (analysis_run_id, metric_key, metric_value, unit, is_primary)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        "raw_payload",
                        metric_value,
                        None,
                        0,
                    ),
                )
                metrics_inserted += 1

        conn.execute(
            "UPDATE analysis_results SET analysis_run_id = ? WHERE result_id = ?",
            (run_id, result_id),
        )
        migrated += 1

    print(f"[Database] Analysis migration completed: migrated={migrated}, skipped={skipped}")


# -----------------------------------------------------------------------------
# Migration entry point
# -----------------------------------------------------------------------------

def apply(conn: sqlite3.Connection) -> None:
    """
    Apply schema changes required for Phase 1 (structure only).
    """
    conn.execute("PRAGMA foreign_keys = ON")

    _create_tables(conn, NEW_TABLES)
    _add_columns(conn, ALTER_COLUMNS)
    _create_indexes(conn, NEW_INDEXES)
    _create_indexes(conn, LEGACY_INDEXES)

    _populate_experiment_metadata(conn)
    _seed_experiment_versions(conn)
    _migrate_spectra(conn)
    _migrate_analysis_results(conn)
