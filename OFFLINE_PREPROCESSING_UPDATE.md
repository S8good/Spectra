﻿# 离线光谱分析 - 预处理功能更新

## 概述
本次更新为离线光谱分析窗口增加了预处理控制，使主共振峰寻峰与报表导出能够统一使用基线校正与平滑处理。同时新增“启用预处理”统一开关与“单次/两阶段平滑”切换。

## 新增界面元素
- 预处理面板（左侧）：
  - 启用预处理（统一开关）
  - ALS 基线（开关）
  - Savitzky-Golay 平滑（开关）
  - Noise Range（噪声范围设置）
  - 调整预处理参数...（打开交互式设置）

- 预处理设置对话框：
  - 预览光谱选择（可选择不同光谱进行预览）
  - 两阶段平滑开关（取消勾选即为单次平滑）
  - Savitzky-Golay 参数自动校正（保证 polyorder < window 且 window 为奇数）

## 行为变化
- 静态分析（寻峰）在启用预处理时使用处理后数据。
- 汇总报告生成在启用预处理时使用处理后数据。
- 分析结果导出仍保留原始数据列；启用预处理时额外导出：
  - ALS Baseline
  - Processed Value / Processed Absorbance
- 离线汇总报告的寻峰范围使用静态分析的寻峰范围设置。
- 新增“Enable preprocessing”统一开关，关闭时强制使用原始数据；开启时按 ALS/SG 勾选应用预处理。
- 导出汇总报告仅包含 Absorbance 光谱（忽略 Background/Reference）。
- 噪声范围从静态分析移到预处理面板。
- 曲线自动聚焦：若导入全谱且未手动缩放，X 轴聚焦到寻峰范围；Y 轴按“寻峰范围 + 噪声范围”计算。

## 单次 vs 两阶段平滑
- 两阶段（默认）：先 Coarse 再 Fine。
- 单次：取消勾选“Two-stage smoothing”，仅应用 Coarse 阶段。

## 参数计算逻辑（离线分析表格）
- 已实现：
  - Peak Wavelength：在寻峰范围内按当前寻峰算法定位主峰。
  - Peak Intensity：主峰点强度（与预处理开关一致）。
  - FWHM：基于主峰位置计算半高全宽。
  - RMS Noise：噪声范围内去均值；若存在明显斜率则线性去趋势后计算 RMS。
    - 判定：`abs(slope) * (x_max - x_min) > 0.01 * max(1e-12, y_range)` 视为存在明显斜率。
    - 公式：`RMS = sqrt(mean(detrended^2))`
  - C Noise：噪声范围内峰-峰噪声（去趋势后 max(y)-min(y)）。
    - 公式：`C Noise = max(detrended) - min(detrended)`
  - SNR：Peak Intensity / RMS Noise。
    - 公式：`SNR = PeakIntensity / RMS`
  - Peak Area：寻峰范围内按当前预处理状态积分。
    - 公式：`PeakArea = ∫ y dx`（实现为 `trapz(y, x)`）
- 未实现（占位）：
  - Skewness
  - Baseline Slope
  - Baseline Ripple
  - Repeatability (Mean/Std/CV)
  - LOB/LOD/LOQ

## 修改文件列表
- nanosense/gui/analysis_window.py
  - 新增预处理面板、显示切换；寻峰/报表/导出应用预处理。
  - 新增噪声范围与表格计算逻辑；表格列支持拖拽与横向滚动。
  - 表格与预处理/寻峰范围联动刷新。
  - 表格主题跟随深浅色主题。
  - 移除“显示处理后光谱”，改为“Enable preprocessing”统一开关。
  - 汇总报告仅导出 Absorbance。
- nanosense/gui/preprocessing_dialog.py
  - 增加预览选择与单次/两阶段切换。
  - 增加 Savitzky-Golay 参数自动校正。
  - 白色主题下更新曲线/坐标轴颜色提升可读性。
- nanosense/utils/plot_generator.py
  - 批处理绘图支持单次/两阶段平滑。
- nanosense/utils/data_processor.py
  - 汇总峰位计算支持单次/两阶段平滑。
- nanosense/gui/delta_lambda_visualizer.py
  - Δλ 计算支持单次/两阶段平滑。
- nanosense/gui/data_analysis_dialog.py
  - 预处理参数新增 sg_two_stage 默认值。
- nanosense/gui/main_window.py
  - 导入光谱后自动分类（Background/Reference/Absorbance），并弹窗复核可修改。
- nanosense/gui/spectrum_classification_dialog.py
  - 新增“光谱分类确认”对话框，支持本次会话不再提示。
- nanosense/gui/analysis_window.py
  - 右侧新增分类切换按钮，筛选显示 Background/Reference/Absorbance 光谱。

## 备注
- 若出现 polyorder >= window length，会自动修正参数避免报错。
