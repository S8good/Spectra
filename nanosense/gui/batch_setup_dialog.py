# nanosense/gui/batch_setup_dialog.py

import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QPushButton, QFileDialog, QComboBox, QDialogButtonBox,
                             QHBoxLayout, QLabel, QSpinBox, QCheckBox, QDoubleSpinBox, QGroupBox)
from PyQt5.QtCore import QEvent  # 新增 QEvent


class BatchSetupDialog(QDialog):
    """
    在开始批量采集前，用于设置输出文件夹和文件格式的对话框。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # 设置初始文本

    def _init_ui(self):
        """
        创建并布局所有UI控件。
        """
        self.setMinimumWidth(500)
        main_layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # 输出文件夹选择
        initial_path = self.app_settings.get('default_save_path', os.path.expanduser("~"))
        self.output_folder_edit = QLineEdit(initial_path)
        self.browse_button = QPushButton()

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.output_folder_edit)
        folder_layout.addWidget(self.browse_button)
        self.output_folder_label = QLabel()
        form_layout.addRow(self.output_folder_label, folder_layout)

        # 文件格式选择
        self.format_combo = QComboBox()
        self.format_label = QLabel()
        form_layout.addRow(self.format_label, self.format_combo)

        # “每个孔位的点数”设置
        self.points_per_well_spinbox = QSpinBox()
        self.points_per_well_spinbox.setRange(1, 512)  # 允许采集 1 到 512 个点
        self.points_per_well_spinbox.setValue(16)  # 默认值仍然是 16
        self.points_per_well_label = QLabel()  # 创建空标签，文本在翻译函数中设置
        form_layout.addRow(self.points_per_well_label, self.points_per_well_spinbox)

        # ---添加裁切范围设置 ---
        self.enable_cropping_checkbox = QCheckBox(self.tr("Enable wavelength cropping"))
        self.enable_cropping_checkbox.setChecked(True)
        form_layout.addRow(self.enable_cropping_checkbox)

        self.crop_start_spinbox = QDoubleSpinBox()
        self.crop_end_spinbox = QDoubleSpinBox()
        for spinbox in [self.crop_start_spinbox, self.crop_end_spinbox]:
            spinbox.setDecimals(1)
            spinbox.setRange(200.0, 2000.0)
            spinbox.setSingleStep(10.0)
            spinbox.setSuffix(" nm")

        self.crop_start_spinbox.setValue(450.0)
        self.crop_end_spinbox.setValue(750.0)

        self.crop_start_label = QLabel(self.tr("Crop Start Wavelength:"))
        self.crop_end_label = QLabel(self.tr("Crop End Wavelength:"))

        # --- 【新增】添加自动化采集设置 ---
        self.auto_group = QGroupBox()
        auto_layout = QFormLayout(self.auto_group)
        self.enable_auto_checkbox = QCheckBox()
        self.enable_auto_checkbox.setChecked(False)  # 默认不启用

        self.intra_well_interval_spinbox = QDoubleSpinBox()
        self.intra_well_interval_spinbox.setDecimals(1)
        self.intra_well_interval_spinbox.setRange(0.5, 300.0)
        self.intra_well_interval_spinbox.setValue(2.0)
        self.intra_well_interval_spinbox.setSuffix(" s")

        self.inter_well_interval_spinbox = QDoubleSpinBox()
        self.inter_well_interval_spinbox.setDecimals(1)
        self.inter_well_interval_spinbox.setRange(1.0, 1800.0)
        self.inter_well_interval_spinbox.setValue(10.0)
        self.inter_well_interval_spinbox.setSuffix(" s")

        self.intra_well_interval_label = QLabel()
        self.inter_well_interval_label = QLabel()

        auto_layout.addRow(self.enable_auto_checkbox)
        auto_layout.addRow(self.intra_well_interval_label, self.intra_well_interval_spinbox)
        auto_layout.addRow(self.inter_well_interval_label, self.inter_well_interval_spinbox)

        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.auto_group)  # 将新的Group添加到主布局

        form_layout.addRow(self.crop_start_label, self.crop_start_spinbox)
        form_layout.addRow(self.crop_end_label, self.crop_end_spinbox)

        main_layout.addLayout(form_layout)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        self._on_auto_acquisition_toggled(self.enable_auto_checkbox.isChecked())
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        """
        连接所有控件的信号与槽。
        """
        self.browse_button.clicked.connect(self._select_output_folder)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.enable_cropping_checkbox.toggled.connect(self._on_cropping_toggled)
        self.enable_auto_checkbox.toggled.connect(self._on_auto_acquisition_toggled)

    def _on_auto_acquisition_toggled(self, checked):
        """当自动采集复选框状态改变时，更新UI。"""
        self.intra_well_interval_spinbox.setEnabled(checked)
        self.inter_well_interval_spinbox.setEnabled(checked)
        self.intra_well_interval_label.setEnabled(checked)
        self.inter_well_interval_label.setEnabled(checked)

    def _on_cropping_toggled(self, checked):
        self.crop_start_spinbox.setEnabled(checked)
        self.crop_end_spinbox.setEnabled(checked)
        self.crop_start_label.setEnabled(checked)
        self.crop_end_label.setEnabled(checked)

    def get_settings(self):
        """
        返回用户选择的所有设置。
        """
        folder = self.output_folder_edit.text()
        format_text = self.format_combo.currentText()

        if self.tr("Excel File") in format_text:
            extension = ".xlsx"
        elif self.tr("Text File") in format_text:
            extension = ".txt"
        else:
            extension = ".csv"

        points_per_well = self.points_per_well_spinbox.value()

        crop_start = self.crop_start_spinbox.value() if self.enable_cropping_checkbox.isChecked() else None
        crop_end = self.crop_end_spinbox.value() if self.enable_cropping_checkbox.isChecked() else None

        # 【新增】获取自动化设置
        is_auto_enabled = self.enable_auto_checkbox.isChecked()
        intra_well_interval = self.intra_well_interval_spinbox.value()
        inter_well_interval = self.inter_well_interval_spinbox.value()

        # 【修改】返回所有设置
        return (folder, extension, points_per_well, crop_start, crop_end,
                is_auto_enabled, intra_well_interval, inter_well_interval)

    def changeEvent(self, event):
        """ 新增：响应语言变化事件 """
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """ 新增：重新翻译此控件内的所有UI文本 """
        self.setWindowTitle(self.tr("Batch Task Settings"))
        self.output_folder_label.setText(self.tr("Select Report Output Folder:"))
        self.browse_button.setText(self.tr("Browse..."))
        self.format_label.setText(self.tr("Select File Format:"))
        # 【新增】翻译自动化采集相关的UI
        self.auto_group.setTitle(self.tr("Automatic Acquisition Settings"))
        self.enable_auto_checkbox.setText(self.tr("Enable Automatic Acquisition"))
        self.intra_well_interval_label.setText(self.tr("Point-to-Point Interval (s):"))
        self.inter_well_interval_label.setText(self.tr("Well-to-Well Interval (s):"))

        # 为新增的标签设置文本
        self.points_per_well_label.setText(self.tr("Points per Well:"))

        # 刷新下拉框内容
        current_text = self.format_combo.currentText()
        self.format_combo.clear()
        items = [
            self.tr("Excel File (*.xlsx)"),
            self.tr("CSV File (*.csv)"),
            self.tr("Text File (*.txt)")
        ]
        self.format_combo.addItems(items)
        # 尝试恢复之前的选择
        index = self.format_combo.findText(current_text)
        if index != -1:
            self.format_combo.setCurrentIndex(index)

        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("Cancel"))

    def _select_output_folder(self):
        """
        打开文件夹选择对话框。
        """
        start_path = self.output_folder_edit.text()
        path = QFileDialog.getExistingDirectory(self, self.tr("Select Report Output Folder"), start_path)
        if path:
            self.output_folder_edit.setText(path)

