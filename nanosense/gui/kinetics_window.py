# nanosense/gui/kinetics_window.py

import os
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QDialog,
    QToolButton,
    QLabel,
    QFormLayout,
    QDoubleSpinBox,
)
from PyQt5.QtCore import pyqtSignal, QEvent
from PyQt5.QtGui import QIcon
import pyqtgraph as pg

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
        main_layout.setSpacing(8)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.addStretch()
        self.reset_button = QPushButton()
        self.reset_button.setFixedWidth(150)
        toolbar_layout.addWidget(self.reset_button)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.getViewBox().sigStateChanged.connect(self._on_view_interacted)

        main_layout.addLayout(toolbar_layout)
        main_layout.addWidget(self.plot_widget)

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
        if not data_pairs:
            return

        pairs = []
        for x_vals, y_vals in data_pairs:
            if x_vals is None or y_vals is None:
                continue
            x_array = np.asarray(x_vals)
            y_array = np.asarray(y_vals)
            if x_array.ndim == 1 and y_array.ndim == 1 and x_array.size == y_array.size:
                pairs.append((x_array, y_array))

        if not pairs:
            return

        while len(self._curves) < len(pairs):
            self._curves.append(self.plot_widget.plot())
        while len(self._curves) > len(pairs):
            curve = self._curves.pop()
            self.plot_widget.removeItem(curve)

        total = len(pairs)
        for index, ((x_vals, y_vals), curve) in enumerate(zip(pairs, self._curves)):
            color = pg.intColor(index, hues=max(total, 1), alpha=200)
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
        self.plot_widget.setTitle(translated_title, color="#90A4AE", size="12pt")
        self.reset_button.setText(self.tr("Reset View"))

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)


