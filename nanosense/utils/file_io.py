# nanosense/utils/file_io.py

import os
import traceback
import re

import numpy as np
import pandas as pd
from PyQt5.QtWidgets import QFileDialog, QMessageBox
import io
from collections import defaultdict

def _get_start_path(default_path=""):
    """一个内部辅助函数，用于确定文件对话框的起始路径。"""
    if default_path and os.path.isdir(default_path):
        return default_path
    return os.path.expanduser("~")

def save_spectrum(parent, mode_name, x_data, y_data, default_path=""):
    """
    【已升级和国际化】打开文件对话框，将单条光谱数据保存到Excel或CSV/TXT文件。
    """
    start_path = _get_start_path(default_path)
    full_default_path = os.path.join(start_path, f"{mode_name}_result.xlsx")

    # 【修改】使用 parent.tr() 来翻译UI字符串
    file_path, _ = QFileDialog.getSaveFileName(
        parent,
        parent.tr("Save Spectrum Data"),
        full_default_path,
        parent.tr("Excel Files (*.xlsx);;CSV Files (*.csv);;Text Files (*.txt)")
    )

    if file_path:
        try:
            df = pd.DataFrame({f"Wavelength (nm)": x_data, mode_name: y_data})
            if file_path.endswith('.xlsx'):
                df.to_excel(file_path, index=False, engine='openpyxl')
            else:
                df.to_csv(file_path, index=False, float_format='%.8f')
            print(f"数据已成功保存到: {file_path}")
            return file_path
        except Exception as e:
            # 【修改】使用 parent.tr() 来翻译UI字符串
            QMessageBox.critical(parent, parent.tr("Error"), parent.tr("An error occurred while saving the file: {0}").format(str(e)))
    return None

def save_all_spectra_to_file(parent, mode_name, wavelengths, spectra_dict, default_path=""):
    """
    【最终修正和国际化版】将一个包含多种光谱的字典保存到一个多列文件中。
    """
    start_path = _get_start_path(default_path)
    full_default_path = os.path.join(start_path, f"All_Spectra_Data_{mode_name}.xlsx")

    # 【修改】使用 parent.tr() 来翻译UI字符串
    file_path, _ = QFileDialog.getSaveFileName(
        parent,
        parent.tr("Save All Spectra"),
        full_default_path,
        parent.tr("Excel Files (*.xlsx);;CSV Files (*.csv);;Text Files (*.txt)")
    )

    if file_path:
        try:
            data_dict = {f"Wavelength (nm)": wavelengths}
            for name, spec_data in spectra_dict.items():
                if spec_data is not None:
                    data_dict[name] = spec_data

            df = pd.DataFrame(data_dict)

            if file_path.endswith('.xlsx'):
                df.to_excel(file_path, index=False, engine='openpyxl')
            else:
                df.to_csv(file_path, index=False, float_format='%.8f')

            # 【修改】使用 parent.tr() 来翻译UI字符串
            QMessageBox.information(parent, parent.tr("Success"),
                                    parent.tr("All spectral data successfully saved to:\n{0}").format(file_path))
            return file_path
        except Exception as e:
            # 【修改】使用 parent.tr() 来翻译UI字符串
            QMessageBox.critical(parent, parent.tr("Error"), parent.tr("An error occurred while saving the file: {0}").format(str(e)))
    return None

def load_wide_format_spectrum(file_path):
    """
    【新增】专门用于从宽格式文件（如批量采集结果）加载多条光谱数据。
    文件格式假定为：第一列是波长，后续多列是强度数据。

    :param file_path: Excel或CSV文件的路径。
    :return: (wavelengths, spectra_df, error_message)
             wavelengths: 一维Numpy数组。
             spectra_df: 包含所有光谱数据的Pandas DataFrame，列名为光谱名称。
             error_message: 如果出错则为字符串，否则为None。
    """
    try:
        if file_path.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path, header=0)
        else:
            df = pd.read_csv(file_path, header=0)

        if df.shape[1] < 2:
            return None, None, "文件至少需要包含两列（波长和至少一列强度数据）。"

        # 第一列为波长
        wavelengths = df.iloc[:, 0].values

        # 筛选出所有吸收光谱列
        absorbance_cols = [col for col in df.columns if 'absorbance' in col.lower()]

        if not absorbance_cols:
            # 如果没有找到Absorbance列，则回退到加载除波长外的所有列
            spectra_df = df.iloc[:, 1:]
        else:
            # 否则，只加载Absorbance列
            spectra_df = df[absorbance_cols]

        return wavelengths, spectra_df, None

    except Exception as e:
        error_msg = f"加载并解析宽格式文件时出错: {e}"
        print(error_msg)
        return None, None, error_msg

