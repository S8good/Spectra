# nanosense/gui/data_analysis_dialog.py

import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QGroupBox,
                             QProgressBar, QLabel, QMessageBox, QListWidget, QListWidgetItem, QDialogButtonBox,
                             QCheckBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QEvent  # 导入 QEvent

from nanosense.utils.data_processor import export_grouped_data, generate_summary_reports, aggregate_batch_files
from .preprocessing_dialog import PreprocessingDialog
from ..utils.plot_generator import generate_plots_for_point


class AnalysisWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str, list)

    def __init__(self, grouped_data, output_folder, selected_points, options, preprocessing_params, app_settings): # 增加 app_settings
        super().__init__()
        self.grouped_data = grouped_data
        self.output_folder = output_folder
        self.selected_points = selected_points
        self.options = options
        self.preprocessing_params = preprocessing_params
        self.app_settings = app_settings # 存储设置

    def run(self):
        report_log = []
        try:
            self.progress.emit(30, "Data loaded, starting analysis...")
            if self.options.get('export_excel', False):
                self.progress.emit(40, "Exporting grouped Excel files...")
                export_grouped_data(self.output_folder, self.grouped_data, self.selected_points)
                report_log.append("Grouped Excel export complete.")
            if self.options.get('export_summaries', False):
                self.progress.emit(50, "Calculating peak positions and generating summary tables...")
                # 将 app_settings 传递给下游函数
                generate_summary_reports(self.output_folder, self.grouped_data, self.selected_points,
                                         self.preprocessing_params, self.app_settings)
                report_log.append("Peak position/shift summary generation complete.")
            if self.options.get('generate_plots', False):
                total_points = len(self.selected_points)
                for i, point_name in enumerate(self.selected_points):
                    progress_val = 70 + int(30 * (i + 1) / total_points)
                    self.progress.emit(progress_val, f"Generating plots ({i + 1}/{total_points}): {point_name}...")
                    if point_name in self.grouped_data:
                        generate_plots_for_point(point_name, self.grouped_data[point_name], self.output_folder,
                                                 self.preprocessing_params)
                report_log.append("Plot generation complete.")
            self.progress.emit(100, "All tasks completed!")
            self.finished.emit(self.output_folder, report_log)
        except Exception as e:
            self.finished.emit(None, [f"A critical error occurred: {e}"])

