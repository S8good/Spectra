# nanosense/gui/preprocessing_dialog.py

import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox,
                             QFormLayout, QLabel, QSpinBox, QDoubleSpinBox, QDialogButtonBox, QComboBox,
                             QCheckBox)
from PyQt5.QtCore import Qt, QEvent  # 导入 QEvent
import pyqtgraph as pg

from nanosense.algorithms.preprocessing import baseline_als, smooth_savitzky_golay


class PreprocessingDialog(QDialog):
    def __init__(self, sample_wavelengths, sample_intensity, initial_params,
                 parent=None, spectra_options=None, selected_name=None):
        super().__init__(parent)
        self.setMinimumSize(900, 600)

        self.wavelengths = sample_wavelengths
        self.raw_intensity = sample_intensity
        self.params = initial_params.copy()
        self.spectra_options = spectra_options or []
        self.selected_name = selected_name

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()
        if self.preview_combo is not None:
            self._set_preview_data(self.preview_combo.currentIndex())  # 设置初始文本
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
        self.preview_combo = None
        self.preview_label = None
        if self.spectra_options:
            preview_form = QFormLayout()
            self.preview_label = QLabel()
            self.preview_combo = QComboBox()
            for name, _, _ in self.spectra_options:
                self.preview_combo.addItem(str(name))
            preview_form.addRow(self.preview_label, self.preview_combo)
            control_layout.addLayout(preview_form)
            if self.selected_name is not None:
                match_index = self.preview_combo.findText(self.selected_name)
                if match_index != -1:
                    self.preview_combo.setCurrentIndex(match_index)
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
        self.sg_two_stage_checkbox = QCheckBox()
        self.sg_window_coarse_label = QLabel();
        sg_layout.addRow(self.sg_two_stage_checkbox)
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
        if self.preview_combo is not None:
            self.preview_combo.currentIndexChanged.connect(self._on_preview_changed)
        self.sg_two_stage_checkbox.toggled.connect(self._on_smoothing_mode_changed)
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
        if self.preview_label is not None:
            self.preview_label.setText(self.tr("Preview Spectrum:"))

        self.als_group.setTitle(self.tr("1. Baseline Correction (ALS)"))
        self.als_lambda_label.setText(self.tr("Lambda (λ):"))
        self.als_p_label.setText("p:")

        self.sg_group.setTitle(self.tr("2. Smoothing (S-G)"))
        self.sg_two_stage_checkbox.setText(self.tr("Two-stage smoothing"))
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
        self.sg_two_stage_checkbox.setChecked(self.params.get('sg_two_stage', True))
        self._normalize_sg_controls()
        self._set_smoothing_mode()

    def _normalize_sg_controls(self):
        self._normalize_sg_pair(self.sg_window_coarse_input, self.sg_poly_coarse_input)
        self._normalize_sg_pair(self.sg_window_fine_input, self.sg_poly_fine_input)

    def _normalize_sg_pair(self, window_spinbox, poly_spinbox):
        window = int(window_spinbox.value())
        poly = int(poly_spinbox.value())
        if window % 2 == 0:
            window += 1
        if window <= poly:
            window = poly + 1
        if window % 2 == 0:
            window += 1
        window = min(window, int(window_spinbox.maximum()))
        poly_max = max(int(poly_spinbox.minimum()), window - 1)
        if window <= poly:
            poly = max(poly_spinbox.minimum(), window - 1)
        poly_spinbox.setMaximum(poly_max)
        if poly > poly_max:
            poly = poly_max
        block_w = window_spinbox.blockSignals(True)
        block_p = poly_spinbox.blockSignals(True)
        window_spinbox.setValue(window)
        poly_spinbox.setValue(poly)
        window_spinbox.blockSignals(block_w)
        poly_spinbox.blockSignals(block_p)

    def _update_plot(self):
        self._normalize_sg_controls()
        self.params['als_lambda'] = self.als_lambda_input.value()
        self.params['als_p'] = self.als_p_input.value()
        self.params['sg_window_coarse'] = self.sg_window_coarse_input.value()
        self.params['sg_polyorder_coarse'] = self.sg_poly_coarse_input.value()
        self.params['sg_window_fine'] = self.sg_window_fine_input.value()
        self.params['sg_polyorder_fine'] = self.sg_poly_fine_input.value()
        self.params['sg_two_stage'] = self.sg_two_stage_checkbox.isChecked()

        self.raw_curve.setData(self.wavelengths, self.raw_intensity, pen='w')
        baseline = baseline_als(self.raw_intensity, lam=self.params['als_lambda'], p=self.params['als_p'])
        baseline_corrected = self.raw_intensity - baseline
        coarse_smoothed = smooth_savitzky_golay(baseline_corrected,
                                                window_length=self.params['sg_window_coarse'],
                                                polyorder=self.params['sg_polyorder_coarse'])
        if self.params['sg_two_stage']:
            fine_smoothed = smooth_savitzky_golay(coarse_smoothed,
                                                  window_length=self.params['sg_window_fine'],
                                                  polyorder=self.params['sg_polyorder_fine'])
        else:
            fine_smoothed = coarse_smoothed
        self.baseline_curve.setData(self.wavelengths, baseline, pen=pg.mkPen('y', style=Qt.DashLine))
        self.processed_curve.setData(self.wavelengths, fine_smoothed, pen=pg.mkPen('g', width=2))

    def _set_smoothing_mode(self):
        use_two_stage = bool(self.sg_two_stage_checkbox.isChecked())
        self.sg_window_fine_input.setEnabled(use_two_stage)
        self.sg_poly_fine_input.setEnabled(use_two_stage)
        self.sg_window_fine_label.setEnabled(use_two_stage)
        self.sg_poly_fine_label.setEnabled(use_two_stage)

    def _on_smoothing_mode_changed(self):
        self._set_smoothing_mode()
        self._update_plot()

    def _set_preview_data(self, index):
        if index < 0 or index >= len(self.spectra_options):
            return
        _, wavelengths, intensity = self.spectra_options[index]
        self.wavelengths = wavelengths
        self.raw_intensity = intensity

    def _on_preview_changed(self, index):
        self._set_preview_data(index)
        self._update_plot()

    def get_params(self):
        return self.params