def load_spectrum_from_path(file_path):
    """
    【已升级和修复】根据提供的文件路径直接加载光谱数据。
    能自动处理Excel、逗号分隔或空白分隔的文本文件。
    """
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return None, None

    try:
        # 1. 优先处理 Excel 文件
        if file_path.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path, header=0)
            x_data = df.iloc[:, 0].values
            y_data = df.iloc[:, 1].values
            return x_data, y_data

        # 2. 对于文本文件 (.txt, .csv 等)，优先尝试使用 pandas 读取
        else:
            # 尝试使用逗号作为分隔符
            try:
                df = pd.read_csv(file_path, header=0, sep=',')
                if df.shape[1] >= 2:
                    x_data = df.iloc[:, 0].values
                    y_data = df.iloc[:, 1].values
                    return x_data, y_data
            except Exception:
                # 如果逗号分隔失败，则尝试使用空白作为分隔符
                df = pd.read_csv(file_path, header=0, delim_whitespace=True)
                if df.shape[1] >= 2:
                    x_data = df.iloc[:, 0].values
                    y_data = df.iloc[:, 1].values
                    return x_data, y_data

            # 如果 pandas 两种方法都失败了，抛出异常进入最后的备用方案
            raise ValueError("Pandas failed to parse with common delimiters.")

    except Exception as e:
        print(f"使用 Pandas 加载文件时发生错误 {file_path}: {e}")
        # 3. 最后的备用方案：使用 numpy.loadtxt
        # 这对于非常规或不标准的文本格式可能有效
        try:
            print("尝试使用 numpy.loadtxt 作为备用方法...")
            # delimiter=None 会自动识别空白或逗号
            data = np.loadtxt(file_path, delimiter=None, skiprows=1, comments='#')
            x_data = data[:, 0]
            y_data = data[:, 1]
            return x_data, y_data
        except Exception as e2:
            print(f"使用 numpy.loadtxt 备用方法加载失败: {e2}")
            return None, None

def load_spectra_from_path(path, mode='folder'):
    """
    【全新智能加载函数】
    根据路径和模式加载多个光谱。

    :param path: 文件路径或文件夹路径
    :param mode: 'folder' 或 'file'
    :return: 一个包含光谱数据字典的列表
    """
    spectra_list = []

    if mode == 'folder' and os.path.isdir(path):
        # --- 模式一：加载文件夹内的所有文件 ---
        for filename in sorted(os.listdir(path)):
            if filename.lower().endswith(('.csv', '.txt', '.xlsx', '.xls')):
                file_path = os.path.join(path, filename)
                x, y = load_spectrum_from_path(file_path)  # 复用我们已有的单文件加载逻辑
                if x is not None:
                    spectra_list.append({'x': x, 'y': y, 'name': filename})

    elif mode == 'file' and os.path.isfile(path):
        # --- 模式二：加载单个文件内的所有列 ---
        try:
            if path.lower().endswith(('.xlsx', '.xls')):
                df = pd.read_excel(path, header=0)
            else:  # .csv, .txt
                # 智能判断分隔符
                try:
                    df = pd.read_csv(path, header=0, sep=',')
                    if df.shape[1] < 2: df = pd.read_csv(path, header=0, sep=r'\s+')
                except:
                    df = pd.read_csv(path, header=0, sep=r'\s+')

            if df.shape[1] < 2:
                print(f"警告：文件 {os.path.basename(path)} 的列数少于2，已跳过。")
                return []

            # 第一列是波长
            x_data = df.iloc[:, 0].values

            # 从第二列开始，每一列都是一条光谱
            for i in range(1, df.shape[1]):
                col_name = df.columns[i]
                y_data = df.iloc[:, i].values

                # 去除 NaN 值
                valid_indices = ~np.isnan(y_data)

                spectra_list.append({
                    'x': x_data[valid_indices],
                    'y': y_data[valid_indices],
                    'name': f"{os.path.basename(path)} - {col_name}"
                })
        except Exception as e:
            print(f"从文件 {path} 加载多列数据时发生错误: {e}")
            return []

    return spectra_list

