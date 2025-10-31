# nanosense/gui/measurement_widget.py

from .peak_metrics_dialog import PeakMetricsDialog
from .collapsible_box import CollapsibleBox
from .kinetics_window import KineticsWindow
from .single_plot_window import SinglePlotWindow
import time
import numpy as np
import queue
import threading
import os
from .realtime_noise_setup_dialog import RealTimeNoiseSetupDialog
from .noise_tools import RealTimeNoiseWorker, NoiseResultDialog
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QGridLayout,
                             QComboBox, QDialog, QMessageBox, QToolButton, QProgressDialog, QFileDialog)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal

import pyqtgraph as pg

from nanosense.algorithms.peak_analysis import (
    find_spectral_peaks,
    find_main_resonance_peak,
    calculate_fwhm,
    PEAK_METHOD_KEYS,
    PEAK_METHOD_LABELS,
    estimate_peak_position,
)
from nanosense.core.controller import FX2000Controller
from nanosense.utils.file_io import save_spectrum, load_spectrum, save_all_spectra_to_file
from nanosense.core.spectrum_processor import SpectrumProcessor

class MeasurementWidget(QWidget):
    kinetics_data_updated = pyqtSignal(dict)

    def __init__(self, controller: FX2000Controller, processor: SpectrumProcessor, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.db_manager = self.main_window.db_manager if self.main_window else None
        self.controller = controller
        self.processor = processor
        self.mode_name = "N/A"
        self.wavelengths = np.array(self.controller.wavelengths if self.controller else [])
        self.data_queue = queue.Queue(maxsize=10)
        self.stop_event = threading.Event()
        self.acquisition_thread = None

        self.is_kinetics_monitoring = False
        self.kinetics_start_time = None
        self.kinetics_last_sample_time = None  # 上一次记录/刷新动力学曲线的时间戳
        self.kinetics_sample_interval = 0.5    # 采样/刷新间隔（秒），可按需调整
        self.kinetics_window = None
        self.kinetics_baseline_value = None
        self.is_acquiring = False
        self.is_ui_update_enabled = True
        # --- 用于存储完整的、未经裁剪的结果光谱 ---
        self.full_result_x = None
        self.full_result_y = None

        # --- 用于存储所有弹出的独立窗口 ---
        self.popout_windows = []
        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self.init_ui()
        self.connect_signals()

        self.processor.result_updated.connect(self._on_result_updated)
        self.processor.background_updated.connect(self._on_background_updated)
        self.processor.reference_updated.connect(self._on_reference_updated)

        self._update_plot_x_range()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)
        control_panel = self._create_control_panel()
        plots_widget = self._create_plots_widget()
        main_layout.addWidget(control_panel)
        main_layout.addWidget(plots_widget, stretch=1)

    def _create_control_panel(self):
        """创建经过现代化改造的控制面板"""
        scroll_area = pg.QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(350)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        panel_widget = QWidget()
        panel_widget.setObjectName("controlPanel")
        panel_layout = QVBoxLayout(panel_widget)
        panel_layout.setSpacing(8)
        panel_layout.setContentsMargins(10, 10, 10, 10)

        # --- Acquisition Control ---
        self.acq_box = CollapsibleBox(self.tr("Acquisition Control"))
        acq_layout = QVBoxLayout()
        acq_layout.setSpacing(10)
        self.toggle_acq_button = QPushButton(self.tr("Start Acquisition"))
        self.capture_dark_button = QPushButton(self.tr("Capture Background (Dark)"))
        self.capture_ref_button = QPushButton(self.tr("Capture Reference (Ref)"))
        acq_layout.addWidget(self.toggle_acq_button)
        acq_layout.addWidget(self.capture_dark_button)
        acq_layout.addWidget(self.capture_ref_button)
        self.acq_box.setContentLayout(acq_layout)
        panel_layout.addWidget(self.acq_box)

        # --- Display Range Control ---
        self.range_box = CollapsibleBox(self.tr("Display Range Control"))
        self.range_layout = QFormLayout()
        self.range_layout.setSpacing(10)
        self.display_range_start_spinbox = QDoubleSpinBox()
        self.display_range_end_spinbox = QDoubleSpinBox()

        for spinbox in [self.display_range_start_spinbox, self.display_range_end_spinbox]:
            spinbox.setDecimals(2)
            spinbox.setRange(0, 1300)
            spinbox.setSingleStep(10.0)
            spinbox.setSuffix(self.tr(" nm"))

        self.display_range_start_spinbox.setValue(400.0)
        self.display_range_end_spinbox.setValue(850.0)

        self.reset_range_button = QPushButton(self.tr("Reset Display Range"))
        self.range_layout.addRow(self.tr("Start Wavelength:"), self.display_range_start_spinbox)
        self.range_layout.addRow(self.tr("End Wavelength:"), self.display_range_end_spinbox)
        self.range_layout.addRow(self.reset_range_button)
        self.range_box.setContentLayout(self.range_layout)
        panel_layout.addWidget(self.range_box)

        # --- Parameters & Preprocessing ---
        self.params_box = CollapsibleBox(self.tr("Parameters & Preprocessing"))
        self.params_layout = QFormLayout()
        self.params_layout.setSpacing(10)
        self.integration_time_spinbox = QSpinBox()
        self.integration_time_spinbox.setRange(10, 10000)
        self.integration_time_spinbox.setSuffix(self.tr(" ms"))
        self.integration_time_spinbox.setValue(100)
        self.smoothing_window_spinbox = QSpinBox()
        self.smoothing_window_spinbox.setRange(3, 99)
        self.smoothing_window_spinbox.setSingleStep(2)
        self.smoothing_window_spinbox.setValue(11)
        self.smooth_method_combo = QComboBox()
        self.smooth_method_combo.addItems(
            [self.tr("No Smoothing"), self.tr("Savitzky-Golay"),
             self.tr("Moving Average"), self.tr("Median Filter")]
        )
        self.baseline_correction_button = QPushButton(self.tr("Correct Current Baseline"))
        self.params_layout.addRow(self.tr("Integration Time:"), self.integration_time_spinbox)
        self.params_layout.addRow(self.tr("Smoothing Method:"), self.smooth_method_combo)
        self.params_layout.addRow(self.tr("Smoothing Window:"), self.smoothing_window_spinbox)
        self.params_layout.addRow(self.baseline_correction_button)
        self.params_box.setContentLayout(self.params_layout)
        panel_layout.addWidget(self.params_box)

        # --- Spectral Analysis ---
        self.analysis_box = CollapsibleBox(self.tr("Spectral Analysis"))
        analysis_outer_layout = QVBoxLayout()
        analysis_outer_layout.setSpacing(10)
        self.analysis_form_layout = QFormLayout()
        self.peak_method_combo = QComboBox()
        for method_key in PEAK_METHOD_KEYS:
            label = PEAK_METHOD_LABELS[method_key]
            self.peak_method_combo.addItem(self.tr(label), userData=method_key)
        self.peak_height_spinbox = QDoubleSpinBox()
        self.peak_height_spinbox.setDecimals(4)
        self.peak_height_spinbox.setRange(-1000, 10000)
        self.peak_height_spinbox.setValue(0.1)
        self.find_peaks_button = QPushButton(self.tr("Find All Peaks"))
        self.find_main_peak_button = QPushButton(self.tr("Find Main Resonance Peak"))
        self.analysis_form_layout.addRow(self.tr("Main Peak Algorithm:"), self.peak_method_combo)
        self.analysis_form_layout.addRow(self.tr("Minimum Peak Height:"), self.peak_height_spinbox)
        analysis_outer_layout.addLayout(self.analysis_form_layout)
        self.range_group = QGroupBox(self.tr("Spectral Peak Find Range"))
        self.range_layout_form = QFormLayout(self.range_group)
        self.range_start_spinbox = QDoubleSpinBox()
        self.range_end_spinbox = QDoubleSpinBox()
        for spinbox in [self.range_start_spinbox, self.range_end_spinbox]:
            spinbox.setDecimals(2)
            spinbox.setRange(200.0, 1200.0)
            spinbox.setSingleStep(10.0)
            spinbox.setSuffix(self.tr(" nm"))
        self.range_layout_form.addRow(self.tr("Start Position:"), self.range_start_spinbox)
        self.range_layout_form.addRow(self.tr("End Position:"), self.range_end_spinbox)
        analysis_outer_layout.addWidget(self.range_group)
        analysis_outer_layout.addWidget(self.find_peaks_button)
        analysis_outer_layout.addWidget(self.find_main_peak_button)
        self.result_display_group = QGroupBox(self.tr("Analysis Results"))
        self.result_display_group.setStyleSheet(
            "QGroupBox { background-color: transparent; border: none; margin-top: 0.5em; padding: 0; }")
        self.result_display_layout = QFormLayout(self.result_display_group)
        self.main_peak_wavelength_label = QLabel("N/A")
        self.main_peak_intensity_label = QLabel("N/A")
        self.result_display_layout.addRow(self.tr("Peak Wavelength (nm):"), self.main_peak_wavelength_label)
        self.result_display_layout.addRow(self.tr("Peak Intensity:"), self.main_peak_intensity_label)
        analysis_outer_layout.addWidget(self.result_display_group)
        self.analysis_box.setContentLayout(analysis_outer_layout)
        panel_layout.addWidget(self.analysis_box)

        # --- Kinetics Monitoring & Data Operations ---
        self.kinetics_box = CollapsibleBox(self.tr("Kinetics Monitoring"))
        kinetics_layout = QVBoxLayout()
        kinetics_layout.setSpacing(10)

        kinetics_form_layout = QFormLayout()
        self.kinetics_interval_spinbox = QDoubleSpinBox()
        self.kinetics_interval_spinbox.setDecimals(2)
        self.kinetics_interval_spinbox.setRange(0.05, 3600.0)  # 从 50ms 到 1 小时
        self.kinetics_interval_spinbox.setValue(1.0)          # 默认 1 秒
        self.kinetics_interval_spinbox.setSuffix(" s")
        kinetics_form_layout.addRow(self.tr("Sampling Interval:"), self.kinetics_interval_spinbox)

        kinetics_layout.addLayout(kinetics_form_layout)
        self.set_baseline_button = QPushButton(self.tr("Set Baseline from Current Peak"))
        self.set_baseline_button.setEnabled(False)
        kinetics_layout.addWidget(self.set_baseline_button)
        self.toggle_kinetics_button = QPushButton(self.tr("Start Monitoring"))
        kinetics_layout.addWidget(self.toggle_kinetics_button)
        self.kinetics_box.setContentLayout(kinetics_layout)
        panel_layout.addWidget(self.kinetics_box)

        self.data_op_box = CollapsibleBox(self.tr("Data Operations"))
        data_op_layout = QVBoxLayout()
        data_op_layout.setSpacing(10)
        self.save_all_button = QPushButton(self.tr("Save All Spectra"))
        self.save_data_button = QPushButton(self.tr("Save Result Spectrum"))
        self.load_data_button = QPushButton(self.tr("Load Spectrum for Comparison"))
        data_op_layout.addWidget(self.save_all_button)
        data_op_layout.addWidget(self.save_data_button)
        data_op_layout.addWidget(self.load_data_button)
        self.data_op_box.setContentLayout(data_op_layout)
        panel_layout.addWidget(self.data_op_box)

        # --- Final Setup ---
        self.acq_box.set_expanded(True)
        self.range_box.set_expanded(False)
        self.params_box.set_expanded(False)
        self.analysis_box.set_expanded(False)
        self.kinetics_box.set_expanded(False)
        self.data_op_box.set_expanded(False)
        panel_layout.addStretch()
        self.back_button = QPushButton(self.tr("← Back to Welcome Screen"))
        panel_layout.addWidget(self.back_button)
        scroll_area.setWidget(panel_widget)
        return scroll_area

    def _create_plots_widget(self):
        plots_container = QWidget()
        plots_container.setObjectName("plotsContainer")

        main_plots_layout = QVBoxLayout(plots_container)
        main_plots_layout.setSpacing(10)

        def create_plot_container(plot_widget, title_key, popout_handler):
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
            popout_button.setIcon(pg.QtGui.QIcon(icon_path))
            popout_button.setToolTip(self.tr("Open in New Window"))
            popout_button.clicked.connect(popout_handler)

            header_layout.addWidget(title_label)
            header_layout.addStretch()
            header_layout.addWidget(popout_button)

            layout.addWidget(header_widget)
            layout.addWidget(plot_widget)

            plot_widget.setTitle("")
            plot_widget.showGrid(x=True, y=True, alpha=0.3)

            return container, title_label

        # --- 创建所有图表和容器 ---
        self.signal_plot = pg.PlotWidget()
        self.signal_curve = self.signal_plot.plot(pen='b')
        self.background_plot = pg.PlotWidget()
        self.background_curve = self.background_plot.plot(pen='w')
        self.reference_plot = pg.PlotWidget()
        self.reference_curve = self.reference_plot.plot(pen='g')
        self.result_plot = pg.PlotWidget()
        self.result_curve = self.result_plot.plot(pen='r')

        self.signal_plot_container, self.signal_title_label = create_plot_container(
            self.signal_plot, "Signal Spectrum", lambda: self._open_single_plot_window('signal')
        )
        self.background_plot_container, self.background_title_label = create_plot_container(
            self.background_plot, "Background Spectrum", lambda: self._open_single_plot_window('background')
        )
        self.reference_plot_container, self.reference_title_label = create_plot_container(
            self.reference_plot, "Reference Spectrum", lambda: self._open_single_plot_window('reference')
        )
        self.result_plot_container, self.result_title_label = create_plot_container(
            self.result_plot, "Result Spectrum", lambda: self._open_single_plot_window('result')
        )

        top_row_widget = QWidget()
        top_row_layout = QHBoxLayout(top_row_widget)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(10)
        top_row_layout.addWidget(self.signal_plot_container)
        top_row_layout.addWidget(self.background_plot_container)
        top_row_layout.addWidget(self.reference_plot_container)
        main_plots_layout.addWidget(top_row_widget)
        main_plots_layout.addWidget(self.result_plot_container)
        main_plots_layout.setStretch(0, 3)
        main_plots_layout.setStretch(1, 4)

        self.peak_markers = pg.ScatterPlotItem(size=10, pen=pg.mkPen(None), brush=pg.mkBrush(255, 100, 100, 150))
        self.result_plot.addItem(self.peak_markers)
        self.main_peak_marker = pg.ScatterPlotItem(size=15, symbol='star', pen=pg.mkPen('y'), brush=pg.mkBrush('y'))
        self.result_plot.addItem(self.main_peak_marker)
        self.loaded_curve = self.result_plot.plot(pen=pg.mkPen('y', style=Qt.DashLine, width=2))
        self.fit_curve = self.result_plot.plot(pen=pg.mkPen('c', style=Qt.DotLine, width=2))

        initial_start = 450
        initial_end = 750
        self.region_selector = pg.LinearRegionItem(values=[initial_start, initial_end],
                                                   orientation=pg.LinearRegionItem.Vertical)
        self.result_plot.addItem(self.region_selector)
        self.range_start_spinbox.setValue(initial_start)
        self.range_end_spinbox.setValue(initial_end)

        for plot in [self.signal_plot, self.background_plot, self.reference_plot]:
            plot.setLabel('left', self.tr('Intensity'))
            plot.setLabel('bottom', self.tr('Wavelength (nm)'))
            plot.setXLink(self.signal_plot)

        self.result_plot.setLabel('left', self.mode_name)
        self.result_plot.setLabel('bottom', self.tr('Wavelength (nm)'))

        if self.wavelengths.any():
            min_wl, max_wl = self.wavelengths[0], self.wavelengths[-1]
            self.signal_plot.setXRange(min_wl, max_wl, padding=0.02)

        return plots_container

    def _find_all_peaks(self):
        if self.full_result_y is None:
            print(self.tr("Peak finding failed: No valid data in the result plot."))
            return

        x_data, y_data = self.full_result_x, self.full_result_y
        min_height = self.peak_height_spinbox.value()

        min_wl, max_wl = self.region_selector.getRegion()
        region_indices = np.where((x_data >= min_wl) & (x_data <= max_wl))[0]
        if len(region_indices) < 3:
            print(self.tr("Too few data points in the selected region to find peaks."))
            self.peak_markers.clear()
            return

        start_index = region_indices[0]
        y_subset = y_data[region_indices]
        indices_subset, properties = find_spectral_peaks(y_subset, min_height=min_height)

        if indices_subset.any():
            indices_global = indices_subset + start_index
            peak_x = x_data[indices_global]
            peak_y = y_data[indices_global]
            fwhms = calculate_fwhm(x_data, y_data, indices_global)

            self.peak_markers.setData(peak_x, peak_y)
            print(self.tr("Found {0} peaks in the selected region.").format(len(indices_global)))

            peak_data_for_table = {'wavelengths': peak_x, 'heights': peak_y, 'fwhms': fwhms}
            dialog = PeakMetricsDialog(peak_data_for_table, self)
            dialog.exec_()
        else:
            self.peak_markers.clear()
            print(self.tr("No peaks found with the current settings in the selected region."))

    def _find_main_resonance_peak(self):
        if self.full_result_y is None:
            print(self.tr("Finding main peak failed: No valid data in the result plot."))
            return

        x_data, y_data = self.full_result_x, self.full_result_y
        min_height = self.peak_height_spinbox.value()

        min_wl, max_wl = self.region_selector.getRegion()
        region_indices = np.where((x_data >= min_wl) & (x_data <= max_wl))[0]
        if len(region_indices) < 3:
            print(self.tr("Too few data points in the selected region."))
            self.main_peak_marker.clear()
            return

        start_index = region_indices[0]
        y_subset = y_data[region_indices]

        main_peak_index_subset, _ = find_main_resonance_peak(y_subset, min_height=min_height)

        if main_peak_index_subset is not None:
            main_peak_index_global = main_peak_index_subset + start_index
            peak_x = x_data[main_peak_index_global]
            peak_y = y_data[main_peak_index_global]

            self.main_peak_marker.setData([peak_x], [peak_y])
            self.main_peak_wavelength_label.setText(f"{peak_x:.4f}")
            self.main_peak_intensity_label.setText(f"{peak_y:.4f}")
            print(self.tr("Found main resonance peak @ {0:.2f} nm, Intensity: {1:.2f}").format(peak_x, peak_y))
        else:
            self.main_peak_marker.clear()
            self.main_peak_wavelength_label.setText(self.tr("Not Found"))
            self.main_peak_intensity_label.setText(self.tr("Not Found"))
            print(self.tr("Main resonance peak not found with current settings in the selected region."))

    def connect_signals(self):
        self.processor.background_updated.connect(self.update_background_plot)
        self.processor.reference_updated.connect(self.update_reference_plot)
        self.toggle_acq_button.clicked.connect(self._on_toggle_button_clicked)
        self.capture_dark_button.clicked.connect(self.processor.set_background)
        self.capture_ref_button.clicked.connect(self.processor.set_reference)
        self.integration_time_spinbox.valueChanged.connect(self._on_integration_time_changed)

        self.display_range_start_spinbox.valueChanged.connect(self._update_plot_x_range)
        self.display_range_end_spinbox.valueChanged.connect(self._update_plot_x_range)

        self.reset_range_button.clicked.connect(self._reset_display_range)

        self.find_peaks_button.clicked.connect(self._find_all_peaks)
        self.find_main_peak_button.clicked.connect(self._find_main_resonance_peak)
        self.save_data_button.clicked.connect(self._save_result_spectrum)
        self.load_data_button.clicked.connect(self._load_spectrum_data_for_comparison)
        self.set_baseline_button.clicked.connect(self._set_kinetics_baseline_from_current_peak)
        self.toggle_kinetics_button.clicked.connect(self._toggle_kinetics_window)

        self.save_all_button.clicked.connect(self._save_all_spectra)

        self.range_start_spinbox.valueChanged.connect(self._on_range_spinbox_changed)
        self.range_end_spinbox.valueChanged.connect(self._on_range_spinbox_changed)
        self.region_selector.sigRegionChanged.connect(self._on_region_changed)

    def _open_single_plot_window(self, plot_type):
        """创建并显示一个独立的图表窗口。"""
        plot_map = {
            'signal': (self.signal_plot, self.signal_curve, self.tr("Signal Spectrum")),
            'background': (self.background_plot, self.background_curve, self.tr("Background Spectrum")),
            'reference': (self.reference_plot, self.reference_curve, self.tr("Reference Spectrum")),
            'result': (self.result_plot, self.result_curve, f"{self.tr('Result Spectrum')} ({self.mode_name})")
        }
        if plot_type not in plot_map:
            return

        source_plot, source_curve, title = plot_map[plot_type]

        current_x_range = source_plot.getViewBox().viewRange()[0]
        current_y_range = source_plot.getViewBox().viewRange()[1]
        win = SinglePlotWindow(title, initial_x_range=current_x_range, initial_y_range=current_y_range, parent=self)

        x_data, y_data = source_curve.getData()
        pen = source_curve.opts['pen']
        win.update_data(x_data, y_data, pen)

        self.popout_windows.append({'type': plot_type, 'window': win})
        win.closed.connect(self._on_popout_closed)
        win.show()

    def _on_popout_closed(self, window_instance):
        """当独立窗口被关闭时，将其从更新列表中移除。"""
        self.popout_windows = [item for item in self.popout_windows if item['window'] is not window_instance]
        print(self.tr("A pop-out plot window has been closed."))

    def _build_instrument_metadata(self):
        info = {
            'device_serial': getattr(self.controller, 'serial_number', None) if self.controller else None,
            'integration_time_ms': float(self.integration_time_spinbox.value()) if hasattr(self, 'integration_time_spinbox') else None,
            'averaging': getattr(self.controller, 'scans_to_average', None) if self.controller else None,
            'config': {
                'spectrometer_name': getattr(self.controller, 'name', None) if self.controller else None,
                'mode': self.mode_name,
            }
        }
        config = {key: value for key, value in info.get('config', {}).items() if value is not None}
        if config:
            info['config'] = config
        else:
            info.pop('config', None)
        if all(info.get(key) is None for key in ('device_serial', 'integration_time_ms', 'averaging', 'temperature')) and 'config' not in info:
            return None
        return info

    def _build_processing_metadata(self, spectrum_role=None):
        parameters = {
            'mode': self.mode_name,
            'smoothing_method': self.smooth_method_combo.currentText() if hasattr(self, 'smooth_method_combo') else None,
            'smoothing_window': int(self.smoothing_window_spinbox.value()) if hasattr(self, 'smoothing_window_spinbox') else None,
            'peak_method': self.peak_method_combo.currentData() if hasattr(self, 'peak_method_combo') and self.peak_method_combo.currentData() else (self.peak_method_combo.currentText() if hasattr(self, 'peak_method_combo') else None),
            'peak_height_threshold': float(self.peak_height_spinbox.value()) if hasattr(self, 'peak_height_spinbox') else None,
            'region_start_nm': float(self.range_start_spinbox.value()) if hasattr(self, 'range_start_spinbox') else None,
            'region_end_nm': float(self.range_end_spinbox.value()) if hasattr(self, 'range_end_spinbox') else None,
            'baseline_defined': self.kinetics_baseline_value is not None
        }
        if spectrum_role:
            parameters['spectrum_role'] = spectrum_role
        parameters = {key: value for key, value in parameters.items() if value is not None}
        return {
            'name': 'measurement_widget',
            'version': '1.0',
            'parameters': parameters
        }

    def _save_result_spectrum(self):
        """保存由寻峰范围选择器定义的数据区域。"""
        if self.full_result_y is None:
            QMessageBox.warning(
                self,
                self.tr("Save Failed"),
                self.tr("There is no valid data in the result plot to save.")
            )
            return

        full_x_data, full_y_data = self.full_result_x, self.full_result_y
        min_wl, max_wl = self.region_selector.getRegion()
        mask = (full_x_data >= min_wl) & (full_x_data <= max_wl)
        x_data_sliced = full_x_data[mask]
        y_data_sliced = full_y_data[mask]

        default_save_path = self.app_settings.get('default_save_path', '')
        file_path = save_spectrum(self, self.mode_name, x_data_sliced, y_data_sliced, default_save_path)

        if file_path and self.db_manager:
            try:
                experiment_id = self.main_window.get_or_create_current_experiment_id()
                if experiment_id:
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    instrument_info = self._build_instrument_metadata()

                    self.db_manager.save_spectrum(
                        experiment_id,
                        f"Result_{self.mode_name}",
                        timestamp,
                        full_x_data,
                        full_y_data,
                        instrument_info=instrument_info,
                        processing_info=self._build_processing_metadata('Result'),
                    )
                    if self.processor.latest_signal_spectrum is not None:
                        self.db_manager.save_spectrum(
                            experiment_id,
                            "Signal",
                            timestamp,
                            self.wavelengths,
                            self.processor.latest_signal_spectrum,
                            instrument_info=instrument_info,
                            processing_info=self._build_processing_metadata('Signal'),
                        )
                    if self.processor.background_spectrum is not None:
                        self.db_manager.save_spectrum(
                            experiment_id,
                            "Background",
                            timestamp,
                            self.wavelengths,
                            self.processor.background_spectrum,
                            instrument_info=instrument_info,
                            processing_info=self._build_processing_metadata('Background'),
                        )
                    if self.processor.reference_spectrum is not None:
                        self.db_manager.save_spectrum(
                            experiment_id,
                            "Reference",
                            timestamp,
                            self.wavelengths,
                            self.processor.reference_spectrum,
                            instrument_info=instrument_info,
                            processing_info=self._build_processing_metadata('Reference'),
                        )
                    print(f"光谱数据已同步保存到数据库，实验ID: {experiment_id}")
                    QMessageBox.information(self, self.tr("Database Sync"),
                                            self.tr("Spectrum data has been successfully saved to file and database.\n"
                                                    "Experiment ID: {0}").format(experiment_id))
            except Exception as e:
                print(f"同步到数据库时出错: {e}")
                QMessageBox.warning(self, self.tr("Database Error"),
                                    self.tr("File saved, but an error occurred while syncing to the database:\n{0}")
                                    .format(str(e)))

    def _save_all_spectra(self):
        """保存所有光谱（使用当前寻峰范围裁剪）。"""
        background_spec = self.processor.background_spectrum
        reference_spec = self.processor.reference_spectrum
        signal_spec = self.processor.latest_signal_spectrum
        result_spec = self.full_result_y

        if signal_spec is None:
            QMessageBox.warning(self, self.tr("Incomplete Data"),
                                self.tr("Cannot save because there is no live signal spectrum."))
            return

        min_wl, max_wl = self.region_selector.getRegion()
        mask = (self.wavelengths >= min_wl) & (self.wavelengths <= max_wl)

        spectra_to_save = {
            'Signal': signal_spec[mask] if signal_spec is not None else None,
            'Background': background_spec[mask] if background_spec is not None else None,
            'Reference': reference_spec[mask] if reference_spec is not None else None,
            self.mode_name: result_spec[mask] if result_spec is not None else None
        }

        default_save_path = self.app_settings.get('default_save_path', '')

        save_all_spectra_to_file(
            parent=self,
            mode_name=self.mode_name,
            wavelengths=self.wavelengths[mask],
            spectra_dict=spectra_to_save,
            default_path=default_save_path
        )

    def _on_range_spinbox_changed(self):
        """当输入框数值改变时，更新图表上的区域。"""
        start_val = self.range_start_spinbox.value()
        end_val = self.range_end_spinbox.value()
        self.region_selector.blockSignals(True)
        self.region_selector.setRegion((start_val, end_val))
        self.region_selector.blockSignals(False)

    def _on_region_changed(self):
        """当图表上的区域被拖拽时，更新输入框的数值。"""
        min_val, max_val = self.region_selector.getRegion()
        self.range_start_spinbox.blockSignals(True)
        self.range_end_spinbox.blockSignals(True)
        self.range_start_spinbox.setValue(min_val)
        self.range_end_spinbox.setValue(max_val)
        self.range_start_spinbox.blockSignals(False)
        self.range_end_spinbox.blockSignals(False)

    def set_mode(self, mode_name):
        # 若正在动力学监测，先关闭
        if self.is_kinetics_monitoring:
            self._toggle_kinetics_window()

        self.main_peak_marker.clear()
        self.main_peak_wavelength_label.setText("N/A")
        self.main_peak_intensity_label.setText("N/A")
        if hasattr(self, 'loaded_curve'):
            self.loaded_curve.clear()
        self.peak_markers.clear()

        self.mode_name = mode_name
        display_name = self.tr(self.mode_name)

        self.result_plot.setLabel('left', display_name)
        self.result_plot.setTitle(display_name, color='#90A4AE', size='12pt')
        self.result_title_label.setText(display_name)

        if self.mode_name in ["Reflectance", "Absorbance", "Transmission"]:
            self.capture_ref_button.show()
            self.reference_plot.show()
        else:
            self.capture_ref_button.hide()
            self.reference_plot.hide()

        self.processor.set_mode(mode_name)
        self.processor.clear_background()
        self.processor.clear_reference()

        self.result_curve.clear()
        self.background_curve.clear()
        self.reference_curve.clear()
        print(self.tr("Measurement page switched to: {0}").format(display_name))
        self._toggle_acquisition(True)

    def update_plot(self):
        try:
            raw_signal = self.data_queue.get_nowait()
            if raw_signal is None:
                return

            self.signal_curve.setData(self.wavelengths, raw_signal)

            if self.processor.background_spectrum is None:
                self.background_curve.setData(self.wavelengths, raw_signal)
            if self.processor.reference_spectrum is None:
                self.reference_curve.setData(self.wavelengths, raw_signal)

            self.processor.update_signal(raw_signal)

            # === 动力学采样：统一使用 monotonic 计时，首帧兜底 ===
            if self.is_kinetics_monitoring:
                current_time = time.monotonic()
                interval = float(self.kinetics_interval_spinbox.value())

                if self.kinetics_start_time is None:
                    self.kinetics_start_time = current_time
                if self.kinetics_last_sample_time is None:
                    self.kinetics_last_sample_time = current_time  # 允许首帧立即输出

                if (current_time - self.kinetics_last_sample_time) >= interval:
                    self.kinetics_last_sample_time = current_time

                    peak_wl = self._get_main_peak_wavelength(y_data=self.full_result_y)
                    if peak_wl is not None:
                        elapsed_time = current_time - self.kinetics_start_time

                        data_package = {
                            'result_x': self.full_result_x,
                            'result_y': self.full_result_y,
                            'elapsed_time': float(elapsed_time),
                            'peak_wl': float(peak_wl)
                        }
                        self.kinetics_data_updated.emit(data_package)

            # 更新弹出窗口
            for item in self.popout_windows:
                win = item['window']
                plot_type = item['type']

                if plot_type == 'signal':
                    win.update_data(self.wavelengths, raw_signal, self.signal_curve.opts['pen'])
                elif plot_type == 'background':
                    if self.processor.background_spectrum is None:
                        win.update_data(self.wavelengths, raw_signal, self.background_curve.opts['pen'])
                elif plot_type == 'reference':
                    if self.processor.reference_spectrum is None:
                        win.update_data(self.wavelengths, raw_signal, self.reference_curve.opts['pen'])
                elif plot_type == 'result':
                    x, y = self.result_curve.getData()
                    win.update_data(x, y, self.result_curve.opts['pen'])
                elif plot_type == 'sensorgram':
                    pass

        except queue.Empty:
            pass

    def _on_result_updated(self, x_data, y_data):
        """确保接收到的数据在处理前被转换为Numpy数组。"""
        self.full_result_x = np.array(x_data)
        if y_data is not None:
            self.full_result_y = np.array(y_data)
        else:
            self.full_result_y = None

        if hasattr(self, 'set_baseline_button'):
            self.set_baseline_button.setEnabled(self.full_result_y is not None)

        self._update_result_plot_with_crop()

    def _update_result_plot_with_crop(self):
        """根据显示范围裁剪完整结果光谱并更新绘图。"""
        if self.full_result_y is None:
            self.result_curve.clear()
            return

        start_wl = self.display_range_start_spinbox.value()
        end_wl = self.display_range_end_spinbox.value()

        mask = (self.full_result_x >= start_wl) & (self.full_result_x <= end_wl)
        x_cropped = self.full_result_x[mask]
        y_cropped = self.full_result_y[mask]

        self.result_curve.setData(x_cropped, y_cropped)

    def _on_background_updated(self, x_data, y_data):
        if y_data is not None:
            self.background_curve.setData(x_data, y_data)
        else:
            self.background_curve.clear()

    def _on_reference_updated(self, x_data, y_data):
        if y_data is not None:
            self.reference_curve.setData(x_data, y_data)
        else:
            self.reference_curve.clear()

    def _on_toggle_button_clicked(self):
        """专门响应按钮点击的槽函数，明确地切换采集状态。"""
        self._toggle_acquisition(start=not self.is_acquiring)

    def _toggle_acquisition(self, start):
        """根据明确的布尔参数开始或停止采集。"""
        if start == self.is_acquiring:
            return

        if start:
            self.is_acquiring = True
            self.toggle_acq_button.setText(self.tr("Stop Acquisition"))

            if hasattr(self, 'acquisition_thread') and self.acquisition_thread and self.acquisition_thread.is_alive():
                self.stop_event.set()
                self.acquisition_thread.join(timeout=0.5)

            self.stop_event.clear()
            self.acquisition_thread = threading.Thread(target=self.acquisition_thread_func)
            self.acquisition_thread.daemon = True
            self.acquisition_thread.start()

            if not hasattr(self, 'update_timer'):
                self.update_timer = QTimer(self)
                self.update_timer.setInterval(50)
                self.update_timer.timeout.connect(self.update_plot)
            self.update_timer.start()
            print(self.tr("Acquisition thread has started."))

        else:
            self.is_acquiring = False
            self.toggle_acq_button.setText(self.tr("Start Acquisition"))

            if hasattr(self, 'update_timer'):
                self.update_timer.stop()
            if hasattr(self, 'stop_event'):
                self.stop_event.set()

            if hasattr(self, 'acquisition_thread') and self.acquisition_thread and self.acquisition_thread.is_alive():
                self.acquisition_thread.join(timeout=0.5)

            print(self.tr("Acquisition thread has stopped."))

    def _on_integration_time_changed(self, value):
        if self.controller:
            self.controller.set_integration_time(value)

    def acquisition_thread_func(self):
        while not self.stop_event.is_set():
            if self.controller and self.is_acquiring:
                _, spectrum = self.controller.get_spectrum()
                if not self.data_queue.full():
                    self.data_queue.put(np.array(spectrum))
            else:
                time.sleep(0.1)

    def stop_all_activities(self):
        if self.is_kinetics_monitoring:
            self._toggle_kinetics_window()
        if self.is_acquiring:
            self._toggle_acquisition(False)
        self.stop_event.set()
        if self.acquisition_thread and self.acquisition_thread.is_alive():
            self.acquisition_thread.join(timeout=0.5)

    def _load_spectrum_data_for_comparison(self):
        default_load_path = self.app_settings.get('default_load_path', '')
        x_data, y_data, file_path = load_spectrum(self, default_load_path)
        if x_data is not None and y_data is not None:
            self.loaded_curve.setData(x_data, y_data)
            print(self.tr("Comparison spectrum '{0}' loaded and displayed.").format(os.path.basename(file_path)))

    def _set_kinetics_baseline_from_current_peak(self):
        """将当前结果谱的主峰设置为动力学基线�?"""
        if self.full_result_y is None:
            QMessageBox.warning(
                self,
                self.tr("Baseline Setup"),
                self.tr("No valid result spectrum is available to determine the baseline peak.")
            )
            return

        peak_value = self._get_main_peak_wavelength(self.full_result_y)
        if peak_value is None:
            QMessageBox.warning(
                self,
                self.tr("Baseline Setup"),
                self.tr("Unable to determine the peak wavelength within the selected range.")
            )
            return

        self.kinetics_baseline_value = float(peak_value)
        if self.kinetics_window is not None:
            self.kinetics_window.set_baseline_peak_wavelength(self.kinetics_baseline_value)

        print(self.tr("Kinetics baseline set to {0:.3f} nm.").format(self.kinetics_baseline_value))

    def _on_kinetics_baseline_changed(self, baseline_value):
        """接收动力学窗口的基线更新并同步到测量页"""
        if baseline_value is None:
            self.kinetics_baseline_value = None
        else:
            self.kinetics_baseline_value = float(baseline_value)

    def _toggle_kinetics_window(self):
        """打开或关闭独立的动力学监测窗口。"""
        if self.kinetics_window is None:
            # 开启监测
            self.is_kinetics_monitoring = True
            self.toggle_kinetics_button.setText(self.tr("Stop Monitoring"))
            self.kinetics_interval_spinbox.setEnabled(False)

            # 顶层非模态窗口：parent=None，保证弹出
            self.kinetics_window = KineticsWindow(parent=None)
            self.kinetics_window.baseline_changed.connect(self._on_kinetics_baseline_changed)
            if self.kinetics_baseline_value is not None:
                self.kinetics_window.set_baseline_peak_wavelength(self.kinetics_baseline_value)

            # 关闭信号：无参
            self.kinetics_window.closed.connect(self._on_kinetics_window_closed)

            # 数据转发
            self.kinetics_data_updated.connect(self.kinetics_window.update_kinetics_data)

            # 统一计时（monotonic）
            now = time.monotonic()
            self.kinetics_start_time = now
            self.kinetics_last_sample_time = now

            # 显示并置前
            self.kinetics_window.show()
            self.kinetics_window.raise_()
            self.kinetics_window.activateWindow()

            print("Kinetics monitoring window opened.")
        else:
            # 已存在：若隐藏/最小化则复原，否则关闭
            if (not self.kinetics_window.isVisible()) or self.kinetics_window.isMinimized():
                self.kinetics_window.showNormal()
                self.kinetics_window.raise_()
                self.kinetics_window.activateWindow()
            else:
                try:
                    self.kinetics_window.close()
                finally:
                    pass

    def _on_kinetics_window_closed(self):
        """当动力学窗口关闭时调用的槽函数（无参数）。"""
        self.is_kinetics_monitoring = False
        self.toggle_kinetics_button.setText(self.tr("Start Monitoring"))
        self.kinetics_interval_spinbox.setEnabled(True)
        if self.kinetics_window is not None:
            self.kinetics_baseline_value = self.kinetics_window.baseline_peak_wavelength
        self.kinetics_window = None
        # 恢复时间基到未启动状态，避免残留
        self.kinetics_start_time = None
        self.kinetics_last_sample_time = None

    def _get_main_peak_wavelength(self, y_data):
        if y_data is None:
            return None

        min_wl, max_wl = self.region_selector.getRegion()
        region_indices = np.where((self.wavelengths >= min_wl) & (self.wavelengths <= max_wl))[0]
        if len(region_indices) < 3:
            return None

        x_subset = self.wavelengths[region_indices]
        y_subset = y_data[region_indices]

        method_key = self.peak_method_combo.currentData() or 'highest_point'
        _, peak_wavelength = estimate_peak_position(x_subset, y_subset, method_key)
        return peak_wavelength

    def update_background_plot(self, wavelengths, spectrum):
        """Updates the display of the background spectrum chart."""
        if spectrum is not None:
            self.background_curve.setData(wavelengths, spectrum)
        else:
            self.background_curve.clear()

    def update_reference_plot(self, wavelengths, spectrum):
        """Updates the display of the reference spectrum chart."""
        if spectrum is not None:
            self.reference_curve.setData(wavelengths, spectrum)
        else:
            self.reference_curve.clear()

    def _update_plot_x_range(self):
        """
        此方法现在只控制结果谱图的X轴范围，并触发数据裁剪。
        """
        start_wl = self.display_range_start_spinbox.value()
        end_wl = self.display_range_end_spinbox.value()

        if start_wl >= end_wl:
            return

        self.result_plot.getViewBox().setLimits(xMin=start_wl, xMax=end_wl)
        self.result_plot.setXRange(start_wl, end_wl, padding=0)

        self._update_result_plot_with_crop()

    def _reset_display_range(self):
        """
        Resets the display range and view limits to the full range of the spectrometer.
        """
        min_wl, max_wl = self.controller.wavelengths[0], self.controller.wavelengths[-1]

        self.display_range_start_spinbox.blockSignals(True)
        self.display_range_end_spinbox.blockSignals(True)
        self.display_range_start_spinbox.setValue(min_wl)
        self.display_range_end_spinbox.setValue(max_wl)
        self.display_range_start_spinbox.blockSignals(False)
        self.display_range_end_spinbox.blockSignals(False)

        plots = [self.signal_plot, self.background_plot, self.reference_plot, self.result_plot]
        for plot in plots:
            plot.getViewBox().setLimits(xMin=None, xMax=None)
            plot.autoRange()

        self._update_plot_x_range()

        for item in self.popout_windows:
            win = item['window']
            plot_type = item['type']
            if plot_type in ['signal', 'background', 'reference', 'result']:
                win.update_view_and_limits(x_range=None, y_range=None)

    def start_realtime_noise_analysis(self):
        if not self.is_acquiring:
            QMessageBox.warning(self, self.tr("Warning"),
                                self.tr("Please start real-time acquisition first before analyzing noise."))
            return

        default_save_path = self.app_settings.get('default_save_path', os.path.expanduser("~"))
        output_folder = QFileDialog.getExistingDirectory(
            self, self.tr("Select Base Folder for Noise Analysis Results"), default_save_path)
        if not output_folder:
            return

        setup_dialog = RealTimeNoiseSetupDialog(self.controller, self)
        if setup_dialog.exec_() == QDialog.Accepted:
            num_spectra, interval = setup_dialog.get_settings()
            self._execute_noise_worker(num_spectra, output_folder, interval)

    def _execute_noise_worker(self, num_spectra, output_folder, interval):
        self.progress_dialog = QProgressDialog(self.tr("Acquiring data for noise analysis..."), self.tr("Abort"), 0,
                                               100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoClose(True)
        self.progress_dialog.show()

        self.noise_thread = QThread()
        self.noise_worker = RealTimeNoiseWorker(self.controller, num_spectra, output_folder, interval)
        self.noise_worker.moveToThread(self.noise_thread)

        self.noise_thread.started.connect(self.noise_worker.run)
        self.noise_worker.finished.connect(self._on_realtime_noise_finished)
        self.noise_worker.error.connect(self._on_realtime_noise_error)
        self.noise_worker.progress.connect(self.progress_dialog.setValue)
        self.progress_dialog.canceled.connect(self.noise_worker.stop)

        self.noise_worker.finished.connect(self.noise_thread.quit)
        self.noise_worker.finished.connect(self.noise_worker.deleteLater)
        self.noise_thread.finished.connect(self.noise_thread.deleteLater)

        self.noise_thread.start()

    def _on_realtime_noise_finished(self, folder_path, wavelengths, noise_spectrum, average_noise):
        self.progress_dialog.setValue(100)
        result_dialog = NoiseResultDialog(folder_path, wavelengths, noise_spectrum, average_noise, self)
        result_dialog.exec_()

    def _on_realtime_noise_error(self, error_message):
        self.progress_dialog.close()
        QMessageBox.critical(self, self.tr("Error"), self.tr(error_message))

    def _retranslate_ui(self):
        """重新翻译此控件内的所有UI文本。"""
        self.acq_box.toggle_button.setText(self.tr("Acquisition Control"))
        self.range_box.toggle_button.setText(self.tr("Display Range Control"))
        self.params_box.toggle_button.setText(self.tr("Parameters & Preprocessing"))
        self.analysis_box.toggle_button.setText(self.tr("Spectral Analysis"))
        self.kinetics_box.toggle_button.setText(self.tr("Kinetics Monitoring"))
        kinetics_form_layout = self.kinetics_box.content_area.widget().layout().itemAt(0).layout()
        kinetics_form_layout.labelForField(self.kinetics_interval_spinbox).setText(self.tr("Sampling Interval:"))

        self.data_op_box.toggle_button.setText(self.tr("Data Operations"))

        self.toggle_acq_button.setText(
            self.tr("Start Acquisition") if not self.is_acquiring else self.tr("Stop Acquisition"))
        self.capture_dark_button.setText(self.tr("Capture Background (Dark)"))
        self.capture_ref_button.setText(self.tr("Capture Reference (Ref)"))
        self.reset_range_button.setText(self.tr("Reset Display Range"))
        self.baseline_correction_button.setText(self.tr("Correct Current Baseline"))
        self.find_peaks_button.setText(self.tr("Find All Peaks"))
        self.find_main_peak_button.setText(self.tr("Find Main Resonance Peak"))
        self.set_baseline_button.setText(self.tr("Set Baseline from Current Peak"))
        self.toggle_kinetics_button.setText(
            self.tr("Start Monitoring") if not self.is_kinetics_monitoring else self.tr("Stop Monitoring"))
        self.save_all_button.setText(self.tr("Save All Spectra"))
        self.save_data_button.setText(self.tr("Save Result Spectrum"))
        self.load_data_button.setText(self.tr("Load Spectrum for Comparison"))
        self.back_button.setText(self.tr("← Back to Welcome Screen"))

        self.range_layout.labelForField(self.display_range_start_spinbox).setText(self.tr("Start Wavelength:"))
        self.range_layout.labelForField(self.display_range_end_spinbox).setText(self.tr("End Wavelength:"))

        self.params_layout.labelForField(self.integration_time_spinbox).setText(self.tr("Integration Time:"))
        self.params_layout.labelForField(self.smooth_method_combo).setText(self.tr("Smoothing Method:"))
        self.params_layout.labelForField(self.smoothing_window_spinbox).setText(self.tr("Smoothing Window:"))

        self.analysis_form_layout.labelForField(self.peak_method_combo).setText(self.tr("Main Peak Algorithm:"))
        self.analysis_form_layout.labelForField(self.peak_height_spinbox).setText(self.tr("Minimum Peak Height:"))
        current_method_key = self.peak_method_combo.currentData()
        for index, method_key in enumerate(PEAK_METHOD_KEYS):
            self.peak_method_combo.setItemText(index, self.tr(PEAK_METHOD_LABELS[method_key]))
        if current_method_key is not None:
            restored_index = self.peak_method_combo.findData(current_method_key)
            if restored_index != -1:
                self.peak_method_combo.setCurrentIndex(restored_index)

        self.range_layout_form.labelForField(self.range_start_spinbox).setText(self.tr("Start Position:"))
        self.range_layout_form.labelForField(self.range_end_spinbox).setText(self.tr("End Position:"))

        self.result_display_layout.labelForField(self.main_peak_wavelength_label).setText(
            self.tr("Peak Wavelength (nm):"))
        self.result_display_layout.labelForField(self.main_peak_intensity_label).setText(self.tr("Peak Intensity:"))

        self.range_group.setTitle(self.tr("Spectral Peak Find Range"))
        self.result_display_group.setTitle(self.tr("Analysis Results"))

        display_name = self.tr(self.mode_name)
        self.result_plot.setLabel('left', display_name)
        self.result_plot.setTitle(display_name, color='#90A4AE', size='12pt')
        self.result_title_label.setText(display_name)
