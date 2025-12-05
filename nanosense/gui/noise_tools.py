# nanosense/gui/noise_tools.py
import os
import time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QPushButton, QMessageBox,
                             QLabel, QFormLayout, QGroupBox, QDesktopWidget, QDialogButtonBox)
from PyQt5.QtCore import QObject, pyqtSignal, QEvent, Qt
import pyqtgraph as pg


class RealTimeNoiseWorker(QObject):
    finished = pyqtSignal(str, object, object, float)  # folder_path, wavelengths, noise_spectrum, average_noise
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, controller, num_spectra, output_folder, interval):
        super().__init__()
        self.controller = controller
        self.num_spectra = num_spectra
        self.output_folder = output_folder
        self.interval = interval
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        try:
            # 1. 创建唯一的带时间戳的结果子文件夹
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            results_dir = os.path.join(self.output_folder, f"Noise_Analysis_{timestamp}")
            os.makedirs(results_dir)
            raw_data_dir = os.path.join(results_dir, "raw_data")
            os.makedirs(raw_data_dir)

            spectra_list = []
            wavelengths = self.controller.wavelengths
            self.progress.emit(0, self.tr("Starting real-time acquisition..."))

            # 2. 循环采集并保存原始数据
            for i in range(self.num_spectra):
                if not self._is_running:
                    self.error.emit(self.tr("Task was aborted by the user."))
                    return

                _, spectrum = self.controller.get_spectrum()
                spectra_list.append(spectrum)

                # 保存单条光谱数据
                df = pd.DataFrame({'Wavelength (nm)': wavelengths, 'Intensity': spectrum})
                df.to_csv(os.path.join(raw_data_dir, f"spectrum_{i + 1:03d}.csv"), index=False)

                if self.interval > 0:
                    time.sleep(self.interval)

                progress_val = int(((i + 1) / self.num_spectra) * 100)
                self.progress.emit(progress_val,
                                   self.tr("Acquiring spectra ({0}/{1})...").format(i + 1, self.num_spectra))

            self.progress.emit(95, self.tr("Aggregating raw data..."))
            summary_data_dict = {'Wavelength (nm)': wavelengths}
            for i, spectrum_data in enumerate(spectra_list):
                summary_data_dict[f'Intensity_Run_{i + 1}'] = spectrum_data

            summary_df = pd.DataFrame(summary_data_dict)
            summary_file_path = os.path.join(raw_data_dir, "all_raw_spectra.xlsx")
            summary_df.to_excel(summary_file_path, index=False, engine='openpyxl')

            # 3. 核心计算
            self.progress.emit(90, self.tr("Calculating noise..."))
            spectra_matrix = np.array(spectra_list).T
            noise_per_wavelength = np.std(spectra_matrix, axis=1, ddof=1)
            average_noise = np.mean(noise_per_wavelength)

            # 4. 保存计算结果
            noise_df = pd.DataFrame({'Wavelength (nm)': wavelengths, 'Standard Deviation': noise_per_wavelength})
            noise_df.to_csv(os.path.join(results_dir, "noise_spectrum.csv"), index=False)

            with open(os.path.join(results_dir, "summary.txt"), 'w') as f:
                f.write(f"Real-time Noise Analysis Summary\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Number of Spectra: {self.num_spectra}\n")
                f.write(f"Acquisition Interval (s): {self.interval}\n")
                f.write(f"Average Noise (Mean of Standard Deviations): {average_noise:.6f}\n")

            # 5. 生成并保存汇总图
            plt.style.use('seaborn-v0_8-darkgrid')
            fig, ax = plt.subplots(figsize=(10, 6))
            for i, spec in enumerate(spectra_list):
                ax.plot(wavelengths, spec, alpha=0.5, label=f'Run {i + 1}' if i < 5 else None)  # 最多显示5个图例
            ax.set_title(f'Overlay of {self.num_spectra} Raw Spectra')
            ax.set_xlabel('Wavelength (nm)')
            ax.set_ylabel('Intensity')
            if self.num_spectra > 5:
                ax.legend(['First 5 runs shown'])
            else:
                ax.legend()
            fig.savefig(os.path.join(results_dir, "raw_spectra_overlay.png"))
            plt.close(fig)

            self.progress.emit(100, self.tr("Completed!"))
            self.finished.emit(results_dir, wavelengths, noise_per_wavelength, average_noise)

        except Exception as e:
            self.error.emit(str(e))


class NoiseResultDialog(QDialog):
    def __init__(self, folder_path, wavelengths, noise_spectrum, average_noise, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.wavelengths = wavelengths
        self.noise_spectrum = noise_spectrum
        self.average_noise = average_noise

        self._init_ui()
        self._retranslate_ui()
        self._populate_data()

    def _init_ui(self):
        self.setGeometry(250, 250, 800, 600)
        main_layout = QVBoxLayout(self)

        self.plot_widget = pg.PlotWidget()
        
        # 根据主题设置背景色和网格
        try:
            from ..utils.config_manager import load_settings
            settings = load_settings()
            theme = settings.get('theme', 'dark')
            if theme == 'light':
                self.plot_widget.setBackground('#F0F0F0')
                self.plot_widget.showGrid(x=True, y=True, alpha=0.1)
                # 浅色主题下使用深色曲线
                self.noise_curve = self.plot_widget.plot(pen=pg.mkPen('k', width=2))
            else:
                self.plot_widget.setBackground('#1F2735')
                self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
                # 深色主题下使用青色曲线
                self.noise_curve = self.plot_widget.plot(pen='c')
        except Exception:
            self.plot_widget.setBackground('#1F2735')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self.noise_curve = self.plot_widget.plot(pen='c')

        self.results_group = QGroupBox()
        results_layout = QFormLayout(self.results_group)
        self.avg_noise_label = QLabel()
        self.avg_noise_label_title = QLabel()
        self.folder_path_label = QLabel(
            f'<a href="file:///{os.path.realpath(self.folder_path)}">{self.folder_path}</a>')
        self.folder_path_label.setOpenExternalLinks(True)
        self.folder_path_label_title = QLabel()
        results_layout.addRow(self.avg_noise_label_title, self.avg_noise_label)
        results_layout.addRow(self.folder_path_label_title, self.folder_path_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.button_box.accepted.connect(self.accept)

        main_layout.addWidget(self.plot_widget)
        main_layout.addWidget(self.results_group)
        main_layout.addWidget(self.button_box)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Real-time Noise Analysis Results"))
        self.plot_widget.setTitle(self.tr("Noise Spectrum (Standard Deviation vs. Wavelength)"))
        self.plot_widget.setLabel('left', self.tr('Standard Deviation (σ)'))
        self.plot_widget.setLabel('bottom', self.tr('Wavelength (nm)'))
        self.results_group.setTitle(self.tr("Calculation Results"))
        self.avg_noise_label_title.setText(self.tr("Average Noise (Mean σ):"))
        self.folder_path_label_title.setText(self.tr("Results saved to:"))
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))

    def _populate_data(self):
        self.noise_curve.setData(self.wavelengths, self.noise_spectrum)
        self.avg_noise_label.setText(f"{self.average_noise:.4f}")