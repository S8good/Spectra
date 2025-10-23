# nanosense/gui/plate_setup_dialog.py

import json
import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget,
                             QLabel, QLineEdit, QPushButton, QDialogButtonBox,
                             QFileDialog, QGroupBox, QMessageBox)
from PyQt5.QtCore import Qt, QEvent  # 导入 QEvent
from PyQt5.QtGui import QDoubleValidator


class PlateSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(800, 600)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self.well_widgets = {}
        self.layout_data = {}

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # 设置初始文本

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Toolbar ---
        toolbar_layout = QHBoxLayout()
        self.save_button = QPushButton()  # 创建空按钮
        self.load_button = QPushButton()  # 创建空按钮
        self.clear_button = QPushButton()  # 创建空按钮
        toolbar_layout.addWidget(self.save_button)
        toolbar_layout.addWidget(self.load_button)
        toolbar_layout.addWidget(self.clear_button)
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
                line_edit = QLineEdit()
                line_edit.setPlaceholderText(well_id)
                line_edit.setValidator(QDoubleValidator(0.0, 1e9, 5))
                line_edit.setAlignment(Qt.AlignCenter)
                plate_grid_layout.addWidget(line_edit, row + 1, col + 1)
                self.well_widgets[well_id] = line_edit

        main_layout.addWidget(self.plate_group)

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
        self.plate_group.setTitle(self.tr("Concentration Layout (Unit: nM)"))
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

    # _clear_layout, _populate_widgets_from_data, _get_data_from_widgets 保持不变
    def _clear_layout(self):
        for well_widget in self.well_widgets.values():
            well_widget.clear()

    def _populate_widgets_from_data(self, data):
        self._clear_layout()
        for well_id, params in data.items():
            if well_id in self.well_widgets:
                self.well_widgets[well_id].setText(str(params.get('concentration', '')))

    def _get_data_from_widgets(self):
        current_layout = {}
        for well_id, line_edit in self.well_widgets.items():
            text = line_edit.text().strip()
            if text:
                try:
                    concentration = float(text)
                    current_layout[well_id] = {'concentration': concentration}
                except ValueError:
                    continue
        return current_layout