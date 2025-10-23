# nanosense/gui/realtime_noise_setup_dialog.py

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QDialogButtonBox,
                             QLabel, QSpinBox, QFormLayout, QWidget, QDoubleSpinBox)
from PyQt5.QtCore import QTimer, QEvent
import pyqtgraph as pg

class RealTimeNoiseSetupDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.num_spectra = 20  # 默认值
        self.interval = 0.0

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()

        # 用于实时预览的定时器
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(100) # 每100ms刷新一次
        self.preview_timer.timeout.connect(self._update_preview)
        self.preview_timer.start()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        self.setMinimumSize(600, 500)

        # 预览图
        self.preview_plot = pg.PlotWidget()
        self.preview_curve = self.preview_plot.plot(pen='c')
        main_layout.addWidget(self.preview_plot, 1)

        # 设置区域
        settings_widget = QWidget()
        settings_layout = QFormLayout(settings_widget)

        self.spectra_count_spinbox = QSpinBox()
        self.spectra_count_spinbox.setRange(10, 500)
        self.spectra_count_spinbox.setValue(self.num_spectra)
        self.spectra_count_label = QLabel()

        self.interval_spinbox = QDoubleSpinBox()
        self.interval_spinbox.setRange(0.0, 60.0)
        self.interval_spinbox.setDecimals(2)
        self.interval_spinbox.setValue(self.interval)
        self.interval_spinbox.setSuffix(" s")
        self.interval_label = QLabel()

        settings_layout.addRow(self.spectra_count_label, self.spectra_count_spinbox)
        settings_layout.addRow(self.interval_label, self.interval_spinbox)

        main_layout.addWidget(settings_widget)

        # 按钮
        self.button_box = QDialogButtonBox()
        self.start_button = self.button_box.addButton(QDialogButtonBox.Apply)
        self.cancel_button = self.button_box.addButton(QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.start_button.clicked.connect(self._start_and_accept)
        self.cancel_button.clicked.connect(self.reject)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Real-time Noise Analysis Setup"))
        self.preview_plot.setTitle(self.tr("Live Blank Sample Preview"), color='#90A4AE', size='12pt')
        self.preview_plot.setLabel('bottom', self.tr('Wavelength (nm)'))
        self.preview_plot.setLabel('left', self.tr('Intensity'))
        self.spectra_count_label.setText(self.tr("Number of spectra to collect:"))
        self.interval_label.setText(self.tr("Acquisition Interval (s):"))
        self.start_button.setText(self.tr("Start Analysis"))
        self.cancel_button.setText(self.tr("Cancel"))

    def _update_preview(self):
        if self.controller:
            wavelengths, spectrum = self.controller.get_spectrum()
            self.preview_curve.setData(wavelengths, spectrum)

    def _start_and_accept(self):
        self.num_spectra = self.spectra_count_spinbox.value()
        self.interval = self.interval_spinbox.value()
        self.accept()

    def get_settings(self):
        return self.num_spectra, self.interval

    def closeEvent(self, event):
        self.preview_timer.stop() # 关闭窗口时停止定时器
        super().closeEvent(event)