def load_spectrum(parent, default_path=""):
    """
    【已升级和国际化】弹出一个文件对话框，让用户选择一个光谱文件。
    """
    start_path = _get_start_path(default_path)

    # 【修改】使用 parent.tr() 来翻译UI字符串
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        parent.tr("Load Spectrum Data"),
        start_path,
        parent.tr("All Supported Files (*.xlsx *.xls *.csv *.txt);;Excel Files (*.xlsx *.xls);;CSV/Text Files (*.csv *.txt)")
    )

    if file_path:
        wavelengths, spectra = load_spectrum_from_path(file_path)
        if wavelengths is not None:
            return wavelengths, spectra, os.path.basename(file_path)
        else:
            # 【修改】使用 parent.tr() 来翻译UI字符串
            QMessageBox.critical(parent, parent.tr("Load Failed"), parent.tr("Could not parse the file:\n{0}").format(file_path))

    return None, None, None

def load_xy_data_from_file(parent, default_path=""):
    """
    【已升级】用于从文件加载通用的XY数据，能智能识别逗号、空格或Tab分隔符。
    """
    start_path = _get_start_path(default_path)

    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        parent.tr("Load XY Data"), # 使用tr()
        start_path,
        parent.tr("All Supported Files (*.xlsx *.xls *.csv *.txt);;Excel Files (*.xlsx *.xls);;CSV/Text Files (*.csv *.txt)")
    )

    if file_path:
        try:
            if file_path.lower().endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_path, header=0)
            else:
                # --- 核心修改：智能识别分隔符 ---
                try:
                    df = pd.read_csv(file_path, header=0, sep=',')
                    if df.shape[1] < 2:
                        # 【核心修改】使用新的推荐参数 sep='\s+'
                        df = pd.read_csv(file_path, header=0, sep='\s+')
                except Exception:
                    # 【核心修改】使用新的推荐参数 sep='\s+'
                    df = pd.read_csv(file_path, header=0, sep='\s+')

            if df.shape[1] < 2:
                raise ValueError("The file does not contain at least two columns.")

            x_data = df.iloc[:, 0].values
            y_data = df.iloc[:, 1].values
            return x_data, y_data
        except Exception as e:
            QMessageBox.critical(parent, parent.tr("Load Failed"),
                                 parent.tr("Could not parse the XY data file:\n{0}").format(str(e)))

    return None, None

