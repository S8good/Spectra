# nanosense/gui/analysis_window.py

import os
import time
import re
import pandas as pd
import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
                             QPushButton, QComboBox, QFormLayout, QDoubleSpinBox, QLabel, QGroupBox,
                             QMessageBox, QFileDialog, QInputDialog, QScrollArea)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QEvent
from PyQt5.QtGui import QPalette

from nanosense.algorithms.peak_analysis import (
    calculate_fwhm,
    PEAK_METHOD_KEYS,
    PEAK_METHOD_LABELS,
    estimate_peak_position,
)
from .collapsible_box import CollapsibleBox
class SummaryReportWorker(QThread):
    """一个专门在后台批量分析并生成汇总报告的工作线程。"""
    progress = pyqtSignal(int, str)  # 发射进度（百分比，消息）
    finished = pyqtSignal(str, str)  # 发射（成功消息/错误消息，报告文件路径）

    def __init__(self, spectra_to_process, output_folder, parent=None):
        super().__init__(parent)
        self.spectra = spectra_to_process
        self.output_folder = output_folder

    def run(self):
        try:
            total_spectra = len(self.spectra)
            peak_metrics_list = []

            for i, (name, data) in enumerate(self.spectra.items()):
                self.progress.emit(int(i / total_spectra * 70), f"Analyzing: {name}")
                peak_index = np.argmax(data['y'])
                peak_wl = data['x'][peak_index]
                peak_int = data['y'][peak_index]
                fwhm_results = calculate_fwhm(data['x'], data['y'], [peak_index])
                fwhm = fwhm_results[0] if fwhm_results else np.nan
                peak_metrics_list.append({
                    'File Name': name, 'Peak Wavelength (nm)': peak_wl,
                    'Peak Intensity': peak_int, 'FWHM (nm)': fwhm
                })

            self.progress.emit(75, "Generating summary table...")
            summary_df = pd.DataFrame(peak_metrics_list)
            stats_df = summary_df[['Peak Wavelength (nm)', 'Peak Intensity', 'FWHM (nm)']].agg(['mean', 'std']).T
            stats_df['CV (%)'] = (stats_df['std'] / stats_df['mean']) * 100
            avg_y = np.mean([data['y'] for data in self.spectra.values()], axis=0)
            avg_x = next(iter(self.spectra.values()))['x']
            avg_df = pd.DataFrame({'Wavelength (nm)': avg_x, 'Average Value': avg_y})
            all_spectra_df_dict = {'Wavelength (nm)': avg_x}
            for name, data in self.spectra.items():
                all_spectra_df_dict[name] = data['y']
            all_spectra_df = pd.DataFrame(all_spectra_df_dict)

            timestamp = time.strftime("%Y%m%d-%H%M%S")
            report_path = os.path.join(self.output_folder, f"Summary_Report_{timestamp}.xlsx")
            with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
                summary_df.to_excel(writer, sheet_name='Peak Metrics Summary', index=False)
                stats_df.to_excel(writer, sheet_name='Statistics')
                avg_df.to_excel(writer, sheet_name='Average Spectrum Data', index=False)
                all_spectra_df.to_excel(writer, sheet_name='All Spectra Data', index=False)

            self.progress.emit(100, "Report generation complete!")
            self.finished.emit("success", report_path)

        except Exception as e:
            error_message = f"An error occurred while generating the summary report: {e}"
            print(error_message)
            self.finished.emit(error_message, "")

class AverageCalculator(QThread):
    finished = pyqtSignal(object)

    def __init__(self, spectra_y_list, parent=None):
        super().__init__(parent)
        self.spectra_y_list = spectra_y_list

    def run(self):
        try:
            average_y = np.mean(self.spectra_y_list, axis=0)
            self.finished.emit(average_y)
        except Exception as e:
            print(f"计算平均值时发生错误: {e}")
            self.finished.emit(None)

DEFAULT_CURVES_TO_DISPLAY = 20
AVERAGE_CURVE_KEY = "__average_curve__"

