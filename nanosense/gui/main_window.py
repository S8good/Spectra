# nanosense/gui/main_window.py
import json
import os
import time
from PyQt5.QtWidgets import QMainWindow, QStackedWidget, QMessageBox, QDialog, QFileDialog, QAction, QApplication, QInputDialog
from .performance_dialog import PerformanceDialog
from .database_explorer import DatabaseExplorerDialog
from nanosense.utils.file_io import load_spectra_from_path
from nanosense.core.controller import FX2000Controller
from nanosense.core.spectrum_processor import SpectrumProcessor
from nanosense.utils.file_io import load_spectrum
from .affinity_analysis_dialog import AffinityAnalysisDialog
from .analysis_window import AnalysisWindow
from .colorimetry_widget import ColorimetryWidget
from .data_analysis_dialog import DataAnalysisDialog
from .kobs_linearization_dialog import KobsLinearizationDialog
from .measurement_widget import MeasurementWidget
from .menu_bar import MenuBar
from .plate_setup_dialog import PlateSetupDialog
from .sensitivity_dialog import SensitivityDialog
from .calibration_dialog import CalibrationDialog
from .noise_analysis_dialog import NoiseAnalysisDialog
from .three_file_import_dialog import ThreeFileImportDialog
from nanosense.core.batch_acquisition import BatchRunDialog, BatchAcquisitionWorker
from .batch_setup_dialog import BatchSetupDialog
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTranslator
from .batch_report_dialog import BatchReportDialog
from .settings_dialog import SettingsDialog
from .about_dialog import AboutDialog
from .mock_api_config_dialog import MockAPIConfigDialog
from ..core.database_manager import DatabaseManager
from ..utils.config_manager import load_settings, save_settings