def save_batch_spectrum_data(file_path, wavelengths, absorbance_spectra, signals_list=None, background=None,
                             reference=None, crop_start_wl=None, crop_end_wl=None):
    """
    【已重构】将一个孔位的数据保存到文件中。
    - 保存全波长范围的原始数据。
    - 如果提供了裁切范围，则在子文件夹中创建三种不同格式的裁切后报告。
    """
    try:
        output_dir = os.path.dirname(file_path)
        base_filename = os.path.basename(file_path)
        file_extension = os.path.splitext(base_filename)[1].lower()

        # 确保波长是Numpy数组
        wavelengths = np.array(wavelengths)
        # --- 【修复】第1步: 准备并保存只包含全波长范围原始数据的DataFrame ---
        raw_data_dict = {'Wavelength': wavelengths}
        if background is not None: raw_data_dict['Background'] = background
        if reference is not None: raw_data_dict['Reference'] = reference
        if signals_list:
            for i, sig in enumerate(signals_list):
                if sig is not None: raw_data_dict[f"Signal_{i + 1}"] = sig

        df_raw_full = pd.DataFrame(raw_data_dict)

        full_range_dir = os.path.join(output_dir, 'full_range_spectra')
        os.makedirs(full_range_dir, exist_ok=True)
        full_range_output_path = os.path.join(full_range_dir, base_filename)

        if file_extension == '.xlsx':
            df_raw_full.to_excel(full_range_output_path, index=False, engine='openpyxl')
        else:
            df_raw_full.to_csv(full_range_output_path, index=False, float_format='%.8f')
        print(f"全波长范围原始数据已保存到: {full_range_output_path}")

        # --- 如果没有提供裁切范围或吸收光谱数据，则在此结束 ---
        if crop_start_wl is None or crop_end_wl is None or not absorbance_spectra:
            return

        # --- 【修复】第2步: 单独准备只包含裁切后结果数据的DataFrame ---
        mask = (wavelengths >= crop_start_wl) & (wavelengths <= crop_end_wl)
        cropped_wavelengths = wavelengths[mask]

        results_data_dict = {'Wavelength': cropped_wavelengths}
        for i, abso in enumerate(absorbance_spectra):
            if abso is not None and len(abso) == len(cropped_wavelengths):
                results_data_dict[f"Absorbance_{i + 1}"] = abso

        if len(results_data_dict.keys()) <= 1:
            print(f"警告: {base_filename} 没有有效的吸收光谱数据可以保存，已跳过裁切报告的生成。")
            return

        df_results_cropped = pd.DataFrame(results_data_dict)
        df_raw_cropped = df_raw_full[mask].copy().reset_index(drop=True)

        # --- 后续的报告生成逻辑现在使用正确的数据源 ---
        start_int, end_int = int(crop_start_wl), int(crop_end_wl)
        cropped_range_dir = os.path.join(output_dir, f'cropped_range_{start_int}-{end_int}nm')
        base, ext = os.path.splitext(base_filename)
        cropped_filename = f"{base}_{start_int}-{end_int}nm{ext}"

        # 任务 2: 保存 `spectra_data` 子文件夹
        spectra_data_dir = os.path.join(cropped_range_dir, 'spectra_data')
        os.makedirs(spectra_data_dir, exist_ok=True)
        spectra_data_path = os.path.join(spectra_data_dir, cropped_filename)

        # 【核心修复】从裁切后的原始数据中只选择基础列
        base_columns = ['Wavelength']
        if 'Background' in df_raw_cropped:
            base_columns.append('Background')
        if 'Reference' in df_raw_cropped:
            base_columns.append('Reference')
        df_base_cropped = df_raw_cropped[base_columns]

        # 合并基础数据和结果数据进行保存
        df_combined_cropped = pd.concat([df_base_cropped, df_results_cropped.drop('Wavelength', axis=1)], axis=1)

        if file_extension == '.xlsx':
            df_combined_cropped.to_excel(spectra_data_path, index=False, engine='openpyxl')
        else:
            df_combined_cropped.to_csv(spectra_data_path, index=False, float_format='%.8f')
        print(f"裁切后的组合数据已保存到: {spectra_data_path}")

        # 任务 3: 创建 `aggregated_data` 文件夹和交替格式的Excel
        aggregated_dir = os.path.join(cropped_range_dir, 'aggregated_data')
        os.makedirs(aggregated_dir, exist_ok=True)
        aggregated_path = os.path.join(aggregated_dir, f"aggregated_{cropped_filename}")

        agg_data = {'Wavelength': df_combined_cropped['Wavelength']}
        if 'Background' in df_combined_cropped: agg_data['Background'] = df_combined_cropped['Background']
        if 'Reference' in df_combined_cropped: agg_data['Reference'] = df_combined_cropped['Reference']
        for i in range(len(signals_list)):
            point_num = i + 1
            sig_col, abs_col = f"Signal_{point_num}", f"Absorbance_{point_num}"
            if sig_col in df_combined_cropped: agg_data[sig_col] = df_combined_cropped[sig_col]
            if abs_col in df_combined_cropped: agg_data[abs_col] = df_combined_cropped[abs_col]
        df_aggregated = pd.DataFrame(agg_data)

        if file_extension == '.xlsx':
            df_aggregated.to_excel(aggregated_path, index=False, engine='openpyxl')
        else:
            df_aggregated.to_csv(aggregated_path, index=False, float_format='%.8f')
        print(f"聚合的交替格式报告已保存到: {aggregated_path}")

        # 任务 4: 创建 `per_point_sheets` 文件夹和每点一页的Excel
        # (这个功能强制使用Excel，因为CSV不支持多工作表)
        per_point_dir = os.path.join(cropped_range_dir, 'per_point_sheets')
        os.makedirs(per_point_dir, exist_ok=True)
        per_point_base, _ = os.path.splitext(cropped_filename)
        per_point_path = os.path.join(per_point_dir, f"per_point_{per_point_base}.xlsx")

        with pd.ExcelWriter(per_point_path, engine='openpyxl') as writer:
            for i in range(len(signals_list)):
                point_num = i + 1
                sheet_name = f"Point_{point_num}"

                sheet_data = {'Wavelength': df_combined_cropped['Wavelength']}
                if 'Background' in df_combined_cropped: sheet_data['Background'] = df_combined_cropped['Background']
                if 'Reference' in df_combined_cropped: sheet_data['Reference'] = df_combined_cropped['Reference']

                sig_col, abs_col = f"Signal_{point_num}", f"Absorbance_{point_num}"
                if sig_col in df_combined_cropped: sheet_data['Signal'] = df_combined_cropped[sig_col]
                if abs_col in df_combined_cropped: sheet_data['Absorbance'] = df_combined_cropped[abs_col]

                df_sheet = pd.DataFrame(sheet_data)
                df_sheet.to_excel(writer, sheet_name=sheet_name, index=False)
        print(f"每点一页格式的报告已保存到: {per_point_path}")


    except Exception as e:
        print(f"保存批量光谱数据时发生严重错误: {e}")
        traceback.print_exc()  # 打印详细的错误追溯

