# nanosense/algorithms/peak_analysis.py

import numpy as np
from scipy.signal import find_peaks
from scipy.optimize import curve_fit


def find_spectral_peaks(y_data, min_height=None, min_distance=None):
    """
    一个通用的光谱寻峰函数。
    【已简化】不再请求scipy计算宽度。
    """
    try:
        indices, properties = find_peaks(y_data, height=min_height, distance=min_distance)
        return indices, properties
    except Exception as e:
        print(f"寻峰时发生错误: {e}")
        return np.array([]), {}

def calculate_fwhm(x_data, y_data, peak_indices):
    """
    手动计算在一组峰值处的半峰全宽 (FWHM)。
    返回:
    list: 包含每个峰对应FWHM值的列表。
    """
    fwhms = []
    for peak_idx in peak_indices:
        try:
            peak_height = y_data[peak_idx]
            baseline = np.min(y_data)  # 简单以最低点为基线
            half_max_height = baseline + (peak_height - baseline) / 2.0

            # 寻找左边界
            left_side = y_data[:peak_idx]
            # 找到所有低于半高值的点，取最后一个
            left_cross_indices = np.where(left_side < half_max_height)[0]
            if not left_cross_indices.any():
                fwhms.append(0)
                continue
            left_idx = left_cross_indices[-1]

            # 寻找右边界
            right_side = y_data[peak_idx:]
            # 找到所有低于半高值的点，取第一个
            right_cross_indices = np.where(right_side < half_max_height)[0]
            if not right_cross_indices.any():
                fwhms.append(0)
                continue
            right_idx = right_cross_indices[0] + peak_idx

            # 使用线性插值来获得更精确的边界点
            left_wl = np.interp(half_max_height, [y_data[left_idx], y_data[left_idx + 1]],
                                [x_data[left_idx], x_data[left_idx + 1]])
            right_wl = np.interp(half_max_height, [y_data[right_idx], y_data[right_idx - 1]],
                                 [x_data[right_idx], x_data[right_idx - 1]])

            fwhms.append(abs(right_wl - left_wl))
        except Exception:
            fwhms.append(0)  # 如果计算出错，则记为0

    return fwhms

def find_main_resonance_peak(y_data, min_height=None, min_distance=None):
    """
    从索引中找到强度最高的主共振峰。
    """
    # 1. 首先，使用通用函数找到所有可能的候选峰
    all_indices, all_properties = find_spectral_peaks(y_data, min_height, min_distance)

    # 2. 如果没有找到任何峰，直接返回
    if len(all_indices) == 0:
        return None, None

    # 3. 从所有找到的峰中，找到高度最高的那个峰的索引
    heights = y_data[all_indices]
    index_of_highest_peak_in_list = np.argmax(heights)

    # 4. 获取这个最高峰在原始数据中的索引
    main_peak_original_index = all_indices[index_of_highest_peak_in_list]

    # 5. 提取这个最高峰的所有属性
    main_peak_properties = {key: value[index_of_highest_peak_in_list] for key, value in all_properties.items()}

    return main_peak_original_index, main_peak_properties


def calculate_centroid(wavelengths, intensities):
    """
    计算光谱峰的质心。
    该方法考虑了峰半高宽（FWHM）区域内的数据点。

    返回:
    float: 计算出的质心波长。如果无法计算，则返回None。
    """
    if intensities is None or len(intensities) < 3:
        return None

    try:
        # 找到峰值的最大强度和其位置
        peak_intensity = np.max(intensities)
        peak_index = np.argmax(intensities)

        # 计算半高值（最大值与最小值的一半）
        half_max_intensity = np.min(intensities) + (peak_intensity - np.min(intensities)) / 2.0

        # 找到半高宽的左右边界
        # 从峰值点向左搜索
        left_index = np.where(intensities[:peak_index] < half_max_intensity)[0]
        if len(left_index) == 0:
            left_index = 0
        else:
            left_index = left_index[-1]

        # 从峰值点向右搜索
        right_index = np.where(intensities[peak_index:] < half_max_intensity)[0]
        if len(right_index) == 0:
            right_index = len(intensities) - 1
        else:
            right_index = right_index[0] + peak_index

        # 提取峰值区域的数据
        peak_wavelengths = wavelengths[left_index: right_index + 1]
        peak_intensities = intensities[left_index: right_index + 1]

        # 计算质心
        # 分子: sum(intensity * wavelength)
        numerator = np.sum(peak_intensities * peak_wavelengths)
        # 分母: sum(intensity)
        denominator = np.sum(peak_intensities)

        if denominator == 0:
            return None

        centroid_wavelength = numerator / denominator
        return centroid_wavelength

    except Exception as e:
        print(f"计算质心时发生错误: {e}")
        return None

def gaussian(x, amplitude, center, sigma):
    """一个标准的高斯函数模型。"""
    return amplitude * np.exp(-(x - center) ** 2 / (2 * sigma ** 2))


def fit_peak_gaussian(wavelengths, intensities):
    """
    使用高斯模型拟合光谱峰。

    返回:
    dict: 包含拟合参数的字典，如 {'center': 650.1, 'amplitude': 1000, 'sigma': 5.2}
          如果拟合失败，返回None。
    """
    if intensities is None or len(intensities) < 3:
        return None

    try:
        # 为拟合提供一个好的初始猜测值 (p0)
        # 这是成功拟合的关键
        center_guess_index = np.argmax(intensities)
        center_guess = wavelengths[center_guess_index]
        amplitude_guess = np.max(intensities)
        # 粗略估计峰宽
        sigma_guess = (wavelengths[-1] - wavelengths[0]) / 10

        # 使用scipy的curve_fit进行拟合
        popt, pcov = curve_fit(
            gaussian,
            wavelengths,
            intensities,
            p0=[amplitude_guess, center_guess, sigma_guess]
        )

        # 提取拟合结果
        fit_amplitude, fit_center, fit_sigma = popt

        return {
            'center': fit_center,
            'amplitude': fit_amplitude,
            'sigma': fit_sigma
        }

    except RuntimeError:
        print("高斯拟合失败：无法收敛。")
        return None
    except Exception as e:
        print(f"高斯拟合时发生错误: {e}")
        return None