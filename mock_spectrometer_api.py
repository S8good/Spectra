# mock_spectrometer_api.py (已升级为可配置)

import numpy as np
import time
from nanosense.utils.config_manager import load_settings # 【新增】导入配置加载器

class Wrapper:
    """
    一个【可配置的】模拟光谱仪API。
    它可以根据配置文件模拟静态峰、动态动力学或纯噪声。
    """

    def __init__(self):
        # 【核心修改】从加载配置，不再硬编码
        settings = load_settings()
        self.config = settings.get('mock_api_config')

        self.wavelengths = np.linspace(350, 950, 2048)
        self.device_count = 1
        self.start_time = time.time()  # 模拟开始的时间

    def _gaussian(self, x, amp, cen, wid):
        """高斯函数生成器"""
        return amp * np.exp(-(x - cen) ** 2 / (2 * wid ** 2))

    def OpenAllSpectrometers(self):
        print(f"模拟：找到 {self.device_count} 个设备。")
        return self.device_count

    def getName(self, index):
        if index == 0: return "MockFX2000_Configurable"
        return ""

    def getSerialNumber(self, index):
        if index == 0: return "MOCK-CONFIG-SN"
        return ""

    def setIntegrationTime(self, index, time_ms):
        pass

    def getSpectrum(self, index):
        """
        核心修改：根据配置文件中的模式，动态生成光谱。
        """
        mode = self.config.get('mode', 'dynamic')
        noise_level = self.config.get('noise_level', 50.0)
        noise = np.random.normal(0, noise_level, len(self.wavelengths))

        # 模式一：动态动力学
        if mode == 'dynamic':
            elapsed_time = time.time() - self.start_time
            current_peak_pos = self.config.get('dynamic_initial_pos', 650.0)
            initial_pos = self.config.get('dynamic_initial_pos', 650.0)
            total_shift = self.config.get('dynamic_shift_total', 10.0)
            baseline_dur = self.config.get('dynamic_baseline_duration', 5)
            assoc_dur = self.config.get('dynamic_assoc_duration', 20)
            dissoc_dur = self.config.get('dynamic_dissoc_duration', 30)

            if elapsed_time < baseline_dur:
                current_peak_pos = initial_pos
            elif elapsed_time < baseline_dur + assoc_dur:
                time_in_phase = elapsed_time - baseline_dur
                shift = total_shift * (time_in_phase / assoc_dur)
                current_peak_pos = initial_pos + shift
            elif elapsed_time < baseline_dur + assoc_dur + dissoc_dur:
                time_in_phase = elapsed_time - (baseline_dur + assoc_dur)
                shift = total_shift * (1 - (time_in_phase / dissoc_dur))
                current_peak_pos = initial_pos + shift
            else:
                current_peak_pos = initial_pos

            intensity = self._gaussian(self.wavelengths, 15000, current_peak_pos, 10)
            return intensity + noise

        # 模式二：静态峰
        elif mode == 'static':
            amp = self.config.get('static_peak_amp', 15000.0)
            pos = self.config.get('static_peak_pos', 650.0)
            width = self.config.get('static_peak_width', 10.0)
            intensity = self._gaussian(self.wavelengths, amp, pos, width)
            return intensity + noise

        # 模式三：纯噪声基线
        elif mode == 'noisy_baseline':
            # 简单返回一个以0为中心，带有指定噪声水平的信号
            return noise

        # 默认情况
        else:
            return np.zeros_like(self.wavelengths)