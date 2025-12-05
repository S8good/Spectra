# nanosense/gui/preprocessing_dialog.py

import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox,
                             QFormLayout, QLabel, QSpinBox, QDoubleSpinBox, QDialogButtonBox)
from PyQt5.QtCore import Qt, QEvent  # 导入 QEvent
import pyqtgraph as pg

from nanosense.algorithms.preprocessing import baseline_als, smooth_savitzky_golay


class PreprocessingDialog(QDialog):
    def __init__(self, sample_wavelengths, sample_intensity, initial_params, parent=None):
        super().__init__(parent)
        self.setMinimumSize(900, 600)

        self.wavelengths = sample_wavelengths
        self.raw_intensity = sample_intensity
        self.params = initial_params.copy()

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # 设置初始文本
        self._update_plot()

    # (此代码块应放在 preprocessing_dialog.py 的 PreprocessingDialog 类中)

    def _init_ui(self):
        """
        创建并布局所有UI控件。
        """
        main_layout = QHBoxLayout(self)

        # ... (左侧控制面板的代码保持不变) ...
        control_panel = QGroupBox()
        control_panel.setFixedWidth(320)
        control_layout = QVBoxLayout(control_panel)
        self.control_panel_group = control_panel
        self.als_group = QGroupBox()
        als_layout = QFormLayout(self.als_group)
        self.als_lambda_input = QDoubleSpinBox();
        self.als_lambda_input.setDecimals(0);
        self.als_lambda_input.setRange(1e3, 1e9)
        self.als_p_input = QDoubleSpinBox();
        self.als_p_input.setDecimals(3);
        self.als_p_input.setSingleStep(0.001);
        self.als_p_input.setRange(0.001, 0.1)
        self.als_lambda_label = QLabel();
        self.als_p_label = QLabel()
        als_layout.addRow(self.als_lambda_label, self.als_lambda_input);
        als_layout.addRow(self.als_p_label, self.als_p_input)
        self.sg_group = QGroupBox()
        sg_layout = QFormLayout(self.sg_group)
        self.sg_window_coarse_input = QSpinBox();
        self.sg_window_coarse_input.setRange(3, 199);
        self.sg_window_coarse_input.setSingleStep(2)
        self.sg_poly_coarse_input = QSpinBox();
        self.sg_poly_coarse_input.setRange(1, 10)
        self.sg_window_fine_input = QSpinBox();
        self.sg_window_fine_input.setRange(3, 199);
        self.sg_window_fine_input.setSingleStep(2)
        self.sg_poly_fine_input = QSpinBox();
        self.sg_poly_fine_input.setRange(1, 10)
        self.sg_window_coarse_label = QLabel();
        self.sg_poly_coarse_label = QLabel()
        self.sg_window_fine_label = QLabel();
        self.sg_poly_fine_label = QLabel()
        sg_layout.addRow(self.sg_window_coarse_label, self.sg_window_coarse_input);
        sg_layout.addRow(self.sg_poly_coarse_label, self.sg_poly_coarse_input)
        sg_layout.addRow(QLabel("---"));
        sg_layout.addRow(self.sg_window_fine_label, self.sg_window_fine_input);
        sg_layout.addRow(self.sg_poly_fine_label, self.sg_poly_fine_input)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        control_layout.addWidget(self.als_group);
        control_layout.addWidget(self.sg_group);
        control_layout.addStretch();
        control_layout.addWidget(self.button_box)

        # --- Plotting Area ---
        self.plot_widget = pg.PlotWidget()
        
        # 根据主题设置背景色
        from ..utils.config_manager import load_settings
        settings = load_settings()
        theme = settings.get('theme', 'dark')
        if theme == 'light':
            self.plot_widget.setBackground('#F0F0F0')
        else:
            self.plot_widget.setBackground('#1F2735')

        main_layout.addWidget(control_panel)
        main_layout.addWidget(self.plot_widget, stretch=1)

        self._populate_initial_values()

    def _connect_signals(self):
        self.als_lambda_input.valueChanged.connect(self._update_plot)
        self.als_p_input.valueChanged.connect(self._update_plot)
        self.sg_window_coarse_input.valueChanged.connect(self._update_plot)
        self.sg_poly_coarse_input.valueChanged.connect(self._update_plot)
        self.sg_window_fine_input.valueChanged.connect(self._update_plot)
        self.sg_poly_fine_input.valueChanged.connect(self._update_plot)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def changeEvent(self, event):
        """ 新增：响应语言变化事件 """
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """ 新增：重新翻译此控件内的所有UI文本 """
        self.setWindowTitle(self.tr("Interactive Preprocessing Settings"))
        self.control_panel_group.setTitle(self.tr("Parameters"))

        self.als_group.setTitle(self.tr("1. Baseline Correction (ALS)"))
        self.als_lambda_label.setText(self.tr("Lambda (λ):"))
        self.als_p_label.setText("p:")

        self.sg_group.setTitle(self.tr("2. Two-Stage Smoothing (S-G)"))
        self.sg_window_coarse_label.setText(self.tr("Coarse Smoothing Window:"))
        self.sg_poly_coarse_label.setText(self.tr("Coarse Smoothing Order:"))
        self.sg_window_fine_label.setText(self.tr("Fine Smoothing Window:"))
        self.sg_poly_fine_label.setText(self.tr("Fine Smoothing Order:"))

        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("Cancel"))

        self.plot_widget.setTitle(self.tr("Preprocessing Effect Preview"))

        # 移除对 self.plot_widget.legend 的直接访问
        self.plot_widget.clear()  # 先清空图表中的所有项目（曲线等）

        # 重新添加一个图例。如果已有图例，pyqtgraph会智能处理，不会重复添加。
        self.plot_widget.addLegend()

        # 使用翻译后的名称，重新创建曲线对象
        self.raw_curve = self.plot_widget.plot(self.wavelengths, self.raw_intensity, name=self.tr("Raw Spectrum"),
                                               pen='w')
        self.baseline_curve = self.plot_widget.plot(name=self.tr("Fitted Baseline"),
                                                    pen=pg.mkPen('y', style=Qt.DashLine))
        self.processed_curve = self.plot_widget.plot(name=self.tr("Processed Spectrum"), pen=pg.mkPen('g', width=2))

        self._update_plot()  # 调用一次更新，确保所有曲线都有正确的数据

    def _populate_initial_values(self):
        """用初始参数填充UI控件"""
        self.als_lambda_input.setValue(self.params['als_lambda'])
        self.als_p_input.setValue(self.params['als_p'])
        self.sg_window_coarse_input.setValue(self.params['sg_window_coarse'])
        self.sg_poly_coarse_input.setValue(self.params['sg_polyorder_coarse'])
        self.sg_window_fine_input.setValue(self.params['sg_window_fine'])
        self.sg_poly_fine_input.setValue(self.params['sg_polyorder_fine'])

    def _update_plot(self):
        self.params['als_lambda'] = self.als_lambda_input.value()
        self.params['als_p'] = self.als_p_input.value()
        self.params['sg_window_coarse'] = self.sg_window_coarse_input.value()
        self.params['sg_polyorder_coarse'] = self.sg_poly_coarse_input.value()
        self.params['sg_window_fine'] = self.sg_window_fine_input.value()
        self.params['sg_polyorder_fine'] = self.sg_poly_fine_input.value()

        baseline = baseline_als(self.raw_intensity, lam=self.params['als_lambda'], p=self.params['als_p'])
        baseline_corrected = self.raw_intensity - baseline
        coarse_smoothed = smooth_savitzky_golay(baseline_corrected,
                                                window_length=self.params['sg_window_coarse'],
                                                polyorder=self.params['sg_polyorder_coarse'])
        fine_smoothed = smooth_savitzky_golay(coarse_smoothed,
                                              window_length=self.params['sg_window_fine'],
                                              polyorder=self.params['sg_polyorder_fine'])
        self.baseline_curve.setData(self.wavelengths, baseline, pen=pg.mkPen('y', style=Qt.DashLine))
        self.processed_curve.setData(self.wavelengths, fine_smoothed, pen=pg.mkPen('g', width=2))

    def get_params(self):
        return self.params