class KineticsWindow(QMainWindow):
    """
    独立的实时动力学监测窗口。
    """

    closed = pyqtSignal(object)
    baseline_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setObjectName("KineticsWindowRoot")

        self.kinetics_time_data = []
        self.kinetics_wavelength_data = []
        self.accumulated_results = []
        self._popout_windows = []
        self.baseline_peak_wavelength = None
        self.peak_shift_time_data = []
        self.peak_shift_values = []
        self.noise_time_data = []
        self.noise_values = []
        self._shift_user_interacted = False
        self._noise_user_interacted = False

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()
        self._apply_theme()

    def _init_ui(self):
        self.setWindowTitle(self.tr("Real-time Kinetics Analysis"))
        self.setGeometry(240, 160, 1200, 780)

        central_widget = QWidget()
        central_widget.setObjectName("kineticsCentralWidget")
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(18)

        # --- 左侧控制面板 ---
        control_panel = QWidget()
        control_panel.setObjectName("kineticsControlPanel")
        control_panel.setFixedWidth(360)
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(18, 18, 18, 18)
        control_layout.setSpacing(14)

        self.kinetics_box = CollapsibleBox(self.tr("Kinetics Analysis"))
        kinetics_layout = QVBoxLayout()
        kinetics_layout.setSpacing(10)

        baseline_form = QFormLayout()
        baseline_form.setSpacing(6)
        baseline_form.setContentsMargins(0, 0, 0, 0)

        self.baseline_spinbox = QDoubleSpinBox()
        self.baseline_spinbox.setDecimals(3)
        self.baseline_spinbox.setRange(0.0, 2000.0)
        self.baseline_spinbox.setSingleStep(0.1)
        self.baseline_spinbox.setSuffix(" nm")
        self.baseline_spinbox.setSpecialValueText(self.tr("Not Set"))
        baseline_form.addRow(self.tr("Baseline Peak (nm):"), self.baseline_spinbox)
        kinetics_layout.addLayout(baseline_form)

        baseline_button_layout = QHBoxLayout()
        baseline_button_layout.setSpacing(8)
        self.apply_baseline_button = QPushButton(self.tr("Apply Baseline"))
        self.clear_baseline_button = QPushButton(self.tr("Clear Baseline"))
        baseline_button_layout.addWidget(self.apply_baseline_button)
        baseline_button_layout.addWidget(self.clear_baseline_button)
        kinetics_layout.addLayout(baseline_button_layout)

        self.baseline_status_label = QLabel(self.tr("Baseline: Not Set"))
        self.baseline_status_label.setObjectName("baselineStatusLabel")
        kinetics_layout.addWidget(self.baseline_status_label)

        self.clear_kinetics_button = QPushButton(self.tr("Clear Kinetics Data"))
        self.correct_drift_button = QPushButton(self.tr("Drift Correction"))
        self.analyze_kinetics_button = QPushButton(self.tr("Analyze Kinetics Curve"))
        self.reset_summary_button = QPushButton(self.tr("Reset Summary View"))
        self.reset_sensor_button = QPushButton(self.tr("Reset Sensorgram View"))
        self.reset_shift_button = QPushButton(self.tr("Reset Peak Shift View"))
        self.reset_noise_button = QPushButton(self.tr("Reset Noise View"))

        button_grid = QGridLayout()
        button_grid.setSpacing(10)
        button_grid.addWidget(self.clear_kinetics_button, 0, 0, 1, 2)
        button_grid.addWidget(self.correct_drift_button, 1, 0)
        button_grid.addWidget(self.analyze_kinetics_button, 1, 1)
        button_grid.addWidget(self.reset_summary_button, 2, 0)
        button_grid.addWidget(self.reset_sensor_button, 2, 1)
        button_grid.addWidget(self.reset_shift_button, 3, 0)
        button_grid.addWidget(self.reset_noise_button, 3, 1)
        kinetics_layout.addLayout(button_grid)

        self.kinetics_box.setContentLayout(kinetics_layout)

        control_layout.addWidget(self.kinetics_box)
        control_layout.addStretch()

        # --- 右侧图表区域 ---
        plots_widget = QWidget()
        plots_widget.setObjectName("kineticsPlotsPanel")
        plots_layout = QGridLayout(plots_widget)
        plots_layout.setContentsMargins(18, 18, 18, 18)
        plots_layout.setHorizontalSpacing(18)
        plots_layout.setVerticalSpacing(18)

        self.summary_plot = pg.PlotWidget()
        (self.summary_container,
         self.summary_title_label,
         self.summary_popout_button) = self._create_plot_container(
            self.summary_plot,
            "Accumulated Results Summary",
            self._open_summary_popout
        )

        self.sensorgram_plot = pg.PlotWidget()
        self.sensorgram_curve = self.sensorgram_plot.plot(
            pen=pg.mkPen('#E91E63', width=2),
            symbol='o',
            symbolSize=6,
            symbolBrush='#F06292'
        )
        (self.sensor_container,
         self.sensor_title_label,
         self.sensor_popout_button) = self._create_plot_container(
            self.sensorgram_plot,
            "Kinetics Curve (Sensorgram)",
            self._open_sensorgram_popout
        )

        self.peak_shift_plot = pg.PlotWidget()
        self.peak_shift_plot.getViewBox().sigStateChanged.connect(self._on_shift_view_interacted)
        self.peak_shift_curve = self.peak_shift_plot.plot(
            pen=pg.mkPen('#FFB74D', width=2),
            symbol='o',
            symbolBrush='#FFD54F',
            symbolSize=6
        )
        (self.peak_shift_container,
         self.peak_shift_title_label,
         self.peak_shift_popout_button) = self._create_plot_container(
            self.peak_shift_plot,
            "Peak Wavelength Shift",
            self._open_peak_shift_popout
        )

        self.noise_trend_plot = pg.PlotWidget()
        self.noise_trend_plot.getViewBox().sigStateChanged.connect(self._on_noise_view_interacted)
        self.noise_trend_curve = self.noise_trend_plot.plot(
            pen=pg.mkPen('#4DB6AC', width=2),
            symbol='o',
            symbolBrush='#80CBC4',
            symbolSize=6
        )
        (self.noise_container,
         self.noise_title_label,
         self.noise_popout_button) = self._create_plot_container(
            self.noise_trend_plot,
            "Real-time Average Noise Trend",
            self._open_noise_popout
        )

        plots_layout.addWidget(self.summary_container, 0, 0)
        plots_layout.addWidget(self.peak_shift_container, 0, 1)
        plots_layout.addWidget(self.sensor_container, 1, 0)
        plots_layout.addWidget(self.noise_container, 1, 1)
        plots_layout.setRowStretch(0, 1)
        plots_layout.setRowStretch(1, 1)
        plots_layout.setColumnStretch(0, 1)
        plots_layout.setColumnStretch(1, 1)

        main_layout.addWidget(control_panel)
        main_layout.addWidget(plots_widget, stretch=1)

        self.kinetics_box.set_expanded(True)
        self._style_plot(self.summary_plot)
        self._style_plot(self.sensorgram_plot)
        self._style_plot(self.peak_shift_plot)
        self._style_plot(self.noise_trend_plot)

    def _connect_signals(self):
        self.apply_baseline_button.clicked.connect(self._apply_baseline_value)
        self.clear_baseline_button.clicked.connect(self._clear_baseline_value)
        self.clear_kinetics_button.clicked.connect(self._clear_kinetics_data)
        self.correct_drift_button.clicked.connect(self._open_drift_correction_dialog)
        self.analyze_kinetics_button.clicked.connect(self._open_kinetics_analysis_dialog)
        self.reset_summary_button.clicked.connect(self._reset_summary_view)
        self.reset_sensor_button.clicked.connect(self._reset_sensorgram_view)
        self.reset_shift_button.clicked.connect(self._reset_peak_shift_view)
        self.reset_noise_button.clicked.connect(self._reset_noise_view)

    # --- UI helpers -----------------------------------------------------
    def _create_plot_container(self, plot_widget, title_key, popout_handler):
        """创建带标题和弹出按钮的图表容器"""
        container = QWidget()
        container.setObjectName("plotCard")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("plotHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)

        title_label = QLabel(self.tr(title_key))
        title_label.setObjectName("plotTitleLabel")

        popout_button = QToolButton()
        popout_button.setObjectName("plotPopoutButton")
        # 根据当前主题选择合适的图标
        self._update_popout_button_icon(popout_button)
        popout_button.setToolTip(self.tr("Open in New Window"))
        popout_button.clicked.connect(popout_handler)

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(popout_button)

        layout.addWidget(header)
        layout.addWidget(plot_widget)

        plot_widget.setTitle("")
        plot_widget.showGrid(x=True, y=True, alpha=0.3)

        return container, title_label, popout_button

    def _update_popout_button_icon(self, button):
        """根据当前主题更新弹出按钮的图标"""
        # 获取当前主题设置
        try:
            from ..utils.config_manager import load_settings
            settings = load_settings()
            theme = settings.get('theme', 'dark')
            
            # 根据主题选择图标
            if theme == 'light':
                icon_filename = 'zoom_dark.png'  # 浅色主题使用深色图标
            else:
                icon_filename = 'zoom.png'  # 深色主题使用白色图标
                
            icon_path = os.path.join(os.path.dirname(__file__), "assets", "icons", icon_filename)
            if os.path.exists(icon_path):
                button.setIcon(QIcon(icon_path))
            else:
                # 如果深色图标不存在，回退到原始图标
                original_icon_path = os.path.join(os.path.dirname(__file__), "assets", "icons", "zoom.png")
                button.setIcon(QIcon(original_icon_path))
        except Exception:
            # 如果无法加载设置或图标，使用默认图标
            icon_path = os.path.join(os.path.dirname(__file__), "assets", "icons", "zoom.png")
            button.setIcon(QIcon(icon_path))

    def _update_all_popout_icons(self):
        """更新所有弹出按钮的图标"""
        # 更新所有图表的弹出按钮图标
        try:
            if hasattr(self, 'summary_popout_button'):
                self._update_popout_button_icon(self.summary_popout_button)
            if hasattr(self, 'sensor_popout_button'):
                self._update_popout_button_icon(self.sensor_popout_button)
            if hasattr(self, 'peak_shift_popout_button'):
                self._update_popout_button_icon(self.peak_shift_popout_button)
            if hasattr(self, 'noise_popout_button'):
                self._update_popout_button_icon(self.noise_popout_button)
        except Exception:
            pass  # 忽略错误

    def _style_plot(self, plot_widget):
        # 获取当前主题设置
        try:
            from ..utils.config_manager import load_settings
            settings = load_settings()
            theme = settings.get('theme', 'dark')
            
            # 根据主题设置不同的背景色和样式
            if theme == 'light':
                plot_widget.setBackground("#F0F0F0")  # 偏暗的浅色背景
                axis_pen = pg.mkPen("#000000", width=1)  # 坐标轴使用黑色
                text_pen = pg.mkPen("#000000")  # 坐标文本使用黑色
                grid_alpha = 0.15
                border_pen = pg.mkPen("#CED4DA", width=1)
            else:
                plot_widget.setBackground("#1F2735")  # 深色背景
                axis_pen = pg.mkPen("#4D5A6D", width=1)
                text_pen = pg.mkPen("#E2E8F0")
                grid_alpha = 0.15
                border_pen = pg.mkPen("#39475A", width=1)
                
            for axis in ("left", "bottom"):
                ax = plot_widget.getPlotItem().getAxis(axis)
                ax.setPen(axis_pen)
                ax.setTextPen(text_pen)
                ax.setStyle(tickLength=6)
            plot_widget.getPlotItem().showGrid(x=True, y=True, alpha=grid_alpha)
            plot_widget.getViewBox().setBorder(border_pen)
        except Exception:
            # 如果无法加载设置，使用默认样式
            plot_widget.setBackground("#1F2735")
            axis_pen = pg.mkPen("#4D5A6D", width=1)
            text_pen = pg.mkPen("#E2E8F0")
            for axis in ("left", "bottom"):
                ax = plot_widget.getPlotItem().getAxis(axis)
                ax.setPen(axis_pen)
                ax.setTextPen(text_pen)
                ax.setStyle(tickLength=6)
            plot_widget.getPlotItem().showGrid(x=True, y=True, alpha=0.15)
            plot_widget.getViewBox().setBorder(pg.mkPen("#39475A", width=1))

    def _apply_theme(self):
        self.setStyleSheet("""
#KineticsWindowRoot {
    background-color: #1A202C;
    color: #E2E8F0;
    font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
    font-size: 13px;
}
#kineticsCentralWidget {
    background-color: #1A202C;
}
#kineticsControlPanel {
    background-color: #2D3748;
    border: 1px solid #4A5568;
    border-radius: 12px;
    color: #E2E8F0;
}
#kineticsControlPanel QWidget {
    background-color: transparent;
    color: #E2E8F0;
}
#kineticsControlPanel QLabel {
    color: #E2E8F0;
}
#kineticsPlotsPanel {
    background-color: #2D3748;
    border: 1px solid #4A5568;
    border-radius: 12px;
}
#plotCard {
    background-color: #1F2735;
    border: 1px solid #39475A;
    border-radius: 12px;
}
#plotHeader {
    border-bottom: 1px solid #39475A;
    background-color: rgba(255, 255, 255, 0.04);
}
#plotTitleLabel {
    color: #E2E8F0;
    font-size: 12pt;
    font-weight: 600;
}
#plotPopoutButton {
    background-color: transparent;
    border: 1px solid #4A5568;
    border-radius: 6px;
    padding: 4px;
}
#plotPopoutButton:hover {
    background-color: #2B6CB0;
    border-color: #2B6CB0;
}
QLabel#baselineStatusLabel {
    color: #A0AEC0;
}
CollapsibleBox {
    background-color: transparent;
}
CollapsibleBox > QScrollArea {
    background-color: transparent;
    border: none;
}
CollapsibleBox > QScrollArea > QWidget {
    background-color: transparent;
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
#kineticsControlPanel QPushButton {
    background-color: #3182CE;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    color: #FFFFFF;
    font-weight: 600;
}
#kineticsControlPanel QPushButton:hover {
    background-color: #2B6CB0;
}
#kineticsControlPanel QPushButton:pressed {
    background-color: #245A86;
}
#kineticsControlPanel QPushButton:disabled {
    background-color: #4A5568;
    color: #A0AEC0;
}
CollapsibleBox > QToolButton {
    background-color: #2D3748;
    border: 1px solid #4A5568;
    border-radius: 6px;
    padding: 10px 12px;
    color: #E2E8F0;
    font-weight: 600;
    text-align: left;
}
CollapsibleBox > QToolButton:hover {
    background-color: #2B3647;
}
        """)
        # 更新所有弹出按钮的图标
        self._update_all_popout_icons()

    # --- Reset helpers --------------------------------------------------
    def _reset_summary_view(self):
        self.summary_plot.enableAutoRange(x=True, y=True)

    def _reset_sensorgram_view(self):
        self.sensorgram_plot.enableAutoRange(x=True, y=True)

    def _reset_peak_shift_view(self):
        self._shift_user_interacted = False
        self.peak_shift_plot.enableAutoRange(x=True, y=True)

    def _reset_noise_view(self):
        self._noise_user_interacted = False
        self.noise_trend_plot.enableAutoRange(x=True, y=True)

    def _on_shift_view_interacted(self):
        self._shift_user_interacted = True

    def _on_noise_view_interacted(self):
        self._noise_user_interacted = True

    # --- Baseline -------------------------------------------------------
    def _apply_baseline_value(self):
        value = float(self.baseline_spinbox.value())
        if value <= 0:
            self.baseline_peak_wavelength = None
        else:
            self.baseline_peak_wavelength = value
        self._update_baseline_status()
        self._rebuild_peak_shift_curve()
        self.baseline_changed.emit(self.baseline_peak_wavelength)

    def _clear_baseline_value(self):
        self.baseline_peak_wavelength = None
        block = self.baseline_spinbox.blockSignals(True)
        self.baseline_spinbox.setValue(self.baseline_spinbox.minimum())
        self.baseline_spinbox.blockSignals(block)
        self._update_baseline_status()
        self._rebuild_peak_shift_curve()
        self.baseline_changed.emit(self.baseline_peak_wavelength)

    def _update_baseline_status(self):
        if self.baseline_peak_wavelength is None:
            self.baseline_status_label.setText(self.tr("Baseline: Not Set"))
        else:
            self.baseline_status_label.setText(
                self.tr("Baseline: {0:.3f} nm").format(self.baseline_peak_wavelength)
            )

    def set_baseline_peak_wavelength(self, baseline_value):
        if baseline_value is None:
            self._clear_baseline_value()
            return
        value = float(baseline_value)
        block = self.baseline_spinbox.blockSignals(True)
        self.baseline_spinbox.setValue(value)
        self.baseline_spinbox.blockSignals(block)
        self.baseline_peak_wavelength = value
        self._update_baseline_status()
        self._rebuild_peak_shift_curve()

    def _rebuild_peak_shift_curve(self):
        if self.baseline_peak_wavelength is None:
            self.peak_shift_time_data.clear()
            self.peak_shift_values.clear()
            self.peak_shift_curve.clear()
            return

        shifts = [float(w) - self.baseline_peak_wavelength for w in self.kinetics_wavelength_data]
        self.peak_shift_time_data = list(self.kinetics_time_data)
        self.peak_shift_values = shifts
        self.peak_shift_curve.setData(self.peak_shift_time_data, self.peak_shift_values)
        if not self._shift_user_interacted:
            self.peak_shift_plot.enableAutoRange(x=True, y=True)

    # --- Popout windows -------------------------------------------------
    def _open_summary_popout(self):
        if not self.accumulated_results:
            return
        window = SummaryPopoutWindow(self.tr("Accumulated Results Summary"), parent=self)
        window.closed.connect(self._on_popout_closed)
        window.update_curves(self.accumulated_results)
        window.show()
        self._popout_windows.append({"window": window, "type": "summary"})

    def _open_sensorgram_popout(self):
        if not self.kinetics_time_data:
            return
        self._open_popout_plot(
            self.kinetics_time_data,
            self.kinetics_wavelength_data,
            self.tr("Kinetics Curve (Sensorgram)"),
            pen=pg.mkPen('#E91E63', width=2),
            kind="sensor"
        )

    def _open_peak_shift_popout(self):
        if not self.peak_shift_time_data:
            return
        self._open_popout_plot(
            self.peak_shift_time_data,
            self.peak_shift_values,
            self.tr("Peak Wavelength Shift"),
            pen=pg.mkPen('#FFB74D', width=2),
            kind="peak_shift"
        )

    def _open_noise_popout(self):
        if not self.noise_time_data:
            return
        self._open_popout_plot(
            self.noise_time_data,
            self.noise_values,
            self.tr("Real-time Average Noise Trend"),
            pen=pg.mkPen('#4DB6AC', width=2),
            kind="noise"
        )

    def _open_popout_plot(self, x_data, y_data, title, pen, kind):
        if x_data is None or y_data is None:
            return
        x_array = np.asarray(x_data)
        y_array = np.asarray(y_data)
        if not x_array.size or not y_array.size:
            return
        window = SinglePlotWindow(title, parent=self)
        window.closed.connect(self._on_popout_closed)
        window.update_data(x_array, y_array, pen)
        window.show()
        self._popout_windows.append({"window": window, "type": kind, "pen": pen})

    def _on_popout_closed(self, window):
        self._popout_windows = [entry for entry in self._popout_windows if entry["window"] != window]

    # --- Data handling --------------------------------------------------
    def _clear_kinetics_data(self):
        self.kinetics_time_data.clear()
        self.kinetics_wavelength_data.clear()
        self.accumulated_results.clear()
        self.peak_shift_time_data.clear()
        self.peak_shift_values.clear()
        self.noise_time_data.clear()
        self.noise_values.clear()

        self.sensorgram_curve.clear()
        self.summary_plot.clear()
        self.peak_shift_curve.clear()
        self.noise_trend_curve.clear()

        self._reset_summary_view()
        self._reset_sensorgram_view()
        self._reset_peak_shift_view()
        self._reset_noise_view()

        for entry in list(self._popout_windows):
            window = entry.get("window")
            if window:
                try:
                    window.close()
                except Exception:
                    pass
        self._popout_windows.clear()

    def _open_drift_correction_dialog(self):
        if not self.kinetics_time_data:
            return
        dialog = DriftCorrectionDialog(self.kinetics_time_data, self.kinetics_wavelength_data, self)
        if dialog.exec_() == QDialog.Accepted:
            corrected = dialog.get_corrected_data()
            if corrected is not None:
                self.kinetics_wavelength_data = list(corrected)
                self.sensorgram_curve.setData(self.kinetics_time_data, self.kinetics_wavelength_data)
                self._rebuild_peak_shift_curve()

    def _open_kinetics_analysis_dialog(self):
        if len(self.kinetics_time_data) < 5:
            return
        dialog = KineticsAnalysisDialog(self.kinetics_time_data, self.kinetics_wavelength_data, self.main_window)
        dialog.exec_()

    def update_kinetics_data(self, data_package):
        result_x = data_package.get("result_x")
        result_y = data_package.get("result_y")
        elapsed_time = data_package.get("elapsed_time")
        peak_wl = data_package.get("peak_wl")

        if elapsed_time is not None and peak_wl is not None:
            elapsed_time = float(elapsed_time)
            peak_wl = float(peak_wl)
            self.kinetics_time_data.append(elapsed_time)
            self.kinetics_wavelength_data.append(peak_wl)
            self.sensorgram_curve.setData(self.kinetics_time_data, self.kinetics_wavelength_data)
            self._update_peak_shift_series(elapsed_time, peak_wl)

            if result_x is not None and result_y is not None:
                self.accumulated_results.append((np.array(result_x, copy=True), np.array(result_y, copy=True)))
                self._update_summary_plot()
                self._update_noise_trend(elapsed_time)

        self._refresh_popouts()

    def _update_peak_shift_series(self, elapsed_time, peak_wavelength):
        if self.baseline_peak_wavelength is None:
            return
        shift = peak_wavelength - self.baseline_peak_wavelength
        self.peak_shift_time_data.append(elapsed_time)
        self.peak_shift_values.append(shift)
        self.peak_shift_curve.setData(self.peak_shift_time_data, self.peak_shift_values)
        if not self._shift_user_interacted:
            self.peak_shift_plot.enableAutoRange(x=True, y=True)

    def _update_noise_trend(self, elapsed_time):
        if len(self.accumulated_results) < 1:
            return

        spectra = []
        min_length = None
        for wavelengths, spectrum in self.accumulated_results:
            if spectrum is None:
                continue
            arr = np.asarray(spectrum, dtype=float)
            if min_length is None or arr.size < min_length:
                min_length = arr.size
            spectra.append(arr)

        if not spectra or min_length is None or min_length == 0:
            return

        trimmed = np.array([spec[:min_length] for spec in spectra])
        if trimmed.shape[0] == 1:
            noise_value = 0.0
        else:
            noise_value = float(np.mean(np.std(trimmed, axis=0, ddof=0)))

        self.noise_time_data.append(float(elapsed_time))
        self.noise_values.append(noise_value)
        self.noise_trend_curve.setData(self.noise_time_data, self.noise_values)
        if not self._noise_user_interacted:
            self.noise_trend_plot.enableAutoRange(x=True, y=True)

    def _update_summary_plot(self):
        view_box = self.summary_plot.getViewBox()
        current_range = view_box.viewRange()
        auto_state = view_box.state.get("autoRange", [True, True])

        self.summary_plot.clear()
        if not self.accumulated_results:
            return

        total = len(self.accumulated_results)
        for index, pair in enumerate(self.accumulated_results):
            if (not isinstance(pair, (tuple, list))) or len(pair) != 2:
                continue
            wavelengths, spectrum = pair
            if wavelengths is None or spectrum is None:
                continue
            wavelengths = np.asarray(wavelengths)
            spectrum = np.asarray(spectrum)
            if wavelengths.ndim != 1 or spectrum.ndim != 1 or wavelengths.size != spectrum.size or not wavelengths.size:
                continue
            color = pg.intColor(index, hues=total, alpha=180)
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
            window = entry.get("window")
            kind = entry.get("type")
            if window is None:
                continue

            if kind == "summary":
                if self.accumulated_results:
                    window.update_curves(self.accumulated_results)
            elif kind == "sensor" and sensor_x.size and sensor_y.size:
                pen = entry.get("pen")
                window.update_data(sensor_x, sensor_y, pen)
            elif kind == "peak_shift" and self.peak_shift_time_data:
                pen = entry.get("pen")
                window.update_data(
                    np.asarray(self.peak_shift_time_data),
                    np.asarray(self.peak_shift_values),
                    pen
                )
            elif kind == "noise" and self.noise_time_data:
                pen = entry.get("pen")
                window.update_data(
                    np.asarray(self.noise_time_data),
                    np.asarray(self.noise_values),
                    pen
                )

    # --- Qt events ------------------------------------------------------
    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Real-time Kinetics Analysis"))

        self.kinetics_box.toggle_button.setText(self.tr("Kinetics Analysis"))
        self.apply_baseline_button.setText(self.tr("Apply Baseline"))
        self.clear_baseline_button.setText(self.tr("Clear Baseline"))
        self.baseline_spinbox.setSuffix(" " + self.tr("nm"))
        self.baseline_spinbox.setSpecialValueText(self.tr("Not Set"))
        self._update_baseline_status()
        self.clear_kinetics_button.setText(self.tr("Clear Kinetics Data"))
        self.correct_drift_button.setText(self.tr("Drift Correction"))
        self.analyze_kinetics_button.setText(self.tr("Analyze Kinetics Curve"))
        self.reset_summary_button.setText(self.tr("Reset Summary View"))
        self.reset_sensor_button.setText(self.tr("Reset Sensorgram View"))
        self.reset_shift_button.setText(self.tr("Reset Peak Shift View"))
        self.reset_noise_button.setText(self.tr("Reset Noise View"))

        self.summary_plot.setTitle(self.tr("Accumulated Results Summary"), color="#90A4AE", size="12pt")
        self.summary_plot.setLabel("bottom", self.tr("Wavelength (nm)"))
        self.summary_plot.setLabel("left", self.tr("Absorbance"))

        self.sensorgram_plot.setTitle(self.tr("Kinetics Curve (Sensorgram)"), color="#90A4AE", size="12pt")
        self.sensorgram_plot.setLabel("bottom", self.tr("Time (s)"))
        self.sensorgram_plot.setLabel("left", self.tr("Peak Wavelength (nm)"))

        self.peak_shift_plot.setTitle(self.tr("Peak Wavelength Shift"), color="#90A4AE", size="12pt")
        self.peak_shift_plot.setLabel("bottom", self.tr("Time (s)"))
        self.peak_shift_plot.setLabel("left", self.tr("Shift (nm)"))

        self.noise_trend_plot.setTitle(self.tr("Real-time Average Noise Trend"), color="#90A4AE", size="12pt")
        self.noise_trend_plot.setLabel("bottom", self.tr("Time (s)"))
        self.noise_trend_plot.setLabel("left", self.tr("Average Noise (σ)"))

        self.summary_title_label.setText(self.tr("Accumulated Results Summary"))
        self.sensor_title_label.setText(self.tr("Kinetics Curve (Sensorgram)"))
        self.peak_shift_title_label.setText(self.tr("Peak Wavelength Shift"))
        self.noise_title_label.setText(self.tr("Real-time Average Noise Trend"))

        self.summary_popout_button.setToolTip(self.tr("Open in New Window"))
        self.sensor_popout_button.setToolTip(self.tr("Open in New Window"))
        self.peak_shift_popout_button.setToolTip(self.tr("Open in New Window"))
        self.noise_popout_button.setToolTip(self.tr("Open in New Window"))

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)
