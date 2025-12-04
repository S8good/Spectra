# nanosense/utils/report_generator.py

import os
import time
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from nanosense.algorithms.peak_analysis import find_main_resonance_peak, calculate_fwhm


def run_analysis_pipeline(wavelengths, spectra_df):
    """
    分析流水线，负责对加载的光谱数据进行核心计算。
    """
    try:
        peak_metrics_list = []

        # 1. 遍历每一条光谱（DataFrame的每一列）
        for col_name in spectra_df.columns:
            spectrum_data = spectra_df[col_name].values

            # 2. 寻找主共振峰
            #    这里使用最简单可靠的 np.argmax 来找到最大值点作为峰值
            peak_index, _ = find_main_resonance_peak(spectrum_data, wavelengths, min_height=-np.inf)

            if peak_index is not None:
                peak_wl = wavelengths[peak_index]
                peak_int = spectrum_data[peak_index]

                # 3. 计算半峰全宽 (FWHM)
                fwhm_results = calculate_fwhm(wavelengths, spectrum_data, [peak_index])
                fwhm = fwhm_results[0] if fwhm_results else np.nan

                peak_metrics_list.append({
                    'Spectrum Name': col_name,
                    'Peak Wavelength (nm)': peak_wl,
                    'Peak Intensity': peak_int,
                    'FWHM (nm)': fwhm
                })

        # 4. 将结果整理成 DataFrame
        summary_df = pd.DataFrame(peak_metrics_list)

        # 5. 计算统计数据 (均值, 标准差, 变异系数)
        stats_df = summary_df[['Peak Wavelength (nm)', 'Peak Intensity', 'FWHM (nm)']].agg(['mean', 'std']).T
        stats_df['CV (%)'] = (stats_df['std'] / stats_df['mean']) * 100

        # 6. 计算平均光谱
        average_spectrum_y = spectra_df.mean(axis=1).values
        average_spectrum_df = pd.DataFrame({
            'Wavelength (nm)': wavelengths,
            'Average Intensity': average_spectrum_y
        })

        # 7. 返回所有分析结果
        return {
            'summary_df': summary_df,
            'stats_df': stats_df,
            'average_spectrum_df': average_spectrum_df,
            'full_spectra_df': pd.concat([pd.DataFrame({'Wavelength (nm)': wavelengths}), spectra_df], axis=1)
        }
    except Exception as e:
        return {'error': str(e)}


def generate_reports(input_path, output_folder, analysis_results, generate_csv, generate_pdf, generate_word):
    """
    根据分析结果和用户选项，生成各种格式的报告文件。
    """
    try:
        # 创建一个唯一的子文件夹来存放本次任务的所有报告
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        input_filename = os.path.splitext(os.path.basename(input_path))[0]
        report_subfolder = os.path.join(output_folder, f"Report_{input_filename}_{timestamp}")
        os.makedirs(report_subfolder, exist_ok=True)

        # --- 生成 Excel 报告 (核心功能) ---
        if generate_csv:  # 虽然选项是CSV，但Excel更强大，能保存多个工作表
            excel_path = os.path.join(report_subfolder, "analysis_summary.xlsx")
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                analysis_results['summary_df'].to_excel(writer, sheet_name='Peak Metrics Summary', index=False)
                analysis_results['stats_df'].to_excel(writer, sheet_name='Statistics')
                analysis_results['average_spectrum_df'].to_excel(writer, sheet_name='Average Spectrum Data',
                                                                 index=False)
                analysis_results['full_spectra_df'].to_excel(writer, sheet_name='All Spectra Data', index=False)
            print(f"Excel 报告已保存至: {excel_path}")

        # --- 生成 PDF 报告 (占位功能) ---
        if generate_pdf:
            # 注意: 完整的PDF报告生成比较复杂，通常需要 reportlab 或 matplotlib 等库
            # 这里我们只生成一个简单的光谱图作为示例
            pdf_path = os.path.join(report_subfolder, "average_spectrum_plot.png")  # 暂存为图片
            avg_df = analysis_results['average_spectrum_df']

            plt.style.use('seaborn-v0_8-darkgrid')
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.plot(avg_df['Wavelength (nm)'], avg_df['Average Intensity'])
            ax.set_title('Average Spectrum')
            ax.set_xlabel('Wavelength (nm)')
            ax.set_ylabel('Intensity')
            ax.grid(True)
            fig.savefig(pdf_path)
            plt.close(fig)
            print(f"光谱图已保存至: {pdf_path} (提示: 完整PDF功能需额外开发)")

        # --- 生成 Word 报告 (占位功能) ---
        if generate_word:
            # 注意: Word报告生成需要 python-docx 库
            print("提示: Word报告生成功能正在开发中。")

    except Exception as e:
        print(f"生成报告时发生错误: {e}")