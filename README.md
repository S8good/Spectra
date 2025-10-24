# 纳米光子学传感检测数据可视化分析系统

本项目是纳米传感实验室研发的综合光谱处理平台，专注于表面等离子体共振（SPR/LSPR）、纳米传感和生化检测等应用场景。系统采用 `PyQt5` 构建桌面界面，结合 `pyqtgraph` 的 GPU 加速绘图，实现从光谱仪采集、信号处理、科学分析到实验归档的全流程闭环。软件原生支持 FX2000 等真实硬件，同时内置可配置的模拟 API，便于在无硬件条件下教学、演示与调试。

---

## 系统概览
- **完整工作流覆盖**：从欢迎页模式选择、实时采集、动力学监控，到批量板式实验、专项分析、数据库归档的全链路支持。
- **双栈硬件模式**：`nanosense.core.controller.FX2000Controller` 驱动真实光谱仪，并自动管理 DLL 加载与单例生命周期；`mock_spectrometer_api.Wrapper` 读取配置生成动态/静态/噪声光谱，实现无缝切换。
- **实时可视化内核**：`nanosense.gui.measurement_widget.MeasurementWidget` 将信号、背景、参考、结果四条光谱以毫秒级刷新绘制，支持波段裁剪、平滑、基线校正、峰值计算与数据导出。
- **科学分析工具集**：算法模块涵盖灵敏度曲线拟合、亲和力常数 (KD) 求解、`k_obs` 线性化、噪声评估、探测性能 (LOB/LOD/LOQ) 等分析任务，配套对话框提供交互式参数设置与结果展示。
- **数据治理能力**：`nanosense.core.database_manager.DatabaseManager` 基于 SQLite 构建“项目 → 实验 → 光谱/分析结果”的层级结构，结合 `DatabaseExplorerDialog` 实现历史数据检索、筛选、导出与复盘。
- **国际化与定制化**：UI 全面支持中英文切换（`nanosense/translations`），深色主题适配实验室环境；配置文件 `~/.nanosense/config.json` 集中管理默认路径、模拟 API 参数、语言、日志策略等。

---

## 功能矩阵
| 功能模块 | 细节描述 | 关键界面/类 |
| --- | --- | --- |
| 设备连接与模式切换 | 欢迎页选择测量模式与硬件来源；真实模式加载 `IdeaOptics.dll` 连接 FX2000，失败时自动回退；模拟模式可根据配置动态漂移峰位或注入噪声 | `WelcomeWidget`, `FX2000Controller`, `mock_spectrometer_api` |
| 实时采集与控制 | CollapsibleBox 面板集中控制采集状态、背景/参考捕获、积分时间、平均次数、波段显示；线程安全队列保障数据流畅；支持返回欢迎页重新选择模式 | `MeasurementWidget`, `main.py`, `SpectrumProcessor` |
| 光谱预处理与分析 | 支持 Savitzky–Golay、滑动平均、中值滤波；自动扣除背景/参考，避免除零；提供主峰搜索算法（最高点、拟合、质心等）、FWHM 计算、区域裁剪、独立窗口对比 | `nanosense.algorithms.peak_analysis`, `MeasurementWidget` |
| 动力学监测 | 以固定采样间隔追踪峰位/强度随时间变化，`KineticsWindow` 独立展示并支持暂停、导出；内部记录原始时间戳供后续分析 | `kinetics_window.py`, `MeasurementWidget` |
| 噪声分析 | `RealTimeNoiseWorker` 后台批量采集光谱，计算噪声谱、平均谱、标准差；`NoiseResultDialog` 可视化结果并提供保存路径；支持导入历史数据重现统计 | `noise_tools.py`, `noise_analysis_dialog.py` |
| 批量采集（孔板/点位） | `BatchSetupDialog` 配置孔板维度、测量点、背景/参考策略；`BatchRunDialog` 实时显示指令、曲线、进度条、汇总图，并可弹出多曲线窗口；完成后自动生成报告与数据表 | `nanosense.core.batch_acquisition`, `batch_report_dialog.py` |
| 专项分析工具 | 灵敏度（校准曲线拟合、线性范围判断）、亲和力 KD（结合/解离拟合）、`k_obs` 线性化、探测性能 LOB/LOD/LOQ、噪声导入分析、批量数据分析等模块按需弹窗，结果可写入数据库 | `sensitivity_dialog.py`, `affinity_analysis_dialog.py`, `kobs_linearization_dialog.py`, `performance_dialog.py`, `data_analysis_dialog.py` |
| 色度学分析 | 导入 Excel/CSV/TXT 光谱，计算三刺激值、CIE xy、CIE Lab、相关色温、亮度等；支持选择光源（D65/A/C/D50/D55/D75）与观察者角度（2°/10°），结果可保存数据库 | `colorimetry_widget.py`, `nanosense.algorithms.colorimetry`, `utils.file_io` |
| 数据导入导出 | 提供单光谱、三文件（Signal/Dark/Ref）、多列批量光谱导入；结果谱与全部谱导出为 Excel/CSV/TXT；批量模式生成整板数据表与图像报告 | `three_file_import_dialog.py`, `utils.file_io`, `utils.report_generator` |
| 数据库管理 | 自动创建默认项目、交互式新建实验，保存配置快照、光谱、分析结果；`DatabaseExplorerDialog` 提供项目/时间/类型筛选、排序、导出功能 | `database_manager.py`, `database_explorer.py` |
| 设置与日志 | `SettingsDialog` 调整默认路径、数据库位置、语言、硬件模式、日志开关；`MockAPIConfigDialog` 实时修改模拟峰位、幅值、噪声、动力学阶段时长 | `settings_dialog.py`, `mock_api_config_dialog.py` |

