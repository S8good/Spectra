# nanosense/utils/data_processor.py (新版本)
import os

import pandas as pd
import numpy as np
from collections import defaultdict
import re

from nanosense.algorithms.peak_analysis import find_main_resonance_peak
from nanosense.algorithms.preprocessing import baseline_als, smooth_savitzky_golay
from nanosense.utils.file_io import load_wide_format_spectrum


def process_excel_file(file_path):
    """
    【已修复】读取一个包含多个工作表的Excel文件，并按测量点对数据进行重组。
    修复了当列名无法正确解析时导致的 'NoneType' 错误。
    """
    try:
        xls = pd.ExcelFile(file_path)
    except Exception as e:
        return None, [f"无法读取Excel文件: {e}"]

    sheet_names = xls.sheet_names
    grouped_data = defaultdict(list)
    report_log = [f"成功打开文件，找到 {len(sheet_names)} 个工作表: {', '.join(sheet_names)}"]

    for sheet_name in sheet_names:
        try:
            df = pd.read_excel(xls, sheet_name=sheet_name)

            x_axis_col = df.columns[0]
            x_axis_data = df[[x_axis_col]]

            for col_name in df.columns[1:]:
                col_name_str = str(col_name)

                # --- 核心修复：使用更简洁、更安全的一步式正则表达式 ---
                # 这个新规则会直接匹配可选的前缀（如 "Point "）和必须的数字部分
                match = re.match(r"(?:[Pp]oint\s*|\b[Pp])?(\d+)", col_name_str)

                if match:
                    # group(1) 现在直接就是我们需要的数字部分
                    number_part = match.group(1)
                    point_name = f"Point {number_part}"

                    point_df = pd.concat([x_axis_data, df[[col_name]]], axis=1)
                    point_df.rename(columns={col_name: sheet_name}, inplace=True)

                    grouped_data[point_name].append(point_df)

            report_log.append(f"  - 已处理工作表 '{sheet_name}'")

        except Exception as e:
            report_log.append(f"  - !! 处理工作表 '{sheet_name}' 时出错: {e}")
            continue

    # --- 数据合并部分（保持不变）---
    final_data = {}
    x_axis_col = ""  # 初始化 x_axis_col
    for point_name, df_list in grouped_data.items():
        if not df_list: continue

        # 确保 x_axis_col 被正确设置
        if not x_axis_col:
            x_axis_col = df_list[0].columns[0]

        merged_df = df_list[0]
        for i in range(1, len(df_list)):
            if x_axis_col not in df_list[i].columns:
                report_log.append(f"  - !! 警告：在合并 '{point_name}' 时，部分工作表中缺少X轴列 '{x_axis_col}'")
                continue
            merged_df = pd.merge(merged_df, df_list[i], on=x_axis_col, how='outer')

        final_data[point_name] = merged_df.sort_values(by=x_axis_col).reset_index(drop=True)
        report_log.append(f"已成功合并测量点 '{point_name}' 的数据。")

    if not final_data:
        report_log.append("处理完成，但未能根据规则识别和合并任何测量点。请检查Excel列名是否符合'Point X'或纯数字格式。")

    return final_data, report_log

def export_grouped_data(output_folder, grouped_data, selected_points):
    """
    【已升级】将选定的分组数据导出到单独的Excel文件中。
    现在会将所有Excel文件保存在一个名为 "output_tables" 的子文件夹中。

    Args:
        output_folder (str): 用户选择的主输出文件夹路径。
        grouped_data (dict): 从 process_excel_file 返回的数据字典。
        selected_points (list): 用户勾选的要导出的测量点名称列表。
    """
    exported_files = []

    tables_dir = os.path.join(output_folder, "output_tables")
    os.makedirs(tables_dir, exist_ok=True)
    # --- 修改结束 ---

    for point_name in selected_points:
        if point_name in grouped_data:
            df_to_export = grouped_data[point_name]
            safe_filename = f"{point_name.lower().replace(' ', '_')}.xlsx"

            # --- 核心修改：使用新的子文件夹路径 ---
            output_path = os.path.join(tables_dir, safe_filename)
            # --- 修改结束 ---

            try:
                df_to_export.to_excel(output_path, index=False)
                exported_files.append(output_path)
            except Exception as e:
                print(f"导出 {point_name} 到 {output_path} 时失败: {e}")

    return exported_files

