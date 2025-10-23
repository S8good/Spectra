# 文件路径: nanosense/gui/batch_report_dialog.py

import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QPushButton, QFileDialog, QCheckBox, QGroupBox,
                             QProgressBar, QLabel, QMessageBox, QHBoxLayout)
from PyQt5.QtCore import QThread, pyqtSignal, QEvent  # 导入 QEvent

from nanosense.utils.file_io import load_wide_format_spectrum
from nanosense.utils.report_generator import run_analysis_pipeline, generate_reports

class ReportWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str, str)  # 'status', 'message_or_path'

    def __init__(self, input_path, output_folder, options):
        super().__init__()
        self.input_path = input_path
        self.output_folder = output_folder
        self.options = options

    def run(self):
        try:
            # 1. 加载数据 (使用英文源文本)
            self.progress.emit(10, "Loading spectrum data...")
            wavelengths, spectra_df, error = load_wide_format_spectrum(self.input_path)
            if error:
                self.finished.emit("error", f"Load failed: {error}")
                return

            # 2. 运行分析 (使用英文源文本)
            self.progress.emit(40, "Analyzing spectra...")
            analysis_results = run_analysis_pipeline(wavelengths, spectra_df)
            if 'error' in analysis_results:
                self.finished.emit("error", f"Analysis failed: {analysis_results['error']}")
                return

            # 3. 生成报告 (使用英文源文本)
            self.progress.emit(70, "Generating reports...")
            generate_reports(self.input_path, self.output_folder, analysis_results, **self.options)

            self.progress.emit(100, "Completed!")
            self.finished.emit("success", self.output_folder)
        except Exception as e:
            self.finished.emit("error", f"A critical error occurred: {e}")

class BatchReportDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(500)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # 在初始化时调用，设置所有文本
        self.worker = None

        self._populate_initial_paths()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 1. 文件选择区
        self.file_group = QGroupBox()
        form_layout = QFormLayout()
        self.input_path_edit = QLineEdit()
        self.output_folder_edit = QLineEdit()
        self.browse_input_button = QPushButton()
        self.browse_output_button = QPushButton()

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input_path_edit)
        input_layout.addWidget(self.browse_input_button)
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_folder_edit)
        output_layout.addWidget(self.browse_output_button)

        self.input_label = QLabel()  # 创建空标签
        self.output_label = QLabel() # 创建空标签
        form_layout.addRow(self.input_label, input_layout)
        form_layout.addRow(self.output_label, output_layout)
        self.file_group.setLayout(form_layout)
        layout.addWidget(self.file_group)

        # 2. 报告选项区
        self.options_group = QGroupBox()
        options_layout = QHBoxLayout()
        self.csv_checkbox = QCheckBox()
        self.csv_checkbox.setChecked(True)
        self.pdf_checkbox = QCheckBox()
        self.pdf_checkbox.setChecked(True)
        self.word_checkbox = QCheckBox()
        self.word_checkbox.setChecked(True)
        options_layout.addWidget(self.csv_checkbox)
        options_layout.addWidget(self.pdf_checkbox)
        options_layout.addWidget(self.word_checkbox)
        self.options_group.setLayout(options_layout)
        layout.addWidget(self.options_group)

        # 3. 进度与控制区
        self.start_button = QPushButton()
        self.progress_bar = QProgressBar()
        self.status_label = QLabel()
        layout.addWidget(self.start_button)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

    def _connect_signals(self):
        self.browse_input_button.clicked.connect(self._select_input_file)
        self.browse_output_button.clicked.connect(self._select_output_folder)
        self.start_button.clicked.connect(self._start_processing)

    def changeEvent(self, event):
        """新增：响应语言变化事件"""
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """新增：重新翻译所有UI文本"""
        self.setWindowTitle(self.tr("Generate Analysis Report"))

        # 文件组
        self.file_group.setTitle(self.tr("Files and Paths"))
        self.input_label.setText(self.tr("Input Spectrum File:"))
        self.output_label.setText(self.tr("Report Output Folder:"))
        self.browse_input_button.setText(self.tr("Browse..."))
        self.browse_output_button.setText(self.tr("Browse..."))

        # 选项组
        self.options_group.setTitle(self.tr("Report Options"))
        self.csv_checkbox.setText(self.tr("Generate CSV Data Table"))
        self.pdf_checkbox.setText(self.tr("Generate PDF Report"))
        self.word_checkbox.setText(self.tr("Generate Word Report"))

        # 控制区
        self.start_button.setText(self.tr("Start Report Generation"))
        self.status_label.setText(self.tr("Please select files and folders."))

    def _populate_initial_paths(self):
        """用设置中存储的默认路径填充输入框"""
        default_load = self.app_settings.get('default_load_path', '')
        default_save = self.app_settings.get('default_save_path', '')
        self.input_path_edit.setText(default_load)
        self.output_folder_edit.setText(default_save)

    def _select_input_file(self):
        start_path = self.input_path_edit.text() or self.app_settings.get('default_load_path', os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Spectrum File"),
            start_path,
            "Data Files (*.xlsx *.xls *.csv *.txt)"
        )
        if path:
            self.input_path_edit.setText(path)
            self.output_folder_edit.setText(os.path.dirname(path))

    def _select_output_folder(self):
        start_path = self.output_folder_edit.text() or self.app_settings.get('default_save_path',
                                                                             os.path.expanduser("~"))
        path = QFileDialog.getExistingDirectory(self, self.tr("Select Report Output Folder"), start_path)
        if path:
            self.output_folder_edit.setText(path)

    def _start_processing(self):
        input_path = self.input_path_edit.text()
        output_folder = self.output_folder_edit.text()

        if not input_path or not output_folder:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Please provide paths for both input file and output folder."))
            return

        options = {
            'generate_csv': self.csv_checkbox.isChecked(),
            'generate_pdf': self.pdf_checkbox.isChecked(),
            'generate_word': self.word_checkbox.isChecked()
        }

        self.start_button.setEnabled(False)
        self.worker = ReportWorker(input_path, output_folder, options)
        self.worker.progress.connect(self._update_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.status_label.setText(self.tr(message)) # 翻译来自线程的消息

    def _on_finished(self, status, message):
        self.start_button.setEnabled(True)
        if status == "success":
            QMessageBox.information(self, self.tr("Complete"), self.tr("Report generated successfully!"))
        else:
            QMessageBox.critical(self, self.tr("Failed"), self.tr("Processing failed: {0}").format(message))