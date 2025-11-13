import sqlite3

import pytest

from nanosense.core.data_access import ExplorerDataAccess


def setup_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE projects (project_id INTEGER PRIMARY KEY, name TEXT, status TEXT, creation_date TEXT)")
    conn.execute(
        "CREATE TABLE experiments (experiment_id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, status TEXT, timestamp TEXT, created_at TEXT, updated_at TEXT, type TEXT, operator TEXT)"
    )
    conn.execute(
        "CREATE TABLE batch_runs (batch_run_id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, status TEXT, start_time TEXT, end_time TEXT)"
    )
    conn.execute(
        "CREATE TABLE batch_run_items (item_id INTEGER PRIMARY KEY, batch_run_id INTEGER, position_label TEXT, sequence_no INTEGER, status TEXT, experiment_id INTEGER, capture_count INTEGER, last_captured_at TEXT, metadata_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE spectrum_sets (spectrum_set_id INTEGER PRIMARY KEY, experiment_id INTEGER, capture_label TEXT, spectrum_role TEXT, result_variant TEXT, captured_at TEXT, created_at TEXT, instrument_state_id INTEGER, processing_config_id INTEGER, quality_flag TEXT)"
    )
    conn.execute(
        "CREATE TABLE instrument_states (instrument_state_id INTEGER PRIMARY KEY, device_serial TEXT, integration_time_ms REAL, temperature REAL)"
    )
    conn.execute(
        "CREATE TABLE processing_snapshots (processing_config_id INTEGER PRIMARY KEY, name TEXT, version TEXT)"
    )
    return conn


def test_fetch_projects_returns_sorted_projects():
    conn = setup_conn()
    conn.executemany(
        "INSERT INTO projects VALUES (?, ?, ?, ?)",
        [
            (1, "Proj A", "active", "2025-01-01"),
            (2, "Proj B", "archived", "2025-01-05"),
        ],
    )
    access = ExplorerDataAccess(conn)
    projects = access.fetch_projects()
    assert projects[0]["project_id"] == 2
    assert projects[1]["project_id"] == 1


def test_fetch_experiment_detail_returns_joined_fields():
    conn = setup_conn()
    conn.execute("INSERT INTO projects VALUES (1, 'Proj', 'active', '2025-01-01')")
    conn.execute(
        "INSERT INTO experiments VALUES (3, 1, 'Exp', 'completed', '2025-01-10 10:00:00', '2025-01-10 12:00:00', '2025-01-11', 'kind', 'alice')"
    )
    access = ExplorerDataAccess(conn)
    detail = access.fetch_experiment_detail(3)
    assert detail is not None
    assert detail["project_name"] == "Proj"
    assert detail["experiment_status"] == "completed"


def test_fetch_spectrum_detail_includes_joined_metadata():
    conn = setup_conn()
    conn.execute("INSERT INTO instrument_states VALUES (1, 'SN-001', 10.5, 25.0)")
    conn.execute("INSERT INTO processing_snapshots VALUES (5, 'proc', '1.0')")
    conn.execute(
        "INSERT INTO spectrum_sets VALUES (7, 3, 'Signal', 'Result', 'A', '2025-01-01', '2025-01-01', 1, 5, 'good')"
    )
    access = ExplorerDataAccess(conn)
    detail = access.fetch_spectrum_detail(7)
    assert detail["instrument_device_serial"] == "SN-001"
    assert detail["processing_name"] == "proc"


def test_fetch_batch_overview_returns_items_for_experiment():
    conn = setup_conn()
    conn.execute("INSERT INTO batch_runs VALUES (2, 1, 'Batch A', 'in_progress', '2025-01-01', NULL)")
    conn.execute(
        "INSERT INTO batch_run_items VALUES (10, 2, 'A1', 1, 'completed', 3, 5, '2025-01-02', '{}')"
    )
    access = ExplorerDataAccess(conn)
    rows = access.fetch_batch_overview(3)
    assert len(rows) == 1
    assert rows[0]["batch_name"] == "Batch A"
    assert rows[0]["position_label"] == "A1"
    assert rows[0]["item_status"] == "completed"
    assert rows[0]["capture_count"] == 5