def load_wide_format_spectrum(file_path):
    """
    加载宽格式的光谱文件（第一列为波长，后续列为光谱数据）。
    能自动处理Excel、逗号分隔或空白分隔的文本文件。

    :param file_path: 文件路径
    :return: (wavelengths, spectra_df, error_message)
    """
    if not os.path.exists(file_path):
        return None, None, f"文件不存在: {file_path}"

    try:
        # 优先处理 Excel 文件
        if file_path.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path, header=0)
        # 再处理文本文件 (.txt, .csv 等)
        else:
            try:
                # 尝试用逗号作为分隔符
                df = pd.read_csv(file_path, header=0, sep=',')
                if df.shape[1] < 2:  # 如果列数少于2，说明分隔符可能不对
                    df = pd.read_csv(file_path, header=0, delim_whitespace=True)
            except Exception:
                # 如果逗号失败，尝试用任意空白作为分隔符
                df = pd.read_csv(file_path, header=0, delim_whitespace=True)

        if df.shape[1] < 2:
            return None, None, f"文件 {os.path.basename(file_path)} 的有效数据列少于2。"

        wavelengths = df.iloc[:, 0].values
        spectra_df = df.iloc[:, 1:]

        return wavelengths, spectra_df, None

    except Exception as e:
        return None, None, f"加载文件时发生错误: {e}"

def export_experiments_to_excel(experiments_data, file_path):
    """
    【已重构】将一个或多个实验的完整数据导出到一个多工作表的Excel文件中。
    - Summary sheet: 汇总所有实验的元数据和分析结果。
    - 每个实验现在会生成多个独立的sheet来存放不同类型的光谱数据。
    """
    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            # 1. 创建总览工作表 (逻辑不变)
            summary_list = []
            for exp_data in experiments_data:
                meta = exp_data['metadata']
                summary = {
                    'Experiment ID': meta['experiment_id'],
                    'Experiment Name': meta['name'],
                    'Timestamp': meta['timestamp'],
                    'Type': meta['type'],
                    'Operator': meta['operator'],
                    'Notes': meta['notes']
                }
                for i, result in enumerate(exp_data['results']):
                    # 将结果数据打平，放入总览表
                    for key, value in result['data'].items():
                        summary[f"Result_{i + 1}_{key}"] = value
                summary_list.append(summary)

            summary_df = pd.DataFrame(summary_list)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

            # 2. 【核心重构】为每个实验的光谱数据创建更精细的工作表
            for exp_data in experiments_data:
                exp_id = exp_data['metadata']['experiment_id']
                exp_name_safe = "".join(c for c in exp_data['metadata']['name'] if c.isalnum())[:15]

                # 如果没有光谱数据，则跳过
                if not exp_data['spectra']:
                    continue

                # 将光谱按类型分组
                spectra_by_type = defaultdict(list)
                for spec in exp_data['spectra']:
                    spectra_by_type[spec['type']].append(spec['intensities'])

                # 为每个类型的数据创建一个DataFrame并写入独立的Sheet
                for spec_type, intensities_list in spectra_by_type.items():
                    # 创建一个包含波长的基础DataFrame
                    df_spec = pd.DataFrame({'Wavelength': exp_data['spectra'][0]['wavelengths']})

                    # 将同类型的所有光谱作为新列添加
                    for i, intensities in enumerate(intensities_list):
                        col_name = f"{spec_type}" if len(intensities_list) == 1 else f"{spec_type}_{i + 1}"
                        df_spec[col_name] = intensities

                    # 创建一个简短且唯一的工作表名称
                    sheet_name = f"Exp{exp_id}_{spec_type[:20]}"
                    df_spec.to_excel(writer, sheet_name=sheet_name, index=False)

        return True, ""
    except Exception as e:
        return False, str(e)
