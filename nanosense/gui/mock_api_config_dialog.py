# nanosense/gui/mock_api_config_dialog.py
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox,
                             QPushButton, QDialogButtonBox, QGroupBox,
                             QLabel, QDoubleSpinBox, QSpinBox)
from PyQt5.QtCore import QEvent

class MockAPIConfigDialog(QDialog):
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.settings = current_settings.copy() # 使用传入设置的副本
        self._init_ui()
        self._connect_signals()
        self._populate_initial_values()
        self._retranslate_ui()
        self._on_mode_changed() # 初始化时根据模式更新UI显隐

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # 模式选择
        form_layout = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_label = QLabel()
        form_layout.addRow(self.mode_label, self.mode_combo)
        main_layout.addLayout(form_layout)

        # 静态峰参数
        self.static_group = QGroupBox()
        static_layout = QFormLayout(self.static_group)
        self.static_pos_spin = QDoubleSpinBox(); self.static_pos_spin.setRange(200, 1200)
        self.static_amp_spin = QDoubleSpinBox(); self.static_amp_spin.setRange(0, 65535)
        self.static_width_spin = QDoubleSpinBox(); self.static_width_spin.setRange(1, 100)
        self.noise_spin = QDoubleSpinBox(); self.noise_spin.setRange(0, 1000)
        self.static_pos_label = QLabel(); self.static_amp_label = QLabel()
        self.static_width_label = QLabel(); self.noise_label = QLabel()
        static_layout.addRow(self.static_pos_label, self.static_pos_spin)
        static_layout.addRow(self.static_amp_label, self.static_amp_spin)
        static_layout.addRow(self.static_width_label, self.static_width_spin)
        static_layout.addRow(self.noise_label, self.noise_spin)
        main_layout.addWidget(self.static_group)

        # 动态(动力学)参数
        self.dynamic_group = QGroupBox()
        dynamic_layout = QFormLayout(self.dynamic_group)
        self.dyn_pos_spin = QDoubleSpinBox(); self.dyn_pos_spin.setRange(200, 1200)
        self.dyn_shift_spin = QDoubleSpinBox(); self.dyn_shift_spin.setRange(-100, 100)
        self.dyn_base_spin = QSpinBox(); self.dyn_base_spin.setRange(0, 600)
        self.dyn_assoc_spin = QSpinBox(); self.dyn_assoc_spin.setRange(1, 600)
        self.dyn_dissoc_spin = QSpinBox(); self.dyn_dissoc_spin.setRange(1, 600)
        self.dyn_pos_label = QLabel(); self.dyn_shift_label = QLabel()
        self.dyn_base_label = QLabel(); self.dyn_assoc_label = QLabel(); self.dyn_dissoc_label = QLabel()
        dynamic_layout.addRow(self.dyn_pos_label, self.dyn_pos_spin)
        dynamic_layout.addRow(self.dyn_shift_label, self.dyn_shift_spin)
        dynamic_layout.addRow(self.dyn_base_label, self.dyn_base_spin)
        dynamic_layout.addRow(self.dyn_assoc_label, self.dyn_assoc_spin)
        dynamic_layout.addRow(self.dyn_dissoc_label, self.dyn_dissoc_spin)
        main_layout.addWidget(self.dynamic_group)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self):
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.button_box.accepted.connect(self._save_and_accept)
        self.button_box.rejected.connect(self.reject)

    def changeEvent(self, event):
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr("Mock API Configuration"))
        self.mode_label.setText(self.tr("Simulation Mode:"))
        current_data = self.mode_combo.currentData()
        self.mode_combo.clear()
        self.mode_combo.addItem(self.tr("Dynamic Kinetics"), "dynamic")
        self.mode_combo.addItem(self.tr("Static Peak"), "static")
        self.mode_combo.addItem(self.tr("Noisy Baseline"), "noisy_baseline")
        index = self.mode_combo.findData(current_data)
        if index != -1: self.mode_combo.setCurrentIndex(index)

        self.static_group.setTitle(self.tr("Static Peak Parameters"))
        self.static_pos_label.setText(self.tr("Peak Position (nm):"))
        self.static_amp_label.setText(self.tr("Amplitude (counts):"))
        self.static_width_label.setText(self.tr("Sigma (nm):"))
        self.noise_label.setText(self.tr("Noise Level (counts):"))

        self.dynamic_group.setTitle(self.tr("Dynamic Kinetics Parameters"))
        self.dyn_pos_label.setText(self.tr("Initial Position (nm):"))
        self.dyn_shift_label.setText(self.tr("Total Shift (nm):"))
        self.dyn_base_label.setText(self.tr("Baseline Duration (s):"))
        self.dyn_assoc_label.setText(self.tr("Association Duration (s):"))
        self.dyn_dissoc_label.setText(self.tr("Dissociation Duration (s):"))

        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("Cancel"))

    def _populate_initial_values(self):
        config = self.settings.get('mock_api_config', {})
        index = self.mode_combo.findData(config.get('mode', 'dynamic'))
        if index != -1: self.mode_combo.setCurrentIndex(index)

        self.static_pos_spin.setValue(config.get('static_peak_pos', 650.0))
        self.static_amp_spin.setValue(config.get('static_peak_amp', 15000.0))
        self.static_width_spin.setValue(config.get('static_peak_width', 10.0))
        self.noise_spin.setValue(config.get('noise_level', 50.0))

        self.dyn_pos_spin.setValue(config.get('dynamic_initial_pos', 650.0))
        self.dyn_shift_spin.setValue(config.get('dynamic_shift_total', 10.0))
        self.dyn_base_spin.setValue(config.get('dynamic_baseline_duration', 5))
        self.dyn_assoc_spin.setValue(config.get('dynamic_assoc_duration', 20))
        self.dyn_dissoc_spin.setValue(config.get('dynamic_dissoc_duration', 30))

    def _on_mode_changed(self):
        mode = self.mode_combo.currentData()
        self.static_group.setVisible(mode == 'static')
        self.dynamic_group.setVisible(mode == 'dynamic')
        # 如果是 noisy_baseline，两者都隐藏
        if mode == 'noisy_baseline':
             self.noise_label.setText(self.tr("Noise Level (counts):"))
        else:
             self.noise_label.setText(self.tr("Noise Level (counts, superimposed):"))

    def _save_and_accept(self):
        config = self.settings.get('mock_api_config', {})
        config['mode'] = self.mode_combo.currentData()
        config['static_peak_pos'] = self.static_pos_spin.value()
        config['static_peak_amp'] = self.static_amp_spin.value()
        config['static_peak_width'] = self.static_width_spin.value()
        config['noise_level'] = self.noise_spin.value()
        config['dynamic_initial_pos'] = self.dyn_pos_spin.value()
        config['dynamic_shift_total'] = self.dyn_shift_spin.value()
        config['dynamic_baseline_duration'] = self.dyn_base_spin.value()
        config['dynamic_assoc_duration'] = self.dyn_assoc_spin.value()
        config['dynamic_dissoc_duration'] = self.dyn_dissoc_spin.value()
        self.settings['mock_api_config'] = config
        self.accept()

    def get_settings(self):
        return self.settings