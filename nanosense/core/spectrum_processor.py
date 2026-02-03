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
        self.wavelengths = wavelengths
        self.mode_name = "N/A"

        # 光谱数据状态
        self.background_spectrum = None
        self.reference_spectrum = None
        self.latest_signal_spectrum = None
        
        # 平滑参数
        self.smoothing_method = "Savitzky-Golay"  # 默认方法
        self.smoothing_window = 11  # 默认窗口
        self.smoothing_order = 3  # SG滤波器阶数

    def set_smoothing_params(self, method, window, order=3):
        """设置平滑参数。"""
        self.smoothing_method = method
        self.smoothing_window = window
        self.smoothing_order = order
        print(f"平滑参数已更新: {method}, window={window}, order={order}")
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

    def process_and_emit(self):
        """
        【已修改 - 裁剪方案】
        此版本不再进行基于阈值的掩码操作，而是直接计算并发出完整的光谱。
        所有裁剪和过滤逻辑将移至UI层处理。
        """
        if self.latest_signal_spectrum is None:
            self.result_updated.emit(self.wavelengths, None)
            return

        # 步骤 1: 应用平滑（使用UI设置的参数）
        processed_signal = self._apply_smoothing(self.latest_signal_spectrum)
        dark = self._apply_smoothing(self.background_spectrum) if self.background_spectrum is not None else np.zeros_like(processed_signal)
        smoothed_ref = self._apply_smoothing(self.reference_spectrum) if self.reference_spectrum is not None else np.ones_like(processed_signal)

        result_spectrum = None

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
                result_spectrum = -1 * np.log10(safe_log_argument)
            else:  # Reflectance or Transmission
                result_spectrum = trans_or_refl

        elif self.mode_name in ["Raman", "Fluorescence"]:
            if self.background_spectrum is not None:
                result_spectrum = processed_signal - dark
            else:
                result_spectrum = processed_signal
            
            # For Raman, use reference spectrum for normalization if available
            if self.mode_name == "Raman" and self.reference_spectrum is not None:
                safe_denominator = np.copy(smoothed_ref)
                safe_denominator[safe_denominator == 0] = 1e-9
                result_spectrum = result_spectrum / safe_denominator
        else:  # 原始信号模式
            result_spectrum = processed_signal

        # 发射最终计算出的完整光谱
        self.result_updated.emit(self.wavelengths, result_spectrum)