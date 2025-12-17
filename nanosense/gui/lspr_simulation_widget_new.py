# nanosense/gui/lspr_simulation_widget.py
"""
LSPR 传感器仿真主窗口 - 改进的UI设计
三面板布局：左侧参数控制，中间热力图，右侧光谱响应
"""

from PyQt5.QtWidgets import (
    QWidget, QMainWindow, QHBoxLayout, QVBoxLayout, QGroupBox, 
    QPushButton, QLabel, QSlider, QRadioButton, QFileDialog, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QEvent
from PyQt5.QtGui import QFont, QColor
import pyqtgraph as pg
import numpy as np

from nanosense.algorithms.lspr_model import SensorModel
from nanosense.utils.config_manager import load_settings
from nanosense.tools.lspr_export import LSPRDataExporter, get_supported_formats


class LSPRSimulationWidget(QMainWindow):
    """LSPR 传感器仿真主窗口（独立浮动窗口）- 改进UI版本"""
    
    simulation_updated = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LSPR Sensor Simulation")
        self.setGeometry(150, 150, 1500, 850)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | 
                           Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint)
        
        # 初始化数据模型
        self.sensor_model = SensorModel(array_size=15)
        self.data_exporter = LSPRDataExporter()
        self.comparison_window = None
        self.current_selected_pos = (7, 7)
        self.current_material = 'Au'
        
        # 初始化 UI
        self._init_ui()
        self._apply_theme()
        self._run_simulation()
    
    def _init_ui(self):
        """初始化用户界面 - 三面板布局"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(12, 12, 12, 12)
        
        # 左侧：参数控制面板（350px）
        self.control_panel = self._create_control_panel()
        main_layout.addWidget(self.control_panel, 0)
        
        # 中间：热力图（450px）
        self.array_view = self._create_array_view()
        main_layout.addWidget(self.array_view, 1)
        
        # 右侧：光谱响应（450px）
        self.spectrum_view = self._create_spectrum_view()
        main_layout.addWidget(self.spectrum_view, 1)
    
    def _create_control_panel(self) -> QGroupBox:
        """创建左侧参数控制面板 - 完全改进的布局"""
        group = QGroupBox("System Configuration")
        group.setMinimumWidth(340)
        group.setMaximumWidth(380)
        
        layout = QVBoxLayout(group)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # ========== Nanoparticle Material Section ==========
        mat_title = QLabel("Nanoparticle Material")
        mat_title_font = mat_title.font()
        mat_title_font.setPointSize(11)
        mat_title_font.setBold(True)
        mat_title.setFont(mat_title_font)
        layout.addWidget(mat_title)
        
        # 材料按钮
        self.material_buttons = {}
        for material in ['Au', 'Ag', 'Au@Ag']:
            btn = QPushButton(material)
            btn.setCheckable(True)
            btn.setMinimumHeight(32)
            if material == 'Au':
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, m=material: self._select_material(m))
            self.material_buttons[material] = btn
            layout.addWidget(btn)
        
        mat_desc = QLabel("Affects baseline LSPR peak position and bulk sensitivity.")
        mat_desc.setStyleSheet("color: #666; font-size: 9pt;")
        mat_desc.setWordWrap(True)
        layout.addWidget(mat_desc)
        
        # ========== Resonance Mode Section ==========
        layout.addSpacing(10)
        mode_title = QLabel("Resonance Mode")
        mode_title_font = mode_title.font()
        mode_title_font.setPointSize(11)
        mode_title_font.setBold(True)
        mode_title.setFont(mode_title_font)
        layout.addWidget(mode_title)
        
        self.lspr_radio = QRadioButton("Standard LSPR")
        self.lspr_radio.setChecked(True)
        self.lspr_radio.toggled.connect(self._on_mode_changed)
        layout.addWidget(self.lspr_radio)
        
        lspr_desc = QLabel("Random distribution. Broad peaks, lower FOM")
        lspr_desc.setStyleSheet("color: #666; font-size: 8pt;")
        lspr_desc.setContentsMargins(25, 3, 0, 0)
        layout.addWidget(lspr_desc)
        
        self.slr_radio = QRadioButton("Lattice SLR (High-Q)")
        self.slr_radio.toggled.connect(self._on_mode_changed)
        layout.addWidget(self.slr_radio)
        
        slr_desc = QLabel("Periodic array. High-Q narrow peaks, superior LOD")
        slr_desc.setStyleSheet("color: #666; font-size: 8pt;")
        slr_desc.setContentsMargins(25, 3, 0, 0)
        layout.addWidget(slr_desc)
        
        # ========== Environmental Noise Section ==========
        layout.addSpacing(10)
        noise_title = QLabel("Environmental Noise (Shot + Thermal)")
        noise_title_font = noise_title.font()
        noise_title_font.setPointSize(11)
        noise_title_font.setBold(True)
        noise_title.setFont(noise_title_font)
        layout.addWidget(noise_title)
        
        noise_layout = QHBoxLayout()
        self.noise_slider = QSlider(Qt.Horizontal)
        self.noise_slider.setRange(0, 100)
        self.noise_slider.setValue(20)
        self.noise_slider.setMinimumHeight(20)
        
        self.noise_value_label = QLabel("0.2")
        self.noise_value_label.setMinimumWidth(35)
        self.noise_value_label.setAlignment(Qt.AlignCenter)
        
        self.noise_slider.valueChanged.connect(self._on_noise_changed)
        
        noise_layout.addWidget(self.noise_slider)
        noise_layout.addWidget(self.noise_value_label)
        layout.addLayout(noise_layout)
        
        # ========== CHIP STATS Section ==========
        layout.addSpacing(15)
        stats_title = QLabel("CHIP STATS")
        stats_title.setStyleSheet("font-weight: bold; font-size: 10pt; color: #2c3e50;")
        layout.addWidget(stats_title)
        
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(30)
        
        # Active Wells
        active_layout = QVBoxLayout()
        self.active_wells_count = QLabel("225")
        self.active_wells_count.setStyleSheet("font-weight: bold; font-size: 14pt;")
        self.active_wells_count.setAlignment(Qt.AlignCenter)
        active_label = QLabel("Active Wells")
        active_label.setStyleSheet("color: #666; font-size: 9pt;")
        active_label.setAlignment(Qt.AlignCenter)
        active_layout.addWidget(self.active_wells_count)
        active_layout.addWidget(active_label)
        stats_layout.addLayout(active_layout)
        
        # Target Markers
        marker_layout = QVBoxLayout()
        self.target_markers_count = QLabel("10")
        self.target_markers_count.setStyleSheet("font-weight: bold; font-size: 14pt;")
        self.target_markers_count.setAlignment(Qt.AlignCenter)
        marker_label = QLabel("Target Markers")
        marker_label.setStyleSheet("color: #666; font-size: 9pt;")
        marker_label.setAlignment(Qt.AlignCenter)
        marker_layout.addWidget(self.target_markers_count)
        marker_layout.addWidget(marker_label)
        stats_layout.addLayout(marker_layout)
        
        layout.addLayout(stats_layout)
        layout.addStretch()
        
        return group
    
    def _select_material(self, material: str):
        """选择材料"""
        self.current_material = material
        # 更新按钮状态
        for mat, btn in self.material_buttons.items():
            btn.setChecked(mat == material)
        self._on_parameters_changed()
    
    def _on_noise_changed(self, value):
        """噪声滑块变化"""
        noise_value = value / 100.0
        self.noise_value_label.setText(f"{noise_value:.1f}")
        self._on_parameters_changed()
    
    def _create_array_view(self) -> QWidget:
        """创建中间的热力图显示面板"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 标题
        title_layout = QHBoxLayout()
        title = QLabel("Microfluidic Array")
        title_font = title.font()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        
        # 色标标签
        colorbar_label = QLabel("Low Δλ")
        colorbar_label.setStyleSheet("color: #666; font-size: 9pt;")
        
        colorbar_label2 = QLabel("High Δλ")
        colorbar_label2.setStyleSheet("color: #666; font-size: 9pt;")
        colorbar_label2.setAlignment(Qt.AlignRight)
        
        title_layout.addWidget(title)
        title_layout.addStretch()
        title_layout.addWidget(colorbar_label)
        title_layout.addWidget(colorbar_label2, 0)
        layout.addLayout(title_layout)
        
        # 使用 ImageView 显示热力图
        self.array_view_widget = pg.ImageView()
        self.array_view_widget.ui.roiBtn.hide()
        self.array_view_widget.ui.menuBtn.hide()
        
        try:
            colormap = pg.colormap.get('viridis')
        except:
            colormap = pg.colormap.get('jet')
        self.array_view_widget.setColorMap(colormap)
        
        self.array_view_widget.scene.sigMouseClicked.connect(self._on_array_clicked)
        
        layout.addWidget(self.array_view_widget, 1)
        
        # 底部信息面板
        info_group = QGroupBox()
        info_layout = QVBoxLayout(info_group)
        info_layout.setSpacing(8)
        info_layout.setContentsMargins(10, 10, 10, 10)
        
        # 网格信息
        info1_layout = QHBoxLayout()
        self.well_id_label = QLabel("Well ID: B15")
        self.well_id_label.setStyleSheet("color: #0066CC; font-size: 10pt;")
        info1_layout.addWidget(self.well_id_label)
        info1_layout.addStretch()
        info_layout.addLayout(info1_layout)
        
        # 标记物和浓度信息
        info2_layout = QHBoxLayout()
        self.marker_label = QLabel("Marker: NSE")
        self.marker_label.setStyleSheet("color: #0066CC; font-size: 10pt;")
        info2_layout.addWidget(self.marker_label)
        info2_layout.addStretch()
        info_layout.addLayout(info2_layout)
        
        # 浓度信息
        info3_layout = QHBoxLayout()
        self.conc_label = QLabel("Conc: 100 pM")
        self.conc_label.setStyleSheet("color: #0066CC; font-size: 10pt;")
        info3_layout.addWidget(self.conc_label)
        info3_layout.addStretch()
        info_layout.addLayout(info3_layout)
        
        # 偏移信息
        info4_layout = QHBoxLayout()
        self.shift_label = QLabel("Shift (Δλ): +4.47 nm")
        self.shift_label.setStyleSheet("color: #FF6600; font-size: 10pt; font-weight: bold;")
        info4_layout.addWidget(self.shift_label)
        info4_layout.addStretch()
        info_layout.addLayout(info4_layout)
        
        layout.addWidget(info_group)
        
        return container
    
    def _create_spectrum_view(self) -> QWidget:
        """创建右侧的光谱响应显示面板"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 标题和模式标签
        title_layout = QHBoxLayout()
        title = QLabel("LSPR Spectral Response")
        title_font = title.font()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        
        mode_badge = QLabel("Standard Mode")
        mode_badge.setStyleSheet("""
            background-color: #FFF8DC;
            color: #FF8C00;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 9pt;
            font-weight: bold;
        """)
        
        title_layout.addWidget(title)
        title_layout.addStretch()
        title_layout.addWidget(mode_badge)
        layout.addLayout(title_layout)
        
        # 光谱图
        self.spectrum_plot = pg.PlotWidget()
        self.spectrum_plot.setLabel('bottom', 'Wavelength', units='nm')
        self.spectrum_plot.setLabel('left', 'Extinction', units='a.u.')
        self.spectrum_plot.addLegend(offset=(10, 10))
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.3)
        
        layout.addWidget(self.spectrum_plot, 1)
        
        return container
    
    def _run_simulation(self):
        """运行仿真"""
        material = self.current_material
        mode = 'LSPR' if self.lspr_radio.isChecked() else 'SLR'
        concentration = 100.0  # 默认值
        noise_level = self.noise_slider.value() / 100.0
        temperature = 25.0
        
        shift_matrix = self.sensor_model.generate_shift_matrix(
            material=material,
            mode=mode,
            concentration=concentration,
            noise_level=noise_level,
            temperature=temperature
        )
        
        self._update_array_view(shift_matrix)
        self._update_spectrum_view(self.current_selected_pos)
    
    def _update_array_view(self, shift_matrix: np.ndarray):
        """更新热力图显示"""
        self.array_view_widget.setImage(shift_matrix, autoRange=True, autoLevels=True)
    
    def _update_spectrum_view(self, pos: tuple):
        """更新光谱显示"""
        row, col = pos
        spectrum_data = self.sensor_model.get_spectrum(row, col)
        
        self.spectrum_plot.clear()
        
        wavelengths = spectrum_data['wavelengths']
        baseline = spectrum_data['baseline']
        signal = spectrum_data['signal']
        shift = spectrum_data['shift']
        
        self.spectrum_plot.plot(
            wavelengths, baseline,
            pen=pg.mkPen('#808080', width=2, style=Qt.DashLine),
            name='Baseline (Reference)',
            symbol='o',
            symbolSize=5
        )
        
        self.spectrum_plot.plot(
            wavelengths, signal,
            pen=pg.mkPen('#0066FF', width=2),
            name=f'Signal (After Binding)',
            symbol='o',
            symbolSize=5
        )
        
        # 更新底部信息
        self.well_id_label.setText(f"Well ID: {chr(65 + row)}{col + 1}")
        self.shift_label.setText(f"Shift (Δλ): +{shift:.2f} nm")
        self.conc_label.setText("Conc: 100 pM")
    
    def _on_array_clicked(self, event):
        """热力图点击事件"""
        if event.button() != 1:
            return
        
        scene_pos = event.scenePos()
        view_box = self.array_view_widget.getImageItem().getViewBox()
        view_pos = view_box.mapSceneToView(scene_pos)
        
        row = int(np.clip(view_pos.y(), 0, 14))
        col = int(np.clip(view_pos.x(), 0, 14))
        
        self.current_selected_pos = (row, col)
        self._update_spectrum_view((row, col))
    
    def _on_mode_changed(self):
        """模式改变事件"""
        self._on_parameters_changed()
    
    def _on_parameters_changed(self):
        """参数改变事件"""
        self._run_simulation()
    
    def _apply_theme(self):
        """应用主题"""
        try:
            settings = load_settings()
            theme = settings.get('theme', 'dark')
        except:
            theme = 'dark'
        
        if theme == 'light':
            self.array_view_widget.getImageItem().getViewBox().setBackgroundColor('#F0F0F0')
            self.spectrum_plot.setBackground('#F0F0F0')
            self.spectrum_plot.getAxis('bottom').setPen(pg.mkPen('#212529', width=1))
            self.spectrum_plot.getAxis('left').setPen(pg.mkPen('#212529', width=1))
            self.spectrum_plot.getAxis('bottom').setTextPen(pg.mkPen('#495057'))
            self.spectrum_plot.getAxis('left').setTextPen(pg.mkPen('#495057'))
        else:
            self.array_view_widget.getImageItem().getViewBox().setBackgroundColor('#1F2735')
            self.spectrum_plot.setBackground('#1F2735')
            self.spectrum_plot.getAxis('bottom').setPen(pg.mkPen('#90A4AE', width=1))
            self.spectrum_plot.getAxis('left').setPen(pg.mkPen('#90A4AE', width=1))
            self.spectrum_plot.getAxis('bottom').setTextPen(pg.mkPen('#B0BEC5'))
            self.spectrum_plot.getAxis('left').setTextPen(pg.mkPen('#B0BEC5'))
    
    def changeEvent(self, event):
        """处理主题切换事件"""
        if event.type() == QEvent.PaletteChange:
            self._apply_theme()
        super().changeEvent(event)
