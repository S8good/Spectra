import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import validate_migration as vm


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    return conn


def test_check_tables_missing_reports_expected_tables():
    conn = make_conn()
    conn.execute("CREATE TABLE projects (project_id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE experiments (experiment_id INTEGER PRIMARY KEY)")
    missing = vm.check_tables(conn)
    assert "spectra" in missing
    assert "spectrum_sets" in missing


def test_check_latency_detects_offenders():
    conn = make_conn()
    conn.execute(
        """
        CREATE TABLE spectrum_sets (
            spectrum_set_id INTEGER PRIMARY KEY,
            captured_at TEXT,
            created_at TEXT
        )
        """
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute(
        "INSERT INTO spectrum_sets VALUES (1, ?, ?)",
        (
            now.strftime("%Y-%m-%d %H:%M:%S"),
            (now + timedelta(seconds=400)).strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.execute(
        "INSERT INTO spectrum_sets VALUES (2, ?, ?)",
        (
            now.strftime("%Y-%m-%d %H:%M:%S"),
            (now + timedelta(seconds=100)).strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    offenders = vm.check_latency(conn, timedelta(seconds=300))
    assert len(offenders) == 1
    assert offenders[0][0] == 1


def test_check_batch_status_detects_inconsistent_runs():
    conn = make_conn()
    conn.execute(
        """
        CREATE TABLE batch_runs (
            batch_run_id INTEGER PRIMARY KEY,
            status TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE batch_run_items (
            item_id INTEGER PRIMARY KEY,
            batch_run_id INTEGER,
            status TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO batch_runs VALUES (?, ?)",
        [
            (1, "completed"),
            (2, "in_progress"),
        ],
    )
    conn.executemany(
        "INSERT INTO batch_run_items VALUES (?, ?, ?)",
        [
            (1, 1, "completed"),
            (2, 1, "pending"),
            (3, 2, "completed"),
        ],
    )

    completed_with_open, stalled = vm.check_batch_status(conn)

    assert completed_with_open == [(1, 1)]
    assert stalled == [(2, 1)]


def build_validation_db(tmp_path, latency_seconds: int = 0) -> Path:
    db_path = tmp_path / "validation.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE projects (project_id INTEGER PRIMARY KEY, name TEXT, status TEXT, creation_date TEXT)")
    conn.execute("CREATE TABLE experiments (experiment_id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, status TEXT, created_at TEXT, updated_at TEXT, type TEXT, operator TEXT)")
    conn.execute("CREATE TABLE spectra (spectrum_id INTEGER PRIMARY KEY, experiment_id INTEGER, type TEXT, timestamp TEXT, wavelengths TEXT, intensities TEXT, spectrum_set_id INTEGER, data_id INTEGER, quality_flag TEXT)")
    conn.execute("CREATE TABLE analysis_results (result_id INTEGER PRIMARY KEY, experiment_id INTEGER, analysis_type TEXT, timestamp TEXT, result_data TEXT, source_spectrum_ids TEXT, analysis_run_id INTEGER)")
    conn.execute("CREATE TABLE spectrum_sets (spectrum_set_id INTEGER PRIMARY KEY, experiment_id INTEGER, capture_label TEXT, spectrum_role TEXT, result_variant TEXT, captured_at TEXT, created_at TEXT, instrument_state_id INTEGER, processing_config_id INTEGER, quality_flag TEXT)")
    conn.execute("CREATE TABLE spectrum_data (data_id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE analysis_runs (analysis_run_id INTEGER PRIMARY KEY, experiment_id INTEGER, analysis_type TEXT, started_at TEXT)")
    conn.execute("CREATE TABLE analysis_metrics (analysis_run_id INTEGER, metric_key TEXT, metric_value TEXT, unit TEXT, is_primary INTEGER)")
    conn.execute("CREATE TABLE experiment_versions (experiment_version_id INTEGER PRIMARY KEY, experiment_id INTEGER, version_no INTEGER, snapshot_json TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE batch_runs (batch_run_id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, status TEXT, start_time TEXT, end_time TEXT)")
    conn.execute("CREATE TABLE batch_run_items (item_id INTEGER PRIMARY KEY, batch_run_id INTEGER, position_label TEXT, sequence_no INTEGER, status TEXT, experiment_id INTEGER, capture_count INTEGER, last_captured_at TEXT, metadata_json TEXT)")
    conn.execute("CREATE VIEW legacy_spectrum_sets_view AS SELECT experiment_id, capture_label AS type, captured_at AS timestamp FROM spectrum_sets")
    conn.execute("CREATE VIEW legacy_analysis_runs_view AS SELECT experiment_id, analysis_type, started_at AS timestamp FROM analysis_runs")

    conn.execute("INSERT INTO projects VALUES (1, 'Proj', 'active', '2025-01-01')")
    conn.execute("INSERT INTO experiments VALUES (2, 1, 'Exp', 'completed', '2025-01-02', '2025-01-03', 'kind', 'alice')")
    captured = '2025-01-04 00:00:00'
    created_dt = datetime.strptime(captured, '%Y-%m-%d %H:%M:%S') + timedelta(seconds=latency_seconds)
    created = created_dt.strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("INSERT INTO spectrum_sets VALUES (5, 2, 'Signal', 'Result', 'A', ?, ?, NULL, NULL, 'good')", (captured, created))
    conn.execute("INSERT INTO spectra VALUES (10, 2, 'Signal', ?, NULL, NULL, 5, NULL, 'good')", (captured,))
    conn.execute("INSERT INTO experiment_versions VALUES (1, 2, 1, '{}', '2025-01-04')")
    conn.commit()
    conn.close()
    return db_path


def test_main_strict_treats_warnings_as_failure(tmp_path):
    db_path = build_validation_db(tmp_path, latency_seconds=600)
    exit_code = vm.main(["--db", str(db_path), "--max-latency", "300", "--strict"])
    assert exit_code == 1


def test_main_report_file(tmp_path):
    db_path = build_validation_db(tmp_path, latency_seconds=0)
    report_path = tmp_path / "report.txt"
    exit_code = vm.main(["--db", str(db_path), "--report-file", str(report_path)])
    assert exit_code == 0
    assert report_path.exists()
    content = report_path.read_text(encoding='utf-8')
    assert "OK" in content


def test_main_history_file(tmp_path):
    db_path = build_validation_db(tmp_path, latency_seconds=0)
    history_path = tmp_path / "history.csv"
    exit_code = vm.main(["--db", str(db_path), "--history-file", str(history_path)])
    assert exit_code == 0
    lines = history_path.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 2
    header, record = lines
    assert header == "timestamp,errors,warnings,exit_code"
    assert record.endswith(',0')