# 【新增】导出逻辑的主函数
def export_data_custom(parent, experiments_data):
    """
    根据用户的两种不同需求，导出两个独立的Excel文件。
    """
    if not experiments_data:
        return

    # 1. 弹出文件保存对话框，让用户指定一个基础文件名
    default_path = os.path.join(os.path.expanduser("~"), "Exported_Data.xlsx")
    file_path, _ = QFileDialog.getSaveFileName(
        parent, parent.tr("Export Experiment Data - Choose a base name"), default_path,
        parent.tr("Excel Files (*.xlsx)")
    )
    if not file_path:
        return

    # 从完整路径中分离出目录、基础名和扩展名
    output_dir = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]

    # --- 生成第一个文件：详细数据 ---
    detailed_path = os.path.join(output_dir, f"{base_name}_Detailed.xlsx")
    success1, msg1 = _export_detailed_spectra(experiments_data, detailed_path)

    # --- 生成第二个文件：聚合数据 ---
    aggregated_path = os.path.join(output_dir, f"{base_name}_Aggregated.xlsx")
    success2, msg2 = _export_aggregated_results(experiments_data, aggregated_path)

    # --- 最终反馈 ---
    final_message = []
    if success1:
        final_message.append(parent.tr("Detailed report saved to:\n{0}").format(detailed_path))
    else:
        final_message.append(parent.tr("Failed to save detailed report: {0}").format(msg1))

    if success2:
        final_message.append(parent.tr("Aggregated report saved to:\n{0}").format(aggregated_path))
    else:
        # 如果msg2不为空，说明是可预期的跳过，而不是错误
        if msg2:
            final_message.append(parent.tr("Aggregated report was not generated: {0}").format(msg2))
        else:  # 如果msg2为空，说明发生了意外错误
            final_message.append(parent.tr("Failed to save aggregated report."))

    QMessageBox.information(parent, parent.tr("Export Complete"), "\n\n".join(final_message))
# 【新增】生成“详细数据”文件的辅助函数
def _generate_unique_sheet_name(base_name, used_names):
    """
    生成符合 Excel 限制（长度 <= 31，不能包含 \\ / ? * : [ ] ）且不重复的工作表名称。
    """
    if not base_name:
        base_name = "Sheet"

    # 替换非法字符
    sanitized = re.sub(r'[\\\/\?\*\:\[\]]', '_', base_name)
    sanitized = sanitized.strip()
    if not sanitized:
        sanitized = "Sheet"

    # 限制长度
    sanitized = sanitized[:31]

    unique_name = sanitized
    counter = 1
    while unique_name in used_names:
        suffix = f"_{counter}"
        unique_name = f"{sanitized[:31 - len(suffix)]}{suffix}"
        counter += 1

    used_names.add(unique_name)
    return unique_name

def _flatten_data_to_rows(data, prefix=""):
    """
    将嵌套的 dict/list 结构展开为 (key, value) 的序列，便于导出成表格。
    """
    if isinstance(data, np.generic):
        data = data.item()
    if isinstance(data, np.ndarray):
        data = data.tolist()
    if isinstance(data, pd.Series):
        data = data.tolist()
    if isinstance(data, pd.Timestamp):
        data = data.isoformat()

    rows = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_data_to_rows(value, new_prefix))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            new_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            rows.extend(_flatten_data_to_rows(value, new_prefix))
    else:
        key = prefix or "value"
        rows.append((key, data))

    return rows

