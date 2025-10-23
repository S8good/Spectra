# 传感器性能评估函数 (灵敏度, LOD等)
# nanosense/algorithms/performance.py

from scipy.optimize import curve_fit
import numpy as np


def calculate_sensitivity(x_values, y_values):
    """
    根据给定的X和Y数据，通过线性拟合计算灵敏度。
    """
    if len(x_values) < 2:
        return None
    a, b = np.polyfit(x_values, y_values, 1)
    correlation_matrix = np.corrcoef(x_values, y_values)
    correlation_xy = correlation_matrix[0, 1]
    r_squared = correlation_xy**2
    return {
        'sensitivity': a,
        'intercept': b,
        'r_squared': r_squared
    }

def saturation_binding_model(concentration, R_max, KD):
    """饱和结合模型 (Langmuir / Michaelis-Menten)"""
    return (R_max * concentration) / (KD + concentration)

# 【新增】为 saturation_binding_model 添加一个更通用的别名
michaelis_menten = saturation_binding_model

def calculate_affinity_kd(concentrations, responses):
    """
    根据给定的浓度和响应数据，通过带边界约束的非线性拟合计算亲和力常数 KD。
    """
    if len(concentrations) < 3:
        return None
    try:
        r_max_guess = np.max(responses)
        half_max_response = r_max_guess / 2.0
        kd_guess_index = np.argmin(np.abs(responses - half_max_response))
        kd_guess = concentrations[kd_guess_index]
        initial_guesses = [r_max_guess, kd_guess]
        lower_bounds = [np.max(responses), 0.0]
        upper_bounds = [np.max(responses) * 2, np.inf]
        bounds = (lower_bounds, upper_bounds)
        popt, pcov = curve_fit(
            saturation_binding_model,
            concentrations,
            responses,
            p0=initial_guesses,
            bounds=bounds,
            maxfev=5000
        )
        R_max_fit, KD_fit = popt
        residuals = responses - saturation_binding_model(concentrations, *popt)
        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((responses - np.mean(responses)) ** 2)
        r_squared = 1 - (ss_res / ss_tot)
        return {
            'KD': KD_fit,
            'R_max': R_max_fit,
            'r_squared': r_squared
        }
    except Exception as e:
        print(f"Affinity fit failed: {e}")
        return None


def hill_equation(concentration, R_max, KD, n):
    """
    Hill方程模型。
    """
    return (R_max * np.power(concentration, n)) / (np.power(KD, n) + np.power(concentration, n))


def fit_hill_equation(concentrations, responses):
    """
    使用Hill方程进行非线性拟合。
    """
    if len(concentrations) < 4:
        return None
    try:
        r_max_guess = np.max(responses)
        half_max_response = r_max_guess / 2.0
        kd_guess_index = np.argmin(np.abs(responses - half_max_response))
        kd_guess = concentrations[kd_guess_index]
        n_guess = 1.0
        initial_guesses = [r_max_guess, kd_guess, n_guess]
        lower_bounds = [np.max(responses) * 0.8, 0, 0.1]
        upper_bounds = [np.max(responses) * 2.0, np.inf, 10.0]
        bounds = (lower_bounds, upper_bounds)
        popt, pcov = curve_fit(
            hill_equation,
            concentrations,
            responses,
            p0=initial_guesses,
            bounds=bounds,
            maxfev=8000
        )
        R_max_fit, KD_fit, n_fit = popt
        residuals = responses - hill_equation(concentrations, *popt)
        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((responses - np.mean(responses)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        return {
            'KD': KD_fit,
            'R_max': R_max_fit,
            'n': n_fit,
            'r_squared': r_squared
        }
    except Exception as e:
        print(f"Hill equation fit failed: {e}")
        return None