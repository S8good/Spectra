# 文件路径: nanosense/gui/calibration_dialog.py

import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QWidget,
                             QLabel, QFormLayout, QDialogButtonBox, QMessageBox)
from PyQt5.QtCore import QEvent
import pyqtgraph as pg
from nanosense.algorithms.kinetics import linear_fit
from nanosense.utils.file_io import load_xy_data_from_file


class CalibrationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setGeometry(150, 150, 1300, 700)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self.full_x_data = None
        self.full_y_data = None

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(420)

        # --- 数据输入 ---
        self.table_group = QGroupBox()
        table_layout = QVBoxLayout(self.table_group)
        self.data_table = QTableWidget()
        self.data_table.setColumnCount(2)
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.data_table.setRowCount(8)
        table_layout.addWidget(self.data_table)
        import_button_layout = QHBoxLayout()
        self.import_button = QPushButton()
        self.add_row_button = QPushButton()
        import_button_layout.addWidget(self.import_button)
        import_button_layout.addWidget(self.add_row_button)
        table_layout.addLayout(import_button_layout)

        # --- 结果显示 ---
        self.result_group = QGroupBox()
        result_layout = QVBoxLayout(self.result_group)  # 【修改】使用QVBoxLayout以便添加按钮

        result_form_layout = QFormLayout()
        self.slope_label = QLabel("N/A")
        self.intercept_label = QLabel("N/A")
        self.r_squared_label = QLabel("N/A")
        self.range_label = QLabel("N/A")
        self.slope_label_title = QLabel()
        self.intercept_label_title = QLabel()
        self.r_squared_label_title = QLabel()
        self.range_label_title = QLabel()
        result_form_layout.addRow(self.slope_label_title, self.slope_label)
        result_form_layout.addRow(self.intercept_label_title, self.intercept_label)
        result_form_layout.addRow(self.r_squared_label_title, self.r_squared_label)
        result_form_layout.addRow(self.range_label_title, self.range_label)

        self.lod_button = QPushButton(self.tr("Calculate Limit of Detection (LOD)..."))
        self.lod_button.setEnabled(False)
        self.save_to_db_button = QPushButton(self.tr("Save Results to Database"))
        self.save_to_db_button.setEnabled(False)

        result_layout.addLayout(result_form_layout)
        result_layout.addWidget(self.save_to_db_button)
        result_layout.addWidget(self.lod_button)

        self.calculate_button = QPushButton()
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)

        left_layout.addWidget(self.table_group)
        left_layout.addWidget(self.calculate_button)
        left_layout.addWidget(self.result_group)
        left_layout.addStretch()
        left_layout.addWidget(self.button_box)

        # --- 绘图区域 ---
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True)
        self.data_points = pg.ScatterPlotItem(size=10, pen=pg.mkPen(None), brush=pg.mkBrush(0, 100, 255, 200))
        self.fit_line = pg.PlotDataItem(pen=pg.mkPen('r', width=2))
        self.plot_widget.addItem(self.data_points)
        self.plot_widget.addItem(self.fit_line)
        self.range_line1 = pg.InfiniteLine(angle=90, movable=True, pen='y')
        self.range_line2 = pg.InfiniteLine(angle=90, movable=True, pen='y')
        self.range_line1.hide()
        self.range_line2.hide()
        self.plot_widget.addItem(self.range_line1)
        self.plot_widget.addItem(self.range_line2)

        main_layout.addWidget(left_panel)
        main_layout.addWidget(self.plot_widget, stretch=1)

    def _connect_signals(self):
        self.import_button.clicked.connect(self._handle_import)
        self.add_row_button.clicked.connect(lambda: self.data_table.insertRow(self.data_table.rowCount()))
        self.calculate_button.clicked.connect(self._perform_initial_calculation)
        self.range_line1.sigPositionChanged.connect(self._update_fit_based_on_range)
        self.range_line2.sigPositionChanged.connect(self._update_fit_based_on_range)
        self.button_box.accepted.connect(self.accept)
        self.lod_button.clicked.connect(self._open_lod_dialog)
        self.save_to_db_button.clicked.connect(self._save_results_to_db)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Calibration Curve"))
        self.table_group.setTitle(self.tr("Data Input"))

        # 【修改】为表头添加单位
        self.data_table.setHorizontalHeaderLabels([self.tr("Concentration (nM)"), self.tr("Response (nm)")])

        self.import_button.setText(self.tr("Import from File..."))
        self.add_row_button.setText(self.tr("Add Row"))
        self.calculate_button.setText(self.tr("Calculate & Plot"))
        self.result_group.setTitle(self.tr("Calculation Results"))
        self.slope_label_title.setText(self.tr("Slope (m):"))
        self.intercept_label_title.setText(self.tr("Intercept (c):"))
        self.r_squared_label_title.setText(self.tr("R-squared (R²):"))
        self.range_label_title.setText(self.tr("Fit Range:"))
        if self.range_label.text() in ["Not selected", "未选择"]:
            self.range_label.setText(self.tr("Not selected"))
        self.lod_button.setText(self.tr("Calculate Limit of Detection (LOD)..."))
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.plot_widget.setTitle(self.tr("Calibration Curve Linear Fit"))

        # 【修改】为坐标轴标签添加单位
        self.plot_widget.setLabel('left', self.tr('Response (nm)'))
        self.plot_widget.setLabel('bottom', self.tr('Concentration (nM)'))

    def _handle_import(self):
        default_load_path = self.app_settings.get('default_load_path', '')
        x_data, y_data = load_xy_data_from_file(self, default_load_path)
        if x_data is None or y_data is None: return
        self.data_table.clearContents()
        self.data_table.setRowCount(len(x_data))
        for i, (x_val, y_val) in enumerate(zip(x_data, y_data)):
            self.data_table.setItem(i, 0, QTableWidgetItem(str(x_val)))
            self.data_table.setItem(i, 1, QTableWidgetItem(str(y_val)))

    def _open_lod_dialog(self):
        """
        从主窗口打开性能分析对话框，并传入当前计算出的斜率。
        """
        try:
            slope_text = self.slope_label.text().split(' ')[0]
            slope_value = float(slope_text)

            # 调用主窗口的方法来打开新的对话框
            if self.main_window and hasattr(self.main_window, '_open_performance_dialog'):
                self.main_window._open_performance_dialog(slope=slope_value)
            else:
                QMessageBox.warning(self, self.tr("Error"), self.tr("Cannot open performance dialog."))

        except (ValueError, IndexError):
            QMessageBox.warning(self, self.tr("Warning"),
                                self.tr("Cannot calculate LOD because a valid slope (m) has not been determined yet."))

    def _update_fit_based_on_range(self):
        if self.full_x_data is None or len(self.full_x_data) < 2: return
        min_range = min(self.range_line1.value(), self.range_line2.value())
        max_range = max(self.range_line1.value(), self.range_line2.value())
        self.range_label.setText(f"[{min_range:.4g}, {max_range:.4g}]")

        indices = np.where((self.full_x_data >= min_range) & (self.full_x_data <= max_range))
        x_in_range = self.full_x_data[indices]
        y_in_range = self.full_y_data[indices]

        if len(x_in_range) < 2:
            self.fit_line.clear()
            not_enough_data_str = self.tr("Not enough data")
            self.slope_label.setText(not_enough_data_str)
            self.intercept_label.setText(not_enough_data_str)
            self.r_squared_label.setText(not_enough_data_str)
            self.save_to_db_button.setEnabled(False)
            return

        results = linear_fit(x_in_range, y_in_range)
        if results:
            # 【修改】直接使用固定的单位字符串 "nm/nM" 和 "nm"
            self.slope_label.setText(f"{results['slope']:.4g} nm/nM")
            self.intercept_label.setText(f"{results['intercept']:.4f} nm")
            self.r_squared_label.setText(f"{results['r_squared']:.4f}")

            self.lod_button.setEnabled(True)
            self.save_to_db_button.setEnabled(True)

            coeffs = [results['slope'], results['intercept']]
            fit_x = np.array([min_range, max_range])
            fit_y = np.polyval(coeffs, fit_x)
            self.fit_line.setData(fit_x, fit_y)
        else:
            self.lod_button.setEnabled(False)
            self.save_to_db_button.setEnabled(False)

    def _perform_initial_calculation(self):
        x_data, y_data = [], []
        for row in range(self.data_table.rowCount()):
            try:
                x_item = self.data_table.item(row, 0)
                y_item = self.data_table.item(row, 1)
                if x_item and y_item and x_item.text() and y_item.text():
                    x_data.append(float(x_item.text()))
                    y_data.append(float(y_item.text()))
            except (ValueError, AttributeError):
                continue
        if not x_data: return

        # 将数据按x值排序，这对于绘图很重要
        sorted_indices = np.argsort(x_data)
        self.full_x_data = np.array(x_data)[sorted_indices]
        self.full_y_data = np.array(y_data)[sorted_indices]

        self.data_points.setData(self.full_x_data, self.full_y_data)
        self.range_line1.setPos(self.full_x_data.min())
        self.range_line2.setPos(self.full_x_data.max())
        self.range_line1.show()
        self.range_line2.show()
        self._update_fit_based_on_range()

    def _save_results_to_db(self):
        """将当前显示的校准曲线分析结果保存到数据库。"""
        if not self.main_window or not self.main_window.db_manager:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Database is not available."))
            return

        try:
            experiment_id = self.main_window.get_or_create_current_experiment_id()
            if experiment_id is None:
                return

            results_data = {
                'slope': self.slope_label.text(),
                'intercept': self.intercept_label.text(),
                'r_squared': self.r_squared_label.text(),
                'fit_range': self.range_label.text()
            }

            self.main_window.db_manager.save_analysis_result(
                experiment_id=experiment_id,
                analysis_type='Calibration_Fit',
                result_data=results_data
            )

            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Calibration curve results have been saved to the database."))
            self.save_to_db_button.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, self.tr("Database Error"),
                                 self.tr("An error occurred while saving to the database:\n{0}").format(str(e)))