---

## 工作流详解
### 1. 启动与模式选择
1. 在虚拟环境运行 `python main.py`，若存在 `nanosense/gui/assets/splash.png` 会先显示进度条启动画面。
2. 欢迎页展示八大测量模式按钮（Absorbance/Transmission/Reflectance/Raman/Fluorescence/Abs Irradiance/Rel Irradiance/Color）以及硬件模式下拉框。
3. 选择真实硬件后，`FX2000Controller.connect` 会加载 `IdeaOptics.dll` 并尝试发现光谱仪；若未检测到设备或驱动加载失败，系统会提示错误并自动切换为模拟模式。
4. 进入主窗口时，系统根据选择的模式设置图表标签、处理策略，并在底部状态栏告知当前硬件模式。

### 2. 实时测量与处理
1. **采集控制**：左侧 CollapsibleBox 面板提供 “Start Acquisition / Stop”、“Capture Background”、“Capture Reference”、“Reset Display Range”等按钮；积分时间 (10–10000 ms) 与平均次数可实时调整。
2. **光谱通道**：右侧同时绘制 Signal、Background、Reference、Result 四个图层。结果谱会根据模式执行如下处理：
   - 反射/透射：在扣除暗噪、参考后计算比例；
   - 吸光度：对透射率取 `-log10`；
   - 拉曼/荧光：扣除背景后直接输出；
   - 辐照度/原始：展示平滑后的原始信号。
3. **波段裁剪**：可通过显示范围控制输入起止波长，所有图表同步更新；独立弹窗可以放大任意光谱并锁定范围。
4. **基线与平滑**：平滑方法与窗口宽度会实时作用于最新信号；基线校正按钮针对当前结果谱执行低频拟合并扣除残余漂移。

### 3. 峰值分析与动力学
1. **主峰搜索**：可选择“最高点”“Savitzky–Golay 拟合”“质心”等方法，设置最小峰高、搜索区间，实时输出峰位与峰强，并在图表上高亮。
2. **FWHM/峰组分析**：通过 `PeakMetricsDialog` 查看主峰半高宽、峰高、噪声水平等指标，并可导出分析结果。
3. **动力学监控**：开启“Start Monitoring”后，系统会以设定的采样间隔记录主峰位置、峰值强度，`KineticsWindow` 以独立窗口展示时间序列，可暂停、恢复、导出 CSV。

### 4. 噪声评估
1. 进入 “Real-time Data Analysis...” 后，指定采集次数与时间间隔，系统会在后台采集多条光谱并计算平均谱、噪声谱、RMS 噪声。
2. `NoiseResultDialog` 显示结果图表、统计表格，提示输出目录并提供再次分析的快捷入口。
3. `Import Data Analysis...` 支持从已有文件导入多条光谱进行同类分析，便于复现历史噪声评估。

### 5. 批量板式实验
1. **配置阶段**：`BatchSetupDialog` 设置孔板行列、测量点数量、流程提示语、是否自动捕获背景/参考、是否在每个点保存结果等。
2. **运行阶段**：`BatchRunDialog` 给出逐步指示（放置背景/参考、移动到指定孔位/点位），实时绘制信号、背景、参考、结果、累计汇总曲线；支持单点重测、暂停、提前终止。
3. **数据输出**：完成后自动保存：
   - 每个点的信号/背景/参考/结果谱线；
   - 汇总吸光度曲线与列表；
   - Excel/CSV 报表（通过 `save_batch_spectrum_data`/`report_generator`）；
   - 可选将结果写入数据库以备后续分析。

### 6. 专项分析工具
- **灵敏度计算**：导入或录入浓度-响应数据，执行线性拟合，输出灵敏度、截距、R²、线性范围、残差分析，并可保存曲线截图与数据。
- **亲和力 (KD)**：导入关联/解离光谱，自动提取动力学曲线，使用指数拟合获得 KD、ka、kd，支持参数约束与拟合质量报告。
- **`k_obs` 线性化**：针对多个浓度的动力学数据，计算表观速率常数并线性拟合，提供斜率/截距/相关系数及图像输出。
- **探测性能评估**：通过噪声统计与校准曲线计算 LOB、LOD、LOQ，展示计算公式、中间结果与可视化图表。
- **批量数据分析**：导入多列光谱文件，执行批量峰值、吸光度计算，生成对比图与统计表。

