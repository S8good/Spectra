# nanosense/gui/colorimetry_widget.py

import numpy as np
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QFileDialog, QDialog, QFormLayout, QComboBox, QDialogButtonBox, QMessageBox)
from PyQt5.QtCore import QEvent
import pyqtgraph as pg
from nanosense.algorithms.colorimetry import calculate_colorimetric_values
# 【新增】导入我们通用的文件加载函数
from nanosense.utils.file_io import load_spectrum_from_path


class ColorimetryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.main_window = parent
        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self.wavelengths = None
        self.spectral_data = None
        self.latest_results = None

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Toolbar ---
        toolbar_layout = QHBoxLayout()
        self.load_button = QPushButton()
        self.settings_button = QPushButton()
        self.save_to_db_button = QPushButton()
        self.save_to_db_button.setEnabled(False)

        toolbar_layout.addWidget(self.load_button)
        toolbar_layout.addWidget(self.settings_button)
        toolbar_layout.addWidget(self.save_to_db_button)
        toolbar_layout.addStretch()

        # --- Main Content Area ---
        content_layout = QHBoxLayout()

        self.plot_widget = pg.PlotWidget()
        
        # 根据主题设置背景色和网格
        from ..utils.config_manager import load_settings
        settings = load_settings()
        theme = settings.get('theme', 'dark')
        if theme == 'light':
            self.plot_widget.setBackground('#F0F0F0')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.1)
            # 浅色主题下使用黑色曲线
            self.spectrum_curve = self.plot_widget.plot(pen=pg.mkPen(color='k', width=2))
        else:
            self.plot_widget.setBackground('#1F2735')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            # 深色主题下使用白色曲线
            self.spectrum_curve = self.plot_widget.plot(pen=pg.mkPen(color='w', width=2))

        # 【修改】移除 self.data_table，它是不需要的
        # self.data_table = QTableWidget()
        # self.data_table.setColumnCount(2)
        # self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(2)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.setFixedWidth(300)  # 【新增】给结果表格一个固定宽度

        content_layout.addWidget(self.plot_widget, 3)
        # content_layout.addWidget(self.data_table, 1) # 【修改】移除
        content_layout.addWidget(self.results_table, 1)  # 【修改】结果表格现在占据右侧

        main_layout.addLayout(toolbar_layout)
        main_layout.addLayout(content_layout)

    def _connect_signals(self):
        self.load_button.clicked.connect(self._load_spectrum)
        self.settings_button.clicked.connect(self._open_settings_dialog)
        self.save_to_db_button.clicked.connect(self._save_results_to_db)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.load_button.setText(self.tr("Import Spectrum Data"))
        self.settings_button.setText(self.tr("Settings"))
        self.save_to_db_button.setText(self.tr("Save Results to Database"))
        self.plot_widget.setTitle(self.tr("Spectral Curve"))
        self.plot_widget.setLabel('bottom', self.tr('Wavelength (nm)'))
        self.plot_widget.setLabel('left', self.tr('Reflectance / Transmittance'))
        self.results_table.setHorizontalHeaderLabels([self.tr("Parameter"), self.tr("Value")])

    def _load_spectrum(self):
        """【重大修改】使用通用的加载函数，并修正逻辑错误"""
        default_load_path = self.app_settings.get('default_load_path', os.path.expanduser("~"))

        # 【修改】允许选择所有支持的文件类型，包括Excel
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Load Spectrum Data"), default_load_path,
            self.tr(
                "All Supported Files (*.xlsx *.xls *.csv *.txt);;Excel Files (*.xlsx *.xls);;CSV/Text Files (*.csv *.txt)")
        )
        if not file_path: return

        try:
            # 【修改】调用通用的 load_spectrum_from_path 函数
            wavelengths, spectral_data = load_spectrum_from_path(file_path)

            if wavelengths is None or spectral_data is None:
                raise ValueError("Failed to parse spectrum data from file.")

            self.wavelengths = wavelengths
            self.spectral_data = spectral_data

            # 【修改】直接更新图表和计算结果，不再更新不必要的数据表
            self._update_plot()
            self._calculate_and_display_results()

            print(f"Spectrum data loaded from {file_path}.")
        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Error loading spectrum file: {0}").format(str(e)))

    def _update_plot(self):
        """新增一个专门更新图表的函数"""
        if self.wavelengths is not None and self.spectral_data is not None:
            self.spectrum_curve.setData(self.wavelengths, self.spectral_data)

    def _calculate_and_display_results(self, illuminant='D65', observer='2'):
        # ... 此方法代码保持不变 ...
        results = calculate_colorimetric_values(self.wavelengths, self.spectral_data, illuminant, observer)
        self.latest_results = results
        if self.latest_results:
            self.save_to_db_button.setEnabled(True)
        else:
            self.save_to_db_button.setEnabled(False)

        self.results_table.setRowCount(len(results))
        for i, (param, value) in enumerate(results.items()):
            self.results_table.setItem(i, 0, QTableWidgetItem(param))
            self.results_table.setItem(i, 1, QTableWidgetItem(f"{value:.4f}"))
        print(f"Colorimetric parameters calculated using illuminant {illuminant} and {observer}° observer.")

    # ... _open_settings_dialog 和 _save_results_to_db 方法保持不变 ...
    def _open_settings_dialog(self):
        dialog = ColorSettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            illuminant, observer = dialog.get_settings()
            if self.wavelengths is not None:
                self._calculate_and_display_results(illuminant, observer)

    def _save_results_to_db(self):
        """将色度学计算结果保存到数据库。"""
        if not self.main_window or not self.main_window.db_manager:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Database is not available."))
            return

        if not self.latest_results:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("No valid colorimetry results to save."))
            return

        try:
            experiment_id = self.main_window.get_or_create_current_experiment_id()
            if experiment_id is None:
                return

            self.main_window.db_manager.save_analysis_result(
                experiment_id=experiment_id,
                analysis_type='Colorimetry',
                result_data=self.latest_results
            )

            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Colorimetry results have been saved to the database."))
            self.save_to_db_button.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, self.tr("Database Error"),
                                 self.tr("An error occurred while saving to the database:\n{0}").format(str(e)))


# ... ColorSettingsDialog 类的代码保持不变 ...
class ColorSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()

    def _init_ui(self):
        layout = QFormLayout(self)
        self.illuminant_combo = QComboBox()
        self.illuminant_combo.addItems(['D65', 'A', 'C', 'D50', 'D55', 'D75'])
        self.observer_combo = QComboBox()
        self.observer_combo.addItems(['2', '10'])
        self.illuminant_label = QLabel()
        self.observer_label = QLabel()
        layout.addRow(self.illuminant_label, self.illuminant_combo)
        layout.addRow(self.observer_label, self.observer_combo)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addRow(self.button_box)

    def _connect_signals(self):
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Colorimetry Settings"))
        self.illuminant_label.setText(self.tr("Standard Illuminant:"))
        self.observer_label.setText(self.tr("Standard Observer:"))
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("Cancel"))

    def get_settings(self):
        return self.illuminant_combo.currentText(), self.observer_combo.currentText()