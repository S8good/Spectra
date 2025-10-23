# nanosense/gui/performance_dialog.py

import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QPushButton, QDialogButtonBox,
                             QLabel, QTextEdit, QFormLayout, QMessageBox, QGroupBox, QDoubleSpinBox)
from PyQt5.QtCore import QEvent


class PerformanceDialog(QDialog):
    """
    一个统一的窗口，用于计算和显示 LOB, LOD, 和 LOQ。
    """

    def __init__(self, main_window, parent=None, slope=None):
        super().__init__(parent)
        self.main_window = main_window
        self.initial_slope = slope  # 接收从校准曲线传入的斜率

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()

        if self.initial_slope is not None:
            self.slope_input.setValue(self.initial_slope)

    def _init_ui(self):
        self.setMinimumWidth(450)
        main_layout = QVBoxLayout(self)

        # --- 数据输入区 ---
        input_group = QGroupBox()
        input_layout = QFormLayout(input_group)

        self.blank_values_input = QTextEdit()
        self.low_conc_values_input = QTextEdit()
        self.slope_input = QDoubleSpinBox()
        self.slope_input.setDecimals(5)
        self.slope_input.setRange(-1e12, 1e12)

        self.blank_label = QLabel()
        self.low_conc_label = QLabel()
        self.slope_label = QLabel()

        input_layout.addRow(self.blank_label, self.blank_values_input)
        input_layout.addRow(self.low_conc_label, self.low_conc_values_input)
        input_layout.addRow(self.slope_label, self.slope_input)

        main_layout.addWidget(input_group)

        # --- 控制与结果区 ---
        self.calculate_button = QPushButton()
        main_layout.addWidget(self.calculate_button)

        result_group = QGroupBox()
        result_layout = QFormLayout(result_group)

        self.mean_blank_label = QLabel("N/A")
        self.sd_blank_label = QLabel("N/A")
        self.lob_label = QLabel("N/A")
        self.lod_cal_label = QLabel("N/A")  # 基于校准曲线
        self.loq_cal_label = QLabel("N/A")  # 基于校准曲线
        self.lod_low_conc_label = QLabel("N/A")  # 基于低浓度样品

        self.mean_blank_title = QLabel()
        self.sd_blank_title = QLabel()
        self.lob_title = QLabel()
        self.lod_cal_title = QLabel()
        self.loq_cal_title = QLabel()
        self.lod_low_conc_title = QLabel()

        result_layout.addRow(self.mean_blank_title, self.mean_blank_label)
        result_layout.addRow(self.sd_blank_title, self.sd_blank_label)
        result_layout.addRow(self.lob_title, self.lob_label)
        result_layout.addRow(self.lod_cal_title, self.lod_cal_label)
        result_layout.addRow(self.loq_cal_title, self.loq_cal_label)
        result_layout.addRow(self.lod_low_conc_title, self.lod_low_conc_label)

        main_layout.addWidget(result_group)

        self.save_to_db_button = QPushButton()
        self.save_to_db_button.setEnabled(False)
        main_layout.addWidget(self.save_to_db_button)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Close)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.calculate_button.clicked.connect(self._perform_calculations)
        self.save_to_db_button.clicked.connect(self._save_results_to_db)
        self.button_box.rejected.connect(self.reject)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Detection Performance (LOB, LOD, LOQ)"))

        self.blank_label.setText(self.tr("Blank Responses (comma-separated):"))
        self.low_conc_label.setText(self.tr("Low Conc. Responses (optional):"))
        self.slope_label.setText(self.tr("Sensitivity / Slope (S):"))
        self.calculate_button.setText(self.tr("Calculate"))

        self.mean_blank_title.setText(self.tr("Mean of Blanks:"))
        self.sd_blank_title.setText(self.tr("Std Dev of Blanks (SD_blank):"))
        self.lob_title.setText(self.tr("LOB (nm):"))
        self.lod_cal_title.setText(self.tr("LOD (nM, from Calibration):"))
        self.loq_cal_title.setText(self.tr("LOQ (nM, from Calibration):"))
        self.lod_low_conc_title.setText(self.tr("LOD (nm, from Low Conc. Sample):"))

        self.save_to_db_button.setText(self.tr("Save Results to Database"))
        self.button_box.button(QDialogButtonBox.Close).setText(self.tr("Close"))

    def _parse_input(self, text_edit):
        text = text_edit.toPlainText().strip()
        if not text:
            return []
        try:
            values_str = text.replace(',', ' ').replace('\\n', ' ').split()
            return [float(v) for v in values_str if v]
        except ValueError:
            return None

    def _perform_calculations(self):
        blank_values = self._parse_input(self.blank_values_input)
        low_conc_values = self._parse_input(self.low_conc_values_input)
        slope = self.slope_input.value()

        if blank_values is None or (low_conc_values is None and low_conc_values != []):
            QMessageBox.critical(self, self.tr("Input Error"),
                                 self.tr("Invalid input. Please ensure all entries are numbers."))
            return

        if len(blank_values) < 3:
            QMessageBox.warning(self, self.tr("Input Error"),
                                self.tr("Please enter at least three blank sample values."))
            return

        # --- Calculations ---
        mean_blank = np.mean(blank_values)
        sd_blank = np.std(blank_values, ddof=1)
        lob = mean_blank + 1.645 * sd_blank

        self.mean_blank_label.setText(f"{mean_blank:.4f}")
        self.sd_blank_label.setText(f"{sd_blank:.4f}")
        self.lob_label.setText(f"{lob:.4f}")

        # LOD/LOQ from calibration
        if slope != 0:
            lod_cal = (3 * sd_blank) / abs(slope)
            loq_cal = (10 * sd_blank) / abs(slope)
            self.lod_cal_label.setText(f"{lod_cal:.4g}")
            self.loq_cal_label.setText(f"{loq_cal:.4g}")
        else:
            self.lod_cal_label.setText(self.tr("N/A (Slope is zero)"))
            self.loq_cal_label.setText(self.tr("N/A (Slope is zero)"))

        # LOD from low concentration sample
        if len(low_conc_values) >= 3:
            sd_low_conc = np.std(low_conc_values, ddof=1)
            lod_low_conc = lob + 1.645 * sd_low_conc
            self.lod_low_conc_label.setText(f"{lod_low_conc:.4f}")
        else:
            self.lod_low_conc_label.setText(self.tr("N/A (Not enough data)"))

        self.save_to_db_button.setEnabled(True)

    def _save_results_to_db(self):
        if not self.main_window or not self.main_window.db_manager:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Database is not available."))
            return

        try:
            experiment_id = self.main_window.get_or_create_current_experiment_id()
            if experiment_id is None: return

            results_data = {
                'LOB_nm': self.lob_label.text(),
                'LOD_nM_from_Calibration': self.lod_cal_label.text(),
                'LOQ_nM_from_Calibration': self.loq_cal_label.text(),
                'LOD_nm_from_Low_Conc': self.lod_low_conc_label.text(),
                'Mean_blank': self.mean_blank_label.text(),
                'SD_blank': self.sd_blank_label.text(),
                'Sensitivity_used': self.slope_input.value()
            }

            self.main_window.db_manager.save_analysis_result(
                experiment_id=experiment_id,
                analysis_type='Detection_Performance',
                result_data=results_data
            )

            QMessageBox.information(self, self.tr("Success"),
                                    self.tr("Detection performance results have been saved to the database."))
            self.save_to_db_button.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, self.tr("Database Error"),
                                 self.tr("An error occurred while saving to the database:\\n{0}").format(str(e)))