### 7. 色度学流程
1. 导入外部光谱文件后，`ColorimetryWidget` 将光谱绘制于左侧，右侧表格列出 X、Y、Z、x、y、Y、Lab、CRI、CCT 等参数。
2. “Settings” 对话框选择光源与观察者角度后，软件会重新计算色度参数并更新图表。
3. “Save Results to Database” 将色度结果作为分析记录写入当前实验，便于追踪材料颜色性能。

### 8. 数据库生命周期
1. 第一次运行若未设置数据库路径，`AppWindow` 会提示并允许以只读模式运行；在 `Settings → Customize Parameters...` 中指定路径后，系统自动创建所需表结构。
2. 每次新建实验时，弹窗询问实验名称并记录配置快照（积分时间、模式等）；光谱数据与分析结果均按时间戳归档。
3. `DatabaseExplorerDialog` 提供项目、实验类型、时间范围、操作员等条件筛选，可查看光谱列表、导出 Excel/CSV、直接打开对应结果文件。

### 9. 配置与国际化
1. 所有配置存放于 `~/.nanosense/config.json`；`config_manager` 在读取时自动填充缺失字段，确保兼容旧版本。
2. `MockAPIConfigDialog` 可在 GUI 中调整模拟模式：静态峰位、幅值、宽度，动态模式的基线/结合/解离阶段时长和峰位漂移，总噪声水平等。
3. 语言切换通过 `Settings → Language` 实现，`AppWindow` 会加载 `chinese.qm` 或恢复默认英语，并触发所有界面类的 `changeEvent` 以刷新文字。

---

## 环境准备
1. 使用 Python 3.9 及以上版本，建议创建专用虚拟环境。
2. 安装基础依赖：
   ```powershell
   pip install PyQt5 pyqtgraph numpy scipy pandas openpyxl pythonnet
   ```
3. 如需生成报告或使用额外算法，请按需安装 `reportlab`、`matplotlib`、`scikit-learn` 等扩展库。
4. 真实硬件模式需确保系统能访问 `drivers/IdeaOptics.dll`、`drivers/CyUSB.dll`，并与当前 Python 位数匹配；若加载失败，控制台会提示错误，按提示调整环境变量或重新安装驱动。

---

## 运行与调试
```powershell
python main.py
```
- 启动后根据需求选择真实硬件或模拟 API；调试阶段可在 `main.py` 注释掉启动画面或调整 `time.sleep` 加速加载。
- 控制台输出包含硬件连接状态、模式切换、数据库提示、模拟配置等日志信息，有助于快速定位问题。
- 若需要验证采集线程行为，可运行 `python main_acquisition_loop.py`，在命令行环境下查看实时峰值。

---

## 项目结构
```text
.
├── main.py                         # GUI 启动入口，控制欢迎页与主窗口切换
├── main_acquisition_loop.py        # 采集线程命令行示例
├── mock_spectrometer_api.py        # 模拟光谱仪实现与配置读取
├── drivers/                        # 真实硬件依赖的 DLL/类型库
├── nanosense/
│   ├── gui/                        # 主窗口、控件、对话框、资源
│   ├── core/                       # 硬件控制器、批量采集、光谱处理、数据库
│   ├── algorithms/                 # 峰值、动力学、色度学、性能等算法
│   ├── utils/                      # 文件 IO、配置、日志、报表工具
│   └── translations/               # Qt 多语言资源（.ts/.qm）
└── README.md
```

---

## 常见问题与排查
- **连接真实光谱仪失败**：确认 USB 物理连接、安装 IdeaOptics 官方驱动、Python 与 DLL 位数一致；必要时将 `drivers/` 添加至系统 PATH，并以管理员身份运行。
- **模拟模式无输出**：检查 `~/.nanosense/config.json` 是否包含 `mock_api_config`，若配置缺失可删除文件让程序重新生成默认配置；通过 `MockAPIConfigDialog` 验证参数是否合理。
- **界面无法切换到中文**：确认 `nanosense/translations/chinese.qm` 存在；切换语言后若部分界面未更新，可重启程序或检查对应类的 `changeEvent` 是否被修改。
- **数据库相关按钮灰色**：说明尚未配置数据库路径，打开 `Settings → Customize Parameters...` 指定 `.db` 文件后生效；若指定路径不可写，请检查权限。
- **导出 Excel 报错**：确保安装 `openpyxl`；若导出 CSV/TXT 失败，请确认目标目录存在且可写。
- **实时绘图卡顿**：可降低采集频率、减少平滑窗口、关闭多余弹窗，或在模拟模式下降低噪声水平以减轻 CPU 负载。

---

## 开发与扩展建议
1. 为核心算法与 IO 功能添加单元测试，引入持续集成保障版本演进质量。
2. 抽象硬件接口层，以便接入更多型号光谱仪或网络采集端口。
3. 封装插件机制，让研究人员快速集成新的算法模块或报告模板。
4. 与实验自动化系统对接，开放外部 API，构建自动化批量采集与分析流水线。

欢迎阅读 `nanosense/gui` 与 `nanosense/core` 目录中的源码，了解界面逻辑与数据处理细节；如有新的实验需求，可在现有框架基础上继续拓展！
