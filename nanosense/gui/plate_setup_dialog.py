# nanosense/gui/plate_setup_dialog.py

import json
import os
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QMessageBox,
    QFormLayout,
    QScrollArea,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, QEvent  # required for changeEvent
from PyQt5.QtGui import QDoubleValidator


class PlateSetupDialog(QDialog):
    def __init__(self, parent=None, rows: int = 8, cols: int = 12, layout_label: str = ""):
        super().__init__(parent)
        self.rows = max(1, min(rows, 26))
        self.cols = max(1, cols)
        self.layout_label = layout_label or f"{self.rows} x {self.cols}"
        self.total_wells = self.rows * self.cols

        self.setMinimumSize(900, 620)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self.well_widgets = {}
        self.layout_data = {}

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # initialize translated text

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Toolbar ---
        toolbar_layout = QHBoxLayout()
        self.save_button = QPushButton()
        self.load_button = QPushButton()
        self.clear_button = QPushButton()
        toolbar_layout.addWidget(self.save_button)
        toolbar_layout.addWidget(self.load_button)
        toolbar_layout.addWidget(self.clear_button)
        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)

        self.layout_summary_label = QLabel()
        self.layout_summary_label.setAlignment(Qt.AlignCenter)
        self.layout_summary_label.setStyleSheet("color: #90A4AE; font-weight: 500;")
        main_layout.addWidget(self.layout_summary_label)

        # --- Plate Grid ---
        self.plate_group = QGroupBox()
        plate_grid_layout = QGridLayout()
        plate_grid_layout.setSpacing(5)
        self.plate_group.setLayout(plate_grid_layout)
        self.plate_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        for col in range(self.cols):
            plate_grid_layout.addWidget(QLabel(f"{col + 1}"), 0, col + 1, Qt.AlignCenter)
        for row in range(self.rows):
            row_char = chr(ord('A') + row)
            plate_grid_layout.addWidget(QLabel(row_char), row + 1, 0, Qt.AlignCenter)
            for col in range(self.cols):
                well_id = f"{row_char}{col + 1}"
                well_widget = QWidget()
                well_layout = QVBoxLayout(well_widget)
                well_layout.setContentsMargins(0, 0, 0, 0)
                concentration_edit = QLineEdit()
                concentration_edit.setPlaceholderText(well_id)
                concentration_edit.setValidator(QDoubleValidator(0.0, 1e9, 5))
                concentration_edit.setAlignment(Qt.AlignCenter)
                well_layout.addWidget(concentration_edit)
                plate_grid_layout.addWidget(well_widget, row + 1, col + 1)
                self.well_widgets[well_id] = concentration_edit
            plate_grid_layout.setRowStretch(row + 1, 0)

        plate_grid_layout.setRowStretch(self.rows + 1, 1)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.plate_group)
        main_layout.addWidget(scroll_area, 1)

        # --- Confirmation Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.save_button.clicked.connect(self._save_layout)
        self.load_button.clicked.connect(self._load_layout)
        self.clear_button.clicked.connect(self._clear_layout)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def changeEvent(self, event):
        """Handle language change events."""
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """Refresh translated UI text."""
        self.setWindowTitle(
            self.tr("Batch Acquisition Setup - {label}").format(label=self.layout_label)
        )
        self.layout_summary_label.setText(
            self.tr("{rows} rows x {cols} columns ({total} wells)").format(
                rows=self.rows, cols=self.cols, total=self.total_wells
            )
        )
        self.save_button.setText(self.tr("Save Layout"))
        self.load_button.setText(self.tr("Load Layout"))
        self.clear_button.setText(self.tr("Clear Layout"))
        self.plate_group.setTitle(self.tr("Concentration Layout"))
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("Cancel"))

    def _save_layout(self):
        layout_to_save = self._get_data_from_widgets()
        if not layout_to_save:
            QMessageBox.information(self, self.tr("Info"), self.tr("Current layout is empty, nothing to save."))
            return
        default_save_path = self.app_settings.get('default_save_path', '')
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Save Layout File"), default_save_path,
                                              self.tr("JSON Files (*.json)"))
        if path:
            try:
                with open(path, 'w') as f:
                    json.dump(layout_to_save, f, indent=4)
                QMessageBox.information(self, self.tr("Success"),
                                        self.tr("Layout successfully saved to {0}").format(path))
            except Exception as e:
                QMessageBox.critical(self, self.tr("Error"), self.tr("Failed to save layout: {0}").format(e))

    def _load_layout(self):
        default_load_path = self.app_settings.get('default_load_path', '')
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Load Layout File"), default_load_path,
                                              self.tr("JSON Files (*.json)"))
        if path:
            try:
                with open(path, 'r') as f:
                    loaded_data = json.load(f)
                self._populate_widgets_from_data(loaded_data)
                QMessageBox.information(self, self.tr("Success"),
                                        self.tr("Successfully loaded layout from {0}").format(path))
            except Exception as e:
                QMessageBox.critical(self, self.tr("Error"), self.tr("Failed to load layout: {0}").format(e))

    def get_layout_data(self):
        self.layout_data = self._get_data_from_widgets()
        if not self.layout_data:
            QMessageBox.warning(self, self.tr("Invalid Input"),
                                self.tr("You have not set the concentration for any well. Please set at least one."))
            return None
        return self.layout_data

    def _clear_layout(self):
        for well_widget in self.well_widgets.values():
            well_widget.clear()

    def _populate_widgets_from_data(self, data):
        self._clear_layout()
        for well_id, params in data.items():
            if well_id in self.well_widgets and isinstance(params, dict):
                self.well_widgets[well_id].setText(str(params.get('concentration', '')))

    def _get_data_from_widgets(self):
        current_layout = {}
        for well_id, line_edit in self.well_widgets.items():
            text = line_edit.text().strip()
            if not text:
                continue
            try:
                concentration = float(text)
            except ValueError:
                continue
            entry = {'concentration': concentration}
            current_layout[well_id] = entry
        return current_layout
