# nanosense/gui/database_explorer.py
import os
from typing import Any, Dict, List, Optional

import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QDialogButtonBox,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
    QWidget,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QDateEdit,
    QAbstractItemView,
    QMessageBox,
    QTabWidget,
    QTextEdit,
    QCheckBox,
)
from ..utils.file_io import export_data_custom
from PyQt5.QtCore import QEvent, QDate, Qt, pyqtSignal
try:  # 部分旧版 PyQt5 未提供 QFutureWatcher
    from PyQt5.QtCore import QFutureWatcher
except ImportError:
    QFutureWatcher = None  # type: ignore

try:
    from PyQt5 import QtConcurrent  # type: ignore
except ImportError:
    QtConcurrent = None  # type: ignore

import csv
from datetime import datetime
import time
from nanosense.core.data_access import ExplorerDataAccess
from nanosense.core.reference_templates import load_reference_templates, resolve_template_path


class SortableTableWidgetItem(QTableWidgetItem):
    """Table widget item that keeps a sortable key separate from display text."""
    def __init__(self, display_text: str, sort_key):
        super().__init__(display_text)
        self._sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SortableTableWidgetItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)

class DatabaseExplorerDialog(QDialog):
    load_spectra_requested = pyqtSignal(list)#定义一个信号
    def __init__(self, parent=None):
        super().__init__(parent)
        # show standard window controls
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)

        # 从父窗口 (AppWindow) 获取 db_manager
        if parent and hasattr(parent, 'db_manager'):
            self.db_manager = self.parent().db_manager
        else:
            self.db_manager = None
        self.app_settings = getattr(parent, "app_settings", {}) if parent and hasattr(parent, "app_settings") else {}
        self.data_access = None
        if self.db_manager and hasattr(self.db_manager, "conn") and self.db_manager.conn:
            self.data_access = ExplorerDataAccess(self.db_manager.conn)

        self._async_supported = bool(QFutureWatcher and QtConcurrent)
        self._search_token = None
        self._search_watcher: Optional["QFutureWatcher"] = None
        self._detail_token = None
        self._detail_watcher: Optional["QFutureWatcher"] = None
        self._current_batch_rows: List[Dict[str, Any]] = []
        self._filtered_batch_rows: List[Dict[str, Any]] = []
        template_setting = None
        if isinstance(self.app_settings, dict):
            template_setting = self.app_settings.get("reference_template_path")
        template_path = resolve_template_path(template_setting)
        if isinstance(self.app_settings, dict):
            self.app_settings["reference_template_path"] = str(template_path)
        self.reference_template_path = str(template_path)
        self.reference_templates = load_reference_templates(self.reference_template_path)

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()
        self._populate_initial_data()
        self._clear_detail_tabs()

    def _init_ui(self):
        self.setMinimumSize(1200, 700)
        main_layout = QHBoxLayout(self)

        # --- 左侧：筛选控制面板 ---
        filter_panel = QWidget()
        filter_panel.setFixedWidth(340)
        filter_layout = QVBoxLayout(filter_panel)

        self.filter_group = QGroupBox()
        form_layout = QFormLayout(self.filter_group)
        form_layout.setSpacing(10)

        self.project_combo = QComboBox()
        self.exp_name_edit = QLineEdit()
        self.start_date_edit = QDateEdit(calendarPopup=True)
        self.end_date_edit = QDateEdit(calendarPopup=True)
        self.exp_type_combo = QComboBox()
        self.status_combo = QComboBox()
        self.operator_edit = QLineEdit()

        self.project_label = QLabel()
        self.exp_name_label = QLabel()
        self.date_range_label = QLabel()
        self.exp_type_label = QLabel()
        self.status_label = QLabel()
        self.operator_label = QLabel()

        form_layout.addRow(self.project_label, self.project_combo)
        form_layout.addRow(self.exp_name_label, self.exp_name_edit)
        form_layout.addRow(self.date_range_label, self.start_date_edit)
        form_layout.addRow(QLabel(), self.end_date_edit)  # "To" label for date range
        form_layout.addRow(self.exp_type_label, self.exp_type_combo)
        form_layout.addRow(self.status_label, self.status_combo)
        form_layout.addRow(self.operator_label, self.operator_edit)

        self.search_button = QPushButton()
        self.reset_button = QPushButton()

        filter_layout.addWidget(self.filter_group)
        filter_layout.addWidget(self.search_button)
        filter_layout.addWidget(self.reset_button)
        filter_layout.addStretch()

        # --- 右侧：结果显示区域 ---
        results_panel = QWidget()
        results_layout = QVBoxLayout(results_panel)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(7)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionsClickable(True)
        self.results_table.horizontalHeader().setSortIndicatorShown(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSortingEnabled(True)

        self.detail_tabs = QTabWidget()

        # Experiment detail tab
        experiment_tab = QWidget()
        experiment_layout = QFormLayout(experiment_tab)
        experiment_layout.setSpacing(6)
        self.experiment_detail_labels = {}
        detail_fields = [
            ("project_name", self.tr("Project")),
            ("name", self.tr("Experiment Name")),
            ("type", self.tr("Type")),
            ("status", self.tr("Status")),
            ("operator", self.tr("Operator")),
            ("created_at", self.tr("Created At")),
            ("updated_at", self.tr("Updated At")),
            ("timestamp", self.tr("Legacy Timestamp")),
        ]
        for key, label_text in detail_fields:
            value_label = QLabel(self.tr("—"))
            value_label.setObjectName(f"detail_{key}")
            experiment_layout.addRow(label_text, value_label)
            self.experiment_detail_labels[key] = value_label
        self.experiment_notes = QTextEdit()
        self.experiment_notes.setReadOnly(True)
        experiment_layout.addRow(self.tr("Notes"), self.experiment_notes)
        self.detail_tabs.addTab(experiment_tab, self.tr("Experiment Details"))

        # Spectra tab
        spectra_tab = QWidget()
        spectra_layout = QVBoxLayout(spectra_tab)
        self.spectra_table = QTableWidget()
        self.spectra_table.setColumnCount(9)
        self.spectra_table.setHorizontalHeaderLabels(
            [
                self.tr("Set ID"),
                self.tr("Capture Label"),
                self.tr("Role"),
                self.tr("Variant"),
                self.tr("Captured At"),
                self.tr("Created At"),
                self.tr("Instrument ID"),
                self.tr("Processing ID"),
                self.tr("Quality"),
            ]
        )
        self.spectra_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.spectra_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.spectra_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        spectra_layout.addWidget(self.spectra_table)
        self.detail_tabs.addTab(spectra_tab, self.tr("Spectra"))

        # Batch overview tab
        batch_tab = QWidget()
        batch_layout = QVBoxLayout(batch_tab)
        self.batch_filter_bar = QHBoxLayout()
        self.batch_status_label = QLabel()
        self.batch_status_filter = QComboBox()
        self.batch_status_filter.setMinimumWidth(140)
        self.batch_status_filter.addItem(self.tr("All Status"), "")
        self.batch_position_label = QLabel()
        self.batch_position_filter = QLineEdit()
        self.batch_position_filter.setPlaceholderText(self.tr("Filter by position label"))
        self.batch_apply_filter_button = QPushButton(self.tr("Apply"))
        self.batch_clear_filter_button = QPushButton(self.tr("Clear"))
        self.batch_review_only_checkbox = QCheckBox()
        self.batch_filter_bar.addWidget(self.batch_status_label)
        self.batch_filter_bar.addWidget(self.batch_status_filter)
        self.batch_filter_bar.addWidget(self.batch_position_label)
        self.batch_filter_bar.addWidget(self.batch_position_filter, 1)
        self.batch_filter_bar.addWidget(self.batch_apply_filter_button)
        self.batch_filter_bar.addWidget(self.batch_clear_filter_button)
        self.batch_filter_bar.addWidget(self.batch_review_only_checkbox)
        self.batch_filter_bar.addStretch()
        batch_layout.addLayout(self.batch_filter_bar)
        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(10)
        self.batch_table.setHorizontalHeaderLabels(
            [
                self.tr("Item ID"),
                self.tr("Batch ID"),
                self.tr("Batch Name"),
                self.tr("Batch Status"),
                self.tr("Position"),
                self.tr("Item Status"),
                self.tr("Capture Count"),
                self.tr("Last Captured At"),
                self.tr("SAM Angle (°)"),
                self.tr("QA Flag"),
            ]
        )
        self.batch_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.batch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        batch_layout.addWidget(self.batch_table)
        self.batch_template_group = QGroupBox()
        template_layout = QFormLayout(self.batch_template_group)
        self.batch_template_source_label = QLabel()
        self.batch_template_source_value = QLabel("-")
        self.batch_template_name_label = QLabel()
        self.batch_template_name_value = QLabel("-")
        self.batch_template_threshold_label = QLabel()
        self.batch_template_threshold_value = QLabel("-")
        self.batch_template_preview_button = QPushButton()
        self.batch_template_preview_button.setEnabled(False)
        template_layout.addRow(self.batch_template_source_label, self.batch_template_source_value)
        template_layout.addRow(self.batch_template_name_label, self.batch_template_name_value)
        template_layout.addRow(self.batch_template_threshold_label, self.batch_template_threshold_value)
        template_layout.addRow(self.batch_template_preview_button)
        batch_layout.addWidget(self.batch_template_group)
        self.detail_tabs.addTab(batch_tab, self.tr("Batch Overview"))

        self.results_hint_label = QLabel()
        self.results_hint_label.setText("")

        action_buttons_layout = QHBoxLayout()
        self.load_spectra_button = QPushButton()
        self.export_button = QPushButton()
        self.delete_button = QPushButton()

        action_buttons_layout.addStretch()
        action_buttons_layout.addWidget(self.load_spectra_button)
        action_buttons_layout.addWidget(self.export_button)
        action_buttons_layout.addWidget(self.delete_button)

        results_layout.addWidget(self.results_table)
        results_layout.addWidget(self.results_hint_label)
        results_layout.addWidget(self.detail_tabs)
        results_layout.addLayout(action_buttons_layout)

        main_layout.addWidget(filter_panel)
        main_layout.addWidget(results_panel, 1)

    def _connect_signals(self):
        # 目前只连接占位符，后续会实现具体功能
        self.search_button.clicked.connect(self._search_database)
        self.reset_button.clicked.connect(self._reset_filters)
        self.load_spectra_button.clicked.connect(self._load_selected_spectra)
        self.export_button.clicked.connect(self._export_selected_data)
        self.status_combo.currentIndexChanged.connect(self._search_database)
        self.operator_edit.textChanged.connect(self._search_database)
        self.results_table.itemSelectionChanged.connect(self._refresh_detail_tabs)
        self.delete_button.clicked.connect(self._delete_selected_experiments)
        self.batch_status_filter.currentIndexChanged.connect(self._apply_batch_filters)
        self.batch_apply_filter_button.clicked.connect(self._apply_batch_filters)
        self.batch_clear_filter_button.clicked.connect(self._reset_batch_filters)
        self.batch_position_filter.returnPressed.connect(self._apply_batch_filters)
        self.batch_review_only_checkbox.stateChanged.connect(self._apply_batch_filters)
        self.batch_table.itemSelectionChanged.connect(self._update_batch_template_panel)
        self.batch_template_preview_button.clicked.connect(self._show_template_preview_from_selection)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Database Explorer"))

        # 筛选面板
        self.filter_group.setTitle(self.tr("Filter Criteria"))
        self.project_label.setText(self.tr("Project:"))
        self.exp_name_label.setText(self.tr("Experiment Name:"))
        self.date_range_label.setText(self.tr("Date Range (From/To):"))
        self.exp_type_label.setText(self.tr("Experiment Type:"))
        self.status_label.setText(self.tr("Experiment Status:"))
        self.operator_label.setText(self.tr("Operator contains:"))
        self.operator_edit.setPlaceholderText(self.tr("Operator contains"))
        self._populate_status_filter()
        self.batch_status_label.setText(self.tr("Batch Status:"))
        self.batch_position_label.setText(self.tr("Position:"))
        self.batch_position_filter.setPlaceholderText(self.tr("Filter by position label"))
        self.batch_apply_filter_button.setText(self.tr("Apply"))
        self.batch_clear_filter_button.setText(self.tr("Clear"))
        self.batch_review_only_checkbox.setText(self.tr("Show needs review only"))
        self.batch_template_group.setTitle(self.tr("Reference Details"))
        self.batch_template_source_label.setText(self.tr("Source:"))
        self.batch_template_name_label.setText(self.tr("Template:"))
        self.batch_template_threshold_label.setText(self.tr("Threshold:"))
        self.batch_template_preview_button.setText(self.tr("Preview Template"))
        self.search_button.setText(self.tr("Search"))
        self.reset_button.setText(self.tr("Reset Filters"))

        # 结果表格
        self.results_table.setHorizontalHeaderLabels([            self.tr("Exp. ID"), self.tr("Project"), self.tr("Experiment Name"),            self.tr("Type"), self.tr("Timestamp"), self.tr("Operator"), self.tr("Status")        ])

        # 操作按钮
        self.load_spectra_button.setText(self.tr("Load Spectra to Analysis"))
        self.export_button.setText(self.tr("Export Selected..."))
        self.delete_button.setText(self.tr("Delete Selected"))

    def _populate_initial_data(self):
        """用数据库中的现有数据填充筛选器"""
        if not self.db_manager:
            self.search_button.setEnabled(False)
            return

        # 填充项目下拉框
        self.project_combo.clear()
        self.project_combo.addItem(self.tr("All Projects"), -1)  # 添加一个"全部"选项
        projects = self.db_manager.get_all_projects()
        for project_id, name in projects:
            self.project_combo.addItem(name, project_id)

        # 设置日期范围
        self.start_date_edit.setDate(QDate.currentDate().addYears(-1))
        self.end_date_edit.setDate(QDate.currentDate())

        # 填充实验类型
        self.exp_type_combo.clear()
        self.exp_type_combo.addItems([self.tr("All Types"), "Single Measurement"])
        self._populate_status_filter()
        self.operator_edit.clear()
        self.status_combo.setCurrentIndex(0)

    def _populate_status_filter(self):
        self.status_combo.blockSignals(True)
        try:
            self.status_combo.clear()
            self.status_combo.addItem(self.tr("All Status"), "")
            statuses = []
            if self.db_manager and hasattr(self.db_manager, "get_distinct_experiment_statuses"):
                statuses = self.db_manager.get_distinct_experiment_statuses()
            for status in statuses:
                if status:
                    self.status_combo.addItem(status, status)
        finally:
            self.status_combo.blockSignals(False)

    @staticmethod
    def _text_sort_key(display_text: str):
        normalized = display_text or ""
        return (normalized == "", normalized.lower())

    @staticmethod
    def _numeric_sort_key(value: Any):
        if value in (None, ""):
            return (1, 0.0)
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            try:
                return (0, float(str(value)))
            except (TypeError, ValueError):
                return (1, 0.0)

    @staticmethod
    def _datetime_sort_key(value: Any):
        if not value:
            return (1, 0.0)
        if isinstance(value, datetime):
            return (0, value.timestamp())
        text_value = str(value)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text_value, fmt)
                return (0, parsed.timestamp())
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(text_value)
            return (0, parsed.timestamp())
        except ValueError:
            return (1, text_value.lower())

    def _create_results_item(self, value: Any, column_index: int) -> QTableWidgetItem:
        display_text = "" if value in (None, "") else str(value)
        if column_index == 0:
            sort_key = self._numeric_sort_key(value)
        elif column_index == 4:
            sort_key = self._datetime_sort_key(value)
        else:
            sort_key = self._text_sort_key(display_text)
        return SortableTableWidgetItem(display_text, sort_key)

    def _search_database(self):
        """执行查询并刷新实验列表（异步以避免阻塞 UI）。"""
        if not self.db_manager:
            return
        filters = self._collect_filters()
        if self._async_supported:
            self._start_async_search(filters)
        else:
            result = self._execute_search(filters)
            if result.get("error"):
                QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr("Search failed: {0}").format(result["error"]),
                )
                self.results_hint_label.setText(self.tr("Query failed. Please adjust filters and retry."))
                return
            self._apply_search_results(result["results"], result["elapsed_ms"], result["timestamp"])

    def _collect_filters(self) -> Dict[str, Any]:
        project_id = self.project_combo.currentData()
        name_filter = self.exp_name_edit.text().strip()
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        type_text = self.exp_type_combo.currentText()
        type_filter = type_text if type_text != self.tr("All Types") else ""
        status_filter = self.status_combo.currentData() or ""
        operator_filter = self.operator_edit.text().strip()
        return {
            "project_id": project_id,
            "name_filter": name_filter,
            "start_date": start_date,
            "end_date": end_date,
            "type_filter": type_filter,
            "status_filter": status_filter,
            "operator_filter": operator_filter,
        }

    def _set_search_in_progress(self, running: bool) -> None:
        self.search_button.setEnabled(not running)
        self.reset_button.setEnabled(not running)
        if running:
            self.results_hint_label.setText(self.tr("Running query..."))

    def _start_async_search(self, filters: Dict[str, Any]) -> None:
        self._set_search_in_progress(True)
        token = object()
        self._search_token = token
        watcher = QFutureWatcher()
        watcher.setParent(self)
        future = QtConcurrent.run(self._execute_search, filters)
        watcher.finished.connect(lambda tok=token, w=watcher: self._handle_search_finished(tok, w))
        self._search_watcher = watcher
        watcher.setFuture(future)

    def _execute_search(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"error": None}
        start_perf = time.perf_counter()
        try:
            results = self.db_manager.search_experiments(**filters)
        except Exception as exc:
            payload["error"] = str(exc)
            return payload
        elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload.update(
            {
                "results": results,
                "elapsed_ms": elapsed_ms,
                "timestamp": timestamp,
            }
        )
        return payload

    def _handle_search_finished(self, token, watcher: "QFutureWatcher") -> None:
        result = watcher.result()
        watcher.deleteLater()
        if token is not self._search_token:
            return
        self._search_watcher = None
        self._set_search_in_progress(False)
        if not result or result.get("error"):
            error_message = result.get("error") if isinstance(result, dict) else self.tr("Unknown error.")
            QMessageBox.critical(self, self.tr("Error"), self.tr("Search failed: {0}").format(error_message))
            self.results_hint_label.setText(self.tr("Query failed. Please adjust filters and retry."))
            return
        self._apply_search_results(result["results"], result["elapsed_ms"], result["timestamp"])

    def _apply_search_results(self, results, elapsed_ms: float, timestamp: str) -> None:
        header = self.results_table.horizontalHeader()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        if sort_section < 0:
            sort_section = None

        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)

        if not results:
            self.results_hint_label.setText(
                self.tr("No matching experiments. Refreshed at {0} (elapsed {1:.0f} ms)").format(
                    timestamp, elapsed_ms
                )
            )
            self._clear_detail_tabs()
            self.results_table.setSortingEnabled(True)
            return

        self.results_table.setRowCount(len(results))
        for row_index, row_data in enumerate(results):
            for col_index, cell_data in enumerate(row_data):
                item = self._create_results_item(cell_data, col_index)
                self.results_table.setItem(row_index, col_index, item)

        self.results_table.setSortingEnabled(True)
        if sort_section is not None and self.results_table.rowCount() > 0:
            self.results_table.sortItems(sort_section, sort_order)

        summary = self.tr("Found {0} experiment(s). Refreshed at {1} (elapsed {2:.0f} ms)").format(
            len(results), timestamp, elapsed_ms
        )
        self.results_hint_label.setText(summary)
        if self.results_table.rowCount() > 0:
            self.results_table.selectRow(0)
            self._refresh_detail_tabs()

    def _reset_filters(self):
        """【修改】重置所有筛选条件并重新搜索。"""
        self.exp_name_edit.clear()
        self._populate_initial_data() # 这个方法会重置下拉框和日期
        self._search_database() # 重置后立即执行一次搜索，显示所有结果

    def _load_selected_spectra(self):
        """获取选中的实验，并发出包含光谱数据的信号。"""
        selected_items = self.results_table.selectionModel().selectedRows()
        if not selected_items:
            self._export_current_results_to_csv()
            return

        # 从表格的第一列获取实验ID
        experiment_ids = []
        for index in selected_items:
            item = self.results_table.item(index.row(), 0)
            if not item:
                continue
            try:
                experiment_ids.append(int(item.text()))
            except ValueError:
                continue

        if not experiment_ids:
            QMessageBox.warning(self, self.tr("Info"), self.tr("Please select one or more experiments to export."))
            return

        if self.db_manager:
            spectra_list = self.db_manager.get_spectra_for_experiments(experiment_ids)
            if spectra_list:
                # 发出信号，将获取到的光谱列表传递出去
                self.load_spectra_requested.emit(spectra_list)
            else:
                QMessageBox.information(self, self.tr("Info"),
                                        self.tr("No spectra found for the selected experiments."))

    def _delete_selected_experiments(self):
        """处理删除选中实验的逻辑"""
        selected_items = self.results_table.selectionModel().selectedRows()
        if not selected_items:
            QMessageBox.warning(self, self.tr("Info"), self.tr("Please select one or more experiments to delete."))
            return

        # 从表格中获取ID和名称，用于在确认对话框中显示
        experiments_to_delete = []
        for index in selected_items:
            exp_id = int(self.results_table.item(index.row(), 0).text())
            exp_name = self.results_table.item(index.row(), 2).text()
            experiments_to_delete.append({'id': exp_id, 'name': exp_name})

        # 创建确认信息
        names_to_delete_str = "\n".join([f"- {exp['name']}" for exp in experiments_to_delete])
        question_text = self.tr(
            "Are you sure you want to permanently delete the following {0} experiment(s)?\n\n{1}\n\nThis action cannot be undone.").format(
            len(experiments_to_delete), names_to_delete_str
        )

        # 弹出确认对话框
        reply = QMessageBox.question(self, self.tr('Confirm Deletion'), question_text,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            ids_to_delete = [exp['id'] for exp in experiments_to_delete]

            if self.db_manager:
                success, error_message = self.db_manager.delete_experiments(ids_to_delete)

                if success:
                    QMessageBox.information(self, self.tr("Success"),
                                            self.tr("Selected experiments have been deleted."))
                    # 刷新表格视图
                    self._search_database()
                else:
                    QMessageBox.critical(self, self.tr("Error"),
                                         self.tr("Failed to delete experiments: {0}").format(error_message))

    def _export_selected_data(self):
        """【修改】处理导出选中实验的逻辑，调用新的主导出函数。"""
        selected_items = self.results_table.selectionModel().selectedRows()
        if not selected_items:
            QMessageBox.warning(self, self.tr("Info"), self.tr("Please select one or more experiments to export."))
            return

        # 收集所有选中实验的完整数据
        experiment_ids = [int(self.results_table.item(index.row(), 0).text()) for index in selected_items]
        all_data_to_export = []
        if self.db_manager:
            for exp_id in experiment_ids:
                exp_data = self.db_manager.get_full_experiment_data(exp_id)
                if exp_data:
                    all_data_to_export.append(exp_data)

        if not all_data_to_export:
            QMessageBox.warning(self, self.tr("Error"),
                                self.tr("Could not retrieve data for the selected experiments."))
            return

        # 调用新的主导出函数
        export_data_custom(self, all_data_to_export)

    def _export_current_results_to_csv(self):
        headers = [self.results_table.horizontalHeaderItem(col).text() for col in range(self.results_table.columnCount())]
        rows = []
        for row in range(self.results_table.rowCount()):
            first_item = self.results_table.item(row, 0)
            if not first_item:
                continue
            try:
                int(first_item.text())
            except ValueError:
                continue
            row_values = []
            for col in range(self.results_table.columnCount()):
                item = self.results_table.item(row, col)
                row_values.append(item.text() if item else "")
            rows.append(row_values)

        if not rows:
            QMessageBox.information(self, self.tr("Info"), self.tr("No experiment data available to export."))
            return

        default_name = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_path = os.path.join(os.path.expanduser("~"), f"experiments_{default_name}.csv")
        file_path, _ = QFileDialog.getSaveFileName(
            default_path,
            self.tr("Export Experiments Summary"),
            default_path,
            self.tr("CSV Files (*.csv)"),
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                writer.writerows(rows)
            QMessageBox.information(
                self,
                self.tr("Success"),
                self.tr("Exported {0} experiment rows to:\n{1}").format(len(rows), file_path)
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Failed to export data: {0}").format(str(exc)))

    def _get_selected_experiment_id(self) -> Optional[int]:
        selection_model = self.results_table.selectionModel()
        if not selection_model:
            return None
        selected_rows = selection_model.selectedRows()
        if not selected_rows:
            return None
        first_index = selected_rows[0]
        item = self.results_table.item(first_index.row(), 0)
        if not item:
            return None
        try:
            return int(item.text())
        except (TypeError, ValueError):
            return None

    def _refresh_detail_tabs(self):
        experiment_id = self._get_selected_experiment_id()
        if not experiment_id or not self.data_access:
            self._clear_detail_tabs()
            return
        if not self._async_supported:
            payload = self._load_detail_payload(experiment_id)
            if payload.get("error"):
                QMessageBox.warning(
                    self,
                    self.tr("Warning"),
                    self.tr("Failed to load detail tabs: {0}").format(payload["error"]),
                )
                return
            self._update_experiment_tab(payload.get("overview"))
            self._update_spectra_tab(payload.get("spectra") or [])
            self._update_batch_tab(payload.get("batch") or [])
            return

        token = object()
        self._detail_token = token
        self.detail_tabs.setEnabled(False)
        watcher = QFutureWatcher()
        watcher.setParent(self)
        future = QtConcurrent.run(self._load_detail_payload, experiment_id)
        watcher.finished.connect(lambda tok=token, w=watcher: self._handle_detail_finished(tok, w))
        self._detail_watcher = watcher
        watcher.setFuture(future)

    def _load_detail_payload(self, experiment_id: int) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"error": None}
        try:
            overview = self.data_access.fetch_experiment_overview(experiment_id)
            spectra_rows = self.data_access.fetch_spectrum_sets(experiment_id, limit=100)
            batch_rows = self.data_access.fetch_batch_overview(experiment_id)
        except Exception as exc:
            payload["error"] = str(exc)
            return payload
        payload.update(
            {
                "overview": overview,
                "spectra": spectra_rows,
                "batch": batch_rows,
            }
        )
        return payload

    def _handle_detail_finished(self, token, watcher: "QFutureWatcher") -> None:
        result = watcher.result()
        watcher.deleteLater()
        if token is not self._detail_token:
            return
        self._detail_watcher = None
        self.detail_tabs.setEnabled(True)

        if not result or result.get("error"):
            QMessageBox.warning(
                self,
                self.tr("Warning"),
                self.tr("Failed to load detail tabs: {0}").format(result.get("error", self.tr("Unknown error"))),
            )
            return

        self._update_experiment_tab(result.get("overview"))
        self._update_spectra_tab(result.get("spectra") or [])
        self._update_batch_tab(result.get("batch") or [])

    def _clear_detail_tabs(self):
        placeholder = self.tr("—")
        for label in getattr(self, "experiment_detail_labels", {}).values():
            label.setText(placeholder)
        if hasattr(self, "experiment_notes"):
            self.experiment_notes.clear()
        if hasattr(self, "spectra_table"):
            self.spectra_table.setRowCount(0)
        if hasattr(self, "batch_table"):
            self.batch_table.setRowCount(0)
        self._current_batch_rows = []
        self._filtered_batch_rows = []
        placeholder = self.tr("—")
        self.batch_template_source_value.setText(placeholder)
        self.batch_template_name_value.setText(placeholder)
        self.batch_template_threshold_value.setText(placeholder)
        self.batch_template_preview_button.setEnabled(False)

    def _update_experiment_tab(self, overview: Optional[Dict[str, Any]]):
        if not overview:
            self._clear_detail_tabs()
            return

        for key, label in self.experiment_detail_labels.items():
            value = overview.get(key)
            label.setText(str(value) if value not in (None, "") else self.tr("—"))

        notes_value = overview.get("notes")
        self.experiment_notes.setPlainText(str(notes_value) if notes_value else "")

    def _update_spectra_tab(self, spectra_rows: List[Dict[str, Any]]):
        self.spectra_table.setRowCount(0)
        if not spectra_rows:
            return

        columns = [
            "spectrum_set_id",
            "capture_label",
            "spectrum_role",
            "result_variant",
            "captured_at",
            "created_at",
            "instrument_state_id",
            "processing_config_id",
            "quality_flag",
        ]
        self.spectra_table.setRowCount(len(spectra_rows))
        for row_idx, row in enumerate(spectra_rows):
            for col_idx, key in enumerate(columns):
                value = row.get(key)
                item = QTableWidgetItem("" if value is None else str(value))
                self.spectra_table.setItem(row_idx, col_idx, item)

    def _update_batch_tab(self, batch_rows: List[Dict[str, Any]]):
        self._current_batch_rows = batch_rows or []
        self._populate_batch_status_filter()
        self._apply_batch_filters()

    def _populate_batch_status_filter(self):
        if not hasattr(self, "batch_status_filter"):
            return
        current_value = self.batch_status_filter.currentData()
        self.batch_status_filter.blockSignals(True)
        self.batch_status_filter.clear()
        self.batch_status_filter.addItem(self.tr("All Status"), "")
        statuses = sorted(
            {row.get("batch_status") for row in self._current_batch_rows if row.get("batch_status")}
        )
        for status in statuses:
            self.batch_status_filter.addItem(status, status)
        target_index = self.batch_status_filter.findData(current_value) if current_value else 0
        if target_index < 0:
            target_index = 0
        self.batch_status_filter.setCurrentIndex(target_index)
        self.batch_status_filter.blockSignals(False)

    def _reset_batch_filters(self):
        self.batch_status_filter.blockSignals(True)
        self.batch_status_filter.setCurrentIndex(0)
        self.batch_status_filter.blockSignals(False)
        self.batch_position_filter.clear()
        if hasattr(self, "batch_review_only_checkbox"):
            self.batch_review_only_checkbox.blockSignals(True)
            self.batch_review_only_checkbox.setChecked(False)
            self.batch_review_only_checkbox.blockSignals(False)
        self._apply_batch_filters()

    def _apply_batch_filters(self):
        rows = self._current_batch_rows or []
        status_value = self.batch_status_filter.currentData()
        position_text = self.batch_position_filter.text().strip().lower()
        review_only = (
            self.batch_review_only_checkbox.isChecked()
            if hasattr(self, "batch_review_only_checkbox")
            else False
        )
        filtered: List[Dict[str, Any]] = []
        for row in rows:
            if status_value and row.get("batch_status") != status_value:
                continue
            label_value = (row.get("position_label") or "").lower()
            if position_text and position_text not in label_value:
                continue
            if review_only and row.get("qa_flag") != "needs_review":
                continue
            filtered.append(row)
        self._filtered_batch_rows = filtered
        self._render_batch_rows(filtered)
        self._update_batch_template_panel()

    def _render_batch_rows(self, batch_rows: List[Dict[str, Any]]):
        self.batch_table.setRowCount(0)
        if not batch_rows:
            return
        columns = [
            "item_id",
            "batch_run_id",
            "batch_name",
            "batch_status",
            "position_label",
            "item_status",
            "capture_count",
            "last_captured_at",
            "sam_angle_deg",
            "qa_flag",
        ]
        self.batch_table.setRowCount(len(batch_rows))
        for row_idx, row in enumerate(batch_rows):
            for col_idx, key in enumerate(columns):
                value = row.get(key)
                if key == "sam_angle_deg" and value is not None:
                    value = f"{float(value):.2f}"
                item = QTableWidgetItem("" if value is None else str(value))
                self.batch_table.setItem(row_idx, col_idx, item)
        if self.batch_table.rowCount() > 0:
            self.batch_table.selectRow(0)
        else:
            self._update_batch_template_panel()

    def _get_selected_batch_row(self) -> Optional[Dict[str, Any]]:
        if not self._filtered_batch_rows:
            return None
        row_index = self.batch_table.currentRow()
        if row_index < 0 or row_index >= len(self._filtered_batch_rows):
            return None
        return self._filtered_batch_rows[row_index]

    def _update_batch_template_panel(self):
        placeholder = self.tr("—")
        row = self._get_selected_batch_row()
        if not row:
            self.batch_template_source_value.setText(placeholder)
            self.batch_template_name_value.setText(placeholder)
            self.batch_template_threshold_value.setText(placeholder)
            self.batch_template_preview_button.setEnabled(False)
            return
        source = row.get("reference_source") or "reference_capture"
        template_name = row.get("reference_template_id")
        threshold = row.get("reference_threshold_deg")
        source_text = self.tr("Template") if source == "template" else self.tr("Reference Capture")
        self.batch_template_source_value.setText(source_text)
        self.batch_template_name_value.setText(template_name or placeholder)
        self.batch_template_threshold_value.setText(
            f"{float(threshold):.2f}°" if isinstance(threshold, (int, float)) else placeholder
        )
        self.batch_template_preview_button.setEnabled(bool(template_name))

    def _show_template_preview_from_selection(self):
        row = self._get_selected_batch_row()
        if not row:
            return
        template_id = row.get("reference_template_id")
        if not template_id:
            QMessageBox.information(
                self,
                self.tr("Info"),
                self.tr("The selected record does not reference a template."),
            )
            return
        self.reference_templates = load_reference_templates(self.reference_template_path)
        template = self.reference_templates.get(template_id)
        if not template:
            QMessageBox.warning(
                self,
                self.tr("Template Missing"),
                self.tr("Template '{0}' was not found.").format(template_id),
            )
            return
        wavelengths = template.get("wavelengths") or []
        intensities = template.get("intensities") or []
        if len(wavelengths) < 2 or len(intensities) != len(wavelengths):
            QMessageBox.warning(
                self,
                self.tr("Invalid Template"),
                self.tr("Template '{0}' has invalid data.").format(template_id),
            )
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Template Preview — {0}").format(template_id))
        layout = QVBoxLayout(dialog)
        info_label = QLabel(
            self.tr("Points: {cnt} | Range: {start:.2f} - {end:.2f} nm").format(
                cnt=len(wavelengths), start=wavelengths[0], end=wavelengths[-1]
            )
        )
        layout.addWidget(info_label)
        plot = pg.PlotWidget()
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.plot(wavelengths, intensities, pen=pg.mkPen("c"))
        layout.addWidget(plot)
        close_button = QPushButton(self.tr("Close"))
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.resize(640, 420)
        dialog.exec_()

