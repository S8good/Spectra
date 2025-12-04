# nanosense/core/batch_acquisition.py
import json
import queue
import time
import os
import numpy as np
import threading
import pandas as pd
import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QMessageBox,
    QGridLayout,
    QWidget,
    QToolButton,
    QSizePolicy,
    QStyle,
    QFileDialog,
    QGroupBox,
    QToolTip,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QThread, Qt, QEvent, QSize
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from .controller import FX2000Controller
from ..utils.file_io import save_batch_spectrum_data, load_spectrum_from_path
from ..gui.single_plot_window import SinglePlotWindow

PROGRESS_BAR_STYLE = """
QProgressBar {
    border: 1px solid rgba(224, 224, 224, 0.6);
    border-radius: 5px;
    text-align: center;
    background-color: rgba(0, 0, 0, 0.2);
    color: white;
    min-height: 18px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                      stop:0 #4169E1, stop:1 #483D8B);
    border-radius: 4px;
}
"""

MINI_PROGRESS_STYLE = """
QProgressBar {
    border: 1px solid rgba(224, 224, 224, 0.4);
    border-radius: 3px;
    background-color: rgba(255, 255, 255, 0.08);
    min-height: 4px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                      stop:0 #8EC5FC, stop:1 #3F5EFB);
    border-radius: 2px;
}
"""


def _calculate_absorbance(signal, background, reference):
    """Compute absorbance from signal, background, and reference spectra."""
    if signal is None or background is None or reference is None:
        return None
    signal = np.array(signal, dtype=float)
    background = np.array(background, dtype=float)
    reference = np.array(reference, dtype=float)
    valid_mask = (
        np.isfinite(signal)
        & np.isfinite(background)
        & np.isfinite(reference)
    )
    if not np.any(valid_mask):
        return None
    absorbance = np.full(signal.shape, np.nan, dtype=float)
    sig_eff = signal[valid_mask] - background[valid_mask]
    ref_eff = reference[valid_mask] - background[valid_mask]
    safe_denominator = np.copy(ref_eff)
    safe_denominator[safe_denominator == 0] = 1e-9
    transmittance = sig_eff / safe_denominator
    transmittance[transmittance <= 0] = 1e-9
    absorbance[valid_mask] = -1 * np.log10(transmittance)
    return absorbance


class MultiCurvePlotWindow(pg.QtWidgets.QMainWindow):
    closed = pyqtSignal(object)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setGeometry(300, 300, 800, 600)
        self.plot_widget = pg.PlotWidget()
        self.setCentralWidget(self.plot_widget)
        self.plot_widget.addLegend()

    def update_data(self, wavelengths, spectra_list):
        self.plot_widget.clear()
        if wavelengths is not None and spectra_list:
            for i, spectrum in enumerate(spectra_list):
                color = pg.intColor(i, hues=len(spectra_list), alpha=150)
                self.plot_widget.plot(
                    wavelengths, spectrum, pen=pg.mkPen(color), name=f"Result_{i+1}"
                )

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)



