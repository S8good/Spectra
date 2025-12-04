#!/usr/bin/env python3
"""
测试峰值分析功能的简单脚本
"""

import sys
import os
import numpy as np

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.insert(0, project_root)

# 测试peak_analysis模块
from nanosense.algorithms.peak_analysis import (
    find_main_resonance_peak,
    calculate_fwhm,
    PEAK_METHOD_LABELS
)

def test_peak_analysis():
    """测试峰值分析功能"""
    print("=== 测试峰值分析功能 ===")
    
    # 创建测试数据（模拟一个简单的峰值）
    wavelengths = np.linspace(500, 800, 100)
    center = 650
    sigma = 20
    intensity = np.exp(-((wavelengths - center) ** 2) / (2 * sigma ** 2)) * 1000
    intensity += np.random.normal(0, 50, len(wavelengths))  # 添加一些噪声
    
    print(f"测试波长范围: {wavelengths[0]} - {wavelengths[-1]} nm")
    print(f"预期峰值位置: {center} nm")
    
    # 测试所有峰值检测方法
    for method_key in PEAK_METHOD_LABELS.keys():
        print(f"\n测试方法: {PEAK_METHOD_LABELS[method_key]} ({method_key})")
        
        try:
            # 调用寻峰函数
            peak_index, peak_properties = find_main_resonance_peak(intensity, wavelengths=wavelengths, method=method_key)
            
            if peak_index is not None:
                peak_wavelength = wavelengths[peak_index]
                peak_intensity = intensity[peak_index]
                
                print(f"  检测到峰值: {peak_wavelength:.2f} nm, 强度: {peak_intensity:.2f}")
                print(f"  峰值索引: {peak_index}")
                print(f"  峰值属性: {peak_properties}")
                
                # 计算FWHM
                fwhm = calculate_fwhm(wavelengths, intensity, [peak_index])
                if fwhm and len(fwhm) > 0:
                    print(f"  FWHM: {fwhm[0]:.2f} nm")
                else:
                    print(f"  FWHM: 无法计算")
            else:
                print(f"  未检测到峰值")
                
        except Exception as e:
            print(f"  测试失败: {e}")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    test_peak_analysis()