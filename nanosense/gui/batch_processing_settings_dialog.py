# nanosense/gui/batch_processing_settings_dialog.py

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QDialogButtonBox, QLabel
)
from PyQt5.QtCore import pyqtSignal, QEvent


class BatchProcessingSettingsDialog(QDialog):
    """
    批量采集预处理参数设置对话框
    
    包含采集、平滑、基线校正、寻峰算法的完整设置
    """
    
    settings_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None, initial_settings=None):
        super().__init__(parent)
        
        # 默认参数
        self.default_settings = {
            'integration_time_ms': 100,
            'smoothing_method': 'Savitzky-Golay',
            'smoothing_window': 15,
            'smoothing_order': 3,
            'baseline_enabled': True,
            'baseline_algorithm': 'ALS',
            'baseline_lambda': 1000000,
            'baseline_p': 0.001,
            'baseline_niter': 10,
            'peak_method': 'gaussian_fit',
            'peak_height': 0.01
        }
        
        # 使用初始设置或默认值
        self.current_settings = initial_settings if initial_settings else self.default_settings.copy()
        
        self._init_ui()
        self._load_settings()
        self._retranslate_ui()
    
    def _init_ui(self):
        """初始化UI"""
        self.setMinimumWidth(450)
        main_layout = QVBoxLayout(self)
        
        # 1. 采集参数组
        acquisition_group = QGroupBox()
        acq_layout = QFormLayout()
        
        self.integration_time_spinbox = QSpinBox()
        self.integration_time_spinbox.setRange(50, 1000)
        self.integration_time_spinbox.setSuffix(" ms")
        self.integration_time_spinbox.setSingleStep(10)
        
        self.integration_time_label = QLabel()
        acq_layout.addRow(self.integration_time_label, self.integration_time_spinbox)
        acquisition_group.setLayout(acq_layout)
        main_layout.addWidget(acquisition_group)
        
        # 2. 平滑设置组
        smoothing_group = QGroupBox()
        smooth_layout = QFormLayout()
        
        self.smoothing_method_combo = QComboBox()
        self.smoothing_method_combo.addItem("Savitzky-Golay", "Savitzky-Golay")
        self.smoothing_method_combo.addItem("Moving Average", "Moving Average")
        self.smoothing_method_combo.currentIndexChanged.connect(self._on_smoothing_method_changed)
        
        self.smoothing_window_spinbox = QSpinBox()
        self.smoothing_window_spinbox.setRange(3, 51)
        self.smoothing_window_spinbox.setSingleStep(2)  # 确保是奇数
        
        self.smoothing_order_spinbox = QSpinBox()
        self.smoothing_order_spinbox.setRange(1, 5)
        
        self.smoothing_method_label = QLabel()
        self.smoothing_window_label = QLabel()
        self.smoothing_order_label = QLabel()
        
        smooth_layout.addRow(self.smoothing_method_label, self.smoothing_method_combo)
        smooth_layout.addRow(self.smoothing_window_label, self.smoothing_window_spinbox)
        smooth_layout.addRow(self.smoothing_order_label, self.smoothing_order_spinbox)
        
        smoothing_group.setLayout(smooth_layout)
        main_layout.addWidget(smoothing_group)
        
        # 3. 基线校正设置组
        baseline_group = QGroupBox()
        baseline_layout = QFormLayout()
        
        self.baseline_enabled_checkbox = QCheckBox()
        self.baseline_enabled_checkbox.toggled.connect(self._on_baseline_enabled_toggled)
        
        self.baseline_algorithm_combo = QComboBox()
        self.baseline_algorithm_combo.addItem("ALS", "ALS")
        self.baseline_algorithm_combo.addItem("SNIP", "SNIP")
        self.baseline_algorithm_combo.addItem("Linear", "Linear")
        self.baseline_algorithm_combo.currentIndexChanged.connect(self._on_baseline_algorithm_changed)
        
        self.baseline_lambda_spinbox = QDoubleSpinBox()
        self.baseline_lambda_spinbox.setRange(1000, 100000000)
        self.baseline_lambda_spinbox.setDecimals(0)
        self.baseline_lambda_spinbox.setSingleStep(100000)
        
        self.baseline_p_spinbox = QDoubleSpinBox()
        self.baseline_p_spinbox.setRange(0.0001, 0.1)
        self.baseline_p_spinbox.setDecimals(4)
        self.baseline_p_spinbox.setSingleStep(0.001)
        
        self.baseline_niter_spinbox = QSpinBox()
        self.baseline_niter_spinbox.setRange(1, 50)
        
        self.baseline_enabled_label = QLabel()
        self.baseline_algorithm_label = QLabel()
        self.baseline_lambda_label = QLabel()
        self.baseline_p_label = QLabel()
        self.baseline_niter_label = QLabel()
        
        baseline_layout.addRow(self.baseline_enabled_label, self.baseline_enabled_checkbox)
        baseline_layout.addRow(self.baseline_algorithm_label, self.baseline_algorithm_combo)
        baseline_layout.addRow(self.baseline_lambda_label, self.baseline_lambda_spinbox)
        baseline_layout.addRow(self.baseline_p_label, self.baseline_p_spinbox)
        baseline_layout.addRow(self.baseline_niter_label, self.baseline_niter_spinbox)
        
        baseline_group.setLayout(baseline_layout)
        main_layout.addWidget(baseline_group)
        
        # 4. 寻峰算法设置组
        peak_group = QGroupBox()
        peak_layout = QFormLayout()
        
        self.peak_method_combo = QComboBox()
        from nanosense.algorithms.peak_analysis import PEAK_METHOD_LABELS
        for method_key, method_label in PEAK_METHOD_LABELS.items():
            self.peak_method_combo.addItem(method_label, method_key)
        
        self.peak_height_spinbox = QDoubleSpinBox()
        self.peak_height_spinbox.setRange(0.001, 10.0)
        self.peak_height_spinbox.setDecimals(3)
        self.peak_height_spinbox.setSingleStep(0.01)
        
        self.peak_method_label = QLabel()
        self.peak_height_label = QLabel()
        
        peak_layout.addRow(self.peak_method_label, self.peak_method_combo)
        peak_layout.addRow(self.peak_height_label, self.peak_height_spinbox)
        
        peak_group.setLayout(peak_layout)
        main_layout.addWidget(peak_group)
        
        # 5. 按钮组
        button_layout = QHBoxLayout()
        self.reset_button = QPushButton()
        self.reset_button.clicked.connect(self._reset_to_defaults)
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        button_layout.addWidget(self.button_box)
        
        main_layout.addLayout(button_layout)
        
        # 保存组件引用便于显示/隐藏
        self.acquisition_group = acquisition_group
        self.smoothing_group = smoothing_group
        self.baseline_group = baseline_group
        self.peak_group = peak_group
    
    def _on_smoothing_method_changed(self):
        """平滑方法改变时，显示/隐藏多项式阶数"""
        is_sg = self.smoothing_method_combo.currentData() == "Savitzky-Golay"
        self.smoothing_order_spinbox.setVisible(is_sg)
        self.smoothing_order_label.setVisible(is_sg)
    
    def _on_baseline_enabled_toggled(self, checked):
        """基线校正启用状态改变"""
        self.baseline_algorithm_combo.setEnabled(checked)
        self.baseline_lambda_spinbox.setEnabled(checked)
        self.baseline_p_spinbox.setEnabled(checked)
        self.baseline_niter_spinbox.setEnabled(checked)
        self.baseline_algorithm_label.setEnabled(checked)
        self.baseline_lambda_label.setEnabled(checked)
        self.baseline_p_label.setEnabled(checked)
        self.baseline_niter_label.setEnabled(checked)
        
        if checked:
            self._on_baseline_algorithm_changed()
    
    def _on_baseline_algorithm_changed(self):
        """基线算法改变时，显示/隐藏ALS参数"""
        is_als = self.baseline_algorithm_combo.currentData() == "ALS"
        self.baseline_lambda_spinbox.setVisible(is_als)
        self.baseline_p_spinbox.setVisible(is_als)
        self.baseline_niter_spinbox.setVisible(is_als)
        self.baseline_lambda_label.setVisible(is_als)
        self.baseline_p_label.setVisible(is_als)
        self.baseline_niter_label.setVisible(is_als)
    
    def _load_settings(self):
        """加载设置到UI控件"""
        self.integration_time_spinbox.setValue(self.current_settings.get('integration_time_ms', 100))
        
        # 平滑设置
        method_index = self.smoothing_method_combo.findData(self.current_settings.get('smoothing_method', 'Savitzky-Golay'))
        if method_index >= 0:
            self.smoothing_method_combo.setCurrentIndex(method_index)
        self.smoothing_window_spinbox.setValue(self.current_settings.get('smoothing_window', 11))
        self.smoothing_order_spinbox.setValue(self.current_settings.get('smoothing_order', 3))
        
        # 基线校正设置
        self.baseline_enabled_checkbox.setChecked(self.current_settings.get('baseline_enabled', True))
        algo_index = self.baseline_algorithm_combo.findData(self.current_settings.get('baseline_algorithm', 'ALS'))
        if algo_index >= 0:
            self.baseline_algorithm_combo.setCurrentIndex(algo_index)
        self.baseline_lambda_spinbox.setValue(self.current_settings.get('baseline_lambda', 5000000))
        self.baseline_p_spinbox.setValue(self.current_settings.get('baseline_p', 0.001))
        self.baseline_niter_spinbox.setValue(self.current_settings.get('baseline_niter', 10))
        
        # 寻峰设置
        peak_index = self.peak_method_combo.findData(self.current_settings.get('peak_method', 'gaussian_fit'))
        if peak_index >= 0:
            self.peak_method_combo.setCurrentIndex(peak_index)
        self.peak_height_spinbox.setValue(self.current_settings.get('peak_height', 0.01))
        
        # 触发UI更新
        self._on_smoothing_method_changed()
        self._on_baseline_enabled_toggled(self.baseline_enabled_checkbox.isChecked())
    
    def _reset_to_defaults(self):
        """重置为默认值"""
        self.current_settings = self.default_settings.copy()
        self._load_settings()
    
    def get_settings(self):
        """获取当前设置"""
        return {
            'integration_time_ms': self.integration_time_spinbox.value(),
            'smoothing_method': self.smoothing_method_combo.currentData(),
            'smoothing_window': self.smoothing_window_spinbox.value(),
            'smoothing_order': self.smoothing_order_spinbox.value(),
            'baseline_enabled': self.baseline_enabled_checkbox.isChecked(),
            'baseline_algorithm': self.baseline_algorithm_combo.currentData(),
            'baseline_lambda': self.baseline_lambda_spinbox.value(),
            'baseline_p': self.baseline_p_spinbox.value(),
            'baseline_niter': self.baseline_niter_spinbox.value(),
            'peak_method': self.peak_method_combo.currentData(),
            'peak_height': self.peak_height_spinbox.value(),
        }
    
    def get_settings_summary(self):
        """获取设置摘要文本用于显示"""
        settings = self.get_settings()
        parts = []
        
        # 平滑
        method_abbrev = "SG" if settings['smoothing_method'] == "Savitzky-Golay" else "MA"
        parts.append(f"{method_abbrev}({settings['smoothing_window']})")
        
        # 基线
        if settings['baseline_enabled']:
            if settings['baseline_algorithm'] == 'ALS':
                parts.append(f"ALS(λ={settings['baseline_lambda']:.0e})")
            else:
                parts.append(settings['baseline_algorithm'])
        else:
            parts.append("No BL")
        
        # 寻峰
        peak_labels = {
            'highest_point': '最高点',
            'weighted_mean': '加权平均',
            'gaussian_fit': '高斯拟合',
            'lorentz_fit': '洛伦兹拟合'
        }
        peak_label = peak_labels.get(settings['peak_method'], settings['peak_method'])
        parts.append(peak_label)
        
        return " | ".join(parts)
    
    def changeEvent(self, event):
        """响应语言变化"""
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)
    
    def _retranslate_ui(self):
        """重新翻译UI文本"""
        self.setWindowTitle(self.tr("Processing Settings"))
        
        # 采集参数
        self.acquisition_group.setTitle(self.tr("Acquisition Parameters"))
        self.integration_time_label.setText(self.tr("Integration Time:"))
        
        # 平滑设置
        self.smoothing_group.setTitle(self.tr("Smoothing Settings"))
        self.smoothing_method_label.setText(self.tr("Smoothing Method:"))
        self.smoothing_window_label.setText(self.tr("Window Size:"))
        self.smoothing_order_label.setText(self.tr("Polynomial Order:"))
        
        # 基线校正
        self.baseline_group.setTitle(self.tr("Baseline Correction"))
        self.baseline_enabled_label.setText(self.tr("Enable Baseline Correction:"))
        self.baseline_algorithm_label.setText(self.tr("Algorithm:"))
        self.baseline_lambda_label.setText(self.tr("Lambda (λ):"))
        self.baseline_p_label.setText(self.tr("p Parameter:"))
        self.baseline_niter_label.setText(self.tr("Iterations:"))
        
        # 寻峰设置
        self.peak_group.setTitle(self.tr("Peak Finding"))
        self.peak_method_label.setText(self.tr("Peak Method:"))
        self.peak_height_label.setText(self.tr("Height Threshold:"))
        
        # 按钮
        self.reset_button.setText(self.tr("Reset to Defaults"))
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("Cancel"))
