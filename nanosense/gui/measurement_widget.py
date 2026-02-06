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
                             QComboBox, QDialog, QMessageBox, QToolButton, QProgressDialog, QFileDialog,
                             QCheckBox)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal

import pyqtgraph as pg

from nanosense.algorithms.peak_analysis import (
    find_spectral_peaks,
    find_main_resonance_peak,
    calculate_fwhm,
    PEAK_METHOD_KEYS,
    PEAK_METHOD_LABELS,
    estimate_peak_position,
    calculate_sers_enhancement_factor,
)
from nanosense.algorithms.raman_database import (
    create_raman_database,
    search_raman_substances_by_peaks,
    get_raman_substance_info,
    get_all_raman_substances,
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
        
        # 连接平滑参数控件信号
        self.smooth_method_combo.currentTextChanged.connect(self._update_smoothing_params)
        self.smoothing_window_spinbox.valueChanged.connect(self._update_smoothing_params)
        
        # 初始化处理器的平滑参数
        self._update_smoothing_params()
        # 旧的 _update_plot_x_range() 已移除，现在由 analysis_range 统一管理

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
        scroll_area.setFixedWidth(420)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        panel_widget = QWidget()
        panel_widget.setObjectName("controlPanel")
        panel_layout = QVBoxLayout(panel_widget)
        panel_layout.setSpacing(8)
        panel_layout.setContentsMargins(10, 10, 10, 10)

        # --- 采集控制 ---
        self.acq_box = CollapsibleBox(self.tr("Acquisition Control"))
        acq_layout = QFormLayout()
        self.toggle_acq_button = QPushButton(self.tr("Start Acquisition"))
        self.toggle_acq_button.setCheckable(True)
        acq_layout.addRow(self.toggle_acq_button)
        self.capture_dark_button = QPushButton(self.tr("Capture Dark"))
        acq_layout.addRow(self.capture_dark_button)
        self.capture_ref_button = QPushButton(self.tr("Capture Ref"))
        acq_layout.addRow(self.capture_ref_button)
        
        # --- 拉曼专用控件 ---
        self.raman_group = QGroupBox(self.tr("Raman Settings"))
        raman_layout = QFormLayout(self.raman_group)
        
        # 带有快速选择按钮的激发波长
        wavelength_layout = QVBoxLayout()
        wavelength_input_layout = QHBoxLayout()
        self.excitation_wavelength_spinbox = QDoubleSpinBox()
        self.excitation_wavelength_spinbox.setRange(300.0, 1000.0)
        self.excitation_wavelength_spinbox.setDecimals(1)
        self.excitation_wavelength_spinbox.setValue(785.0)
        self.excitation_wavelength_spinbox.setSuffix(" nm")
        wavelength_input_layout.addWidget(self.excitation_wavelength_spinbox)
        
        # 常用波长的快速选择按钮
        wavelength_buttons_layout = QHBoxLayout()
        common_wavelengths = [532.0, 633.0, 785.0]
        self.wavelength_buttons = []
        for wl in common_wavelengths:
            button = QPushButton(f"{int(wl)}")
            button.setFixedWidth(60)
            button.clicked.connect(lambda checked, w=wl: self.excitation_wavelength_spinbox.setValue(w))
            self.wavelength_buttons.append(button)
            wavelength_buttons_layout.addWidget(button)
        wavelength_buttons_layout.addStretch()
        
        wavelength_layout.addLayout(wavelength_input_layout)
        wavelength_layout.addLayout(wavelength_buttons_layout)
        raman_layout.addRow(self.tr("Excitation Wavelength:"), wavelength_layout)
        
        # 激光功率控制
        self.laser_power_spinbox = QDoubleSpinBox()
        self.laser_power_spinbox.setRange(0.0, 100.0)
        self.laser_power_spinbox.setDecimals(1)
        self.laser_power_spinbox.setValue(50.0)
        self.laser_power_spinbox.setSuffix(" %")
        raman_layout.addRow(self.tr("Laser Power:"), self.laser_power_spinbox)
        
        # 带有安全警告的激光开关按钮
        self.laser_button = QPushButton(self.tr("Turn Laser ON"))
        self.laser_button.setCheckable(True)
        self.laser_button.setStyleSheet("QPushButton:checked { background-color: #ef4444; color: white; }")
        raman_layout.addRow(self.tr("Laser Control:"), self.laser_button)
        
        # 平均扫描次数
        self.scans_to_average_spinbox = QSpinBox()
        self.scans_to_average_spinbox.setRange(1, 100)
        self.scans_to_average_spinbox.setValue(1)
        raman_layout.addRow(self.tr("Scans to Average:"), self.scans_to_average_spinbox)
        
        acq_layout.addWidget(self.raman_group)
        self.acq_box.setContentLayout(acq_layout)
        panel_layout.addWidget(self.acq_box)

        # --- 显示范围控制已移除，统一到参数与预处理中的分析范围 ---

        # --- 参数与预处理 ---
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
        
        # 拉曼专用预处理控件
        self.raman_preprocessing_group = QGroupBox(self.tr("Raman Preprocessing"))
        raman_preprocessing_layout = QFormLayout(self.raman_preprocessing_group)
        
        # 荧光背景扣除
        self.fluorescence_subtract_checkbox = QCheckBox(self.tr("Fluorescence Background Subtraction"))
        self.fluorescence_subtract_checkbox.setChecked(False)
        raman_preprocessing_layout.addRow(self.fluorescence_subtract_checkbox)
        
        # 瑞利散射去除
        self.rayleigh_remove_checkbox = QCheckBox(self.tr("Rayleigh Scattering Removal"))
        self.rayleigh_remove_checkbox.setChecked(False)
        raman_preprocessing_layout.addRow(self.rayleigh_remove_checkbox)
        
        # 瑞利截止波数
        self.rayleigh_cutoff_spinbox = QDoubleSpinBox()
        self.rayleigh_cutoff_spinbox.setRange(0, 1000)
        self.rayleigh_cutoff_spinbox.setDecimals(0)
        self.rayleigh_cutoff_spinbox.setValue(200)
        self.rayleigh_cutoff_spinbox.setSuffix(" cm⁻¹")
        raman_preprocessing_layout.addRow(self.tr("Rayleigh Cutoff:"), self.rayleigh_cutoff_spinbox)
        
        # 归一化
        self.normalization_combo = QComboBox()
        self.normalization_combo.addItems([
            self.tr("No Normalization"),
            self.tr("Peak Height Normalization"),
            self.tr("Area Normalization"),
            self.tr("Standard Normal Variate (SNV)")
        ])
        raman_preprocessing_layout.addRow(self.tr("Normalization:"), self.normalization_combo)
        
        self.params_layout.addRow(self.tr("Integration Time:"), self.integration_time_spinbox)
        self.params_layout.addRow(self.tr("Smoothing Method:"), self.smooth_method_combo)
        self.params_layout.addRow(self.tr("Smoothing Window:"), self.smoothing_window_spinbox)
        
        # 基线校正控件
        self.baseline_group = QGroupBox(self.tr("Baseline Correction"))
        baseline_layout = QFormLayout(self.baseline_group)
        
        # 启用基线校正
        self.baseline_enable_checkbox = QCheckBox(self.tr("Enable Baseline Correction"))
        self.baseline_enable_checkbox.setChecked(False)
        baseline_layout.addRow(self.baseline_enable_checkbox)
        
        # 算法选择
        self.baseline_algorithm_combo = QComboBox()
        self.baseline_algorithm_combo.addItems(["ALS"])  # 未来可扩展ArPLS, Polynomial
        baseline_layout.addRow(self.tr("Algorithm:"), self.baseline_algorithm_combo)
        
        # Lambda 参数 (平滑度)
        self.baseline_lambda_spinbox = QDoubleSpinBox()
        self.baseline_lambda_spinbox.setRange(1e2, 1e9)
        self.baseline_lambda_spinbox.setValue(1e6)
        self.baseline_lambda_spinbox.setDecimals(0)
        self.baseline_lambda_spinbox.setSingleStep(1e5)
        self.baseline_lambda_spinbox.setToolTip(
            self.tr("Larger values = smoother baseline (typical: 1e5 - 1e7)")
        )
        baseline_layout.addRow(self.tr("Lambda (平滑度):"), self.baseline_lambda_spinbox)
        
        # p 参数 (不对称性)
        self.baseline_p_spinbox = QDoubleSpinBox()
        self.baseline_p_spinbox.setRange(0.001, 0.1)
        self.baseline_p_spinbox.setValue(0.01)
        self.baseline_p_spinbox.setDecimals(3)
        self.baseline_p_spinbox.setSingleStep(0.001)
        self.baseline_p_spinbox.setToolTip(
            self.tr("Asymmetry parameter (typical: 0.001 - 0.1)")
        )
        baseline_layout.addRow(self.tr("p (不对称性):"), self.baseline_p_spinbox)
        
        # 迭代次数
        self.baseline_niter_spinbox = QSpinBox()
        self.baseline_niter_spinbox.setRange(1, 50)
        self.baseline_niter_spinbox.setValue(10)
        self.baseline_niter_spinbox.setToolTip(
            self.tr("Number of iterations (typical: 10-20)")
        )
        baseline_layout.addRow(self.tr("Iterations:"), self.baseline_niter_spinbox)
        
        self.params_layout.addRow(self.baseline_group)
        self.params_layout.addRow(self.baseline_correction_button)
        self.params_layout.addRow(self.raman_preprocessing_group)
        
        # 统一的分析范围设置
        self.analysis_range_group = QGroupBox(self.tr("Analysis Range"))
        analysis_range_layout = QFormLayout(self.analysis_range_group)
        
        self.analysis_start_spinbox = QDoubleSpinBox()
        self.analysis_start_spinbox.setRange(200.0, 1200.0)
        self.analysis_start_spinbox.setValue(500.0)
        self.analysis_start_spinbox.setSuffix(" nm")
        self.analysis_start_spinbox.setDecimals(1)
        self.analysis_start_spinbox.setToolTip(
            self.tr("Start wavelength for display, peak finding, and preprocessing")
        )
        
        self.analysis_end_spinbox = QDoubleSpinBox()
        self.analysis_end_spinbox.setRange(200.0, 1200.0)
        self.analysis_end_spinbox.setValue(900.0)
        self.analysis_end_spinbox.setSuffix(" nm")
        self.analysis_end_spinbox.setDecimals(1)
        self.analysis_end_spinbox.setToolTip(
            self.tr("End wavelength for display, peak finding, and preprocessing")
        )
        
        analysis_range_layout.addRow(self.tr("Start:"), self.analysis_start_spinbox)
        analysis_range_layout.addRow(self.tr("End:"), self.analysis_end_spinbox)
        self.params_layout.addRow(self.analysis_range_group)
        self.params_box.setContentLayout(self.params_layout)
        panel_layout.addWidget(self.params_box)

        # --- 光谱分析 ---
        self.analysis_box = CollapsibleBox(self.tr("Spectral Analysis"))
        analysis_outer_layout = QVBoxLayout()
        analysis_outer_layout.setSpacing(10)
        self.analysis_form_layout = QFormLayout()
        self.peak_method_combo = QComboBox()
        # 显式添加翻译标记，确保Qt Linguist能检测到这些字符串
        peak_labels = {
            'highest_point': self.tr('Highest Point'),
            'centroid': self.tr('Centroid'),
            'gaussian_fit': self.tr('Gaussian Fit'),
            'parabolic': self.tr('Parabolic Interpolation'),
            'wavelet': self.tr('Wavelet Transform'),
            'threshold': self.tr('Threshold-based'),
        }
        for method_key in PEAK_METHOD_KEYS:
            label = peak_labels[method_key]
            self.peak_method_combo.addItem(label, userData=method_key)
        self.peak_height_spinbox = QDoubleSpinBox()
        self.peak_height_spinbox.setDecimals(4)
        self.peak_height_spinbox.setRange(-1000, 10000)
        self.peak_height_spinbox.setValue(0.1)
        self.find_peaks_button = QPushButton(self.tr("Find All Peaks"))
        self.find_main_peak_button = QPushButton(self.tr("Find Main Resonance Peak"))
        self.analysis_form_layout.addRow(self.tr("Main Peak Algorithm:"), self.peak_method_combo)
        self.analysis_form_layout.addRow(self.tr("Minimum Peak Height:"), self.peak_height_spinbox)
        analysis_outer_layout.addLayout(self.analysis_form_layout)
        # --- 寻峰范围已移除，统一到参数与预处理中的分析范围 ---
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
        
        # 波长/波数切换按钮
        self.wavenumber_toggle = QPushButton(self.tr("Switch to Wavenumber"))
        self.wavenumber_toggle.setCheckable(True)
        analysis_outer_layout.addWidget(self.wavenumber_toggle)
        
        # 初始化processor的分析范围
        self.processor.set_analysis_range(
            self.analysis_start_spinbox.value(),
            self.analysis_end_spinbox.value()
        )
        analysis_outer_layout.addWidget(self.result_display_group)
        self.analysis_box.setContentLayout(analysis_outer_layout)
        panel_layout.addWidget(self.analysis_box)

        # --- SERS分析 ---        
        self.sers_box = CollapsibleBox(self.tr("SERS Analysis"))
        sers_layout = QVBoxLayout()
        sers_layout.setSpacing(10)
        
        # SERS分析表单
        sers_form_layout = QFormLayout()
        
        # 参考物质选择
        self.reference_material_combo = QComboBox()
        self.reference_material_combo.addItems([
            self.tr("Rhodamine 6G"),
            self.tr("Crystal Violet"),
            self.tr("Phenylalanine"),
            self.tr("Custom")
        ])
        sers_form_layout.addRow(self.tr("Reference Material:"), self.reference_material_combo)
        
        # SERS基底选择
        self.substrate_combo = QComboBox()
        self.substrate_combo.addItems([
            self.tr("Gold Nanoparticles"),
            self.tr("Silver Nanoparticles"),
            self.tr("Gold Nanostars"),
            self.tr("Custom")
        ])
        sers_form_layout.addRow(self.tr("SERS Substrate:"), self.substrate_combo)
        
        # 浓度输入
        self.sers_concentration_spinbox = QDoubleSpinBox()
        self.sers_concentration_spinbox.setRange(1e-12, 1.0)
        self.sers_concentration_spinbox.setDecimals(12)
        self.sers_concentration_spinbox.setValue(1e-6)
        self.sers_concentration_spinbox.setSuffix(" M")
        sers_form_layout.addRow(self.tr("SERS Concentration:"), self.sers_concentration_spinbox)
        
        self.reference_concentration_spinbox = QDoubleSpinBox()
        self.reference_concentration_spinbox.setRange(1e-12, 1.0)
        self.reference_concentration_spinbox.setDecimals(12)
        self.reference_concentration_spinbox.setValue(1e-4)
        self.reference_concentration_spinbox.setSuffix(" M")
        sers_form_layout.addRow(self.tr("Reference Concentration:"), self.reference_concentration_spinbox)
        
        # 计算方法
        self.sers_method_combo = QComboBox()
        self.sers_method_combo.addItems([
            self.tr("Peak Height"),
            self.tr("Area")
        ])
        sers_form_layout.addRow(self.tr("Calculation Method:"), self.sers_method_combo)
        
        sers_layout.addLayout(sers_form_layout)
        
        # 分析按钮
        self.calculate_sers_button = QPushButton(self.tr("Calculate SERS Enhancement Factor"))
        sers_layout.addWidget(self.calculate_sers_button)
        
        # SERS结果显示
        self.sers_result_group = QGroupBox(self.tr("SERS Analysis Results"))
        self.sers_result_layout = QFormLayout(self.sers_result_group)
        self.sers_enhancement_label = QLabel("N/A")
        self.sers_enhancement_label.setStyleSheet("font-weight: bold;")
        self.sers_result_layout.addRow(self.tr("Enhancement Factor:"), self.sers_enhancement_label)
        sers_layout.addWidget(self.sers_result_group)
        
        self.sers_box.setContentLayout(sers_layout)
        panel_layout.addWidget(self.sers_box)

        # --- 拉曼数据库 ---        
        self.database_box = CollapsibleBox(self.tr("Raman Database"))
        database_layout = QVBoxLayout()
        database_layout.setSpacing(10)
        
        # 数据库搜索表单
        database_form_layout = QFormLayout()
        
        # 物质搜索
        self.substance_search_combo = QComboBox()
        # 初始化时将在set_mode中填充
        database_form_layout.addRow(self.tr("Search Substance:"), self.substance_search_combo)
        
        # 峰值范围搜索
        self.peak_range_start_spinbox = QDoubleSpinBox()
        self.peak_range_start_spinbox.setRange(0, 4000)
        self.peak_range_start_spinbox.setDecimals(0)
        self.peak_range_start_spinbox.setValue(400)
        self.peak_range_start_spinbox.setSuffix(" cm⁻¹")
        database_form_layout.addRow(self.tr("Peak Range Start:"), self.peak_range_start_spinbox)
        
        self.peak_range_end_spinbox = QDoubleSpinBox()
        self.peak_range_end_spinbox.setRange(0, 4000)
        self.peak_range_end_spinbox.setDecimals(0)
        self.peak_range_end_spinbox.setValue(1800)
        self.peak_range_end_spinbox.setSuffix(" cm⁻¹")
        database_form_layout.addRow(self.tr("Peak Range End:"), self.peak_range_end_spinbox)
        
        # 匹配容差
        self.database_tolerance_spinbox = QDoubleSpinBox()
        self.database_tolerance_spinbox.setRange(0.1, 20.0)
        self.database_tolerance_spinbox.setDecimals(1)
        self.database_tolerance_spinbox.setValue(5.0)
        self.database_tolerance_spinbox.setSuffix(" cm⁻¹")
        database_form_layout.addRow(self.tr("Match Tolerance:"), self.database_tolerance_spinbox)
        
        database_layout.addLayout(database_form_layout)
        
        # 数据库按钮
        database_buttons_layout = QHBoxLayout()
        self.search_substance_button = QPushButton(self.tr("Search Substance"))
        self.match_peaks_button = QPushButton(self.tr("Match Peaks"))
        self.view_database_button = QPushButton(self.tr("View Database"))
        database_buttons_layout.addWidget(self.search_substance_button)
        database_buttons_layout.addWidget(self.match_peaks_button)
        database_buttons_layout.addWidget(self.view_database_button)
        database_layout.addLayout(database_buttons_layout)
        
        # 数据库结果显示
        self.database_result_group = QGroupBox(self.tr("Database Results"))
        self.database_result_layout = QFormLayout(self.database_result_group)
        self.database_substance_label = QLabel("N/A")
        self.database_peaks_label = QLabel("N/A")
        self.database_description_label = QLabel("N/A")
        self.database_match_label = QLabel("N/A")
        
        self.database_result_layout.addRow(self.tr("Substance:"), self.database_substance_label)
        self.database_result_layout.addRow(self.tr("Characteristic Peaks:"), self.database_peaks_label)
        self.database_result_layout.addRow(self.tr("Description:"), self.database_description_label)
        self.database_result_layout.addRow(self.tr("Match Score:"), self.database_match_label)
        database_layout.addWidget(self.database_result_group)
        
        self.database_box.setContentLayout(database_layout)
        panel_layout.addWidget(self.database_box)

        # --- 动力学监测与数据操作 ---
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

        # --- 最终设置 ---
        self.acq_box.set_expanded(True)
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
            """创建带标题和弹出按钮的图表容器"""
            container = QWidget()
            container.setObjectName("plotCard")
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            header_widget = QWidget()
            header_widget.setObjectName("plotHeader")
            header_layout = QHBoxLayout(header_widget)
            header_layout.setContentsMargins(5, 2, 5, 2)

            title_label = QLabel(self.tr(title_key))
            title_label.setStyleSheet("color: #90A4AE; font-size: 12pt;")

            popout_button = QToolButton()
            # 根据当前主题选择合适的图标
            self._update_popout_button_icon(popout_button)
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
        # 性能优化：导入优化工具
        from ..utils.plot_utils import optimize_plot_performance, InteractivePlotEnhancer
        
        self.signal_plot = pg.PlotWidget()
        optimize_plot_performance(self.signal_plot)  # 启用降采样以获得更好的性能
        self.signal_enhancer = InteractivePlotEnhancer(self.signal_plot)
        self.signal_plot.addLegend()
        self.signal_enhancer.setup_legend_toggle()  # 添加图例后调用，确保图例位于右上角
        self.signal_curve = self.signal_plot.plot(pen=pg.mkPen('#1f77b4', width=2), name='Signal')  # 蓝色信号光谱
        
        self.background_plot = pg.PlotWidget()
        optimize_plot_performance(self.background_plot)  # 启用降采样以获得更好的性能
        self.background_enhancer = InteractivePlotEnhancer(self.background_plot)
        self.background_plot.addLegend()
        self.background_enhancer.setup_legend_toggle()  # 添加图例后调用，确保图例位于右上角
        self.background_curve = self.background_plot.plot(pen=pg.mkPen('#ff7f0e', width=2), name='Background')  # 橙色背景光谱
        
        self.reference_plot = pg.PlotWidget()
        optimize_plot_performance(self.reference_plot)  # 启用降采样以获得更好的性能
        self.reference_enhancer = InteractivePlotEnhancer(self.reference_plot)
        self.reference_plot.addLegend()
        self.reference_enhancer.setup_legend_toggle()  # 添加图例后调用，确保图例位于右上角
        self.reference_curve = self.reference_plot.plot(pen=pg.mkPen('#2ca02c', width=2), name='Reference')  # 绿色参考光谱
        
        self.result_plot = pg.PlotWidget()
        optimize_plot_performance(self.result_plot)  # 启用降采样以获得更好的性能
        self.result_enhancer = InteractivePlotEnhancer(self.result_plot) # Keep ref to add legend later? or add now
        self.result_plot.addLegend()
        self.result_enhancer.setup_legend_toggle() # Refresh toggle after adding legend
        self.result_curve = self.result_plot.plot(pen=pg.mkPen('#d62728', width=2), name='Result')  # 红色结果光谱

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

        # 蛍色寻峰范围选择框已移除，使用统一的分析范围控件

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

        min_wl = self.analysis_start_spinbox.value()
        max_wl = self.analysis_end_spinbox.value()
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

        min_wl = self.analysis_start_spinbox.value()
        max_wl = self.analysis_end_spinbox.value()
        region_indices = np.where((x_data >= min_wl) & (x_data <= max_wl))[0]
        if len(region_indices) < 3:
            print(self.tr("Too few data points in the selected region."))
            self.main_peak_marker.clear()
            return

        start_index = region_indices[0]
        x_subset = x_data[region_indices]
        y_subset = y_data[region_indices]

        # 获取选择的寻峰算法
        method_key = self.peak_method_combo.currentData() or 'highest_point'
        
        # 使用estimate_peak_position函数支持所有寻峰算法
        main_peak_index_subset, peak_wavelength = estimate_peak_position(
            x_subset, y_subset, method=method_key
        )

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

        # 连接统一的分析范围信号
        self.analysis_start_spinbox.valueChanged.connect(self._on_analysis_range_changed)
        self.analysis_end_spinbox.valueChanged.connect(self._on_analysis_range_changed)
        
        # 峰分析和数据保存
        self.find_peaks_button.clicked.connect(self._find_all_peaks)
        self.find_main_peak_button.clicked.connect(self._find_main_resonance_peak)
        self.save_data_button.clicked.connect(self._save_result_spectrum)
        self.load_data_button.clicked.connect(self._load_spectrum_data_for_comparison)
        self.set_baseline_button.clicked.connect(self._set_kinetics_baseline_from_current_peak)
        self.toggle_kinetics_button.clicked.connect(self._toggle_kinetics_window)
        # 波长/波数切换
        self.wavenumber_toggle.clicked.connect(self._toggle_wavelength_wavenumber)
        self.save_all_button.clicked.connect(self._save_all_spectra)
        
        # 连接基线校正参数信号
        self.baseline_enable_checkbox.stateChanged.connect(self._update_baseline_params)
        self.baseline_algorithm_combo.currentTextChanged.connect(self._update_baseline_params)
        self.baseline_lambda_spinbox.valueChanged.connect(self._update_baseline_params)
        self.baseline_p_spinbox.valueChanged.connect(self._update_baseline_params)
        self.baseline_niter_spinbox.valueChanged.connect(self._update_baseline_params)
        
        # SERS分析
        self.calculate_sers_button.clicked.connect(self._calculate_sers_enhancement)
        
        # 拉曼数据库
        self.search_substance_button.clicked.connect(self._search_substance)
        self.match_peaks_button.clicked.connect(self._match_peaks_with_database)
        self.view_database_button.clicked.connect(self._view_database)
        
        # 激光控制
        self.laser_button.clicked.connect(self._on_laser_button_clicked)
        self.excitation_wavelength_spinbox.valueChanged.connect(self._on_excitation_wavelength_changed)
        self.laser_power_spinbox.valueChanged.connect(self._on_laser_power_changed)

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
            # 平滑参数
            'smoothing_method': self.smooth_method_combo.currentText() if hasattr(self, 'smooth_method_combo') else None,
            'smoothing_window': int(self.smoothing_window_spinbox.value()) if hasattr(self, 'smoothing_window_spinbox') else None,
            'smoothing_order': int(self.poly_order_spinbox.value()) if hasattr(self, 'poly_order_spinbox') else None,
            # 基线校正参数
            'baseline_enabled': self.baseline_enabled_checkbox.isChecked() if hasattr(self, 'baseline_enabled_checkbox') else None,
            'baseline_algorithm': self.baseline_algorithm_combo.currentText() if hasattr(self, 'baseline_algorithm_combo') else None,
            'baseline_lambda': float(self.baseline_lambda_spinbox.value()) if hasattr(self, 'baseline_lambda_spinbox') else None,
            'baseline_p': float(self.baseline_p_spinbox.value()) if hasattr(self, 'baseline_p_spinbox') else None,
            'baseline_niter': int(self.baseline_niter_spinbox.value()) if hasattr(self, 'baseline_niter_spinbox') else None,
            # 寻峰参数
            'peak_method': self.peak_method_combo.currentData() if hasattr(self, 'peak_method_combo') and self.peak_method_combo.currentData() else (self.peak_method_combo.currentText() if hasattr(self, 'peak_method_combo') else None),
            'peak_height_threshold': float(self.peak_height_spinbox.value()) if hasattr(self, 'peak_height_spinbox') else None,
            # 分析范围
            'analysis_start_nm': float(self.analysis_start_spinbox.value()) if hasattr(self, 'analysis_start_spinbox') else None,
            'analysis_end_nm': float(self.analysis_end_spinbox.value()) if hasattr(self, 'analysis_end_spinbox') else None,
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
        min_wl = self.analysis_start_spinbox.value()
        max_wl = self.analysis_end_spinbox.value()
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
                    
                    # 创建裁剪mask用于信号/背景/参考光谱
                    wl_mask = (self.wavelengths >= min_wl) & (self.wavelengths <= max_wl)
                    wavelengths_cropped = self.wavelengths[wl_mask]

                    # 保存结果光谱（使用裁剪数据）
                    self.db_manager.save_spectrum(
                        experiment_id,
                        f"Result_{self.mode_name}",
                        timestamp,
                        x_data_sliced,
                        y_data_sliced,
                        instrument_info=instrument_info,
                        processing_info=self._build_processing_metadata('Result'),
                    )
                    # 保存信号光谱（裁剪到分析范围）
                    if self.processor.latest_signal_spectrum is not None:
                        self.db_manager.save_spectrum(
                            experiment_id,
                            "Signal",
                            timestamp,
                            wavelengths_cropped,
                            self.processor.latest_signal_spectrum[wl_mask],
                            instrument_info=instrument_info,
                            processing_info=self._build_processing_metadata('Signal'),
                        )
                    # 保存背景光谱（裁剪到分析范围）
                    if self.processor.background_spectrum is not None:
                        self.db_manager.save_spectrum(
                            experiment_id,
                            "Background",
                            timestamp,
                            wavelengths_cropped,
                            self.processor.background_spectrum[wl_mask],
                            instrument_info=instrument_info,
                            processing_info=self._build_processing_metadata('Background'),
                        )
                    # 保存参考光谱（裁剪到分析范围）
                    if self.processor.reference_spectrum is not None:
                        self.db_manager.save_spectrum(
                            experiment_id,
                            "Reference",
                            timestamp,
                            wavelengths_cropped,
                            self.processor.reference_spectrum[wl_mask],
                            instrument_info=instrument_info,
                            processing_info=self._build_processing_metadata('Reference'),
                        )
                    print(f"光谱数据已同步保存到数据库，实验ID: {experiment_id}，范围: {min_wl}-{max_wl} nm")
                    QMessageBox.information(self, self.tr("Database Sync"),
                                            self.tr("Spectrum data has been successfully saved to file and database.\n"
                                                    "Experiment ID: {0}\nWavelength Range: {1}-{2} nm").format(experiment_id, min_wl, max_wl))
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

        min_wl = self.analysis_start_spinbox.value()
        max_wl = self.analysis_end_spinbox.value()
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

    def _on_analysis_range_changed(self):
        """分析范围改变时更新processor和UI"""
        start = self.analysis_start_spinbox.value()
        end = self.analysis_end_spinbox.value()
        
        if start >= end:
            return  # 无效范围
        
        # 通知processor更新分析范围（会触发重新处理）
        self.processor.set_analysis_range(start, end)

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

        if self.mode_name in ["Reflectance", "Absorbance", "Transmission", "Raman"]:
            self.capture_ref_button.show()
            self.reference_plot.show()
        else:
            self.capture_ref_button.hide()
            self.reference_plot.hide()
        
        # 显示/隐藏拉曼专用控件
        if hasattr(self, 'raman_group'):
            if self.mode_name == "Raman":
                self.raman_group.setVisible(True)
            else:
                self.raman_group.setVisible(False)
        
        # 显示/隐藏拉曼预处理控件
        if hasattr(self, 'raman_preprocessing_group'):
            if self.mode_name == "Raman":
                self.raman_preprocessing_group.setVisible(True)
            else:
                self.raman_preprocessing_group.setVisible(False)
        
        # 显示/隐藏波数切换按钮（仅拉曼模式）
        if hasattr(self, 'wavenumber_toggle'):
            if self.mode_name == "Raman":
                self.wavenumber_toggle.setVisible(True)
            else:
                self.wavenumber_toggle.setVisible(False)
        
        # 显示/隐藏SERS分析控件
        if hasattr(self, 'sers_box'):
            if self.mode_name == "Raman":
                self.sers_box.show()
            else:
                self.sers_box.hide()
        
        # 显示/隐藏拉曼数据库控件
        if hasattr(self, 'database_box'):
            if self.mode_name == "Raman":
                self.database_box.show()
                # 填充物质搜索下拉菜单
                if hasattr(self, 'substance_search_combo'):
                    substances = get_all_raman_substances()
                    self.substance_search_combo.clear()
                    self.substance_search_combo.addItems(substances)
            else:
                self.database_box.hide()

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
                        
                        # 裁剪到分析范围，避免发送范围外的原始信号值
                        analysis_start = self.analysis_start_spinbox.value()
                        analysis_end = self.analysis_end_spinbox.value()
                        
                        # 创建分析范围内的数据
                        mask = (self.full_result_x >= analysis_start) & (self.full_result_x <= analysis_end)
                        cropped_x = self.full_result_x[mask]
                        cropped_y = self.full_result_y[mask]

                        data_package = {
                            'result_x': cropped_x,
                            'result_y': cropped_y,
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
    
    def _update_smoothing_params(self):
        """当平滑参数改变时更新处理器。"""
        method = self.smooth_method_combo.currentText()
        window = self.smoothing_window_spinbox.value()
        # 确保窗口大小是奇数
        if window % 2 == 0:
            window += 1
            self.smoothing_window_spinbox.setValue(window)
        self.processor.set_smoothing_params(method, window)
    
    def _update_baseline_params(self):
        """更新处理器的基线校正参数。"""
        enabled = self.baseline_enable_checkbox.isChecked()
        algorithm = self.baseline_algorithm_combo.currentText()
        lam = self.baseline_lambda_spinbox.value()
        p = self.baseline_p_spinbox.value()
        niter = self.baseline_niter_spinbox.value()
        
        # 调用处理器的设置方法
        self.processor.set_baseline_params(enabled, algorithm, lam, p, niter)

    def _update_result_plot_with_crop(self):
        """
        根据显示范围裁剪完整结果光谱并更新绘图。
        """
        if self.full_result_y is None:
            self.result_curve.clear()
            return

        start_wl = self.analysis_start_spinbox.value()
        end_wl = self.analysis_end_spinbox.value()

        mask = (self.full_result_x >= start_wl) & (self.full_result_x <= end_wl)
        x_cropped = self.full_result_x[mask]
        y_cropped = self.full_result_y[mask]

        # 如果在拉曼模式下，应用拉曼预处理
        if self.mode_name == "Raman":
            from nanosense.algorithms.preprocessing import (
                remove_rayleigh_scattering,
                fluorescence_background_subtraction,
                normalize_spectrum
            )
            
            # 应用瑞利散射去除
            if self.rayleigh_remove_checkbox.isChecked():
                excitation_wavelength = self.excitation_wavelength_spinbox.value()
                cutoff_wavenumber = self.rayleigh_cutoff_spinbox.value()
                y_cropped = remove_rayleigh_scattering(
                    x_cropped, 
                    y_cropped, 
                    excitation_wavelength, 
                    cutoff_wavenumber
                )
            
            # 应用荧光背景扣除
            if self.fluorescence_subtract_checkbox.isChecked():
                y_cropped = fluorescence_background_subtraction(y_cropped)
            
            # 应用归一化
            normalization_method = self.normalization_combo.currentText()
            norm_method_map = {
                "No Normalization": "none",
                "Peak Height Normalization": "peak_height",
                "Area Normalization": "area",
                "Standard Normal Variate (SNV)": "snv"
            }
            norm_method = norm_method_map.get(normalization_method, "none")
            y_cropped = normalize_spectrum(y_cropped, norm_method)

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
            parent_window = getattr(self, 'main_window', None)
            self.kinetics_window = KineticsWindow(parent=parent_window)
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

        min_wl = self.analysis_start_spinbox.value()
        max_wl = self.analysis_end_spinbox.value()
        region_indices = np.where((self.wavelengths >= min_wl) & (self.wavelengths <= max_wl))[0]
        if len(region_indices) < 3:
            return None

        x_subset = self.wavelengths[region_indices]
        y_subset = y_data[region_indices]

        method_key = self.peak_method_combo.currentData() or 'highest_point'
        _, peak_wavelength = estimate_peak_position(x_subset, y_subset, method_key)
        return peak_wavelength

    def update_background_plot(self, wavelengths, spectrum):
        """更新背景光谱图表的显示。"""
        if spectrum is not None:
            self.background_curve.setData(wavelengths, spectrum)
        else:
            self.background_curve.clear()

    def update_reference_plot(self, wavelengths, spectrum):
        """更新参考光谱图表的显示。"""
        if spectrum is not None:
            self.reference_curve.setData(wavelengths, spectrum)
        else:
            self.reference_curve.clear()


        for item in self.popout_windows:
            win = item['window']
            plot_type = item['type']
            if plot_type in ['signal', 'background', 'reference', 'result']:
                win.update_view_and_limits(x_range=None, y_range=None)

    def _calculate_sers_enhancement(self):
        """
        计算SERS增强因子
        """
        if self.mode_name != "Raman":
            QMessageBox.warning(self, self.tr("Warning"), self.tr("SERS analysis is only available in Raman mode"))
            return
        
        if self.full_result_y is None:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("No spectrum data available"))
            return
        
        # 获取SERS和参考光谱数据
        sers_intensities = self.full_result_y
        
        # 检查参考光谱是否可用
        if self.processor.reference_spectrum is None:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("No reference spectrum available. Please capture a reference spectrum first."))
            return
        
        reference_intensities = self.processor.reference_spectrum
        
        # 获取浓度值
        sers_concentration = self.sers_concentration_spinbox.value()
        reference_concentration = self.reference_concentration_spinbox.value()
        
        # 获取计算方法
        method = self.sers_method_combo.currentText()
        method_key = 'peak_height' if method == self.tr("Peak Height") else 'area'
        
        # 计算增强因子
        enhancement_factor = calculate_sers_enhancement_factor(
            sers_intensities,
            reference_intensities,
            sers_concentration,
            reference_concentration,
            method=method_key
        )
        
        if enhancement_factor is not None:
            # 显示结果
            self.sers_enhancement_label.setText(f"{enhancement_factor:.2e}")
            print(self.tr("Calculated SERS enhancement factor: {0:.2e}").format(enhancement_factor))
        else:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Failed to calculate SERS enhancement factor"))

    def _search_substance(self):
        """
        搜索指定物质的拉曼特征峰
        """
        substance_name = self.substance_search_combo.currentText()
        if not substance_name:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("Please select a substance"))
            return
        
        # 获取物质信息
        substance_info = get_raman_substance_info(substance_name)
        if substance_info:
            # 显示物质信息
            self.database_substance_label.setText(substance_name)
            peaks_str = ', '.join([f"{peak}" for peak in substance_info["peaks"]])
            self.database_peaks_label.setText(peaks_str)
            self.database_description_label.setText(substance_info["description"])
            self.database_match_label.setText("N/A")
            print(self.tr("Found substance: {0}").format(substance_name))
        else:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Substance not found in database"))

    def _match_peaks_with_database(self):
        """
        将测量的峰与数据库中的物质匹配
        """
        if self.mode_name != "Raman":
            QMessageBox.warning(self, self.tr("Warning"), self.tr("Peak matching is only available in Raman mode"))
            return
        
        if self.full_result_y is None:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("No spectrum data available"))
            return
        
        # 检查是否在波数模式
        if not self.wavenumber_toggle.isChecked():
            QMessageBox.warning(self, self.tr("Warning"), self.tr("Please switch to wavenumber mode first"))
            return
        
        # 获取峰位数据
        if hasattr(self, 'peak_markers'):
            peaks = self.peak_markers.getData()
            if peaks:
                peak_wavenumbers = peaks[0]
                if len(peak_wavenumbers) == 0:
                    QMessageBox.warning(self, self.tr("Warning"), self.tr("No peaks detected. Please find peaks first"))
                    return
                
                # 获取匹配容差
                tolerance = self.database_tolerance_spinbox.value()
                
                # 匹配峰位
                matches = search_raman_substances_by_peaks(peak_wavenumbers, tolerance)
                
                if matches:
                    # 显示最佳匹配
                    best_match = matches[0]
                    self.database_substance_label.setText(best_match["substance"])
                    peaks_str = ', '.join([f"{peak}" for peak in best_match["reference_peaks"]])
                    self.database_peaks_label.setText(peaks_str)
                    self.database_description_label.setText(best_match["description"])
                    self.database_match_label.setText(f"{best_match['match_score']:.2f}")
                    
                    print(self.tr("Best match: {0} (Score: {1:.2f})").format(best_match["substance"], best_match["match_score"]))
                else:
                    QMessageBox.information(self, self.tr("Information"), self.tr("No matches found in database"))
            else:
                QMessageBox.warning(self, self.tr("Warning"), self.tr("No peaks detected. Please find peaks first"))
        else:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Peak markers not available"))

    def _view_database(self):
        """
        查看数据库中的所有物质
        """
        substances = get_all_raman_substances()
        if substances:
            # 创建简单的数据库查看对话框
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QListWidget, QLabel, QPushButton
            
            dialog = QDialog(self)
            dialog.setWindowTitle(self.tr("Raman Database"))
            dialog.resize(400, 300)
            
            layout = QVBoxLayout(dialog)
            
            label = QLabel(self.tr("Available Substances:"))
            layout.addWidget(label)
            
            list_widget = QListWidget()
            list_widget.addItems(substances)
            layout.addWidget(list_widget)
            
            button = QPushButton(self.tr("Close"))
            button.clicked.connect(dialog.accept)
            layout.addWidget(button)
            
            dialog.exec_()
        else:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Failed to load database"))

    def _on_laser_button_clicked(self, checked):
        """
        处理激光按钮点击事件
        """
        if checked:
            # 激光开启确认
            reply = QMessageBox.question(self, self.tr("Laser Safety Warning"),
                                       self.tr('''Are you sure you want to turn on the laser?

Laser radiation can be harmful to eyes and skin.
Please ensure proper safety precautions are in place.

Do you wish to continue?'''),
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                self.laser_button.setText(self.tr("Turn Laser OFF"))
                # 调用控制器设置激光状态
                if self.controller:
                    self.controller.set_laser_state(True)
            else:
                self.laser_button.setChecked(False)
        else:
            self.laser_button.setText(self.tr("Turn Laser ON"))
            # 调用控制器设置激光状态
            if self.controller:
                self.controller.set_laser_state(False)

    def _on_excitation_wavelength_changed(self, value):
        """
        处理激发波长变化
        """
        if self.controller:
            self.controller.set_excitation_wavelength(value)

    def _on_laser_power_changed(self, value):
        """
        处理激光功率变化
        """
        if self.controller:
            self.controller.set_laser_power(value)

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



        self.result_display_layout.labelForField(self.main_peak_wavelength_label).setText(
            self.tr("Peak Wavelength (nm):"))
        self.result_display_layout.labelForField(self.main_peak_intensity_label).setText(self.tr("Peak Intensity:"))


        self.result_display_group.setTitle(self.tr("Analysis Results"))

        display_name = self.tr(self.mode_name)
        self.result_plot.setLabel('left', display_name)
        self.result_plot.setTitle(display_name, color='#90A4AE', size='12pt')
        self.result_title_label.setText(display_name)

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
                
            icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'icons', icon_filename)
            if os.path.exists(icon_path):
                button.setIcon(pg.QtGui.QIcon(icon_path))
            else:
                # 如果深色图标不存在，回退到原始图标
                original_icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'icons', 'zoom.png')
                button.setIcon(pg.QtGui.QIcon(original_icon_path))
        except Exception:
            # 如果无法加载设置或图标，使用默认图标
            icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'icons', 'zoom.png')
            button.setIcon(pg.QtGui.QIcon(icon_path))

    def _update_all_popout_icons(self):
        """更新所有弹出按钮的图标"""
        # 更新所有图表的弹出按钮图标
        try:
            plot_containers = [
                self.signal_plot_container,
                self.background_plot_container,
                self.reference_plot_container,
                self.result_plot_container
            ]
            
            for container in plot_containers:
                if container:
                    popout_button = container.findChild(QToolButton)
                    if popout_button:
                        self._update_popout_button_icon(popout_button)
        except Exception:
            pass  # 忽略错误

    def _update_plot_backgrounds(self):
        """根据当前主题更新图表背景"""
        try:
            from ..utils.config_manager import load_settings
            settings = load_settings()
            theme = settings.get('theme', 'dark')
            
            # 定义不同主题的背景色和网格透明度
            if theme == 'light':
                background_color = '#F0F0F0'  # 偏暗的浅色背景
                grid_alpha = 0.1
                # 浅色主题下坐标轴和坐标使用黑色
                axis_pen = pg.mkPen("#000000", width=1)
                text_pen = pg.mkPen("#000000")
            else:
                background_color = '#1F2735'  # 深色背景
                grid_alpha = 0.3
                # 深色主题下坐标轴和坐标使用浅色
                axis_pen = pg.mkPen("#4D5A6D", width=1)
                text_pen = pg.mkPen("#E2E8F0")
                
            # 更新所有图表的背景
            for plot in [self.signal_plot, self.background_plot, self.reference_plot, self.result_plot]:
                plot.setBackground(background_color)
                plot.showGrid(x=True, y=True, alpha=grid_alpha)
                # 设置坐标轴和坐标文本颜色
                for axis in ("left", "bottom"):
                    ax = plot.getPlotItem().getAxis(axis)
                    ax.setPen(axis_pen)
                    ax.setTextPen(text_pen)
                
            # 更新图例文字颜色
            text_color = '#000000' if theme == 'light' else '#E2E8F0'
            for plot in [self.signal_plot, self.background_plot, self.reference_plot, self.result_plot]:
                legend = plot.getPlotItem().legend
                if legend:
                    for item in legend.items:
                        label = item[1]  # item is a tuple (sample, label)
                        label.setText(label.text, color=text_color)
        except Exception:
            pass  # 忽略错误
    
    def wavelength_to_raman_shift(self, wavelengths, excitation_wavelength):
        """
        将波长转换为拉曼位移
        :param wavelengths: 波长数组（nm）
        :param excitation_wavelength: 激发波长（nm）
        :return: 拉曼位移数组（cm⁻¹）
        """
        lambda_exc = excitation_wavelength * 1e-7  # 转换为cm
        lambda_em = wavelengths * 1e-7  # 转换为cm
        raman_shift = 10000 * (1/lambda_exc - 1/lambda_em)
        return raman_shift
    
    def raman_shift_to_wavelength(self, raman_shifts, excitation_wavelength):
        """
        将拉曼位移转换为波长
        :param raman_shifts: 拉曼位移数组（cm⁻¹）
        :param excitation_wavelength: 激发波长（nm）
        :return: 波长数组（nm）
        """
        lambda_exc = excitation_wavelength * 1e-7  # 转换为cm
        raman_shift_cm = raman_shifts / 10000  # 转换为cm⁻¹
        lambda_em = 1 / (1/lambda_exc - raman_shift_cm)
        return lambda_em * 1e7  # 转换回nm
    
    def _toggle_wavelength_wavenumber(self):
        """
        切换波长和波数显示
        """
        if self.mode_name != "Raman":
            QMessageBox.warning(self, self.tr("Warning"), self.tr("Wavenumber display is only available in Raman mode"))
            self.wavenumber_toggle.setChecked(False)
            return
        
        if self.full_result_x is None or self.full_result_y is None:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("No spectrum data available"))
            self.wavenumber_toggle.setChecked(False)
            return
        
        excitation_wavelength = self.excitation_wavelength_spinbox.value()
        
        if self.wavenumber_toggle.isChecked():
            # 切换到波数
            self.wavenumber_toggle.setText(self.tr("Switch to Wavelength"))
            
            # 将波长转换为波数
            wavenumbers = self.wavelength_to_raman_shift(self.full_result_x, excitation_wavelength)
            
            # 更新结果图
            self.result_curve.setData(wavenumbers, self.full_result_y)
            self.result_plot.setLabel('bottom', self.tr('Raman Shift (cm⁻¹)'))
            
            # 更新峰值标签
            self.result_display_layout.labelForField(self.main_peak_wavelength_label).setText(self.tr("Peak Wavenumber (cm⁻¹):"))
            
            # 更新峰值标记（如果有）
            if hasattr(self, 'peak_markers'):
                peaks = self.peak_markers.getData()
                if peaks:
                    peak_wavelengths = peaks[0]
                    peak_intensities = peaks[1]
                    peak_wavenumbers = self.wavelength_to_raman_shift(peak_wavelengths, excitation_wavelength)
                    self.peak_markers.setData(peak_wavenumbers, peak_intensities)
            
            if hasattr(self, 'main_peak_marker'):
                main_peak = self.main_peak_marker.getData()
                if main_peak:
                    main_peak_wavelength = main_peak[0][0]
                    main_peak_intensity = main_peak[1][0]
                    main_peak_wavenumber = self.wavelength_to_raman_shift(np.array([main_peak_wavelength]), excitation_wavelength)[0]
                    self.main_peak_marker.setData([main_peak_wavenumber], [main_peak_intensity])
                    self.main_peak_wavelength_label.setText(f"{main_peak_wavenumber:.2f}")
        else:
            # 切换回波长
            self.wavenumber_toggle.setText(self.tr("Switch to Wavenumber"))
            
            # 更新结果图
            self.result_curve.setData(self.full_result_x, self.full_result_y)
            self.result_plot.setLabel('bottom', self.tr('Wavelength (nm)'))
            
            # 更新峰值标签
            self.result_display_layout.labelForField(self.main_peak_wavelength_label).setText(self.tr("Peak Wavelength (nm):"))
            
            # 更新峰值标记（如果有）
            if hasattr(self, 'peak_markers'):
                peaks = self.peak_markers.getData()
                if peaks:
                    peak_wavenumbers = peaks[0]
                    peak_intensities = peaks[1]
                    peak_wavelengths = self.raman_shift_to_wavelength(peak_wavenumbers, excitation_wavelength)
                    self.peak_markers.setData(peak_wavelengths, peak_intensities)
            
            if hasattr(self, 'main_peak_marker'):
                main_peak = self.main_peak_marker.getData()
                if main_peak:
                    main_peak_wavenumber = main_peak[0][0]
                    main_peak_intensity = main_peak[1][0]
                    main_peak_wavelength = self.raman_shift_to_wavelength(np.array([main_peak_wavenumber]), excitation_wavelength)[0]
                    self.main_peak_marker.setData([main_peak_wavelength], [main_peak_intensity])
                    self.main_peak_wavelength_label.setText(f"{main_peak_wavelength:.2f}")
