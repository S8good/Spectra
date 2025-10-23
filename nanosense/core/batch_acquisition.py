# nanosense/core/batch_acquisition.py (最终预览版)
import queue
import time
import os
import numpy as np
import threading
import pyqtgraph as pg
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox, QGridLayout, \
    QHBoxLayout, QWidget, QToolButton
from PyQt5.QtCore import QObject, pyqtSignal, QThread, Qt, QEvent
from collections import defaultdict
import pandas as pd
from .controller import FX2000Controller
from ..utils.file_io import save_batch_spectrum_data
from ..gui.single_plot_window import SinglePlotWindow

def _calculate_absorbance(signal, background, reference):
    """根据信号、背景和参考光谱计算吸收率"""
    if signal is None or background is None or reference is None:
        return None
    signal, background, reference = np.array(signal), np.array(background), np.array(reference)
    effective_signal = signal - background
    effective_ref = reference - background
    safe_denominator = np.copy(effective_ref)
    safe_denominator[safe_denominator == 0] = 1e-9
    transmittance = effective_signal / safe_denominator
    transmittance[transmittance <= 0] = 1e-9
    absorbance = -1 * np.log10(transmittance)
    return absorbance

class MultiCurvePlotWindow(pg.QtWidgets.QMainWindow):
    closed = pyqtSignal(object)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setGeometry(300, 300, 800, 600)
        self.plot_widget = pg.PlotWidget()
        self.setCentralWidget(self.plot_widget)
        self.plot_widget.addLegend()

    def update_data(self, wavelengths, spectra_list):
        self.plot_widget.clear()
        if wavelengths is not None and spectra_list:
            for i, spectrum in enumerate(spectra_list):
                color = pg.intColor(i, hues=len(spectra_list), alpha=150)
                self.plot_widget.plot(wavelengths, spectrum, pen=pg.mkPen(color), name=f"Result_{i+1}")

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)

