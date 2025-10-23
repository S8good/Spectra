# nanosense/gui/database_explorer.py
import os

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox,
                             QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QWidget, QFileDialog,
                             QFormLayout, QLineEdit, QComboBox, QDateEdit, QAbstractItemView, QMessageBox)
from ..utils.file_io import export_data_custom
from PyQt5.QtCore import QEvent, QDate, pyqtSignal

class DatabaseExplorerDialog(QDialog):
    load_spectra_requested = pyqtSignal(list)#定义一个信号
    def __init__(self, parent=None):
        super().__init__(parent)

        # 从父窗口 (AppWindow) 获取 db_manager
        if parent and hasattr(parent, 'db_manager'):
            self.db_manager = self.parent().db_manager
        else:
            self.db_manager = None

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()
        self._populate_initial_data()

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

        self.project_label = QLabel()
        self.exp_name_label = QLabel()
        self.date_range_label = QLabel()
        self.exp_type_label = QLabel()

        form_layout.addRow(self.project_label, self.project_combo)
        form_layout.addRow(self.exp_name_label, self.exp_name_edit)
        form_layout.addRow(self.date_range_label, self.start_date_edit)
        form_layout.addRow(QLabel(), self.end_date_edit)  # "To" label for date range
        form_layout.addRow(self.exp_type_label, self.exp_type_combo)

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
        self.results_table.setColumnCount(6)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        action_buttons_layout = QHBoxLayout()
        self.load_spectra_button = QPushButton()
        self.export_button = QPushButton()
        self.delete_button = QPushButton()

        action_buttons_layout.addStretch()
        action_buttons_layout.addWidget(self.load_spectra_button)
        action_buttons_layout.addWidget(self.export_button)
        action_buttons_layout.addWidget(self.delete_button)

        results_layout.addWidget(self.results_table)
        results_layout.addLayout(action_buttons_layout)

        main_layout.addWidget(filter_panel)
        main_layout.addWidget(results_panel, 1)

    def _connect_signals(self):
        # 目前只连接占位符，后续会实现具体功能
        self.search_button.clicked.connect(self._search_database)
        self.reset_button.clicked.connect(self._reset_filters)
        self.load_spectra_button.clicked.connect(self._load_selected_spectra)
        self.export_button.clicked.connect(self._export_selected_data)
        self.delete_button.clicked.connect(self._delete_selected_experiments)

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
        self.search_button.setText(self.tr("Search"))
        self.reset_button.setText(self.tr("Reset Filters"))

        # 结果表格
        self.results_table.setHorizontalHeaderLabels([
            self.tr("Exp. ID"), self.tr("Project"), self.tr("Experiment Name"),
            self.tr("Type"), self.tr("Timestamp"), self.tr("Operator")
        ])

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
        self.exp_type_combo.addItems([self.tr("All Types"), "Single Measurement"])  # 后续可扩展

    def _search_database(self):
        """【修改】执行真正的数据库搜索并填充表格。"""
        if not self.db_manager:
            return

        # 1. 从UI控件收集筛选条件
        project_id = self.project_combo.currentData()
        name_filter = self.exp_name_edit.text().strip()
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")

        type_text = self.exp_type_combo.currentText()
        # 假设 "All Types" 或其翻译版本意味着不过滤
        type_filter = type_text if type_text != self.tr("All Types") else ""

        # 2. 调用数据库管理器执行搜索
        results = self.db_manager.search_experiments(
            project_id=project_id,
            name_filter=name_filter,
            start_date=start_date,
            end_date=end_date,
            type_filter=type_filter
        )

        # 3. 将结果填充到表格中
        self.results_table.setRowCount(0)  # 清空旧结果
        self.results_table.setRowCount(len(results))

        for row_index, row_data in enumerate(results):
            # row_data 的顺序与我们SQL查询中SELECT的顺序一致
            # (exp_id, proj_name, exp_name, type, timestamp, operator)
            for col_index, cell_data in enumerate(row_data):
                item = QTableWidgetItem(str(cell_data))
                self.results_table.setItem(row_index, col_index, item)

        print(f"搜索完成，找到 {len(results)} 条记录。")

    def _reset_filters(self):
        """【修改】重置所有筛选条件并重新搜索。"""
        self.exp_name_edit.clear()
        self._populate_initial_data() # 这个方法会重置下拉框和日期
        self._search_database() # 重置后立即执行一次搜索，显示所有结果

    def _load_selected_spectra(self):
        """获取选中的实验，并发出包含光谱数据的信号。"""
        selected_items = self.results_table.selectionModel().selectedRows()
        if not selected_items:
            QMessageBox.warning(self, self.tr("Info"), self.tr("Please select one or more experiments from the table."))
            return

        # 从表格的第一列获取实验ID
        experiment_ids = [int(self.results_table.item(index.row(), 0).text()) for index in selected_items]

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