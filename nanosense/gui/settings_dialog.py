# nanosense/gui/settings_dialog.py
import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QPushButton, QFileDialog, QDialogButtonBox,
                             QHBoxLayout, QGroupBox, QLabel, QDoubleSpinBox, QMessageBox)
from PyQt5.QtCore import QEvent  # 新增 QEvent
from nanosense.core.database_manager import DatabaseManager


class SettingsDialog(QDialog):
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(500)

        self.settings = current_settings.copy()

        self._init_ui()
        self._connect_signals()
        self._populate_initial_values()
        self._retranslate_ui()  # 设置初始文本

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        self.paths_group = QGroupBox()
        paths_layout = QFormLayout(self.paths_group)

        # 保存路径
        self.save_path_edit = QLineEdit()
        self.save_path_browse_btn = QPushButton()
        save_path_layout = QHBoxLayout()
        save_path_layout.addWidget(self.save_path_edit)
        save_path_layout.addWidget(self.save_path_browse_btn)
        self.save_path_label = QLabel()
        paths_layout.addRow(self.save_path_label, save_path_layout)

        # 加载路径
        self.load_path_edit = QLineEdit()
        self.load_path_browse_btn = QPushButton()
        load_path_layout = QHBoxLayout()
        load_path_layout.addWidget(self.load_path_edit)
        load_path_layout.addWidget(self.load_path_browse_btn)
        self.load_path_label = QLabel()
        paths_layout.addRow(self.load_path_label, load_path_layout)

        self.analysis_group = QGroupBox()
        analysis_layout = QFormLayout(self.analysis_group)

        self.wl_start_spinbox = QDoubleSpinBox()
        self.wl_end_spinbox = QDoubleSpinBox()
        for spinbox in [self.wl_start_spinbox, self.wl_end_spinbox]:
            spinbox.setDecimals(1)
            spinbox.setRange(200.0, 2000.0)
            spinbox.setSingleStep(10.0)
            spinbox.setSuffix(" nm")

        self.wl_start_label = QLabel()
        self.wl_end_label = QLabel()
        analysis_layout.addRow(self.wl_start_label, self.wl_start_spinbox)
        analysis_layout.addRow(self.wl_end_label, self.wl_end_spinbox)

        main_layout.addWidget(self.paths_group)
        main_layout.addWidget(self.analysis_group)

        self.db_group = QGroupBox()
        db_layout = QFormLayout(self.db_group)
        self.db_path_edit = QLineEdit()
        self.db_path_browse_btn = QPushButton()
        db_path_layout = QHBoxLayout()
        db_path_layout.addWidget(self.db_path_edit)
        db_path_layout.addWidget(self.db_path_browse_btn)
        self.db_path_label = QLabel()
        db_layout.addRow(self.db_path_label, db_path_layout)

        self.init_db_button = QPushButton()  # 初始化按钮
        db_layout.addRow(self.init_db_button)
        main_layout.addWidget(self.db_group)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.save_path_browse_btn.clicked.connect(lambda: self._browse_folder(self.save_path_edit))
        self.load_path_browse_btn.clicked.connect(lambda: self._browse_folder(self.load_path_edit))
        self.db_path_browse_btn.clicked.connect(self._browse_db_file)
        self.init_db_button.clicked.connect(self._initialize_db)
        self.button_box.accepted.connect(self._save_and_accept)
        self.button_box.rejected.connect(self.reject)

    def changeEvent(self, event):
        """ 新增：响应语言变化事件 """
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """ 新增：重新翻译此控件内的所有UI文本 """
        # 【核心修改】
        self.setWindowTitle(self.tr("Customize Parameters"))
        self.paths_group.setTitle(self.tr("Default Paths"))

        browse_text = self.tr("Browse...")
        self.save_path_browse_btn.setText(browse_text)
        self.load_path_browse_btn.setText(browse_text)

        self.save_path_label.setText(self.tr("Default Save/Export Path:"))
        self.load_path_label.setText(self.tr("Default Load/Import Path:"))

        self.analysis_group.setTitle(self.tr("Batch Data Analysis Parameters"))
        self.wl_start_label.setText(self.tr("Peak Analysis Start Wavelength:"))
        self.wl_end_label.setText(self.tr("Peak Analysis End Wavelength:"))

        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("Cancel"))

        self.db_group.setTitle(self.tr("Database Settings"))  # 【新增】
        self.db_path_label.setText(self.tr("Database File Path:"))  # 【新增】
        self.db_path_browse_btn.setText(self.tr("Browse..."))  # 【新增】
        self.init_db_button.setText(self.tr("Initialize/Create Database"))  # 【新增】

    def _browse_folder(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, self.tr("Select Folder"), line_edit.text())
        if directory:
            line_edit.setText(directory)

    def _browse_db_file(self):  # 【新增】
        """用于选择数据库保存路径和文件名"""
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Select Database File"), self.db_path_edit.text(),
                                              "SQLite Database (*.db)")
        if path:
            self.db_path_edit.setText(path)

    def _initialize_db(self):  # 【新增】
        """点击按钮时，根据路径初始化数据库"""
        db_path = self.db_path_edit.text()
        if not db_path:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("Database path cannot be empty."))
            return
        try:
            DatabaseManager(db_path)  # 初始化会创建文件和表
            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Database successfully initialized at:\n{0}").format(db_path))
        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Failed to initialize database: {0}").format(str(e)))

    def _populate_initial_values(self):
        self.save_path_edit.setText(self.settings.get('default_save_path', os.path.expanduser("~")))
        self.load_path_edit.setText(self.settings.get('default_load_path', os.path.expanduser("~")))
        self.wl_start_spinbox.setValue(self.settings.get('analysis_wl_start', 450.0))
        self.wl_end_spinbox.setValue(self.settings.get('analysis_wl_end', 750.0))
        default_db_path = os.path.join(os.path.expanduser("~"), ".nanosense", "nanosense_data.db")
        self.db_path_edit.setText(self.settings.get('database_path', default_db_path))

    def _save_and_accept(self):
        self.settings['default_save_path'] = self.save_path_edit.text()
        self.settings['default_load_path'] = self.load_path_edit.text()
        self.settings['analysis_wl_start'] = self.wl_start_spinbox.value()
        self.settings['analysis_wl_end'] = self.wl_end_spinbox.value()
        self.settings['database_path'] = self.db_path_edit.text()
        self.accept()

    def get_settings(self):
        return self.settings