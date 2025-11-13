"""
Batch-friendly data access helpers for the database explorer.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple


class DataAccessError(RuntimeError):
    """Raised when data access queries fail."""


class ExplorerDataAccess:
    """
    Lightweight repository for composite queries used by the database explorer.
    All methods return plain Python data structures to avoid GUI dependencies.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def fetch_projects(self) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT project_id, name, status, creation_date
            FROM projects
            ORDER BY creation_date DESC
            """
        )
        return [
            {
                "project_id": row[0],
                "name": row[1],
                "status": row[2],
                "creation_date": row[3],
            }
            for row in cursor.fetchall()
        ]

    def fetch_experiments(self, project_id: int) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT experiment_id, name, status, created_at, updated_at
            FROM experiments
            WHERE project_id = ?
            ORDER BY created_at DESC
            """,
            (project_id,),
        )
        return [
            {
                "experiment_id": row[0],
                "name": row[1],
                "status": row[2],
                "created_at": row[3],
                "updated_at": row[4],
            }
            for row in cursor.fetchall()
        ]

    def fetch_experiment_statuses(self) -> List[str]:
        cursor = self.conn.execute(
            """
            SELECT DISTINCT status
            FROM experiments
            WHERE status IS NOT NULL
            ORDER BY status
            """
        )
        return [row[0] for row in cursor.fetchall() if row[0]]

    def search_experiments(
        self,
        project_id: Optional[int] = None,
        name_filter: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        type_filter: str = "",
        limit: Optional[int] = None,
        sort_by: str = "created_at",
        sort_desc: bool = True,
        status_filter: str = "",
        operator_filter: str = "",
    ) -> List[Tuple]:
        clauses = []
        params: List[Any] = []
        if project_id not in (None, -1):
            clauses.append("project_id = ?")
            params.append(project_id)
        if name_filter:
            clauses.append("name LIKE ?")
            params.append(f"%{name_filter}%")
        coalesced_date = "date(COALESCE(created_at, timestamp))"
        if start_date:
            clauses.append(f"{coalesced_date} >= date(?)")
            params.append(start_date)
        if end_date:
            clauses.append(f"{coalesced_date} <= date(?)")
            params.append(end_date)
        if type_filter:
            clauses.append("type = ?")
            params.append(type_filter)
        if status_filter:
            clauses.append("status = ?")
            params.append(status_filter)
        if operator_filter:
            clauses.append("operator LIKE ?")
            params.append(f"%{operator_filter}%")
        where_sql = ""
        if clauses:
            where_sql = "WHERE " + " AND ".join(clauses)
        order_map = {
            "experiment_id": "experiment_id",
            "created_at": "COALESCE(created_at, timestamp)",
        }
        order_expr = order_map.get(sort_by, "COALESCE(created_at, timestamp)")
        direction = "DESC" if sort_desc else "ASC"
        query = f"""
            SELECT experiment_id,
                   (SELECT name FROM projects WHERE projects.project_id = experiments.project_id) AS project_name,
                   name,
                   type,
                   COALESCE(created_at, timestamp) AS created_at,
                   operator,
                   status
            FROM experiments
            {where_sql}
            ORDER BY {order_expr} {direction}
        """
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        cursor = self.conn.execute(query, tuple(params))
        return cursor.fetchall()


    def fetch_experiment_detail(self, experiment_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT e.experiment_id,
                   e.project_id,
                   e.name,
                   e.status,
                   e.created_at,
                   e.updated_at,
                   e.type,
                   e.operator,
                   p.name,
                   p.status
            FROM experiments e
            LEFT JOIN projects p ON e.project_id = p.project_id
            WHERE e.experiment_id = ?
            """,
            (experiment_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "experiment_id": row[0],
            "project_id": row[1],
            "experiment_name": row[2],
            "experiment_status": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "experiment_type": row[6],
            "operator": row[7],
            "project_name": row[8],
            "project_status": row[9],
        }

    def fetch_batch_runs(self, project_id: int) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT batch_run_id, name, status, start_time, end_time
            FROM batch_runs
            WHERE project_id = ?
            ORDER BY start_time DESC
            """,
            (project_id,),
        )
        return [
            {
                "batch_run_id": row[0],
                "name": row[1],
                "status": row[2],
                "start_time": row[3],
                "end_time": row[4],
            }
            for row in cursor.fetchall()
        ]

    def fetch_batch_run_items(self, batch_run_id: int) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT item_id,
                   position_label,
                   status,
                   experiment_id,
                   capture_count,
                   last_captured_at
            FROM batch_run_items
            WHERE batch_run_id = ?
            ORDER BY sequence_no
            """,
            (batch_run_id,),
        )
        return [
            {
                "item_id": row[0],
                "position_label": row[1],
                "status": row[2],
                "experiment_id": row[3],
                "capture_count": row[4],
                "last_captured_at": row[5],
            }
            for row in cursor.fetchall()
        ]

    def fetch_batch_overview(self, experiment_id: int) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT bri.item_id,
                   br.batch_run_id,
                   br.name,
                   br.status,
                   bri.position_label,
                   bri.status,
                   bri.capture_count,
                   bri.last_captured_at,
                   bri.metadata_json
            FROM batch_run_items bri
            JOIN batch_runs br ON bri.batch_run_id = br.batch_run_id
            WHERE bri.experiment_id = ?
            ORDER BY br.start_time DESC, bri.sequence_no
            """,
            (experiment_id,),
        )
        rows = cursor.fetchall()
        overview: List[Dict[str, Any]] = []
        for row in rows:
            overview.append(
                {
                    "item_id": row[0],
                    "batch_run_id": row[1],
                    "batch_name": row[2],
                    "batch_status": row[3],
                    "position_label": row[4],
                    "item_status": row[5],
                    "capture_count": row[6],
                    "last_captured_at": row[7],
                }
            )
        return overview

    def fetch_experiment_overview(self, experiment_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT e.experiment_id,
                   e.name,
                   e.type,
                   e.status,
                   e.operator,
                   e.created_at,
                   e.updated_at,
                   e.timestamp,
                   e.notes,
                   e.project_id,
                   p.name AS project_name
            FROM experiments e
            LEFT JOIN projects p ON p.project_id = e.project_id
            WHERE e.experiment_id = ?
            """,
            (experiment_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "experiment_id": row[0],
            "name": row[1],
            "type": row[2],
            "status": row[3],
            "operator": row[4],
            "created_at": row[5],
            "updated_at": row[6],
            "timestamp": row[7],
            "notes": row[8],
            "project_id": row[9],
            "project_name": row[10],
        }

    def fetch_spectrum_sets(self, experiment_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = """
            SELECT spectrum_set_id,
                   capture_label,
                   spectrum_role,
                   result_variant,
                   captured_at,
                   created_at,
                   instrument_state_id,
                   processing_config_id,
                   quality_flag
            FROM spectrum_sets
            WHERE experiment_id = ?
            ORDER BY captured_at DESC
        """
        params: Tuple[Any, ...] = (experiment_id,)
        if limit:
            sql += " LIMIT ?"
            params += (limit,)

        cursor = self.conn.execute(sql, params)
        return [
            {
                "spectrum_set_id": row[0],
                "capture_label": row[1],
                "spectrum_role": row[2],
                "result_variant": row[3],
                "captured_at": row[4],
                "created_at": row[5],
                "instrument_state_id": row[6],
                "processing_config_id": row[7],
                "quality_flag": row[8],
            }
            for row in cursor.fetchall()
        ]

    def fetch_spectrum_detail(self, spectrum_set_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT ss.spectrum_set_id,
                   ss.capture_label,
                   ss.spectrum_role,
                   ss.result_variant,
                   ss.captured_at,
                   ss.created_at,
                   ss.quality_flag,
                   ss.instrument_state_id,
                   ss.processing_config_id,
                   inst.device_serial,
                   inst.integration_time_ms,
                   inst.temperature,
                   proc.name,
                   proc.version
            FROM spectrum_sets ss
            LEFT JOIN instrument_states AS inst ON ss.instrument_state_id = inst.instrument_state_id
            LEFT JOIN processing_snapshots AS proc ON ss.processing_config_id = proc.processing_config_id
            WHERE ss.spectrum_set_id = ?
            """,
            (spectrum_set_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "spectrum_set_id": row[0],
            "capture_label": row[1],
            "spectrum_role": row[2],
            "result_variant": row[3],
            "captured_at": row[4],
            "created_at": row[5],
            "quality_flag": row[6],
            "instrument_state_id": row[7],
            "processing_config_id": row[8],
            "instrument_device_serial": row[9],
            "instrument_integration_ms": row[10],
            "instrument_temperature": row[11],
            "processing_name": row[12],
            "processing_version": row[13],
        }
