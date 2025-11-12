# nanosense/gui/delta_lambda_visualizer.py

import os
import re
from datetime import datetime

import numpy as np
try:
    import pyqtgraph.opengl as gl
    from pyqtgraph.opengl import GLMeshItem, GLAxisItem
    GL_IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # Missing PyOpenGL backend
    gl = None
    GLMeshItem = GLAxisItem = None
    GL_IMPORT_ERROR = exc
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor, QImage
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from nanosense.algorithms.peak_analysis import find_main_resonance_peak
from nanosense.algorithms.preprocessing import baseline_als, smooth_savitzky_golay
from nanosense.utils.file_io import load_wide_format_spectrum

try:  # Optional dependency for GIF export
    import imageio.v3 as iio
except ImportError:
    iio = None


class DeltaLambdaVisualizationDialog(QDialog):
    """
    Visualize Δλ (peak wavelength shift) as an interactive 3D surface.
    Input: a folder containing two wide-format batch spectrum files (baseline & post-reaction).
    """

    SUPPORTED_EXT = (".csv", ".txt", ".xlsx", ".xls")

    def __init__(self, preprocessing_params=None, app_settings=None, initial_folder=None, parent=None):
        super().__init__(parent)
        if gl is None:
            raise ImportError(
                "pyqtgraph.opengl (PyOpenGL backend) is unavailable. Please install PyOpenGL and try again."
            ) from GL_IMPORT_ERROR
        self.setWindowTitle(self.tr("Δλ Visualization"))
        self.resize(1000, 720)

        self.preprocessing_params = preprocessing_params or {}
        self.app_settings = app_settings or {}

        self.folder_path = None
        self.available_files = []
        self.delta_grid = None
        self.delta_map = {}
        self.row_labels = []
        self.col_labels = []
        self.layout_is_plate = False
        self.bar_items = []
        self.grid_item = None
        self.axis_item = None
        self.plate_id = ""
        self._negative_values_present = False

        self._build_ui()
        self._connect_signals()
        self._update_controls_state()
        if initial_folder:
            self._load_folder(initial_folder, show_warning=False)

    # ------------------------------------------------------------------ UI ---
    def _build_ui(self):
        layout = QVBoxLayout(self)

        folder_group = QGroupBox(self.tr("Input Folder (two batch files required)"))
        folder_layout = QVBoxLayout(folder_group)

        folder_row = QHBoxLayout()
        self.folder_label = QLabel(self.tr("No folder selected."))
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        folder_row.addWidget(self.folder_label, 1)
        self.select_folder_button = QPushButton(self.tr("Choose Folder..."))
        folder_row.addWidget(self.select_folder_button)
        folder_layout.addLayout(folder_row)

        combo_form = QFormLayout()
        self.baseline_combo = QComboBox()
        self.post_combo = QComboBox()
        combo_form.addRow(self.tr("Baseline file:"), self.baseline_combo)
        combo_form.addRow(self.tr("Post-reaction file:"), self.post_combo)
        folder_layout.addLayout(combo_form)

        self.compute_button = QPushButton(self.tr("Load && Compute Δλ"))
        folder_layout.addWidget(self.compute_button)
        layout.addWidget(folder_group)

        meta_group = QGroupBox(self.tr("Metadata & Export Settings"))
        meta_layout = QFormLayout(meta_group)
        self.plate_id_edit = QLineEdit()
        meta_layout.addRow(self.tr("Plate ID (for filenames):"), self.plate_id_edit)

        png_row = QHBoxLayout()
        self.dpi_spinbox = QSpinBox()
        self.dpi_spinbox.setRange(72, 600)
        self.dpi_spinbox.setValue(220)
        self.dpi_spinbox.setSuffix(" dpi")
        png_row.addWidget(self.dpi_spinbox)
        self.export_view_button = QPushButton(self.tr("Export View PNG"))
        png_row.addWidget(self.export_view_button)
        meta_layout.addRow(self.tr("Interactive PNG:"), png_row)

        mpl_row = QHBoxLayout()
        self.export_matplotlib_button = QPushButton(self.tr("Export Matplotlib PNG"))
        mpl_row.addWidget(self.export_matplotlib_button)
        meta_layout.addRow(self.tr("High-quality PNG:"), mpl_row)

        gif_row = QHBoxLayout()
        self.gif_step_spinbox = QSpinBox()
        self.gif_step_spinbox.setRange(5, 90)
        self.gif_step_spinbox.setValue(15)
        self.gif_step_spinbox.setSuffix("°/frame")
        self.gif_delay_spinbox = QSpinBox()
        self.gif_delay_spinbox.setRange(30, 500)
        self.gif_delay_spinbox.setValue(120)
        self.gif_delay_spinbox.setSuffix(" ms")
        gif_row.addWidget(QLabel(self.tr("Step:")))
        gif_row.addWidget(self.gif_step_spinbox)
        gif_row.addWidget(QLabel(self.tr("Frame delay:")))
        gif_row.addWidget(self.gif_delay_spinbox)
        self.export_gif_button = QPushButton(self.tr("Export Orbit GIF"))
        gif_row.addWidget(self.export_gif_button)
        meta_layout.addRow(self.tr("GIF Export (optional):"), gif_row)

        layout.addWidget(meta_group)

        self.gl_view = gl.GLViewWidget()
        self.gl_view.setBackgroundColor(20, 20, 20)
        self.gl_view.opts["distance"] = 60
        layout.addWidget(self.gl_view, 1)

        status_row = QHBoxLayout()
        self.summary_label = QLabel(self.tr("Δλ surface not generated yet."))
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_row.addWidget(self.summary_label, 1)
        layout.addLayout(status_row)

    def _connect_signals(self):
        self.select_folder_button.clicked.connect(self._select_folder)
        self.compute_button.clicked.connect(self._load_and_visualize)
        self.export_view_button.clicked.connect(self._export_png)
        self.export_matplotlib_button.clicked.connect(self._export_matplotlib_png)
        self.export_gif_button.clicked.connect(self._export_gif)

    def _update_controls_state(self):
        has_folder = bool(self.folder_path and len(self.available_files) >= 2)
        has_data = self.delta_grid is not None
        self.compute_button.setEnabled(has_folder)
        self.export_view_button.setEnabled(has_data)
        self.export_matplotlib_button.setEnabled(has_data)
        self.export_gif_button.setEnabled(has_data)

    # ------------------------------------------------------------ Workflow ---
    def _select_folder(self):
        start_path = self.folder_path or self.app_settings.get("default_load_path", os.path.expanduser("~"))
        folder = QFileDialog.getExistingDirectory(self, self.tr("Select folder containing two batch files"), start_path)
        if not folder:
            return
        self._load_folder(folder, show_warning=True)

    def _load_folder(self, folder, show_warning=True):
        files = [
            f
            for f in sorted(os.listdir(folder))
            if f.lower().endswith(self.SUPPORTED_EXT) and os.path.isfile(os.path.join(folder, f))
        ]
        if len(files) < 2:
            if show_warning:
                QMessageBox.warning(
                    self,
                    self.tr("Folder Error"),
                    self.tr("Folder must contain at least two supported files (*.csv / *.txt / *.xlsx)."),
                )
            return False

        self.folder_path = folder
        self.available_files = files
        self.folder_label.setText(folder)
        self.plate_id = os.path.basename(folder)
        self.plate_id_edit.setText(self.plate_id)

        self.baseline_combo.clear()
        self.post_combo.clear()
        for fname in files:
            self.baseline_combo.addItem(fname)
            self.post_combo.addItem(fname)
        if len(files) >= 2:
            self.baseline_combo.setCurrentIndex(0)
            self.post_combo.setCurrentIndex(1)

        self.delta_grid = None
        self.summary_label.setText(self.tr("Folder selected. Click “Load & Compute Δλ” to generate the surface."))
        self._update_controls_state()
        return True

    def _load_and_visualize(self):
        if not self.folder_path:
            QMessageBox.information(self, self.tr("Info"), self.tr("Please select a folder first."))
            return

        baseline_file = self.baseline_combo.currentText()
        post_file = self.post_combo.currentText()
        if baseline_file == post_file:
            QMessageBox.warning(self, self.tr("Selection Error"), self.tr("Please choose two different files."))
            return

        baseline_path = os.path.join(self.folder_path, baseline_file)
        post_path = os.path.join(self.folder_path, post_file)
        if not (os.path.exists(baseline_path) and os.path.exists(post_path)):
            QMessageBox.warning(self, self.tr("File Missing"), self.tr("Selected files no longer exist."))
            return

        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            baseline_peaks = self._compute_peak_positions(baseline_path)
            post_peaks = self._compute_peak_positions(post_path)
            if not baseline_peaks or not post_peaks:
                QMessageBox.warning(
                    self,
                    self.tr("Analysis Error"),
                    self.tr("Unable to extract peak wavelengths from one or both files."),
                )
                return

            baseline_keys = set(baseline_peaks.keys())
            post_keys = set(post_peaks.keys())
            shared_keys = sorted(baseline_keys & post_keys)
            if not shared_keys:
                QMessageBox.warning(
                    self,
                    self.tr("Column Mismatch"),
                    self.tr("No matching measurement columns between the two files."),
                )
                return

            missing_pre = post_keys - baseline_keys
            missing_post = baseline_keys - post_keys
            warnings = []
            if missing_pre:
                warnings.append(self.tr("Columns only in post file: {0}").format(", ".join(sorted(missing_pre))[:120]))
            if missing_post:
                warnings.append(self.tr("Columns only in baseline file: {0}").format(", ".join(sorted(missing_post))[:120]))

            delta_map = {}
            self._negative_values_present = False
            for key in shared_keys:
                pre_val = baseline_peaks.get(key, np.nan)
                post_val = post_peaks.get(key, np.nan)
                if np.isnan(pre_val) or np.isnan(post_val):
                    delta_map[key] = np.nan
                    continue
                delta = float(post_val - pre_val)
                if delta < 0:
                    self._negative_values_present = True
                delta_map[key] = delta

            self.delta_map = delta_map
            self.row_labels, self.col_labels, grid, self.layout_is_plate = self._build_delta_grid(delta_map)
            if grid is None:
                QMessageBox.warning(
                    self,
                    self.tr("Visualization Error"),
                    self.tr("No valid Δλ values were computed; cannot render the surface."),
                )
                return

            self.delta_grid = grid
            self._render_surface()
            stats_text = self._format_stats_text(delta_map, warnings)
            self.summary_label.setText(stats_text)

        except Exception as exc:  # pylint: disable=broad-except
            QMessageBox.critical(
                self,
                self.tr("Unexpected Error"),
                self.tr("Δλ calculation failed:\n{0}").format(str(exc)),
            )
        finally:
            QApplication.restoreOverrideCursor()
            self._update_controls_state()

    # ----------------------------------------------------------- Processing ---
    def _compute_peak_positions(self, file_path):
        wavelengths, spectra_df, error = load_wide_format_spectrum(file_path)
        if error:
            raise ValueError(error)

        wavelengths = np.asarray(wavelengths, dtype=np.float64)
        spectra_df = self._normalize_measurement_columns(spectra_df)
        peaks = {}

        wl_start = self.app_settings.get("analysis_wl_start", 450.0)
        wl_end = self.app_settings.get("analysis_wl_end", 750.0)

        als_lambda = self.preprocessing_params.get("als_lambda", 1e9)
        als_p = self.preprocessing_params.get("als_p", 0.01)
        sg_window_coarse = self.preprocessing_params.get("sg_window_coarse", 15)
        sg_poly_coarse = self.preprocessing_params.get("sg_polyorder_coarse", 3)
        sg_window_fine = self.preprocessing_params.get("sg_window_fine", 9)
        sg_poly_fine = self.preprocessing_params.get("sg_polyorder_fine", 3)

        for col in spectra_df.columns:
            intensities = spectra_df[col].values
            try:
                intensities = np.asarray(intensities, dtype=np.float64)
            except ValueError:
                peaks[str(col)] = np.nan
                continue

            if intensities.shape[0] != wavelengths.shape[0]:
                peaks[str(col)] = np.nan
                continue

            baseline = baseline_als(intensities, lam=als_lambda, p=als_p)
            corrected = intensities - baseline
            mask = (wavelengths >= wl_start) & (wavelengths <= wl_end)
            if not np.any(mask):
                peaks[str(col)] = np.nan
                continue

            sub_wl = wavelengths[mask]
            sub_int = corrected[mask]
            if sub_wl.size < 20:
                peaks[str(col)] = np.nan
                continue

            coarse = smooth_savitzky_golay(sub_int, sg_window_coarse, sg_poly_coarse)
            fine = smooth_savitzky_golay(coarse, sg_window_fine, sg_poly_fine)
            peak_idx, _ = find_main_resonance_peak(fine, min_height=0)
            if peak_idx is None or peak_idx >= sub_wl.size:
                peaks[str(col)] = np.nan
            else:
                peaks[str(col)] = float(sub_wl[peak_idx])

        return peaks

    def _normalize_measurement_columns(self, df):
        """
        Drop instrument metadata columns (e.g., LightBK) and rename numeric-only
        columns to Point_### so that baseline/post files can align automatically.
        """
        metadata_names = {"lightbk", "samplebk", "lightsource", "work", "dark", "light", "reference"}
        kept_columns = []
        renamed = []
        sequential_idx = 1

        for col in df.columns:
            name_str = str(col).strip()
            lower_name = name_str.lower()
            if lower_name in metadata_names:
                continue

            kept_columns.append(col)
            if re.fullmatch(r"\d{1,3}", name_str):
                new_name = f"Point_{int(name_str):03d}"
            elif lower_name.startswith("point"):
                new_name = name_str
            elif re.search(r"[A-Za-z]", name_str):
                new_name = name_str
            else:
                new_name = f"Point_{sequential_idx:03d}"
            renamed.append(new_name)
            sequential_idx += 1

        if not kept_columns:
            raise ValueError("No measurement columns detected after removing metadata columns.")

        cleaned = df[kept_columns].copy()
        cleaned.columns = renamed
        return cleaned

    def _build_delta_grid(self, delta_map):
        if not delta_map:
            return [], [], None, False

        row_indices = {}
        col_indices = {}
        placements = {}

        for name in delta_map.keys():
            parsed = self._parse_well_position(name)
            if parsed:
                row_label, col_label = parsed
                row_indices.setdefault(row_label, len(row_indices))
                col_indices.setdefault(col_label, len(col_indices))
                placements[name] = (row_label, col_label)

        # Use parsed plate layout when enough points are mapped
        if placements and len(row_indices) > 1 and len(col_indices) > 1:
            rows = sorted(row_indices.keys(), key=lambda k: (len(k), k))
            cols = sorted(col_indices.keys(), key=lambda k: (int(k), k))
            grid = np.full((len(rows), len(cols)), np.nan, dtype=np.float32)
            for label, value in delta_map.items():
                if label not in placements:
                    continue
                row_label, col_label = placements[label]
                r_idx = rows.index(row_label)
                c_idx = cols.index(col_label)
                grid[r_idx, c_idx] = value
            return rows, cols, grid, True

        # Fallback: auto tile values in a near-square grid
        values = list(delta_map.items())
        count = len(values)
        cols = int(np.ceil(np.sqrt(count)))
        rows = int(np.ceil(count / cols))
        grid = np.full((rows, cols), np.nan, dtype=np.float32)
        for idx, (_, value) in enumerate(values):
            r = idx // cols
            c = idx % cols
            grid[r, c] = value

        row_labels = [str(i + 1) for i in range(rows)]
        col_labels = [str(i + 1) for i in range(cols)]
        return row_labels, col_labels, grid, False

    @staticmethod
    def _parse_well_position(label):
        """
        Attempt to extract row letter & column number from labels like "Point A1", "A01", "B12".
        """
        sanitized = re.sub(r"[^A-Za-z0-9]", "", str(label))
        match = re.search(r"([A-Za-z])(\d{1,3})", sanitized)
        if not match:
            return None
        row = match.group(1).upper()
        col = str(int(match.group(2)))  # remove leading zeros for consistent sorting
        return row, col

    def _render_surface(self):
        if self.bar_items:
            for item in self.bar_items:
                self.gl_view.removeItem(item)
            self.bar_items.clear()
        if self.grid_item:
            self.gl_view.removeItem(self.grid_item)
            self.grid_item = None
        if self.axis_item:
            self.gl_view.removeItem(self.axis_item)
            self.axis_item = None

        rows = len(self.row_labels)
        cols = len(self.col_labels)
        if rows == 0 or cols == 0:
            return

        bar_heights = np.clip(np.nan_to_num(self.delta_grid, nan=0.0), 0.0, None)
        x_coords, y_coords = np.meshgrid(np.arange(1, cols + 1, dtype=np.float32),
                                         np.arange(1, rows + 1, dtype=np.float32))
        heights_flat = bar_heights.flatten()
        colors = self._build_bar_colors(heights_flat)

        cube_mesh = gl.MeshData(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0],
                                          [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]], dtype=np.float32),
                                np.array([[0, 1, 2], [1, 3, 2],
                                          [4, 5, 6], [5, 7, 6],
                                          [0, 1, 4], [1, 5, 4],
                                          [2, 3, 6], [3, 7, 6],
                                          [0, 2, 4], [2, 6, 4],
                                          [1, 3, 5], [3, 7, 5]], dtype=np.uint32))
        self.bar_items = []
        for (x, y, height, color) in zip(x_coords.flatten(), y_coords.flatten(), heights_flat, colors):
            mesh = GLMeshItem(meshdata=cube_mesh, smooth=False, color=color, shader="shaded", glOptions="opaque")
            mesh.scale(0.8, 0.8, height if height > 0 else 0.01)
            mesh.translate(x, y, (height if height > 0 else 0.01) / 2.0)
            self.gl_view.addItem(mesh)
            self.bar_items.append(mesh)

        self.grid_item = gl.GLGridItem()
        self.grid_item.setSize(cols + 1, rows + 1, 0.1)
        self.grid_item.setSpacing(1, 1, 1)
        self.grid_item.translate((cols + 1) / 2, (rows + 1) / 2, 0)
        self.gl_view.addItem(self.grid_item)

        z_extent = max(float(np.nanmax(bar_heights)), 0.2)
        self.axis_item = GLAxisItem()
        self.axis_item.setSize(cols + 1, rows + 1, z_extent * 1.2)
        self.gl_view.addItem(self.axis_item)

        max_extent = max(rows, cols, z_extent)
        self.gl_view.opts["distance"] = max_extent * 3.0
        self.gl_view.opts["elevation"] = 30
        self.gl_view.opts["azimuth"] = 45

    @staticmethod
    def _build_bar_colors(heights):
        if heights.size == 0:
            return np.zeros((0, 4), dtype=np.float32)
        max_val = float(np.max(heights))
        if max_val <= 0:
            return np.tile(np.array([[0.95, 0.95, 0.95, 0.9]], dtype=np.float32), (heights.size, 1))
        norm = heights / max_val
        base = np.array([0.98, 0.74, 0.20, 0.95], dtype=np.float32)  # amber
        highlight = np.array([1.0, 0.93, 0.60, 0.98], dtype=np.float32)
        colors = base + (highlight - base) * norm[:, None]
        return colors.astype(np.float32)

    def _format_stats_text(self, delta_map, warnings):
        values = np.array(list(delta_map.values()), dtype=np.float64)
        finite_values = values[np.isfinite(values)]
        if finite_values.size == 0:
            stats = self.tr("Δλ computed, but all values are NaN.")
        else:
            stats = self.tr("Δλ count: {0}, min: {1:.2f} nm, max: {2:.2f} nm").format(
                finite_values.size,
                np.min(finite_values),
                np.max(finite_values),
            )
        if self._negative_values_present:
            stats += " · " + self.tr("Negative shifts were clipped to 0 in the surface view.")
        if not self.layout_is_plate:
            stats += " · " + self.tr("Layout auto-arranged (row/column labels inferred).")
        if warnings:
            stats += " · " + " | ".join(warnings)
        return stats

    # --------------------------------------------------------------- Export ---
    def _export_png(self):
        if self.delta_grid is None:
            QMessageBox.information(self, self.tr("Info"), self.tr("Please generate the Δλ surface first."))
            return

        plate_id = self.plate_id_edit.text().strip() or "plate"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{timestamp}_{plate_id}_delta_lambda.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Save PNG Snapshot"),
            os.path.join(self.folder_path or os.path.expanduser("~"), default_name),
            "PNG Files (*.png)",
        )
        if not path:
            return

        image = self.gl_view.readQImage()
        if image.isNull():
            QMessageBox.warning(self, self.tr("Export Error"), self.tr("Unable to capture the current view."))
            return

        dpi = self.dpi_spinbox.value()
        dots_per_meter = int(dpi / 25.4 * 1000)
        image.setDotsPerMeterX(dots_per_meter)
        image.setDotsPerMeterY(dots_per_meter)
        if not image.save(path, "PNG"):
            QMessageBox.warning(self, self.tr("Export Error"), self.tr("Failed to save PNG file."))
            return
        QMessageBox.information(self, self.tr("Done"), self.tr("PNG snapshot saved:\n{0}").format(path))

    def _export_matplotlib_png(self):
        if self.delta_grid is None:
            QMessageBox.information(self, self.tr("Info"), self.tr("Please generate the Δλ surface first."))
            return
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D  # pylint: disable=unused-import,import-error
        except ImportError as exc:  # pragma: no cover
            QMessageBox.warning(
                self,
                self.tr("Dependency Missing"),
                self.tr("Matplotlib is required for high-quality export: {0}").format(str(exc)),
            )
            return

        plate_id = self.plate_id_edit.text().strip() or "plate"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{timestamp}_{plate_id}_delta_lambda_matplotlib.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Save Matplotlib PNG"),
            os.path.join(self.folder_path or os.path.expanduser("~"), default_name),
            "PNG Files (*.png)",
        )
        if not path:
            return

        z_matrix = np.clip(np.nan_to_num(self.delta_grid, nan=0.0), 0.0, None)
        rows, cols = z_matrix.shape
        xpos, ypos = np.meshgrid(np.arange(cols), np.arange(rows))
        xpos = xpos.flatten()
        ypos = ypos.flatten()
        zpos = np.zeros_like(xpos)
        dx = dy = 0.8
        dz = z_matrix.flatten()
        max_val = float(np.max(dz)) if dz.size else 1.0
        norm = dz / max_val if max_val > 0 else np.zeros_like(dz)
        cmap = plt.get_cmap("YlOrBr")
        colors = cmap(norm)

        fig = plt.figure(figsize=(8, 6), dpi=self.dpi_spinbox.value())
        ax = fig.add_subplot(111, projection="3d")
        ax.bar3d(xpos, ypos, zpos, dx, dy, dz, color=colors, shade=True, zsort="average")

        ax.set_title(f"Δλ 3D Map — {plate_id}")
        ax.set_xlabel(self.tr("Column (x)"))
        ax.set_ylabel(self.tr("Row (y)"))
        ax.set_zlabel(self.tr("Δλ (nm)"))
        ax.set_xticks(np.arange(cols) + dx / 2)
        ax.set_xticklabels(self.col_labels or [str(i + 1) for i in range(cols)])
        ax.set_yticks(np.arange(rows) + dy / 2)
        ax.set_yticklabels(self.row_labels or [str(i + 1) for i in range(rows)])
        ax.set_zlim(0, max(0.1, float(np.max(dz)) * 1.2 if dz.size else 1.0))
        ax.view_init(elev=25, azim=-60)
        ax.grid(True, linestyle=":", color="#B0BEC5", alpha=0.6)

        try:
            fig.savefig(path, dpi=self.dpi_spinbox.value(), bbox_inches="tight")
            QMessageBox.information(self, self.tr("Done"), self.tr("Matplotlib PNG saved:\n{0}").format(path))
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, self.tr("Export Error"), str(exc))
        finally:
            plt.close(fig)

    def _export_gif(self):
        if self.delta_grid is None:
            QMessageBox.information(self, self.tr("Info"), self.tr("Please generate the Δλ surface first."))
            return
        if iio is None:
            QMessageBox.warning(
                self,
                self.tr("Dependency Missing"),
                self.tr("imageio is required for GIF export. Please install it via `pip install imageio`."),
            )
            return

        plate_id = self.plate_id_edit.text().strip() or "plate"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{timestamp}_{plate_id}_delta_lambda.gif"
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Save Orbit GIF"),
            os.path.join(self.folder_path or os.path.expanduser("~"), default_name),
            "GIF Files (*.gif)",
        )
        if not path:
            return

        step = self.gif_step_spinbox.value()
        frames_needed = max(1, int(np.ceil(360 / step)))
        delay = self.gif_delay_spinbox.value() / 1000.0

        initial_opts = dict(self.gl_view.opts)
        frames = []
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            for _ in range(frames_needed):
                self.gl_view.orbit(step, 0)
                QApplication.processEvents()
                frame = self.gl_view.readQImage()
                if frame.isNull():
                    continue
                frames.append(self._qimage_to_array(frame))

            if not frames:
                QMessageBox.warning(self, self.tr("Export Error"), self.tr("Failed to capture any frames."))
                return

            iio.mimsave(path, frames, duration=delay, loop=0)
            QMessageBox.information(self, self.tr("Done"), self.tr("GIF saved:\n{0}").format(path))
        except Exception as exc:  # pylint: disable=broad-except
            QMessageBox.critical(self, self.tr("Export Error"), str(exc))
        finally:
            self._restore_camera(initial_opts)
            QApplication.restoreOverrideCursor()

    @staticmethod
    def _qimage_to_array(image: QImage):
        converted = image.convertToFormat(QImage.Format_RGBA8888)
        width = converted.width()
        height = converted.height()
        ptr = converted.bits()
        ptr.setsize(converted.byteCount())
        arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 4))
        return arr.copy()

    def _restore_camera(self, opts_snapshot):
        for key, value in opts_snapshot.items():
            if key in self.gl_view.opts:
                self.gl_view.opts[key] = value
        self.gl_view.update()
