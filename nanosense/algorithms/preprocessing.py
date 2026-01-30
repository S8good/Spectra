# nanosense/algorithms/preprocessing.py

import numpy as np
from scipy.signal import savgol_filter, medfilt
from scipy.sparse import csc_matrix, eye, diags
from scipy.sparse.linalg import spsolve

"""
光谱预处理函数 (平滑, 基线校正等)
这部分代码实现了关键数据预处理算法。
"""

def smooth_savitzky_golay(spectrum, window_length=11, polyorder=3):
    """
    【Savitzky-Golay 平滑】
    这是最推荐的光谱平滑方法之一，因为它能在有效去噪的同时，很好地保留峰形特征。
    """
    if len(spectrum) < window_length:
        return spectrum
    if window_length % 2 == 0:
        window_length += 1
    return savgol_filter(spectrum, window_length, polyorder)


def smooth_moving_average(spectrum, window_size=5):
    """
    【移动平均平滑】
    一种简单有效的平滑方法，适用于去除高频随机噪声。
    """
    return np.convolve(spectrum, np.ones(window_size)/window_size, mode='same')


def smooth_median(spectrum, kernel_size=5):
    """
    【中值滤波】
    该方法对于去除突然的、不连续的脉冲噪声（异常值）非常有效。
    """
    if kernel_size % 2 == 0:
        kernel_size += 1
    return medfilt(spectrum, kernel_size)


def baseline_als(y, lam=1e6, p=0.01, niter=10):
    """
    【不对称最小二乘法 (Asymmetric Least Squares, ALS) 基线校正】
    这是一种强大且自动化的基线校正算法，与“惩罚最小二乘法”思想一致。
    """
    L = len(y)
    D = diags([1, -2, 1], [0, -1, -2], shape=(L, L - 2))
    D = lam * D.dot(D.transpose())
    w = np.ones(L)
    W = csc_matrix(diags(w, 0, shape=(L, L)))
    for i in range(niter):
        W.setdiag(w)
        Z = W + D
        z = spsolve(Z, w * y)
        w = p * (y > z) + (1 - p) * (y < z)
    return z


def remove_rayleigh_scattering(wavelengths, spectrum, excitation_wavelength, cutoff_wavenumber=200):
    """
    【瑞利散射去除】
    去除瑞利散射峰附近的信号，避免其干扰拉曼信号分析。
    """
    # 计算瑞利散射的波长范围
    lambda_exc = excitation_wavelength
    # 转换截止波数为波长
    lambda_cutoff = 1 / (1/(lambda_exc * 1e-7) - cutoff_wavenumber / 10000) * 1e7
    
    # 创建掩码，保留截止波长以外的信号
    mask = np.abs(wavelengths - lambda_exc) > np.abs(lambda_cutoff - lambda_exc)
    
    # 应用掩码
    filtered_spectrum = spectrum.copy()
    filtered_spectrum[~mask] = 0
    
    return filtered_spectrum


def fluorescence_background_subtraction(spectrum, window_size=51, poly_order=3):
    """
    【荧光背景扣除】
    使用多项式拟合去除荧光背景。
    """
    # 生成波长索引
    x = np.arange(len(spectrum))
    
    # 使用Savitzky-Golay滤波估计背景
    background = savgol_filter(spectrum, window_size, poly_order)
    
    # 扣除背景
    corrected_spectrum = spectrum - background
    
    # 确保结果非负
    corrected_spectrum = np.maximum(corrected_spectrum, 0)
    
    return corrected_spectrum


def standard_normal_variate(spectrum):
    """
    【标准正态变量变换 (Standard Normal Variate, SNV)】
    对光谱进行标准化处理，提高不同光谱之间的可比性。
    """
    mean = np.mean(spectrum)
    std = np.std(spectrum)
    if std == 0:
        return spectrum
    return (spectrum - mean) / std


def normalize_spectrum(spectrum, method='none'):
    """
    【光谱归一化】
    支持多种归一化方法。
    """
    if method == 'none':
        return spectrum
    elif method == 'peak_height':
        max_val = np.max(spectrum)
        if max_val == 0:
            return spectrum
        return spectrum / max_val
    elif method == 'area':
        area = np.sum(spectrum)
        if area == 0:
            return spectrum
        return spectrum / area
    elif method == 'snv':
        return standard_normal_variate(spectrum)
    else:
        return spectrum