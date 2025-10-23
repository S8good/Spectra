# nanosense/gui/affinity_analysis_dialog.py

import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox,
                             QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QWidget,
                             QComboBox, QFormLayout, QMessageBox)
from PyQt5.QtCore import QEvent  # 导入 QEvent
import pyqtgraph as pg

from nanosense.algorithms.performance import calculate_affinity_kd, saturation_binding_model, fit_hill_equation, hill_equation
from nanosense.utils.file_io import load_xy_data_from_file


class AffinityAnalysisDialog(QDialog):
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
        left_panel = QWidget();
        left_panel.setFixedWidth(420)
        left_layout = QVBoxLayout(left_panel)

        # --- Data Input Group ---
        self.data_group = QGroupBox()
        data_layout = QVBoxLayout(self.data_group)
        self.data_table = QTableWidget();
        self.data_table.setColumnCount(2);
        self.data_table.setRowCount(8)
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        data_layout.addWidget(self.data_table)
        import_button_layout = QHBoxLayout()
        self.import_button = QPushButton()
        self.add_row_button = QPushButton()
        import_button_layout.addWidget(self.import_button);
        import_button_layout.addWidget(self.add_row_button)
        data_layout.addLayout(import_button_layout)

        # --- Fit Settings Group ---
        self.settings_group = QGroupBox()
        settings_layout = QFormLayout(self.settings_group)
        self.fit_model_combo = QComboBox()
        self.fit_model_label = QLabel()
        settings_layout.addRow(self.fit_model_label, self.fit_model_combo)

        # --- Fit Results Group ---
        self.results_group = QGroupBox()
        self.results_layout = QFormLayout(self.results_group)
        self.KD_label = QLabel("N/A");
        self.R_max_label = QLabel("N/A")
        self.n_label = QLabel("N/A");
        self.r_squared_label = QLabel("N/A")
        self.KD_label_title = QLabel();
        self.R_max_label_title = QLabel()
        self.n_label_title = QLabel();
        self.r_squared_label_title = QLabel()
        self.results_layout.addRow(self.KD_label_title, self.KD_label)
        self.results_layout.addRow(self.R_max_label_title, self.R_max_label)
        self.results_layout.addRow(self.n_label_title, self.n_label)
        self.results_layout.addRow(self.r_squared_label_title, self.r_squared_label)
        # 【新增】添加保存按钮到结果区域
        self.save_to_db_button = QPushButton()
        self.save_to_db_button.setEnabled(False)  # 初始时禁用
        self.results_layout.addRow(self.save_to_db_button)

        self.calculate_button = QPushButton()
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        left_layout.addWidget(self.data_group);
        left_layout.addWidget(self.settings_group)
        left_layout.addWidget(self.calculate_button);
        left_layout.addWidget(self.results_group)
        left_layout.addStretch();
        left_layout.addWidget(self.button_box)

        # --- Plotting Area ---
        self.plot_widget = pg.PlotWidget()
        self.data_points = pg.ScatterPlotItem(size=10, brush=pg.mkBrush(0, 100, 255, 200))
        self.fit_line = pg.PlotDataItem(pen=pg.mkPen('r', width=2))
        self.plot_widget.addItem(self.data_points);
        self.plot_widget.addItem(self.fit_line)
        main_layout.addWidget(left_panel);
        main_layout.addWidget(self.plot_widget, stretch=1)

    def _connect_signals(self):
        self.import_button.clicked.connect(self._handle_import)
        self.add_row_button.clicked.connect(lambda: self.data_table.insertRow(self.data_table.rowCount()))
        self.calculate_button.clicked.connect(self._perform_analysis)
        self.button_box.accepted.connect(self.accept)
        self.fit_model_combo.currentIndexChanged.connect(self._update_result_labels)
        self.save_to_db_button.clicked.connect(self._save_results_to_db)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Affinity Analysis(KD)"))
        self.data_group.setTitle(self.tr("Data Input"))
        self.data_table.setHorizontalHeaderLabels([self.tr("Concentration (nM)"), self.tr("Response (nm)")])
        self.import_button.setText(self.tr("Import from File..."))
        self.add_row_button.setText(self.tr("Add Row"))
        self.settings_group.setTitle(self.tr("Fit Settings"))
        self.fit_model_label.setText(self.tr("Fit Model:"))

        current_data = self.fit_model_combo.currentData()
        self.fit_model_combo.clear()
        self.fit_model_combo.addItem(self.tr("Michaelis-Menten"), userData="mm")
        self.fit_model_combo.addItem(self.tr("Hill Equation"), userData="hill")
        index = self.fit_model_combo.findData(current_data)
        if index != -1: self.fit_model_combo.setCurrentIndex(index)

        self.results_group.setTitle(self.tr("Fit Results"))
        self.save_to_db_button.setText(self.tr("Save Results to Database"))
        self.KD_label_title.setText(self.tr("KD (nM):"))
        self.R_max_label_title.setText(self.tr("R_max (nm):"))
        self.n_label_title.setText(self.tr("Hill Coefficient (n):"))
        self.r_squared_label_title.setText(self.tr("R-squared (R²):"))
        self.calculate_button.setText(self.tr("Calculate & Plot"))
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.plot_widget.setTitle(self.tr("Affinity Saturation Curve Fit"))
        self.plot_widget.setLabel('left', self.tr('Response (nm)'))
        self.plot_widget.setLabel('bottom', self.tr('Concentration (nM)'))
        self._update_result_labels()

    def _update_result_labels(self):
        model_key = self.fit_model_combo.currentData()
        is_hill = (model_key == 'hill')
        self.n_label.setVisible(is_hill)
        self.n_label_title.setVisible(is_hill)

    def _perform_analysis(self):
        concentrations, responses = [], []
        for row in range(self.data_table.rowCount()):
            try:
                conc_item = self.data_table.item(row, 0);
                resp_item = self.data_table.item(row, 1)
                if conc_item and resp_item and conc_item.text() and resp_item.text():
                    concentrations.append(float(conc_item.text()));
                    responses.append(float(resp_item.text()))
            except (ValueError, AttributeError):
                continue
        if len(concentrations) < 3:
            not_enough_data_str = self.tr("Not enough data")
            self.KD_label.setText(not_enough_data_str);
            self.R_max_label.setText(not_enough_data_str);
            self.r_squared_label.setText(not_enough_data_str);
            self.n_label.setText("N/A")
            return
        concentrations, responses = np.array(concentrations), np.array(responses)

        # 【核心修改】使用 userData 进行逻辑判断
        model_key = self.fit_model_combo.currentData()
        fit_results = None

        if model_key == 'hill':
            fit_results = fit_hill_equation(concentrations, responses)
        else:  # Default to Michaelis-Menten
            fit_results = calculate_affinity_kd(concentrations, responses)

        if fit_results:
            self.KD_label.setText(f"{fit_results['KD']:.4f}")
            self.R_max_label.setText(f"{fit_results['R_max']:.4f}")
            self.r_squared_label.setText(f"{fit_results['r_squared']:.4f}")
            self.data_points.setData(concentrations, responses)
            fit_x = np.linspace(min(concentrations), max(concentrations), 200)

            if model_key == 'hill':
                self.n_label.setText(f"{fit_results['n']:.4f}")
                fit_y = hill_equation(fit_x, fit_results['R_max'], fit_results['KD'], fit_results['n'])
            else:
                self.n_label.setText("N/A")
                fit_y = saturation_binding_model(fit_x, fit_results['R_max'], fit_results['KD'])
            self.fit_line.setData(fit_x, fit_y)
            self.save_to_db_button.setEnabled(True)  # 【新增】计算成功，启用按钮
        else:
            fit_failed_str = self.tr("Fit Failed")
            self.KD_label.setText(fit_failed_str);
            self.R_max_label.setText(fit_failed_str);
            self.r_squared_label.setText(fit_failed_str);
            self.n_label.setText(fit_failed_str)
            self.save_to_db_button.setEnabled(False)  # 【新增】计算失败，禁用按钮

    def _handle_import(self):
        default_load_path = self.app_settings.get('default_load_path', '')
        x_data, y_data = load_xy_data_from_file(self, default_load_path)
        if x_data is None or y_data is None: return
        self.data_table.clearContents();
        self.data_table.setRowCount(len(x_data))
        for i, (x_val, y_val) in enumerate(zip(x_data, y_data)):
            self.data_table.setItem(i, 0, QTableWidgetItem(str(x_val)));
            self.data_table.setItem(i, 1, QTableWidgetItem(str(y_val)))

    def _save_results_to_db(self):
        """将当前显示的分析结果保存到数据库。"""
        main_window = self.parent()
        if not main_window or not main_window.db_manager:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Database is not available."))
            return

        try:
            # 1. 确保有一个有效的实验会话
            experiment_id = main_window.get_or_create_current_experiment_id()
            if experiment_id is None:
                return  # 用户取消了命名实验

            # 2. 从界面标签中收集结果数据
            model_key = self.fit_model_combo.currentData()
            results_data = {
                'model': self.fit_model_combo.currentText(),
                'KD': float(self.KD_label.text()),
                'R_max': float(self.R_max_label.text()),
                'r_squared': float(self.r_squared_label.text())
            }
            if model_key == 'hill':
                results_data['n'] = float(self.n_label.text())

            # 3. 调用数据库管理器来保存
            main_window.db_manager.save_analysis_result(
                experiment_id=experiment_id,
                analysis_type='Affinity_KD',
                result_data=results_data
            )

            # 4. 给予用户反馈
            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Analysis results have been saved to the database."))
            self.save_to_db_button.setEnabled(False)  # 保存后禁用，防止重复保存

        except ValueError:
            QMessageBox.warning(self, self.tr("Error"),
                                self.tr("Cannot save, results are not valid numbers."))
        except Exception as e:
            QMessageBox.critical(self, self.tr("Database Error"),
                                 self.tr("An error occurred while saving to the database:\n{0}").format(str(e)))