def generate_summary_reports(output_folder, grouped_data, selected_points, preprocessing_params, app_settings):
    """
    【最终可配置版】
    1. 从 app_settings 获取分析波长范围。
    2. 先对全波段数据进行基线校正。
    3. 再截取用户定义的范围进行平滑和寻峰。
    4. 对输出的Excel汇总表按测量点编号进行自然排序。
    """
    peak_positions = defaultdict(dict)

    # --- 核心修改：从配置中获取分析范围 ---
    wl_start = app_settings.get('analysis_wl_start', 450.0)
    wl_end = app_settings.get('analysis_wl_end', 750.0)
    # --- 修改结束 ---

    for point_name in selected_points:
        if point_name not in grouped_data:
            continue

        df = grouped_data[point_name]
        original_wavelengths = df.iloc[:, 0].values

        for col_name in df.columns[1:]:
            original_intensity = df[col_name].values

            # 步骤 1: 先在【全波段】原始数据上进行基线校正
            baseline = baseline_als(original_intensity, lam=preprocessing_params['als_lambda'],
                                    p=preprocessing_params['als_p'])
            baseline_corrected_full = original_intensity - baseline

            # 步骤 2: 然后，截取用户定义的范围，用于后续处理
            range_mask = (original_wavelengths >= wl_start) & (original_wavelengths <= wl_end)
            wavelengths_subset = original_wavelengths[range_mask]
            intensity_subset = baseline_corrected_full[range_mask]

            if len(wavelengths_subset) < 20: # 保持安全检查
                peak_positions[point_name][col_name] = np.nan
                continue

            # 步骤 3: 在截取后的数据子集上进行两阶段平滑
            sg_two_stage = preprocessing_params.get('sg_two_stage', True)
            coarse_smoothed = smooth_savitzky_golay(intensity_subset,
                                                    window_length=preprocessing_params['sg_window_coarse'],
                                                    polyorder=preprocessing_params['sg_polyorder_coarse'])
            if sg_two_stage:
                fine_smoothed = smooth_savitzky_golay(
                    coarse_smoothed,
                    window_length=preprocessing_params['sg_window_fine'],
                    polyorder=preprocessing_params['sg_polyorder_fine']
                )
            else:
                fine_smoothed = coarse_smoothed

            # 步骤 4: 在最终处理后的数据子集上寻找主峰
            peak_idx, _ = find_main_resonance_peak(fine_smoothed, wavelengths_subset, min_height=0)

            if peak_idx is not None:
                peak_wavelength = wavelengths_subset[peak_idx]
                peak_positions[point_name][col_name] = peak_wavelength
            else:
                peak_positions[point_name][col_name] = np.nan

    if not peak_positions:
        return

    # --- 后续的DataFrame创建和保存逻辑不变 ---
    positions_df = pd.DataFrame(peak_positions).T
    sort_key = positions_df.index.str.extract(r'(\d+)', expand=False).astype(int)
    positions_df = positions_df.sort_index(key=lambda x: sort_key)

    shifts_df = positions_df.copy()
    if not shifts_df.empty and len(shifts_df.columns) > 0:
        first_measurement_column = shifts_df.columns[0]
        shifts_df = shifts_df.subtract(shifts_df[first_measurement_column], axis=0)

    tables_dir = os.path.join(output_folder, "output_tables")
    os.makedirs(tables_dir, exist_ok=True)

    positions_output_path = os.path.join(tables_dir, "peak_positions.xlsx")
    shifts_output_path = os.path.join(tables_dir, "peak_shifts.xlsx")

    try:
        positions_df.to_excel(positions_output_path, index=True)
        shifts_df.to_excel(shifts_output_path, index=True)
        print(f"汇总表已保存到 {tables_dir}")
    except Exception as e:
        print(f"保存汇总表时出错: {e}")


def aggregate_batch_files(folder_path):
    """
    【新增】聚合一个文件夹内所有独立的批量采集文件。
    将它们合并成一个与 process_excel_file 输出格式兼容的数据字典。
    """
    report_log = [f"开始处理文件夹: {folder_path}"]
    final_data = {}

    # 假设文件名格式为 'timestamp_A1_100nM.csv'
    # 我们用正则表达式来解析文件名，提取孔位信息
    pattern = re.compile(r".*?_([A-H]\d{1,2})_.*")

    # 第一次遍历：按孔位分组文件
    well_files = defaultdict(list)
    for filename in sorted(os.listdir(folder_path)):
        if filename.lower().endswith(('.csv', '.txt', '.xlsx')):
            match = pattern.match(filename)
            if match:
                well_id = match.group(1)
                well_files[well_id].append(os.path.join(folder_path, filename))

    if not well_files:
        report_log.append("错误：在文件夹中未找到符合 '..._A1_...' 格式的光谱文件。")
        return None, report_log

    grouped_data = {}
    for well_id, files in well_files.items():
        point_name = f"Point_{well_id}"

        # 由于一个文件现在就包含了所有重复测量，我们只处理每个孔位的第一个文件
        if not files:
            continue

        file_to_process = files[0]  # 只取第一个匹配的文件

        # --- 核心修改在这里 ---
        # 调用新的专用函数来加载所有吸收光谱
        wavelengths, spectra_df, error = load_wide_format_spectrum(file_to_process)

        if error:
            report_log.append(f"处理文件 {os.path.basename(file_to_process)} 时出错: {error}")
            continue

        if wavelengths is not None and spectra_df is not None:
            # 将波长列添加到DataFrame的开头
            full_df = pd.concat([pd.DataFrame({'Wavelength (nm)': wavelengths}), spectra_df], axis=1)
            grouped_data[point_name] = full_df
            report_log.append(f"成功聚合 {well_id} 的 {len(spectra_df.columns)} 条光谱。")

    if not grouped_data:
        report_log.append("错误：虽然找到了文件，但未能成功解析出任何光谱数据。")
        return None, report_log

    return grouped_data, report_log