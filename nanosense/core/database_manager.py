# nanosense/core/database_manager.py
import sqlite3
import os
import json
import time
import numpy as np
from collections import defaultdict

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
            self._init_complete = True
            print(f"数据库已连接并初始化于: {db_path}")

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

    def find_or_create_project(self, name, description=""):
        if not self.conn: return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT project_id FROM projects WHERE name = ?", (name,))
            result = cursor.fetchone()
            if result:
                return result[0]
            else:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT INTO projects (name, description, creation_date)
                    VALUES (?, ?, ?)
                """, (name, description, timestamp))
                self.conn.commit()
                return cursor.lastrowid
        except Exception as e:
            print(f"查找或创建项目失败: {e}")
            return None

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

    def save_spectrum(self, experiment_id, spec_type, timestamp, wavelengths, intensities):
        if not self.conn: return None
        try:
            cursor = self.conn.cursor()
            wl_str = json.dumps(wavelengths.tolist())
            int_str = json.dumps(intensities.tolist())
            cursor.execute("""
                INSERT INTO spectra (experiment_id, type, timestamp, wavelengths, intensities)
                VALUES (?, ?, ?, ?, ?)
            """, (experiment_id, spec_type, timestamp, wl_str, int_str))
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            print(f"保存光谱数据失败: {e}")
            return None

    def save_analysis_result(self, experiment_id, analysis_type, result_data, source_spectrum_ids=[]):
        if not self.conn: return None
        try:
            cursor = self.conn.cursor()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            result_str = json.dumps(result_data)
            source_ids_str = json.dumps(source_spectrum_ids)
            cursor.execute("""
                INSERT INTO analysis_results (experiment_id, analysis_type, timestamp, result_data, source_spectrum_ids)
                VALUES (?, ?, ?, ?, ?)
            """, (experiment_id, analysis_type, timestamp, result_str, source_ids_str))
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            print(f"保存分析结果失败: {e}")
            return None

    def search_experiments(self, project_id=-1, name_filter="", start_date="", end_date="", type_filter=""):
        """
        根据多个筛选条件搜索实验记录。
        返回一个包含实验详情的列表。
        """
        if not self.conn: return []

        try:
            cursor = self.conn.cursor()

            # 基础查询语句，使用 JOIN 来同时获取项目名称
            query = """
                SELECT e.experiment_id, p.name, e.name, e.type, e.timestamp, e.operator
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
                conditions.append("DATE(e.timestamp) >= ?")
                params.append(start_date)

            if end_date:
                conditions.append("DATE(e.timestamp) <= ?")
                params.append(end_date)

            if type_filter and type_filter != "All Types":  # 假设 "All Types" 是UI上的默认值
                conditions.append("e.type = ?")
                params.append(type_filter)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY e.timestamp DESC"  # 按时间倒序排列

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

            # 2. 【核心重构】获取所有关联的光谱，并按时间戳分组
            cursor.execute(
                "SELECT type, wavelengths, intensities, timestamp FROM spectra WHERE experiment_id = ? ORDER BY timestamp",
                (experiment_id,))

            spectra_by_timestamp = defaultdict(dict)
            for spec_type, wl_json, int_json, timestamp in cursor.fetchall():
                # 使用时间戳作为分组的键
                spectra_by_timestamp[timestamp]['wavelengths'] = json.loads(wl_json)
                spectra_by_timestamp[timestamp][spec_type] = json.loads(int_json)

            # 将分组后的字典转换为列表
            exp_data['spectra_sets'] = list(spectra_by_timestamp.values())

            # 3. 获取所有关联的分析结果 (不变)
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