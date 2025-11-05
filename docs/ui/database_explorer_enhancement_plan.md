# Database Explorer Enhancement Plan

## Objectives
- Surface Phase 1 structured data (batch runs, wells, spectrum sets, metadata) through the GUI explorer.
- Provide quick diagnostics for batch acquisition state, spectrum quality, and associated snapshots.
- Maintain responsiveness and avoid blocking UI threads during large data loads.

## Feature Breakdown
1. **Hierarchical Navigation**
   - Left pane: projects → experiments → batch runs → batch run items → spectrum sets.
   - Persist user filters (project, status, date range) between sessions.
2. **Spectrum Detail Panel**
   - Display capture metadata (captured_at, instrument fingerprint, processing parameters).
   - Inline plot preview using existing Matplotlib utilities; lazy load waveform data.
   - Actions: export structured JSON, copy snapshot IDs, open in analysis dialog.
3. **Batch Overview Tab**
   - Grid showing batch_run_items with status badges, last capture timestamp, analysis outcomes.
   - Aggregate counters (completed, pending, failed) with quick filters.
4. **Search & Filter**
   - Text search across experiment names, batch labels, capture labels.
   - Advanced filters: status, time range, snapshot fingerprint, instrument serial.
5. **Performance Considerations**
   - Use background threads (QtConcurrent) for heavy queries.
   - Implement pagination/virtualized list for large spectrum sets.
   - Cache recent query results with invalidation on data changes.

## Implementation Steps
1. **Data Access Layer**
   - Extend `DatabaseManager` / dedicated repository class with batched query helpers (`fetch_batch_summary`, `fetch_spectrum_set_detail`, etc.).
   - Ensure queries leverage new indices (e.g., `idx_spectrum_sets_experiment`, `idx_batch_run_items_batch`).
2. **Model/View Updates**
   - Introduce view models (e.g., `BatchRunTreeModel`, `SpectrumSetTableModel`) to decouple UI from raw SQL.
   - Adopt Qt’s `QSortFilterProxyModel` for filters.
3. **UI Layout**
   - Update `DatabaseExplorerDialog` to host navigation tree, detail tabs, and filter bar.
   - Add reusable components for status badges and metadata viewers.
4. **Interactivity**
   - Wire selection signals to load detail panel asynchronously.
   - Provide context menu actions (export, open analysis) with command routing.
5. **Testing & QA**
   - Add smoke tests using pytest-qt (if available) or manual test script enumerating navigation paths.
   - Prepare demo dataset with diverse batch statuses for validation.

## Documentation & Rollout
- Update README screenshots and section describing the explorer workflow.
- Publish internal wiki page summarizing shortcuts, filters, and troubleshooting tips.
- Schedule knowledge-share session with operations team after beta release.

## Dependencies & Risks
- Requires consistent metadata in structured tables (coordinate with snapshot governance to ensure completeness).
- Potential performance regressions if queries are not optimized; monitor with profiling runs on production-size copies.
