# 纳米光子学传感检测数据可视化分析系统

本项目面向 SPR / LSPR 等纳米光子学实验场景，提供从光谱采集、分析到数据库治理的一体化桌面解决方案。应用基于 **PyQt5** 与 **pyqtgraph** 构建，支持真实硬件（FX2000）和内置模拟光谱仪双栈模式，可用于教学演示、实验排查以及数据归档。

---

## 目录导航

- [功能亮点](#功能亮点)
- [快速开始](#快速开始)
- [常用脚本](#常用脚本)
- [数据库结构与治理](#数据库结构与治理)
- [测试与持续集成](#测试与持续集成)
- [目录结构示例](#目录结构示例)
- [参与贡献](#参与贡献)

---

## 功能亮点

- **全流程采集与分析**：实时光谱绘制、批量孔板流程、灵敏度/亲和力等专项分析模块。
- **硬件/模拟双模栈**：`FX2000Controller` 驱动真实设备；`mock_spectrometer_api` 提供可配置模拟数据，便于离线调试。
- **数据库浏览器增强**：实验列表支持条件筛选，下方新增“实验详情 / 光谱集合 / 批次概览”标签页，快速定位关键信息并导出。
- **数据导入与治理**：支持 Excel/CSV/TXT 批量导入，自动记录仪器状态与处理快照；附带快照统计、清理脚本便于日常治理。
- **迁移校验工具链**：提供结构化迁移脚本、验证脚本与 GitHub Actions 工作流，保障 Phase 1 架构升级质量。
- **国际化与个性化设置**：UI 支持中英文切换、深色主题，配置文件集中管理默认路径、语言与日志策略。


---

## 快速开始

### 1. 环境准备

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

> 若计划运行测试或 CI 脚本，同时安装开发依赖：`pip install -r requirements.txt pytest`（pytest 已包含在文件中）。

### 2. 启动应用

```bash
python main.py                 # 启动完整 GUI
python scripts/generate_demo_database.py  # 生成示例数据库（可选）
```

### 3. 配置说明

- 默认配置路径：`~/.nanosense/config.json`
- 默认数据库：`~/.nanosense/nanosense_data.db`
- 若使用真实硬件，需将厂商 DLL 放在 `drivers/` 目录或系统 PATH 下。

---

## 常用脚本

| 脚本 | 功能 | 示例 |
| ---- | ---- | ---- |
| `scripts/generate_demo_database.py` | 生成 Phase 1 结构的演示数据库，包含项目、实验、批量数据 | `python scripts/generate_demo_database.py --force` |
| `scripts/cleanup_snapshots.py` | 按时间/引用情况批量将快照标记为 `is_active = 0` | `python scripts/cleanup_snapshots.py --db data.db --age-days 90` |
| `scripts/report_snapshots.py` | 统计仪器/处理快照的指纹重复情况，输出 Markdown & CSV 报表 | `python scripts/report_snapshots.py --db data.db` |
| `scripts/validate_migration.py` | 检查 Phase 1 迁移结果是否达标（表/视图/链接/延迟等） | `python scripts/validate_migration.py --db data.db --max-latency 600 --strict` |
| `scripts/plot_validation_trends.py` | 将验证历史绘制为趋势图（依赖 `matplotlib`） | `python scripts/plot_validation_trends.py` |
| `scripts/run_validation_report.py` | 汇总验证脚本输出并生成压缩包，可在 CI/日常运行 | `python scripts/run_validation_report.py` |
| `scripts/run_snapshot_governance.py` | 一键生成快照报表、可选清理与 Markdown 摘要 | `python scripts/run_snapshot_governance.py --db data.db --cleanup-dry-run` |
| `scripts/legacy_freeze.py` | Legacy 表冻结审核、备份及回填脚本 | `python scripts/legacy_freeze.py --db data.db --freeze-after 2025-10-01 --backfill-missing` |

更多 CLI 用法可通过 `python <脚本> --help` 查看。

---

## 数据库结构与治理

- **核心结构**：`projects → experiments → spectrum_sets/spectrum_data → analysis_runs/analysis_metrics`
- **批量采集**：`batch_runs` 与 `batch_run_items` 记录批量板布局、采集状态，并与 `spectrum_sets` 建立关联。
- **快照管理**：`instrument_states`、`processing_snapshots` 记录仪器/处理配置；配套脚本可出具重复指纹提醒并进行软删除。
- **迁移策略**：
  - Phase 1 迁移脚本位于 `nanosense/core/migrations/`，通过 `scripts/migrate_db.py` 统一调度。
  - `docs/migrations/phase1/*.md` 与 `docs/operations/` 提供结构变更、回滚与治理手册。
- **数据库浏览器指南**：详见 `docs/ui/database_explorer_demo.md`，包含标签页说明、演示建议。

---

## 测试与持续集成

- 单元测试：
  ```bash
  pytest tests
  ```
- GitHub Actions：`.github/workflows/validation.yml` 自动运行迁移验证脚本与关键单元测试，并上传报告到构建产物。
- 报告输出：测试/验证脚本默认将结果写入 `docs/reports/`（已在 `.gitignore` 中忽略，可自行备份或清理）。

---

## 目录结构示例

```
├── nanosense/                # 核心源码（GUI、算法、数据库、迁移等）
├── scripts/                  # 运维/治理/演示脚本
├── tests/                    # 单元测试
├── docs/                     # 设计文档、操作手册、示例截图
│   ├── operations/           # Legacy 表治理与维护计划
│   ├── migrations/           # Phase 1 迁移方案
│   ├── ui/                   # 数据库浏览器等 UI 说明
│   └── validation/           # 验证流程路线图
├── requirements.txt          # 运行依赖
├── README.md                 # 当前文档
└── .github/workflows/        # CI 配置
```

---

## 参与贡献

1. Fork 仓库，创建特性分支。
2. 完成开发并补充必要的测试/文档。
3. 运行 `pytest` 与关键脚本确保通过。
4. 提交 Pull Request，并在描述中说明变更核心点及验证方式。

欢迎提交 issues 和 PR，共同完善纳米光子学数据平台。谢谢支持！
