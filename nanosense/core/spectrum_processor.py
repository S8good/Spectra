# nanosense/core/spectrum_processor.py

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal
from scipy.signal import savgol_filter


class SpectrumProcessor(QObject):
    """
    光谱数据处理器 (模型)。
    负责存储、管理和计算光谱数据，与GUI分离。
    """
    # 定义信号，当计算结果更新时发射
    result_updated = pyqtSignal(object, object)  # 发射 x_data, y_data
    background_updated = pyqtSignal(object, object)
    reference_updated = pyqtSignal(object, object)

    def __init__(self, wavelengths):
        super().__init__()
        self.wavelengths = np.array(wavelengths)  # 确保是numpy数组
        self.mode_name = "N/A"

        # 光谱数据状态
        self.background_spectrum = None
        self.reference_spectrum = None
        self.latest_signal_spectrum = None
        
        # 平滑参数
        self.smoothing_method = "Savitzky-Golay"  # 默认方法
        self.smoothing_window = 11  # 默认窗口
        self.smoothing_order = 3  # SG滤波器阶数
        
        # 基线校正参数
        self.baseline_correction_enabled = False  # 是否启用基线校正
        self.baseline_algorithm = "ALS"  # 默认使用ALS算法
        self.baseline_lambda = 1e6  # ALS lambda参数
        self.baseline_p = 0.01  # ALS p参数
        self.baseline_niter = 10  # ALS迭代次数
        
        # 分析范围参数
        self.analysis_start = 500.0  # nm
        self.analysis_end = 900.0    # nm
        self.processing_margin = 30.0  # nm, 边界扩展

    def set_smoothing_params(self, method, window, order=3):
        """设置平滑参数。"""
        self.smoothing_method = method
        self.smoothing_window = window
        self.smoothing_order = order
        print(f"平滑参数已更新: {method}, window={window}, order={order}")
        # 参数改变后重新计算
        self.process_and_emit()
    
    def set_baseline_params(self, enabled, algorithm="ALS", lam=1e6, p=0.01, niter=10):
        """设置基线校正参数。"""
        self.baseline_correction_enabled = enabled
        self.baseline_algorithm = algorithm
        self.baseline_lambda = lam
        self.baseline_p = p
        self.baseline_niter = niter
        print(f"基线校正参数已更新: enabled={enabled}, algorithm={algorithm}, lambda={lam}, p={p}, niter={niter}")
        # 参数改变后重新计算
        self.process_and_emit()
    
    def set_analysis_range(self, start, end):
        """设置分析范围。"""
        self.analysis_start = start
        self.analysis_end = end
        print(f"分析范围已更新: {start}-{end} nm")
        # 参数改变后重新计算
        self.process_and_emit()

    def set_mode(self, mode_name):
        """设置当前的测量模式。"""
        self.mode_name = mode_name
        print(f"处理器模式已设置为: {self.mode_name}")
        self.process_and_emit()  # 模式改变后立即重新计算

    def set_background(self):
        """将最新的信号光谱存储为背景光谱。"""
        if self.latest_signal_spectrum is not None:
            self.background_spectrum = self.latest_signal_spectrum.copy()
            print("背景光谱已更新。")
            self.background_updated.emit(self.wavelengths, self.background_spectrum)
            self.process_and_emit()

    def set_reference(self):
        """将最新的信号光谱存储为参考光谱。"""
        if self.latest_signal_spectrum is not None:
            self.reference_spectrum = self.latest_signal_spectrum.copy()
            print("参考光谱已更新。")
            self.reference_updated.emit(self.wavelengths, self.reference_spectrum)
            self.process_and_emit()

    def clear_background(self):
        """清除背景光谱。"""
        self.background_spectrum = None
        self.background_updated.emit(self.wavelengths, None)  # 发射None以清空图表
        self.process_and_emit()

    def clear_reference(self):
        """清除参考光谱。"""
        self.reference_spectrum = None
        self.reference_updated.emit(self.wavelengths, None)  # 发射None以清空图表
        self.process_and_emit()

    def update_signal(self, new_signal_spectrum):
        """用新的实时信号光谱更新状态并触发计算。"""
        self.latest_signal_spectrum = new_signal_spectrum
        self.process_and_emit()

    def _apply_smoothing(self, spectrum):
        """
        根据设置的参数应用平滑。
        支持多种平滑方法：No Smoothing, Savitzky-Golay, Moving Average, Median Filter
        """
        if spectrum is None:
            return None
        
        if self.smoothing_method == "No Smoothing" or self.smoothing_method == "不平滑":
            return spectrum
        
        elif self.smoothing_method == "Savitzky-Golay":
            from scipy.signal import savgol_filter
            return savgol_filter(spectrum, self.smoothing_window, self.smoothing_order)
        
        elif self.smoothing_method == "Moving Average" or self.smoothing_method == "移动平均":
            from scipy.ndimage import uniform_filter1d
            return uniform_filter1d(spectrum, size=self.smoothing_window)
        
        elif self.smoothing_method == "Median Filter" or self.smoothing_method == "中值滤波":
            from scipy.signal import medfilt
            return medfilt(spectrum, kernel_size=self.smoothing_window)
        
        else:
            # 未知方法，使用默认SG滤波
            return savgol_filter(spectrum, self.smoothing_window, self.smoothing_order)
    
    def _apply_baseline_correction(self, spectrum):
        """
        应用基线校正。
        支持ALS算法，未来可扩展ArPLS、多项式拟合等。
        """
        if spectrum is None or not self.baseline_correction_enabled:
            return spectrum
        
        if self.baseline_algorithm == "ALS":
            from ..algorithms.preprocessing import baseline_als
            # 计算基线
            baseline = baseline_als(
                spectrum, 
                lam=self.baseline_lambda, 
                p=self.baseline_p, 
                niter=self.baseline_niter
            )
            # 扣除基线
            return spectrum - baseline
        
        else:
            # 未知算法，不进行基线校正
            return spectrum

    def process_and_emit(self):
        """
        【已修改 - 基于分析范围的预处理】
        只对分析范围 ± margin 进行平滑和基线校正，避免高噪声区域影响处理质量。
        """
        if self.latest_signal_spectrum is None:
            self.result_updated.emit(self.wavelengths, None)
            return

        # 步骤 1: 计算有效处理范围
        margin = self.processing_margin
        proc_start = max(self.wavelengths[0], self.analysis_start - margin)
        proc_end = min(self.wavelengths[-1], self.analysis_end + margin)
        
        # 步骤 2: 找到对应的索引范围
        mask = (self.wavelengths >= proc_start) & (self.wavelengths <= proc_end)
        proc_indices = np.where(mask)[0]
        
        # 如果没有有效索引，返回None
        if len(proc_indices) == 0:
            self.result_updated.emit(self.wavelengths, None)
            return
        
        # 步骤 3: 裁剪光谱到处理范围
        proc_signal = self.latest_signal_spectrum[proc_indices]
        proc_dark = self.background_spectrum[proc_indices] if self.background_spectrum is not None else None
        proc_ref = self.reference_spectrum[proc_indices] if self.reference_spectrum is not None else None

        # 步骤 4: 应用平滑（只对裁剪后的光谱）
        processed_signal = self._apply_smoothing(proc_signal)
        dark = self._apply_smoothing(proc_dark) if proc_dark is not None else np.zeros_like(processed_signal)
        smoothed_ref = self._apply_smoothing(proc_ref) if proc_ref is not None else np.ones_like(processed_signal)

        result_spectrum_cropped = None

        # 步骤 5: 根据模式计算结果（裁剪后的数据）
        if self.mode_name in ["Reflectance", "Transmission", "Absorbance"]:
            if self.background_spectrum is None or self.reference_spectrum is None:
                self.result_updated.emit(self.wavelengths, None)
                return

            effective_signal = processed_signal - dark
            effective_ref = smoothed_ref - dark

            safe_denominator = np.copy(effective_ref)
            safe_denominator[safe_denominator == 0] = 1e-9

            trans_or_refl = effective_signal / safe_denominator

            if self.mode_name == 'Absorbance':
                safe_log_argument = np.copy(trans_or_refl)
                safe_log_argument[safe_log_argument <= 0] = 1e-9
                result_spectrum_cropped = -1 * np.log10(safe_log_argument)
            else:  # Reflectance or Transmission
                result_spectrum_cropped = trans_or_refl

        elif self.mode_name in ["Raman", "Fluorescence"]:
            if self.background_spectrum is not None:
                result_spectrum_cropped = processed_signal - dark
            else:
                result_spectrum_cropped = processed_signal
            
            # For Raman, use reference spectrum for normalization if available
            if self.mode_name == "Raman" and self.reference_spectrum is not None:
                safe_denominator = np.copy(smoothed_ref)
                safe_denominator[safe_denominator == 0] = 1e-9
                result_spectrum_cropped = result_spectrum_cropped / safe_denominator
        else:  # 原始信号模式
            result_spectrum_cropped = processed_signal
        
        # 步骤 6: 应用基线校正（只对裁剪后的光谱）
        if result_spectrum_cropped is not None:
            result_spectrum_cropped = self._apply_baseline_correction(result_spectrum_cropped)
        
        # 步骤 7: 重建完整光谱（在处理范围外填充原始未处理值）
        # 创建完整结果数组，初始化为原始信号
        full_result = self.latest_signal_spectrum.copy()
        
        # 将处理后的数据填充到对应位置
        if result_spectrum_cropped is not None:
            full_result[proc_indices] = result_spectrum_cropped

        # 发射完整光谱
        self.result_updated.emit(self.wavelengths, full_result)