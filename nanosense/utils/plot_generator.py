# nanosense/utils/plot_generator.py

# (文件顶部的 import 语句保持不变)
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import traceback

from nanosense.algorithms.peak_analysis import find_main_resonance_peak
from nanosense.algorithms.preprocessing import baseline_als, smooth_savitzky_golay
from nanosense.utils.config_manager import load_settings


def generate_plots_for_point(point_name, df, output_folder, preprocessing_params):
    """
    【最终版】根据UI传递的参数，执行真正的两阶段平滑，并只绘制吸收光谱。
    """
    # (文件夹创建和数据加载部分无变化)
    original_dir = os.path.join(output_folder, "original_plots")
    focused_dir = os.path.join(output_folder, "normalized_plots_focus_peak")
    fixed_range_dir = os.path.join(output_folder, "normalized_plots_fixed_range")
    original_fixed_range_dir = os.path.join(output_folder, "original_plots_fixed_range")

    os.makedirs(original_dir, exist_ok=True)
    os.makedirs(focused_dir, exist_ok=True)
    os.makedirs(fixed_range_dir, exist_ok=True)
    os.makedirs(original_fixed_range_dir, exist_ok=True)

    try:
        plt.style.use('dark_background')
        wavelengths = df.iloc[:, 0].values

        spectra_df = df.iloc[:, 3:]
        if spectra_df.empty:
            print(f"警告：在为 {point_name} 生成图表时，未找到任何有效的光谱数据列（从第4列开始）。")
            return

        # (fig1, 原始光谱图部分无变化)
        fig1, ax1 = plt.subplots(figsize=(10, 6))
        for col in spectra_df.columns:
            ax1.plot(wavelengths, spectra_df[col], label=col)
        ax1.set_title(f'Original Spectra - {point_name}')
        ax1.set_xlabel('Wavelength (nm)')
        ax1.set_ylabel('Absorbance')
        ax1.legend()
        ax1.grid(True)
        fig1.savefig(os.path.join(original_dir, f"{point_name.lower().replace(' ', '_')}_original.png"))
        plt.close(fig1)

        app_settings = load_settings()
        wl_start = app_settings.get('analysis_wl_start', 450.0)
        wl_end = app_settings.get('analysis_wl_end', 750.0)

        # (预处理和寻峰部分无变化)
        processed_data = {'Wavelength (nm)': wavelengths}
        peak_locations = []
        for col in spectra_df.columns:
            spectrum_data = spectra_df[col].values
            baseline = baseline_als(spectrum_data, lam=preprocessing_params['als_lambda'],
                                    p=preprocessing_params['als_p'])
            baseline_corrected = spectrum_data - baseline
            coarse_smoothed = smooth_savitzky_golay(baseline_corrected,
                                                    window_length=preprocessing_params['sg_window_coarse'],
                                                    polyorder=preprocessing_params['sg_polyorder_coarse'])
            fine_smoothed = smooth_savitzky_golay(coarse_smoothed, window_length=preprocessing_params['sg_window_fine'],
                                                  polyorder=preprocessing_params['sg_polyorder_fine'])
            if np.max(fine_smoothed) != np.min(fine_smoothed):
                processed_data[col] = (fine_smoothed - np.min(fine_smoothed)) / (
                            np.max(fine_smoothed) - np.min(fine_smoothed))
            else:
                processed_data[col] = fine_smoothed
            range_mask = (wavelengths >= wl_start) & (wavelengths <= wl_end)
            y_subset = processed_data[col][range_mask]
            x_subset = wavelengths[range_mask]
            peak_index_in_subset, _ = find_main_resonance_peak(y_subset, x_subset)
            if peak_index_in_subset is not None:
                global_indices_in_range = np.where(range_mask)[0]
                peak_index_global = global_indices_in_range[peak_index_in_subset]
                peak_locations.append(wavelengths[peak_index_global])
        processed_df = pd.DataFrame(processed_data)

        # --- 3. 生成峰区放大图 (增加Y轴自动缩放) ---
        if peak_locations:
            center_peak = np.mean(peak_locations)
            fig3, ax3 = plt.subplots(figsize=(10, 6))
            for col in processed_df.columns[1:]:
                ax3.plot(wavelengths, processed_df[col], label=col)

            ax3.set_title(f'Peak Focus - {point_name}')
            ax3.set_xlabel('Wavelength (nm)')
            ax3.set_ylabel('Normalized Intensity')

            # 设置X轴范围 (无变化)
            x_lim_min, x_lim_max = center_peak - 50, center_peak + 50
            ax3.set_xlim(x_lim_min, x_lim_max)

            # --- 【核心修复】计算并设置Y轴的显示范围 ---
            # 1. 找出在X轴缩放范围内的所有数据点
            y_min_in_view = np.inf
            y_max_in_view = -np.inf
            zoom_mask = (wavelengths >= x_lim_min) & (wavelengths <= x_lim_max)

            for col in processed_df.columns[1:]:
                y_data_in_view = processed_df[col][zoom_mask]
                if y_data_in_view.size > 0:
                    y_min_in_view = min(y_min_in_view, y_data_in_view.min())
                    y_max_in_view = max(y_max_in_view, y_data_in_view.max())

            # 2. 计算一点边距(padding)，让视图更美观
            if np.isfinite(y_min_in_view) and np.isfinite(y_max_in_view):
                y_range = y_max_in_view - y_min_in_view
                padding = y_range * 0.1  # 10%的边距
                ax3.set_ylim(y_min_in_view - padding, y_max_in_view + padding)
            # --- 修复结束 ---

            ax3.legend()
            ax3.grid(True)
            fig3.savefig(os.path.join(focused_dir, f"{point_name.lower().replace(' ', '_')}_focused.png"))
            plt.close(fig3)

        # (fig4 和 fig5 部分无变化)
        # --- 4. 生成固定范围的【处理后】光谱图 ---
        fixed_range_mask = (wavelengths >= wl_start) & (wavelengths <= wl_end)
        fig4, ax4 = plt.subplots(figsize=(10, 6))
        for col in processed_df.columns[1:]:
            ax4.plot(wavelengths[fixed_range_mask], processed_df[col][fixed_range_mask], label=col)
        ax4.set_title(f'Fixed Range ({wl_start}-{wl_end}nm) - {point_name}')
        ax4.set_xlabel('Wavelength (nm)')
        ax4.set_ylabel('Normalized Intensity')
        ax4.legend()
        ax4.grid(True)
        fig4.savefig(os.path.join(fixed_range_dir, f"{point_name.lower().replace(' ', '_')}_fixed_range.png"))
        plt.close(fig4)

        # --- 5. 生成固定范围的【原始】光谱图 ---
        fig5, ax5 = plt.subplots(figsize=(10, 6))
        for col in spectra_df.columns:
            ax5.plot(wavelengths[fixed_range_mask], spectra_df[col][fixed_range_mask], label=col)
        ax5.set_title(f'Original Spectra Fixed Range ({wl_start}-{wl_end}nm) - {point_name}')
        ax5.set_xlabel('Wavelength (nm)')
        ax5.set_ylabel('Absorbance')
        ax5.legend()
        ax5.grid(True)
        fig5.savefig(
            os.path.join(original_fixed_range_dir, f"{point_name.lower().replace(' ', '_')}_original_fixed_range.png"))
        plt.close(fig5)

    except Exception as e:
        error_details = traceback.format_exc()
        detailed_error_message = f"为 {point_name} 生成图表时发生严重错误: {e}\n\n{error_details}"
        print(detailed_error_message)
        raise e