class AppWindow(QMainWindow):
    restart_requested = pyqtSignal(bool)

    def __init__(self, use_real_hardware=True):
        super().__init__()
        self.setWindowTitle("Nanophotonics sensing detection data visualization analysis system")
        self.setGeometry(100, 100, 1280, 800)

        self.app_settings = load_settings()

        # 保存硬件模式状态
        self.use_real_hardware = use_real_hardware
        self.analysis_windows = []
        self.db_explorer_window = None
        self.controller = None

        self.db_manager = None
        self.current_project_id = None
        self.current_experiment_id = None
        self._initialize_database()
        self._find_or_create_default_project()

        # 直接在构造函数中尝试连接硬件
        self.controller = FX2000Controller.connect(use_real_hardware=self.use_real_hardware)
        if not self.controller:
            # 根据硬件模式显示不同的错误信息
            if self.use_real_hardware:
                error_message = "连接真实硬件失败！\n\n请检查以下几点：\n1. 光谱仪是否已通过USB正确连接。\n2. 设备驱动是否已正确安装。"
            else:
                error_message = "启动模拟API失败，请检查代码。"

            QMessageBox.critical(self, "硬件错误", error_message)
            # 使用 QTimer 确保窗口在显示错误后能安全关闭
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, self.close)
            return

        self.processor = SpectrumProcessor(self.controller.wavelengths)

        self.translator = QTranslator()

        self._create_global_actions()
        self.init_ui()
        self.apply_styles()  # 保持你原有的样式加载
        self._setup_initial_state()

        self._setup_initial_language()
    # 【新增】初始化数据库连接
    def _initialize_database(self):
        db_path = self.app_settings.get('database_path')
        if db_path:
            self.db_manager = DatabaseManager(db_path)
        else:
            print("警告：未在配置中找到数据库路径，数据库功能将不可用。")
            QMessageBox.warning(self, "数据库警告",
                                "未在配置文件中找到数据库路径。\n"
                                "请通过 Settings -> Customize Parameters... 设置数据库文件路径以启用数据归档功能。")
    # 【新增】查找或创建默认项目
    def _find_or_create_default_project(self):
        if self.db_manager:
            project_name = "Default Project"
            self.current_project_id = self.db_manager.find_or_create_project(
                name=project_name,
                description="Default project for general experiments."
            )
            print(f"当前项目已设置为 '{project_name}' (ID: {self.current_project_id})")
    # 【新增】获取当前实验ID，如果不存在则创建
    def get_or_create_current_experiment_id(self):
        """获取当前实验ID，如果不存在则创建。现在增加了对项目ID的检查。"""
        if not self.db_manager:
            return None

        # 【新增】双重检查，确保在创建实验前，项目ID是有效的
        if self.current_project_id is None:
            self._find_or_create_default_project()
            if self.current_project_id is None:
                QMessageBox.critical(self, self.tr("Database Error"), self.tr("Failed to find or create a default project. Cannot save experiment."))
                return None

        if self.current_experiment_id is None:
            text, ok = QInputDialog.getText(self, self.tr("New Experiment"),
                                            self.tr("Please name this new experiment session:"))
            if ok and text:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                config_snapshot = json.dumps({
                    'integration_time': self.measurement_page.integration_time_spinbox.value(),
                    'mode': self.measurement_page.mode_name
                })

                self.current_experiment_id = self.db_manager.create_experiment(
                    project_id=self.current_project_id,
                    name=text,
                    exp_type="Single Measurement",
                    timestamp=timestamp,
                    config_snapshot=config_snapshot
                )
                print(f"新实验 '{text}' 已创建，ID: {self.current_experiment_id}")
            else:
                return None  # 用户取消

        return self.current_experiment_id

    def _create_global_actions(self):
        self.go_home_action = QAction(self.tr('Back to Welcome Screen'), self)
        self.go_home_action.setShortcut('Ctrl+H')
        self.go_home_action.setShortcutContext(Qt.ApplicationShortcut)
        self.exit_action = QAction(self.tr('Exit'), self)
        self.exit_action.setShortcut('Ctrl+Q')
        self.exit_action.setShortcutContext(Qt.ApplicationShortcut)

    def init_ui(self):
        # 【修改】创建MenuBar时，将全局Action传递进去
        self.setMenuBar(MenuBar(self.go_home_action, self.exit_action, self))

        self._connect_menu_signals()
        self.stacked_widget = QStackedWidget(self)
        self.setCentralWidget(self.stacked_widget)
        self.measurement_page = MeasurementWidget(controller=self.controller, processor=self.processor, parent=self)
        self.colorimetry_page = ColorimetryWidget(parent=self)
        self.stacked_widget.addWidget(self.measurement_page)
        self.stacked_widget.addWidget(self.colorimetry_page)
        self.measurement_page.back_button.hide()

    def _connect_menu_signals(self):
        menu = self.menuBar()

        menu.hardware_mode_action.toggled.connect(self._handle_hardware_mode_change)

        menu.import_spectra_action.triggered.connect(self._trigger_import_single_spectrum)
        menu.import_three_file_action.triggered.connect(self._trigger_import_three_files)
        menu.import_from_folder_action.triggered.connect(self._trigger_import_multiple_from_folder)
        menu.import_from_file_action.triggered.connect(self._trigger_import_multiple_from_file)

        menu.go_home_action.setEnabled(True)
        self.go_home_action.triggered.connect(self._request_restart)
        self.exit_action.triggered.connect(self.close)

        menu.batch_report_action.triggered.connect(self._open_batch_report_dialog)
        menu.sensitivity_action.triggered.connect(self._open_sensitivity_dialog)
        menu.affinity_action.triggered.connect(self._open_affinity_analysis_dialog)
        menu.kobs_linear_action.triggered.connect(self._open_kobs_linearization_dialog)
        menu.import_noise_action.triggered.connect(self._open_noise_analysis_dialog)
        menu.realtime_noise_action.triggered.connect(self._trigger_realtime_noise_analysis)
        menu.calibration_action.triggered.connect(self._open_calibration_dialog)
        menu.performance_action.triggered.connect(self._open_performance_dialog)

        menu.batch_acquisition_action.triggered.connect(self._start_batch_acquisition)
        menu.data_analysis_action.triggered.connect(self._open_data_analysis_dialog)
        menu.database_explorer_action.triggered.connect(self._open_database_explorer)

        menu.language_zh_action.triggered.connect(lambda: self._switch_language('zh'))
        menu.language_en_action.triggered.connect(lambda: self._switch_language('en'))

        if hasattr(menu, 'default_paths_action'):
            menu.default_paths_action.triggered.connect(self._open_settings_dialog)

        if hasattr(menu, 'mock_api_config_action'):
            menu.mock_api_config_action.triggered.connect(self._open_mock_api_config_dialog)

        menu.about_action.triggered.connect(self._show_about_dialog)

        self.addAction(menu.go_home_action)
        self.addAction(menu.exit_action)

    def _open_performance_dialog(self, slope=None):
        """打开检测性能分析对话框，可以选择性地传入斜率。"""
        dialog = PerformanceDialog(main_window=self, parent=self, slope=slope)
        dialog.exec_()

    def _setup_initial_state(self):
        """根据传入的硬件模式，设置复选框的初始状态。"""
        self.menuBar().hardware_mode_action.setChecked(self.use_real_hardware)

    def _handle_hardware_mode_change(self, checked):
        """当用户点击 'Use Real Hardware' 复选框时被调用。"""
        # 检查新状态是否与当前状态不同
        if checked != self.use_real_hardware:
            reply = QMessageBox.information(
                self,
                "需要重启",
                "切换硬件模式需要重新启动应用程序。\n\n点击 'OK' 将返回到启动器。",
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Ok
            )

            if reply == QMessageBox.Ok:
                self._request_restart()  # 调用重启方法
            else:
                # 如果用户取消，将复选框恢复到原始状态
                menu_bar = self.menuBar()
                menu_bar.hardware_mode_action.blockSignals(True)
                menu_bar.hardware_mode_action.setChecked(self.use_real_hardware)
                menu_bar.hardware_mode_action.blockSignals(False)

    def _request_restart(self):
        if self.controller:
            self.controller.disconnect()
        self.restart_requested.emit(self.use_real_hardware)
        self.close()

    def switch_to_initial_view(self, mode_name):
        print(f"主窗口接收到初始模式: {mode_name}")

        if mode_name == "Color":
            self.stacked_widget.setCurrentWidget(self.colorimetry_page)
        else:
            self.measurement_page.set_mode(mode_name)
            self.stacked_widget.setCurrentWidget(self.measurement_page)

    def connect_hardware(self):
        self.controller = FX2000Controller.connect(use_real_hardware=self.use_real_hardware)
        if not self.controller:
            # 【新增】根据硬件模式显示不同的错误信息
            if self.use_real_hardware:
                # 这是你想要的提示信息
                error_message = "连接真实硬件失败！\n\n请检查以下几点：\n1. 光谱仪是否已通过USB正确连接。\n2. 设备驱动是否已正确安装。"
            else:
                error_message = "启动模拟API失败，请检查代码。"

            QMessageBox.critical(self, "硬件错误", error_message)
            return False
        return True

    def apply_styles(self):
        self.setStyleSheet("""
                    
                    /* ===== Global Settings ===== */
                    QMainWindow, QDialog, QWidget {
                        background-color: #1A202C; /* 深蓝灰色背景 */
                        color: #E2E8F0; /* 柔和的白色文字 */
                        font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
                        font-size: 14px;
                    }
                    
                    /* ===== Main Content Panel Style  ===== */
                    #plotsContainer {
                        background-color: #2D3748; /* 使用一个比主背景稍亮的颜色 */
                        border-radius: 8px;      /* 添加圆角使其看起来更柔和 */
                    }
                    /* ===== Custom CollapsibleBox Style ===== */
                    CollapsibleBox {
                        /* 为整个控件设置外边距，创造呼吸感 */
                        margin-bottom: 4px; 
                    }
                    
                    CollapsibleBox > QToolButton {
                        background-color: #2D3748; /* 标题栏背景色 */
                        border: 1px solid #4A5568;
                        border-radius: 4px;
                        font-weight: bold;
                        font-size: 15px;
                        padding: 8px; /* 加大内边距 */
                        color: #CBD5E0;
                        text-align: left; /* 文字居左 */
                    }
                    
                    CollapsibleBox > QScrollArea {
                        background-color: #2D3748;
                        border: none;
                        border-top: 1px solid #4A5568; /* 只保留上边框作为分割线 */
                        margin: 0px 5px 0px 5px; /* 左右留出一些边距 */
                    }

                    /* ===== GroupBox & Custom CollapsibleBox ===== */
                    QGroupBox {
                        background-color: #2D3748; /* 稍亮的面板背景 */
                        border: 1px solid #4A5568;
                        border-radius: 8px;
                        margin-top: 1em;
                        padding: 10px;
                    }
                    QGroupBox::title {
                        subcontrol-origin: margin;
                        subcontrol-position: top center;
                        padding: 0 10px;
                        color: #A0AEC0;
                    }
                    /* Style for your CollapsibleBox's button */
                    CollapsibleBox > QToolButton {
                        background-color: #2D3748;
                        border: 1px solid #4A5568;
                        border-radius: 4px;
                        font-weight: bold;
                        padding: 5px;
                        color: #CBD5E0;
                    }

                    /* ===== Buttons ===== */
                    QPushButton {
                        background-color: #3182CE; /* 蓝色主调 */
                        color: white;
                        font-weight: bold;
                        border: none;
                        border-radius: 4px;
                        padding: 8px 16px;
                    }
                    QPushButton:hover {
                        background-color: #2B6CB0;
                    }
                    QPushButton:pressed {
                        background-color: #2C5282;
                    }
                    QPushButton:disabled {
                        background-color: #4A5568;
                        color: #A0AEC0;
                    }

                    /* ===== Input Widgets ===== */
                    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                        background-color: #2D3748;
                        color: #E2E8F0;
                        border: 1px solid #4A5568;
                        border-radius: 4px;
                        padding: 5px;
                    }
                    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
                        border: 1px solid #3182CE; /* 焦点状态时高亮 */
                    }
                    QComboBox::drop-down {
                        border: none;
                    }
                    QComboBox::down-arrow {
                        image: url(nanosense/gui/assets/down_arrow.svg); /* (需要一个白色向下箭头SVG图标) */
                    }
                    QComboBox QAbstractItemView {
                        background-color: #2D3748;
                        color: #E2E8F0;
                        border: 1px solid #4A5568;
                        selection-background-color: #3182CE; /* 选中项的背景色 */
                    }

                    /* ===== Table & List ===== */
                    QTableWidget, QListWidget {
                        background-color: #2D3748;
                        border: 1px solid #4A5568;
                        border-radius: 4px;
                        gridline-color: #4A5568;
                    }
                    QHeaderView::section {
                        background-color: #1A202C;
                        color: #A0AEC0;
                        padding: 4px;
                        border: 1px solid #4A5568;
                    }
                    QTableWidget::item, QListWidget::item {
                        padding: 5px;
                    }
                    QTableWidget::item:selected, QListWidget::item:selected {
                        background-color: #3182CE;
                        color: white;
                    }

                    /* ===== Scroll Bars ===== */
                    QScrollBar:vertical {
                        border: none;
                        background: #2D3748;
                        width: 10px;
                        margin: 0px 0px 0px 0px;
                    }
                    QScrollBar::handle:vertical {
                        background: #4A5568;
                        min-height: 20px;
                        border-radius: 5px;
                    }
                    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                        height: 0px;
                    }
                    QScrollBar:horizontal {
                         border: none;
                         background: #2D3748;
                         height: 10px;
                         margin: 0px 0px 0px 0px;
                    }
                    QScrollBar::handle:horizontal {
                         background: #4A5568;
                         min-width: 20px;
                         border-radius: 5px;
                    }
                     QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                        width: 0px;
                    }
                    /* ===== Tab Widget Style (新增) ===== */
                    QTabWidget::pane { /* Tab页的边框和背景 */
                        border: 1px solid #4A5568;
                        border-top: none; /* 顶部边框由Tab按钮提供，此处去掉 */
                        border-radius: 0 0 4px 4px;
                    }

                    QTabBar::tab { /* Tab按钮的样式 */
                        background-color: #2D3748; /* 未选中时的背景色 */
                        color: #A0AEC0; /* 未选中时的文字颜色 */
                        border: 1px solid #4A5568;
                        border-bottom: none; /* 底边框去掉，与pane连接 */
                        padding: 8px 16px;
                        border-top-left-radius: 4px;
                        border-top-right-radius: 4px;
                    }

                    QTabBar::tab:selected { /* Tab按钮被选中时的样式 */
                        background-color: #1A202C; /* 选中时使用更深的背景色，与主窗口融合 */
                        color: white; /* 选中时使用更亮的文字颜色 */
                        border-bottom: 1px solid #1A202C; /* 覆盖pane的上边框，实现融合效果 */
                    }

                    QTabBar::tab:hover { /* 鼠标悬停在Tab按钮上时 */
                        background-color: #384253;
                    }
                    
                    /* ===== Menu Bar Style (新增) ===== */
                    QMenuBar {
                        background-color: #1A202C; /* 匹配主窗口背景色 */
                        color: #E2E8F0;
                        border-bottom: 1px solid #4A5568; /* 底部加一条细微分割线，增加层次感 */
                    }
                    
                    QMenuBar::item {
                        background-color: transparent;
                        padding: 5px 10px;
                        margin: 2px;
                    }
                    
                    QMenuBar::item:selected { /* 当鼠标悬停或选中顶级菜单项时 */
                        background-color: #2D3748; /* 使用面板的背景色作为高亮 */
                        color: white;
                        border-radius: 4px;
                    }
                    
                    QMenu { /* 下拉菜单本身的样式 */
                        background-color: #2D3748;
                        color: #E2E8F0;
                        border: 1px solid #4A5568;
                    }
                    
                    QMenu::item {
                        padding: 8px 25px; /* 为下拉菜单项提供更多空间 */
                    }
                    
                    QMenu::item:selected { /* 当鼠标悬停或选中下拉菜单里的项目时 */
                        background-color: #3182CE; /* 使用我们的主题蓝色作为高亮 */
                        color: white;
                    }
                    
                    QMenu::separator {
                        height: 1px;
                        background-color: #4A5568;
                        margin: 5px 0px;
                    }
                    
                """)

    def closeEvent(self, event):
        # 【修改】在关闭前关闭数据库连接
        if self.db_manager:
            self.db_manager.close()
            print("数据库连接已关闭。")
        if hasattr(self, 'measurement_page'):
            self.measurement_page.stop_all_activities()
        print("程序退出...")
        event.accept()

    def _trigger_import_single_spectrum(self):
        # 【核心修复】从全局设置中获取默认加载路径
        default_load_path = self.app_settings.get('default_load_path', '')

        # 【核心修复】将获取到的路径传递给文件加载函数
        x_data, y_data, file_path = load_spectrum(self, default_load_path)

        if x_data is not None:
            name = os.path.basename(file_path) if file_path else "Loaded Spectrum"
            single_spectrum_data = {'x': x_data, 'y': y_data, 'name': name}
            analysis_win = AnalysisWindow(spectra_data=single_spectrum_data, parent=self)
            self.analysis_windows.append(analysis_win)
            analysis_win.show()

    def _trigger_import_three_files(self):
        dialog = ThreeFileImportDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # 【关键】这里调用的是 get_data()，获取的是一个包含所有光谱的字典
            all_data = dialog.get_data()
            if all_data and all_data.get('result'):
                # 将这个包含所有数据的【完整字典】传递给 AnalysisWindow
                analysis_win = AnalysisWindow(spectra_data=all_data, parent=self)
                self.analysis_windows.append(analysis_win)
                analysis_win.show()

    def _trigger_import_multiple_from_folder(self):
        """专门处理从文件夹导入的逻辑。"""
        # 【核心修复】获取并使用默认加载路径
        default_load_path = self.app_settings.get('default_load_path', '')
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择包含光谱文件的文件夹", default_load_path
        )
        if not dir_path:
            return

        spectra_list = load_spectra_from_path(dir_path, mode='folder')

        if spectra_list:
            print(f"成功从文件夹加载了 {len(spectra_list)} 条光谱曲线。")
            win = AnalysisWindow(spectra_data=spectra_list, parent=self)
            self.analysis_windows.append(win)
            win.show()
        else:
            QMessageBox.warning(self, "提示", "所选文件夹中未找到可加载的光谱文件。")

    def _trigger_import_multiple_from_file(self):
        """专门处理从单个多列文件导入的逻辑。"""
        # 【核心修复】获取并使用默认加载路径
        default_load_path = self.app_settings.get('default_load_path', '')
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择一个多列光谱文件", default_load_path, "Data Files (*.xlsx *.xls *.csv *.txt)"
        )
        if not file_path:
            return

        spectra_list = load_spectra_from_path(file_path, mode='file')

        if spectra_list:
            print(f"成功从文件加载了 {len(spectra_list)} 条光谱曲线。")
            win = AnalysisWindow(spectra_data=spectra_list, parent=self)
            self.analysis_windows.append(win)
            win.show()
        else:
            QMessageBox.warning(self, "提示", "未能从所选文件中加载任何光谱数据。")

    def _trigger_find_peaks(self):
        if self.stacked_widget.currentWidget() is self.measurement_page:
            self.measurement_page._find_all_peaks()
        else:
            print("请先进入测量页面再使用寻峰功能。")

    def _open_data_analysis_dialog(self):
        dialog = DataAnalysisDialog(self)
        dialog.exec_()

    def _open_settings_dialog(self):
        """
        打开设置对话框，并处理返回结果。
        """
        dialog = SettingsDialog(self.app_settings, self)
        if dialog.exec_() == QDialog.Accepted:
            updated_settings = dialog.get_settings()
            self.app_settings.update(updated_settings)
            save_settings(self.app_settings)
            new_db_path = self.app_settings.get('database_path')
            if self.db_manager is None or self.db_manager.db_path != new_db_path:
                if self.db_manager:
                    self.db_manager.close()
                self.db_manager = DatabaseManager(new_db_path)
                self._find_or_create_default_project()
                QMessageBox.information(self, self.tr("Info"), self.tr(
                    "Database connection has been updated. A restart may be required for all features to use the new database."))

            QMessageBox.information(self, "成功", "默认路径设置已保存。")

    def _open_sensitivity_dialog(self):
        dialog = SensitivityDialog(self)
        dialog.exec_()

    def _open_calibration_dialog(self):
        dialog = CalibrationDialog(self)
        dialog.exec_()

    def _open_kobs_linearization_dialog(self):
        dialog = KobsLinearizationDialog(self)
        dialog.exec_()

    def _open_affinity_analysis_dialog(self):
        dialog = AffinityAnalysisDialog(self)
        dialog.exec_()

    def _open_batch_report_dialog(self):
        """打开一键生成分析报告的对话框。"""
        dialog = BatchReportDialog(self)
        dialog.exec_()

    def _trigger_realtime_noise_analysis(self):  # <--- 重新添加此方法
        if self.stacked_widget.currentWidget() is self.measurement_page:
            self.measurement_page.start_realtime_noise_analysis()
        else:
            QMessageBox.information(self, self.tr("Info"), self.tr(
                "Please switch to the measurement page to perform real-time noise analysis."))

    def _open_noise_analysis_dialog(self):
        dialog = NoiseAnalysisDialog(self)
        dialog.exec_()

    def _show_about_dialog(self):
        dialog = AboutDialog(self)
        dialog.exec_()

    def placeholder_function(self, feature_name):
        QMessageBox.information(self, "提示", f"功能 '{feature_name}' 正在开发中！")

    def _start_batch_acquisition(self):
        plate_setup_dialog = PlateSetupDialog(self)
        if plate_setup_dialog.exec_() != QDialog.Accepted:
            return
        layout_data = plate_setup_dialog.get_layout_data()
        if not layout_data:
            return

        batch_setup_dialog = BatchSetupDialog(self)
        if batch_setup_dialog.exec_() != QDialog.Accepted:
            return

        (output_folder, file_extension, points_per_well, crop_start, crop_end,
         is_auto_enabled, intra_well_interval, inter_well_interval) = batch_setup_dialog.get_settings()

        if not output_folder:
            QMessageBox.warning(self, "错误", "必须选择一个有效的输出文件夹。")
            return

        self.run_dialog = BatchRunDialog(self)
        self.batch_thread = QThread()

        # 【核心修复】将新的自动化参数传递给后台工作线程的构造函数
        self.batch_worker = BatchAcquisitionWorker(
            self.controller, layout_data, output_folder, file_extension,
            points_per_well=points_per_well,
            crop_start_wl=crop_start,
            crop_end_wl=crop_end,
            is_auto_enabled=is_auto_enabled,
            intra_well_interval=intra_well_interval,
            inter_well_interval=inter_well_interval
        )

        self.batch_worker.moveToThread(self.batch_thread)

        self.batch_thread.started.connect(self.batch_worker.run)
        self.batch_worker.finished.connect(self.batch_thread.quit)
        self.batch_worker.finished.connect(self.batch_worker.deleteLater)
        self.batch_thread.finished.connect(self.batch_thread.deleteLater)
        self.batch_worker.error.connect(lambda msg: QMessageBox.critical(self, "错误", msg))
        self.batch_worker.update_dialog.connect(self.run_dialog.update_state)
        self.batch_worker.live_preview_data.connect(self.run_dialog.update_all_plots)

        self.run_dialog.action_triggered.connect(self.batch_worker.trigger_action, Qt.DirectConnection)
        self.run_dialog.back_triggered.connect(self.batch_worker.go_back, Qt.DirectConnection)
        self.batch_thread.finished.connect(self.run_dialog.accept)

        self.batch_worker.finished.connect(self._on_batch_acquisition_finished)

        self.batch_thread.start()
        self.run_dialog.show()

        result = self.run_dialog.exec_()

        # 如果任务不是被用户中止的，而是正常完成的
        if result == QDialog.Accepted and self.batch_worker._is_running:
            reply = QMessageBox.question(self, '任务完成',
                                         f"批量采集已完成，数据已保存在:\n{output_folder}\n\n"
                                         "是否立即对这些数据进行批量分析？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)

            if reply == QMessageBox.Yes:
                analysis_dialog = DataAnalysisDialog(self, initial_folder=output_folder)
                analysis_dialog.exec_()

    def _abort_batch_task(self):
        """
        中止批量采集任务，并执行一个完整的硬件断开重连周期来确保驱动状态被重置。
        """
        print("正在中止批量采集任务...")
        # 1. 像之前一样，先停止Python线程的循环
        if hasattr(self, 'batch_worker') and self.batch_worker:
            self.batch_worker.stop()  # 这会设置标志位并调用 abort_endpoint_pipe

        # 2. 【关键】完全断开与硬件的连接
        print("正在执行硬件控制器断开连接...")
        FX2000Controller.disconnect()

        # 3. 等待一小段时间，给操作系统和驱动足够的时间来释放资源
        time.sleep(0.2)

        # 4. 【关键】立即重新连接，获取一个全新的、干净的控制器实例
        print("正在重新连接硬件控制器...")
        self.controller = FX2000Controller.connect(self.use_real_hardware)

        # 5. 检查重连是否成功，并更新软件中对控制器的引用
        if not self.controller:
            QMessageBox.critical(self, "严重错误", "中止后重新连接硬件失败，程序可能不稳定，建议重启。")
            self.close()
        else:
            # 更新测量页面和处理器持有的控制器实例
            self.measurement_page.controller = self.controller
            self.processor.wavelengths = self.controller.wavelengths
            print("硬件重置并重新连接成功。")

    def _on_batch_acquisition_finished(self):
        """
        当批量采集工作线程完成其任务后，此槽函数被调用。
        """
        # 1. 检查对话框是否存在并关闭它
        if hasattr(self, 'run_dialog') and self.run_dialog:
            self.run_dialog.accept()  # accept()会关闭对话框并设置result为Accepted

        # 2. 检查任务是否是正常完成的（即用户没有点击中止）
        # self.batch_worker 此时可能已经被 deleteLater 清理，需要检查
        if hasattr(self, 'batch_worker') and self.batch_worker and self.batch_worker._is_running:

            output_folder = self.batch_worker.output_folder

            reply = QMessageBox.question(self, '任务完成',
                                         f"批量采集已完成，数据已保存在:\n{output_folder}\n\n"
                                         "是否立即对这些数据进行批量分析？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)

            if reply == QMessageBox.Yes:
                # 自动打开批量分析对话框
                analysis_dialog = DataAnalysisDialog(self, initial_folder=output_folder)
                analysis_dialog.exec_()

    def update_run_dialog(self, status: dict):
        if "instruction" in status:
            self.run_dialog.instruction_label.setText(status["instruction"])
        if "total_progress" in status:
            self.run_dialog.total_progress_bar.setValue(status["total_progress"])
        if "point_progress" in status:
            self.run_dialog.point_progress_bar.setValue(status["point_progress"])
        if "button_text" in status:
            self.run_dialog.action_button.setText(status["button_text"])
        if "button_enabled" in status:
            self.run_dialog.action_button.setEnabled(status["button_enabled"])

    def _switch_language(self, language):
        """
        【已修复】加载并安装指定语言的翻译文件，并手动更新所有UI。
        修复了翻译文件路径错误的问题。
        """
        app = QApplication.instance()

        # 1. 移除旧的翻译器实例 (如果存在)
        if hasattr(self, 'translator'):
            app.removeTranslator(self.translator)

        # 2. 创建一个全新的、干净的翻译器实例
        self.translator = QTranslator()

        # 3. 如果目标语言是中文，则加载并安装新的翻译器
        if language == 'zh':
            # 【核心修复】修正了 .qm 文件的相对路径
            translation_path = os.path.join('nanosense', 'translations', 'chinese.qm')

            if os.path.exists(translation_path) and self.translator.load(translation_path):
                app.installTranslator(self.translator)
                print("Chinese translation loaded.")
            else:
                print(f"Warning: Chinese translation file not found or failed to load.")
                language = 'en'  # 加载失败，强制退回英文

        # 4. 更新菜单项的勾选状态
        is_chinese = (language == 'zh')
        self.menuBar().language_zh_action.setChecked(is_chinese)
        self.menuBar().language_en_action.setChecked(not is_chinese)

        # 5. 保存设置
        self.app_settings['language'] = language
        save_settings(self.app_settings)

        # 6. 手动触发所有UI的文本刷新
        self._retranslate_ui()

    def _retranslate_ui(self):
        """
        重新翻译当前窗口的所有UI文本。
        """
        print("Retranslating UI...")
        self.setWindowTitle(self.tr("Nanophotonics sensing detection data visualization analysis system"))

        # 重新翻译全局Action的文本
        self.go_home_action.setText(self.tr('Back to Welcome Screen'))
        self.exit_action.setText(self.tr('Exit'))

        # 重新翻译菜单栏
        if hasattr(self.menuBar(), '_retranslate_ui'):
            self.menuBar()._retranslate_ui()

        # 命令子页面也进行自我翻译
        if hasattr(self, 'measurement_page') and hasattr(self.measurement_page, '_retranslate_ui'):
            self.measurement_page._retranslate_ui()

    def _setup_initial_language(self):
        """
        在程序启动时，根据配置文件设置初始语言。
        """
        # 从设置中读取保存的语言，如果不存在，则默认为 'en' (英文)
        language = self.app_settings.get('language', 'en')

        # 根据读取到的语言，设置菜单项的勾选状态
        if language == 'zh':
            self.menuBar().language_zh_action.setChecked(True)
        else:
            self.menuBar().language_en_action.setChecked(True)

        # 调用语言切换函数，以确保程序启动时就加载正确的翻译
        self._switch_language(language)

    def _open_mock_api_config_dialog(self):
        """
        打开模拟API配置对话框，并在用户确认后保存设置。
        """
        dialog = MockAPIConfigDialog(self.app_settings, self)
        if dialog.exec_() == QDialog.Accepted:
            self.app_settings.update(dialog.get_settings())
            save_settings(self.app_settings)
            QMessageBox.information(self,
                                    self.tr("Restart Required"),
                                    self.tr(
                                        "Mock API settings have been saved. Please restart the application in mock mode for the changes to take effect."))

    def _open_database_explorer(self):
        """【修改】以非模态方式打开数据库浏览器，并防止重复打开。"""
        if not self.db_manager:
            QMessageBox.warning(self, self.tr("Database Error"),
                                self.tr("Database is not connected. Please check the settings."))
            return

        # 如果窗口已经打开，则直接激活并显示在最前端，而不是创建新的
        if self.db_explorer_window and self.db_explorer_window.isVisible():
            self.db_explorer_window.activateWindow()
            return

        # 创建新实例并将其存储在 self.db_explorer_window 中
        self.db_explorer_window = DatabaseExplorerDialog(parent=self)
        self.db_explorer_window.load_spectra_requested.connect(self._open_analysis_window_from_db)

        # 使用 .show() 而不是 .exec_()
        self.db_explorer_window.show()

    def _open_analysis_window_from_db(self, spectra_list):
        """根据从数据库加载的光谱列表，创建一个新的分析窗口。"""
        if not spectra_list:
            return

        print(f"从数据库加载了 {len(spectra_list)} 条光谱，正在打开分析窗口...")

        # 创建并显示 AnalysisWindow 来展示这些数据
        analysis_win = AnalysisWindow(spectra_data=spectra_list, parent=self)
        self.analysis_windows.append(analysis_win)
        analysis_win.show()
