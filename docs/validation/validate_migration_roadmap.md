# Validate Migration Roadmap

## Goals
- Provide confidence in Phase 1 migration integrity via automated checks.
- Catch regressions early through unit tests and CI gates.
- Keep reports consumable by operations and developers.

## Short-Term Actions
1. **Refactor Script for Testability**
   - Extract structural checks, latency analysis, batch status logic into helper functions returning data classes.
   - Ensure functions accept dependency-injected cursors/queries for mocking.
2. **Unit Test Coverage**
   - Create `tests/test_validate_migration.py` covering:
     - Missing table/view/column detection.
     - Count mismatch warnings.
     - Latency offender identification (edge cases with null timestamps).
     - Batch status detection scenarios.
   - Use in-memory SQLite fixtures populated per test case.
3. **CI Integration**
   - Add workflow job executing:
     ```bash
     python -m pytest tests/test_validate_migration.py
     python scripts/validate_migration.py --db data/nanosense_data.db --max-latency 600 --batch-status --sample-rate 0
     ```
   - Store CLI output artifact (e.g., `validation_logs.txt`) for audit trail.
- 2025-11-03：已落地 `--strict` / `--report-file` / `--history-file` 参数，并补充 `tests/test_validate_migration.py` 覆盖严格模式、报告输出与历史记录；CI 工作流已同步执行严格校验并上传报表。

## Mid-Term Enhancements
- 持续积累 `docs/reports/validation_history.csv` 指标，并使用 `scripts/plot_validation_trends.py` 生成趋势图，为运维提供可视化参考。
- 在 CI 中增加历史指标图表或仪表盘展示，以便运维快速评估迁移质量。

## Ownership & Timeline
- **Owner:** Migration tooling squad (contact: Codex).
- **Sprint target:** Finish refactor + unit tests within next iteration; enable CI gate in subsequent release train。
- **Review cadence:** Weekly stand-up review of validation outputs; escalate blocking warnings immediately。
