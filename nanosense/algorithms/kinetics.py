# nanosense/algorithms/kinetics.py

import numpy as np
from scipy.optimize import curve_fit


def linear_fit(x_values, y_values):
    # ... (此函数不变) ...
    if len(x_values) < 2: return None
    m, b = np.polyfit(x_values, y_values, 1)
    r_squared = np.corrcoef(x_values, y_values)[0, 1] ** 2
    return {'slope': m, 'intercept': b, 'r_squared': r_squared}


def mono_exponential_decay(t, a, b, c):
    """单指数衰减模型: f(t) = a * e^(-bt) + c"""
    return a * np.exp(-b * t) + c


# 在 nanosense/algorithms/kinetics.py 文件中

def fit_kinetics_curve(time_data, y_data):
    """
    【已升级】使用论文中的方法来估算初始值，以进行更精确的拟合。
    """
    time_data = np.array(time_data)
    y_data = np.array(y_data)

    if len(time_data) < 3:
        return None

    try:
        # --- 遵照论文公式 4-4 到 4-11 实现初始值估算 ---
        # 1. 估算 c (f(t->inf))
        c_guess = np.mean(y_data[-3:])
        # 2. 估算 a (f(0) - c)
        f0_guess = np.mean(y_data[:3])
        a_guess = f0_guess - c_guess

        # 3. 估算 b (1/tau)
        # 找到y值下降到 (a/e + c) 时的时间点 tau
        target_y = a_guess / np.e + c_guess
        # 找到与target_y最接近的数据点的索引
        tau_index = np.argmin(np.abs(y_data - target_y))
        tau_guess = time_data[tau_index]

        # 避免除以零的边界情况
        if tau_guess == 0:
            tau_guess = time_data[int(len(time_data) / 2)] if len(time_data) > 1 else 1.0

        b_guess = 1 / tau_guess

        initial_guesses = [a_guess, b_guess, c_guess]
        print(f"--- DEBUG: 拟合初始猜测值 (a,b,c): {initial_guesses} ---")

        # 使用curve_fit进行拟合
        popt, pcov = curve_fit(
            mono_exponential_decay,
            time_data,
            y_data,
            p0=initial_guesses,
            maxfev=5000  # 增加最大迭代次数以提高收敛成功率
        )

        return {'a': popt[0], 'b': popt[1], 'c': popt[2]}

    except RuntimeError:
        print("动力学拟合失败：无法收敛。请检查选择的数据区域或调整初始值。")
        return None
    except Exception as e:
        print(f"动力学拟合时发生错误: {e}")
        return None

def calculate_residuals(time_data, y_data, fit_params):
    # ... (此函数不变) ...
    if fit_params is None: return np.zeros_like(y_data)
    fitted_y = mono_exponential_decay(time_data, **fit_params)
    return y_data - fitted_y


def correct_drift(time_data, y_data, baseline_start_time, baseline_end_time):
    # ... (此函数不变) ...
    time_data, y_data = np.array(time_data), np.array(y_data)
    baseline_mask = (time_data >= baseline_start_time) & (time_data <= baseline_end_time)
    baseline_time, baseline_y = time_data[baseline_mask], y_data[baseline_mask]
    if len(baseline_time) < 2: return y_data
    drift_rate, intercept = np.polyfit(baseline_time, baseline_y, 1)
    drift_trend = drift_rate * time_data + intercept
    return y_data - drift_trend