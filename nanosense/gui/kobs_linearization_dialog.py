# nanosense/gui/kobs_linearization_dialog.py

import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox,
                             QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QWidget, QFormLayout)
from PyQt5.QtCore import QEvent  # 新增 QEvent
import pyqtgraph as pg
from nanosense.algorithms.kinetics import linear_fit
from nanosense.utils.file_io import load_xy_data_from_file


class KobsLinearizationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setGeometry(250, 250, 1300, 700)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # 设置初始文本

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        # --- Left Panel ---
        left_panel = QWidget();
        left_panel.setFixedWidth(420)
        left_layout = QVBoxLayout(left_panel)

        self.data_group = QGroupBox()
        table_layout = QVBoxLayout(self.data_group)
        self.data_table = QTableWidget();
        self.data_table.setColumnCount(2);
        self.data_table.setRowCount(5)
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table_layout.addWidget(self.data_table)
        import_button_layout = QHBoxLayout()
        self.import_button = QPushButton()
        self.add_row_button = QPushButton()
        import_button_layout.addWidget(self.import_button);
        import_button_layout.addWidget(self.add_row_button)
        table_layout.addLayout(import_button_layout)

        self.results_group = QGroupBox()
        results_layout = QFormLayout(self.results_group)
        self.k_a_label = QLabel("N/A");
        self.k_d_label = QLabel("N/A")
        self.KD_label = QLabel("N/A");
        self.r_squared_label = QLabel("N/A")
        self.k_a_label_title = QLabel();
        self.k_d_label_title = QLabel()
        self.KD_label_title = QLabel();
        self.r_squared_label_title = QLabel()
        results_layout.addRow(self.k_a_label_title, self.k_a_label)
        results_layout.addRow(self.k_d_label_title, self.k_d_label)
        results_layout.addRow(self.KD_label_title, self.KD_label)
        results_layout.addRow(self.r_squared_label_title, self.r_squared_label)

        self.calculate_button = QPushButton()
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)

        left_layout.addWidget(self.data_group)
        left_layout.addWidget(self.calculate_button)
        left_layout.addWidget(self.results_group)
        left_layout.addStretch()
        left_layout.addWidget(self.button_box)

        # --- Right Plot ---
        self.plot_widget = pg.PlotWidget()
        self.data_points = pg.ScatterPlotItem(size=10, brush=pg.mkBrush(0, 100, 255, 200))
        self.fit_line = pg.PlotDataItem(pen=pg.mkPen('r', width=2))
        self.plot_widget.addItem(self.data_points)
        self.plot_widget.addItem(self.fit_line)

        main_layout.addWidget(left_panel)
        main_layout.addWidget(self.plot_widget, stretch=1)

    def _connect_signals(self):
        self.import_button.clicked.connect(self._handle_import)
        self.add_row_button.clicked.connect(lambda: self.data_table.insertRow(self.data_table.rowCount()))
        self.calculate_button.clicked.connect(self._perform_analysis)
        self.button_box.accepted.connect(self.accept)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("k_obs Linearization Analysis"))

        self.data_group.setTitle(self.tr("Data Input"))
        self.data_table.setHorizontalHeaderLabels([self.tr("Concentration [A] (nM)"), self.tr("k_obs (1/s)")])
        self.import_button.setText(self.tr("Import from File..."))
        self.add_row_button.setText(self.tr("Add Row"))

        self.results_group.setTitle(self.tr("Final Calculation Results"))
        self.k_a_label_title.setText(self.tr("ka (1/M·s):"))
        self.k_d_label_title.setText(self.tr("kd (1/s):"))
        self.KD_label_title.setText(self.tr("KD (M):"))
        self.r_squared_label_title.setText(self.tr("R-squared (R²):"))

        self.calculate_button.setText(self.tr("Calculate & Plot"))
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))

        self.plot_widget.setTitle(self.tr("k_obs vs. Concentration"))
        self.plot_widget.setLabel('bottom', self.tr('Concentration [A] (nM)'))
        self.plot_widget.setLabel('left', self.tr('k_obs (1/s)'))

    def _handle_import(self):
        default_load_path = self.app_settings.get('default_load_path', '')
        x_data, y_data = load_xy_data_from_file(self, default_load_path)
        if x_data is None or y_data is None: return
        self.data_table.clearContents()
        self.data_table.setRowCount(len(x_data))
        for i, (x_val, y_val) in enumerate(zip(x_data, y_data)):
            self.data_table.setItem(i, 0, QTableWidgetItem(str(x_val)))
            self.data_table.setItem(i, 1, QTableWidgetItem(str(y_val)))

    def _perform_analysis(self):
        concentrations, k_obs_values = [], []
        for row in range(self.data_table.rowCount()):
            try:
                conc_item = self.data_table.item(row, 0);
                kobs_item = self.data_table.item(row, 1)
                if conc_item and kobs_item and conc_item.text() and kobs_item.text():
                    concentrations.append(float(conc_item.text()));
                    k_obs_values.append(float(kobs_item.text()))
            except (ValueError, AttributeError):
                continue
        if len(concentrations) < 2: return

        fit_results = linear_fit(np.array(concentrations), np.array(k_obs_values))
        if fit_results:
            k_a_nM = fit_results['slope']
            k_d = fit_results['intercept']
            k_a = k_a_nM * 1e9
            KD = float('inf') if k_a == 0 else k_d / k_a

            self.k_a_label.setText(f"{k_a:.2e}")
            self.k_d_label.setText(f"{k_d:.2e}")
            self.KD_label.setText(f"{KD:.2e}")
            self.r_squared_label.setText(f"{fit_results['r_squared']:.4f}")

            self.data_points.setData(concentrations, k_obs_values)
            fit_x = np.array([min(concentrations), max(concentrations)])
            fit_y = k_a_nM * fit_x + k_d
            self.fit_line.setData(fit_x, fit_y)