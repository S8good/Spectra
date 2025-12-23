# nanosense/core/database_manager.py

import sqlite3
import os
import json
import time
import hashlib
import numpy as np
from collections import defaultdict
from .migration_runner import run_migrations
from .snapshot_utils import (
    canonicalize_instrument_info,
    canonicalize_processing_info,
    serialize_payload,
)
from typing import Any, Dict, List, Optional, Tuple


def _merge_nested_dict(target: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key] = _merge_nested_dict(dict(target.get(key, {})), value)
        elif isinstance(value, dict):
            target[key] = _merge_nested_dict({}, value)
        else:
            target[key] = value
    return target


class DatabaseManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, db_path=None):
        if hasattr(self, '_init_complete') and self.db_path == db_path:
            return
        if db_path:
            self.db_path = db_path
            self.conn = None
            self._connect()
            self._create_tables()
            self._run_pending_migrations()
            self._create_compatibility_views()
            self._init_complete = True
            print(f"数据库已连接并初始化: {db_path}")

    def _connect(self):
        try:
            db_dir = os.path.dirname(self.db_path)
            os.makedirs(db_dir, exist_ok=True)
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        except Exception as e:
            print(f"数据库连接失败: {e}")

    def _create_tables(self):
        """【重大修改】重新定义数据库结构，增加项目、分析结果等表。"""

        if not self.conn:
            return

        try:
            cursor = self.conn.cursor()

            # 【新增】创建项目表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                creation_date TEXT NOT NULL
            );
            """)

            # 【修改】扩展实验表，增加与项目的关联以及更丰富的元数据
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

            # 【修改】光谱数据表结构不变，但其逻辑意义更清晰
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS spectra (
                spectrum_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER,
                type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                wavelengths TEXT,
                intensities TEXT,
                FOREIGN KEY (experiment_id) REFERENCES experiments (experiment_id)
            );
            """)

            # 【新增】创建分析结果表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER,
                analysis_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                result_data TEXT,
                source_spectrum_ids TEXT,
                FOREIGN KEY (experiment_id) REFERENCES experiments (experiment_id)
            );
            """)

            self.conn.commit()

        except Exception as e:
            print(f"创建数据表失败: {e}")

    def _create_compatibility_views(self):
        if not self.conn:
            return

        try:
            cursor = self.conn.cursor()

            cursor.execute("""
            CREATE VIEW IF NOT EXISTS legacy_spectrum_sets_view AS
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
            """)

            cursor.execute("""
            CREATE VIEW IF NOT EXISTS legacy_analysis_runs_view AS
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
            """)

            self.conn.commit()

        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                print("兼容视图创建被跳过，等待迁移完成后重新初始化。")
            else:
                print(f"创建兼容视图失败: {e}")
        except Exception as e:
            print(f"创建兼容视图失败: {e}")

    def _run_pending_migrations(self):
        if not self.conn:
            return

        try:
            run_migrations(self.conn, logger=self._log_migration)
        except Exception as e:
            print(f"数据库迁移失败: {e}")
            raise

    @staticmethod
    def _log_migration(message):
        print(f"[Database] {message}")

    def _fetch_structured_spectra(self, experiment_id: int) -> Optional[List[Dict[str, Any]]]:
        if not self.conn:
            return None

        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT spectrum_set_id, type, timestamp, wavelengths, intensities
                FROM legacy_spectrum_sets_view
                WHERE experiment_id = ?
                ORDER BY timestamp, spectrum_set_id
                """, (experiment_id,))
            rows = cursor.fetchall()
            if not rows:
                return None
            spectra_by_timestamp: Dict[str, Dict[str, Any]] = defaultdict(dict)
            for _set_id, spec_type, timestamp_value, wl_json, int_json in rows:
                try:
                    wavelengths = json.loads(wl_json or '[]')
                except json.JSONDecodeError:
                    wavelengths = []
                try:
                    intensities = json.loads(int_json or '[]')
                except json.JSONDecodeError:
                    intensities = []
                bucket = spectra_by_timestamp.setdefault(timestamp_value, {})
                if 'wavelengths' not in bucket:
                    bucket['wavelengths'] = wavelengths
                normalized_type = spec_type or 'Unknown'
                bucket[normalized_type] = intensities
            return list(spectra_by_timestamp.values())
        except sqlite3.OperationalError:
            return None
        except Exception as e:
            print(f"读取结构化光谱数据失败: {e}")
            return None

    def _coerce_metric_value(self, raw_value: Optional[str]) -> Any:
        if raw_value is None:
            return None
        value = raw_value.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _fetch_structured_analysis(self, experiment_id: int) -> Optional[List[Dict[str, Any]]]:
        if not self.conn:
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT analysis_run_id, analysis_type, timestamp, metric_key, metric_value, unit, input_context
                FROM legacy_analysis_runs_view
                WHERE experiment_id = ?
                ORDER BY timestamp, analysis_run_id
                """, (experiment_id,))
            rows = cursor.fetchall()
            if not rows:
                return None
            runs: Dict[int, Dict[str, Any]] = {}
            for run_id, analysis_type, timestamp_value, metric_key, metric_value, unit, input_context in rows:
                entry = runs.setdefault(run_id,
                                        {'type': analysis_type or 'Unknown', 'timestamp': timestamp_value, 'data': {}})
                if metric_key:
                    coerced = self._coerce_metric_value(metric_value)
                    entry['data'][metric_key] = coerced
                if input_context is not None:
                    entry.setdefault('_input_context', input_context)
            results: List[Dict[str, Any]] = []
            for payload in runs.values():
                data = payload['data']
                raw_context = payload.get('_input_context')
                if not data and raw_context:
                    try:
                        context_obj = json.loads(raw_context)
                        raw_payload = context_obj.get('raw_result_data')
                        if isinstance(raw_payload, str):
                            try:
                                parsed_raw = json.loads(raw_payload)
                            except json.JSONDecodeError:
                                parsed_raw = {'raw': raw_payload}
                            if isinstance(parsed_raw, dict):
                                data.update(parsed_raw)
                            else:
                                data['value'] = parsed_raw
                    except json.JSONDecodeError:
                        data['raw_payload'] = raw_context
                results.append({'type': payload['type'], 'data': data})
            return results
        except sqlite3.OperationalError:
            return None
        except Exception as e:
            print(f"读取结构化分析结果失败: {e}")
            return None

    @staticmethod
    def _normalize_spectrum_role(spec_type: Optional[str]) -> Tuple[str, str, Optional[str]]:
        spec_type = (spec_type or 'Unknown').strip()
        if spec_type.lower() in {'signal', 'background', 'reference'}:
            return spec_type.capitalize(), spec_type.capitalize(), None
        if spec_type.startswith('Result_'):
            variant = spec_type.split('Result_', 1)[1] or None
            return spec_type, 'Result', variant
        return spec_type, spec_type, None

    def _get_or_create_instrument_state(
            self,
            cursor: sqlite3.Cursor,
            instrument_info: Optional[Dict[str, Any]],
    ) -> Optional[int]:
        if not instrument_info:
            return None

        device_serial = instrument_info.get('device_serial')
        integration_time = instrument_info.get('integration_time_ms')
        averaging = instrument_info.get('averaging')
        temperature = instrument_info.get('temperature')
        signature = canonicalize_instrument_info(instrument_info)
        if not signature:
            signature = {}
        config_json = serialize_payload(signature)
        try:
            cursor.execute(
                """
                SELECT instrument_state_id
                FROM instrument_states
                WHERE config_json = ? AND is_active = 1
                LIMIT 1
                """,
                (config_json,),
            )
            row = cursor.fetchone()
            if row:
                return row[0]
            captured_at = time.strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                """
                INSERT INTO instrument_states (
                    device_serial,
                    integration_time_ms,
                    averaging,
                    temperature,
                    config_json,
                    captured_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (device_serial, integration_time, averaging, temperature, config_json, captured_at),
            )
            return cursor.lastrowid
        except sqlite3.OperationalError:
            return None
        except Exception as e:
            print(f"记录仪器状态失败: {e}")
            return None

    def _get_or_create_processing_snapshot(
            self,
            cursor: sqlite3.Cursor,
            processing_info: Optional[Dict[str, Any]],
    ) -> Optional[int]:
        if not processing_info:
            return None

        name = processing_info.get('name') or 'unspecified'
        version = processing_info.get('version') or '1.0'
        normalized_info = dict(processing_info)
        normalized_info['name'] = name
        normalized_info['version'] = version
        canonical = canonicalize_processing_info(normalized_info)
        parameters = canonical.get('parameters', {})
        parameters_json = json.dumps(parameters, ensure_ascii=False, sort_keys=True)

        try:
            cursor.execute(
                """
                SELECT processing_config_id
                FROM processing_snapshots
                WHERE name = ? AND version = ? AND parameters_json = ? AND is_active = 1
                LIMIT 1
                """,
                (name, version, parameters_json),
            )
            row = cursor.fetchone()
            if row:
                return row[0]
            created_at = time.strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                """
                INSERT INTO processing_snapshots (
                    name,
                    version,
                    parameters_json,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (name, version, parameters_json, created_at),
            )
            return cursor.lastrowid
        except sqlite3.OperationalError:
            return None
        except Exception as e:
            print(f"记录处理配置失败: {e}")
            return None

    def _store_structured_spectrum(
            self,
            cursor: sqlite3.Cursor,
            experiment_id: int,
            spec_type: Optional[str],
            timestamp: str,
            wavelengths: List[float],
            intensities: List[float],
            *,
            batch_run_item_id: Optional[int] = None,
            instrument_info: Optional[Dict[str, Any]] = None,
            processing_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        try:
            wave_blob = json.dumps(wavelengths, separators=(',', ':')).encode('utf-8')
            inten_blob = json.dumps(intensities, separators=(',', ':')).encode('utf-8')
            checksum = hashlib.sha256(wave_blob + b'|' + inten_blob).hexdigest()
            cursor.execute(
                """
                INSERT INTO spectrum_data (wavelengths_blob, intensities_blob, points_count, hash, storage_format, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sqlite3.Binary(wave_blob), sqlite3.Binary(inten_blob), len(wavelengths), checksum, 'json', timestamp),
            )
            data_id = cursor.lastrowid
            instrument_state_id = self._get_or_create_instrument_state(cursor, instrument_info)
            processing_config_id = self._get_or_create_processing_snapshot(cursor, processing_info)
            capture_label, spectrum_role, result_variant = self._normalize_spectrum_role(spec_type)
            cursor.execute(
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
                    region_start_nm,
                    region_end_nm,
                    note,
                    quality_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    experiment_id,
                    batch_run_item_id,
                    capture_label,
                    spectrum_role,
                    result_variant,
                    data_id,
                    instrument_state_id,
                    processing_config_id,
                    timestamp,
                    timestamp,
                    'good'
                ),
            )
            return cursor.lastrowid
        except sqlite3.OperationalError:
            return None
        except Exception as e:
            print(f"写入结构化光谱失败: {e}")
            return None

    @staticmethod
    def _stringify_metric_value(value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _store_structured_analysis(
            self,
            cursor: sqlite3.Cursor,
            *,
            result_id: int,
            experiment_id: int,
            analysis_type: Optional[str],
            timestamp: str,
            result_data: Any,
            source_ids: List[Any],
    ) -> Optional[int]:
        try:
            analysis_type = analysis_type or 'Unknown'
            context = {
                'legacy_result_id': result_id,
                'source_spectrum_ids': source_ids,
                'raw_result_data': result_data,
            }
            input_context = json.dumps(context, ensure_ascii=False)

            cursor.execute(
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
                (experiment_id, analysis_type, 'legacy', 'completed', timestamp, timestamp, input_context),

            )

            run_id = cursor.lastrowid

            metrics_written = False

            if isinstance(result_data, dict):

                primary_assigned = False

                for key, value in result_data.items():

                    metric_str = self._stringify_metric_value(value)

                    is_numeric = isinstance(value, (int, float))

                    cursor.execute(

                        """

                        INSERT INTO analysis_metrics (analysis_run_id, metric_key, metric_value, unit, is_primary)

                        VALUES (?, ?, ?, ?, ?)

                        """,

                        (run_id, str(key), metric_str, None, 1 if is_numeric and not primary_assigned else 0),

                    )

                    if is_numeric and not primary_assigned:
                        primary_assigned = True

                    metrics_written = True

            else:

                metric_str = self._stringify_metric_value(result_data)

                cursor.execute(

                    """

                    INSERT INTO analysis_metrics (analysis_run_id, metric_key, metric_value, unit, is_primary)

                    VALUES (?, ?, ?, ?, ?)

                    """,

                    (run_id, 'value', metric_str, None, 1),

                )

                metrics_written = True

            if not metrics_written:
                cursor.execute(

                    """

                    INSERT INTO analysis_metrics (analysis_run_id, metric_key, metric_value, unit, is_primary)

                    VALUES (?, ?, ?, ?, ?)

                    """,

                    (run_id, 'raw_payload', json.dumps(result_data, ensure_ascii=False), None, 0),

                )

            cursor.execute(

                "UPDATE analysis_results SET analysis_run_id = ? WHERE result_id = ?",

                (run_id, result_id),

            )

            return run_id

        except sqlite3.OperationalError:

            return None

        except Exception as e:

            print(f"写入结构化分析结果失败: {e}")

            return None

    def create_batch_run(self, project_id: int, name: str, layout_reference: str = "",

                         operator: str = "", notes: str = "") -> Optional[int]:

        if not self.conn:
            return None

        try:

            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            cursor = self.conn.cursor()

            cursor.execute(

                """

                INSERT INTO batch_runs (

                    project_id,

                    name,

                    layout_reference,

                    operator,

                    start_time,

                    status,

                    notes,

                    created_at,

                    updated_at

                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

                """,

                (

                    project_id,

                    name,

                    layout_reference,

                    operator,

                    timestamp,

                    "in_progress",

                    notes,

                    timestamp,

                    timestamp,

                ),

            )

            self.conn.commit()

            return cursor.lastrowid

        except Exception as e:

            print(f"创建批量运行记录失败: {e}")

            return None

    def update_batch_run(self, batch_run_id: int, status: Optional[str] = None,

                         end_time: Optional[str] = None) -> bool:

        if not self.conn:
            return False

        fields = []

        params: List[Any] = []

        if status:
            fields.append("status = ?")

            params.append(status)

        if end_time:

            fields.append("end_time = ?")

            params.append(end_time)

        elif status in {"completed", "failed", "aborted"}:

            fields.append("end_time = ?")

            params.append(time.strftime("%Y-%m-%d %H:%M:%S"))

        fields.append("updated_at = ?")

        params.append(time.strftime("%Y-%m-%d %H:%M:%S"))

        params.append(batch_run_id)

        try:

            cursor = self.conn.cursor()

            cursor.execute(

                f"UPDATE batch_runs SET {', '.join(fields)} WHERE batch_run_id = ?",

                params,

            )

            self.conn.commit()

            return True

        except Exception as e:

            print(f"更新批量运行状态失败: {e}")

            return False

    def create_batch_items(self, batch_run_id: int, layout_data: Dict[str, Dict[str, Any]]) -> Dict[str, int]:

        mapping: Dict[str, int] = {}

        if not self.conn:
            return mapping

        try:

            cursor = self.conn.cursor()

            for sequence_no, (position_label, meta) in enumerate(sorted(layout_data.items()), start=1):
                metadata = json.dumps(meta, ensure_ascii=False)

                cursor.execute(

                    """

                    INSERT INTO batch_run_items (

                        batch_run_id,

                        position_label,

                        sequence_no,

                        sample_id,

                        planned_stage,

                        actual_stage,

                        experiment_id,

                        capture_count,

                        status,

                        last_captured_at,

                        metadata_json

                    ) VALUES (?, ?, ?, NULL, 'pending', NULL, NULL, 0, 'pending', NULL, ?)

                    """,

                    (batch_run_id, position_label, sequence_no, metadata),

                )

                mapping[position_label] = cursor.lastrowid

            self.conn.commit()

        except Exception as e:

            print(f"创建批量运行明细失败: {e}")

        return mapping

    def attach_experiment_to_batch_item(self, item_id: int, experiment_id: int):

        if not self.conn:
            return

        try:

            cursor = self.conn.cursor()

            cursor.execute(

                """

                UPDATE batch_run_items

                SET experiment_id = ?, status = 'in_progress'

                WHERE item_id = ?

                """,

                (experiment_id, item_id),

            )

            self.conn.commit()

        except Exception as e:

            print(f"关联批量明细与实验失败: {e}")

    def update_batch_item_progress(self, item_id: int, capture_count: Optional[int] = None,

                                   status: Optional[str] = None):

        if not self.conn:
            return

        fields = []

        params: List[Any] = []

        if capture_count is not None:
            fields.append("capture_count = ?")

            params.append(capture_count)

        if status:
            fields.append("status = ?")

            params.append(status)

            fields.append("actual_stage = ?")

            params.append(status)

        fields.append("last_captured_at = ?")

        params.append(time.strftime("%Y-%m-%d %H:%M:%S"))

        params.append(item_id)

        try:

            cursor = self.conn.cursor()

            cursor.execute(

                f"UPDATE batch_run_items SET {', '.join(fields)} WHERE item_id = ?",

                params,

            )

            self.conn.commit()

        except Exception as e:

            print(f"更新批量明细进度失败: {e}")

    def finalize_batch_item(self, item_id: int, status: str = "completed"):

        self.update_batch_item_progress(item_id, status=status)

    def update_batch_item_metadata(self, item_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:

        if not self.conn:
            return None

        try:

            cursor = self.conn.cursor()

            cursor.execute(

                "SELECT metadata_json FROM batch_run_items WHERE item_id = ?",

                (item_id,),

            )

            row = cursor.fetchone()

            metadata = {}

            if row and row[0]:

                try:

                    metadata = json.loads(row[0])

                except json.JSONDecodeError:

                    metadata = {}

            merged = _merge_nested_dict(metadata, updates)

            cursor.execute(

                "UPDATE batch_run_items SET metadata_json = ? WHERE item_id = ?",

                (json.dumps(merged, ensure_ascii=False), item_id),

            )

            self.conn.commit()

            return merged

        except Exception as e:

            print(f"更新批量明细元数据失败: {e}")

            return None

    def find_or_create_project(self, name, description=""):
        if not self.conn:
            print("数据库连接未建立")
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT project_id FROM projects WHERE name = ?", (name,))
            result = cursor.fetchone()
            if result:
                project_id = result[0]
                print(f"找到现有项目: {name} (ID: {project_id})")
                return project_id
            else:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT INTO projects (name, description, creation_date)
                    VALUES (?, ?, ?)
                """, (name, description, timestamp))
                self.conn.commit()
                project_id = cursor.lastrowid
                print(f"创建新项目: {name} (ID: {project_id})")
                return project_id
        except Exception as e:
            print(f"查找或创建项目失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_distinct_experiment_statuses(self):

        if not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT DISTINCT status FROM experiments WHERE status IS NOT NULL ORDER BY status")
            return [row[0] for row in cursor.fetchall() if row[0]]
        except Exception as e:
            print(f"获取实验状态列表失败: {e}")
            return []

    def get_all_projects(self):

        if not self.conn: return []

        try:

            cursor = self.conn.cursor()

            cursor.execute("SELECT project_id, name FROM projects ORDER BY name")

            return cursor.fetchall()

        except Exception as e:

            print(f"获取所有项目失败: {e}")

            return []

    def create_experiment(self, project_id, name, exp_type, timestamp, operator="", notes="", config_snapshot="{}"):

        if not self.conn: return None

        try:

            cursor = self.conn.cursor()

            cursor.execute("""

                INSERT INTO experiments (project_id, name, type, timestamp, operator, notes, config_snapshot)

                VALUES (?, ?, ?, ?, ?, ?, ?)

            """, (project_id, name, exp_type, timestamp, operator, notes, config_snapshot))

            self.conn.commit()

            return cursor.lastrowid

        except Exception as e:

            print(f"创建实验记录失败: {e}")

            return None

    def save_spectrum(

            self,

            experiment_id,

            spec_type,

            timestamp,

            wavelengths,

            intensities,

            *,

            batch_run_item_id: Optional[int] = None,

            instrument_info: Optional[Dict[str, Any]] = None,

            processing_info: Optional[Dict[str, Any]] = None,

    ):

        if not self.conn:
            return None

        try:

            cursor = self.conn.cursor()

            wavelengths_array = np.asarray(wavelengths)

            intensities_array = np.asarray(intensities)

            wl_list = wavelengths_array.tolist()

            int_list = intensities_array.tolist()

            # Structured storage (fallback to legacy table on failure)

            self._store_structured_spectrum(

                cursor,

                experiment_id,

                spec_type,

                timestamp,

                wl_list,

                int_list,

                batch_run_item_id=batch_run_item_id,

                instrument_info=instrument_info,

                processing_info=processing_info,

            )

            wl_str = json.dumps(wl_list)

            int_str = json.dumps(int_list)

            cursor.execute(
                """
                INSERT INTO spectra (experiment_id, type, timestamp, wavelengths, intensities)
                VALUES (?, ?, ?, ?, ?)
                """,
                (experiment_id, spec_type, timestamp, wl_str, int_str)
            )
            self.conn.commit()

            return cursor.lastrowid

        except Exception as e:

            self.conn.rollback()

            print(f"光谱数据入库失败: {e}")

            return None

    def save_analysis_result(self, experiment_id, analysis_type, result_data, source_spectrum_ids=None):

        if not self.conn:
            return None

        try:

            cursor = self.conn.cursor()

            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

            source_spectrum_ids = source_spectrum_ids or []

            result_str = json.dumps(result_data)

            source_ids_str = json.dumps(source_spectrum_ids)

            cursor.execute(

                """

                INSERT INTO analysis_results (experiment_id, analysis_type, timestamp, result_data, source_spectrum_ids)

                VALUES (?, ?, ?, ?, ?)

                """,

                (experiment_id, analysis_type, timestamp, result_str, source_ids_str)

            )

            result_id = cursor.lastrowid

            self._store_structured_analysis(

                cursor,

                result_id=result_id,

                experiment_id=experiment_id,

                analysis_type=analysis_type,

                timestamp=timestamp,

                result_data=result_data,

                source_ids=source_spectrum_ids,

            )

            self.conn.commit()

            return result_id

        except Exception as e:

            self.conn.rollback()

            print(f"保存分析结果失败: {e}")

            return None

    def search_experiments(
            self,
            project_id=-1,
            name_filter="",
            start_date="",
            end_date="",
            type_filter="",
            limit=None,
            sort_by="created_at",
            sort_desc=True,
            status_filter="",
            operator_filter="",
    ):

        """

        根据多个筛选条件搜索实验记录。

        返回一个包含实验详情的列表。

        """

        if not self.conn: return []

        try:

            cursor = self.conn.cursor()

            # 基础查询语句，使用 JOIN 来同时获取项目名称

            query = """

                SELECT e.experiment_id, p.name, e.name, e.type, COALESCE(e.created_at, e.timestamp) AS created_at, e.operator, e.status

                FROM experiments e

                LEFT JOIN projects p ON e.project_id = p.project_id

            """

            conditions = []

            params = []

            # 动态构建 WHERE 子句

            if project_id != -1:
                conditions.append("e.project_id = ?")

                params.append(project_id)

            if name_filter:
                conditions.append("e.name LIKE ?")

                params.append(f"%{name_filter}%")  # 使用 LIKE 实现模糊搜索

            if start_date:
                conditions.append("DATE(COALESCE(e.created_at, e.timestamp)) >= ?")

                params.append(start_date)

            if end_date:
                conditions.append("DATE(COALESCE(e.created_at, e.timestamp)) <= ?")

                params.append(end_date)

            if type_filter and type_filter != "All Types":  # 假设 "All Types" 是UI上的默认值

                conditions.append("e.type = ?")

                params.append(type_filter)

            if status_filter:
                conditions.append("e.status = ?")

                params.append(status_filter)

            if operator_filter:
                conditions.append("e.operator LIKE ?")

                params.append(f"%{operator_filter}%")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            order_map = {

                "experiment_id": "e.experiment_id",

                "created_at": "COALESCE(e.created_at, e.timestamp)",

            }

            order_expr = order_map.get(sort_by, "COALESCE(e.created_at, e.timestamp)")

            direction = "DESC" if sort_desc else "ASC"

            query += f" ORDER BY {order_expr} {direction}"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor.execute(query, params)

            return cursor.fetchall()



        except Exception as e:

            print(f"搜索实验时发生错误: {e}")

            return []

    def get_spectra_for_experiments(self, experiment_ids):

        """

        根据一个或多个实验ID，获取所有相关的光谱数据。

        返回一个适合 AnalysisWindow 使用的字典列表。

        """

        if not self.conn or not experiment_ids:
            return []

        try:

            cursor = self.conn.cursor()

            # 使用占位符来安全地查询多个ID

            placeholders = ','.join('?' for _ in experiment_ids)

            query = f"""

                SELECT e.name, s.type, s.wavelengths, s.intensities

                FROM spectra s

                JOIN experiments e ON s.experiment_id = e.experiment_id

                WHERE s.experiment_id IN ({placeholders})

                ORDER BY s.experiment_id, s.spectrum_id

            """

            cursor.execute(query, experiment_ids)

            spectra_list = []

            for exp_name, spec_type, wl_json, int_json in cursor.fetchall():
                wavelengths = np.array(json.loads(wl_json))

                intensities = np.array(json.loads(int_json))

                # 创建一个唯一的、可读的名称

                unique_name = f"{exp_name}_{spec_type}"

                spectra_list.append({

                    'x': wavelengths,

                    'y': intensities,

                    'name': unique_name

                })

            return spectra_list



        except Exception as e:

            print(f"获取光谱数据时发生错误: {e}")

            return []

    def delete_experiments(self, experiment_ids):

        """

        根据一个或多个实验ID，删除实验及其所有关联的光谱和分析结果。

        操作被包裹在一个事务中，确保原子性。

        """

        if not self.conn or not experiment_ids:
            return False, "No connection or no IDs provided."

        placeholders = ','.join('?' for _ in experiment_ids)

        try:

            cursor = self.conn.cursor()

            # 开启一个事务

            cursor.execute("BEGIN TRANSACTION")

            # 1. 删除关联的分析结果

            cursor.execute(f"DELETE FROM analysis_results WHERE experiment_id IN ({placeholders})", experiment_ids)

            # 2. 删除关联的光谱

            cursor.execute(f"DELETE FROM spectra WHERE experiment_id IN ({placeholders})", experiment_ids)

            # 3. 删除实验本身

            cursor.execute(f"DELETE FROM experiments WHERE experiment_id IN ({placeholders})", experiment_ids)

            # 提交事务

            self.conn.commit()

            print(f"成功删除了 {len(experiment_ids)} 个实验及其关联数据。")

            return True, ""



        except Exception as e:

            # 如果任何一步出错，回滚所有更改

            self.conn.rollback()

            error_message = f"删除实验时发生错误: {e}"

            print(error_message)

            return False, error_message

    def get_full_experiment_data(self, experiment_id):

        """

        【已重构】获取单个实验的所有相关数据。

        光谱数据现在按时间戳分组，以代表单个“保存事件”。

        """

        if not self.conn: return None

        try:

            cursor = self.conn.cursor()

            # 1. 获取实验元数据 (不变)

            cursor.execute("SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,))

            exp_meta = cursor.fetchone()

            if not exp_meta: return None

            exp_data = {

                'metadata': {

                    'experiment_id': exp_meta[0], 'project_id': exp_meta[1], 'name': exp_meta[2],

                    'type': exp_meta[3], 'timestamp': exp_meta[4], 'operator': exp_meta[5],

                    'notes': exp_meta[6], 'config_snapshot': json.loads(exp_meta[7] or '{}')

                },

                'spectra_sets': [],  # 【修改】从 'spectra' 改为 'spectra_sets'

                'results': []  # 分析结果部分不变

            }

            # 2. 使用新的光谱结构（如已生成）优先返回

            structured_spectra = self._fetch_structured_spectra(experiment_id)

            if structured_spectra:

                exp_data['spectra_sets'] = structured_spectra

            else:

                cursor.execute(

                    "SELECT type, wavelengths, intensities, timestamp FROM spectra WHERE experiment_id = ? ORDER BY timestamp",

                    (experiment_id,))

                spectra_by_timestamp = defaultdict(dict)

                for spec_type, wl_json, int_json, timestamp in cursor.fetchall():
                    spectra_by_timestamp[timestamp]['wavelengths'] = json.loads(wl_json)

                    spectra_by_timestamp[timestamp][spec_type] = json.loads(int_json)

                exp_data['spectra_sets'] = list(spectra_by_timestamp.values())

            # 3. 使用结构化分析结果（如已生成）

            structured_analysis = self._fetch_structured_analysis(experiment_id)

            if structured_analysis:

                exp_data['results'] = structured_analysis

            else:

                cursor.execute("SELECT analysis_type, result_data FROM analysis_results WHERE experiment_id = ?",

                               (experiment_id,))

                for analysis_type, result_json in cursor.fetchall():
                    exp_data['results'].append({

                        'type': analysis_type,

                        'data': json.loads(result_json)

                    })

            return exp_data



        except Exception as e:

            print(f"获取完整实验数据时出错: {e}")

            return None

    def close(self):

        if self.conn:
            self.conn.close()

            self.conn = None