class BatchRunDialog(QDialog):
    """Dialog that presents batch acquisition controls and live preview plots."""

    background_collect_requested = pyqtSignal()
    background_import_requested = pyqtSignal(dict)
    reference_collect_requested = pyqtSignal()
    reference_import_requested = pyqtSignal(dict)
    signal_collect_requested = pyqtSignal()
    back_triggered = pyqtSignal()
    abort_mission = pyqtSignal()
    peak_method_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_manager = getattr(parent, "db_manager", None)
        self.worker = None
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(1300, 800)
        self.setModal(True)
        self.summary_curves = []
        self.is_summary_paused = False
        self.popout_windows = []
        self._allow_close = False
        self._current_phase: Optional[str] = None
        self._last_import_dir = ""
        self._reference_hint_shown = False
        self._dummy_strings_for_translator()
        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()

    def _dummy_strings_for_translator(self) -> None:
        self.tr("Please place [Background] for well {well_id}\n(Live preview active...)")
        self.tr("Collect Background")
        self.tr("Import Background")
        self.tr("Please place [Reference] for well {well_id}\n(Live preview active...)")
        self.tr("Collect Reference")
        self.tr("Import Reference")
        self.tr("Please move to well {well_id}, point {point_num}/{total_points}\n(Live preview active...)")
        self.tr("Collect this Point")
        self.tr("Calculating absorbance for {well_id}...")
        self.tr("Saving data for {well_id}...")
        self.tr("Batch acquisition complete!")
        self.tr("Done")

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        self.instruction_label = QLabel()
        font = self.instruction_label.font()
        font.setPointSize(14)
        self.instruction_label.setFont(font)
        self.instruction_label.setAlignment(Qt.AlignCenter)

        button_icon_size = QSize(22, 22)
        button_box_size = QSize(36, 36)
        icons_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "gui",
            "assets",
            "icons",
        )

        def _render_svg(icon_filename: str, color: QColor) -> QPixmap:
            icon_path = os.path.join(icons_dir, icon_filename)
            renderer = QSvgRenderer(icon_path)
            pixmap = QPixmap(button_icon_size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), color)
            painter.end()
            return pixmap

        def _make_tool_button(icon_filename: str) -> QToolButton:
            btn = QToolButton()
            btn.setAutoRaise(True)
            enabled_pixmap = _render_svg(icon_filename, QColor(255, 255, 255))
            disabled_pixmap = _render_svg(icon_filename, QColor(140, 140, 140, 180))
            icon = QIcon()
            icon.addPixmap(enabled_pixmap, QIcon.Normal, QIcon.Off)
            icon.addPixmap(enabled_pixmap, QIcon.Active, QIcon.Off)
            icon.addPixmap(disabled_pixmap, QIcon.Disabled, QIcon.Off)
            btn.setIcon(icon)
            btn.setIconSize(button_icon_size)
            btn.setFixedSize(button_box_size)
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            return btn

        self.tb_back = _make_tool_button("tool_prev.svg")
        self.tb_background_collect = _make_tool_button("tool_collect_background.svg")
        self.tb_background_import = _make_tool_button("tool_import_background.svg")
        self.tb_reference_collect = _make_tool_button("tool_collect_reference.svg")
        self.tb_reference_import = _make_tool_button("tool_import_reference.svg")
        self.tb_signal_collect = _make_tool_button("tool_collect_point.svg")
        self.tb_abort = _make_tool_button("tool_abort.svg")

        topbar = QWidget()
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(8, 4, 8, 4)
        topbar_layout.setSpacing(6)
        topbar_layout.addWidget(self.tb_back)
        topbar_layout.addSpacing(4)
        topbar_layout.addWidget(self.tb_background_collect)
        topbar_layout.addWidget(self.tb_background_import)
        topbar_layout.addSpacing(4)
        topbar_layout.addWidget(self.tb_reference_collect)
        topbar_layout.addWidget(self.tb_reference_import)
        topbar_layout.addSpacing(4)
        topbar_layout.addWidget(self.tb_signal_collect)
        topbar_layout.addStretch(1)
        topbar_layout.addWidget(self.tb_abort)

        main_layout.addWidget(topbar)
        main_layout.addWidget(self.instruction_label)

        # Reuse tool buttons for existing control logic.
        self.back_button = self.tb_back
        self.background_collect_button = self.tb_background_collect
        self.background_import_button = self.tb_background_import
        self.reference_collect_button = self.tb_reference_collect
        self.reference_import_button = self.tb_reference_import
        self.signal_collect_button = self.tb_signal_collect
        self.abort_button = self.tb_abort


        plots_container = QWidget()
        plots_layout = QVBoxLayout(plots_container)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        plots_layout.setSpacing(12)

        self.plot_grid = QGridLayout()
        self.plot_grid.setSpacing(12)
        # 设置列宽比例：1:1:1:1
        self.plot_grid.setColumnStretch(0, 1)  # 信号谱/实时结果谱
        self.plot_grid.setColumnStretch(1, 1)  # 背景谱/累计结果谱
        self.plot_grid.setColumnStretch(2, 1)  # 参考谱/累计结果谱
        self.plot_grid.setColumnStretch(3, 1)  # 峰值表
        # 设置行高比例
        self.plot_grid.setRowStretch(0, 1)  # 第一行
        self.plot_grid.setRowStretch(1, 1)  # 第二行

        def create_plot_container(plot_widget: pg.PlotWidget, title_key: str, popout_handler) -> QWidget:
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
            icon_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "gui",
                "assets",
                "icons",
                "zoom.png",
            )
            popout_button.setIcon(pg.QtGui.QIcon(icon_path))
            popout_button.setIconSize(QSize(18, 18))
            popout_button.setFixedSize(26, 26)
            popout_button.setAutoRaise(True)
            popout_button.setStyleSheet("border: none; padding: 0;")
            popout_button.setToolTip(self.tr("Open in New Window"))
            popout_button.clicked.connect(popout_handler)
            header_layout.addWidget(title_label)
            header_layout.addStretch()
            header_layout.addWidget(popout_button)
            layout.addWidget(header_widget)
            layout.addWidget(plot_widget)
            plot_widget.setTitle("")
            plot_widget.showGrid(x=True, y=True, alpha=0.3)
            return container

        self.signal_plot = pg.PlotWidget()
        self.signal_curve = self.signal_plot.plot(pen="c")
        self.background_plot = pg.PlotWidget()
        self.background_curve = self.background_plot.plot(pen="w")
        self.reference_plot = pg.PlotWidget()
        self.reference_curve = self.reference_plot.plot(pen="m")
        self.result_plot = pg.PlotWidget()
        self.result_curve = self.result_plot.plot(pen="y")
        self.summary_plot = pg.PlotWidget()

        self.signal_container = create_plot_container(
            self.signal_plot, "Live Signal", lambda: self._open_popout_window("signal")
        )
        self.background_container = create_plot_container(
            self.background_plot,
            "Current Background",
            lambda: self._open_popout_window("background"),
        )
        self.reference_container = create_plot_container(
            self.reference_plot,
            "Current Reference",
            lambda: self._open_popout_window("reference"),
        )
        self.result_container = create_plot_container(
            self.result_plot,
            "Live Result (Absorbance)",
            lambda: self._open_popout_window("result"),
        )
        self.summary_container = create_plot_container(
            self.summary_plot,
            "Accumulated Results Summary",
            lambda: self._open_popout_window("summary"),
        )

        # 添加峰值表
        self.peak_table_container = self._create_peak_table_container()
        
        # 第一行：信号谱、背景谱、参考谱（各占1/3宽度）
        self.plot_grid.addWidget(self.signal_container, 0, 0)
        self.plot_grid.addWidget(self.background_container, 0, 1)
        self.plot_grid.addWidget(self.reference_container, 0, 2)
        
        # 第二行：实时结果谱(1/3)、累计结果谱(2/3)
        self.plot_grid.addWidget(self.result_container, 1, 0)
        self.plot_grid.addWidget(self.summary_container, 1, 1, 1, 2)  # 累计结果谱占据两列
        
        # 右侧：峰值表(垂直占据两行)
        self.plot_grid.addWidget(self.peak_table_container, 0, 3, 2, 1)

        plots_layout.addLayout(self.plot_grid, 1)
        main_layout.addWidget(plots_container)

        # Peak analysis controls
        peak_analysis_layout = QHBoxLayout()
        peak_analysis_layout.addWidget(QLabel(self.tr("Peak Finding Algorithm:")))
        self.peak_method_combo = QComboBox()
        from nanosense.algorithms.peak_analysis import PEAK_METHOD_LABELS
        for method_key, method_label in PEAK_METHOD_LABELS.items():
            self.peak_method_combo.addItem(self.tr(method_label), method_key)
        # 默认选择最高峰值法
        self.peak_method_combo.setCurrentText(self.tr("Highest Point"))
        peak_analysis_layout.addWidget(self.peak_method_combo)
        peak_analysis_layout.addStretch()
        main_layout.addLayout(peak_analysis_layout)
        
        summary_controls_layout = QHBoxLayout()
        self.toggle_summary_button = QPushButton()
        self.toggle_summary_button.setCheckable(True)
        self.clear_summary_button = QPushButton()
        self.toggle_reference_button = QPushButton()
        self.toggle_reference_button.setCheckable(True)
        summary_controls_layout.addStretch()
        summary_controls_layout.addWidget(self.toggle_summary_button)
        summary_controls_layout.addWidget(self.clear_summary_button)
        summary_controls_layout.addWidget(self.toggle_reference_button)
        main_layout.addLayout(summary_controls_layout)

        self.progress_panel = QWidget()
        progress_layout = QVBoxLayout(self.progress_panel)
        progress_layout.setContentsMargins(0, 4, 0, 0)
        progress_layout.setSpacing(4)
        self.progress_info_label = QLabel()
        self.progress_info_label.setStyleSheet("color: #90A4AE; font-size: 11px;")
        self.total_progress_bar = QProgressBar()
        self.total_progress_bar.setStyleSheet(PROGRESS_BAR_STYLE)
        self.point_progress_bar = QProgressBar()
        self.point_progress_bar.setStyleSheet(MINI_PROGRESS_STYLE)
        self.point_progress_bar.setTextVisible(False)
        self.point_progress_bar.setFixedHeight(6)
        self._total_progress_value = 0
        self._point_progress_value = 0
        self.progress_info_label.setText(self._progress_text())
        progress_layout.addWidget(self.progress_info_label)
        progress_layout.addWidget(self.total_progress_bar)
        progress_layout.addWidget(self.point_progress_bar)
        main_layout.addWidget(self.progress_panel)

        for btn in (
            self.background_collect_button,
            self.background_import_button,
            self.reference_collect_button,
            self.reference_import_button,
            self.signal_collect_button,
        ):
            btn.setEnabled(False)
        self.back_button.setEnabled(False)

    def _connect_signals(self) -> None:
        self.background_collect_button.clicked.connect(self.background_collect_requested.emit)
        self.background_import_button.clicked.connect(lambda: self._prompt_import("background"))
        self.reference_collect_button.clicked.connect(self.reference_collect_requested.emit)
        self.reference_import_button.clicked.connect(lambda: self._prompt_import("reference"))
        self.signal_collect_button.clicked.connect(self.signal_collect_requested.emit)
        self.back_button.clicked.connect(self.back_triggered.emit)
        self.abort_button.clicked.connect(self._confirm_abort)
        self.toggle_summary_button.toggled.connect(self._toggle_summary_pause)
        self.clear_summary_button.clicked.connect(self._clear_summary_plot)
        self.toggle_reference_button.toggled.connect(self._toggle_reference_sections)
        self.peak_method_combo.currentIndexChanged.connect(lambda: self.peak_method_changed.emit(self.get_selected_peak_method()))

    def _prompt_import(self, spectrum_type: str) -> None:
        start_dir = self._last_import_dir or os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Spectrum File"),
            start_dir,
            self.tr(
                "All Supported Files (*.xlsx *.xls *.csv *.txt);;Excel Files (*.xlsx *.xls);;CSV/Text Files (*.csv *.txt)"
            ),
        )
        if not file_path:
            return
        wavelengths, intensities = load_spectrum_from_path(file_path)
        if wavelengths is None or intensities is None:
            QMessageBox.critical(
                self,
                self.tr("Import Failed"),
                self.tr("Could not load spectrum data from:\n{0}").format(file_path),
            )
            return
        if len(wavelengths) != len(intensities):
            QMessageBox.critical(
                self,
                self.tr("Import Failed"),
                self.tr("Loaded data has mismatched wavelength and intensity lengths."),
            )
            return
        self._last_import_dir = os.path.dirname(file_path)
        payload = {
            "type": spectrum_type,
            "file_path": file_path,
            "wavelengths": wavelengths,
            "spectrum": intensities,
        }
        if spectrum_type == "background":
            self.background_import_requested.emit(payload)
        else:
            self.reference_import_requested.emit(payload)

    def _apply_phase_controls(
        self,
        phase: Optional[str],
        collect_enabled: bool,
        import_enabled: Optional[bool],
    ) -> None:
        mapping = {
            "background": (self.background_collect_button, self.background_import_button),
            "reference": (self.reference_collect_button, self.reference_import_button),
            "signal": (self.signal_collect_button, None),
        }
        for key, (collect_btn, import_btn) in mapping.items():
            active = key == phase
            collect_btn.setChecked(active and collect_btn.isCheckable())
            collect_btn.setEnabled(collect_enabled if active else False)
            if import_btn is not None:
                allow_import = collect_enabled if import_enabled is None else import_enabled
                import_btn.setEnabled(allow_import if active else False)
        self._current_phase = phase

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _create_peak_table_container(self) -> QWidget:
        """创建峰值表格容器"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 创建表头
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 2, 5, 2)
        title_label = QLabel(self.tr("Peak Results"))
        title_label.setStyleSheet("color: #90A4AE; font-size: 12pt;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        layout.addWidget(header_widget)
        
        # 创建表格
        self.peak_table = QTableWidget()
        self.peak_table.setColumnCount(3)
        self.peak_table.setHorizontalHeaderLabels([
            self.tr("Well-Point"),
            self.tr("Peak Wavelength (nm)"),
            self.tr("Peak Intensity (Abs)")
        ])
        
        # 设置表格样式
        self.peak_table.setStyleSheet("""
            QTableWidget {
                background-color: rgba(33, 33, 33, 0.8);
                border: none;
                color: white;
            }
            QTableWidget::item {
                border-bottom: 1px solid rgba(224, 224, 224, 0.1);
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: rgba(65, 105, 225, 0.5);
            }
            QHeaderView::section {
                background-color: rgba(0, 0, 0, 0.3);
                border: none;
                border-bottom: 1px solid rgba(224, 224, 224, 0.2);
                color: white;
                padding: 5px;
            }
        """)
        
        # 设置表头自适应
        self.peak_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.peak_table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.peak_table)
        
        return container
    
    def update_peak_table(self, well_id: str, point_num: int, peak_wavelength: float, peak_intensity: float) -> None:
        """更新峰值表格"""
        # 查找是否已存在相同的孔位-点数据
        well_point_key = f"{well_id}-{point_num}"
        existing_row = -1
        
        for row in range(self.peak_table.rowCount()):
            item = self.peak_table.item(row, 0)
            if item and item.text() == well_point_key:
                existing_row = row
                break
        
        if existing_row >= 0:
            # 更新现有行
            row = existing_row
        else:
            # 插入新行
            row = self.peak_table.rowCount()
            self.peak_table.insertRow(row)
        
        # 设置单元格内容
        well_point_item = QTableWidgetItem(well_point_key)
        well_point_item.setTextAlignment(Qt.AlignCenter)
        peak_wl_item = QTableWidgetItem(f"{peak_wavelength:.2f}")
        peak_wl_item.setTextAlignment(Qt.AlignCenter)
        peak_int_item = QTableWidgetItem(f"{peak_intensity:.4f}")
        peak_int_item.setTextAlignment(Qt.AlignCenter)
        
        self.peak_table.setItem(row, 0, well_point_item)
        self.peak_table.setItem(row, 1, peak_wl_item)
        self.peak_table.setItem(row, 2, peak_int_item)
        
        # 自动滚动到最后一行
        self.peak_table.scrollToBottom()
    
    def remove_from_peak_table(self, well_id: str, point_num: int) -> None:
        """从峰值表格中删除指定孔位-点的数据"""
        well_point_key = f"{well_id}-{point_num}"
        
        # 查找并删除匹配的行
        for row in range(self.peak_table.rowCount()):
            item = self.peak_table.item(row, 0)
            if item and item.text() == well_point_key:
                self.peak_table.removeRow(row)
                break

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Batch Acquisition in Progress..."))
        self.instruction_label.setText(self.tr("Initializing..."))
        tooltip_map = {
            self.tb_back: "Previous Step",
            self.tb_background_collect: "Collect Background",
            self.tb_background_import: "Import Background",
            self.tb_reference_collect: "Collect Reference",
            self.tb_reference_import: "Import Reference",
            self.tb_signal_collect: "Collect this Point",
            self.tb_abort: "Abort Task",
        }
        for button, key in tooltip_map.items():
            button.setToolTip(self.tr(key))

        title_style = {"color": "#90A4AE", "size": "12pt"}
        self.signal_plot.setTitle(self.tr("Live Signal"), **title_style)
        self.background_plot.setTitle(self.tr("Current Background"), **title_style)
        self.reference_plot.setTitle(self.tr("Current Reference"), **title_style)
        self.result_plot.setTitle(self.tr("Live Result (Absorbance)"), **title_style)
        self.summary_plot.setTitle(self.tr("Accumulated Results Summary"), **title_style)

        self.toggle_summary_button.setText(self.tr("Pause Overlay"))
        self.clear_summary_button.setText(self.tr("Clear Summary Plot"))
        self._toggle_reference_sections(self.toggle_reference_button.isChecked())
        self.progress_info_label.setText(self._progress_text())

    def _open_popout_window(self, plot_type: str) -> None:
        for item in self.popout_windows:
            if item["type"] == plot_type:
                item["window"].activateWindow()
                return
        title_map = {
            "signal": self.tr("Live Signal"),
            "background": self.tr("Current Background"),
            "reference": self.tr("Current Reference"),
            "result": self.tr("Live Result (Absorbance)"),
            "summary": self.tr("Accumulated Results Summary"),
        }
        title = title_map.get(plot_type, "Plot")
        if plot_type == "summary":
            win = MultiCurvePlotWindow(title, self)
        else:
            win = SinglePlotWindow(title, parent=self)
        self.popout_windows.append({"type": plot_type, "window": win})
        win.closed.connect(self._on_popout_closed)
        win.show()

    def _on_popout_closed(self, window_instance: QWidget) -> None:
        self.popout_windows = [
            item for item in self.popout_windows if item["window"] is not window_instance
        ]

    def update_all_plots(self, data_package: Dict[str, Any]) -> None:
        full_wavelengths = data_package.get("full_wavelengths")
        result_wavelengths = data_package.get("result_wavelengths")
        if full_wavelengths is None:
            return
        live_signal = data_package.get("live_signal")
        background = data_package.get("background")
        reference = data_package.get("reference")
        all_results = data_package.get("all_results", [])

        live_signal_series = live_signal if live_signal is not None else []
        background_series = background if background is not None else []
        reference_series = reference if reference is not None else []

        self.signal_curve.setData(full_wavelengths, live_signal_series)
        self.background_curve.setData(full_wavelengths, background_series)
        self.reference_curve.setData(full_wavelengths, reference_series)

        current_result = None
        result_series: Any = []
        if result_wavelengths is not None:
            live_signal_np = np.array(live_signal) if live_signal is not None else None
            background_np = np.array(background) if background is not None else None
            reference_np = np.array(reference) if reference is not None else None
            mask = np.isin(full_wavelengths, result_wavelengths)
            signal_cropped = live_signal_np[mask] if live_signal_np is not None else None
            background_cropped = background_np[mask] if background_np is not None else None
            reference_cropped = reference_np[mask] if reference_np is not None else None
            current_result = _calculate_absorbance(
                signal_cropped, background_cropped, reference_cropped
            )
            result_series = current_result if current_result is not None else []
            self.result_curve.setData(result_wavelengths, result_series)
        else:
            self.result_curve.setData([], [])

        if not self.is_summary_paused and len(all_results) != len(self.summary_curves):
            self._redraw_summary_plot(result_wavelengths, all_results)

        for item in self.popout_windows:
            win = item["window"]
            window_type = item["type"]
            if window_type == "signal":
                win.update_data(full_wavelengths, live_signal_series, self.signal_curve.opts["pen"])
            elif window_type == "background":
                win.update_data(full_wavelengths, background_series, self.background_curve.opts["pen"])
            elif window_type == "reference":
                win.update_data(full_wavelengths, reference_series, self.reference_curve.opts["pen"])
            elif window_type == "result":
                win.update_data(result_wavelengths, result_series, self.result_curve.opts["pen"])
            elif window_type == "summary":
                win.update_data(result_wavelengths, all_results)

    def _redraw_summary_plot(self, wavelengths, all_results) -> None:
        self.summary_plot.clear()
        self.summary_curves.clear()
        if wavelengths is None:
            return
        for index, spectrum in enumerate(all_results or []):
            color = pg.intColor(index, hues=len(all_results), alpha=150)
            curve = self.summary_plot.plot(wavelengths, spectrum, pen=pg.mkPen(color))
            self.summary_curves.append(curve)

    def _toggle_summary_pause(self, paused: bool) -> None:
        self.is_summary_paused = paused
        self.toggle_summary_button.setText(
            self.tr("Resume Overlay") if paused else self.tr("Pause Overlay")
        )

    def _clear_summary_plot(self) -> None:
        self.summary_plot.clear()
        self.summary_curves.clear()
        self._redraw_summary_plot(None, [])

    def _toggle_reference_sections(self, hidden: bool) -> None:
        self.background_container.setVisible(not hidden)
        self.reference_container.setVisible(not hidden)
        self.plot_grid.removeWidget(self.summary_container)
        if hidden:
            # Span both rows and last two columns
            self.plot_grid.addWidget(self.summary_container, 0, 1, 2, 2)
        else:
            self.plot_grid.addWidget(self.summary_container, 1, 1, 1, 2)
        self._reference_hint_shown = False
        label = (
            self.tr("Show Reference/Background")
            if hidden
            else self.tr("Hide Reference/Background")
        )
        self.toggle_reference_button.setText(label)

    def get_selected_peak_method(self) -> str:
        """获取当前选择的寻峰算法"""
        return self.peak_method_combo.currentData()
    
    def _progress_text(self) -> str:
        return self.tr("Total progress: {total}% | Current well: {point}%").format(
            total=int(self._total_progress_value),
            point=int(self._point_progress_value),
        )

    def _show_reference_hint(self) -> None:
        if self._reference_hint_shown or not self.toggle_reference_button:
            return
        message = self.tr(
            "Reference/background plots are hidden. Click the button to show them."
        )
        btn = self.toggle_reference_button
        pos = btn.mapToGlobal(btn.rect().center())
        QToolTip.showText(pos, message, btn)
        self._reference_hint_shown = True

    def _confirm_abort(self) -> None:
        reply = QMessageBox.question(
            self,
            self.tr("Confirm"),
            self.tr("Are you sure you want to abort the current batch acquisition task?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.abort_mission.emit()
            self.reject()

    def closeEvent(self, event) -> None:
        reply = QMessageBox.question(
            self,
            self.tr("Confirm"),
            self.tr("Are you sure you want to abort the current batch acquisition task?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.abort_mission.emit()
            super().closeEvent(event)
        else:
            event.ignore()

    def update_state(self, status: Dict[str, Any]) -> None:
        instruction_key = status.get("instruction_key")
        if instruction_key:
            params = status.get("params", {})
            self.instruction_label.setText(self.tr(instruction_key).format(**params))
        previous_phase = self._current_phase
        if "total_progress" in status:
            value = int(status["total_progress"])
            self._total_progress_value = value
            self.total_progress_bar.setValue(value)
        if "point_progress" in status:
            value = int(status["point_progress"])
            self._point_progress_value = value
            self.point_progress_bar.setValue(value)
        self.progress_info_label.setText(self._progress_text())

        phase = status.get("phase", self._current_phase)
        collect_enabled = status.get("button_enabled", False)
        import_enabled = status.get("import_enabled")
        self._apply_phase_controls(phase, collect_enabled, import_enabled)

        if "back_button_enabled" in status:
            self.back_button.setEnabled(status["back_button_enabled"])
        if (
            phase == "signal"
            and previous_phase != "signal"
            and self.toggle_reference_button.isChecked()
        ):
            self._show_reference_hint()

# --------------------------------------------------------------------------------
class BatchAcquisitionWorker(QObject):
    """Thread-safe batch acquisition worker that processes commands from a queue."""

    finished = pyqtSignal()
    error = pyqtSignal(str)
    update_dialog = pyqtSignal(dict)
    live_preview_data = pyqtSignal(dict)
    peak_found = pyqtSignal(str, int, float, float)  # well_id, point_num, peak_wavelength, peak_intensity
    peak_removed = pyqtSignal(str, int)  # well_id, point_num - signal to remove peak from table

    def __init__(
        self,
        controller: FX2000Controller,
        layout_data: dict,
        output_folder: str,
        file_extension: str,
        points_per_well: int = 16,
        crop_start_wl=None,
        crop_end_wl=None,
        is_auto_enabled=False,
        intra_well_interval=2.0,
        inter_well_interval=10.0,
        db_manager=None,
        project_id=None,
        batch_run_id=None,
        batch_item_map=None,
        operator: str = "",
        instrument_info: Optional[Dict[str, Any]] = None,
        processing_info: Optional[Dict[str, Any]] = None,
        peak_method: str = "highest_point",
    ):
        super().__init__()
        self.controller = controller
        self.layout_data = layout_data
        self.output_folder = output_folder
        self.file_extension = file_extension
        self.points_per_well = points_per_well
        self.crop_start_wl = crop_start_wl
        self.crop_end_wl = crop_end_wl
        # Automation settings
        self.is_auto_enabled = is_auto_enabled
        self.intra_well_interval = intra_well_interval
        self.inter_well_interval = inter_well_interval
        self.peak_method = peak_method
        
        # Initialize worker state
        self._is_running = True
        self.run_status = "pending"
        self.command_queue = queue.Queue(maxsize=1)
        self.tasks = []
        self.task_index = 0
        self.collected_data = defaultdict(lambda: {"signals": {}, "absorbance": {}})
        self.db_manager = db_manager
        self.project_id = project_id
        self.batch_run_id = batch_run_id
        self.batch_item_map = batch_item_map or {}
        self.operator = operator or ""
        if self.db_manager and self.project_id is not None:
            self._initialize_batch_records()
        self.well_experiments: Dict[str, int] = {}
        self.spectrum_registry = defaultdict(lambda: defaultdict(list))
        self.capture_counts = defaultdict(int)
        self.completed_wells = set()
        
        # Initialize instrument and processing info
        base_instrument = dict(instrument_info) if instrument_info else {}
        config_meta = dict(base_instrument.get("config") or {})
        config_meta.setdefault("source", "batch_acquisition")
        config_meta.setdefault("points_per_well", points_per_well)
        config_meta.setdefault("crop_start_nm", crop_start_wl)
        config_meta.setdefault("crop_end_nm", crop_end_wl)
        config_meta.setdefault("auto_enabled", is_auto_enabled)
        config_meta = {
            key: value for key, value in config_meta.items() if value is not None
        }
        if config_meta:
            base_instrument["config"] = config_meta
        else:
            base_instrument.pop("config", None)
        if "device_serial" not in base_instrument and controller:
            base_instrument["device_serial"] = getattr(
                controller, "serial_number", None
            )
        self.instrument_info = base_instrument if base_instrument else None
        
        # Initialize processing info
        base_processing = dict(processing_info) if processing_info else {}
        base_processing["name"] = base_processing.get("name") or "batch_acquisition"
        base_processing["version"] = base_processing.get("version") or "1.0"
        parameters = dict(base_processing.get("parameters") or {})
        parameters.setdefault("source", "batch_acquisition")
        parameters.setdefault("points_per_well", points_per_well)
        parameters.setdefault("crop_start_nm", crop_start_wl)
        parameters.setdefault("crop_end_nm", crop_end_wl)
        parameters.setdefault("auto_enabled", is_auto_enabled)
        parameters.setdefault("intra_well_interval_s", intra_well_interval)
        parameters.setdefault("inter_well_interval_s", inter_well_interval)
        parameters.setdefault("layout_well_count", len(layout_data))
        base_processing["parameters"] = {
            key: value for key, value in parameters.items() if value is not None
        }
        self.processing_info = base_processing
        
        # Initialize wavelengths
        self.wavelengths = np.array(self.controller.wavelengths)
        if self.crop_start_wl is not None and self.crop_end_wl is not None:
            self.wavelength_mask = (self.wavelengths >= self.crop_start_wl) & (
                self.wavelengths <= self.crop_end_wl
            )
            self.cropped_wavelengths = self.wavelengths[self.wavelength_mask]
        else:
            self.wavelength_mask = None
            self.cropped_wavelengths = self.wavelengths
    
    def update_peak_method(self, new_method: str):
        """更新寻峰方法"""
        self.peak_method = new_method


    def request_collect(self):
        """Queue a collect command for the current acquisition phase."""
        if self.command_queue.empty():
            self.command_queue.put(("COLLECT", None))

    def trigger_action(self):
        """Legacy alias preserved for backwards compatibility."""
        self.request_collect()

    def stop(self):
        self._is_running = False
        if self.command_queue.empty():
            self.command_queue.put(("STOP", None))
        if self.controller:
            self.controller.abort_endpoint_pipe()

    def go_back(self):
        """Queue a request to move back to the previous task."""
        if self.task_index > 0 and self.command_queue.empty():
            self.command_queue.put(("BACKWARD", None))

    def request_import(self, payload: Dict[str, Any]):
        """Queue an import command for the current background or reference step."""
        if not payload or "type" not in payload or "spectrum" not in payload:
            return
        if self.command_queue.empty():
            self.command_queue.put(("IMPORT", payload))

    def _timed_preview_wait(self, duration):
        """Wait for a duration while publishing preview spectra."""
        start_time = time.time()
        current_task = self.tasks[self.task_index]
        current_well_id = current_task["well_id"]
        current_well_data = self.collected_data.get(current_well_id, {})
        all_completed_results = []
        for well_id, data in self.collected_data.items():
            all_completed_results.extend(data["absorbance"].values())
        while (time.time() - start_time) < duration:
            if not self._is_running:
                return False
            _, spectrum = self.controller.get_spectrum()
            data_package = {
                "full_wavelengths": self.wavelengths,
                "live_signal": spectrum,
                "background": current_well_data.get("background"),
                "reference": current_well_data.get("reference"),
                "result_wavelengths": self.cropped_wavelengths,
                "all_results": all_completed_results,
            }
            self.live_preview_data.emit(data_package)
            QThread.msleep(50)
        return True

    def _get_command_while_previewing(self):
        """Poll the command queue while streaming preview data."""
        self.command_queue.queue.clear()
        last_spectrum = None
        current_task = self.tasks[self.task_index]
        current_well_id = current_task["well_id"]
        current_well_data = self.collected_data.get(current_well_id, {})
        all_completed_results = []
        for well_id, data in self.collected_data.items():
            all_completed_results.extend(data["absorbance"].values())
        while self.command_queue.empty() and self._is_running:
            _, spectrum = self.controller.get_spectrum()
            last_spectrum = spectrum
            data_package = {
                "full_wavelengths": self.wavelengths,
                "live_signal": spectrum,
                "background": current_well_data.get("background"),
                "reference": current_well_data.get("reference"),
                "result_wavelengths": self.cropped_wavelengths,
                "all_results": all_completed_results,
            }
            self.live_preview_data.emit(data_package)
            QThread.msleep(50)
        command = ("STOP", None)
        if self._is_running:
            try:
                queued_item = self.command_queue.get_nowait()
                if isinstance(queued_item, tuple) and len(queued_item) == 2:
                    command = queued_item
                else:
                    command = (queued_item, None)
            except queue.Empty:
                print("Warning: preview loop exited but no command was queued.")
        return last_spectrum, command[0], command[1]

    def _initialize_batch_records(self) -> None:
        if not self.db_manager or self.project_id is None:
            return
        layout_reference = ""
        if self.layout_data:
            try:
                layout_reference = json.dumps(
                    {"wells": sorted(self.layout_data.keys())},
                    ensure_ascii=False,
                )
            except Exception:
                layout_reference = f"{len(self.layout_data)} wells"
        if not self.batch_run_id:
            run_name = time.strftime("Batch-%Y%m%d-%H%M%S")
            notes = f"Auto-generated batch run ({len(self.layout_data)} wells)"
            try:
                self.batch_run_id = self.db_manager.create_batch_run(
                    self.project_id,
                    run_name,
                    layout_reference=layout_reference,
                    operator=self.operator or "",
                    notes=notes,
                )
            except Exception as exc:
                print(f"鍒濆鍖栨壒閲忚繍琛屽け璐? {exc}")
                self.batch_run_id = None
        if not self.batch_run_id:
            return
        if self.batch_item_map:
            return
        try:
            item_payload: Dict[str, Dict[str, Any]] = {}
            for position_label, meta in (self.layout_data or {}).items():
                payload: Dict[str, Any] = {}
                if isinstance(meta, dict):
                    payload.update(meta)
                elif meta is not None:
                    payload["label"] = str(meta)
                payload.setdefault("expected_points", self.points_per_well)
                item_payload[position_label] = payload
            self.batch_item_map = self.db_manager.create_batch_items(
                self.batch_run_id,
                item_payload,
            )
        except Exception as exc:
            print(f"鍒涘缓鎵归噺瀛斾綅鏄庣粏澶辫触: {exc}")
            self.batch_item_map = {}

    def _ensure_well_experiment(self, well_id: str) -> Optional[int]:
        if not self.db_manager or self.project_id is None:
            return None
        if well_id in self.well_experiments:
            return self.well_experiments[well_id]
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        concentration = self.layout_data.get(well_id, {}).get("concentration")
        notes = f"Batch well {well_id}"
        if concentration is not None:
            notes += f", concentration={concentration}"
        config_snapshot = json.dumps(
            {
                "mode": "batch",
                "points_per_well": self.points_per_well,
                "crop_start": self.crop_start_wl,
                "crop_end": self.crop_end_wl,
                "auto_enabled": self.is_auto_enabled,
            },
            ensure_ascii=False,
        )
        experiment_name = f"Batch-{well_id}-{timestamp}"
        exp_id = self.db_manager.create_experiment(
            project_id=self.project_id,
            name=experiment_name,
            exp_type="Batch Measurement",
            timestamp=timestamp,
            operator=self.operator,
            notes=notes,
            config_snapshot=config_snapshot,
        )
        if exp_id:
            self.well_experiments[well_id] = exp_id
            item_id = self.batch_item_map.get(well_id)
            if item_id:
                self.db_manager.attach_experiment_to_batch_item(item_id, exp_id)
        return exp_id

    def _processing_payload_for_label(
        self, spectrum_label: str
    ) -> Optional[Dict[str, Any]]:
        if not self.processing_info:
            return None
        payload = {
            "name": self.processing_info.get("name", "batch_acquisition"),
            "version": self.processing_info.get("version", "1.0"),
            "parameters": dict(self.processing_info.get("parameters", {})),
        }
        if spectrum_label:
            payload["parameters"]["spectrum_label"] = spectrum_label
        return payload

    def _save_spectrum_to_db(
        self, well_id: str, spec_label: str, wavelengths, intensities
    ) -> Optional[int]:
        if not self.db_manager:
            return None
        exp_id = self._ensure_well_experiment(well_id)
        if exp_id is None:
            return None
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(wavelengths, np.ndarray):
            wl_list = wavelengths.tolist()
        else:
            wl_list = list(wavelengths)
        if isinstance(intensities, np.ndarray):
            int_list = intensities.tolist()
        else:
            int_list = list(intensities)

        try:
            item_id = self.batch_item_map.get(well_id) if self.batch_item_map else None
            spectrum_id = self.db_manager.save_spectrum(
                exp_id,
                spec_label,
                timestamp,
                wl_list,
                int_list,
                batch_run_item_id=item_id,
                instrument_info=self.instrument_info,
                processing_info=self._processing_payload_for_label(spec_label),
            )
            if spectrum_id:
                bucket = (
                    "Result"
                    if spec_label.startswith("Result")
                    else (
                        "Signal"
                        if spec_label.startswith("Signal")
                        else spec_label.capitalize()
                    )
                )
                self.spectrum_registry[well_id][bucket].append(spectrum_id)

            return spectrum_id
        except Exception as e:
            print(f"淇濆瓨鎵归噺鍏夎氨鍒版暟鎹簱澶辫触: {e}")
            return None


    def _align_imported_spectrum(
        self, imported_wavelengths: Any, imported_values: Any
    ) -> Tuple[Optional[np.ndarray], Optional[str]]:
        try:
            wavelengths = np.array(imported_wavelengths, dtype=float)
            values = np.array(imported_values, dtype=float)
        except (TypeError, ValueError):
            return None, "Imported data could not be parsed as numeric arrays."

        mask = np.isfinite(wavelengths) & np.isfinite(values)
        wavelengths = wavelengths[mask]
        values = values[mask]

        if (
            wavelengths.ndim != 1
            or values.ndim != 1
            or wavelengths.size != values.size
        ):
            return None, "Imported data has inconsistent dimensions."
        if wavelengths.size < 2:
            return None, "Imported spectrum must contain at least two points."

        order = np.argsort(wavelengths)
        wavelengths = wavelengths[order]
        values = values[order]

        target_wavelengths = self.wavelengths
        aligned = np.full(target_wavelengths.shape, np.nan, dtype=float)
        overlap_mask = (
            (target_wavelengths >= wavelengths[0])
            & (target_wavelengths <= wavelengths[-1])
        )
        if not np.any(overlap_mask):
            return None, "Imported wavelength range has no overlap with the instrument range."
        aligned[overlap_mask] = np.interp(
            target_wavelengths[overlap_mask], wavelengths, values
        )
        return aligned, None

    def _apply_imported_spectrum(
        self, well_id: str, task_type: str, payload: Optional[Dict[str, Any]]
    ) -> bool:
        if payload is None:
            self.error.emit("No spectrum data was provided for import.")
            return False
        if task_type not in {"background", "reference"}:
            self.error.emit("Import is only supported for background or reference steps.")
            return False

        requested_type = payload.get("type")
        if requested_type and requested_type != task_type:
            self.error.emit("Imported spectrum type does not match the current step.")
            return False

        aligned_values, error_message = self._align_imported_spectrum(
            payload.get("wavelengths"), payload.get("spectrum")
        )
        if aligned_values is None:
            if error_message:
                self.error.emit(error_message)
            return False
        if np.isnan(aligned_values).all():
            self.error.emit("Imported spectrum has no usable wavelength overlap.")
            return False

        file_path = payload.get("file_path", "")
        self._ensure_well_experiment(well_id)
        self.collected_data[well_id][task_type] = aligned_values
        self.collected_data[well_id][f"{task_type}_source"] = {
            "mode": "imported",
            "path": file_path,
        }
        label = "Background" if task_type == "background" else "Reference"
        self._save_spectrum_to_db(well_id, label, self.wavelengths, aligned_values)
        self._record_batch_capture(well_id, status="collecting")
        return True

    def _record_batch_capture(self, well_id: str, status: Optional[str] = None):
        if not self.db_manager:
            return
        item_id = self.batch_item_map.get(well_id)
        if not item_id:
            return
        capture_count = self.capture_counts.get(well_id)
        self.db_manager.update_batch_item_progress(
            item_id, capture_count=capture_count, status=status
        )

    def _finalize_batch_item(self, well_id: str, status: str = "completed"):
        if not self.db_manager:
            return
        item_id = self.batch_item_map.get(well_id)
        if item_id:
            self.db_manager.finalize_batch_item(item_id, status=status)
            if status == "completed":
                self.completed_wells.add(well_id)

    def _finalize_batch_run(self, status: str):
        if not self.db_manager or not self.batch_run_id:
            return
        # 鏍囪鏈畬鎴愮殑鏄庣粏
        for well_id, item_id in self.batch_item_map.items():
            if well_id not in self.completed_wells:
                self.db_manager.finalize_batch_item(item_id, status=status)
        self.db_manager.update_batch_run(self.batch_run_id, status=status)

    def _generate_tasks(self):
        # (姝ゅ嚱鏁版棤鍙樺寲)
        well_ids = sorted(self.layout_data.keys())
        for well_id in well_ids:
            self.tasks.append({"type": "background", "well_id": well_id})
            self.tasks.append({"type": "reference", "well_id": well_id})
            for point_num in range(1, self.points_per_well + 1):
                self.tasks.append(
                    {"type": "signal", "well_id": well_id, "point_num": point_num}
                )
            self.tasks.append({"type": "save", "well_id": well_id})



    def run(self):
        self.run_status = "in_progress"
        try:
            folder_timestamp = time.strftime("%Y%m%d-%H%M%S")
            run_output_folder = os.path.join(
                self.output_folder, f"BatchRun_{folder_timestamp}"
            )
            os.makedirs(run_output_folder, exist_ok=True)
            self._generate_tasks()
            total_tasks = len(self.tasks)
            while self.task_index < total_tasks and self._is_running:
                task = self.tasks[self.task_index]
                well_id = task["well_id"]
                task_type = task["type"]

                if task_type == "save":
                    self.update_dialog.emit(
                        {
                            "instruction_key": "Saving data for {well_id}...",
                            "params": {"well_id": well_id},
                            "total_progress": int(self.task_index / total_tasks * 100),
                            "point_progress": 100,
                            "phase": None,
                            "button_enabled": False,
                            "import_enabled": False,
                            "back_button_enabled": False,
                        }
                    )
                    well_data = self.collected_data[well_id]
                    signals_list = [
                        well_data["signals"][k]
                        for k in sorted(well_data["signals"] )
                    ]
                    absorbance_list = [
                        well_data["absorbance"][k]
                        for k in sorted(well_data["absorbance"])
                    ]
                    concentration = self.layout_data[well_id].get("concentration", 0.0)
                    timestamp_file = time.strftime("%Y%m%d-%H%M%S")
                    filename = f"{timestamp_file}_{well_id}_{concentration}nM{self.file_extension}"
                    output_path = os.path.join(run_output_folder, filename)
                    save_batch_spectrum_data(
                        file_path=output_path,
                        wavelengths=self.wavelengths,
                        absorbance_spectra=absorbance_list,
                        signals_list=signals_list,
                        background=well_data.get("background"),
                        reference=well_data.get("reference"),
                        crop_start_wl=self.crop_start_wl,
                        crop_end_wl=self.crop_end_wl,
                    )
                    exp_id = self._ensure_well_experiment(well_id)
                    if self.db_manager and exp_id:
                        serial_signals = [
                            np.asarray(sig).tolist() if sig is not None else None
                            for sig in signals_list
                        ]
                        serial_absorbance = [
                            np.asarray(val).tolist() if val is not None else None
                            for val in absorbance_list
                        ]
                        source_ids = []
                        registry = self.spectrum_registry[well_id]
                        for bucket in ("Background", "Reference", "Signal", "Result"):
                            source_ids.extend(registry.get(bucket, []))
                        summary_payload = {
                            "concentration": concentration,
                            "signals": serial_signals,
                            "absorbance": serial_absorbance,
                            "points_collected": len([s for s in serial_signals if s is not None]),
                        }
                        self.db_manager.save_analysis_result(
                            experiment_id=exp_id,
                            analysis_type="BatchSummary",
                            result_data=summary_payload,
                            source_spectrum_ids=source_ids,
                        )
                    self._record_batch_capture(well_id, status="completed")
                    self._finalize_batch_item(well_id, status="completed")
                    self.task_index += 1
                    continue

                if task_type == "background":
                    self.update_dialog.emit({
                        "instruction_key": "Please place [Background] for well {well_id}\\n(Live preview active...)",
                        "params": {"well_id": well_id},
                        "total_progress": int(self.task_index / total_tasks * 100),
                        "point_progress": 0,
                        "phase": "background",
                        "button_enabled": not self.is_auto_enabled,
                        "import_enabled": not self.is_auto_enabled,
                        "back_button_enabled": self.task_index > 0 and not self.is_auto_enabled,
                    })
                elif task_type == "reference":
                    self.update_dialog.emit({
                        "instruction_key": "Please place [Reference] for well {well_id}\\n(Live preview active...)",
                        "params": {"well_id": well_id},
                        "total_progress": int(self.task_index / total_tasks * 100),
                        "point_progress": 0,
                        "phase": "reference",
                        "button_enabled": not self.is_auto_enabled,
                        "import_enabled": not self.is_auto_enabled,
                        "back_button_enabled": not self.is_auto_enabled,
                    })
                elif task_type == "signal":
                    point_num = task["point_num"]
                    points_done = len(self.collected_data[well_id]["signals"])
                    self.update_dialog.emit({
                        "instruction_key": "Please move to well {well_id}, point {point_num}/{total_points}\\n(Live preview active...)",
                        "params": {"well_id": well_id, "point_num": point_num, "total_points": self.points_per_well},
                        "point_progress": int((points_done / self.points_per_well) * 100),
                        "total_progress": int(self.task_index / total_tasks * 100),
                        "phase": "signal",
                        "button_enabled": not self.is_auto_enabled,
                        "import_enabled": False,
                        "back_button_enabled": not self.is_auto_enabled,
                    })

                spectrum = None
                payload = None
                if not self.is_auto_enabled:
                    spectrum, command, payload = self._get_command_while_previewing()
                else:
                    delay = self.intra_well_interval
                    if task_type in ("background", "reference"):
                        delay = self.inter_well_interval
                    if not self._timed_preview_wait(delay):
                        command = "STOP"
                    else:
                        _, spectrum = self.controller.get_spectrum()
                        command = "COLLECT"
                        payload = None

                if command == "STOP" or not self._is_running:
                    if command == "STOP" and self.run_status == "in_progress":
                        self.run_status = "aborted"
                    break

                if command == "BACKWARD":
                    if self.task_index > 0:
                        previous_task = self.tasks[self.task_index - 1]
                        rollback_well = previous_task["well_id"]
                        rollback_type = previous_task["type"]
                        data = self.collected_data[rollback_well]
                        if rollback_type == "background":
                            data.pop("background", None)
                            data.pop("background_source", None)
                        elif rollback_type == "reference":
                            data.pop("reference", None)
                            data.pop("reference_source", None)
                        elif rollback_type == "signal":
                            point_num = previous_task["point_num"]
                            data["signals"].pop(point_num, None)
                            data["absorbance"].pop(point_num, None)
                            # 发出信号，通知UI从峰值表格中删除相应数据
                            self.peak_removed.emit(rollback_well, point_num)
                        self.task_index -= 1
                    continue

                if command == "IMPORT":
                    if not self._apply_imported_spectrum(well_id, task_type, payload):
                        continue
                    self.task_index += 1
                    continue

                if spectrum is None:
                    _, spectrum = self.controller.get_spectrum()
                self._ensure_well_experiment(well_id)

                if task_type == "background":
                    self.collected_data[well_id]["background"] = spectrum
                    self._save_spectrum_to_db(
                        well_id, "Background", self.wavelengths, spectrum
                    )
                    self._record_batch_capture(well_id, status="collecting")
                elif task_type == "reference":
                    self.collected_data[well_id]["reference"] = spectrum
                    self._save_spectrum_to_db(
                        well_id, "Reference", self.wavelengths, spectrum
                    )
                    self._record_batch_capture(well_id, status="collecting")
                elif task_type == "signal":
                    point_num = task["point_num"]
                    self.collected_data[well_id]["signals"][point_num] = spectrum
                    self._save_spectrum_to_db(
                        well_id,
                        f"Signal_Point_{point_num}",
                        self.wavelengths,
                        spectrum,
                    )
                    self.capture_counts[well_id] += 1
                    bg = self.collected_data[well_id].get("background")
                    ref = self.collected_data[well_id].get("reference")
                    if self.wavelength_mask is not None:
                        spectrum_np = np.array(spectrum)
                        bg_np = np.array(bg) if bg is not None else None
                        ref_np = np.array(ref) if ref is not None else None
                        signal_cropped = spectrum_np[self.wavelength_mask]
                        bg_cropped = bg_np[self.wavelength_mask] if bg_np is not None else None
                        ref_cropped = ref_np[self.wavelength_mask] if ref_np is not None else None
                    else:
                        signal_cropped, bg_cropped, ref_cropped = spectrum, bg, ref
                    absorbance = _calculate_absorbance(signal_cropped, bg_cropped, ref_cropped)
                    if absorbance is not None:
                        self.collected_data[well_id]["absorbance"][point_num] = absorbance
                        result_wavelengths = (
                            self.cropped_wavelengths
                            if self.wavelength_mask is not None
                            else self.wavelengths
                        )
                        
                        # 计算寻峰结果
                        from nanosense.algorithms.peak_analysis import find_main_resonance_peak, calculate_fwhm
                        peak_index, peak_properties = find_main_resonance_peak(absorbance, result_wavelengths, method=self.peak_method)
                        
                        # 计算半峰全宽
                        peak_info = {"peak_position": None, "peak_intensity": None, "fwhm": None}
                        if peak_index is not None:
                            # 获取峰值波长和强度
                            peak_info["peak_position"] = result_wavelengths[peak_index]
                            peak_info["peak_intensity"] = absorbance[peak_index]
                            
                            # 计算半峰全宽
                            fwhm = calculate_fwhm(result_wavelengths, absorbance, [peak_index])
                            if fwhm and len(fwhm) > 0:
                                peak_info["fwhm"] = fwhm[0]
                        
                        # 保存寻峰结果
                        self.collected_data[well_id]["peak_info"] = self.collected_data[well_id].get("peak_info", {})
                        self.collected_data[well_id]["peak_info"][point_num] = peak_info
                        
                        # 发射峰值信息信号
                        if peak_info["peak_position"] is not None and peak_info["peak_intensity"] is not None:
                            self.peak_found.emit(well_id, point_num, peak_info["peak_position"], peak_info["peak_intensity"])
                        
                        self._save_spectrum_to_db(
                            well_id,
                            f"Result_Point_{point_num}",
                            result_wavelengths,
                            absorbance,
                        )
                    self._record_batch_capture(well_id, status="collecting")

                self.task_index += 1

            if self._is_running:
                self.update_dialog.emit({
                    "instruction_key": "Batch acquisition complete!",
                    "total_progress": 100,
                    "point_progress": 100,
                    "phase": "complete",
                    "button_enabled": False,
                    "import_enabled": False,
                    "back_button_enabled": False,
                })
            try:
                if self._is_running:
                    all_results_data = {}
                    if (
                        not hasattr(self.controller, "wavelengths")
                        or self.controller.wavelengths is None
                    ):
                        raise ValueError("Unable to obtain instrument wavelength data.")
                    wavelengths = np.array(self.controller.wavelengths)
                    sorted_well_ids = sorted(self.collected_data.keys())
                    for well in sorted_well_ids:
                        well_data = self.collected_data[well]
                        if "absorbance" in well_data:
                            for point_num in sorted(well_data["absorbance"].keys()):
                                column_name = f"{well}_Point_{point_num}"
                                all_results_data[column_name] = well_data["absorbance"][point_num]
                    if all_results_data:
                        df_summary = pd.DataFrame(all_results_data)
                        wavelengths_for_summary = (
                            self.cropped_wavelengths
                            if self.wavelength_mask is not None
                            else wavelengths
                        )
                        df_summary.insert(0, "Wavelength", wavelengths_for_summary)
                        summary_filename = f"batch_summary_all_results_{folder_timestamp}.xlsx"
                        summary_output_path = os.path.join(run_output_folder, summary_filename)
                        df_summary.to_excel(summary_output_path, index=False, engine="openpyxl")
                        
                        # 保存寻峰结果到Excel文件
                        peak_results_data = []
                        for well in sorted_well_ids:
                            well_data = self.collected_data[well]
                            if "peak_info" in well_data:
                                for point_num in sorted(well_data["peak_info"].keys()):
                                    peak_info = well_data["peak_info"][point_num]
                                    peak_results_data.append({
                                        "Well ID": well,
                                        "Point Number": point_num,
                                        "Peak Wavelength (nm)": peak_info["peak_position"],
                                        "Peak Intensity (Abs)": peak_info["peak_intensity"],
                                        "FWHM (nm)": peak_info["fwhm"],
                                        "Peak Method": self.peak_method
                                    })
                        
                        if peak_results_data:
                            df_peak_results = pd.DataFrame(peak_results_data)
                            peak_results_filename = f"batch_peak_results_{folder_timestamp}.xlsx"
                            peak_results_output_path = os.path.join(run_output_folder, peak_results_filename)
                            df_peak_results.to_excel(peak_results_output_path, index=False, engine="openpyxl")
            except Exception as exc:
                self.run_status = "failed"
                print(f"Failed to generate batch summary file: {exc}")
                self.error.emit(f"Failed to generate final summary file: {exc}")
        except Exception as exc:
            self.run_status = "failed"
            self.error.emit(str(exc))
        finally:
            if self.run_status == "pending":
                self.run_status = "aborted"
            self._finalize_batch_run(self.run_status)
            self._is_running = False
            self.finished.emit()

