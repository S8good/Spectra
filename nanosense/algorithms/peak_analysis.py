# nanosense/algorithms/peak_analysis.py

import numpy as np
from scipy.signal import find_peaks
from scipy.optimize import curve_fit

PEAK_METHOD_LABELS = {
    'highest_point': 'Highest Point',
    'centroid': 'Centroid',
    'gaussian_fit': 'Gaussian Fit',
    'parabolic': 'Parabolic Interpolation',
    'wavelet': 'Wavelet Transform',
    'threshold': 'Threshold-based',
}
PEAK_METHOD_KEYS = tuple(PEAK_METHOD_LABELS.keys())


def find_spectral_peaks(y_data, min_height=None, min_distance=None):
    """
    一个通用的光谱寻峰函数。
    不再请求scipy计算宽度。
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

def find_main_resonance_peak(y_data, wavelengths=None, min_height=None, min_distance=None, method='highest_point'):
    """
    从索引中找到主共振峰。
    
    参数:
    y_data: numpy数组，光谱强度数据
    wavelengths: numpy数组，对应的波长数据。如果为None，将使用索引作为波长。
    min_height: 峰的最小高度
    min_distance: 峰之间的最小距离
    method: 寻峰方法
    """
    # 1. 首先，使用通用函数找到所有可能的候选峰
    all_indices, all_properties = find_spectral_peaks(y_data, min_height, min_distance)

    # 2. 如果没有找到任何峰，直接返回
    if len(all_indices) == 0:
        return None, None

    # 3. 根据指定的方法选择主峰
    method_key = (method or 'highest_point').lower()
    if method_key not in PEAK_METHOD_LABELS:
        method_key = 'highest_point'

    # 如果没有提供波长数据，使用索引作为波长
    if wavelengths is None:
        wavelengths = np.arange(len(y_data))
    else:
        wavelengths = np.asarray(wavelengths)

    if method_key == 'highest_point':
        # 从所有找到的峰中，找到高度最高的那个峰的索引
        heights = y_data[all_indices]
        index_of_highest_peak_in_list = np.argmax(heights)

        # 获取这个最高峰在原始数据中的索引
        main_peak_original_index = all_indices[index_of_highest_peak_in_list]

        # 提取这个最高峰的所有属性
        main_peak_properties = {key: value[index_of_highest_peak_in_list] for key, value in all_properties.items()}

        return main_peak_original_index, main_peak_properties
    else:
        # 对于其他方法，我们使用estimate_peak_position函数
        peak_index, peak_wavelength = estimate_peak_position(wavelengths, y_data, method=method_key)
        
        if peak_index is not None:
            # 直接使用估计的峰位，而不是从候选峰中选择
            main_peak_original_index = peak_index
            
            # 计算峰属性
            main_peak_properties = {
                'peak_index': main_peak_original_index,
                'peak_wavelength': peak_wavelength,
                'peak_intensity': float(y_data[main_peak_original_index])
            }
            
            # 计算FWHM
            if len(all_indices) > 0:
                # 找到最接近的候选峰
                closest_candidate_idx = np.argmin(np.abs(all_indices - main_peak_original_index))
                closest_candidate = all_indices[closest_candidate_idx]
                
                # 如果接近候选峰，使用候选峰的属性
                if abs(main_peak_original_index - closest_candidate) < 5:  # 允许5个点的误差
                    main_peak_properties.update({
                        key: value[closest_candidate_idx] for key, value in all_properties.items()
                    })
            
            return main_peak_original_index, main_peak_properties

    # 如果所有方法都失败了，回退到最高点法
    heights = y_data[all_indices]
    index_of_highest_peak_in_list = np.argmax(heights)
    main_peak_original_index = all_indices[index_of_highest_peak_in_list]
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


def estimate_peak_position(wavelengths, intensities, method='highest_point'):
    """
    根据指定方法估计峰位。

    返回:
    tuple: (approx_index, peak_wavelength)
    """
    if wavelengths is None or intensities is None:
        return None, None

    wavelengths_arr = np.asarray(wavelengths)
    intensities_arr = np.asarray(intensities)

    if wavelengths_arr.size == 0 or intensities_arr.size == 0:
        return None, None

    method_key = (method or 'highest_point').lower()
    if method_key not in PEAK_METHOD_LABELS:
        method_key = 'highest_point'

    try:
        if method_key == 'highest_point':
            index = int(np.argmax(intensities_arr))
            return index, float(wavelengths_arr[index])

        if method_key == 'centroid':
            center = calculate_centroid(wavelengths_arr, intensities_arr)
            if center is None:
                return None, None
            approx_index = int(np.argmin(np.abs(wavelengths_arr - center)))
            return approx_index, float(center)

        if method_key == 'gaussian_fit':
            fit_results = fit_peak_gaussian(wavelengths_arr, intensities_arr)
            if not fit_results:
                return None, None
            center = float(fit_results['center'])
            approx_index = int(np.argmin(np.abs(wavelengths_arr - center)))
            return approx_index, center
            
        if method_key == 'parabolic':
            # 二次多项式拟合寻峰
            index = int(np.argmax(intensities_arr))
            if index <= 0 or index >= len(intensities_arr) - 1:
                return index, float(wavelengths_arr[index])
            
            # 使用峰值点及其左右相邻点进行二次拟合
            x = wavelengths_arr[index-1:index+2]
            y = intensities_arr[index-1:index+2]
            
            # 二次多项式拟合: y = ax^2 + bx + c
            coeffs = np.polyfit(x, y, 2)
            a, b, c = coeffs
            
            # 计算极值点: x = -b/(2a)
            if a != 0:
                peak_wavelength = -b / (2 * a)
                approx_index = int(np.argmin(np.abs(wavelengths_arr - peak_wavelength)))
                return approx_index, peak_wavelength
            else:
                return index, float(wavelengths_arr[index])

        if method_key == 'wavelet':
            # 小波变换寻峰
            try:
                from scipy.signal import find_peaks_cwt
                # 使用连续小波变换寻找峰值
                peak_indices = find_peaks_cwt(intensities_arr, widths=np.arange(1, 10))
                if len(peak_indices) > 0:
                    # 选择幅度最大的峰值
                    peak_heights = intensities_arr[peak_indices]
                    max_peak_idx = peak_indices[np.argmax(peak_heights)]
                    return max_peak_idx, float(wavelengths_arr[max_peak_idx])
                else:
                    # 如果没找到峰值，回退到最高点法
                    index = int(np.argmax(intensities_arr))
                    return index, float(wavelengths_arr[index])
            except ImportError:
                # 如果没有安装scipy或相关模块，回退到最高点法
                index = int(np.argmax(intensities_arr))
                return index, float(wavelengths_arr[index])

        if method_key == 'threshold':
            # 阈值法寻峰
            # 计算自适应阈值（平均值+标准差）
            threshold = np.mean(intensities_arr) + np.std(intensities_arr)
            
            # 寻找超过阈值的区域
            above_threshold = intensities_arr > threshold
            
            if np.any(above_threshold):
                # 找到所有连续的超过阈值的区域
                regions = []
                start = None
                
                for i, is_above in enumerate(above_threshold):
                    if is_above and start is None:
                        start = i
                    elif not is_above and start is not None:
                        regions.append((start, i-1))
                        start = None
                
                # 处理最后一个区域
                if start is not None:
                    regions.append((start, len(intensities_arr)-1))
                
                # 在每个区域中找到最大值点
                peak_candidates = []
                for start, end in regions:
                    region_intensities = intensities_arr[start:end+1]
                    local_max_idx = np.argmax(region_intensities)
                    global_max_idx = start + local_max_idx
                    peak_candidates.append((global_max_idx, intensities_arr[global_max_idx]))
                
                # 选择幅度最大的峰值
                if peak_candidates:
                    peak_idx = max(peak_candidates, key=lambda x: x[1])[0]
                    return peak_idx, float(wavelengths_arr[peak_idx])
            
            # 如果没有找到满足条件的峰值，回退到最高点法
            index = int(np.argmax(intensities_arr))
            return index, float(wavelengths_arr[index])

    except Exception as exc:
        print(f"estimate_peak_position failed: {exc}")

    return None, None


def calculate_raman_shift(wavelengths, excitation_wavelength):
    """
    【计算拉曼位移】
    将波长转换为拉曼位移（cm⁻¹）。
    """
    lambda_exc = excitation_wavelength * 1e-7  # 转换为cm
    lambda_em = wavelengths * 1e-7  # 转换为cm
    raman_shift = 10000 * (1/lambda_exc - 1/lambda_em)
    return raman_shift


def identify_raman_peaks(wavenumbers, intensities, min_height=None, min_distance=None):
    """
    【拉曼特征峰识别】
    识别拉曼光谱中的特征峰。
    """
    # 使用通用寻峰函数找到所有可能的峰
    indices, properties = find_spectral_peaks(intensities, min_height, min_distance)
    
    if len(indices) == 0:
        return np.array([]), {}, []
    
    # 计算每个峰的拉曼位移和强度
    peak_wavenumbers = wavenumbers[indices]
    peak_intensities = intensities[indices]
    
    # 计算每个峰的FWHM
    fwhms = calculate_fwhm(wavenumbers, intensities, indices)
    
    # 构建峰信息列表
    peak_info = []
    for i, (wn, inten, fwhm) in enumerate(zip(peak_wavenumbers, peak_intensities, fwhms)):
        peak_info.append({
            'wavenumber': float(wn),
            'intensity': float(inten),
            'fwhm': float(fwhm),
            'index': int(indices[i])
        })
    
    return indices, properties, peak_info


def match_raman_peaks(peak_wavenumbers, reference_peaks, tolerance=5.0):
    """
    【拉曼峰匹配】
    将识别的拉曼峰与参考峰进行匹配。
    """
    matches = []
    
    for peak in peak_wavenumbers:
        # 找到最接近的参考峰
        closest_ref = None
        min_distance = float('inf')
        
        for ref_peak in reference_peaks:
            distance = abs(peak - ref_peak)
            if distance < min_distance:
                min_distance = distance
                closest_ref = ref_peak
        
        # 如果在容忍范围内，认为是匹配的
        if min_distance <= tolerance:
            matches.append({
                'measured': float(peak),
                'reference': float(closest_ref),
                'difference': float(min_distance)
            })
    
    return matches
