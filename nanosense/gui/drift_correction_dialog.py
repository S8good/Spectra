# nanosense/gui/drift_correction_dialog.py

import numpy as np
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox
from PyQt5.QtCore import QEvent  # 导入 QEvent
import pyqtgraph as pg

from nanosense.algorithms.kinetics import correct_drift


class DriftCorrectionDialog(QDialog):
    def __init__(self, time_data, y_data, parent=None):
        super().__init__(parent)
        self.setGeometry(200, 200, 700, 500)

        self.time_data = np.array(time_data)
        self.y_data = np.array(y_data)
        self.corrected_y_data = None

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()  # 设置初始文本

    def _init_ui(self):
        """
        创建并布局所有UI控件。
        """
        layout = QVBoxLayout(self)

        self.plot = pg.PlotWidget()

        # 绘制原始数据和校正后数据的预览
        self.plot.plot(self.time_data, self.y_data, pen='w', name="Raw Data")
        self.corrected_curve = self.plot.plot(pen='g', name="Corrected Data")

        # 创建两条可拖拽的垂直线
        initial_pos1 = self.time_data[int(len(self.time_data) * 0.1)]
        initial_pos2 = self.time_data[int(len(self.time_data) * 0.2)]
        self.line1 = pg.InfiniteLine(pos=initial_pos1, angle=90, movable=True, pen='y')
        self.line2 = pg.InfiniteLine(pos=initial_pos2, angle=90, movable=True, pen='y')
        self.plot.addItem(self.line1)
        self.plot.addItem(self.line2)
        layout.addWidget(self.plot)

        # 创建按钮
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton()  # 创建空按钮
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_layout.addWidget(self.apply_button)
        button_layout.addStretch()
        button_layout.addWidget(self.button_box)
        layout.addLayout(button_layout)

    def _connect_signals(self):
        """
        连接所有控件的信号与槽。
        """
        self.apply_button.clicked.connect(self._update_correction_preview)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def changeEvent(self, event):
        """
        响应语言变化事件。
        """
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """
        重新翻译此控件内的所有UI文本。
        """
        self.setWindowTitle(self.tr("Kinetics Curve Drift Correction"))
        self.plot.setTitle(self.tr("Drag the yellow vertical lines to select the baseline region"))
        self.plot.setLabel('bottom', self.tr('Time (s)'))
        self.plot.setLabel('left', self.tr('Peak Wavelength (nm)'))
        self.apply_button.setText(self.tr("Preview Correction"))
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("Cancel"))

    def _update_correction_preview(self):
        """更新校正后的数据预览。"""
        pos1 = self.line1.value()
        pos2 = self.line2.value()
        start_time, end_time = min(pos1, pos2), max(pos1, pos2)

        self.corrected_y_data = correct_drift(self.time_data, self.y_data, start_time, end_time)
        self.corrected_curve.setData(self.time_data, self.corrected_y_data)
        print(self.tr("Previewing correction using baseline from {0:.2f}s to {1:.2f}s.").format(start_time, end_time))

    def get_corrected_data(self):
        """在对话框关闭后，由主窗口调用此方法来获取最终结果。"""
        self._update_correction_preview()
        return self.corrected_y_data