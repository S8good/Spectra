import sqlite3

from scripts import legacy_freeze as lf


def build_legacy_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE spectra (
            spectrum_id INTEGER PRIMARY KEY,
            experiment_id INTEGER,
            timestamp TEXT,
            created_at TEXT,
            spectrum_set_id INTEGER,
            data_id INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE analysis_results (
            result_id INTEGER PRIMARY KEY,
            experiment_id INTEGER,
            timestamp TEXT,
            analysis_run_id INTEGER
        )
        """
    )
    return conn


def test_analyze_legacy_tables_counts():
    conn = build_legacy_conn()
    conn.executemany(
        "INSERT INTO spectra VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "2025-01-01 00:00:00", "2025-01-01 00:10:00", None, None),
            (2, 1, "2025-01-02 00:00:00", "2025-01-02 00:10:00", 10, 20),
        ],
    )
    conn.executemany(
        "INSERT INTO analysis_results VALUES (?, ?, ?, ?)",
        [
            (5, 1, "2025-01-01 00:00:00", None),
            (6, 1, "2024-12-01 00:00:00", 7),
        ],
    )

    stats = lf.analyze_legacy_tables(conn, "2024-12-31 23:59:59")
    assert stats["spectra"]["total"] == 2
    assert stats["spectra"]["pending"] == 1
    assert stats["spectra"]["recent"] == 2  # both created_at > freeze threshold
    assert stats["analysis_results"]["pending"] == 1
    assert stats["analysis_results"]["recent"] == 1


def test_build_warnings_reports_pending_and_recent():
    stats = {
        "spectra": {"exists": True, "pending": 2, "recent": 1},
        "analysis_results": {"exists": True, "pending": 0, "recent": 3},
    }
    warnings = lf.build_warnings(stats, "2025-01-01 00:00:00")
    assert any("spectra rows" in item for item in warnings)
    assert any("analysis_results rows" in item for item in warnings)