class AnalysisWindow(QMainWindow):

    def __init__(self, spectra_data=None, parent=None):
        super().__init__(parent)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self.spectra = {}
        self.average_curve_data = None
        self.average_curve_item = None
        self.main_spectrum_to_analyze = None
        self.calc_thread = None
        self.report_worker = None
        self.source_signal = None
        self.source_background = None
        self.source_reference = None
        self.user_has_interacted_with_plot = False # 用户是否手动缩放/平移了图表
        self.total_spectra_count = 0
        self.display_spectra_count = 0

        self.init_ui()
        self.connect_signals()

        if spectra_data is not None:
            self.set_initial_data(spectra_data)

        self._retranslate_ui()

    def init_ui(self):
        self.setGeometry(150, 150, 1300, 700)
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        control_panel = self._create_control_panel()
        plot_widget = self._create_plot_widget()
        main_layout.addWidget(control_panel)
        main_layout.addWidget(plot_widget, stretch=1)

    def set_initial_data(self, spectra_data):
        spectra_list_of_dicts = []
        if isinstance(spectra_data, dict) and 'result' in spectra_data:
            result_x, result_y = spectra_data['result']
            spectra_list_of_dicts.append({'x': result_x, 'y': result_y, 'name': 'Calculated Result'})
            if spectra_data.get('signal'): self.source_signal = spectra_data['signal']
            if spectra_data.get('background'): self.source_background = spectra_data['background']
            if spectra_data.get('reference'): self.source_reference = spectra_data['reference']
        elif isinstance(spectra_data, list):
            spectra_list_of_dicts = spectra_data
        elif isinstance(spectra_data, dict):
            spectra_list_of_dicts.append(spectra_data)

        self.plot_widget.clear()
        self.plot_widget.addItem(self.main_peak_marker)
        self.plot_widget.addItem(self.region_selector)
        self.main_peak_marker.clear()

        if self.average_curve_item:
            self.plot_widget.removeItem(self.average_curve_item)
        self.average_curve_item = None
        self.average_curve_data = None
        self.spectra.clear()
        self.spectra_list_widget.clear()
        self.analysis_target_combo.blockSignals(True)
        self.analysis_target_combo.clear()

        self.total_spectra_count = len(spectra_list_of_dicts)
        self._update_display_count_and_title()

        # 【核心修改】为所有光谱创建曲线，但只显示一部分
        for i, spec_dict in enumerate(spectra_list_of_dicts):
            x, y, name = spec_dict['x'], spec_dict['y'], spec_dict['name']
            # 创建一个唯一的内部key，例如 "测试02_Signal___1"
            key = f"{name}___{i}"

            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)

            # 将这个唯一的key存入列表项中，作为它的“身份证”
            item.setData(Qt.UserRole, key)

            # 默认只勾选并显示前 DEFAULT_CURVES_TO_DISPLAY 条
            should_be_visible = (i < DEFAULT_CURVES_TO_DISPLAY)
            item.setCheckState(Qt.Checked if should_be_visible else Qt.Unchecked)

            color = pg.Color((i * 30 + 50) % 255, (i * 50 + 100) % 255, (i * 70 + 150) % 255)
            pen = pg.mkPen(color=color, width=1)

            # 为所有光谱都创建曲线对象
            curve_item = self.plot_widget.plot(x, y, pen=pen, name=name)
            curve_item.setVisible(should_be_visible)  # 根据标志位设置初始可见性

            self.spectra[key] = {'x': x, 'y': y, 'name': name, 'curve': curve_item, 'list_item': item}
            self.spectra_list_widget.addItem(item)
            self.analysis_target_combo.addItem(name)
            self.analysis_target_combo.setItemData(self.analysis_target_combo.count() - 1, key)

        if spectra_list_of_dicts:
            self.analysis_target_combo.setCurrentIndex(0)
        self.analysis_target_combo.blockSignals(False)

        if spectra_list_of_dicts:
            self.update_analysis_target(self.analysis_target_combo.currentText())
        else:
            self.main_spectrum_to_analyze = None

    def _update_display_count_and_title(self):
        """
        【新增】重新计算当前显示的曲线数量，并更新图表标题。
        """
        # 遍历列表，统计被勾选的项目数量
        checked_count = 0
        for i in range(self.spectra_list_widget.count()):
            if self.spectra_list_widget.item(i).checkState() == Qt.Checked:
                checked_count += 1

        self.display_spectra_count = checked_count
        self._update_plot_title()  # 调用现有的标题更新方法

    def _create_control_panel(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(450)

        panel_widget = QWidget()
        panel_layout = QVBoxLayout(panel_widget)
        panel_layout.setSpacing(10)
        panel_layout.setContentsMargins(5, 5, 5, 5)

        # 1. 数据源下拉框
        self.data_source_box = CollapsibleBox(parent=self)
        data_source_layout = QVBoxLayout()
        self.spectra_list_label = QLabel()
        self.spectra_list_widget = QListWidget()
        data_source_layout.addWidget(self.spectra_list_label)
        data_source_layout.addWidget(self.spectra_list_widget)
        selection_button_layout = QHBoxLayout()
        self.select_all_button = QPushButton()
        self.deselect_all_button = QPushButton()
        self.filter_select_button = QPushButton()
        selection_button_layout.addWidget(self.select_all_button)
        selection_button_layout.addWidget(self.deselect_all_button)
        selection_button_layout.addWidget(self.filter_select_button)
        data_source_layout.addLayout(selection_button_layout)  # 将按钮布局添加到主布局中
        self.data_source_box.setContentLayout(data_source_layout)
        panel_layout.addWidget(self.data_source_box)

        # 2. 数据处理下拉框
        self.processing_box = CollapsibleBox(parent=self)
        processing_layout = QVBoxLayout()
        self.avg_button = QPushButton()
        self.clear_avg_button = QPushButton()
        self.export_summary_button = QPushButton()
        processing_layout.addWidget(self.avg_button)
        processing_layout.addWidget(self.clear_avg_button)
        processing_layout.addWidget(self.export_summary_button)
        self.processing_box.setContentLayout(processing_layout)
        panel_layout.addWidget(self.processing_box)

        # 3. 静态分析下拉框
        self.analysis_box = CollapsibleBox(parent=self)
        analysis_layout = QVBoxLayout()
        analysis_form_layout = QFormLayout()
        self.analysis_target_combo = QComboBox()
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

        self.analysis_target_label = QLabel()
        self.peak_method_label = QLabel()
        self.peak_height_label = QLabel()
        analysis_form_layout.addRow(self.analysis_target_label, self.analysis_target_combo)
        analysis_form_layout.addRow(self.peak_method_label, self.peak_method_combo)
        analysis_form_layout.addRow(self.peak_height_label, self.peak_height_spinbox)

        analysis_layout.addLayout(analysis_form_layout)

        self.range_group = QGroupBox()  # Title will be set in _retranslate_ui
        self.range_layout_form = QFormLayout(self.range_group)
        self.range_start_spinbox = QDoubleSpinBox()
        self.range_end_spinbox = QDoubleSpinBox()
        for spinbox in [self.range_start_spinbox, self.range_end_spinbox]:
            spinbox.setDecimals(2)
            spinbox.setRange(200.0, 1200.0)
            spinbox.setSingleStep(10.0)
            spinbox.setSuffix(" nm")

        self.range_start_spinbox.setValue(450.0)
        self.range_end_spinbox.setValue(750.0)

        self.range_start_label = QLabel()  # Create empty label
        self.range_end_label = QLabel()  # Create empty label
        self.range_layout_form.addRow(self.range_start_label, self.range_start_spinbox)
        self.range_layout_form.addRow(self.range_end_label, self.range_end_spinbox)

        self.reset_range_button = QPushButton()  # Create empty button
        self.range_layout_form.addRow(self.reset_range_button)
        analysis_layout.addWidget(self.range_group)

        self.find_main_peak_button = QPushButton()
        analysis_layout.addWidget(self.find_main_peak_button)

        # 结果显示部分（作为静态分析的一部分）
        self.result_display_group = QGroupBox()
        result_display_layout = QFormLayout(self.result_display_group)
        self.main_peak_wavelength_label = QLabel("N/A")
        self.main_peak_intensity_label = QLabel("N/A")
        self.main_peak_fwhm_label = QLabel("N/A")
        self.peak_wl_label = QLabel()
        self.peak_int_label = QLabel()
        self.peak_fwhm_label = QLabel()
        result_display_layout.addRow(self.peak_wl_label, self.main_peak_wavelength_label)
        result_display_layout.addRow(self.peak_int_label, self.main_peak_intensity_label)
        result_display_layout.addRow(self.peak_fwhm_label, self.main_peak_fwhm_label)
        analysis_layout.addWidget(self.result_display_group)
        self.analysis_box.setContentLayout(analysis_layout)
        panel_layout.addWidget(self.analysis_box)

        # 4. 导出按钮
        self.export_button = QPushButton()
        panel_layout.addWidget(self.export_button)

        # 设置初始展开状态
        self.data_source_box.set_expanded(True)
        self.processing_box.set_expanded(True)
        self.analysis_box.set_expanded(True)
        panel_layout.addStretch()
        scroll_area.setWidget(panel_widget)
        return scroll_area

    def _create_plot_widget(self):
        # 创建一个主容器，用于容纳图表和下面的按钮
        container_widget = QWidget()
        container_layout = QVBoxLayout(container_widget)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(5)

        plot_widget = pg.PlotWidget()
        plot_widget.addLegend()
        self.main_peak_marker = pg.ScatterPlotItem(size=15, symbol='star', pen=pg.mkPen('y'), brush=pg.mkBrush('y'))
        plot_widget.addItem(self.main_peak_marker)
        self.plot_widget = plot_widget

        self.region_selector = pg.LinearRegionItem(values=[450, 750], orientation=pg.LinearRegionItem.Vertical,
                                                   brush=pg.mkBrush(200, 200, 220, 40))
        plot_widget.addItem(self.region_selector)

        # 更新图表样式以适配当前主题
        self._update_plot_styles()

        button_layout = QHBoxLayout()
        self.auto_range_button = QPushButton()  # 创建按钮
        button_layout.addStretch()
        button_layout.addWidget(self.auto_range_button)

        container_layout.addWidget(self.plot_widget)
        container_layout.addLayout(button_layout)

        return container_widget
    def connect_signals(self):
        self.avg_button.clicked.connect(self.calculate_average)
        self.clear_avg_button.clicked.connect(self.clear_average_curve)
        self.analysis_target_combo.currentTextChanged.connect(self.update_analysis_target)
        self.find_main_peak_button.clicked.connect(self.analyze_main_peak)
        self.export_button.clicked.connect(self._export_analysis_results)
        self.export_summary_button.clicked.connect(self._trigger_summary_report)
        self.spectra_list_widget.itemChanged.connect(self._update_curve_visibility)
        # 1. 当用户手动改变视图范围时，调用 _on_plot_interacted
        self.plot_widget.getViewBox().sigRangeChangedManually.connect(self._on_plot_interacted)
        # 2. 连接新添加的 "自动范围" 按钮
        self.auto_range_button.clicked.connect(self._reset_plot_view)
        self.select_all_button.clicked.connect(self._select_all_spectra)
        self.deselect_all_button.clicked.connect(self._deselect_all_spectra)
        self.filter_select_button.clicked.connect(self._filter_select_spectra)

        self.range_start_spinbox.valueChanged.connect(self._on_range_spinbox_changed)
        self.range_end_spinbox.valueChanged.connect(self._on_range_spinbox_changed)
        self.region_selector.sigRegionChanged.connect(self._on_region_changed)
        self.reset_range_button.clicked.connect(self._reset_find_range)

    def _on_plot_interacted(self):
        """当用户手动缩放或平移图表时，此槽函数被调用。"""
        self.user_has_interacted_with_plot = True
        print("用户已手动交互，自动缩放已暂停。")

    def _reset_plot_view(self):
        """当用户点击“自动范围”按钮时，此槽函数被调用。"""
        self.user_has_interacted_with_plot = False
        self.plot_widget.autoRange()
        print("视图已重置，自动缩放已恢复。")

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        elif event.type() == QEvent.PaletteChange:
            # 当主题发生变化时，更新图表样式
            self._update_plot_styles()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Offline Spectrum Analysis"))
        # 控制面板
        self.data_source_box.toggle_button.setText(self.tr("Data Source"))
        self.spectra_list_label.setText(self.tr("Check to use for averaging:"))

        self.select_all_button.setText(self.tr("Select All"))
        self.deselect_all_button.setText(self.tr("Deselect All"))
        self.filter_select_button.setText(self.tr("Filter Select..."))

        self.processing_box.toggle_button.setText(self.tr("Data Processing"))
        self.avg_button.setText(self.tr("Calculate Average Spectrum"))
        self.clear_avg_button.setText(self.tr("Clear Calculated Results"))
        self.export_summary_button.setText(self.tr("Export Summary Report"))

        self.analysis_box.toggle_button.setText(self.tr("Static Analysis"))
        self.analysis_target_label.setText(self.tr("Analysis Target:"))
        self.peak_method_label.setText(self.tr("Main Peak Algorithm:"))
        self.peak_height_label.setText(self.tr("Minimum Peak Height:"))

        self.range_group.setTitle(self.tr("Spectral Peak Find Range"))
        self.range_start_label.setText(self.tr("Start Position:"))
        self.range_end_label.setText(self.tr("End Position:"))
        self.reset_range_button.setText(self.tr("Reset to (450-750nm)"))

        self.find_main_peak_button.setText(self.tr("Find Main Resonance Peak"))

        self.result_display_group.setTitle(self.tr("Analysis Results"))
        self.peak_wl_label.setText(self.tr("Peak Wavelength (nm):"))
        self.peak_int_label.setText(self.tr("Peak Intensity:"))
        self.peak_fwhm_label.setText(self.tr("FWHM (nm):"))

        self.export_button.setText(self.tr("Export Analysis Results"))
        self.auto_range_button.setText(self.tr("Auto Range"))

        current_method_key = self.peak_method_combo.currentData()
        for index, method_key in enumerate(PEAK_METHOD_KEYS):
            self.peak_method_combo.setItemText(index, self.tr(PEAK_METHOD_LABELS[method_key]))
        if current_method_key is not None:
            restored_index = self.peak_method_combo.findData(current_method_key)
            if restored_index != -1:
                self.peak_method_combo.setCurrentIndex(restored_index)

        avg_index = self.analysis_target_combo.findData(AVERAGE_CURVE_KEY)
        if avg_index != -1:
            self.analysis_target_combo.setItemText(avg_index, self.tr("Average Spectrum"))

        # 图表
        self._update_plot_title()
        self.plot_widget.setLabel('bottom', self.tr('Wavelength (nm)'))

    def _update_plot_title(self):
        """一个专门用于更新图表标题的方法，以便翻译"""
        title = self.tr("Spectrum Analysis Plot (Displaying {0} / {1} curves)").format(
            self.display_spectra_count, self.total_spectra_count
        )
        self.plot_widget.setTitle(title, color='#90A4AE', size='12pt')

    def calculate_average(self):
        if self.calc_thread and self.calc_thread.isRunning():
            QMessageBox.information(self, self.tr("Info"), self.tr("Calculation in progress, please wait..."))
            return
        checked_spectra_y = [data['y'] for key, data in self.spectra.items() if
                             data['list_item'].checkState() == Qt.Checked]
        if not checked_spectra_y:
            QMessageBox.warning(self, self.tr("Info"), self.tr("Please check at least one spectrum."))
            return
        self.avg_button.setEnabled(False)
        self.avg_button.setText(self.tr("Calculating..."))
        self.calc_thread = AverageCalculator(checked_spectra_y)
        self.calc_thread.finished.connect(self._on_average_calculated)
        self.calc_thread.start()

    def _on_average_calculated(self, average_y):
        self.avg_button.setEnabled(True)
        self.avg_button.setText(self.tr("Calculate Average Spectrum"))
        if average_y is None:
            QMessageBox.critical(self, self.tr("Error"),
                                 self.tr("An error occurred while calculating the average spectrum."))
            return
        x_data = next(iter(self.spectra.values()))['x']
        avg_name = self.tr("Average Spectrum")
        self.average_curve_data = {'x': x_data, 'y': average_y, 'name': avg_name}
        pen = pg.mkPen('yellow', width=3)
        if self.average_curve_item is None:
            self.average_curve_item = self.plot_widget.plot(x_data, average_y, pen=pen, name=avg_name)
        else:
            self.average_curve_item.setData(x_data, average_y, pen=pen)
        avg_index = self.analysis_target_combo.findData(AVERAGE_CURVE_KEY)
        if avg_index == -1:
            self.analysis_target_combo.addItem(avg_name, userData=AVERAGE_CURVE_KEY)
            avg_index = self.analysis_target_combo.count() - 1
        else:
            self.analysis_target_combo.setItemText(avg_index, avg_name)
        self.analysis_target_combo.setCurrentIndex(avg_index)

    def clear_average_curve(self):
        if self.average_curve_item:
            self.plot_widget.removeItem(self.average_curve_item)
            self.average_curve_item = None
            self.average_curve_data = None
            avg_index = self.analysis_target_combo.findData(AVERAGE_CURVE_KEY)
            if avg_index != -1:
                self.analysis_target_combo.removeItem(avg_index)

    def update_analysis_target(self, name):
        current_index = self.analysis_target_combo.currentIndex()
        data_key = self.analysis_target_combo.itemData(current_index)

        if data_key == AVERAGE_CURVE_KEY and self.average_curve_data:
            self.main_spectrum_to_analyze = self.average_curve_data
        elif data_key in self.spectra:
            self.main_spectrum_to_analyze = self.spectra[data_key]
        else:
            self.main_spectrum_to_analyze = None

    def analyze_main_peak(self):
        if not self.main_spectrum_to_analyze:
            QMessageBox.warning(self, self.tr("Info"), self.tr("No spectrum available for analysis."))
            return

        x_data, y_data = self.main_spectrum_to_analyze['x'], self.main_spectrum_to_analyze['y']
        min_height = self.peak_height_spinbox.value()

        # 清空旧结果
        self.main_peak_marker.clear()
        self.main_peak_wavelength_label.setText("N/A")
        self.main_peak_intensity_label.setText("N/A")
        self.main_peak_fwhm_label.setText("N/A")

        if y_data is None or len(y_data) == 0: return

        # 1. 从UI获取寻峰范围
        min_wl, max_wl = self.region_selector.getRegion()

        # 2. 创建掩码并裁切数据
        region_indices = np.where((x_data >= min_wl) & (x_data <= max_wl))[0]
        if len(region_indices) < 3:
            print(self.tr("Too few data points in the selected find range."))
            return

        x_subset = x_data[region_indices]
        y_subset = y_data[region_indices]

        method_key = self.peak_method_combo.currentData() or 'highest_point'
        subset_index, peak_wavelength = estimate_peak_position(x_subset, y_subset, method_key)

        if peak_wavelength is None:
            self.main_peak_wavelength_label.setText(self.tr("Not Found"))
            self.main_peak_intensity_label.setText(self.tr("Not Found"))
            print(self.tr("Main resonance peak not found with current settings in the selected region."))
            return

        if subset_index is None or subset_index < 0 or subset_index >= len(x_subset):
            subset_index = int(np.argmin(np.abs(x_subset - peak_wavelength)))

        peak_index_global = region_indices[subset_index]
        peak_intensity = float(y_subset[subset_index])

        if peak_intensity >= min_height:
            peak_x = float(peak_wavelength)
            peak_y = peak_intensity

            self.main_peak_marker.setData([peak_x], [peak_y])
            self.main_peak_wavelength_label.setText(f"{peak_x:.4f}")
            self.main_peak_intensity_label.setText(f"{peak_y:.4f}")

            try:
                fwhm_results = calculate_fwhm(x_data, y_data, [peak_index_global])
                if fwhm_results:
                    self.main_peak_fwhm_label.setText(f"{fwhm_results[0]:.4f}")
                else:
                    self.main_peak_fwhm_label.setText(self.tr("Calculation failed"))
            except Exception:
                self.main_peak_fwhm_label.setText(self.tr("Error"))

            print(self.tr("Found main resonance peak @ {0:.2f} nm, Intensity: {1:.2f}").format(peak_x, peak_y))
        else:
            self.main_peak_wavelength_label.setText(self.tr("Not Found"))
            self.main_peak_intensity_label.setText(self.tr("Not Found"))
            print(self.tr("Main resonance peak not found with current settings in the selected region."))

    def _trigger_summary_report(self):
        if self.report_worker and self.report_worker.isRunning():
            QMessageBox.information(self, self.tr("Info"),
                                    self.tr("Report generation is already in progress, please wait..."))
            return
        checked_spectra = {key: data for key, data in self.spectra.items() if
                           data['list_item'].checkState() == Qt.Checked}
        if not checked_spectra:
            QMessageBox.warning(self, self.tr("Info"),
                                self.tr("Please check at least one spectrum to generate a report."))
            return
        default_save_path = self.app_settings.get('default_save_path', '')
        folder_path = QFileDialog.getExistingDirectory(self, self.tr("Select folder to save summary report"),
                                                       default_save_path)
        if not folder_path: return
        self.export_summary_button.setEnabled(False)
        self.export_summary_button.setText(self.tr("Generating..."))
        self.report_worker = SummaryReportWorker(checked_spectra, folder_path)
        self.report_worker.finished.connect(self._on_summary_report_finished)
        self.report_worker.start()

    def _on_summary_report_finished(self, status, report_path):
        self.export_summary_button.setEnabled(True)
        self.export_summary_button.setText(self.tr("Export Summary Report"))
        if status == "success":
            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Summary report successfully generated:\n{0}").format(report_path))
        else:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Failed to generate report:\n{0}").format(status))

    def _export_analysis_results(self):
        if not self.main_spectrum_to_analyze:
            QMessageBox.warning(self, self.tr("Info"),
                                self.tr("Please select a spectrum in the 'Analysis Target' dropdown first."))
            return
        if self.main_peak_wavelength_label.text() == "N/A":
            QMessageBox.warning(self, self.tr("Info"),
                                self.tr("Please click 'Find Main Resonance Peak' for the selected spectrum first."))
            return
        default_save_path = self.app_settings.get('default_save_path', '')
        folder_path = QFileDialog.getExistingDirectory(self, self.tr("Select folder to save results"),
                                                       default_save_path)
        if not folder_path: return
        try:
            object_name = re.sub(r'[\\/*?:"<>|]', "", self.main_spectrum_to_analyze['name'])
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            output_folder = os.path.join(folder_path, f"Analysis_{object_name}_{timestamp}")
            os.makedirs(output_folder)

            if all([self.source_signal, self.source_background, self.source_reference]):
                df_data = {
                    'Wavelength (nm)': self.source_signal[0], 'Signal Intensity': self.source_signal[1],
                    'Background Intensity': self.source_background[1], 'Reference Intensity': self.source_reference[1],
                    'Calculated Absorbance': self.main_spectrum_to_analyze['y']
                }
                df = pd.DataFrame(df_data)
                table_path = os.path.join(output_folder, "full_absorbance_data.xlsx")
            else:
                df_data = {
                    'Wavelength (nm)': self.main_spectrum_to_analyze['x'],
                    'Value': self.main_spectrum_to_analyze['y']
                }
                df = pd.DataFrame(df_data)
                table_path = os.path.join(output_folder, "spectrum_data.xlsx")
            df.to_excel(table_path, index=False, engine='openpyxl')

            peak_metrics = {
                'Parameter': ['Peak Wavelength (nm)', 'Peak Intensity', 'FWHM (nm)'],
                'Value': [
                    self.main_peak_wavelength_label.text(), self.main_peak_intensity_label.text(),
                    self.main_peak_fwhm_label.text()
                ]
            }
            df_metrics = pd.DataFrame(peak_metrics)
            metrics_path = os.path.join(output_folder, "peak_metrics.xlsx")
            df_metrics.to_excel(metrics_path, index=False)

            exporter = pg.exporters.ImageExporter(self.plot_widget.plotItem)
            image_path = os.path.join(output_folder, "spectrum_plot.png")
            exporter.export(image_path)

            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Analysis results have been exported to:\n{0}").format(output_folder))
        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"),
                                 self.tr("An error occurred while exporting files: {0}").format(str(e)))

    def _update_curve_visibility(self, item):
        """
        一个专门用于响应列表项勾选状态变化的新函数。
        包含智能自动缩放逻辑。
        """
        # 通过 "身份证" (UserRole) 获取唯一的 key
        unique_key = item.data(Qt.UserRole)

        # 使用 unique_key 从字典中安全地获取正确的光谱数据
        if unique_key and unique_key in self.spectra:
            spectrum_data = self.spectra[unique_key]
            if spectrum_data['curve']:
                is_checked = (item.checkState() == Qt.Checked)
                spectrum_data['curve'].setVisible(is_checked)

                if not self.user_has_interacted_with_plot:
                    self.plot_widget.autoRange()

                self._update_display_count_and_title()

    def _select_all_spectra(self):
        """将列表中的所有项设置为勾选状态。"""
        # 阻止信号循环触发，以提高性能
        self.spectra_list_widget.blockSignals(True)
        for i in range(self.spectra_list_widget.count()):
            item = self.spectra_list_widget.item(i)
            item.setCheckState(Qt.Checked)
        self.spectra_list_widget.blockSignals(False)
        # 手动触发一次更新
        for item in self.spectra.values():
            if item['curve']:
                item['curve'].show()
        self._update_display_count_and_title()

    def _deselect_all_spectra(self):
        """将列表中的所有项设置为未勾选状态。"""
        self.spectra_list_widget.blockSignals(True)
        for i in range(self.spectra_list_widget.count()):
            item = self.spectra_list_widget.item(i)
            item.setCheckState(Qt.Unchecked)
        self.spectra_list_widget.blockSignals(False)
        # 手动触发一次更新
        for item in self.spectra.values():
            if item['curve']:
                item['curve'].hide()
        self._update_display_count_and_title()

    def _filter_select_spectra(self):
        """弹出一个输入框，根据关键词筛选并勾选列表项。"""
        text, ok = QInputDialog.getText(self, self.tr("Filter Selection"),
                                        self.tr("Enter keyword to select spectra:"))

        if ok and text:
            keyword = text.lower()  # 转换为小写以便不区分大小写匹配
            self.spectra_list_widget.blockSignals(True)
            # 现在遍历列表中的每一项，而不是遍历不完整的数据字典
            for i in range(self.spectra_list_widget.count()):
                item = self.spectra_list_widget.item(i)
                item_text = item.text().lower()

                # 根据关键词设置复选框状态
                should_be_checked = (keyword in item_text)
                item.setCheckState(Qt.Checked if should_be_checked else Qt.Unchecked)

                # 直接找到与该列表项关联的曲线并更新其可见性
                # (这依赖于下面对 set_initial_data 和 _update_curve_visibility 的修改)
                unique_key = item.data(Qt.UserRole)
                if unique_key and unique_key in self.spectra:
                    spectrum_data = self.spectra[unique_key]
                    if spectrum_data['curve']:
                        spectrum_data['curve'].setVisible(should_be_checked)

            self.spectra_list_widget.blockSignals(False)

            self._update_display_count_and_title()

            # 在所有可见性更新完成后，进行一次智能缩放
            if not self.user_has_interacted_with_plot:
                self.plot_widget.autoRange()

    def closeEvent(self, event):
        pg.setConfigOption('background', '#F0F0F0');
        pg.setConfigOption('foreground', 'k')
        if self.parent() and hasattr(self.parent(), 'analysis_windows') and self in self.parent().analysis_windows:
            self.parent().analysis_windows.remove(self)
        super().closeEvent(event)

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

    def _reset_find_range(self):
        """当用户点击“重置范围”按钮时，将范围设为450-750nm。"""
        self.range_start_spinbox.setValue(450.0)
        self.range_end_spinbox.setValue(750.0)
        # Spinbox的 valueChanged 信号会自动触发 _on_range_spinbox_changed，从而更新图表

    def _update_plot_styles(self):
        """根据当前主题更新图表样式"""
        try:
            from ..utils.config_manager import load_settings
            settings = load_settings()
            theme = settings.get('theme', 'dark')
            
            # 定义不同主题的样式
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
                
            # 更新图表的背景和样式
            self.plot_widget.setBackground(background_color)
            self.plot_widget.showGrid(x=True, y=True, alpha=grid_alpha)
            # 设置坐标轴和坐标文本颜色
            for axis in ("left", "bottom"):
                ax = self.plot_widget.getPlotItem().getAxis(axis)
                ax.setPen(axis_pen)
                ax.setTextPen(text_pen)
        except Exception:
            pass  # 忽略错误
