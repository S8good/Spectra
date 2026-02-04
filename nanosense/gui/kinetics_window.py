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

        # 性能优化
        # 性能优化
        from ..utils.plot_utils import optimize_plot_performance, InteractivePlotEnhancer
        
        self.plot_widget = pg.PlotWidget()
        optimize_plot_performance(self.plot_widget)  # 启用降采样
        InteractivePlotEnhancer(self.plot_widget)
        self.plot_widget.addLegend()
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
        # 光谱对比数据存储
        self.baseline_spectrum_x = None
        self.baseline_spectrum_y = None
        self.realtime_spectrum_x = None
        self.realtime_spectrum_y = None
        self._popout_windows = []
        self.baseline_peak_wavelength = None
        self.peak_shift_time_data = []
        self.peak_shift_values = []
        self.noise_time_data = []
        self.noise_values = []
        self._shift_user_interacted = False
        self._comparison_user_interacted = False

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
        self.reset_sensor_button = QPushButton(self.tr("Reset Sensorgram View"))
        self.reset_shift_button = QPushButton(self.tr("Reset Peak Shift View"))
        self.reset_comparison_button = QPushButton(self.tr("Reset Comparison View"))

        button_grid = QGridLayout()
        button_grid.setSpacing(10)
        button_grid.addWidget(self.clear_kinetics_button, 0, 0, 1, 2)
        button_grid.addWidget(self.correct_drift_button, 1, 0)
        button_grid.addWidget(self.analyze_kinetics_button, 1, 1)
        button_grid.addWidget(self.reset_sensor_button, 2, 0)
        button_grid.addWidget(self.reset_shift_button, 2, 1)
        button_grid.addWidget(self.reset_comparison_button, 3, 0, 1, 2)
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

        # 动力学曲线（传感图）- 左上角
        # 性能优化
        from ..utils.plot_utils import optimize_plot_performance, InteractivePlotEnhancer
        
        self.sensorgram_plot = pg.PlotWidget()
        optimize_plot_performance(self.sensorgram_plot)  # 启用降采样
        InteractivePlotEnhancer(self.sensorgram_plot)
        self.sensorgram_plot.addLegend()
        self.sensorgram_curve = self.sensorgram_plot.plot(
            pen=pg.mkPen('#E91E63', width=2),
            symbol='o',
            symbolSize=6,
            symbolBrush='#F06292',
            name='Kinetics'
        )
        (self.sensor_container,
         self.sensor_title_label,
         self.sensor_popout_button) = self._create_plot_container(
            self.sensorgram_plot,
            "Kinetics Curve (Sensorgram)",
            self._open_sensorgram_popout
        )

        # 峰位移图 - 右上角
        self.peak_shift_plot = pg.PlotWidget()
        optimize_plot_performance(self.peak_shift_plot)  # 启用降采样
        InteractivePlotEnhancer(self.peak_shift_plot)
        self.peak_shift_plot.addLegend()
        self.peak_shift_plot.getViewBox().sigStateChanged.connect(self._on_shift_view_interacted)
        self.peak_shift_curve = self.peak_shift_plot.plot(
            pen=pg.mkPen('#FFB74D', width=2),
            symbol='o',
            symbolBrush='#FFD54F',
            symbolSize=6,
            name='Peak Shift'
        )
        (self.peak_shift_container,
         self.peak_shift_title_label,
         self.peak_shift_popout_button) = self._create_plot_container(
            self.peak_shift_plot,
            "Peak Wavelength Shift",
            self._open_peak_shift_popout
        )

        # 光谱对比图 - 底部全宽
        self.comparison_plot = pg.PlotWidget()
        optimize_plot_performance(self.comparison_plot)  # 启用降采样
        InteractivePlotEnhancer(self.comparison_plot)
        self.comparison_plot.addLegend()
        self.comparison_plot.getViewBox().sigStateChanged.connect(self._on_comparison_view_interacted)
        # 基线光谱曲线（蓝色，静态）
        self.baseline_curve = self.comparison_plot.plot(
            pen=pg.mkPen('#1E88E5', width=2),
            name='Baseline'
        )
        # 实时光谱曲线（红色，动态）
        self.realtime_curve = self.comparison_plot.plot(
            pen=pg.mkPen('#E53935', width=2),
            name='Real-time'
        )
        # 峰位标记（用于显示 Δλ）
        self.baseline_peak_marker = pg.ScatterPlotItem(
            size=12, symbol='o', pen=pg.mkPen('#1E88E5', width=2), brush=pg.mkBrush(255, 255, 255, 100)
        )
        self.realtime_peak_marker = pg.ScatterPlotItem(
            size=12, symbol='o', pen=pg.mkPen('#E53935', width=2), brush=pg.mkBrush(255, 255, 255, 100)
        )
        self.comparison_plot.addItem(self.baseline_peak_marker)
        self.comparison_plot.addItem(self.realtime_peak_marker)
        
        (self.comparison_container,
         self.comparison_title_label,
         self.comparison_popout_button) = self._create_plot_container(
            self.comparison_plot,
            "Spectrum Comparison (Baseline vs Real-time)",
            self._open_comparison_popout
        )

        # 布局：上方 2x1，下方全宽
        plots_layout.addWidget(self.sensor_container, 0, 0)
        plots_layout.addWidget(self.peak_shift_container, 0, 1)
        plots_layout.addWidget(self.comparison_container, 1, 0, 1, 2)  # 跨两列
        plots_layout.setRowStretch(0, 1)
        plots_layout.setRowStretch(1, 1)
        plots_layout.setColumnStretch(0, 1)
        plots_layout.setColumnStretch(1, 1)

        main_layout.addWidget(control_panel)
        main_layout.addWidget(plots_widget, stretch=1)

        self.kinetics_box.set_expanded(True)
        self._style_plot(self.sensorgram_plot)
        self._style_plot(self.peak_shift_plot)
        self._style_plot(self.comparison_plot)

    def _connect_signals(self):
        self.apply_baseline_button.clicked.connect(self._apply_baseline_value)
        self.clear_baseline_button.clicked.connect(self._clear_baseline_value)
        self.clear_kinetics_button.clicked.connect(self._clear_kinetics_data)
        self.correct_drift_button.clicked.connect(self._open_drift_correction_dialog)
        self.analyze_kinetics_button.clicked.connect(self._open_kinetics_analysis_dialog)
        self.reset_sensor_button.clicked.connect(self._reset_sensorgram_view)
        self.reset_shift_button.clicked.connect(self._reset_peak_shift_view)
        self.reset_comparison_button.clicked.connect(self._reset_comparison_view)

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
        # 根据主题设置不同的样式
        try:
            from ..utils.config_manager import load_settings
            settings = load_settings()
            theme = settings.get('theme', 'dark')
            
            if theme == 'light':
                # 浅色主题样式
                self.setStyleSheet("""
#KineticsWindowRoot {
    background-color: #F0F0F0;
    color: #000000;
    font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
    font-size: 13px;
}
#kineticsCentralWidget {
    background-color: #F0F0F0;
}
#kineticsControlPanel {
    background-color: #FFFFFF;
    border: 1px solid #CCCCCC;
    border-radius: 12px;
    color: #000000;
}
#kineticsControlPanel QWidget {
    background-color: transparent;
    color: #000000;
}
#kineticsControlPanel QLabel {
    color: #000000;
}
#kineticsPlotsPanel {
    background-color: #FFFFFF;
    border: 1px solid #CCCCCC;
    border-radius: 12px;
}
#plotCard {
    background-color: #FAFAFA;
    border: 1px solid #DDDDDD;
    border-radius: 12px;
}
#plotHeader {
    border-bottom: 1px solid #DDDDDD;
    background-color: rgba(0, 0, 0, 0.04);
}
#plotTitleLabel {
    color: #000000;
    font-size: 12pt;
    font-weight: 600;
}
#plotPopoutButton {
    background-color: transparent;
    border: 1px solid #CCCCCC;
    border-radius: 6px;
    padding: 4px;
}
#plotPopoutButton:hover {
    background-color: #1E90FF;
    border-color: #1E90FF;
}
QLabel#baselineStatusLabel {
    color: #666666;
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
    background-color: #1E90FF;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #187BCD;
}
QPushButton:pressed {
    background-color: #1565C0;
}
QPushButton:disabled {
    background-color: #CCCCCC;
    color: #666666;
}
QDoubleSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #CCCCCC;
    border-radius: 6px;
    padding: 6px;
    color: #000000;
}
QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {
    background-color: #EEEEEE;
    border: none;
    width: 16px;
}
#kineticsControlPanel QPushButton {
    background-color: #1E90FF;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    color: #FFFFFF;
    font-weight: 600;
}
#kineticsControlPanel QPushButton:hover {
    background-color: #187BCD;
}
#kineticsControlPanel QPushButton:pressed {
    background-color: #1565C0;
}
#kineticsControlPanel QPushButton:disabled {
    background-color: #CCCCCC;
    color: #666666;
}
CollapsibleBox > QToolButton {
    background-color: #FFFFFF;
    border: 1px solid #CCCCCC;
    border-radius: 6px;
    padding: 10px 12px;
    color: #000000;
    font-weight: 600;
    text-align: left;
}
CollapsibleBox > QToolButton:hover {
    background-color: #EEEEEE;
}
                """)
            else:
                # 深色主题样式
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
        except Exception:
            # 如果无法加载设置，使用默认的深色主题样式
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
    def _reset_sensorgram_view(self):
        self.sensorgram_plot.enableAutoRange(x=True, y=True)

    def _reset_peak_shift_view(self):
        self._shift_user_interacted = False
        self.peak_shift_plot.enableAutoRange(x=True, y=True)

    def _reset_comparison_view(self):
        self._comparison_user_interacted = False
        self.comparison_plot.enableAutoRange(x=True, y=True)

    def _on_shift_view_interacted(self):
        self._shift_user_interacted = True

    def _on_comparison_view_interacted(self):
        self._comparison_user_interacted = True

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

    def _open_comparison_popout(self):
        """打开光谱对比图的独立窗口"""
        if self.baseline_spectrum_x is None and self.realtime_spectrum_x is None:
            return
        
        window = SinglePlotWindow(self.tr("Spectrum Comparison (Baseline vs Real-time)"), parent=self)
        window.closed.connect(self._on_popout_closed)
        
        # 如果有基线光谱，显示它
        if self.baseline_spectrum_x is not None and self.baseline_spectrum_y is not None:
            window.plot_widget.plot(
                self.baseline_spectrum_x, 
                self.baseline_spectrum_y, 
                pen=pg.mkPen('#1E88E5', width=2),
                name='Baseline'
            )
        
        # 如果有实时光谱，显示它
        if self.realtime_spectrum_x is not None and self.realtime_spectrum_y is not None:
            window.plot_widget.plot(
                self.realtime_spectrum_x, 
                self.realtime_spectrum_y, 
                pen=pg.mkPen('#E53935', width=2),
                name='Real-time'
            )
        
        window.show()
        self._popout_windows.append({"window": window, "type": "comparison"})

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
        """清空所有动力学监测数据"""
        self.kinetics_time_data.clear()
        self.kinetics_wavelength_data.clear()
        self.peak_shift_time_data.clear()
        self.peak_shift_values.clear()
        
        # 清空光谱对比数据
        self.baseline_spectrum_x = None
        self.baseline_spectrum_y = None
        self.realtime_spectrum_x = None
        self.realtime_spectrum_y = None
        self.baseline_peak_wavelength = None  # 清除基线峰值

        self.sensorgram_curve.clear()
        self.peak_shift_curve.clear()
        self.baseline_curve.clear()
        self.realtime_curve.clear()
        self.baseline_peak_marker.clear()
        self.realtime_peak_marker.clear()

        self._reset_sensorgram_view()
        self._reset_peak_shift_view()
        self._reset_comparison_view()

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
        """更新动力学监测数据
        
        首次调用时捕获基线光谱，后续更新实时光谱
        """
        result_x = data_package.get("result_x")
        result_y = data_package.get("result_y")
        elapsed_time = data_package.get("elapsed_time")
        peak_wl = data_package.get("peak_wl")
        
        # DEBUG: 检查接收的数据范围
        if result_y is not None:
            print(f"DEBUG: 接收数据 Y值范围: min={np.min(result_y):.4f}, max={np.max(result_y):.4f}, len={len(result_y)}")

        # 捕获基线光谱（仅在开始时，第一次数据到达时）
        if self.baseline_spectrum_x is None and result_x is not None and result_y is not None:
            self.baseline_spectrum_x = np.array(result_x, copy=True)
            self.baseline_spectrum_y = np.array(result_y, copy=True)
            self.baseline_curve.setData(self.baseline_spectrum_x, self.baseline_spectrum_y)
            
            # 设置基线峰值波长，用于计算峰位移
            if peak_wl is not None:
                self.baseline_peak_wavelength = float(peak_wl)
                # 同步到spinbox和状态标签
                block = self.baseline_spinbox.blockSignals(True)
                self.baseline_spinbox.setValue(self.baseline_peak_wavelength)
                self.baseline_spinbox.blockSignals(block)
                self._update_baseline_status()
                print(f"基线光谱已捕获，波长范围: {self.baseline_spectrum_x[0]:.1f}-{self.baseline_spectrum_x[-1]:.1f} nm，基线峰值: {self.baseline_peak_wavelength:.2f} nm")
            else:
                print(f"基线光谱已捕获，波长范围: {self.baseline_spectrum_x[0]:.1f}-{self.baseline_spectrum_x[-1]:.1f} nm")
            
            # DEBUG: 检查主窗口属性
            print(f"DEBUG: main_window存在: {self.main_window is not None}")
            
            # 获取measurement_widget (可能是main_window本身或其子组件)
            measurement_widget = None
            if hasattr(self.main_window, 'analysis_start_spinbox'):
                measurement_widget = self.main_window
            elif hasattr(self.main_window, 'measurement_page'):
                measurement_widget = self.main_window.measurement_page
            
            print(f"DEBUG: measurement_widget存在: {measurement_widget is not None}")
            
            # 初始设置X轴范围为分析范围
            if measurement_widget and hasattr(measurement_widget, 'analysis_start_spinbox') and hasattr(measurement_widget, 'analysis_end_spinbox'):
                analysis_start = measurement_widget.analysis_start_spinbox.value()
                analysis_end = measurement_widget.analysis_end_spinbox.value()
                print(f"DEBUG: 分析范围值 = {analysis_start} - {analysis_end}")
                self.comparison_plot.setXRange(analysis_start, analysis_end, padding=0.02)
                print(f"光谱对比图X轴范围设置为: {analysis_start:.1f}-{analysis_end:.1f} nm")
            else:
                print("DEBUG: 无法获取分析范围spinbox")
        
        # 更新实时光谱
        if result_x is not None and result_y is not None:
            self.realtime_spectrum_x = np.array(result_x, copy=True)
            self.realtime_spectrum_y = np.array(result_y, copy=True)
            self.realtime_curve.setData(self.realtime_spectrum_x, self.realtime_spectrum_y)

        # 更新动力学曲线（时间 vs 峰位）
        if elapsed_time is not None and peak_wl is not None:
            elapsed_time = float(elapsed_time)
            peak_wl = float(peak_wl)
            self.kinetics_time_data.append(elapsed_time)
            self.kinetics_wavelength_data.append(peak_wl)
            self.sensorgram_curve.setData(self.kinetics_time_data, self.kinetics_wavelength_data)
            
            # DEBUG: 检查峰位移计算
            print(f"更新峰位移: time={elapsed_time:.2f}s, peak={peak_wl:.2f}nm, baseline={self.baseline_peak_wavelength}")
            self._update_peak_shift_series(elapsed_time, peak_wl)
            
            # 更新峰位标记以显示 Δλ
            if self.baseline_spectrum_x is not None and self.baseline_spectrum_y is not None:
                # 找到基线光谱的峰位
                baseline_peak_idx = np.argmax(self.baseline_spectrum_y)
                baseline_peak_wl = self.baseline_spectrum_x[baseline_peak_idx]
                baseline_peak_val = self.baseline_spectrum_y[baseline_peak_idx]
                self.baseline_peak_marker.setData([baseline_peak_wl], [baseline_peak_val])
            
            if self.realtime_spectrum_x is not None and self.realtime_spectrum_y is not None:
                # 找到实时光谱的峰位
                realtime_peak_idx = np.argmax(self.realtime_spectrum_y)
                realtime_peak_wl = self.realtime_spectrum_x[realtime_peak_idx]
                realtime_peak_val = self.realtime_spectrum_y[realtime_peak_idx]
                self.realtime_peak_marker.setData([realtime_peak_wl], [realtime_peak_val])

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


    def _refresh_popouts(self):
        """刷新所有弹出窗口的数据"""
        if not self._popout_windows:
            return

        sensor_x = np.asarray(self.kinetics_time_data)
        sensor_y = np.asarray(self.kinetics_wavelength_data)

        for entry in list(self._popout_windows):
            window = entry.get("window")
            kind = entry.get("type")
            if window is None:
                continue

            if kind == "sensor" and sensor_x.size and sensor_y.size:
                pen = entry.get("pen")
                window.update_data(sensor_x, sensor_y, pen)
            elif kind == "peak_shift" and self.peak_shift_time_data:
                pen = entry.get("pen")
                window.update_data(
                    np.asarray(self.peak_shift_time_data),
                    np.asarray(self.peak_shift_values),
                    pen
                )
            elif kind == "comparison":
                # 对比图窗口需要重新绘制两条曲线
                window.plot_widget.clear()
                if self.baseline_spectrum_x is not None and self.baseline_spectrum_y is not None:
                    window.plot_widget.plot(
                        self.baseline_spectrum_x,
                        self.baseline_spectrum_y,
                        pen=pg.mkPen('#1E88E5', width=2),
                        name='Baseline'
                    )
                if self.realtime_spectrum_x is not None and self.realtime_spectrum_y is not None:
                    window.plot_widget.plot(
                        self.realtime_spectrum_x,
                        self.realtime_spectrum_y,
                        pen=pg.mkPen('#E53935', width=2),
                        name='Real-time'
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
        self.reset_sensor_button.setText(self.tr("Reset Sensorgram View"))
        self.reset_shift_button.setText(self.tr("Reset Peak Shift View"))
        self.reset_comparison_button.setText(self.tr("Reset Comparison View"))

        self.sensorgram_plot.setTitle(self.tr("Kinetics Curve (Sensorgram)"), color="#90A4AE", size="12pt")
        self.sensorgram_plot.setLabel("bottom", self.tr("Time (s)"))
        self.sensorgram_plot.setLabel("left", self.tr("Peak Wavelength (nm)"))

        self.peak_shift_plot.setTitle(self.tr("Peak Wavelength Shift"), color="#90A4AE", size="12pt")
        self.peak_shift_plot.setLabel("bottom", self.tr("Time (s)"))
        self.peak_shift_plot.setLabel("left", self.tr("Shift (nm)"))

        self.comparison_plot.setTitle(self.tr("Spectrum Comparison (Baseline vs Real-time)"), color="#90A4AE", size="12pt")
        self.comparison_plot.setLabel("bottom", self.tr("Wavelength (nm)"))
        self.comparison_plot.setLabel("left", self.tr("Absorbance"))

        self.sensor_title_label.setText(self.tr("Kinetics Curve (Sensorgram)"))
        self.peak_shift_title_label.setText(self.tr("Peak Wavelength Shift"))
        self.comparison_title_label.setText(self.tr("Spectrum Comparison (Baseline vs Real-time)"))

        self.sensor_popout_button.setToolTip(self.tr("Open in New Window"))
        self.peak_shift_popout_button.setToolTip(self.tr("Open in New Window"))
        self.comparison_popout_button.setToolTip(self.tr("Open in New Window"))

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)
