# nanosense/gui/delta_lambda_visualizer.py

import math
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
from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import QCursor, QImage, QMatrix4x4, QVector3D, QVector4D
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
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
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from nanosense.algorithms.peak_analysis import find_main_resonance_peak
from nanosense.algorithms.preprocessing import baseline_als, smooth_savitzky_golay
from nanosense.utils.file_io import load_wide_format_spectrum

try:  # Optional dependency for GIF export
    import imageio.v3 as iio
except ImportError:
    iio = None

DEFAULT_EXPORT_DPI = 220


class DeltaLambdaGLView(gl.GLViewWidget):
    """Custom GL view adding right-button panning while keeping default rotation/zoom."""

    hoverInfoChanged = pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pan_active = False
        self._last_mouse_pos = None
        self._bar_metadata = []
        self.mousePos = QPoint()  # ensure pyqtgraph base class has an initial value
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._pan_active = True
            self._last_mouse_pos = event.pos()
            event.accept()
        else:
            super().mousePressEvent(event)
            self._emit_hover_info(event.pos())

    def mouseMoveEvent(self, event):
        if self._pan_active and event.buttons() & Qt.RightButton:
            if self._last_mouse_pos is None:
                self._last_mouse_pos = event.pos()
            delta = event.pos() - self._last_mouse_pos
            # Negative X delta pans scene to the right visually; adjust scaling to keep smooth
            self.pan(-delta.x() * 0.02, delta.y() * 0.02, 0)
            self._last_mouse_pos = event.pos()
            event.accept()
        else:
            super().mouseMoveEvent(event)
            self._emit_hover_info(event.pos())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton and self._pan_active:
            self._pan_active = False
            self._last_mouse_pos = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            self._emit_hover_info(event.pos())

    def set_bar_metadata(self, metadata):
        self._bar_metadata = metadata or []

    def _emit_hover_info(self, pos):
        if not self._bar_metadata:
            self.hoverInfoChanged.emit(None)
            return
        info = self._pick_bar(pos)
        self.hoverInfoChanged.emit(info)

    def _pick_bar(self, pos):
        width = max(1, self.width())
        height = max(1, self.height())

        proj = QMatrix4x4()
        aspect = width / float(height)
        fov = float(self.opts.get("fov", 60.0))
        near_clip = float(self.opts.get("nearClip", 0.1))
        far_clip = float(self.opts.get("farClip", 10000.0))
        proj.perspective(fov, aspect, near_clip, far_clip)

        view = QMatrix4x4()
        view.translate(0, 0, -self.opts["distance"])
        view.rotate(self.opts["elevation"], 1, 0, 0)
        view.rotate(self.opts["azimuth"], 0, 0, 1)
        center = self.opts["center"]
        cx = center.x() if hasattr(center, "x") else center[0]
        cy = center.y() if hasattr(center, "y") else center[1]
        cz = center.z() if hasattr(center, "z") else center[2]
        view.translate(-cx, -cy, -cz)

        mvp = proj * view
        inv_mvp, invertible = mvp.inverted()
        if not invertible:
            return None

        def to_vec3(vec4):
            w = vec4.w()
            if w == 0:
                return QVector3D(vec4.x(), vec4.y(), vec4.z())
            return QVector3D(vec4.x() / w, vec4.y() / w, vec4.z() / w)

        def screen_to_world(depth):
            ndc_x = (2.0 * pos.x() / width) - 1.0
            ndc_y = 1.0 - (2.0 * pos.y() / height)
            clip_point = QVector4D(ndc_x, ndc_y, depth, 1.0)
            world_point = inv_mvp * clip_point
            return to_vec3(world_point)

        near_point = screen_to_world(-1.0)
        far_point = screen_to_world(1.0)
        direction_vec = (far_point - near_point)
        if math.isclose(direction_vec.lengthSquared(), 0.0, abs_tol=1e-9):
            return None
        direction = direction_vec.normalized()

        def project_point(point):
            vec = QVector4D(point, 1.0)
            clip = proj * (view * vec)
            if clip.w() == 0:
                return None
            ndc_x = clip.x() / clip.w()
            ndc_y = clip.y() / clip.w()
            screen_x = (ndc_x * 0.5 + 0.5) * width
            screen_y = (1 - (ndc_y * 0.5 + 0.5)) * height
            return screen_x, screen_y

        def ray_aabb_distance(center_vec, extent):
            ex, ey, ez = extent
            min_corner = QVector3D(center_vec.x() - ex, center_vec.y() - ey, center_vec.z() - ez)
            max_corner = QVector3D(center_vec.x() + ex, center_vec.y() + ey, center_vec.z() + ez)

            t_min = -float("inf")
            t_max = float("inf")

            for axis in ("x", "y", "z"):
                origin_val = getattr(near_point, axis)()
                dir_val = getattr(direction, axis)()
                min_val = getattr(min_corner, axis)()
                max_val = getattr(max_corner, axis)()

                if math.isclose(dir_val, 0.0, abs_tol=1e-9):
                    if origin_val < min_val or origin_val > max_val:
                        return None
                    continue

                inv_dir = 1.0 / dir_val
                t1 = (min_val - origin_val) / dir_val
                t2 = (max_val - origin_val) / dir_val
                if t1 > t2:
                    t1, t2 = t2, t1
                t_min = max(t_min, t1)
                t_max = min(t_max, t2)
                if t_max < t_min:
                    return None

            if t_max < 0:
                return None
            return t_min if t_min >= 0 else t_max

        best = None
        best_dist = float("inf")

        for meta in self._bar_metadata:
            center_vec = meta.get("center")
            extent = meta.get("extent")
            if center_vec is None or extent is None:
                continue
            distance = ray_aabb_distance(center_vec, extent)
            if distance is None or distance >= best_dist:
                continue
            best_dist = distance
            best = dict(meta)
            projection = project_point(center_vec)
            if projection is not None:
                best["widget_pos"] = QPoint(int(projection[0]), int(projection[1]))
            else:
                best["widget_pos"] = QPoint(int(pos.x()), int(pos.y()))
            best["cursor_pos"] = self.mapToGlobal(pos)

        return best


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
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)

        self.preprocessing_params = preprocessing_params or {}
        self.app_settings = app_settings or {}

        self.folder_path = None
        self.available_files = []
        self.delta_grid = None
        self.delta_map = {}
        self.row_labels = []
        self.col_labels = []
        self.layout_is_plate = False
        self.label_grid = None
        self.table_row_lookup = {}
        self.bar_items = []
        self.grid_item = None
        self.axis_item = None
        self.plate_id = ""
        self._negative_values_present = False
        self._default_camera_opts = {}

        self._build_ui()
        self._connect_signals()
        self._update_controls_state()
        if initial_folder:
            self._load_folder(initial_folder, show_warning=False)

    # ------------------------------------------------------------------ UI ---
    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        layout.addWidget(self.main_splitter, 1)

        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        self.folder_group = QGroupBox(self.tr("Input Folder (two batch files required)"))
        folder_layout = QVBoxLayout(self.folder_group)

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

        margin_default = float(self.app_settings.get("analysis_wl_margin", 20.0))
        self.margin_spinbox = QDoubleSpinBox()
        self.margin_spinbox.setRange(0.0, 200.0)
        self.margin_spinbox.setDecimals(1)
        self.margin_spinbox.setValue(margin_default)
        self.margin_spinbox.setSuffix(" nm")
        self.margin_spinbox.setMaximumWidth(110)
        combo_form.addRow(self.tr("Safety margin:"), self.margin_spinbox)

        preprocess_row = QHBoxLayout()
        preprocess_row.setContentsMargins(0, 0, 0, 0)
        preprocess_row.setSpacing(8)
        baseline_default = bool(self.app_settings.get("analysis_baseline_enabled", True))
        smoothing_default = bool(self.app_settings.get("analysis_smoothing_enabled", True))
        self.baseline_checkbox = QCheckBox(self.tr("ALS baseline"))
        self.baseline_checkbox.setChecked(baseline_default)
        self.smoothing_checkbox = QCheckBox(self.tr("Savitzky-Golay"))
        self.smoothing_checkbox.setChecked(smoothing_default)
        preprocess_row.addWidget(self.baseline_checkbox)
        preprocess_row.addWidget(self.smoothing_checkbox)
        preprocess_widget = QWidget()
        preprocess_widget.setLayout(preprocess_row)
        combo_form.addRow(self.tr("Preprocessing:"), preprocess_widget)
        folder_layout.addLayout(combo_form)

        self.compute_button = QPushButton(self.tr("Load && Compute Δλ"))
        folder_layout.addWidget(self.compute_button)

        self.meta_group = QGroupBox(self.tr("Metadata & Export Settings"))
        meta_layout = QFormLayout(self.meta_group)
        self.plate_id_edit = QLineEdit()
        meta_layout.addRow(self.tr("Plate ID (for filenames):"), self.plate_id_edit)

        export_row = QHBoxLayout()
        self.export_matplotlib_button = QPushButton(self.tr("Export Matplotlib PNG"))
        export_row.addWidget(self.export_matplotlib_button)
        self.export_table_button = QPushButton(self.tr("Export Δλ Table"))
        export_row.addWidget(self.export_table_button)
        meta_layout.addRow(self.tr("High-quality PNG / Data:"), export_row)

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

        self.folder_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.meta_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        controls_layout.addWidget(self.folder_group)
        controls_layout.addWidget(self.meta_group)
        controls_layout.addStretch(1)
        self.controls_widget = controls_widget
        self.main_splitter.addWidget(controls_widget)

        self.point_table = QTableWidget(0, 2)
        self.point_table.setHorizontalHeaderLabels([self.tr("Point"), self.tr("Δλ (nm)")])
        self.point_table.verticalHeader().setVisible(False)
        self.point_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.point_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.point_table.setSelectionMode(QTableWidget.SingleSelection)
        self.point_table.horizontalHeader().setStretchLastSection(True)
        self.point_table.setMinimumWidth(220)

        self.point_table_label = QLabel(self.tr("Point Δλ Summary"))
        table_layout = QVBoxLayout()
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(6)
        table_layout.addWidget(self.point_table_label)
        table_layout.addWidget(self.point_table, 1)
        table_widget = QWidget()
        table_widget.setLayout(table_layout)
        self.table_widget = table_widget

        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(6)

        self.gl_view = DeltaLambdaGLView()
        self.gl_view.setBackgroundColor(20, 20, 20)
        self.gl_view.opts["distance"] = 60
        self.gl_view.setMinimumHeight(320)
        self.hover_overlay_label = QLabel(self.gl_view)
        self.hover_overlay_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 180); color: #FFEE58; padding: 3px 6px; border-radius: 4px;"
        )
        self.hover_overlay_label.hide()
        central_layout.addWidget(self.gl_view, 1)

        footer_row = QHBoxLayout()
        footer_left = QHBoxLayout()
        self.toggle_view_button = QPushButton(self.tr("Expand 3D View"))
        self.toggle_view_button.setCheckable(True)
        footer_left.addWidget(self.toggle_view_button, alignment=Qt.AlignLeft)

        footer_text_layout = QVBoxLayout()
        footer_text_layout.setContentsMargins(12, 0, 0, 0)
        self.summary_label = QLabel(self.tr("\u0394\u03bb surface not generated yet."))
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        footer_text_layout.addWidget(self.summary_label)
        self.hover_label = QLabel(self.tr("Hover a bar to see details."))
        footer_text_layout.addWidget(self.hover_label)
        footer_left.addLayout(footer_text_layout)

        footer_row.addLayout(footer_left, 1)
        central_layout.addLayout(footer_row)

        self.main_splitter.addWidget(central_widget)
        self.main_splitter.addWidget(table_widget)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)

    def _connect_signals(self):
        self.select_folder_button.clicked.connect(self._select_folder)
        self.compute_button.clicked.connect(self._load_and_visualize)
        self.export_matplotlib_button.clicked.connect(self._export_matplotlib_png)
        self.export_gif_button.clicked.connect(self._export_gif)
        self.export_table_button.clicked.connect(self._export_delta_table)
        self.toggle_view_button.toggled.connect(self._toggle_expanded_view)
        self.gl_view.hoverInfoChanged.connect(self._on_hover_info)

    def _update_controls_state(self):
        has_folder = bool(self.folder_path and len(self.available_files) >= 2)
        has_data = self.delta_grid is not None
        self.compute_button.setEnabled(has_folder)
        self.export_matplotlib_button.setEnabled(has_data)
        self.export_gif_button.setEnabled(has_data)

    def _toggle_expanded_view(self, checked):
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(not checked)
        self.point_table_label.setVisible(not checked)
        self.point_table.setVisible(not checked)
        if hasattr(self, "table_widget"):
            self.table_widget.setVisible(not checked)
        self.toggle_view_button.setText(
            self.tr("Exit Expanded View") if checked else self.tr("Expand 3D View")
        )
        self.gl_view.setMinimumHeight(600 if checked else 320)
        if checked:
            self.resize(self.width(), max(self.height(), 720))

    def _on_hover_info(self, info):
        if not info:
            QToolTip.hideText()
            self.hover_label.setText(self.tr("Hover a bar to see details."))
            self.point_table.clearSelection()
            self.hover_overlay_label.hide()
            return
        text = f"{info['label']}: {info['delta']:.3f} nm"
        self.hover_label.setText(text)
        widget_pos = info.get("widget_pos")
        if widget_pos:
            local_pt = widget_pos + QPoint(12, -12)
            self.hover_overlay_label.setText(text)
            self.hover_overlay_label.adjustSize()
            x = max(0, min(self.gl_view.width() - self.hover_overlay_label.width(), local_pt.x()))
            y = max(0, min(self.gl_view.height() - self.hover_overlay_label.height(), local_pt.y()))
            self.hover_overlay_label.move(x, y)
            self.hover_overlay_label.show()
        else:
            self.hover_overlay_label.hide()
        if "cursor_pos" in info:
            QToolTip.showText(info["cursor_pos"], text, self.gl_view)
        row = self.table_row_lookup.get(info["label"])
        if row is not None:
            self.point_table.selectRow(row)

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

        self.app_settings["analysis_wl_margin"] = float(self.margin_spinbox.value())
        self.app_settings["analysis_baseline_enabled"] = bool(self.baseline_checkbox.isChecked())
        self.app_settings["analysis_smoothing_enabled"] = bool(self.smoothing_checkbox.isChecked())

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
            (
                self.row_labels,
                self.col_labels,
                grid,
                self.layout_is_plate,
                self.label_grid,
            ) = self._build_delta_grid(delta_map)
            if grid is None:
                QMessageBox.warning(
                    self,
                    self.tr("Visualization Error"),
                    self.tr("No valid Δλ values were computed; cannot render the surface."),
                )
                return

            self.delta_grid = grid
            self._render_surface()
            self._populate_point_table()
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
        wl_margin = max(0.0, float(self.app_settings.get("analysis_wl_margin", 20.0)))
        apply_baseline = bool(self.app_settings.get("analysis_baseline_enabled", True))
        apply_smoothing = bool(self.app_settings.get("analysis_smoothing_enabled", True))

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

            wl_min = float(np.nanmin(wavelengths))
            wl_max = float(np.nanmax(wavelengths))
            margin_start = max(wl_min, wl_start - wl_margin)
            margin_end = min(wl_max, wl_end + wl_margin)

            margin_mask = (wavelengths >= margin_start) & (wavelengths <= margin_end)
            if not np.any(margin_mask):
                peaks[str(col)] = np.nan
                continue

            margin_wl = wavelengths[margin_mask]
            margin_int = intensities[margin_mask]
            if margin_wl.size < 20:
                peaks[str(col)] = np.nan
                continue

            working = margin_int
            if apply_baseline:
                baseline = baseline_als(margin_int, lam=als_lambda, p=als_p)
                working = margin_int - baseline

            if apply_smoothing:
                coarse = smooth_savitzky_golay(working, sg_window_coarse, sg_poly_coarse)
                fine = smooth_savitzky_golay(coarse, sg_window_fine, sg_poly_fine)
            else:
                fine = working

            final_mask = (margin_wl >= wl_start) & (margin_wl <= wl_end)
            if not np.any(final_mask):
                peaks[str(col)] = np.nan
            else:
                sub_wl = margin_wl[final_mask]
                sub_int = fine[final_mask]
                if sub_wl.size < 20:
                    peaks[str(col)] = np.nan
                    continue
                peak_idx, _ = find_main_resonance_peak(sub_int, min_height=0)
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
            if lower_name.startswith("point"):
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
            return [], [], None, False, None

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
            label_grid = np.empty((len(rows), len(cols)), dtype=object)
            label_grid[:] = None
            for label, value in delta_map.items():
                if label not in placements:
                    continue
                row_label, col_label = placements[label]
                r_idx = rows.index(row_label)
                c_idx = cols.index(col_label)
                grid[r_idx, c_idx] = value
                label_grid[r_idx, c_idx] = label
            return rows, cols, grid, True, label_grid

        # Fallback: auto tile values in a near-square grid
        values = list(delta_map.items())
        count = len(values)
        cols = int(np.ceil(np.sqrt(count)))
        rows = int(np.ceil(count / cols))
        grid = np.full((rows, cols), np.nan, dtype=np.float32)
        label_grid = np.empty((rows, cols), dtype=object)
        label_grid[:] = None
        for idx, (label, value) in enumerate(values):
            r = idx // cols
            c = idx % cols
            grid[r, c] = value
            label_grid[r, c] = label

        row_labels = [str(i + 1) for i in range(rows)]
        col_labels = [str(i + 1) for i in range(cols)]
        return row_labels, col_labels, grid, False, label_grid

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

        raw_matrix = np.nan_to_num(self.delta_grid, nan=0.0)
        bar_heights = np.abs(raw_matrix)
        raw_values_flat = raw_matrix.flatten()
        label_flat = self.label_grid.flatten() if self.label_grid is not None else [None] * raw_values_flat.size
        x_coords, y_coords = np.meshgrid(
            np.arange(1, cols + 1, dtype=np.float32),
            np.arange(1, rows + 1, dtype=np.float32),
        )
        heights_flat = bar_heights.flatten()
        colors = self._build_bar_colors(raw_values_flat)

        vertices = np.array(
            [
                [-0.5, -0.5, -0.5],
                [0.5, -0.5, -0.5],
                [-0.5, 0.5, -0.5],
                [0.5, 0.5, -0.5],
                [-0.5, -0.5, 0.5],
                [0.5, -0.5, 0.5],
                [-0.5, 0.5, 0.5],
                [0.5, 0.5, 0.5],
            ],
            dtype=np.float32,
        )
        faces = np.array(
            [
                [0, 1, 2],
                [1, 3, 2],
                [4, 5, 6],
                [5, 7, 6],
                [0, 1, 4],
                [1, 5, 4],
                [2, 3, 6],
                [3, 7, 6],
                [0, 2, 4],
                [2, 6, 4],
                [1, 3, 5],
                [3, 7, 5],
            ],
            dtype=np.uint32,
        )
        cube_mesh = gl.MeshData(vertices, faces)
        self.bar_items = []
        metadata = []
        for idx, (x, y, magnitude, color, label) in enumerate(
            zip(x_coords.flatten(), y_coords.flatten(), heights_flat, colors, label_flat)
        ):
            if label is None or idx >= raw_values_flat.size:
                continue
            raw_value = raw_values_flat[idx]
            if np.isnan(raw_value):
                continue
            mesh = GLMeshItem(meshdata=cube_mesh, smooth=False, color=color, shader="shaded", glOptions="opaque")
            effective_height = max(magnitude, 0.02)
            mesh.scale(0.8, 0.8, effective_height)
            z_offset = effective_height / 2.0 if raw_value >= 0 else -effective_height / 2.0
            mesh.translate(x, y, z_offset)
            self.gl_view.addItem(mesh)
            self.bar_items.append(mesh)
            metadata.append(
                {
                    "label": label,
                    "delta": float(raw_value),
                    "center": QVector3D(float(x), float(y), float(z_offset)),
                    "extent": (0.4, 0.4, effective_height / 2.0),
                }
            )
        self.gl_view.set_bar_metadata(metadata)

        self.grid_item = gl.GLGridItem()
        self.grid_item.setSize(cols + 1, rows + 1, 0.1)
        self.grid_item.setSpacing(1, 1, 1)
        self.grid_item.translate((cols + 1) / 2, (rows + 1) / 2, 0)
        self.gl_view.addItem(self.grid_item)

        pos_mask = raw_matrix > 0
        neg_mask = raw_matrix < 0
        max_pos_height = float(np.nanmax(np.where(pos_mask, bar_heights, 0.0))) if pos_mask.any() else 0.0
        max_neg_height = float(np.nanmax(np.where(neg_mask, bar_heights, 0.0))) if neg_mask.any() else 0.0
        total_height = max(max_pos_height + max_neg_height, 0.2)
        self.axis_item = GLAxisItem()
        self.axis_item.setSize(cols + 1, rows + 1, total_height * 1.2)
        self.gl_view.addItem(self.axis_item)

        center_z = (max_pos_height - max_neg_height) / 2.0
        self.gl_view.opts["center"] = QVector3D((cols + 1) / 2, (rows + 1) / 2, center_z)

        max_extent = max(rows, cols, total_height)
        self.gl_view.opts["distance"] = max_extent * 3.0
        self.gl_view.opts["elevation"] = 30
        self.gl_view.opts["azimuth"] = 45
        self._default_camera_opts = self._snapshot_camera_opts()

    @staticmethod
    def _build_bar_colors(values):
        if values.size == 0:
            return np.zeros((0, 4), dtype=np.float32)
        max_abs = float(np.max(np.abs(values)))
        if max_abs <= 0:
            return np.tile(np.array([[0.8, 0.8, 0.8, 0.95]], dtype=np.float32), (values.size, 1))
        norm = np.abs(values) / max_abs
        pos_base = np.array([0.98, 0.74, 0.20, 0.95], dtype=np.float32)
        pos_high = np.array([1.0, 0.93, 0.60, 0.98], dtype=np.float32)
        neg_base = np.array([0.35, 0.54, 0.96, 0.95], dtype=np.float32)
        neg_high = np.array([0.63, 0.80, 0.98, 0.98], dtype=np.float32)
        colors = np.zeros((values.size, 4), dtype=np.float32)
        pos_mask = values >= 0
        colors[pos_mask] = pos_base + (pos_high - pos_base) * norm[pos_mask][:, None]
        colors[~pos_mask] = neg_base + (neg_high - neg_base) * norm[~pos_mask][:, None]
        return colors

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
        if not self.layout_is_plate:
            stats += " · " + self.tr("Layout auto-arranged (row/column labels inferred).")
        if warnings:
            stats += " · " + " | ".join(warnings)
        return stats

    def _populate_point_table(self):
        sorted_items = sorted(self.delta_map.items())
        self.point_table.setRowCount(len(sorted_items))
        self.table_row_lookup = {}
        for row, (label, value) in enumerate(sorted_items):
            label_item = QTableWidgetItem(label)
            value_text = "" if np.isnan(value) else f"{value:.3f}"
            value_item = QTableWidgetItem(value_text)
            self.point_table.setItem(row, 0, label_item)
            self.point_table.setItem(row, 1, value_item)
            self.table_row_lookup[label] = row
        self.point_table.resizeColumnsToContents()

    # --------------------------------------------------------------- Export ---
    def _export_matplotlib_png(self):
        if self.delta_grid is None:
            QMessageBox.information(self, self.tr("Info"), self.tr("Please generate the Δλ surface first."))
            return
        try:
            import matplotlib
            matplotlib.use("Agg")
            matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
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

        export_dpi = DEFAULT_EXPORT_DPI
        fig = plt.figure(figsize=(8, 6), dpi=export_dpi)
        ax = fig.add_subplot(111, projection="3d")
        ax.bar3d(xpos, ypos, zpos, dx, dy, dz, color=colors, shade=True, zsort="average")

        ax.set_title(f"\u0394\u03bb 3D Map \u2014 {plate_id}")
        ax.set_xlabel(self.tr("Column (x)"))
        ax.set_ylabel(self.tr("Row (y)"))
        ax.set_zlabel(self.tr("\u0394\u03bb (nm)"))
        ax.set_xticks(np.arange(cols) + dx / 2)
        ax.set_xticklabels(self.col_labels or [str(i + 1) for i in range(cols)])
        ax.set_yticks(np.arange(rows) + dy / 2)
        ax.set_yticklabels(self.row_labels or [str(i + 1) for i in range(rows)])
        ax.set_zlim(0, max(0.1, float(np.max(dz)) * 1.2 if dz.size else 1.0))
        ax.view_init(elev=25, azim=-60)
        ax.grid(True, linestyle=":", color="#B0BEC5", alpha=0.6)

        try:
            fig.savefig(path, dpi=export_dpi, bbox_inches="tight")
            QMessageBox.information(self, self.tr("Done"), self.tr("Matplotlib PNG saved:\n{0}").format(path))
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, self.tr("Export Error"), str(exc))
        finally:
            plt.close(fig)

    def _export_delta_table(self):
        if not self.delta_map:
            QMessageBox.information(self, self.tr("Info"), self.tr("No Δλ data to export."))
            return

        plate_id = self.plate_id_edit.text().strip() or "plate"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{timestamp}_{plate_id}_delta_lambda_table.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export Δλ Table"),
            os.path.join(self.folder_path or os.path.expanduser("~"), default_name),
            "CSV Files (*.csv)",
        )
        if not path:
            return

        try:
            lines = ["Point,DeltaLambda_nm"]
            for label, value in sorted(self.delta_map.items()):
                val_text = "" if np.isnan(value) else f"{value:.6f}"
                lines.append(f"{label},{val_text}")
            with open(path, "w", encoding="utf-8") as fptr:
                fptr.write("\n".join(lines))
            QMessageBox.information(self, self.tr("Done"), self.tr("Δλ table exported:\n{0}").format(path))
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Export Error"), str(exc))

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

        initial_opts = self._snapshot_camera_opts()
        frames = []
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            self._apply_default_camera_view()
            self.gl_view.update()
            QApplication.processEvents()
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

            saver = getattr(iio, "mimsave", None)
            if saver is None:  # imageio.v3 drops mimsave; fall back to v2 API if available
                try:
                    import imageio

                    saver = getattr(imageio, "mimsave", None)
                except ImportError:  # pragma: no cover - extremely unlikely
                    saver = None
            if saver is None:
                QMessageBox.warning(
                    self,
                    self.tr("Export Error"),
                    self.tr("Installed imageio package does not provide GIF saving (`mimsave`)."),
                )
                return

            saver(path, frames, duration=delay, loop=0)
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
                if isinstance(value, QVector3D):
                    self.gl_view.opts[key] = QVector3D(value)
                else:
                    self.gl_view.opts[key] = value
        self.gl_view.update()

    def _apply_default_camera_view(self):
        if not self._default_camera_opts:
            return
        self._restore_camera(self._default_camera_opts)
        QApplication.processEvents()

    def _snapshot_camera_opts(self):
        opts = dict(self.gl_view.opts)
        center = opts.get("center")
        if isinstance(center, QVector3D):
            opts["center"] = QVector3D(center)
        elif isinstance(center, (tuple, list)) and len(center) == 3:
            opts["center"] = tuple(center)
        return opts
