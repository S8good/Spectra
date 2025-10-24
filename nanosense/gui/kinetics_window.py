# nanosense/gui/kinetics_window.py

import os
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QDialog,
    QToolButton,
    QLabel,
)
from PyQt5.QtCore import pyqtSignal, QEvent
import pyqtgraph as pg
from PyQt5.QtGui import QIcon

from .collapsible_box import CollapsibleBox
from .kinetics_analysis_dialog import KineticsAnalysisDialog
from .drift_correction_dialog import DriftCorrectionDialog
from .single_plot_window import SinglePlotWindow


class SummaryPopoutWindow(QMainWindow):
    closed = pyqtSignal(object)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.window_title_source = title
        self._user_interacted = False

        self.setGeometry(220, 220, 900, 600)

        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(6)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.addStretch()
        self.reset_button = QPushButton()
        self.reset_button.setFixedWidth(140)
        toolbar_layout.addWidget(self.reset_button)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.getViewBox().sigStateChanged.connect(self._on_view_interacted)

        main_layout.addLayout(toolbar_layout)
        main_layout.addWidget(self.plot_widget, stretch=1)

        self.setCentralWidget(central_widget)

        self._curves = []
        self.reset_button.clicked.connect(self._reset_view)
        self._retranslate_ui()

    def _on_view_interacted(self):
        self._user_interacted = True

    def _reset_view(self):
        self._user_interacted = False
        self.plot_widget.enableAutoRange(x=True, y=True)

    def update_curves(self, data_pairs):
        if data_pairs is None:
            return

        pairs = [
            (
                np.asarray(x_vals),
                np.asarray(y_vals)
            )
            for x_vals, y_vals in data_pairs
            if x_vals is not None and y_vals is not None
        ]

        pairs = [pair for pair in pairs if pair[0].ndim == 1 and pair[1].ndim == 1 and pair[0].size == pair[1].size]
        if not pairs:
            return

        # ensure same number of PlotDataItems as curves
        while len(self._curves) < len(pairs):
            curve = self.plot_widget.plot()
            self._curves.append(curve)
        while len(self._curves) > len(pairs):
            curve = self._curves.pop()
            self.plot_widget.removeItem(curve)

        total = len(pairs)
        for idx, ((x_vals, y_vals), curve) in enumerate(zip(pairs, self._curves)):
            color = pg.intColor(idx, hues=max(total, 1), alpha=180)
            curve.setData(x_vals, y_vals, pen=pg.mkPen(color))

        if not self._user_interacted:
            self.plot_widget.enableAutoRange(x=True, y=True)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        translated_title = self.tr(self.window_title_source)
        self.setWindowTitle(translated_title)
        self.plot_widget.setTitle(translated_title, color='#90A4AE', size='12pt')
        self.reset_button.setText(self.tr("Reset View"))

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)


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
        self._popout_windows = []

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
        self.reset_summary_button = QPushButton(self.tr("Reset Summary View"))
        self.reset_sensor_button = QPushButton(self.tr("Reset Sensorgram View"))

        kinetics_layout.addWidget(self.clear_kinetics_button)
        kinetics_layout.addWidget(self.correct_drift_button)
        kinetics_layout.addWidget(self.analyze_kinetics_button)
        kinetics_layout.addWidget(self.reset_summary_button)
        kinetics_layout.addWidget(self.reset_sensor_button)
        self.kinetics_box.setContentLayout(kinetics_layout)

        control_layout.addWidget(self.kinetics_box)
        control_layout.addStretch()

        # --- 右侧：图表区 ---
        plots_widget = QWidget()
        plots_layout = QVBoxLayout(plots_widget)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        plots_layout.setSpacing(12)

        self.summary_plot = pg.PlotWidget()
        self.summary_plot.showGrid(x=True, y=True)
        (self.summary_container,
         self.summary_title_label,
         self.summary_popout_button) = self._create_plot_container(
            self.summary_plot,
            "Accumulated Results",
            self._open_summary_popout
        )

        self.sensorgram_plot = pg.PlotWidget()
        self.sensorgram_plot.showGrid(x=True, y=True)
        self.sensorgram_curve = self.sensorgram_plot.plot(pen='m', symbol='o', symbolSize=5, symbolBrush='m')
        (self.sensor_container,
         self.sensor_title_label,
         self.sensor_popout_button) = self._create_plot_container(
            self.sensorgram_plot,
            "Kinetics Curve (Sensorgram)",
            self._open_sensorgram_popout
        )

        plots_layout.addWidget(self.summary_container, stretch=1)
        plots_layout.addWidget(self.sensor_container, stretch=1)

        main_layout.addWidget(control_panel)
        main_layout.addWidget(plots_widget, stretch=1)

        self.kinetics_box.set_expanded(True)

    def _connect_signals(self):
        self.clear_kinetics_button.clicked.connect(self._clear_kinetics_data)
        self.correct_drift_button.clicked.connect(self._open_drift_correction_dialog)
        self.analyze_kinetics_button.clicked.connect(self._open_kinetics_analysis_dialog)
        self.reset_summary_button.clicked.connect(self._reset_summary_view)
        self.reset_sensor_button.clicked.connect(self._reset_sensorgram_view)

    def _create_plot_container(self, plot_widget, title_key, popout_handler):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 2, 5, 2)

        title_label = QLabel(self.tr(title_key))
        title_label.setStyleSheet("color: #90A4AE; font-size: 12pt;")

        popout_button = QToolButton()
        icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'icons', 'zoom.png')
        if os.path.exists(icon_path):
            popout_button.setIcon(QIcon(icon_path))
        popout_button.setToolTip(self.tr("Open in New Window"))
        popout_button.clicked.connect(popout_handler)

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(popout_button)

        layout.addWidget(header_widget)
        layout.addWidget(plot_widget)

        plot_widget.setTitle("")
        plot_widget.showGrid(x=True, y=True, alpha=0.3)

        return container, title_label, popout_button

    def _reset_summary_view(self):
        self.summary_plot.enableAutoRange(x=True, y=True)

    def _reset_sensorgram_view(self):
        self.sensorgram_plot.enableAutoRange(x=True, y=True)

    def _open_summary_popout(self):
        if not self.accumulated_results:
            return
        window = SummaryPopoutWindow(self.tr("Accumulated Results"), parent=self)
        window.closed.connect(self._on_popout_closed)
        window.update_curves(self.accumulated_results)
        window.show()
        self._popout_windows.append({'window': window, 'type': 'summary'})

    def _open_sensorgram_popout(self):
        if not self.kinetics_time_data:
            return
        self._open_popout_plot(
            self.kinetics_time_data,
            self.kinetics_wavelength_data,
            self.tr("Kinetics Curve (Sensorgram)"),
            pen=pg.mkPen('m', width=2),
            kind='sensor'
        )

    def _open_popout_plot(self, x_data, y_data, title, pen, kind):
        if x_data is None or y_data is None:
            return

        x_array = np.asarray(x_data)
        y_array = np.asarray(y_data)
        if x_array.size == 0 or y_array.size == 0:
            return

        window = SinglePlotWindow(title, parent=self)
        window.closed.connect(self._on_popout_closed)
        window.update_data(x_array, y_array, pen)
        window.show()
        self._popout_windows.append({
            'window': window,
            'type': kind,
            'pen': pen
        })

    def _on_popout_closed(self, window):
        self._popout_windows = [entry for entry in self._popout_windows if entry['window'] != window]

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
        self.summary_plot.setTitle(self.tr("Accumulated Results"), color='#90A4AE', size='12pt')
        self.summary_plot.setLabel('bottom', self.tr('Wavelength (nm)'))
        self.summary_plot.setLabel('left', self.tr('Absorbance'))

        self.sensorgram_plot.setTitle(self.tr("Kinetics Curve (Sensorgram)"), color='#90A4AE', size='12pt')
        self.sensorgram_plot.setLabel('bottom', self.tr('Time (s)'))
        self.sensorgram_plot.setLabel('left', self.tr('Peak Wavelength (nm)'))

        self.summary_title_label.setText(self.tr("Accumulated Results"))
        self.sensor_title_label.setText(self.tr("Kinetics Curve (Sensorgram)"))
        self.summary_popout_button.setToolTip(self.tr("Open in New Window"))
        self.sensor_popout_button.setToolTip(self.tr("Open in New Window"))

        self.reset_summary_button.setText(self.tr("Reset Summary View"))
        self.reset_sensor_button.setText(self.tr("Reset Sensorgram View"))

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
        self._reset_summary_view()
        self._reset_sensorgram_view()

        for entry in list(self._popout_windows):
            window = entry.get('window') if isinstance(entry, dict) else entry
            try:
                if window:
                    window.close()
            except Exception:
                pass
        self._popout_windows.clear()

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
        result_x = data_package.get('result_x')
        result_y = data_package.get('result_y')

        elapsed_time = data_package.get('elapsed_time')
        peak_wl = data_package.get('peak_wl')
        if elapsed_time is not None and peak_wl is not None:
            self.kinetics_time_data.append(elapsed_time)
            self.kinetics_wavelength_data.append(peak_wl)
            self.sensorgram_curve.setData(self.kinetics_time_data, self.kinetics_wavelength_data)

            # 添加到累计结果中并更新
            if result_x is not None and result_y is not None:
                self.accumulated_results.append((np.array(result_x, copy=True), np.array(result_y, copy=True)))
                self._update_summary_plot()
        self._refresh_popouts()

    def _update_summary_plot(self):
        """更新累计结果谱图"""
        view_box = self.summary_plot.getViewBox()
        current_range = view_box.viewRange()
        auto_state = view_box.state.get('autoRange', [True, True])

        self.summary_plot.clear()
        if not self.accumulated_results:
            return

        total = len(self.accumulated_results)
        for index, pair in enumerate(self.accumulated_results):
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                continue
            wavelengths, spectrum = pair
            if wavelengths is None or spectrum is None:
                continue
            if len(wavelengths) != len(spectrum) or len(wavelengths) == 0:
                continue

            color = pg.intColor(index, hues=total, alpha=150)
            self.summary_plot.plot(wavelengths, spectrum, pen=pg.mkPen(color))

        auto_x = auto_state[0] if isinstance(auto_state, (list, tuple)) and len(auto_state) > 0 else True
        auto_y = auto_state[1] if isinstance(auto_state, (list, tuple)) and len(auto_state) > 1 else True
        if not auto_x and current_range and len(current_range) > 0:
            self.summary_plot.setXRange(current_range[0][0], current_range[0][1], padding=0)
        if not auto_y and current_range and len(current_range) > 1:
            self.summary_plot.setYRange(current_range[1][0], current_range[1][1], padding=0)
        self.summary_plot.enableAutoRange(x=auto_x, y=auto_y)

    def _refresh_popouts(self):
        if not self._popout_windows:
            return

        sensor_x = np.asarray(self.kinetics_time_data)
        sensor_y = np.asarray(self.kinetics_wavelength_data)

        for entry in list(self._popout_windows):
            window = entry.get('window')
            window_type = entry.get('type')
            if not window:
                continue

            if window_type == 'summary':
                if self.accumulated_results:
                    window.update_curves(self.accumulated_results)
            elif window_type == 'sensor' and sensor_x.size and sensor_y.size:
                pen = entry.get('pen')
                window.update_data(sensor_x, sensor_y, pen)

