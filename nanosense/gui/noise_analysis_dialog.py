# 文件路径: nanosense/gui/noise_analysis_dialog.py

import os
import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
                             QMessageBox, QWidget, QLabel, QFormLayout, QGroupBox)
from PyQt5.QtCore import QEvent
import pyqtgraph as pg

from nanosense.utils.file_io import load_spectra_from_path


class NoiseAnalysisDialog(QDialog):
    """
    一个用于加载多次重复测量的光谱数据，并计算和显示噪声水平的对话框。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setGeometry(200, 200, 800, 600)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- 顶部工具栏 ---
        toolbar_layout = QHBoxLayout()
        self.import_button = QPushButton()
        toolbar_layout.addWidget(self.import_button)
        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)

        # --- 绘图区域 ---
        self.plot_widget = pg.PlotWidget()
        
        # 根据主题设置背景色和网格
        from ..utils.config_manager import load_settings
        settings = load_settings()
        theme = settings.get('theme', 'dark')
        if theme == 'light':
            self.plot_widget.setBackground('#F0F0F0')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.1)
            # 浅色主题下使用深色曲线
            self.noise_curve = self.plot_widget.plot(pen=pg.mkPen('k', width=2))
        else:
            self.plot_widget.setBackground('#1F2735')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            # 深色主题下使用青色曲线
            self.noise_curve = self.plot_widget.plot(pen='c')
        main_layout.addWidget(self.plot_widget)

        # --- 结果显示区域 ---
        self.results_group = QGroupBox()
        results_layout = QFormLayout(self.results_group)
        self.avg_noise_label = QLabel("N/A")
        self.avg_noise_label_title = QLabel()
        results_layout.addRow(self.avg_noise_label_title, self.avg_noise_label)
        main_layout.addWidget(self.results_group)

    def _connect_signals(self):
        self.import_button.clicked.connect(self._handle_import)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Noise Analysis"))
        self.import_button.setText(self.tr("Import Multi-Spectrum File..."))
        self.plot_widget.setTitle(self.tr("Noise Spectrum (Standard Deviation vs. Wavelength)"))
        self.plot_widget.setLabel('left', self.tr('Standard Deviation (σ)'))
        self.plot_widget.setLabel('bottom', self.tr('Wavelength (nm)'))
        self.results_group.setTitle(self.tr("Calculation Results"))
        self.avg_noise_label_title.setText(self.tr("Average Noise (Mean σ):"))

    def _handle_import(self):
        default_load_path = self.app_settings.get('default_load_path', '')
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select a multi-column spectrum file"),
            default_load_path,
            self.tr("Data Files (*.xlsx *.xls *.csv *.txt)")
        )
        if not file_path:
            return

        spectra_list = load_spectra_from_path(file_path, mode='file')

        if not spectra_list or len(spectra_list) < 2:
            QMessageBox.warning(self, self.tr("Error"),
                                self.tr("Please select a file with at least two measurement spectra."))
            return

        try:
            # 将所有光谱的y值整理到一个二维数组中
            wavelengths = spectra_list[0]['x']
            all_y_data = [spec['y'] for spec in spectra_list]
            spectra_matrix = np.array(all_y_data).T  # 转置，使每一行代表一个波长点

            # 核心计算：计算每个波长点（每一行）的标准差
            # ddof=1 使用样本标准差，在统计学上更常用
            noise_per_wavelength = np.std(spectra_matrix, axis=1, ddof=1)

            # 计算总平均噪声
            average_noise = np.mean(noise_per_wavelength)

            # 更新UI
            self.noise_curve.setData(wavelengths, noise_per_wavelength)
            self.avg_noise_label.setText(f"{average_noise:.4f}")

        except Exception as e:
            QMessageBox.critical(self, self.tr("Calculation Error"),
                                 self.tr("An error occurred during noise calculation: {0}").format(str(e)))