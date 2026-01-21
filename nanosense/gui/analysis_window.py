# nanosense/gui/analysis_window.py

import os
import time
import re
import pandas as pd
import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
from scipy.stats import skew
from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
                             QPushButton, QComboBox, QFormLayout, QDoubleSpinBox, QLabel, QGroupBox,
                             QMessageBox, QFileDialog, QInputDialog, QScrollArea, QCheckBox, QDialog,
                             QButtonGroup, QTableWidget, QTableWidgetItem, QHeaderView, QToolTip)
from PyQt5.QtGui import QCursor
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QEvent
from PyQt5.QtGui import QPalette

from nanosense.algorithms.peak_analysis import (
    calculate_fwhm,
    PEAK_METHOD_KEYS,
    PEAK_METHOD_LABELS,
    estimate_peak_position,
)
from nanosense.algorithms.preprocessing import baseline_als, smooth_savitzky_golay
from .collapsible_box import CollapsibleBox
from .preprocessing_dialog import PreprocessingDialog


class SummaryReportWorker(QThread):
    """一个专门在后台批量分析并生成汇总报告的工作线程。"""
    progress = pyqtSignal(int, str)  # 发射进度（百分比，消息）
    finished = pyqtSignal(str, str)  # 发射（成功消息/错误消息，报告文件夹路径）

    def __init__(self, spectra_to_process, output_folder, preprocessing_params=None,
                 apply_baseline=False, apply_smoothing=False, preprocessing_enabled=True,
                 find_range=None, noise_range=None, peak_method='highest_point', 
                 min_height=0.1, parent=None):
        super().__init__(parent)
        self.spectra = spectra_to_process
        self.output_folder = output_folder
        self.preprocessing_params = preprocessing_params or {}
        self.apply_baseline = apply_baseline
        self.apply_smoothing = apply_smoothing
        self.preprocessing_enabled = preprocessing_enabled
        self.find_range = find_range
        self.noise_range = noise_range or (450.0, 750.0)
        self.peak_method = peak_method
        self.min_height = min_height

    def _preprocess_intensity(self, intensity):
        """应用预处理（基线校正和平滑）"""
        if not self.preprocessing_enabled:
            return np.asarray(intensity)
        working = np.asarray(intensity)
        if self.apply_baseline:
            als_lambda = self.preprocessing_params.get("als_lambda", 1e9)
            als_p = self.preprocessing_params.get("als_p", 0.01)
            baseline = baseline_als(working, lam=als_lambda, p=als_p)
            working = working - baseline
        if self.apply_smoothing:
            sg_window_coarse = self.preprocessing_params.get("sg_window_coarse", 14)
            sg_poly_coarse = self.preprocessing_params.get("sg_polyorder_coarse", 3)
            sg_window_fine = self.preprocessing_params.get("sg_window_fine", 8)
            sg_poly_fine = self.preprocessing_params.get("sg_polyorder_fine", 3)
            sg_two_stage = self.preprocessing_params.get("sg_two_stage", True)
            coarse = smooth_savitzky_golay(working, window_length=sg_window_coarse, polyorder=sg_poly_coarse)
            if sg_two_stage:
                working = smooth_savitzky_golay(coarse, window_length=sg_window_fine, polyorder=sg_poly_fine)
            else:
                working = coarse
        return working

    def _format_value(self, value, precision=4):
        """格式化数值显示"""
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return "N/A"
        if isinstance(value, (int, float)):
            return f"{value:.{precision}f}"
        return str(value)

    def run(self):
        try:
            # 0-5%: 创建带时间戳的输出文件夹
            self.progress.emit(0, "Creating output folder...")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            report_folder = os.path.join(self.output_folder, f"Summary_Report_{timestamp}")
            os.makedirs(report_folder, exist_ok=True)
            self.progress.emit(5, "Output folder created")

            total_spectra = len(self.spectra)
            
            # 获取寻峰范围和噪声范围
            min_wl, max_wl = self.find_range if self.find_range else (450.0, 750.0)
            if min_wl > max_wl:
                min_wl, max_wl = max_wl, min_wl
            
            noise_start, noise_end = self.noise_range
            if noise_start > noise_end:
                noise_start, noise_end = noise_end, noise_start

            # 5-65%: 计算所有光谱的完整指标
            all_peak_wls = []  # 用于计算重复性
            all_peak_ints = []
            row_calculations = []

            for i, (name, data) in enumerate(self.spectra.items()):
                progress_pct = 5 + int((i / total_spectra) * 60)
                self.progress.emit(progress_pct, f"Analyzing: {name}")
                
                x_data = np.asarray(data['x'])
                y_data = self._preprocess_intensity(data['y'])

                # 初始化指标字典
                metrics = {
                    "Spectrum": data.get("name", name),
                    "peak_wl": np.nan, "peak_int": np.nan, "fwhm": np.nan,
                    "rms_noise": np.nan, "c_noise": np.nan, "snr": np.nan,
                    "q_factor": np.nan, "peak_area": np.nan,
                    "skewness": np.nan, "slope": np.nan, "ripple": np.nan,
                    "noise_mean": np.nan  # 噪声区域均值，用于 LOB/LOD/LOQ
                }

                # 定义掩码
                range_mask = (x_data >= min_wl) & (x_data <= max_wl)
                noise_mask = (x_data >= noise_start) & (x_data <= noise_end)

                # A. 寻峰与峰形分析
                peak_index_global = None
                if np.count_nonzero(range_mask) >= 3:
                    x_subset = x_data[range_mask]
                    y_subset = np.asarray(y_data)[range_mask]

                    # 计算偏度
                    try:
                        metrics['skewness'] = float(skew(y_subset)) if len(y_subset) > 0 else np.nan
                    except Exception:
                        pass

                    # 寻峰
                    subset_index, peak_wavelength = estimate_peak_position(x_subset, y_subset, self.peak_method)
                    if peak_wavelength is not None:
                        if subset_index is None or subset_index < 0 or subset_index >= len(x_subset):
                            subset_index = int(np.argmin(np.abs(x_subset - peak_wavelength)))

                        peak_value = float(y_subset[subset_index])
                        if peak_value >= self.min_height:
                            metrics['peak_wl'] = float(peak_wavelength)
                            metrics['peak_int'] = peak_value

                            global_indices = np.where(range_mask)[0]
                            peak_index_global = int(global_indices[subset_index])

                            # 计算 FWHM
                            fwhm_results = calculate_fwhm(x_data, y_data, [peak_index_global])
                            if fwhm_results:
                                metrics['fwhm'] = fwhm_results[0]

                            # 计算 Q Factor
                            if not np.isnan(metrics['peak_wl']) and metrics.get('fwhm', 0) > 0:
                                metrics['q_factor'] = metrics['peak_wl'] / metrics['fwhm']

                            # 收集数据用于重复性统计
                            all_peak_wls.append(metrics['peak_wl'])
                            all_peak_ints.append(metrics['peak_int'])

                # B. 噪声与基线分析
                if np.count_nonzero(noise_mask) >= 3:
                    x_noise = x_data[noise_mask]
                    y_noise = np.asarray(y_data)[noise_mask]
                    
                    # 记录噪声区域的原始均值（用于 LOB/LOD/LOQ 计算）
                    metrics['noise_mean'] = float(np.mean(y_noise))

                    # 线性拟合计算基线斜率
                    if np.ptp(x_noise) > 0:
                        slope, intercept = np.polyfit(x_noise, y_noise, 1)
                        metrics['slope'] = float(slope)
                        detrended = y_noise - (slope * x_noise + intercept)
                    else:
                        detrended = y_noise - np.mean(y_noise)
                        metrics['slope'] = 0.0

                    # 计算噪声指标
                    metrics['rms_noise'] = float(np.sqrt(np.mean(detrended ** 2)))
                    metrics['c_noise'] = float(np.ptp(detrended))
                    metrics['ripple'] = float(np.std(detrended))

                # C. 衍生指标 SNR
                if not np.isnan(metrics['peak_int']) and metrics['rms_noise'] > 0:
                    metrics['snr'] = float(metrics['peak_int'] / metrics['rms_noise'])

                # D. 峰面积积分
                if np.count_nonzero(range_mask) >= 2:
                    interval = None
                    if peak_index_global is not None and not np.isnan(metrics['fwhm']) and not np.isnan(metrics['peak_wl']):
                        interval = (metrics['peak_wl'] - 1.5 * metrics['fwhm'], 
                                   metrics['peak_wl'] + 1.5 * metrics['fwhm'])
                    
                    if interval is None:
                        interval = (min_wl, max_wl)

                    left_x, right_x = sorted(interval)
                    left_x = max(left_x, np.min(x_data))
                    right_x = min(right_x, np.max(x_data))

                    area_mask = (x_data >= left_x) & (x_data <= right_x)
                    if np.count_nonzero(area_mask) >= 2:
                        metrics['peak_area'] = float(np.trapz(y_data[area_mask], x_data[area_mask]))

                row_calculations.append(metrics)

            # 65-70%: 计算群体统计指标（重复性）
            self.progress.emit(65, "Calculating repeatability statistics...")
            stats = {
                'wl_mean': np.nan, 'wl_std': np.nan, 'wl_cv': np.nan,
                'int_mean': np.nan, 'int_std': np.nan, 'int_cv': np.nan
            }

            if len(all_peak_wls) > 1:
                stats['wl_mean'] = np.mean(all_peak_wls)
                stats['wl_std'] = np.std(all_peak_wls, ddof=1)
                stats['wl_cv'] = (stats['wl_std'] / stats['wl_mean'] * 100) if stats['wl_mean'] != 0 else 0

            if len(all_peak_ints) > 1:
                stats['int_mean'] = np.mean(all_peak_ints)
                stats['int_std'] = np.std(all_peak_ints, ddof=1)
                stats['int_cv'] = (stats['int_std'] / stats['int_mean'] * 100) if stats['int_mean'] != 0 else 0

            # 70-80%: 生成 600dpi 高清叠加光谱图
            self.progress.emit(70, "Generating 600dpi overlay spectrum plot...")
            self._generate_overlay_plot(report_folder, min_wl, max_wl)
            self.progress.emit(80, "Overlay plot generated")

            # 80-95%: 生成多 Sheet Excel 报表
            self.progress.emit(80, "Generating Excel report...")
            
            # Sheet 1: Detailed Metrics - 所有 18 项指标
            detailed_metrics_data = []
            for m in row_calculations:
                row_data = {
                    'Spectrum': m['Spectrum'],
                    'Peak Wavelength (nm)': m['peak_wl'],
                    'Peak Intensity': m['peak_int'],
                    'FWHM (nm)': m['fwhm'],
                    'RMS Noise': m['rms_noise'],
                    'C Noise': m['c_noise'],
                    'SNR': m['snr'],
                    'Q Factor': m['q_factor'],
                    'Peak Area': m['peak_area'],
                    'Skewness': m['skewness'],
                    'Baseline Slope': m['slope'],
                    'Baseline Ripple': m['ripple'],
                    'Repeatability WL Mean': stats['wl_mean'],
                    'Repeatability WL Std': stats['wl_std'],
                    'Repeatability WL CV%': stats['wl_cv'],
                    'Repeatability Int Mean': stats['int_mean'],
                    'Repeatability Int Std': stats['int_std'],
                    'Repeatability Int CV%': stats['int_cv'],
                }
                detailed_metrics_data.append(row_data)

            detailed_df = pd.DataFrame(detailed_metrics_data)

            # Sheet 2: Statistics Summary - 统计汇总
            self.progress.emit(85, "Calculating statistics summary...")
            stats_columns = ['Peak Wavelength (nm)', 'Peak Intensity', 'FWHM (nm)', 
                           'RMS Noise', 'SNR', 'Q Factor', 'Peak Area']
            stats_summary = detailed_df[stats_columns].agg(['mean', 'std', 'min', 'max']).T
            stats_summary['CV (%)'] = (stats_summary['std'] / stats_summary['mean']) * 100

            # Sheet 3: All Spectra Data - 所有光谱原始数据
            self.progress.emit(90, "Preparing all spectra data...")
            avg_x = next(iter(self.spectra.values()))['x']
            all_spectra_dict = {'Wavelength (nm)': avg_x}
            for name, data in self.spectra.items():
                all_spectra_dict[data.get('name', name)] = self._preprocess_intensity(data['y'])
            all_spectra_df = pd.DataFrame(all_spectra_dict)

            # Sheet 4: Average Spectrum - 平均光谱
            avg_y = np.mean([self._preprocess_intensity(data['y']) for data in self.spectra.values()], axis=0)
            avg_spectrum_df = pd.DataFrame({
                'Wavelength (nm)': avg_x,
                'Average Intensity': avg_y
            })

            # 写入 Excel 文件
            excel_path = os.path.join(report_folder, "summary_metrics.xlsx")
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                detailed_df.to_excel(writer, sheet_name='Detailed Metrics', index=False)
                stats_summary.to_excel(writer, sheet_name='Statistics Summary')
                all_spectra_df.to_excel(writer, sheet_name='All Spectra Data', index=False)
                avg_spectrum_df.to_excel(writer, sheet_name='Average Spectrum', index=False)

            self.progress.emit(95, "Excel report generated")

            # 100%: 完成
            self.progress.emit(100, "Report generation complete!")
            self.finished.emit("success", report_folder)

        except Exception as e:
            import traceback
            error_message = f"An error occurred while generating the summary report: {e}\n{traceback.format_exc()}"
            print(error_message)
            self.finished.emit(error_message, "")

    def _generate_overlay_plot(self, output_folder, min_wl, max_wl):
        """生成 600dpi 高清叠加光谱图"""
        try:
            import matplotlib
            matplotlib.use('Agg')  # 使用非交互式后端
            import matplotlib.pyplot as plt
            
            # 设置样式
            plt.rcParams.update({
                "font.family": "Times New Roman",
                "font.size": 10,
                "axes.linewidth": 1.2,
            })
            
            fig, ax = plt.subplots(figsize=(8, 6), dpi=600)
            
            # 绘制所有光谱
            colors = plt.cm.tab20(np.linspace(0, 1, len(self.spectra)))
            for idx, (name, data) in enumerate(self.spectra.items()):
                x_vals = np.asarray(data['x'])
                y_vals = self._preprocess_intensity(data['y'])
                
                # 只绘制在范围内的数据
                mask = (x_vals >= min_wl) & (x_vals <= max_wl)
                if np.any(mask):
                    ax.plot(x_vals[mask], y_vals[mask], 
                           linewidth=0.8, color=colors[idx], 
                           label=data.get('name', name), alpha=0.7)
            
            ax.set_xlim(min_wl, max_wl)
            ax.set_xlabel("Wavelength (nm)", fontsize=12, fontweight='bold')
            ax.set_ylabel("Intensity", fontsize=12, fontweight='bold')
            ax.set_title("Overlay Spectrum Analysis", fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3, linestyle='--')
            
            # 添加图例（如果光谱不太多）
            if len(self.spectra) <= 20:
                ax.legend(loc='best', fontsize=8, framealpha=0.9)
            
            fig.tight_layout()
            image_path = os.path.join(output_folder, "overlay_spectrum.png")
            fig.savefig(image_path, dpi=600, bbox_inches='tight')
            plt.close(fig)
            
        except Exception as e:
            print(f"Warning: Failed to generate overlay plot with matplotlib: {e}")
            # 如果 matplotlib 失败，跳过图片生成（或使用 pyqtgraph 作为后备）

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

        default_preprocessing_params = {
            'als_lambda': 1e9,
            'als_p': 0.01,
            'sg_window_coarse': 14,
            'sg_polyorder_coarse': 3,
            'sg_window_fine': 8,
            'sg_polyorder_fine': 3,
            'sg_two_stage': True
        }
        stored_params = self.app_settings.get("analysis_preprocessing_params")
        self.preprocessing_params = default_preprocessing_params.copy()
        if isinstance(stored_params, dict):
            self.preprocessing_params.update(stored_params)
        self.preprocessing_enabled_default = bool(self.app_settings.get("analysis_preprocessing_enabled", True))
        self.apply_baseline_default = bool(self.app_settings.get("analysis_baseline_enabled", False))
        self.apply_smoothing_default = bool(self.app_settings.get("analysis_smoothing_enabled", True))

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
        self.current_category_filter = "absorbance"
        self.metrics_table = None
        self.metrics_headers = []

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
        main_layout.addWidget(control_panel, stretch=1)
        main_layout.addWidget(plot_widget, stretch=2)

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

            category = spec_dict.get('category') or "absorbance"
            self.spectra[key] = {
                'x': x,
                'y': y,
                'name': name,
                'curve': curve_item,
                'list_item': item,
                'category': category
            }
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

        self._apply_category_filter(self.current_category_filter)
        self._maybe_focus_plot_to_peak_range()
        self._auto_y_range()
        self._refresh_metrics_table()
        self._auto_y_range()

        self._refresh_plot_curves()

    def _update_display_count_and_title(self):
        """
        【新增】重新计算当前显示的曲线数量，并更新图表标题。
        """
        # 遍历列表，统计被勾选的项目数量
        checked_count = 0
        for i in range(self.spectra_list_widget.count()):
            item = self.spectra_list_widget.item(i)
            if item.checkState() == Qt.Checked and not item.isHidden():
                checked_count += 1

        self.display_spectra_count = checked_count
        self._update_plot_title()  # 调用现有的标题更新方法

    def _maybe_focus_plot_to_peak_range(self):
        if self.user_has_interacted_with_plot:
            return
        if not self.spectra:
            return
        x_min = None
        x_max = None
        for data in self.spectra.values():
            x_vals = np.asarray(data.get('x'))
            if x_vals.size == 0:
                continue
            x_min = np.min(x_vals) if x_min is None else min(x_min, np.min(x_vals))
            x_max = np.max(x_vals) if x_max is None else max(x_max, np.max(x_vals))
        if x_min is None or x_max is None:
            return
        range_min, range_max = self.region_selector.getRegion()
        if range_min > range_max:
            range_min, range_max = range_max, range_min
        full_span = x_max - x_min
        peak_span = range_max - range_min
        if peak_span > 0 and full_span > peak_span * 1.5:
            self.plot_widget.setXRange(range_min, range_max, padding=0)

    def _auto_y_range(self):
        if self.user_has_interacted_with_plot:
            return
        if not self.spectra:
            return
        range_min, range_max = self.region_selector.getRegion()
        if range_min > range_max:
            range_min, range_max = range_max, range_min
        noise_min = self.noise_range_start_spinbox.value()
        noise_max = self.noise_range_end_spinbox.value()
        if noise_min > noise_max:
            noise_min, noise_max = noise_max, noise_min

        y_min = None
        y_max = None
        for data in self.spectra.values():
            if data['list_item'].checkState() != Qt.Checked:
                continue
            if data['list_item'].isHidden():
                continue
            x_vals = np.asarray(data.get('x'))
            if x_vals.size == 0:
                continue
            y_vals = np.asarray(self._get_display_intensity(data.get('y')))
            mask = ((x_vals >= range_min) & (x_vals <= range_max)) | (
                (x_vals >= noise_min) & (x_vals <= noise_max)
            )
            if not np.any(mask):
                continue
            y_subset = y_vals[mask]
            y_min = np.min(y_subset) if y_min is None else min(y_min, np.min(y_subset))
            y_max = np.max(y_subset) if y_max is None else max(y_max, np.max(y_subset))
        if y_min is None or y_max is None:
            return
        y_span = y_max - y_min
        padding = y_span * 0.1 if y_span > 0 else 1e-6
        self.plot_widget.setYRange(y_min - padding, y_max + padding, padding=0)

    def _format_value(self, value, precision=4):
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return "N/A"
        if isinstance(value, (int, float)):
            return f"{value:.{precision}f}"
        return str(value)

    def _find_half_max_interval(self, x_data, y_data, peak_index):
        if peak_index is None or peak_index < 0 or peak_index >= len(y_data):
            return None
        peak_value = y_data[peak_index]
        if peak_value == 0 or np.isnan(peak_value):
            return None
        half_value = peak_value / 2.0

        left_cross = None
        for i in range(peak_index, 0, -1):
            if (y_data[i] - half_value) * (y_data[i - 1] - half_value) <= 0:
                x0, x1 = x_data[i - 1], x_data[i]
                y0, y1 = y_data[i - 1], y_data[i]
                if y1 != y0:
                    ratio = (half_value - y0) / (y1 - y0)
                    left_cross = x0 + ratio * (x1 - x0)
                else:
                    left_cross = x0
                break

        right_cross = None
        for i in range(peak_index, len(y_data) - 1):
            if (y_data[i] - half_value) * (y_data[i + 1] - half_value) <= 0:
                x0, x1 = x_data[i], x_data[i + 1]
                y0, y1 = y_data[i], y_data[i + 1]
                if y1 != y0:
                    ratio = (half_value - y0) / (y1 - y0)
                    right_cross = x0 + ratio * (x1 - x0)
                else:
                    right_cross = x1
                break

        if left_cross is None or right_cross is None:
            return None
        return left_cross, right_cross

    def _refresh_metrics_table(self):
        """
        刷新表格：计算所有光谱的指标（含 Q Factor、重复性、LOD等）。
        此方法替代了原始逻辑，支持更丰富的分析参数。
        """
        if not self.metrics_table:
            return

        # 1. 筛选当前分类下的光谱
        filtered_items = [
            (key, data) for key, data in self.spectra.items()
            if (data.get("category") or "absorbance") == self.current_category_filter
        ]

        # 2. 获取参数设置
        min_wl, max_wl = self.region_selector.getRegion()
        if min_wl > max_wl:
            min_wl, max_wl = max_wl, min_wl

        noise_start = self.noise_range_start_spinbox.value()
        noise_end = self.noise_range_end_spinbox.value()
        if noise_start > noise_end:
            noise_start, noise_end = noise_end, noise_start

        method_key = self.peak_method_combo.currentData() or 'highest_point'
        min_height = self.peak_height_spinbox.value()

        # 用于计算“重复性”的列表 (这是原文件中没有的新变量)
        all_peak_wls = []
        all_peak_ints = []

        # 临时存储每行的单体指标
        row_calculations = []

        # --- 第一步：遍历所有光谱，计算单体指标 ---
        for key, data in filtered_items:
            x_data = np.asarray(data['x'])
            raw_y = data['y']
            y_data = self._get_intensity_for_processing(raw_y)

            # 初始化指标字典 (原文件使用的是分散变量，这里统一用字典管理)
            metrics = {
                "name": data.get("name", ""),
                "peak_wl": np.nan, "peak_int": np.nan, "fwhm": np.nan,
                "rms_noise": np.nan, "c_noise": np.nan, "snr": np.nan,
                "q_factor": np.nan,  # <--- 【新增】初始化 Q Factor
                "peak_area": np.nan,
                "skewness": np.nan, "slope": np.nan, "ripple": np.nan,
                "noise_mean": np.nan  # 噪声区域均值，用于 LOB/LOD/LOQ
            }

            # 掩码定义
            range_mask = (x_data >= min_wl) & (x_data <= max_wl)
            noise_mask = (x_data >= noise_start) & (x_data <= noise_end)

            # A. 寻峰与峰形分析
            peak_index_global = None
            if np.count_nonzero(range_mask) >= 3:
                x_subset = x_data[range_mask]
                y_subset = np.asarray(y_data)[range_mask]

                # 计算偏度 (需确保头部导入了 skew: from scipy.stats import skew)
                try:
                    from scipy.stats import skew
                    metrics['skewness'] = float(skew(y_subset)) if len(y_subset) > 0 else np.nan
                except ImportError:
                    pass

                subset_index, peak_wavelength = estimate_peak_position(x_subset, y_subset, method_key)
                if peak_wavelength is not None:
                    if subset_index is None or subset_index < 0 or subset_index >= len(x_subset):
                        subset_index = int(np.argmin(np.abs(x_subset - peak_wavelength)))

                    peak_value = float(y_subset[subset_index])
                    if peak_value >= min_height:
                        metrics['peak_wl'] = float(peak_wavelength)
                        metrics['peak_int'] = peak_value

                        global_indices = np.where(range_mask)[0]
                        peak_index_global = int(global_indices[subset_index])

                        fwhm_results = calculate_fwhm(x_data, y_data, [peak_index_global])
                        if fwhm_results:
                            metrics['fwhm'] = fwhm_results[0]

                        # ================= [新增代码] 计算 Q Factor =================
                        # 公式: Q = Peak Wavelength / FWHM
                        if not np.isnan(metrics['peak_wl']) and metrics.get('fwhm', 0) > 0:
                            metrics['q_factor'] = metrics['peak_wl'] / metrics['fwhm']
                        else:
                            metrics['q_factor'] = np.nan
                        # ==========================================================

                        # 收集数据用于后续的群体统计
                        all_peak_wls.append(metrics['peak_wl'])
                        all_peak_ints.append(metrics['peak_int'])

            # B. 噪声与基线分析
            if np.count_nonzero(noise_mask) >= 3:
                x_noise = x_data[noise_mask]
                y_noise = np.asarray(y_data)[noise_mask]
                
                # 记录噪声区域的原始均值（用于 LOB/LOD/LOQ 计算）
                metrics['noise_mean'] = float(np.mean(y_noise))

                # 线性拟合计算基线斜率
                if np.ptp(x_noise) > 0:
                    slope, intercept = np.polyfit(x_noise, y_noise, 1)
                    metrics['slope'] = float(slope)
                    detrended = y_noise - (slope * x_noise + intercept)
                else:
                    detrended = y_noise - np.mean(y_noise)
                    metrics['slope'] = 0.0

                # 计算噪声指标
                metrics['rms_noise'] = float(np.sqrt(np.mean(detrended ** 2)))
                metrics['c_noise'] = float(np.ptp(detrended))
                metrics['ripple'] = float(np.std(detrended))

            # C. 衍生指标 SNR
            if not np.isnan(metrics['peak_int']) and metrics['rms_noise'] > 0:
                metrics['snr'] = float(metrics['peak_int'] / metrics['rms_noise'])

            # D. 峰面积积分
            if np.count_nonzero(range_mask) >= 2:
                interval = None
                if peak_index_global is not None and not np.isnan(metrics['fwhm']) and not np.isnan(metrics['peak_wl']):
                    interval = (metrics['peak_wl'] - 1.5 * metrics['fwhm'], metrics['peak_wl'] + 1.5 * metrics['fwhm'])

                if interval is None:
                    interval = (min_wl, max_wl)

                left_x, right_x = sorted(interval)
                left_x = max(left_x, np.min(x_data))
                right_x = min(right_x, np.max(x_data))

                area_mask = (x_data >= left_x) & (x_data <= right_x)
                if np.count_nonzero(area_mask) >= 2:
                    metrics['peak_area'] = float(np.trapz(y_data[area_mask], x_data[area_mask]))

            row_calculations.append(metrics)

        # --- 第二步：计算群体统计指标 (重复性) ---
        stats = {
            'wl_mean': np.nan, 'wl_std': np.nan, 'wl_cv': np.nan,
            'int_mean': np.nan, 'int_std': np.nan, 'int_cv': np.nan
        }

        if len(all_peak_wls) > 1:
            stats['wl_mean'] = np.mean(all_peak_wls)
            stats['wl_std'] = np.std(all_peak_wls, ddof=1)
            stats['wl_cv'] = (stats['wl_std'] / stats['wl_mean'] * 100) if stats['wl_mean'] != 0 else 0

        if len(all_peak_ints) > 1:
            stats['int_mean'] = np.mean(all_peak_ints)
            stats['int_std'] = np.std(all_peak_ints, ddof=1)
            stats['int_cv'] = (stats['int_std'] / stats['int_mean'] * 100) if stats['int_mean'] != 0 else 0

        # --- 第三步：填充表格 ---
        self.metrics_table.setRowCount(len(row_calculations))

        for row, m in enumerate(row_calculations):
            # 准备显示数据 (注意顺序必须与 metrics_headers 完全一致)
            row_values = [
                m['name'],
                self._format_value(m['peak_wl']),
                self._format_value(m['peak_int']),
                self._format_value(m['fwhm']),
                self._format_value(m['rms_noise'], precision=6),
                self._format_value(m['c_noise'], precision=6),
                self._format_value(m['snr'], precision=2),
                self._format_value(m['q_factor'], precision=2),
                self._format_value(m['peak_area']),
                self._format_value(m['skewness'], precision=3),
                self._format_value(m['slope'], precision=6),
                self._format_value(m['ripple'], precision=6),
                # 重复性
                self._format_value(stats['wl_mean']),
                self._format_value(stats['wl_std'], precision=5),
                self._format_value(stats['wl_cv'], precision=3) + "%" if not np.isnan(stats['wl_cv']) else "N/A",
                self._format_value(stats['int_mean']),
                self._format_value(stats['int_std'], precision=5),
                self._format_value(stats['int_cv'], precision=3) + "%" if not np.isnan(stats['int_cv']) else "N/A",
            ]

            for col, value in enumerate(row_values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.metrics_table.setItem(row, col, item)

    def _set_category_filter(self, category):
        if self.current_category_filter == category:
            return
        self.current_category_filter = category
        self._apply_category_filter(category)

    def _apply_category_filter(self, category):
        for i in range(self.spectra_list_widget.count()):
            item = self.spectra_list_widget.item(i)
            unique_key = item.data(Qt.UserRole)
            spectrum_data = self.spectra.get(unique_key)
            spectrum_category = "absorbance"
            if spectrum_data:
                spectrum_category = spectrum_data.get("category") or "absorbance"
            should_show = spectrum_category == category
            item.setHidden(not should_show)

            if spectrum_data and spectrum_data.get('curve'):
                curve = spectrum_data['curve']
                if should_show and item.checkState() == Qt.Checked:
                    curve.setVisible(True)
                else:
                    curve.setVisible(False)

        self._update_display_count_and_title()
        self._refresh_metrics_table()
        if not self.user_has_interacted_with_plot:
            self.plot_widget.autoRange()

    def _show_full_cell_text(self, row, column):
        item = self.metrics_table.item(row, column)
        if not item:
            return
        text = item.text()
        if not text:
            return
        QToolTip.showText(QCursor.pos(), text, self.metrics_table)

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
        # 3. Preprocessing
        self.preprocessing_box = CollapsibleBox(parent=self)
        preprocess_layout = QVBoxLayout()
        self.preprocessing_enabled_checkbox = QCheckBox()
        self.preprocessing_enabled_checkbox.setChecked(self.preprocessing_enabled_default)
        self.baseline_checkbox = QCheckBox()
        self.baseline_checkbox.setChecked(self.apply_baseline_default)
        self.smoothing_checkbox = QCheckBox()
        self.smoothing_checkbox.setChecked(self.apply_smoothing_default)
        self.preprocessing_settings_button = QPushButton()
        self.baseline_checkbox.setEnabled(self.preprocessing_enabled_default)
        self.smoothing_checkbox.setEnabled(self.preprocessing_enabled_default)
        preprocess_layout.addWidget(self.preprocessing_enabled_checkbox)
        preprocess_layout.addWidget(self.baseline_checkbox)
        preprocess_layout.addWidget(self.smoothing_checkbox)
        self.noise_range_group = QGroupBox()
        self.noise_range_layout_form = QFormLayout(self.noise_range_group)
        self.noise_range_start_spinbox = QDoubleSpinBox()
        self.noise_range_end_spinbox = QDoubleSpinBox()
        for spinbox in [self.noise_range_start_spinbox, self.noise_range_end_spinbox]:
            spinbox.setDecimals(2)
            spinbox.setRange(200.0, 1200.0)
            spinbox.setSingleStep(10.0)
            spinbox.setSuffix(" nm")
        self.noise_range_start_spinbox.setValue(450.0)
        self.noise_range_end_spinbox.setValue(750.0)
        self.noise_range_start_label = QLabel()
        self.noise_range_end_label = QLabel()
        self.noise_range_layout_form.addRow(self.noise_range_start_label, self.noise_range_start_spinbox)
        self.noise_range_layout_form.addRow(self.noise_range_end_label, self.noise_range_end_spinbox)
        preprocess_layout.addWidget(self.noise_range_group)
        preprocess_layout.addWidget(self.preprocessing_settings_button)
        self.preprocessing_box.setContentLayout(preprocess_layout)
        panel_layout.addWidget(self.preprocessing_box)

        # 4. Static Analysis
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
        self.preprocessing_box.set_expanded(True)
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

        filter_layout = QHBoxLayout()
        self.show_background_button = QPushButton()
        self.show_reference_button = QPushButton()
        self.show_absorbance_button = QPushButton()
        for button in (self.show_background_button, self.show_reference_button, self.show_absorbance_button):
            button.setCheckable(True)

        self.category_filter_group = QButtonGroup()
        self.category_filter_group.setExclusive(True)
        self.category_filter_group.addButton(self.show_background_button)
        self.category_filter_group.addButton(self.show_reference_button)
        self.category_filter_group.addButton(self.show_absorbance_button)
        self.show_absorbance_button.setChecked(True)

        filter_layout.addWidget(self.show_background_button)
        filter_layout.addWidget(self.show_reference_button)
        filter_layout.addWidget(self.show_absorbance_button)
        filter_layout.addStretch()

        button_layout = QHBoxLayout()
        self.auto_range_button = QPushButton()  # 创建按钮
        button_layout.addStretch()
        button_layout.addWidget(self.auto_range_button)

        container_layout.addLayout(filter_layout)
        container_layout.addWidget(self.plot_widget)

        self.metrics_headers = [
            "Spectrum",
            "Peak Wavelength (nm)",
            "Peak Intensity",
            "FWHM (nm)",
            "RMS Noise",
            "C Noise",
            "SNR",
            "Q Factor",
            "Peak Area",
            "Skewness",
            "Baseline Slope",
            "Baseline Ripple",
            "Repeatability WL Mean",
            "Repeatability WL Std",
            "Repeatability WL CV%",
            "Repeatability Int Mean",
            "Repeatability Int Std",
            "Repeatability Int CV%",
        ]
        self.metrics_table = QTableWidget()
        self.metrics_table.setColumnCount(len(self.metrics_headers))
        self.metrics_table.setHorizontalHeaderLabels(self.metrics_headers)
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.metrics_table.horizontalHeader().setStretchLastSection(False)
        self.metrics_table.verticalHeader().setVisible(False)
        self.metrics_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.metrics_table.setSelectionBehavior(QTableWidget.SelectItems)
        self.metrics_table.setSelectionMode(QTableWidget.SingleSelection)
        self.metrics_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.metrics_table.setAlternatingRowColors(False)
        try:
            from ..utils.config_manager import load_settings
            theme = load_settings().get('theme', 'dark')
            self._apply_metrics_table_theme(theme)
        except Exception:
            self._apply_metrics_table_theme('dark')

        container_layout.addWidget(self.metrics_table)
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
        self.show_background_button.clicked.connect(lambda: self._set_category_filter("background"))
        self.show_reference_button.clicked.connect(lambda: self._set_category_filter("reference"))
        self.show_absorbance_button.clicked.connect(lambda: self._set_category_filter("absorbance"))
        self.select_all_button.clicked.connect(self._select_all_spectra)
        self.deselect_all_button.clicked.connect(self._deselect_all_spectra)
        self.filter_select_button.clicked.connect(self._filter_select_spectra)
        self.preprocessing_enabled_checkbox.toggled.connect(self._on_preprocessing_toggle_changed)
        self.baseline_checkbox.toggled.connect(self._on_preprocessing_toggle_changed)
        self.smoothing_checkbox.toggled.connect(self._on_preprocessing_toggle_changed)
        self.preprocessing_settings_button.clicked.connect(self._open_preprocessing_settings)
        self.peak_method_combo.currentIndexChanged.connect(lambda: self._refresh_metrics_table())
        self.metrics_table.cellClicked.connect(self._show_full_cell_text)

        self.range_start_spinbox.valueChanged.connect(self._on_range_spinbox_changed)
        self.range_end_spinbox.valueChanged.connect(self._on_range_spinbox_changed)
        self.region_selector.sigRegionChanged.connect(self._on_region_changed)
        self.reset_range_button.clicked.connect(self._reset_find_range)
        self.noise_range_start_spinbox.valueChanged.connect(self._on_noise_range_spinbox_changed)
        self.noise_range_end_spinbox.valueChanged.connect(self._on_noise_range_spinbox_changed)

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

        self.preprocessing_box.toggle_button.setText(self.tr("Preprocessing"))
        self.preprocessing_enabled_checkbox.setText(self.tr("Enable preprocessing"))
        self.baseline_checkbox.setText(self.tr("ALS baseline"))
        self.smoothing_checkbox.setText(self.tr("Savitzky-Golay"))
        self.preprocessing_settings_button.setText(self.tr("Adjust Preprocessing Parameters..."))

        self.analysis_box.toggle_button.setText(self.tr("Static Analysis"))
        self.analysis_target_label.setText(self.tr("Analysis Target:"))
        self.peak_method_label.setText(self.tr("Main Peak Algorithm:"))
        self.peak_height_label.setText(self.tr("Minimum Peak Height:"))

        self.range_group.setTitle(self.tr("Spectral Peak Find Range"))
        self.range_start_label.setText(self.tr("Start Position:"))
        self.range_end_label.setText(self.tr("End Position:"))
        self.reset_range_button.setText(self.tr("Reset to (450-750nm)"))

        self.noise_range_group.setTitle(self.tr("Noise Range"))
        self.noise_range_start_label.setText(self.tr("Noise Start:"))
        self.noise_range_end_label.setText(self.tr("Noise End:"))

        self.find_main_peak_button.setText(self.tr("Find Main Resonance Peak"))

        self.result_display_group.setTitle(self.tr("Analysis Results"))
        self.peak_wl_label.setText(self.tr("Peak Wavelength (nm):"))
        self.peak_int_label.setText(self.tr("Peak Intensity:"))
        self.peak_fwhm_label.setText(self.tr("FWHM (nm):"))

        self.show_background_button.setText(self.tr("Background"))
        self.show_reference_button.setText(self.tr("Reference"))
        self.show_absorbance_button.setText(self.tr("Absorbance"))

        if self.metrics_table and self.metrics_headers:
            self.metrics_table.setHorizontalHeaderLabels([self.tr(text) for text in self.metrics_headers])

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
        checked_spectra_y = [
            self._get_display_intensity(data['y']) for key, data in self.spectra.items()
            if data['list_item'].checkState() == Qt.Checked
        ]
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

    def _is_preprocessing_enabled(self):
        return bool(
            self.preprocessing_enabled_checkbox.isChecked()
            and (self.baseline_checkbox.isChecked() or self.smoothing_checkbox.isChecked())
        )

    def _get_intensity_for_processing(self, intensity):
        if not self._is_preprocessing_enabled():
            return intensity
        return self._apply_preprocessing(intensity)[0]

    def _get_display_intensity(self, intensity):
        if not self._is_preprocessing_enabled():
            return intensity
        return self._apply_preprocessing(intensity)[0]

    def _apply_preprocessing(self, intensity):
        working = np.asarray(intensity)
        baseline = None
        if self.baseline_checkbox.isChecked():
            als_lambda = self.preprocessing_params.get("als_lambda", 1e9)
            als_p = self.preprocessing_params.get("als_p", 0.01)
            baseline = baseline_als(working, lam=als_lambda, p=als_p)
            working = working - baseline
        if self.smoothing_checkbox.isChecked():
            sg_window_coarse = self.preprocessing_params.get("sg_window_coarse", 14)
            sg_poly_coarse = self.preprocessing_params.get("sg_polyorder_coarse", 3)
            sg_window_fine = self.preprocessing_params.get("sg_window_fine", 8)
            sg_poly_fine = self.preprocessing_params.get("sg_polyorder_fine", 3)
            sg_two_stage = self.preprocessing_params.get("sg_two_stage", True)
            coarse = smooth_savitzky_golay(working, window_length=sg_window_coarse, polyorder=sg_poly_coarse)
            if sg_two_stage:
                working = smooth_savitzky_golay(coarse, window_length=sg_window_fine, polyorder=sg_poly_fine)
            else:
                working = coarse
        return working, baseline

    def _on_preprocessing_toggle_changed(self):
        if isinstance(self.app_settings, dict):
            self.app_settings["analysis_preprocessing_enabled"] = bool(self.preprocessing_enabled_checkbox.isChecked())
            self.app_settings["analysis_baseline_enabled"] = bool(self.baseline_checkbox.isChecked())
            self.app_settings["analysis_smoothing_enabled"] = bool(self.smoothing_checkbox.isChecked())

        enabled = self.preprocessing_enabled_checkbox.isChecked()
        self.baseline_checkbox.setEnabled(enabled)
        self.smoothing_checkbox.setEnabled(enabled)

        if self.average_curve_item:
            any_checked = any(
                data['list_item'].checkState() == Qt.Checked for data in self.spectra.values()
            )
            if any_checked:
                self.calculate_average()

        self._refresh_plot_curves()

        if self.main_spectrum_to_analyze and self.main_peak_wavelength_label.text() != "N/A":
            self.analyze_main_peak()

        self._refresh_metrics_table()
        self._auto_y_range()

    def _open_preprocessing_settings(self):
        if not self.spectra:
            QMessageBox.warning(self, self.tr("Info"), self.tr("No spectrum available for preprocessing preview."))
            return
        sample_data = self.main_spectrum_to_analyze
        if not sample_data or 'curve' not in sample_data:
            sample_data = next(iter(self.spectra.values()))

        spectra_options = []
        for data in self.spectra.values():
            spectra_options.append((data['name'], data['x'], data['y']))
        if self.average_curve_data:
            spectra_options.append((self.average_curve_data['name'],
                                    self.average_curve_data['x'],
                                    self.average_curve_data['y']))

        selected_name = None
        current_index = self.analysis_target_combo.currentIndex()
        data_key = self.analysis_target_combo.itemData(current_index)
        if data_key == AVERAGE_CURVE_KEY and self.average_curve_data:
            selected_name = self.average_curve_data['name']
        elif data_key in self.spectra:
            selected_name = self.spectra[data_key]['name']

        dialog = PreprocessingDialog(
            sample_data['x'],
            sample_data['y'],
            self.preprocessing_params,
            self,
            spectra_options=spectra_options,
            selected_name=selected_name
        )
        if dialog.exec_() == QDialog.Accepted:
            self.preprocessing_params = dialog.get_params()
            if isinstance(self.app_settings, dict):
                self.app_settings["analysis_preprocessing_params"] = self.preprocessing_params.copy()
            if self.average_curve_item:
                self.calculate_average()
            self._refresh_plot_curves()
            if self.main_spectrum_to_analyze and self.main_peak_wavelength_label.text() != "N/A":
                self.analyze_main_peak()
            self._refresh_metrics_table()

    def _refresh_plot_curves(self):
        for data in self.spectra.values():
            curve = data.get('curve')
            if curve is None:
                continue
            display_y = self._get_display_intensity(data['y'])
            curve.setData(data['x'], display_y)

    def _on_display_mode_changed(self):
        self._refresh_plot_curves()
        if self.average_curve_item:
            self.calculate_average()

    def analyze_main_peak(self):
        if not self.main_spectrum_to_analyze:
            QMessageBox.warning(self, self.tr("Info"), self.tr("No spectrum available for analysis."))
            return

        x_data = self.main_spectrum_to_analyze['x']
        raw_y = self.main_spectrum_to_analyze['y']
        y_data = self._get_intensity_for_processing(raw_y)
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
        checked_spectra = {
            key: data
            for key, data in self.spectra.items()
            if data['list_item'].checkState() == Qt.Checked
            and (data.get("category") or "absorbance") == "absorbance"
        }
        if not checked_spectra:
            QMessageBox.warning(self, self.tr("Info"),
                                self.tr("Please check at least one absorbance spectrum to generate a report."))
            return
        default_save_path = self.app_settings.get('default_save_path', '')
        folder_path = QFileDialog.getExistingDirectory(self, self.tr("Select folder to save summary report"),
                                                       default_save_path)
        if not folder_path: return
        self.export_summary_button.setEnabled(False)
        self.export_summary_button.setText(self.tr("Generating..."))
        
        # 获取噪声范围
        noise_start = self.noise_range_start_spinbox.value()
        noise_end = self.noise_range_end_spinbox.value()
        
        # 获取寻峰方法和最小高度
        peak_method = self.peak_method_combo.currentData() or 'highest_point'
        min_height = self.peak_height_spinbox.value()
        
        self.report_worker = SummaryReportWorker(
            checked_spectra,
            folder_path,
            preprocessing_params=self.preprocessing_params,
            apply_baseline=bool(self.baseline_checkbox.isChecked()),
            apply_smoothing=bool(self.smoothing_checkbox.isChecked()),
            preprocessing_enabled=bool(self.preprocessing_enabled_checkbox.isChecked()),
            find_range=self.region_selector.getRegion(),
            noise_range=(noise_start, noise_end),
            peak_method=peak_method,
            min_height=min_height
        )
        self.report_worker.finished.connect(self._on_summary_report_finished)
        self.report_worker.start()

    def _on_summary_report_finished(self, status, report_folder):
        self.export_summary_button.setEnabled(True)
        self.export_summary_button.setText(self.tr("Export Summary Report"))
        if status == "success":
            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Summary report successfully generated in folder:\n{0}").format(report_folder))
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

            raw_x = self.main_spectrum_to_analyze['x']
            raw_y = self.main_spectrum_to_analyze['y']
            processed_y, baseline = self._apply_preprocessing(raw_y)
            use_processed = self._is_preprocessing_enabled()

            if all([self.source_signal, self.source_background, self.source_reference]):
                df_data = {
                    'Wavelength (nm)': self.source_signal[0], 'Signal Intensity': self.source_signal[1],
                    'Background Intensity': self.source_background[1], 'Reference Intensity': self.source_reference[1],
                    'Calculated Absorbance': raw_y
                }
                if use_processed:
                    if baseline is not None:
                        df_data['ALS Baseline'] = baseline
                    df_data['Processed Absorbance'] = processed_y
                df = pd.DataFrame(df_data)
                table_path = os.path.join(output_folder, "full_absorbance_data.xlsx")
            else:
                df_data = {
                    'Wavelength (nm)': raw_x,
                    'Value': raw_y
                }
                if use_processed:
                    if baseline is not None:
                        df_data['ALS Baseline'] = baseline
                    df_data['Processed Value'] = processed_y
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

            image_path = os.path.join(output_folder, "spectrum_plot.png")
            self._export_publication_plot(image_path)

            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Analysis results have been exported to:\n{0}").format(output_folder))
        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"),
                                 self.tr("An error occurred while exporting files: {0}").format(str(e)))

    def _export_publication_plot(self, image_path):
        try:
            import matplotlib.pyplot as plt
        except Exception:
            exporter = pg.exporters.ImageExporter(self.plot_widget.plotItem)
            exporter.export(image_path)
            return

        range_min, range_max = self.region_selector.getRegion()
        if range_min > range_max:
            range_min, range_max = range_max, range_min

        plt.rcParams.update({
            "font.family": "Times New Roman",
            "axes.linewidth": 1.2,
        })
        fig, ax = plt.subplots(figsize=(6, 4), dpi=600)
        for data in self.spectra.values():
            if data['list_item'].checkState() != Qt.Checked:
                continue
            if data['list_item'].isHidden():
                continue
            x_vals = np.asarray(data['x'])
            y_vals = np.asarray(self._get_display_intensity(data['y']))
            mask = (x_vals >= range_min) & (x_vals <= range_max)
            if not np.any(mask):
                continue
            curve = data.get('curve')
            color = None
            if curve is not None:
                try:
                    pen = curve.opts.get('pen', None)
                    if pen is not None and hasattr(pen, 'color'):
                        color = pen.color().getRgbF()
                except Exception:
                    color = None
            ax.plot(x_vals[mask], y_vals[mask], linewidth=0.8, color=color)

        ax.set_xlim(range_min, range_max)
        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("Intensity")
        ax.grid(False)
        fig.tight_layout()
        fig.savefig(image_path, dpi=600)
        plt.close(fig)

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
                if item.isHidden():
                    spectrum_data['curve'].setVisible(False)
                else:
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
            if item.isHidden():
                continue
            item.setCheckState(Qt.Checked)
        self.spectra_list_widget.blockSignals(False)
        # 手动触发一次更新
        for item in self.spectra.values():
            if item['curve']:
                if not item['list_item'].isHidden():
                    item['curve'].show()
        self._update_display_count_and_title()

    def _deselect_all_spectra(self):
        """将列表中的所有项设置为未勾选状态。"""
        self.spectra_list_widget.blockSignals(True)
        for i in range(self.spectra_list_widget.count()):
            item = self.spectra_list_widget.item(i)
            if item.isHidden():
                continue
            item.setCheckState(Qt.Unchecked)
        self.spectra_list_widget.blockSignals(False)
        # 手动触发一次更新
        for item in self.spectra.values():
            if item['curve']:
                if not item['list_item'].isHidden():
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
                if item.isHidden():
                    continue
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
        self._refresh_metrics_table()

    def _on_noise_range_spinbox_changed(self):
        start_val = self.noise_range_start_spinbox.value()
        end_val = self.noise_range_end_spinbox.value()
        min_val, max_val = sorted([start_val, end_val])
        if min_val != start_val or max_val != end_val:
            self.noise_range_start_spinbox.blockSignals(True)
            self.noise_range_end_spinbox.blockSignals(True)
            self.noise_range_start_spinbox.setValue(min_val)
            self.noise_range_end_spinbox.setValue(max_val)
            self.noise_range_start_spinbox.blockSignals(False)
            self.noise_range_end_spinbox.blockSignals(False)
        self._refresh_metrics_table()
        self._auto_y_range()

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
            self._apply_metrics_table_theme(theme)
        except Exception:
            pass  # 忽略错误

    def _apply_metrics_table_theme(self, theme):
        if not self.metrics_table:
            return
        if theme == 'light':
            self.metrics_table.setStyleSheet(
                "QTableView {"
                " background-color: #f5f5f5;"
                " color: #1f2933;"
                " gridline-color: #d1d5db;"
                "}"
                "QHeaderView::section {"
                " background-color: #e5e7eb;"
                " color: #111827;"
                " padding: 4px;"
                "}"
                "QTableView::item:selected {"
                " background-color: #cbd5e1;"
                "}"
            )
        else:
            self.metrics_table.setStyleSheet(
                "QTableView {"
                " background-color: #1f2735;"
                " color: #e2e8f0;"
                " gridline-color: #3a4456;"
                "}"
                "QHeaderView::section {"
                " background-color: #2a3445;"
                " color: #e2e8f0;"
                " padding: 4px;"
                "}"
                "QTableView::item:selected {"
                " background-color: #2c3e50;"
                "}"
            )