class DataAnalysisDialog(QDialog):
    file_processed_signal = pyqtSignal(object, list)

    def __init__(self, parent=None, initial_folder=None):
        super().__init__(parent)
        self.setMinimumWidth(600)

        if parent and hasattr(parent, 'app_settings'):
            self.app_settings = self.parent().app_settings
        else:
            self.app_settings = {}

        self.processed_data = None
        self.worker = None
        self.input_folder_path = initial_folder
        self.preprocessing_params = {
            'als_lambda': 1e9, 'als_p': 0.01, 'sg_window_coarse': 14,
            'sg_polyorder_coarse': 3, 'sg_window_fine': 8, 'sg_polyorder_fine': 3
        }

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # 设置初始文本

        if self.input_folder_path:
            self.input_path_label.setText(f"Folder: {os.path.basename(self.input_folder_path)}")
            self._process_folder(self.input_folder_path)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Input Source
        self.file_group = QGroupBox()
        file_layout = QHBoxLayout(self.file_group)
        self.input_path_label = QLabel()
        self.browse_button = QPushButton()
        file_layout.addWidget(self.input_path_label, 1)
        file_layout.addWidget(self.browse_button)
        layout.addWidget(self.file_group)

        # Preprocessing Settings
        self.settings_group = QGroupBox()
        settings_layout = QHBoxLayout(self.settings_group)
        self.settings_button = QPushButton()
        self.settings_button.setEnabled(False)
        settings_layout.addWidget(self.settings_button)
        layout.addWidget(self.settings_group)

        # Measurement Point Selection
        self.result_group = QGroupBox()
        result_layout = QVBoxLayout(self.result_group)
        self.point_list_widget = QListWidget()
        result_layout.addWidget(self.point_list_widget)
        layout.addWidget(self.result_group)

        # Export Task Selection
        self.options_group = QGroupBox()
        options_layout = QVBoxLayout(self.options_group)
        self.export_excel_check = QCheckBox()
        self.export_excel_check.setChecked(True)
        self.export_summaries_check = QCheckBox()
        self.export_summaries_check.setChecked(True)
        self.generate_plots_check = QCheckBox()
        self.generate_plots_check.setChecked(True)
        options_layout.addWidget(self.export_excel_check)
        options_layout.addWidget(self.export_summaries_check)
        options_layout.addWidget(self.generate_plots_check)
        layout.addWidget(self.options_group)

        # Controls
        self.run_button = QPushButton()
        self.run_button.setEnabled(False)
        layout.addWidget(self.run_button)
        self.progress_bar = QProgressBar()
        self.status_label = QLabel()
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Close)
        layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.browse_button.clicked.connect(self._select_input_source)
        self.settings_button.clicked.connect(self._open_preprocessing_settings)
        self.run_button.clicked.connect(self._run_tasks)
        self.button_box.rejected.connect(self.reject)
        self.file_processed_signal.connect(self._on_file_processed)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Batch Data Analysis & Reorganization"))
        self.file_group.setTitle(self.tr("1. Input Source"))
        self.input_path_label.setText(self.tr("Please select a folder..."))
        self.browse_button.setText(self.tr("Browse Folder..."))

        self.settings_group.setTitle(self.tr("2. Preprocessing Settings"))
        self.settings_button.setText(self.tr("Adjust Preprocessing Parameters..."))

        self.result_group.setTitle(self.tr("3. Select Measurement Points"))

        self.options_group.setTitle(self.tr("4. Select Export Tasks"))
        self.export_excel_check.setText(self.tr("Export reorganized group data (point_*.xlsx)"))
        self.export_summaries_check.setText(self.tr("Export peak position & shift summary tables (peak_*.xlsx)"))
        self.generate_plots_check.setText(self.tr("Generate PNG analysis plots"))

        self.run_button.setText(self.tr("Execute Tasks"))
        self.status_label.setText(self.tr("Please select a folder first."))
        self.button_box.button(QDialogButtonBox.Close).setText(self.tr("Close"))

    def _select_input_source(self):
        default_load_path = self.app_settings.get('default_load_path', os.path.expanduser("~"))
        path = QFileDialog.getExistingDirectory(self, self.tr("Select folder containing spectrum files"),
                                                default_load_path)
        if path:
            self._process_folder(path)

    def _process_folder(self, folder_path):
        self.input_folder_path = folder_path
        self.input_path_label.setText(f"{self.tr('Folder:')} {os.path.basename(folder_path)}")
        self.point_list_widget.clear()
        self.processed_data = None
        self.run_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        data, log = aggregate_batch_files(folder_path)
        self.file_processed_signal.emit(data, log)

    def _on_file_processed(self, grouped_data, report_log):
        if grouped_data is None:
            QMessageBox.critical(self, self.tr("File Read Error"), "\n".join(report_log))
            self.status_label.setText(self.tr("Folder processing failed, please check file format."))
            return

        self.processed_data = grouped_data
        for point_name in sorted(self.processed_data.keys()):
            item = QListWidgetItem(point_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.point_list_widget.addItem(item)

        if self.point_list_widget.count() > 0:
            self.run_button.setEnabled(True)
            self.settings_button.setEnabled(True)
            self.status_label.setText(
                self.tr("Folder loaded successfully, {0} measurement points identified.").format(len(grouped_data)))

    def _open_preprocessing_settings(self):
        if not self.processed_data:
            QMessageBox.warning(self, self.tr("Info"), self.tr("Please load data successfully first."))
            return
        sample_point_name = list(self.processed_data.keys())[0]
        sample_df = self.processed_data[sample_point_name]
        sample_wavelengths = sample_df.iloc[:, 0].values
        if sample_df.shape[1] > 3:
            sample_intensity = sample_df.iloc[:, 3].values
        else:
            QMessageBox.warning(
                self,
                self.tr("Data Error"),
                self.tr("Sample data must contain at least four columns to preview the absorbance trace.")
            )
            return
        dialog = PreprocessingDialog(sample_wavelengths, sample_intensity, self.preprocessing_params, self)
        if dialog.exec_() == QDialog.Accepted:
            self.preprocessing_params = dialog.get_params()
            QMessageBox.information(self, self.tr("Success"), self.tr("New preprocessing parameters have been saved!"))

    def _run_tasks(self):
        if not self.processed_data: return
        selected_points = [self.point_list_widget.item(i).text() for i in range(self.point_list_widget.count()) if
                           self.point_list_widget.item(i).checkState() == Qt.Checked]
        if not selected_points: QMessageBox.warning(self, self.tr("Info"),
                                                    self.tr("Please check at least one measurement point.")); return

        options = {
            'export_excel': self.export_excel_check.isChecked(),
            'export_summaries': self.export_summaries_check.isChecked(),
            'generate_plots': self.generate_plots_check.isChecked()
        }
        if not any(options.values()): QMessageBox.warning(self, self.tr("Info"),
                                                          self.tr("Please check at least one task.")); return

        output_folder = self.input_folder_path
        if not output_folder: return

        self.run_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.settings_button.setEnabled(False)

        self.worker = AnalysisWorker(self.processed_data, output_folder, selected_points, options,
                                     self.preprocessing_params, self.app_settings)
        self.worker.progress.connect(self._update_progress)
        self.worker.finished.connect(self._on_tasks_finished)
        self.worker.start()


    def _update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.status_label.setText(self.tr(message))  # 翻译进度信息

    def _on_tasks_finished(self, output_folder, report_log):
        self.run_button.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.status_label.setText(self.tr(report_log[-1] if report_log else "Done"))
        if output_folder:
            QMessageBox.information(self, self.tr("Done"),
                                    self.tr("All tasks are complete!\nResults have been saved to:\n{0}").format(
                                        output_folder))
        else:
            QMessageBox.critical(self, self.tr("Failed"),
                                 self.tr("Processing failed:\n{0}").format(
                                     report_log[-1] if report_log else "Unknown error"))
