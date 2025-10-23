# nanosense/gui/kinetics_window.py

import numpy as np
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QGridLayout, QDialog)
from PyQt5.QtCore import pyqtSignal, QEvent
import pyqtgraph as pg

from .collapsible_box import CollapsibleBox
from .kinetics_analysis_dialog import KineticsAnalysisDialog
from .drift_correction_dialog import DriftCorrectionDialog


class KineticsWindow(QMainWindow):
    """
    一个独立的、非模态的窗口，专门用于实时动力学监测和分析。
    """
    closed = pyqtSignal(object)  # 当窗口关闭时发射信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent  # 保存对主窗口的引用，以便调用其方法

        self.kinetics_time_data = []
        self.kinetics_wavelength_data = []
        self.accumulated_results = []

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()

    def _init_ui(self):
        self.setWindowTitle(self.tr("Real-time Kinetics Analysis"))
        self.setGeometry(300, 300, 1000, 700)  # 设置一个合适的初始尺寸

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # --- 左侧：控制面板 ---
        control_panel = QWidget()
        control_panel.setFixedWidth(250)
        control_layout = QVBoxLayout(control_panel)

        self.kinetics_box = CollapsibleBox(self.tr("Kinetics Analysis"))
        kinetics_layout = QVBoxLayout()
        self.clear_kinetics_button = QPushButton(self.tr("Clear Kinetics Data"))
        self.correct_drift_button = QPushButton(self.tr("Drift Correction"))
        self.analyze_kinetics_button = QPushButton(self.tr("Analyze Kinetics Curve"))

        kinetics_layout.addWidget(self.clear_kinetics_button)
        kinetics_layout.addWidget(self.correct_drift_button)
        kinetics_layout.addWidget(self.analyze_kinetics_button)
        self.kinetics_box.setContentLayout(kinetics_layout)

        control_layout.addWidget(self.kinetics_box)
        control_layout.addStretch()

        # --- 右侧：图表区 ---
        plots_widget = QWidget()
        plots_layout = QGridLayout(plots_widget)

        # 创建图表
        self.result_plot = pg.PlotWidget()
        self.result_plot.showGrid(x=True, y=True)  # <-- 新增
        self.result_curve = self.result_plot.plot(pen='y')

        self.summary_plot = pg.PlotWidget()
        self.summary_plot.showGrid(x=True, y=True)  # <-- 新增

        self.sensorgram_plot = pg.PlotWidget()
        self.sensorgram_plot.showGrid(x=True, y=True)  # <-- 新增
        self.sensorgram_curve = self.sensorgram_plot.plot(pen='m', symbol='o', symbolSize=5, symbolBrush='m')

        # 将图表添加到布局
        plots_layout.addWidget(self.result_plot, 0, 0)
        plots_layout.addWidget(self.summary_plot, 0, 1)
        plots_layout.addWidget(self.sensorgram_plot, 1, 0, 1, 2)  # sensorgram 占据下面一整行

        main_layout.addWidget(control_panel)
        main_layout.addWidget(plots_widget, stretch=1)

        self.kinetics_box.set_expanded(True)

    def _connect_signals(self):
        self.clear_kinetics_button.clicked.connect(self._clear_kinetics_data)
        self.correct_drift_button.clicked.connect(self._open_drift_correction_dialog)
        self.analyze_kinetics_button.clicked.connect(self._open_kinetics_analysis_dialog)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Real-time Kinetics Analysis"))

        # 控制面板
        self.kinetics_box.toggle_button.setText(self.tr("Kinetics Analysis"))
        self.clear_kinetics_button.setText(self.tr("Clear Kinetics Data"))
        self.correct_drift_button.setText(self.tr("Drift Correction"))
        self.analyze_kinetics_button.setText(self.tr("Analyze Kinetics Curve"))

        # 图表
        self.result_plot.setTitle(self.tr("Real-time Result Spectrum"), color='#90A4AE', size='12pt')
        self.result_plot.setLabel('bottom', self.tr('Wavelength (nm)'))
        self.result_plot.setLabel('left', self.tr('Absorbance'))  # 假设是吸收模式

        self.summary_plot.setTitle(self.tr("Accumulated Results"), color='#90A4AE', size='12pt')
        self.summary_plot.setLabel('bottom', self.tr('Wavelength (nm)'))
        self.summary_plot.setLabel('left', self.tr('Absorbance'))

        self.sensorgram_plot.setTitle(self.tr("Kinetics Curve (Sensorgram)"), color='#90A4AE', size='12pt')
        self.sensorgram_plot.setLabel('bottom', self.tr('Time (s)'))
        self.sensorgram_plot.setLabel('left', self.tr('Peak Wavelength (nm)'))

    def closeEvent(self, event):
        """当窗口关闭时，发射信号通知主窗口。"""
        self.closed.emit(self)
        super().closeEvent(event)

    # --- 后续将添加数据更新和分析的槽函数 ---

    def _clear_kinetics_data(self):
        """清空所有图表和数据。"""
        self.kinetics_time_data.clear()
        self.kinetics_wavelength_data.clear()
        self.accumulated_results.clear()

        self.sensorgram_curve.clear()
        self.summary_plot.clear()

        print("Kinetics data in the pop-out window has been cleared.")

    def _open_drift_correction_dialog(self):
        if not self.kinetics_time_data: return
        dialog = DriftCorrectionDialog(self.kinetics_time_data, self.kinetics_wavelength_data, self)
        if dialog.exec_() == QDialog.Accepted:
            corrected_data = dialog.get_corrected_data()
            if corrected_data is not None:
                self.kinetics_wavelength_data = list(corrected_data)
                self.sensorgram_curve.setData(self.kinetics_time_data, self.kinetics_wavelength_data)

    def _open_kinetics_analysis_dialog(self):
        if len(self.kinetics_time_data) < 5: return
        dialog = KineticsAnalysisDialog(self.kinetics_time_data, self.kinetics_wavelength_data, self.main_window)
        dialog.exec_()

    def update_kinetics_data(self, data_package):
        """
        一个核心的槽函数，用于接收从主窗口发来的实时数据包并更新所有图表。
        """
        # 更新实时结果谱
        result_x = data_package.get('result_x')
        result_y = data_package.get('result_y')
        if result_x is not None and result_y is not None:
            self.result_curve.setData(result_x, result_y)

        # 更新动力学曲线
        elapsed_time = data_package.get('elapsed_time')
        peak_wl = data_package.get('peak_wl')
        if elapsed_time is not None and peak_wl is not None:
            self.kinetics_time_data.append(elapsed_time)
            self.kinetics_wavelength_data.append(peak_wl)
            self.sensorgram_curve.setData(self.kinetics_time_data, self.kinetics_wavelength_data)

            # 添加到累计结果中并更新
            self.accumulated_results.append(result_y)
            self._update_summary_plot(result_x)

    def _update_summary_plot(self, wavelengths):
        """更新累计结果谱图。"""
        self.summary_plot.clear()
        for i, spectrum in enumerate(self.accumulated_results):
            # 使用带透明度的颜色，让曲线叠加更清晰
            color = pg.intColor(i, hues=len(self.accumulated_results), alpha=150)
            self.summary_plot.plot(wavelengths, spectrum, pen=pg.mkPen(color))