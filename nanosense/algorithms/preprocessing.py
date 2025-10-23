# nanosense/algorithms/preprocessing.py

import numpy as np
from scipy.signal import savgol_filter, medfilt
from scipy.sparse import csc_matrix, eye, diags
from scipy.sparse.linalg import spsolve

"""
光谱预处理函数 (平滑, 基线校正等)
这部分代码实现了论文第3章中讨论的关键数据预处理算法。
"""

def smooth_savitzky_golay(spectrum, window_length=11, polyorder=3):
    """
    【Savitzky-Golay 平滑】
    这是论文中最推荐的光谱平滑方法之一，因为它能在有效去噪的同时，很好地保留峰形特征。
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
    论文中特别提到，该方法对于去除突然的、不连续的脉冲噪声（异常值）非常有效。
    """
    if kernel_size % 2 == 0:
        kernel_size += 1
    return medfilt(spectrum, kernel_size)


def baseline_als(y, lam=1e6, p=0.01, niter=10):
    """
    【不对称最小二乘法 (Asymmetric Least Squares, ALS) 基线校正】
    这是一种强大且自动化的基线校正算法，与论文中提到的“惩罚最小二乘法”思想一致。
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