def _export_detailed_spectra(experiments_data, file_path):
    """
    导出文件1：每个“保存事件”一个sheet，包含其完整的四种光谱。
    """
    try:
        used_sheet_names = set()
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            sheet_counter = 1
            for exp_data in experiments_data:
                for spectra_set in exp_data['spectra_sets']:
                    wavelengths = spectra_set.get('wavelengths')
                    if wavelengths is None:
                        continue

                    if isinstance(wavelengths, np.ndarray):
                        wavelengths = wavelengths.tolist()
                    if not isinstance(wavelengths, (list, tuple)) or len(wavelengths) == 0:
                        continue

                    df = pd.DataFrame({'Wavelength': wavelengths})
                    data_columns_added = 0

                    for column_key, column_name in [
                        ('Signal', 'Signal'),
                        ('Background', 'Background'),
                        ('Reference', 'Reference')
                    ]:
                        values = spectra_set.get(column_key)
                        if isinstance(values, np.ndarray):
                            values = values.tolist()
                        if isinstance(values, (list, tuple)) and len(values) == len(wavelengths):
                            df[column_name] = values
                            data_columns_added += 1

                    result_key = next((k for k in spectra_set if k.startswith('Result_')), None)
                    if result_key:
                        result_values = spectra_set.get(result_key)
                        if isinstance(result_values, np.ndarray):
                            result_values = result_values.tolist()
                        if isinstance(result_values, (list, tuple)) and len(result_values) == len(wavelengths):
                            df[result_key] = result_values
                            data_columns_added += 1

                    if data_columns_added == 0:
                        continue

                    sheet_name = _generate_unique_sheet_name(f'spectra{sheet_counter}', used_sheet_names)
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    sheet_counter += 1

            # 为每个实验添加包含元数据与分析结果的工作表
            for exp_data in experiments_data:
                meta = exp_data.get('metadata', {})
                exp_id = meta.get('experiment_id', 'Unknown')
                summary_rows = []
                kinetics_series_exports = []

                # 基础元数据
                basic_meta_items = [
                    ('Experiment ID', meta.get('experiment_id')),
                    ('Project ID', meta.get('project_id')),
                    ('Experiment Name', meta.get('name')),
                    ('Type', meta.get('type')),
                    ('Timestamp', meta.get('timestamp')),
                    ('Operator', meta.get('operator')),
                    ('Notes', meta.get('notes'))
                ]
                for key, value in basic_meta_items:
                    summary_rows.append({'Section': 'Metadata', 'Item': key, 'Value': value if value is not None else ''})

                # 配置快照（如果存在）
                config_snapshot = meta.get('config_snapshot') or {}
                if config_snapshot:
                    for key, value in _flatten_data_to_rows(config_snapshot, prefix='config_snapshot'):
                        summary_rows.append({'Section': 'Metadata', 'Item': key, 'Value': value})

                # 分析/动力学结果
                for result in exp_data.get('results', []):
                    analysis_type = result.get('type') or 'Analysis'
                    data = result.get('data')
                    if isinstance(data, dict) and analysis_type == 'Kinetics_Fit':
                        time_series = data.get('time_series')
                        if isinstance(time_series, list) and time_series:
                            kinetics_series_exports.append({
                                'analysis_type': analysis_type,
                                'series': time_series
                            })
                            data = {k: v for k, v in data.items() if k != 'time_series'}
                    flattened = _flatten_data_to_rows(data) if data is not None else []
                    if flattened:
                        for key, value in flattened:
                            summary_rows.append({'Section': analysis_type, 'Item': key, 'Value': value})
                    else:
                        summary_rows.append({'Section': analysis_type, 'Item': 'value', 'Value': data})

                if summary_rows:
                    summary_df = pd.DataFrame(summary_rows, columns=['Section', 'Item', 'Value'])
                    summary_df = summary_df.rename(columns={'Section': 'Category', 'Item': 'Parameter'})
                    sheet_name = _generate_unique_sheet_name(f'Exp{exp_id}_Summary', used_sheet_names)
                    summary_df.to_excel(writer, sheet_name=sheet_name, index=False)

                # 如果存在动力学时间序列，则为其创建独立工作表
                for index, series_info in enumerate(kinetics_series_exports, start=1):
                    series = series_info.get('series')
                    if not isinstance(series, list) or not series:
                        continue

                    series_df = pd.DataFrame(series)
                    if series_df.empty:
                        continue

                    rename_map = {}
                    for column in series_df.columns:
                        lower = str(column).lower()
                        if 'time' in lower:
                            rename_map[column] = 'Time (s)'
                        elif 'peak' in lower:
                            rename_map[column] = 'Peak Wavelength (nm)'
                        else:
                            rename_map[column] = column
                    series_df = series_df.rename(columns=rename_map)

                    preferred_order = [col for col in ['Time (s)', 'Peak Wavelength (nm)'] if col in series_df.columns]
                    other_columns = [col for col in series_df.columns if col not in preferred_order]
                    ordered_columns = preferred_order + other_columns
                    series_df = series_df[ordered_columns]

                    base_name = f"Exp{exp_id}_Kinetics"
                    if len(kinetics_series_exports) > 1:
                        base_name = f"{base_name}{index}"
                    sheet_name = _generate_unique_sheet_name(base_name, used_sheet_names)
                    series_df.to_excel(writer, sheet_name=sheet_name, index=False)

        return True, ""
    except Exception as e:
        return False, str(e)
