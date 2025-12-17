# nanosense/gui/lspr_comparison_widget.py
"""
Phase 3：LSPR 多浓度对比分析窗口
支持浓度扫描、灵敏度曲线显示和参数优化结果展示
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPushButton,
    QLabel, QSpinBox, QDoubleSpinBox, QComboBox, QProgressBar,
    QMessageBox, QCheckBox, QGroupBox, QGridLayout
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QEvent
from PyQt5.QtGui import QFont
import pyqtgraph as pg
import numpy as np
from threading import Thread

from nanosense.algorithms.lspr_model import SensorModel
from nanosense.utils.config_manager import load_settings


class ComparisonWorker(QThread):
    """后台工作线程，用于长时间的扫描计算"""
    
    progress = pyqtSignal(int)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, model: SensorModel, sweep_config: dict):
        super().__init__()
        self.model = model
        self.sweep_config = sweep_config
    
    def run(self):
        try:
            if self.sweep_config['type'] == 'concentration':
                self._run_concentration_sweep()
            elif self.sweep_config['type'] == 'sensitivity_curve':
                self._run_sensitivity_curve()
            elif self.sweep_config['type'] == 'parameter_sweep':
                self._run_parameter_sweep()
        except Exception as e:
            self.error.emit(str(e))
    
    def _run_concentration_sweep(self):
        """浓度扫描"""
        num_points = self.sweep_config.get('num_points', 20)
        scale_type = self.sweep_config.get('scale', 'log')
        
        if scale_type == 'log':
            concentrations = self.model.concentration_sweep_linear(1, 1000, num_points)
        else:
            concentrations = self.model.concentration_sweep_linear_scale(1, 1000, num_points)
        
        results = {
            'concentrations': concentrations.tolist(),
            'shifts': [],
            'sensitivities': []
        }
        
        for i, conc in enumerate(concentrations):
            self.model.generate_shift_matrix(
                material=self.sweep_config.get('material', 'Au'),
                mode=self.sweep_config.get('mode', 'LSPR'),
                concentration=float(conc),
                noise_level=self.sweep_config.get('noise_level', 0.5),
                temperature=self.sweep_config.get('temperature', 25.0)
            )
            stats = self.model.get_statistics()
            results['shifts'].append(stats['max'])
            
            # 计算灵敏度
            if i > 0:
                s = (results['shifts'][i] - results['shifts'][i-1]) / (conc - concentrations[i-1])
                results['sensitivities'].append(float(abs(s)))
            else:
                results['sensitivities'].append(0.0)
            
            progress = int((i + 1) / len(concentrations) * 100)
            self.progress.emit(progress)
        
        self.finished.emit(results)
    
    def _run_sensitivity_curve(self):
        """灵敏度曲线生成"""
        num_points = self.sweep_config.get('num_points', 20)
        
        # 生成对数间距的浓度点
        concentrations = self.model.concentration_sweep_linear(1, 1000, num_points)
        sensitivity_curve = self.model.get_sensitivity_curve(concentrations)
        
        results = {
            'concentrations': sorted(sensitivity_curve.keys()),
            'sensitivities': [sensitivity_curve[c] for c in sorted(sensitivity_curve.keys())]
        }
        
        self.progress.emit(100)
        self.finished.emit(results)
    
    def _run_parameter_sweep(self):
        """参数扫描"""
        # 简化版参数扫描：遍历浓度和噪声级别
        concentrations = np.array([1, 10, 50, 100, 500, 1000])
        noise_levels = np.array([0.2, 0.5, 0.8])
        
        results = {
            'concentrations': concentrations.tolist(),
            'noise_levels': noise_levels.tolist(),
            'matrix': np.zeros((len(noise_levels), len(concentrations)))
        }
        
        for i, noise in enumerate(noise_levels):
            for j, conc in enumerate(concentrations):
                self.model.generate_shift_matrix(
                    material=self.sweep_config.get('material', 'Au'),
                    mode=self.sweep_config.get('mode', 'LSPR'),
                    concentration=float(conc),
                    noise_level=float(noise),
                    temperature=self.sweep_config.get('temperature', 25.0)
                )
                stats = self.model.get_statistics()
                results['matrix'][i, j] = stats['mean']
                
                progress = int(((i * len(concentrations) + j + 1) / 
                               (len(noise_levels) * len(concentrations))) * 100)
                self.progress.emit(progress)
        
        self.finished.emit(results)


class LSPRComparisonWidget(QWidget):
    """Phase 3 多浓度对比分析窗口"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LSPR 多浓度对比分析")
        self.setGeometry(150, 150, 1200, 800)
        
        self.sensor_model = SensorModel(array_size=15)
        self.worker = None
        
        self._init_ui()
        self._apply_theme()
    
    def _init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(12, 12, 12, 12)
        
        # 标题
        title = QLabel(self.tr("Multi-Concentration Comparison Analysis"))
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        main_layout.addWidget(title)
        
        # 控制面板
        control_group = self._create_control_panel()
        main_layout.addWidget(control_group)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximum(100)
        main_layout.addWidget(self.progress_bar)
        
        # 标签页
        self.tab_widget = QTabWidget()
        
        # Tab 1：浓度扫描
        self.conc_scan_plot = pg.PlotWidget()
        self.conc_scan_plot.setLabel('bottom', self.tr('Concentration'), units='pM')
        self.conc_scan_plot.setLabel('left', self.tr('Shift'), units='nm')
        self.conc_scan_plot.addLegend()
        self.conc_scan_plot.showGrid(x=True, y=True, alpha=0.3)
        self.tab_widget.addTab(self.conc_scan_plot, self.tr("Concentration Sweep"))
        
        # Tab 2：灵敏度曲线
        self.sensitivity_plot = pg.PlotWidget()
        self.sensitivity_plot.setLabel('bottom', self.tr('Concentration'), units='pM')
        self.sensitivity_plot.setLabel('left', self.tr('Sensitivity'), units='nm/pM')
        self.sensitivity_plot.showGrid(x=True, y=True, alpha=0.3)
        self.tab_widget.addTab(self.sensitivity_plot, self.tr("Sensitivity Curve"))
        
        # Tab 3：参数扫描热力图
        self.param_heatmap = pg.ImageView()
        self.param_heatmap.ui.roiBtn.hide()
        self.param_heatmap.ui.menuBtn.hide()
        self.tab_widget.addTab(self.param_heatmap, self.tr("Parameter Sweep"))
        
        # Tab 4：结果统计
        self.stats_text = pg.TextEdit()
        self.stats_text.setReadOnly(True)
        self.tab_widget.addTab(self.stats_text, self.tr("Statistics"))
        
        main_layout.addWidget(self.tab_widget)
        
        self.setLayout(main_layout)
    
    def _create_control_panel(self) -> QGroupBox:
        """创建控制面板"""
        group = QGroupBox(self.tr("Scan Configuration"))
        layout = QGridLayout(group)
        layout.setSpacing(10)
        
        # 扫描类型
        type_label = QLabel(self.tr("Scan Type:"))
        self.scan_type_combo = QComboBox()
        self.scan_type_combo.addItems([
            self.tr("Concentration Sweep"),
            self.tr("Sensitivity Curve"),
            self.tr("Parameter Sweep")
        ])
        layout.addWidget(type_label, 0, 0)
        layout.addWidget(self.scan_type_combo, 0, 1)
        
        # 采样点数
        points_label = QLabel(self.tr("Sample Points:"))
        self.points_spin = QSpinBox()
        self.points_spin.setRange(5, 100)
        self.points_spin.setValue(20)
        layout.addWidget(points_label, 0, 2)
        layout.addWidget(self.points_spin, 0, 3)
        
        # 浓度范围
        conc_label = QLabel(self.tr("Concentration Range (pM):"))
        self.conc_min_spin = QDoubleSpinBox()
        self.conc_min_spin.setValue(1.0)
        self.conc_min_spin.setRange(0.1, 10000)
        self.conc_max_spin = QDoubleSpinBox()
        self.conc_max_spin.setValue(1000.0)
        self.conc_max_spin.setRange(0.1, 10000)
        layout.addWidget(conc_label, 1, 0)
        layout.addWidget(self.conc_min_spin, 1, 1)
        layout.addWidget(QLabel(" - "), 1, 2)
        layout.addWidget(self.conc_max_spin, 1, 3)
        
        # 材料选择
        material_label = QLabel(self.tr("Material:"))
        self.material_combo = QComboBox()
        self.material_combo.addItems(['Au', 'Ag', 'Au@Ag'])
        layout.addWidget(material_label, 2, 0)
        layout.addWidget(self.material_combo, 2, 1)
        
        # 模式选择
        mode_label = QLabel(self.tr("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['LSPR', 'SLR'])
        layout.addWidget(mode_label, 2, 2)
        layout.addWidget(self.mode_combo, 2, 3)
        
        # 噪声和温度
        noise_label = QLabel(self.tr("Noise Level:"))
        self.noise_spin = QDoubleSpinBox()
        self.noise_spin.setRange(0.0, 1.0)
        self.noise_spin.setValue(0.5)
        self.noise_spin.setSingleStep(0.1)
        layout.addWidget(noise_label, 3, 0)
        layout.addWidget(self.noise_spin, 3, 1)
        
        temp_label = QLabel(self.tr("Temperature (°C):"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(10.0, 50.0)
        self.temp_spin.setValue(25.0)
        layout.addWidget(temp_label, 3, 2)
        layout.addWidget(self.temp_spin, 3, 3)
        
        # 运行按钮
        self.run_button = QPushButton(self.tr("Run Scan"))
        self.run_button.setMinimumHeight(35)
        self.run_button.clicked.connect(self._run_scan)
        layout.addWidget(self.run_button, 4, 0, 1, 4)
        
        return group
    
    def _run_scan(self):
        """启动扫描"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.run_button.setEnabled(False)
        
        scan_type_index = self.scan_type_combo.currentIndex()
        scan_types = ['concentration', 'sensitivity_curve', 'parameter_sweep']
        
        sweep_config = {
            'type': scan_types[scan_type_index],
            'num_points': self.points_spin.value(),
            'conc_min': self.conc_min_spin.value(),
            'conc_max': self.conc_max_spin.value(),
            'material': self.material_combo.currentText(),
            'mode': self.mode_combo.currentText(),
            'noise_level': self.noise_spin.value(),
            'temperature': self.temp_spin.value(),
            'scale': 'log'
        }
        
        self.worker = ComparisonWorker(self.sensor_model, sweep_config)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.finished.connect(self._on_scan_finished)
        self.worker.error.connect(self._on_scan_error)
        self.worker.start()
    
    def _on_scan_finished(self, results: dict):
        """扫描完成处理"""
        self.progress_bar.setVisible(False)
        self.run_button.setEnabled(True)
        
        scan_type_index = self.scan_type_combo.currentIndex()
        
        try:
            if scan_type_index == 0:  # 浓度扫描
                self._display_concentration_sweep(results)
            elif scan_type_index == 1:  # 灵敏度曲线
                self._display_sensitivity_curve(results)
            elif scan_type_index == 2:  # 参数扫描
                self._display_parameter_sweep(results)
            
            QMessageBox.information(
                self,
                self.tr("Scan Complete"),
                self.tr("Scan completed successfully!")
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Display Error"),
                self.tr(f"Error displaying results: {str(e)}")
            )
    
    def _display_concentration_sweep(self, results: dict):
        """显示浓度扫描结果"""
        self.conc_scan_plot.clear()
        
        conc = np.array(results['concentrations'])
        shifts = np.array(results['shifts'])
        
        # 使用对数坐标
        self.conc_scan_plot.setLogMode(x=True, y=False)
        
        # 绘制主曲线
        self.conc_scan_plot.plot(
            conc, shifts,
            pen=pg.mkPen('b', width=2),
            symbol='o',
            symbolSize=6,
            name=self.tr('Shift vs Concentration')
        )
        
        # 统计信息
        stats_text = (
            f"<b>Concentration Sweep Results</b><br>"
            f"Number of Points: {len(conc)}<br>"
            f"Concentration Range: {conc[0]:.1f} - {conc[-1]:.1f} pM<br>"
            f"Max Shift: {np.max(shifts):.3f} nm<br>"
            f"Mean Shift: {np.mean(shifts):.3f} nm<br>"
            f"Std Dev: {np.std(shifts):.3f} nm"
        )
        self.stats_text.setHtml(stats_text)
    
    def _display_sensitivity_curve(self, results: dict):
        """显示灵敏度曲线"""
        self.sensitivity_plot.clear()
        
        conc = np.array(results['concentrations'])
        sensitivity = np.array(results['sensitivities'])
        
        self.sensitivity_plot.setLogMode(x=True, y=False)
        
        self.sensitivity_plot.plot(
            conc, sensitivity,
            pen=pg.mkPen('g', width=2),
            symbol='s',
            symbolSize=6,
            name=self.tr('Sensitivity Curve')
        )
        
        # 统计信息
        max_sens_idx = np.argmax(sensitivity)
        stats_text = (
            f"<b>Sensitivity Curve Results</b><br>"
            f"Number of Points: {len(conc)}<br>"
            f"Max Sensitivity: {np.max(sensitivity):.4f} nm/pM<br>"
            f"At Concentration: {conc[max_sens_idx]:.1f} pM<br>"
            f"Mean Sensitivity: {np.mean(sensitivity):.4f} nm/pM<br>"
            f"Dynamic Range: {(np.max(sensitivity) - np.min(sensitivity)) / np.mean(sensitivity):.2f}"
        )
        self.stats_text.setHtml(stats_text)
    
    def _display_parameter_sweep(self, results: dict):
        """显示参数扫描热力图"""
        matrix = np.array(results['matrix'])
        
        self.param_heatmap.setImage(matrix, autoRange=True, autoLevels=True)
        self.param_heatmap.setColorMap(pg.colormap.get('turbo'))
        
        # 统计信息
        stats_text = (
            f"<b>Parameter Sweep Results</b><br>"
            f"Concentrations Tested: {len(results['concentrations'])}<br>"
            f"Noise Levels Tested: {len(results['noise_levels'])}<br>"
            f"Max Value: {np.max(matrix):.3f}<br>"
            f"Min Value: {np.min(matrix):.3f}<br>"
            f"Mean Value: {np.mean(matrix):.3f}"
        )
        self.stats_text.setHtml(stats_text)
    
    def _on_scan_error(self, error_msg: str):
        """扫描出错处理"""
        self.progress_bar.setVisible(False)
        self.run_button.setEnabled(True)
        
        QMessageBox.critical(
            self,
            self.tr("Scan Error"),
            self.tr(f"An error occurred: {error_msg}")
        )
    
    def _apply_theme(self):
        """应用当前主题"""
        try:
            settings = load_settings()
            theme = settings.get('theme', 'dark')
        except Exception:
            theme = 'dark'
        
        if theme == 'light':
            # 亮色主题
            for plot in [self.conc_scan_plot, self.sensitivity_plot]:
                plot.setBackground('#F0F0F0')
                plot.getAxis('bottom').setPen(pg.mkPen('#212529', width=1))
                plot.getAxis('left').setPen(pg.mkPen('#212529', width=1))
                plot.getAxis('bottom').setTextPen(pg.mkPen('#495057'))
                plot.getAxis('left').setTextPen(pg.mkPen('#495057'))
        else:
            # 暗色主题
            for plot in [self.conc_scan_plot, self.sensitivity_plot]:
                plot.setBackground('#1F2735')
                plot.getAxis('bottom').setPen(pg.mkPen('#90A4AE', width=1))
                plot.getAxis('left').setPen(pg.mkPen('#90A4AE', width=1))
                plot.getAxis('bottom').setTextPen(pg.mkPen('#B0BEC5'))
                plot.getAxis('left').setTextPen(pg.mkPen('#B0BEC5'))
    
    def changeEvent(self, event):
        """处理主题切换事件"""
        if event.type() == QEvent.PaletteChange:
            self._apply_theme()
        super().changeEvent(event)