class BatchRunDialog(QDialog):
    """【已升级和国际化】状态对话框，增加了实时光谱预览图表"""
    action_triggered = pyqtSignal()
    back_triggered = pyqtSignal()
    abort_mission = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # 【核心修改】设置窗口标志以允许最大化、最小化和调整大小
        self.setWindowFlags(
            self.windowFlags() |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint |
            Qt.WindowSystemMenuHint |
            Qt.WindowCloseButtonHint
        )

        self.resize(1300, 800)  # 【修改】使用resize代替setMinimumSize以允许窗口自由缩小
        self.setModal(True)
        self.summary_curves = []
        self.is_summary_paused = False
        self.popout_windows = []

        self._init_ui()
        self._connect_signals()
        self._retranslate_ui()

    def _dummy_strings_for_translator(self):
        self.tr("Please place [Background] for well {well_id}\n(Live preview active...)")
        self.tr("Collect Background")
        self.tr("Please place [Reference] for well {well_id}\n(Live preview active...)")
        self.tr("Collect Reference")
        self.tr("Please move to well {well_id}, point {point_num}/{total_points}\n(Live preview active...)")
        self.tr("Collect this Point")
        self.tr("Calculating absorbance for {well_id}...")
        self.tr("Saving data for {well_id}...")
        self.tr("Batch acquisition complete!")
        self.tr("Done")

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        self.instruction_label = QLabel()
        font = self.instruction_label.font();
        font.setPointSize(14);
        self.instruction_label.setFont(font)
        self.instruction_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.instruction_label)

        plots_container = QWidget()
        plots_layout = QVBoxLayout(plots_container)
        plots_layout.setContentsMargins(0, 0, 0, 0)

        # --- 辅助函数：创建带放大按钮的图表容器 ---
        def create_plot_container(plot_widget, title_key, popout_handler):
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0);
            layout.setSpacing(0)

            header_widget = QWidget()
            header_layout = QHBoxLayout(header_widget)
            header_layout.setContentsMargins(5, 2, 5, 2)

            title_label = QLabel(self.tr(title_key))
            title_label.setStyleSheet("color: #90A4AE; font-size: 12pt;")

            popout_button = QToolButton()
            icon_path = os.path.join(os.path.dirname(__file__), '..', 'gui', 'assets', 'icons', 'zoom.png')
            popout_button.setIcon(pg.QtGui.QIcon(icon_path))
            popout_button.setToolTip(self.tr("Open in New Window"))
            popout_button.clicked.connect(popout_handler)

            header_layout.addWidget(title_label)
            header_layout.addStretch()
            header_layout.addWidget(popout_button)

            layout.addWidget(header_widget)
            layout.addWidget(plot_widget)

            plot_widget.setTitle("")  # 清除pyqtgraph的默认标题
            plot_widget.showGrid(x=True, y=True, alpha=0.3)
            return container

        # --- 创建图表 ---
        self.signal_plot = pg.PlotWidget();
        self.signal_curve = self.signal_plot.plot(pen='c')
        self.background_plot = pg.PlotWidget();
        self.background_curve = self.background_plot.plot(pen='w')
        self.reference_plot = pg.PlotWidget();
        self.reference_curve = self.reference_plot.plot(pen='m')
        self.result_plot = pg.PlotWidget();
        self.result_curve = self.result_plot.plot(pen='y')
        self.summary_plot = pg.PlotWidget()

        # --- 将图表放入带按钮的容器中 ---
        signal_container = create_plot_container(self.signal_plot, "Live Signal",
                                                 lambda: self._open_popout_window('signal'))
        background_container = create_plot_container(self.background_plot, "Current Background",
                                                     lambda: self._open_popout_window('background'))
        reference_container = create_plot_container(self.reference_plot, "Current Reference",
                                                    lambda: self._open_popout_window('reference'))
        result_container = create_plot_container(self.result_plot, "Live Result (Absorbance)",
                                                 lambda: self._open_popout_window('result'))
        summary_container = create_plot_container(self.summary_plot, "Accumulated Results Summary",
                                                  lambda: self._open_popout_window('summary'))

        # --- 布局 ---
        # 【核心修改】将主绘图区的布局从 QVBoxLayout 改为 QGridLayout
        # 我们将整个区域想象成一个 2行6列 的网格
        plots_container = QWidget()
        plots_layout = QGridLayout(plots_container)  # <--- 改为 QGridLayout
        plots_layout.setContentsMargins(0, 0, 0, 0)

        # 将顶部三个图表分别放入网格的第0行，各自占据2列
        plots_layout.addWidget(signal_container, 0, 0, 1, 2)  # (第0行, 第0列, 占1行, 占2列)
        plots_layout.addWidget(background_container, 0, 2, 1, 2)  # (第0行, 第2列, 占1行, 占2列)
        plots_layout.addWidget(reference_container, 0, 4, 1, 2)  # (第0行, 第4列, 占1行, 占2列)

        # 将底部两个图表放入网格的第1行，各自占据3列
        plots_layout.addWidget(result_container, 1, 0, 1, 3)  # (第1行, 第0列, 占1行, 占3列)
        plots_layout.addWidget(summary_container, 1, 3, 1, 3)  # (第1行, 第3列, 占1行, 占3列)

        # 【核心修改】设置行的拉伸因子来控制高度比例 (4:3)
        # 这会让顶部图表获得更多的高度
        plots_layout.setRowStretch(0, 1)  # 第0行（顶部）的拉伸因子为1
        plots_layout.setRowStretch(1, 1)  # 第1行（底部）的拉伸因子为1

        main_layout.addWidget(plots_container)

        # --- 汇总图控制 ---
        summary_controls_layout = QHBoxLayout()
        self.toggle_summary_button = QPushButton()
        self.toggle_summary_button.setCheckable(True)
        self.clear_summary_button = QPushButton()
        summary_controls_layout.addStretch()
        summary_controls_layout.addWidget(self.toggle_summary_button)
        summary_controls_layout.addWidget(self.clear_summary_button)
        main_layout.addLayout(summary_controls_layout)

        # --- 进度条和主按钮 ---
        progress_layout = QGridLayout()
        self.total_progress_bar = QProgressBar()
        self.point_progress_bar = QProgressBar()
        self.total_progress_label = QLabel()
        self.point_progress_label = QLabel()
        progress_layout.addWidget(self.total_progress_label, 0, 0)
        progress_layout.addWidget(self.total_progress_bar, 0, 1)
        progress_layout.addWidget(self.point_progress_label, 1, 0)
        progress_layout.addWidget(self.point_progress_bar, 1, 1)
        main_layout.addLayout(progress_layout)

        button_layout = QHBoxLayout()
        self.back_button = QPushButton()
        self.action_button = QPushButton()
        button_layout.addWidget(self.back_button)
        button_layout.addWidget(self.action_button)
        main_layout.addLayout(button_layout)

        self.abort_button = QPushButton()
        main_layout.addWidget(self.abort_button)

    def _connect_signals(self):
        self.action_button.clicked.connect(self.action_triggered.emit)
        self.back_button.clicked.connect(self.back_triggered.emit)
        self.abort_button.clicked.connect(self._confirm_abort)
        self.toggle_summary_button.toggled.connect(self._toggle_summary_pause)
        self.clear_summary_button.clicked.connect(self._clear_summary_plot)

    def changeEvent(self, event):
        """处理语言变化事件"""
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """重新翻译所有UI文本，包括新的图表标题和按钮。"""
        self.setWindowTitle(self.tr("Batch Acquisition in Progress..."))
        self.instruction_label.setText(self.tr("Initializing..."))

        # 图表标题
        title_style = {'color': '#90A4AE', 'size': '12pt'}
        self.signal_plot.setTitle(self.tr("Live Signal"), **title_style)
        self.background_plot.setTitle(self.tr("Current Background"), **title_style)
        self.reference_plot.setTitle(self.tr("Current Reference"), **title_style)
        self.result_plot.setTitle(self.tr("Live Result (Absorbance)"), **title_style)
        self.summary_plot.setTitle(self.tr("Accumulated Results Summary"), **title_style)

        # 进度条标签
        self.total_progress_label.setText(self.tr("Total Well Progress:"))
        self.point_progress_label.setText(self.tr("Current Point Progress:"))

        # 主按钮
        self.action_button.setText(self.tr("Start"))
        self.back_button.setText(self.tr("Previous Step"))
        self.abort_button.setText(self.tr("Abort Task"))

        # 新增的汇总控制按钮
        self.toggle_summary_button.setText(self.tr("Pause Overlay"))
        self.clear_summary_button.setText(self.tr("Clear Summary Plot"))

    def _open_popout_window(self, plot_type):
        # 检查是否已有同类型的窗口打开
        for item in self.popout_windows:
            if item['type'] == plot_type:
                item['window'].activateWindow()
                return

        title_map = {
            'signal': self.tr("Live Signal"),
            'background': self.tr("Current Background"),
            'reference': self.tr("Current Reference"),
            'result': self.tr("Live Result (Absorbance)"),
            'summary': self.tr("Accumulated Results Summary")
        }
        title = title_map.get(plot_type, "Plot")

        win = None
        if plot_type == 'summary':
            win = MultiCurvePlotWindow(title, self)
        else:
            win = SinglePlotWindow(title, parent=self)

        if win:
            self.popout_windows.append({'type': plot_type, 'window': win})
            win.closed.connect(self._on_popout_closed)
            win.show()  # 使用 .show() 创建非模态窗口

    def _on_popout_closed(self, window_instance):
        self.popout_windows = [item for item in self.popout_windows if item['window'] is not window_instance]
        print(f"Pop-out window '{window_instance.windowTitle()}' closed.")

    def update_all_plots(self, data_package):
        # 【修改】获取全范围和裁切后的数据
        full_wavelengths = data_package.get("full_wavelengths")
        result_wavelengths = data_package.get("result_wavelengths")
        if full_wavelengths is None: return

        live_signal = data_package.get("live_signal", [])
        bg_spec = data_package.get("background")
        ref_spec = data_package.get("reference")
        all_results = data_package.get("all_results", [])

        # 1. 更新使用全范围数据的图表 (主界面和弹出窗口)
        self.signal_curve.setData(full_wavelengths, live_signal)
        self.background_curve.setData(full_wavelengths, bg_spec if bg_spec is not None else [])
        self.reference_curve.setData(full_wavelengths, ref_spec if ref_spec is not None else [])

        # 2. 计算实时吸收光谱 (裁切后)
        current_result = None
        if result_wavelengths is not None:
            # 创建掩码
            mask = np.isin(full_wavelengths, result_wavelengths)

            # 【修复】将列表转换为Numpy数组以使用布尔掩码进行索引
            live_signal_np = np.array(live_signal)
            bg_spec_np = np.array(bg_spec) if bg_spec is not None else None
            ref_spec_np = np.array(ref_spec) if ref_spec is not None else None

            # 裁切用于计算的数据
            live_signal_cropped = live_signal_np[mask] if len(live_signal) > 0 else None
            bg_spec_cropped = bg_spec_np[mask] if bg_spec_np is not None else None
            ref_spec_cropped = ref_spec_np[mask] if ref_spec_np is not None else None
            current_result = _calculate_absorbance(live_signal_cropped, bg_spec_cropped, ref_spec_cropped)

        # 3. 更新使用裁切后数据的图表
        self.result_curve.setData(result_wavelengths, current_result if current_result is not None else [])
        if not self.is_summary_paused and len(all_results) != len(self.summary_curves):
            self._redraw_summary_plot(result_wavelengths, all_results)

        # 4. 【修改】更新所有打开的弹出窗口
        for item in self.popout_windows:
            win = item['window']
            plot_type = item['type']

            if plot_type == 'signal':
                win.update_data(full_wavelengths, live_signal, self.signal_curve.opts['pen'])
            elif plot_type == 'background':
                win.update_data(full_wavelengths, bg_spec, self.background_curve.opts['pen'])
            elif plot_type == 'reference':
                win.update_data(full_wavelengths, ref_spec, self.reference_curve.opts['pen'])
            elif plot_type == 'result':
                win.update_data(result_wavelengths, current_result, self.result_curve.opts['pen'])
            elif plot_type == 'summary':
                win.update_data(result_wavelengths, all_results)

    def _redraw_summary_plot(self, wavelengths, all_results):
        self.summary_plot.clear()
        self.summary_curves.clear()
        for i, spectrum in enumerate(all_results):
            # 使用带透明度的颜色
            color = pg.intColor(i, hues=len(all_results), alpha=150)
            curve = self.summary_plot.plot(wavelengths, spectrum, pen=pg.mkPen(color))
            self.summary_curves.append(curve)

    def _toggle_summary_pause(self, paused):
        self.is_summary_paused = paused
        if paused:
            self.toggle_summary_button.setText(self.tr("Resume Overlay"))
        else:
            self.toggle_summary_button.setText(self.tr("Pause Overlay"))

    def _clear_summary_plot(self):
        # 这个函数只清除前端显示，worker中的历史数据不受影响
        self.summary_plot.clear()
        self.summary_curves.clear()
        # 如果用户在暂停时点击清除，清除后应该保持暂停状态
        # 如果是在运行时点击清除，下一次更新会自动重绘所有历史曲线，等于刷新
        if not self.is_summary_paused:
            # 强制下一次更新重绘
            pass  # 逻辑上，下一次worker发送的数据会自动重绘

    def _confirm_abort(self):
        reply = QMessageBox.question(self, self.tr('Confirm'),
                                     self.tr('Are you sure you want to abort the current batch acquisition task?'),
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.abort_mission.emit()
            self.reject()

    def closeEvent(self, event):
        self._confirm_abort()
        event.ignore()

    def update_state(self, status: dict):
        if "instruction_key" in status:
            key = status["instruction_key"]
            params = status.get("params", {})
            self.instruction_label.setText(self.tr(key).format(**params))

        if "total_progress" in status:
            self.total_progress_bar.setValue(status["total_progress"])
        if "point_progress" in status:
            self.point_progress_bar.setValue(status["point_progress"])

        if "button_text_key" in status:
            self.action_button.setText(self.tr(status["button_text_key"]))

        if "button_enabled" in status:
            self.action_button.setEnabled(status["button_enabled"])

        if "back_button_enabled" in status:
            self.back_button.setEnabled(status["back_button_enabled"])

class BatchAcquisitionWorker(QObject):
    """【最终架构版】采用指令队列(Queue)解决线程安全问题"""
    finished = pyqtSignal()
    error = pyqtSignal(str)
    update_dialog = pyqtSignal(dict)
    live_preview_data = pyqtSignal(dict)

    def __init__(self, controller: FX2000Controller, layout_data: dict, output_folder: str, file_extension: str,
                 points_per_well: int = 16, crop_start_wl=None, crop_end_wl=None,
                 is_auto_enabled=False, intra_well_interval=2.0, inter_well_interval=10.0):  # <--【修改】接收新参数
        super().__init__()
        self.controller = controller
        self.layout_data = layout_data
        self.output_folder = output_folder
        self.file_extension = file_extension
        self.points_per_well = points_per_well
        self.crop_start_wl = crop_start_wl
        self.crop_end_wl = crop_end_wl

        # 【新增】存储自动化采集的设置
        self.is_auto_enabled = is_auto_enabled
        self.intra_well_interval = intra_well_interval
        self.inter_well_interval = inter_well_interval

        self._is_running = True
        self.command_queue = queue.Queue(maxsize=1)
        self.tasks = []
        self.task_index = 0
        self.collected_data = defaultdict(lambda: {"signals": {}, "absorbance": {}})

        self.wavelengths = np.array(self.controller.wavelengths)
        if self.crop_start_wl is not None and self.crop_end_wl is not None:
            self.wavelength_mask = (self.wavelengths >= self.crop_start_wl) & (self.wavelengths <= self.crop_end_wl)
            self.cropped_wavelengths = self.wavelengths[self.wavelength_mask]
        else:
            self.wavelength_mask = None
            self.cropped_wavelengths = self.wavelengths

    def trigger_action(self):
        """由“采集”按钮触发，向队列发送 FORWARD 指令"""
        if self.command_queue.empty():
            self.command_queue.put('FORWARD')

    def stop(self):
        self._is_running = False
        if self.command_queue.empty():
            self.command_queue.put('STOP')
        if self.controller:
            self.controller.abort_endpoint_pipe()

    def go_back(self):
        """由“上一步”按钮触发，向队列发送 BACKWARD 指令"""
        if self.task_index > 0 and self.command_queue.empty():
            self.command_queue.put('BACKWARD')

    def _timed_preview_wait(self, duration):
        """
        【新增】在指定的持续时间内等待，并持续发送预览数据。
        如果用户中止，则返回False。
        """
        start_time = time.time()

        # 为预览获取当前上下文
        current_task = self.tasks[self.task_index]
        current_well_id = current_task['well_id']
        current_well_data = self.collected_data.get(current_well_id, {})
        all_completed_results = []
        for well_id, data in self.collected_data.items():
            all_completed_results.extend(data['absorbance'].values())

        # 在延时期间循环刷新预览
        while (time.time() - start_time) < duration:
            if not self._is_running:  # 允许在等待期间中止
                return False

            _, spectrum = self.controller.get_spectrum()

            # 发射预览信号
            data_package = {
                "full_wavelengths": self.wavelengths,
                "live_signal": spectrum,
                "background": current_well_data.get('background'),
                "reference": current_well_data.get('reference'),
                "result_wavelengths": self.cropped_wavelengths,
                "all_results": all_completed_results
            }
            self.live_preview_data.emit(data_package)

            QThread.msleep(50)  # 控制刷新率，让出CPU

        return True  # 等待成功完成

    def _get_command_while_previewing(self):
        """
        【已重构和修复】在工作线程内直接运行预览循环，不再创建独立的子线程。
        这可以避免对象生命周期冲突导致的 RuntimeError。
        """
        self.command_queue.queue.clear()
        last_spectrum = None

        # 获取当前任务的上下文，用于预览
        current_task = self.tasks[self.task_index]
        current_well_id = current_task['well_id']
        current_well_data = self.collected_data.get(current_well_id, {})

        # 收集所有已完成的结果谱用于汇总图
        all_completed_results = []
        for well_id, data in self.collected_data.items():
            all_completed_results.extend(data['absorbance'].values())

        # 在worker线程中直接循环，直到收到指令或任务停止
        while self.command_queue.empty() and self._is_running:
            # 1. 获取光谱
            _, spectrum = self.controller.get_spectrum()
            last_spectrum = spectrum

            # 2. 发射预览信号
            data_package = {
                "full_wavelengths": self.wavelengths,  # 用于原始信号图
                "live_signal": spectrum,
                "background": current_well_data.get('background'),
                "reference": current_well_data.get('reference'),

                "result_wavelengths": self.cropped_wavelengths,  # 用于结果和汇总图
                "all_results": all_completed_results  # 结果数据本身已是裁切后的
            }
            self.live_preview_data.emit(data_package)

            # 3. 短暂休眠，让出CPU给其他操作，并控制刷新率
            QThread.msleep(50)

        # 循环结束后，从队列中获取指令
        command = 'STOP'  # 默认为停止
        if self._is_running:
            try:
                # 尝试无阻塞地获取指令
                command = self.command_queue.get_nowait()
            except queue.Empty:
                # 如果队列为空但_is_running仍为True，说明可能存在逻辑问题，但我们先安全退出
                print("警告: 预览循环退出，但指令队列为空。")

        return last_spectrum, command

    def _generate_tasks(self):
        # (此函数无变化)
        well_ids = sorted(self.layout_data.keys())
        for well_id in well_ids:
            self.tasks.append({'type': 'background', 'well_id': well_id})
            self.tasks.append({'type': 'reference', 'well_id': well_id})
            for point_num in range(1, self.points_per_well + 1):
                self.tasks.append({'type': 'signal', 'well_id': well_id, 'point_num': point_num})
            self.tasks.append({'type': 'save', 'well_id': well_id})

    def run(self):
        """【最终架构版】基于指令队列的主循环"""
        try:
            folder_timestamp = time.strftime("%Y%m%d-%H%M%S")
            run_output_folder = os.path.join(self.output_folder, f"BatchRun_{folder_timestamp}")
            os.makedirs(run_output_folder, exist_ok=True)

            self._generate_tasks()
            total_tasks = len(self.tasks)

            while self.task_index < total_tasks and self._is_running:
                task = self.tasks[self.task_index]
                well_id = task['well_id']
                task_type = task['type']

                # 1. 更新UI（此部分逻辑不变）
                if task_type == 'background':
                    self.update_dialog.emit(
                        {"instruction_key": "Please place [Background] for well {well_id}\\n(Live preview active...)",
                         "params": {"well_id": well_id}, "total_progress": int(self.task_index / total_tasks * 100),
                         "point_progress": 0, "button_text_key": "Collect Background",
                         "button_enabled": not self.is_auto_enabled,  # 自动模式下禁用按钮
                         "back_button_enabled": self.task_index > 0 and not self.is_auto_enabled})
                elif task_type == 'reference':
                    self.update_dialog.emit(
                        {"instruction_key": "Please place [Reference] for well {well_id}\\n(Live preview active...)",
                         "params": {"well_id": well_id}, "total_progress": int(self.task_index / total_tasks * 100),
                         "point_progress": 0, "button_text_key": "Collect Reference",
                         "button_enabled": not self.is_auto_enabled,
                         "back_button_enabled": not self.is_auto_enabled})
                elif task_type == 'signal':
                    point_num = task['point_num']
                    points_done = len(self.collected_data[well_id]['signals'])
                    self.update_dialog.emit({
                        "instruction_key": "Please move to well {well_id}, point {point_num}/{total_points}\\n(Live preview active...)",
                        "params": {"well_id": well_id, "point_num": point_num,
                                   "total_points": self.points_per_well},
                        "point_progress": int((points_done / self.points_per_well) * 100),
                        "total_progress": int(self.task_index / total_tasks * 100),
                        "button_text_key": "Collect this Point", "button_enabled": not self.is_auto_enabled,
                        "back_button_enabled": not self.is_auto_enabled})

                # 【核心修改】根据是否启用自动模式，决定是等待用户点击还是自动延时
                spectrum = None
                command = None

                if not self.is_auto_enabled:
                    # --- 手动模式 ---
                    spectrum, command = self._get_command_while_previewing()
                else:
                    # --- 自动模式 ---
                    # 确定延时时间
                    delay = self.intra_well_interval
                    # 切换孔位或保存数据时，使用更长的孔间间隔
                    if task_type in ['background', 'reference', 'save']:
                        delay = self.inter_well_interval

                    # 执行带预览的延时等待
                    if not self._timed_preview_wait(delay):
                        command = 'STOP'  # 如果等待被中止，则设置停止指令
                    else:
                        # 等待结束后，自动采集最后一次的光谱并继续
                        _, spectrum = self.controller.get_spectrum()
                        command = 'FORWARD'

                if command == 'STOP' or not self._is_running:
                    break

                # 3. 根据收到的指令处理状态 (此部分逻辑不变)
                if command == 'FORWARD':
                    if task_type == 'background':
                        self.collected_data[well_id]['background'] = spectrum
                    elif task_type == 'reference':
                        self.collected_data[well_id]['reference'] = spectrum
                    elif task_type == 'signal':
                        point_num = task['point_num']
                        self.collected_data[well_id]['signals'][point_num] = spectrum
                        bg = self.collected_data[well_id].get('background')
                        ref = self.collected_data[well_id].get('reference')
                        if self.wavelength_mask is not None:
                            spectrum_np = np.array(spectrum)
                            bg_np = np.array(bg) if bg is not None else None
                            ref_np = np.array(ref) if ref is not None else None
                            signal_cropped = spectrum_np[self.wavelength_mask]
                            bg_cropped = bg_np[self.wavelength_mask] if bg_np is not None else None
                            ref_cropped = ref_np[self.wavelength_mask] if ref_np is not None else None
                        else:
                            signal_cropped, bg_cropped, ref_cropped = spectrum, bg, ref
                        absorbance = _calculate_absorbance(signal_cropped, bg_cropped, ref_cropped)
                        if absorbance is not None:
                            self.collected_data[well_id]['absorbance'][point_num] = absorbance
                    elif task_type == 'save':
                        well_data = self.collected_data[well_id]
                        signals_list = [well_data['signals'][k] for k in sorted(well_data['signals'])]
                        absorbance_list = [well_data['absorbance'][k] for k in sorted(well_data['absorbance'])]
                        concentration = self.layout_data[well_id].get('concentration', 0.0)
                        timestamp = time.strftime("%Y%m%d-%H%M%S")
                        filename = f"{timestamp}_{well_id}_{concentration}nM{self.file_extension}"
                        output_path = os.path.join(run_output_folder, filename)
                        save_batch_spectrum_data(
                            file_path=output_path,
                            wavelengths=self.wavelengths,
                            absorbance_spectra=absorbance_list,
                            signals_list=signals_list,
                            background=well_data.get('background'),
                            reference=well_data.get('reference'),
                            crop_start_wl=self.crop_start_wl,
                            crop_end_wl=self.crop_end_wl
                        )
                    self.task_index += 1
                elif command == 'BACKWARD':
                    if self.task_index > 0:
                        task_to_undo = self.tasks[self.task_index - 1]
                        well_id_to_undo = task_to_undo['well_id']
                        type_to_undo = task_to_undo['type']
                        if type_to_undo == 'background':
                            self.collected_data[well_id_to_undo].pop('background', None)
                        elif type_to_undo == 'reference':
                            self.collected_data[well_id_to_undo].pop('reference', None)
                        elif type_to_undo == 'signal':
                            point_num = task_to_undo['point_num']
                            self.collected_data[well_id_to_undo]['signals'].pop(point_num, None)
                            self.collected_data[well_id_to_undo]['absorbance'].pop(point_num, None)
                        self.task_index -= 1

            if self._is_running: self.update_dialog.emit(
                {"instruction_key": "Batch acquisition complete!", "total_progress": 100, "point_progress": 100,
                 "button_text_key": "Done", "button_enabled": False, "back_button_enabled": False})

            try:
                if self._is_running:  # 只有在任务正常完成时才执行
                    print("正在生成最终结果汇总文件...")
                    all_results_data = {}

                    # 确保波长数据存在
                    if not hasattr(self.controller, 'wavelengths') or self.controller.wavelengths is None:
                        raise ValueError("无法获取有效的波长数据。")

                    wavelengths = np.array(self.controller.wavelengths)

                    # 1. 遍历所有收集到的数据，聚合结果谱
                    # 按孔位ID排序以保证列的顺序固定
                    sorted_well_ids = sorted(self.collected_data.keys())
                    for well_id in sorted_well_ids:
                        well_data = self.collected_data[well_id]
                        if 'absorbance' in well_data:
                            # 按点编号排序
                            sorted_points = sorted(well_data['absorbance'].keys())
                            for point_num in sorted_points:
                                absorbance_spectrum = well_data['absorbance'][point_num]
                                # 为每一列创建一个唯一的名称
                                column_name = f"{well_id}_Point_{point_num}"
                                all_results_data[column_name] = absorbance_spectrum

                    # 2. 如果收集到了结果，则创建DataFrame并保存
                    if all_results_data:
                        df_summary = pd.DataFrame(all_results_data)

                        # 将波长作为第一列插入
                        wavelengths_for_summary = self.cropped_wavelengths if self.wavelength_mask is not None else wavelengths
                        df_summary.insert(0, 'Wavelength', wavelengths_for_summary)

                        # 定义输出路径和文件名
                        summary_filename = f"batch_summary_all_results_{folder_timestamp}.xlsx"
                        summary_output_path = os.path.join(run_output_folder, summary_filename)

                        # 保存到Excel
                        df_summary.to_excel(summary_output_path, index=False, engine='openpyxl')
                        print(f"最终结果汇总文件已成功保存到: {summary_output_path}")
                    else:
                        print("未收集到任何结果光谱，跳过生成最终汇总文件。")

            except Exception as e:
                print(f"生成最终结果汇总文件时发生严重错误: {e}")
                self.error.emit(f"Failed to generate final summary file: {e}")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self._is_running = False
            self.finished.emit()