# 【最终版本】生成“聚合数据”文件的辅助函数
def _export_aggregated_results(experiments_data, file_path):
    """
    【已重构】导出文件2：
    如果所有结果谱的背景谱和参考谱相同，则将所有信号谱和结果谱分别聚合到两个sheet中。
    """
    try:
        all_sets = []
        for exp_data in experiments_data:
            all_sets.extend(exp_data['spectra_sets'])

        if not all_sets:
            return False, "No data to process."  # 翻译: "没有可处理的数据。"

        # 检查是否所有“保存事件”都有Background和Reference
        first_set = all_sets[0]
        if not all(k in first_set for k in ['Background', 'Reference']):
            return False, "Not all measurements have a complete set of Background and Reference spectra."  # 翻译: "并非所有测量都包含完整的背景和参考光谱。"

        # 提取第一个事件的基准光谱作为比较基准
        base_background = np.array(first_set['Background'])
        base_reference = np.array(first_set['Reference'])

        # 检查后续所有事件的基准光谱是否与第一个完全相同
        for i in range(1, len(all_sets)):
            current_set = all_sets[i]
            if not all(k in current_set for k in ['Background', 'Reference']):
                return False, "Inconsistent data sets found."  # 翻译: "发现不一致的数据集。"

            if not (np.array_equal(base_background, np.array(current_set['Background'])) and
                    np.array_equal(base_reference, np.array(current_set['Reference']))):
                return False, "The Background or Reference spectra are not identical across all selected measurements."  # 翻译: "所选测量的背景或参考光谱不完全相同。"

        # --- 如果所有检查都通过，则开始构建聚合DataFrame ---

        # 1. 构建信号谱的DataFrame
        df_signals = pd.DataFrame({
            'Wavelength': first_set['wavelengths'],
            'Background': base_background,
            'Reference': base_reference
        })
        for i, spec_set in enumerate(all_sets):
            if 'Signal' in spec_set:
                df_signals[f"Signal_{i + 1}"] = spec_set['Signal']

        # 2. 构建结果谱的DataFrame
        df_results = pd.DataFrame({
            'Wavelength': first_set['wavelengths'],
            'Background': base_background,
            'Reference': base_reference
        })
        for i, spec_set in enumerate(all_sets):
            result_key = next((k for k in spec_set if k.startswith('Result_')), None)
            if result_key:
                df_results[f"{result_key}_{i + 1}"] = spec_set[result_key]

        # 3. 将两个DataFrame写入同一个Excel文件的不同Sheet
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df_signals.to_excel(writer, sheet_name='Aggregated_Signals', index=False)
            df_results.to_excel(writer, sheet_name='Aggregated_Results', index=False)

        return True, ""
    except Exception as e:
        return False, str(e)
