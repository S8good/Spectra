# nanosense/gui/kinetics_analysis_dialog.py
import time
import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox,
                             QGroupBox, QFormLayout, QLabel, QDoubleSpinBox, QTabWidget, QWidget,
                             QMessageBox)  # 导入 QTabWidget
from PyQt5.QtCore import Qt, QEvent # 导入 QEvent
import pyqtgraph as pg

# 导入所有需要的算法
from nanosense.algorithms.kinetics import fit_kinetics_curve, mono_exponential_decay, calculate_residuals


class KineticsAnalysisDialog(QDialog):
    def __init__(self, time_data, y_data, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setObjectName("KineticsAnalysisDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setGeometry(200, 200, 900, 600)

        self.time_data = np.array(time_data)
        self.y_data = np.array(y_data)

        self._init_ui()
        self._apply_theme()
        self.calculate_button.clicked.connect(self._perform_analysis)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.save_to_db_button.clicked.connect(self._save_results_to_db)

        self._retranslate_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        # --- 左侧：控制与结果面板 (保持不变) ---
        left_panel = QWidget()
        left_panel.setObjectName("kineticsAnalysisSidePanel")
        left_panel.setAttribute(Qt.WA_StyledBackground, True)
        left_panel.setFixedWidth(300)
        left_layout = QVBoxLayout(left_panel)

        self.conc_group = QGroupBox()
        conc_layout = QFormLayout();
        self.concentration_input = QDoubleSpinBox();
        self.concentration_input.setDecimals(5);
        self.concentration_input.setRange(0, 1e9);
        self.concentration_input.setValue(1.0);
        self.conc_label = QLabel()
        conc_layout.addRow(self.conc_label, self.concentration_input)
        self.conc_group.setLayout(conc_layout)
        self.result_group = QGroupBox()  # <--- 修改
        self.result_layout = QFormLayout()  # <--- 新增，存为属性
        self.k_obs_label_title = QLabel()  # <--- 新增
        self.k_obs_label = QLabel("N/A")
        self.k_d_label_title = QLabel()  # <--- 新增
        self.k_d_label = QLabel("N/A")
        self.k_a_label_title = QLabel()  # <--- 新增
        self.k_a_label = QLabel("N/A")
        self.KD_label_title = QLabel()  # <--- 新增
        self.KD_label = QLabel("N/A")
        for label in (self.k_obs_label, self.k_d_label, self.k_a_label, self.KD_label):
            label.setObjectName("analysisValueLabel")
        self.result_layout.addRow(self.k_obs_label_title, self.k_obs_label)  # <--- 修改
        self.result_layout.addRow(self.k_d_label_title, self.k_d_label)  # <--- 修改
        self.result_layout.addRow(self.k_a_label_title, self.k_a_label)  # <--- 修改
        self.result_layout.addRow(self.KD_label_title, self.KD_label)  # <--- 修改
        # 【新增】添加保存按钮到结果区域
        self.save_to_db_button = QPushButton()
        self.save_to_db_button.setEnabled(False)  # 初始时禁用
        self.result_layout.addRow(self.save_to_db_button)

        self.result_group.setLayout(self.result_layout)
        self.calculate_button = QPushButton();

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        left_layout.addWidget(self.conc_group);
        left_layout.addWidget(self.calculate_button);
        left_layout.addWidget(self.result_group);
        left_layout.addStretch();
        left_layout.addWidget(self.button_box)

        # --- 【已重构】右侧：使用 QTabWidget 容纳多个图表 ---
        self.tabs = QTabWidget()
        self.tabs.setObjectName("kineticsAnalysisTabs")

        # 1. 主拟合图
        self._create_main_fit_tab()
        # 2. 偏差图
        self._create_deviation_tab()
        # 3. 自指数图
        self._create_self_exponent_tab()
        # 4. 残差图
        self._create_residual_tab()

        main_layout.addWidget(left_panel)
        main_layout.addWidget(self.tabs, stretch=1)

    def _create_main_fit_tab(self):
        tab = QWidget()
        tab.setObjectName("kineticsAnalysisTab")
        tab.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(tab)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setTitle("请拖拽竖线选择 结合(绿) 与 解离(红) 区域")
        self.plot_widget.setLabel('bottom', 'Time (s)');
        self.plot_widget.setLabel('left', 'Response (nm)')
        self.plot_widget.plot(self.time_data, self.y_data, pen=None, symbol='o', symbolSize=5)
        t_max = self.time_data[-1]
        self.assoc_start_line = pg.InfiniteLine(pos=t_max * 0.1, angle=90, movable=True, pen='g');
        self.assoc_end_line = pg.InfiniteLine(pos=t_max * 0.4, angle=90, movable=True, pen='g')
        self.dissoc_start_line = pg.InfiniteLine(pos=t_max * 0.5, angle=90, movable=True, pen='r');
        self.dissoc_end_line = pg.InfiniteLine(pos=t_max * 0.8, angle=90, movable=True, pen='r')
        self.plot_widget.addItem(self.assoc_start_line);
        self.plot_widget.addItem(self.assoc_end_line);
        self.plot_widget.addItem(self.dissoc_start_line);
        self.plot_widget.addItem(self.dissoc_end_line);
        self.assoc_fit_curve = self.plot_widget.plot(pen=pg.mkPen('c', width=2));
        self.dissoc_fit_curve = self.plot_widget.plot(pen=pg.mkPen('y', width=2))
        self._style_plot(self.plot_widget)
        layout.addWidget(self.plot_widget)
        self.tabs.addTab(tab, "主拟合图")

    def _create_deviation_tab(self):
        tab = QWidget()
        tab.setObjectName("kineticsAnalysisTab")
        tab.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(tab)
        self.dev_plot = pg.PlotWidget(title="偏差图 (Deviation Plot)");
        self.dev_plot.setLabel('bottom', 'Time (s)');
        self.dev_plot.setLabel('left', 'ΔResponse / Δt')
        self.dev_curve = self.dev_plot.plot(pen='w');
        layout.addWidget(self.dev_plot)
        self.tabs.addTab(tab, "偏差图")

    def _create_self_exponent_tab(self):
        tab = QWidget()
        tab.setObjectName("kineticsAnalysisTab")
        tab.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(tab)
        self.exp_plot = pg.PlotWidget(title="自指数图 (Self-Exponent Plot)");
        self.exp_plot.setLabel('bottom', 'Normalized Response');
        self.exp_plot.setLabel('left', 'ΔResponse / Δt')
        self.exp_points = self.exp_plot.plot(pen=None, symbol='o', symbolSize=5);
        self._style_plot(self.exp_plot)
        layout.addWidget(self.exp_plot)
        self.tabs.addTab(tab, "自指数图")

    def _create_residual_tab(self):
        tab = QWidget()
        tab.setObjectName("kineticsAnalysisTab")
        tab.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(tab)
        self.res_plot = pg.PlotWidget(title="残差图 (Residual Plot)");
        self.res_plot.setLabel('bottom', 'Time (s)');
        self.res_plot.setLabel('left', 'Residual (Actual - Fit)')
        self.res_points = self.res_plot.plot(pen=None, symbol='o', symbolSize=5);
        self._style_plot(self.res_plot)
        layout.addWidget(self.res_plot)
        self.tabs.addTab(tab, "残差图")

    def _style_plot(self, plot_widget):
        plot_widget.setBackground("#1F2735")
        axis_pen = pg.mkPen("#4D5A6D", width=1)
        text_pen = pg.mkPen("#E2E8F0")
        for axis in ("left", "bottom"):
            axis_item = plot_widget.getPlotItem().getAxis(axis)
            axis_item.setPen(axis_pen)
            axis_item.setTextPen(text_pen)
            axis_item.setStyle(tickLength=6)
        plot_widget.getPlotItem().showGrid(x=True, y=True, alpha=0.15)
        plot_widget.getViewBox().setBorder(pg.mkPen("#39475A", width=1))

    def _apply_theme(self):
        self.setStyleSheet("""
#KineticsAnalysisDialog {
    background-color: #1A202C;
    color: #E2E8F0;
    font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
    font-size: 13px;
}
#kineticsAnalysisSidePanel {
    background-color: #2D3748;
    border: 1px solid #4A5568;
    border-radius: 12px;
    padding: 16px;
}
#kineticsAnalysisSidePanel QGroupBox {
    background-color: #1F2735;
    border: 1px solid #39475A;
    border-radius: 10px;
    margin-top: 12px;
    padding: 16px;
}
#kineticsAnalysisSidePanel QGroupBox::title {
    color: #E2E8F0;
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 4px;
    font-weight: 600;
}
#kineticsAnalysisSidePanel QLabel {
    color: #E2E8F0;
}
QLabel#analysisValueLabel {
    color: #63B3ED;
    font-weight: 600;
}
QPushButton {
    background-color: #3182CE;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #2B6CB0;
}
QPushButton:pressed {
    background-color: #245A86;
}
QPushButton:disabled {
    background-color: #4A5568;
    color: #A0AEC0;
}
QDialogButtonBox QPushButton {
    min-width: 90px;
}
QDoubleSpinBox {
    background-color: #1F2735;
    border: 1px solid #39475A;
    border-radius: 6px;
    padding: 6px;
    color: #E2E8F0;
}
QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {
    background-color: #2D3748;
    border: none;
    width: 16px;
}
QTabWidget#kineticsAnalysisTabs::pane {
    background-color: #1F2735;
    border: 1px solid #39475A;
    border-radius: 12px;
    padding: 12px;
}
QTabWidget#kineticsAnalysisTabs QWidget {
    background-color: transparent;
}
QTabBar::tab {
    background-color: #2D3748;
    color: #E2E8F0;
    padding: 8px 18px;
    border: 1px solid #39475A;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 6px;
}
QTabBar::tab:selected {
    background-color: #3182CE;
    color: #FFFFFF;
    border-color: #2B6CB0;
}
QTabBar::tab:hover {
    background-color: #2B6CB0;
}
QMessageBox {
    background-color: #2D3748;
    color: #E2E8F0;
}
QMessageBox QLabel {
    color: #E2E8F0;
}
QMessageBox QPushButton {
    background-color: #3182CE;
    padding: 6px 18px;
    border-radius: 6px;
}
        """)

    def _perform_analysis(self):
        """执行拟合流程：选区 -> 拟合 -> 计算 -> 显示结果"""
        try:
            # 1. 复制并清洗原始数据，避免后续过程修改 self.time_data / self.y_data
            time_data = np.array(self.time_data, dtype=float)
            response_data = np.array(self.y_data, dtype=float)

            finite_mask = np.isfinite(time_data) & np.isfinite(response_data)
            if not np.all(finite_mask):
                time_data = time_data[finite_mask]
                response_data = response_data[finite_mask]

            if time_data.size < 5 or response_data.size < 5:
                QMessageBox.warning(
                    self,
                    self.tr("Insufficient Data"),
                    self.tr("Not enough valid data points to perform kinetic analysis. Please collect more measurements.")
                )
                self.save_to_db_button.setEnabled(False)
                return

            order = np.argsort(time_data)
            time_data = time_data[order]
            response_data = response_data[order]

            assoc_start_t = self.assoc_start_line.value()
            assoc_end_t = self.assoc_end_line.value()
            dissoc_start_t = self.dissoc_start_line.value()
            dissoc_end_t = self.dissoc_end_line.value()

            if assoc_start_t >= assoc_end_t or dissoc_start_t >= dissoc_end_t:
                QMessageBox.warning(
                    self,
                    self.tr("Invalid Region"),
                    self.tr("Please make sure the association and dissociation vertical markers define valid ranges (start < end).")
                )
                self.save_to_db_button.setEnabled(False)
                return

            assoc_mask = (time_data >= assoc_start_t) & (time_data <= assoc_end_t)
            dissoc_mask = (time_data >= dissoc_start_t) & (time_data <= dissoc_end_t)

            if np.sum(assoc_mask) < 3 or np.sum(dissoc_mask) < 3:
                QMessageBox.warning(
                    self,
                    self.tr("Insufficient Data"),
                    self.tr("Selected association or dissociation region has fewer than 3 points. Please adjust the vertical markers.")
                )
                self.save_to_db_button.setEnabled(False)
                return

            dissoc_time = time_data[dissoc_mask] - dissoc_start_t
            dissoc_y = response_data[dissoc_mask]
            dissoc_fit_results = fit_kinetics_curve(dissoc_time, dissoc_y)
            if dissoc_fit_results is None:
                self.k_d_label.setText(self.tr("Fit Failed"))
                self.save_to_db_button.setEnabled(False)
                QMessageBox.warning(
                    self,
                    self.tr("Fit Failed"),
                    self.tr("Unable to fit the dissociation segment. Try widening the time window or smoothing the data.")
                )
                return

            k_d = abs(dissoc_fit_results['b'])
            self.k_d_label.setText(f"{k_d:.4e}")
            self.dissoc_fit_curve.setData(
                dissoc_time + dissoc_start_t,
                mono_exponential_decay(dissoc_time, **dissoc_fit_results)
            )

            assoc_time = time_data[assoc_mask] - assoc_start_t
            assoc_y = response_data[assoc_mask]
            assoc_y_inverted = assoc_y.max() - assoc_y
            assoc_fit_results = fit_kinetics_curve(assoc_time, assoc_y_inverted)
            if assoc_fit_results is None:
                self.k_obs_label.setText(self.tr("Fit Failed"))
                self.save_to_db_button.setEnabled(False)
                QMessageBox.warning(
                    self,
                    self.tr("Fit Failed"),
                    self.tr("Unable to fit the association segment. Please adjust the markers or check the signal quality.")
                )
                return

            k_obs = abs(assoc_fit_results['b'])
            self.k_obs_label.setText(f"{k_obs:.4e}")
            fitted_y_inverted = mono_exponential_decay(assoc_time, **assoc_fit_results)
            self.assoc_fit_curve.setData(assoc_time + assoc_start_t, assoc_y.max() - fitted_y_inverted)

            concentration_M = self.concentration_input.value() * 1e-9
            if concentration_M == 0:
                self.k_a_label.setText(self.tr("Concentration cannot be zero"))
                self.KD_label.setText(self.tr("Calculation Error"))
                self.save_to_db_button.setEnabled(False)
                QMessageBox.warning(
                    self,
                    self.tr("Invalid Concentration"),
                    self.tr("Analyte concentration cannot be zero when calculating kinetic constants.")
                )
                return

            if k_obs <= k_d:
                self.k_a_label.setText(self.tr("Calculation Error (k_obs <= k_d)"))
                self.KD_label.setText(self.tr("Calculation Error"))
                self.save_to_db_button.setEnabled(False)
                QMessageBox.warning(
                    self,
                    self.tr("Calculation Error"),
                    self.tr("k_obs must be greater than k_d. Adjust the association window or verify the data.")
                )
                return

            k_a = (k_obs - k_d) / concentration_M
            KD = k_d / k_a
            self.k_a_label.setText(f"{k_a:.4e}")
            self.KD_label.setText(f"{KD:.4e}")
            self.save_to_db_button.setEnabled(True)

            delta_y = np.diff(response_data)
            delta_t = np.diff(time_data)
            if len(delta_t) == 0 or np.allclose(delta_t, 0):
                derivative = np.zeros_like(delta_t)
            else:
                derivative = delta_y / (delta_t + 1e-9)

            if len(derivative) > 0:
                self.dev_curve.setData(time_data[:-1], derivative)

            y_range = response_data.max() - response_data.min()
            if y_range > 0 and len(response_data) > 1:
                normalized_y = (response_data - response_data.min()) / y_range
                self.exp_points.setData(normalized_y[:-1], derivative)

            assoc_residuals = calculate_residuals(assoc_time, assoc_y_inverted, assoc_fit_results)
            dissoc_residuals = calculate_residuals(dissoc_time, dissoc_y, dissoc_fit_results)
            self.res_points.setData(
                np.concatenate([assoc_time + assoc_start_t, dissoc_time + dissoc_start_t]),
                np.concatenate([assoc_residuals, dissoc_residuals])
            )

        except Exception as exc:
            self.save_to_db_button.setEnabled(False)
            self.k_obs_label.setText(self.tr("N/A"))
            self.k_d_label.setText(self.tr("N/A"))
            self.k_a_label.setText(self.tr("N/A"))
            self.KD_label.setText(self.tr("N/A"))
            QMessageBox.critical(
                self,
                self.tr("Unexpected Error"),
                self.tr("An unexpected error occurred during kinetic analysis:\n{0}").format(str(exc))
            )

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Kinetics and Affinity Analysis"))

        self.conc_group.setTitle(self.tr("Experiment Parameters"))
        self.conc_label.setText(self.tr("Analyte Concentration [A] (nM):"))
        self.result_group.setTitle(self.tr("Kinetics Calculation Results"))
        self.k_obs_label_title.setText(self.tr("k_obs (1/s):"))
        self.k_d_label_title.setText(self.tr("k_d (1/s):"))
        self.k_a_label_title.setText(self.tr("k_a (1/M·s):"))
        self.KD_label_title.setText(self.tr("KD (M):"))
        self.calculate_button.setText(self.tr("Calculate Kinetic Constants"))
        self.save_to_db_button.setText(self.tr("Save Results to Database"))
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))

        # Tab页和图表
        self.tabs.setTabText(0, self.tr("Main Fit Plot"))
        self.tabs.setTabText(1, self.tr("Deviation Plot"))
        self.tabs.setTabText(2, self.tr("Self-Exponent Plot"))
        self.tabs.setTabText(3, self.tr("Residual Plot"))

        self.plot_widget.setTitle(
            self.tr("Drag vertical lines to select Association (green) & Dissociation (red) regions"))
        self.plot_widget.setLabel('bottom', self.tr('Time (s)'))
        self.plot_widget.setLabel('left', self.tr('Response (nm)'))

        self.dev_plot.setTitle(self.tr("Deviation Plot"))
        self.res_plot.setTitle(self.tr("Residual Plot"))
        self.exp_plot.setTitle(self.tr("Self-Exponent Plot"))

    def _save_results_to_db(self):
        """将当前显示的动力学分析结果保存到数据库。"""
        if not self.main_window or not self.main_window.db_manager:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Database is not available."))
            return

        try:
            experiment_id = self.main_window.get_or_create_current_experiment_id()
            if experiment_id is None:
                return

            time_data = np.array(self.time_data, dtype=float)
            response_data = np.array(self.y_data, dtype=float)

            finite_mask = np.isfinite(time_data) & np.isfinite(response_data)
            if not np.all(finite_mask):
                time_data = time_data[finite_mask]
                response_data = response_data[finite_mask]

            if time_data.size == 0 or response_data.size == 0:
                QMessageBox.warning(
                    self,
                    self.tr("Insufficient Data"),
                    self.tr("No valid kinetics data is available to save. Please recompute the kinetics first.")
                )
                return

            results_data = {
                'k_obs': self.k_obs_label.text(),
                'k_d': self.k_d_label.text(),
                'k_a': self.k_a_label.text(),
                'KD': self.KD_label.text(),
                'Analyte_Concentration_nM': self.concentration_input.value()
            }

            time_series = []
            time_values = time_data.tolist()
            wavelength_values = response_data.tolist()
            for t, wl in zip(time_values, wavelength_values):
                try:
                    time_value = float(t)
                except (TypeError, ValueError):
                    continue

                peak_value = None
                if wl is not None:
                    try:
                        wl_float = float(wl)
                        if np.isfinite(wl_float):
                            peak_value = wl_float
                    except (TypeError, ValueError):
                        peak_value = None

                time_series.append({'time_s': time_value, 'peak_nm': peak_value})

            if time_series:
                results_data['time_series'] = time_series

            if self.tr("Fit Failed") in results_data.values() or self.tr("Calculation Error") in results_data.values():
                QMessageBox.warning(self, self.tr("Warning"),
                                    self.tr("Cannot save, the calculation has failed or contains errors."))
                return

            self.main_window.db_manager.save_analysis_result(
                experiment_id=experiment_id,
                analysis_type='Kinetics_Fit',
                result_data=results_data
            )

            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Kinetics analysis results have been saved to the database."))
            self.save_to_db_button.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, self.tr("Database Error"),
                                 self.tr("An error occurred while saving to the database:\n{0}").format(str(e)))



