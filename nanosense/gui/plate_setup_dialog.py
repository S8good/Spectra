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
    QComboBox,
    QFormLayout,
    QSpinBox,
)
from PyQt5.QtCore import Qt, QEvent  # 导入 QEvent
from PyQt5.QtGui import QDoubleValidator
from ..core.reference_templates import (
    load_reference_templates,
    resolve_template_path,
)
from .reference_template_manager import ReferenceTemplateManagerDialog


class PlateSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(800, 600)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        template_setting = self.app_settings.get('reference_template_path')
        template_path = resolve_template_path(template_setting)
        self.template_path = str(template_path)
        self.app_settings['reference_template_path'] = self.template_path
        self.templates = load_reference_templates(self.template_path)

        self.well_widgets = {}
        self.reference_widgets = {}
        self.layout_data = {}

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # 设置初始文本

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Toolbar ---
        toolbar_layout = QHBoxLayout()
        self.save_button = QPushButton()
        self.load_button = QPushButton()
        self.clear_button = QPushButton()
        self.manage_templates_button = QPushButton()
        toolbar_layout.addWidget(self.save_button)
        toolbar_layout.addWidget(self.load_button)
        toolbar_layout.addWidget(self.clear_button)
        toolbar_layout.addWidget(self.manage_templates_button)
        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)

        # --- 96-Well Plate Grid ---
        self.plate_group = QGroupBox()  # 创建空分组框
        plate_grid_layout = QGridLayout(self.plate_group)
        plate_grid_layout.setSpacing(5)

        for col in range(12):
            plate_grid_layout.addWidget(QLabel(f"{col + 1}"), 0, col + 1, Qt.AlignCenter)
        for row in range(8):
            row_char = chr(ord('A') + row)
            plate_grid_layout.addWidget(QLabel(row_char), row + 1, 0, Qt.AlignCenter)
            for col in range(12):
                well_id = f"{row_char}{col + 1}"
                well_widget = QWidget()
                well_layout = QVBoxLayout(well_widget)
                well_layout.setContentsMargins(0, 0, 0, 0)
                concentration_edit = QLineEdit()
                concentration_edit.setPlaceholderText(well_id)
                concentration_edit.setValidator(QDoubleValidator(0.0, 1e9, 5))
                concentration_edit.setAlignment(Qt.AlignCenter)
                ref_combo = QComboBox()
                ref_combo.addItem(self.tr("Use Reference Capture"), "capture")
                ref_combo.addItem(self.tr("Use Template"), "template")
                template_combo = QComboBox()
                template_combo.addItem(self.tr("Select Template"), "")
                template_combo.setEnabled(False)
                threshold_spin = QSpinBox()
                threshold_spin.setRange(1, 90)
                threshold_spin.setSuffix("°")
                threshold_spin.setValue(5)
                self.reference_widgets[well_id] = {
                    "mode": ref_combo,
                    "threshold": threshold_spin,
                    "template": template_combo,
                }
                well_layout.addWidget(concentration_edit)
                well_layout.addWidget(ref_combo)
                well_layout.addWidget(template_combo)
                well_layout.addWidget(threshold_spin)
                self._bind_reference_mode(ref_combo, template_combo)
                plate_grid_layout.addWidget(well_widget, row + 1, col + 1)
                self.well_widgets[well_id] = concentration_edit

        main_layout.addWidget(self.plate_group)
        self._refresh_template_options()

        # --- Confirmation Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.save_button.clicked.connect(self._save_layout)
        self.load_button.clicked.connect(self._load_layout)
        self.clear_button.clicked.connect(self._clear_layout)
        self.manage_templates_button.clicked.connect(self._open_template_manager)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def changeEvent(self, event):
        """ 新增：响应语言变化事件 """
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """ 新增：重新翻译此控件内的所有UI文本 """
        self.setWindowTitle(self.tr("Batch Acquisition Setup (96-Well Plate Layout)"))
        self.save_button.setText(self.tr("Save Layout"))
        self.load_button.setText(self.tr("Load Layout"))
        self.clear_button.setText(self.tr("Clear Layout"))
        self.manage_templates_button.setText(self.tr("Manage Templates..."))
        self.plate_group.setTitle(self.tr("Concentration & QA Layout"))
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
        for widgets in self.reference_widgets.values():
            widgets["mode"].setCurrentIndex(0)
            widgets["threshold"].setValue(5)
            widgets["template"].setCurrentIndex(0)
            widgets["template"].setEnabled(False)
        for well_widget in self.well_widgets.values():
            well_widget.clear()

    def _populate_widgets_from_data(self, data):
        self._clear_layout()
        for well_id, params in data.items():
            if well_id in self.well_widgets and isinstance(params, dict):
                self.well_widgets[well_id].setText(str(params.get('concentration', '')))
                reference = params.get("reference") or {}
                widgets = self.reference_widgets.get(well_id)
                if not widgets:
                    continue
                mode = reference.get("source", "reference_capture")
                index = widgets["mode"].findData("template" if mode == "template" else "capture")
                if index >= 0:
                    widgets["mode"].setCurrentIndex(index)
                threshold = reference.get("sam_threshold_deg")
                if isinstance(threshold, (int, float)):
                    widgets["threshold"].setValue(int(threshold))
                template_name = reference.get("template_id")
                combo = widgets["template"]
                target_idx = combo.findData(template_name) if template_name else 0
                combo.setCurrentIndex(target_idx if target_idx >= 0 else 0)
                combo.setEnabled(widgets["mode"].currentData() == "template")

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
            ref_widgets = self.reference_widgets.get(well_id)
            if ref_widgets:
                mode = ref_widgets["mode"].currentData()
                threshold = ref_widgets["threshold"].value()
                reference_block = {
                    "source": "template" if mode == "template" else "reference_capture",
                    "sam_threshold_deg": threshold,
                }
                template_value = ref_widgets["template"].currentData()
                if reference_block["source"] == "template" and template_value:
                    reference_block["template_id"] = template_value
                entry["reference"] = reference_block
            current_layout[well_id] = entry
        return current_layout

    def _bind_reference_mode(self, mode_combo: QComboBox, template_combo: QComboBox):
        def handler(index: int):
            template_combo.setEnabled(mode_combo.itemData(index) == "template")
        mode_combo.currentIndexChanged.connect(handler)
        handler(mode_combo.currentIndex())

    def _refresh_template_options(self):
        template_names = sorted(self.templates.keys())
        for widgets in self.reference_widgets.values():
            combo = widgets["template"]
            current_value = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(self.tr("Select Template"), "")
            for name in template_names:
                combo.addItem(name, name)
            target_idx = combo.findData(current_value) if current_value else 0
            combo.setCurrentIndex(target_idx if target_idx >= 0 else 0)
            combo.blockSignals(False)
            combo.setEnabled(widgets["mode"].currentData() == "template")

    def _open_template_manager(self):
        dialog = ReferenceTemplateManagerDialog(self.template_path, self)
        if dialog.exec_() == QDialog.Accepted:
            self.templates = load_reference_templates(self.template_path)
            self._refresh_template_options()
