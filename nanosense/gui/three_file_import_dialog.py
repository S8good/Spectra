# nanosense/gui/three_file_import_dialog.py

import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget,
                             QLabel, QLineEdit, QPushButton, QDialogButtonBox, QMessageBox)  # 新增 QMessageBox
from PyQt5.QtCore import QEvent  # 新增 QEvent
import pyqtgraph as pg
from nanosense.utils.file_io import load_spectrum
import os


class ThreeFileImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(900, 700)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self.signal_data = None
        self.background_data = None
        self.reference_data = None
        self.result_data = None

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # 设置初始文本

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        # --- 区域 A: 文件选择区 ---
        selection_widget = QWidget()
        selection_layout = QGridLayout(selection_widget)

        self.signal_path_edit = QLineEdit();
        self.signal_path_edit.setReadOnly(True)
        self.bg_path_edit = QLineEdit();
        self.bg_path_edit.setReadOnly(True)
        self.ref_path_edit = QLineEdit();
        self.ref_path_edit.setReadOnly(True)

        self.signal_btn = QPushButton()  # 修改: 创建空按钮
        self.bg_btn = QPushButton()
        self.ref_btn = QPushButton()

        self.signal_label = QLabel()  # 修改: 创建空标签
        self.bg_label = QLabel()
        self.ref_label = QLabel()

        selection_layout.addWidget(self.signal_label, 0, 0)
        selection_layout.addWidget(self.signal_path_edit, 0, 1)
        selection_layout.addWidget(self.signal_btn, 0, 2)
        selection_layout.addWidget(self.bg_label, 1, 0)
        selection_layout.addWidget(self.bg_path_edit, 1, 1)
        selection_layout.addWidget(self.bg_btn, 1, 2)
        selection_layout.addWidget(self.ref_label, 2, 0)
        selection_layout.addWidget(self.ref_path_edit, 2, 1)
        selection_layout.addWidget(self.ref_btn, 2, 2)
        main_layout.addWidget(selection_widget)

        # --- 区域 B: 谱线预览区 ---
        preview_widget = QWidget()
        preview_layout = QHBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOption('background', '#263238')
        pg.setConfigOption('foreground', 'w')

        self.signal_plot = pg.PlotWidget()
        self.bg_plot = pg.PlotWidget()
        self.ref_plot = pg.PlotWidget()

        self.signal_curve = self.signal_plot.plot(pen='c')
        self.bg_curve = self.bg_plot.plot(pen='w')
        self.ref_curve = self.ref_plot.plot(pen='m')

        preview_layout.addWidget(self.signal_plot)
        preview_layout.addWidget(self.bg_plot)
        preview_layout.addWidget(self.ref_plot)
        main_layout.addWidget(preview_widget, stretch=1)

        # --- 区域 C: 结果预览区 ---
        self.result_plot = pg.PlotWidget()
        self.result_curve = self.result_plot.plot(pen='y')
        main_layout.addWidget(self.result_plot, stretch=1)

        # --- 确定/取消按钮 ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        """ 新增：集中管理信号连接 """
        self.signal_btn.clicked.connect(lambda: self.load_file('signal'))
        self.bg_btn.clicked.connect(lambda: self.load_file('background'))
        self.ref_btn.clicked.connect(lambda: self.load_file('reference'))
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def changeEvent(self, event):
        """ 新增：响应语言变化事件 """
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """ 新增：重新翻译此控件内的所有UI文本 """
        self.setWindowTitle(self.tr("Calculate Spectrum from Three Files"))

        self.signal_label.setText(self.tr("Signal Spectrum (S):"))
        self.bg_label.setText(self.tr("Background Spectrum (D):"))
        self.ref_label.setText(self.tr("Reference Spectrum (R):"))

        browse_text = self.tr("Browse...")
        self.signal_btn.setText(browse_text)
        self.bg_btn.setText(browse_text)
        self.ref_btn.setText(browse_text)

        title_style = {'color': '#90A4AE', 'font-size': '10pt'}
        self.signal_plot.setTitle(self.tr("Signal Spectrum Preview"), **title_style)
        self.bg_plot.setTitle(self.tr("Background Spectrum Preview"), **title_style)
        self.ref_plot.setTitle(self.tr("Reference Spectrum Preview"), **title_style)
        self.result_plot.setTitle(self.tr("Result (Absorbance)"), **title_style)

        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("Cancel"))

    def load_file(self, file_type):
        default_load_path = self.app_settings.get('default_load_path', '')
        x, y, file_path = load_spectrum(self, default_load_path)
        if x is not None and y is not None:
            path_edit, curve = None, None
            if file_type == 'signal':
                self.signal_data = (x, y);
                path_edit = self.signal_path_edit;
                curve = self.signal_curve
            elif file_type == 'background':
                self.background_data = (x, y);
                path_edit = self.bg_path_edit;
                curve = self.bg_curve
            elif file_type == 'reference':
                self.reference_data = (x, y);
                path_edit = self.ref_path_edit;
                curve = self.ref_curve
            if path_edit is not None:
                path_edit.setText(file_path)  # load_spectrum现在返回的是完整路径
                curve.setData(x, y)
            self.calculate_and_plot_result()

    def calculate_and_plot_result(self):
        if self.signal_data and self.background_data and self.reference_data:
            s_x, s_y = self.signal_data;
            d_x, d_y = self.background_data;
            r_x, r_y = self.reference_data
            if not (len(s_y) == len(d_y) == len(r_y)):
                # 【修改】使用tr()翻译错误提示
                QMessageBox.critical(self, self.tr("Error"),
                                     self.tr("The lengths of Signal, Background, and Reference spectra do not match."))
                return
            denominator = r_y - d_y
            denominator[denominator == 0] = 1e-9
            result_y_transmittance = (s_y - d_y) / denominator
            result_y_transmittance[result_y_transmittance <= 0] = 1e-9
            result_y_absorbance = -1 * np.log10(result_y_transmittance)
            self.result_data = (s_x, result_y_absorbance)
            self.result_curve.setData(self.result_data[0], self.result_data[1])
            # 【修改】使用tr()翻译打印信息
            print(self.tr("Absorbance spectrum calculated and previewed."))

    def get_data(self):
        return {
            'result': self.result_data, 'signal': self.signal_data,
            'background': self.background_data, 'reference': self.reference_data
        }

    def closeEvent(self, event):
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        super().closeEvent(event)