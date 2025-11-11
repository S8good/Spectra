# nanosense/gui/reference_template_manager.py

from __future__ import annotations

import os
from typing import Dict, Any, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QFileDialog,
    QDialogButtonBox,
    QMessageBox,
    QInputDialog,
    QTextEdit,
    QWidget,
)

from nanosense.core.reference_templates import (
    load_reference_templates,
    save_reference_templates,
    resolve_template_path,
)
from nanosense.utils.file_io import load_spectrum_from_path


class ReferenceTemplateManagerDialog(QDialog):
    """
    Manage reference spectra templates used for SAM QA.
    """

    def __init__(self, template_path: str, parent=None):
        super().__init__(parent)
        self.template_path = resolve_template_path(template_path)
        self.templates: Dict[str, Dict[str, Any]] = load_reference_templates(
            str(self.template_path)
        )
        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()
        self._refresh_template_list()

    def _init_ui(self):
        self.setMinimumSize(640, 480)
        main_layout = QVBoxLayout(self)

        self.template_list = QListWidget()
        main_layout.addWidget(self.template_list)

        button_layout = QHBoxLayout()
        self.add_button = QPushButton()
        self.remove_button = QPushButton()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_plot = pg.PlotWidget()
        self.preview_plot.showGrid(x=True, y=True, alpha=0.3)
        preview_layout.addWidget(self.preview_text)
        preview_layout.addWidget(self.preview_plot, 1)
        main_layout.addWidget(preview_container, 1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.button_box.accepted.connect(self._save_and_accept)
        self.button_box.rejected.connect(self.reject)
        self.add_button.clicked.connect(self._add_template)
        self.remove_button.clicked.connect(self._remove_template)
        self.template_list.currentItemChanged.connect(self._update_preview)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Reference Template Manager"))
        self.add_button.setText(self.tr("Add Template"))
        self.remove_button.setText(self.tr("Remove Selected"))
        self.preview_text.setPlaceholderText(self.tr("Template details preview..."))
        self.preview_plot.setTitle(self.tr("Spectrum Preview"))

    def _refresh_template_list(self):
        self.template_list.clear()
        for name in sorted(self.templates.keys()):
            self.template_list.addItem(name)
        self._update_preview()

    def _update_preview(self):
        current = self.template_list.currentItem()
        if not current:
            self.preview_text.clear()
            self.preview_plot.clear()
            return
        name = current.text()
        template = self.templates.get(name) or {}
        wavelengths = template.get("wavelengths") or []
        intensities = template.get("intensities") or []
        wl_count = len(wavelengths)
        details = [
            f"Name: {name}",
            f"Points: {wl_count}",
            f"Range: {wavelengths[0]:.2f} - {wavelengths[-1]:.2f} nm" if wl_count >= 2 else "",
            f"Notes: {template.get('notes', '')}",
        ]
        if template.get("source_path"):
            details.append(f"Source: {template['source_path']}")
        self.preview_text.setPlainText("\n".join([d for d in details if d]))
        self.preview_plot.clear()
        if wl_count >= 2 and len(intensities) == wl_count:
            self.preview_plot.plot(wavelengths, intensities, pen=pg.mkPen("c"))

    def _add_template(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Spectrum File"),
            os.path.expanduser("~"),
            self.tr("Spectra Files (*.csv *.txt *.xlsx *.xls)"),
        )
        if not file_path:
            return

        x_data, y_data = load_spectrum_from_path(file_path)
        if x_data is None or y_data is None:
            QMessageBox.warning(
                self,
                self.tr("Load Failed"),
                self.tr("Unable to parse spectrum from the selected file."),
            )
            return
        try:
            wavelengths, intensities = self._validate_template_series(x_data, y_data)
        except ValueError as exc:
            QMessageBox.warning(self, self.tr("Load Failed"), str(exc))
            return

        name, ok = QInputDialog.getText(
            self, self.tr("Template Name"), self.tr("Enter a unique template name:")
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        if name in self.templates:
            QMessageBox.warning(
                self,
                self.tr("Duplicate Name"),
                self.tr("A template with this name already exists."),
            )
            return

        self.templates[name] = {
            "wavelengths": wavelengths,
            "intensities": intensities,
            "notes": self.tr("Imported from {0}").format(os.path.basename(file_path)),
            "source_path": file_path,
        }
        self._refresh_template_list()
        items = self.template_list.findItems(name, Qt.MatchExactly)
        if items:
            self.template_list.setCurrentItem(items[0])

    def _remove_template(self):
        current = self.template_list.currentItem()
        if not current:
            return
        name = current.text()
        reply = QMessageBox.question(
            self,
            self.tr("Confirm Deletion"),
            self.tr("Remove template '{0}'?").format(name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.templates.pop(name, None)
            self._refresh_template_list()

    def _save_and_accept(self):
        save_reference_templates(self.templates, str(self.template_path))
        self.accept()

    def _validate_template_series(
        self, wavelengths, intensities
    ) -> Tuple[list, list]:
        arr_wl = np.asarray(wavelengths, dtype=float)
        arr_int = np.asarray(intensities, dtype=float)
        if arr_wl.ndim != 1 or arr_int.ndim != 1:
            raise ValueError(self.tr("Spectrum arrays must be one-dimensional."))
        if arr_wl.size != arr_int.size:
            raise ValueError(self.tr("Wavelength and intensity arrays must have equal length."))
        mask = np.isfinite(arr_wl) & np.isfinite(arr_int)
        arr_wl = arr_wl[mask]
        arr_int = arr_int[mask]
        if arr_wl.size < 2:
            raise ValueError(self.tr("Template must contain at least two valid points."))
        order = np.argsort(arr_wl)
        arr_wl = arr_wl[order]
        arr_int = arr_int[order]
        if np.any(np.diff(arr_wl) == 0):
            raise ValueError(self.tr("Wavelength axis must be strictly increasing."))
        return arr_wl.tolist(), arr_int.tolist()


__all__ = ["ReferenceTemplateManagerDialog"]
