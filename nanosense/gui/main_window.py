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
        self.setWindowTitle(self.tr("Nanophotonics sensing detection data visualization analysis system"))
        self.setGeometry(100, 100, 1280, 800)

        self.app_settings = load_settings()
        self.translator = None
        initial_language = self.app_settings.get('language', 'en')
        self.current_language = self._load_translator(initial_language)

        # 保存硬件模式状态
        self.use_real_hardware = use_real_hardware
        self.analysis_windows = []
        self.db_explorer_window = None
        self.controller = None
        self._hardware_mode_warning_shown = False
        self._menu_bar = None

        self.db_manager = None
        self.current_project_id = None
        self.current_experiment_id = None
        self._initialize_database()
        self._find_or_create_default_project()

        # 直接在构造函数中尝试连接硬件
        requested_mode = self.use_real_hardware
        self.controller, fallback_attempted = self._establish_controller(requested_mode, allow_fallback=True)
        if not self.controller:
            if requested_mode and fallback_attempted:
                error_message = self.tr(
                    "Failed to initialize the spectrometer in both real-hardware and mock modes.\n"
                    "Please verify the hardware connection and the mock API configuration."
                )
            elif requested_mode:
                error_message = self.tr("Failed to connect to the real spectrometer.\n\nPlease verify:\n1. The device is connected via USB.\n2. The driver is installed correctly.")
            else:
                error_message = self.tr("Failed to start the mock API. Please check the code.")

            QMessageBox.critical(self, self.tr("Hardware Error"), error_message)
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, self.close)
            return

        self.processor = SpectrumProcessor(self.controller.wavelengths)

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
            warning_msg = self.tr(
                "No database path was found in the configuration. Database features will be unavailable."
            )
            print(warning_msg)
            QMessageBox.warning(
                self,
                self.tr("Database Warning"),
                self.tr(
                    "No database path was found in the configuration.\n"
                    "Open Settings -> Customize Parameters... to set the database file path and enable data archiving."
                )
            )
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
        self._menu_bar = menu

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

    def _sync_hardware_mode_action(self):
        menu = getattr(self, '_menu_bar', None)
        if menu and hasattr(menu, 'hardware_mode_action'):
            action = menu.hardware_mode_action
            action.blockSignals(True)
            action.setChecked(self.use_real_hardware)
            action.blockSignals(False)

    def _handle_controller_mode_change(self, actual_mode, requested_mode):
        if actual_mode == requested_mode:
            return

        was_real = requested_mode
        self.use_real_hardware = actual_mode
        self._sync_hardware_mode_action()

        if was_real and not actual_mode and not self._hardware_mode_warning_shown:
            QMessageBox.warning(
                self,
                self.tr("Hardware Warning"),
                self.tr("Real hardware connection failed. The application will continue using the mock API.")
            )
            self._hardware_mode_warning_shown = True

        print(f"Hardware mode adjusted to {'Real Hardware' if actual_mode else 'Mock API'} automatically.")

    def _establish_controller(self, requested_mode, allow_fallback=True):
        """
        尝试根据请求的硬件模式建立控制器实例。
        :param requested_mode: True 表示真实硬件，False 表示模拟模式
        :param allow_fallback: 当真实硬件失败时是否尝试自动回退到模拟模式
        :return: (controller, fallback_attempted)
        """
        fallback_attempted = False

        if requested_mode:
            self._hardware_mode_warning_shown = False

        controller = FX2000Controller.connect(use_real_hardware=requested_mode)
        if controller:
            actual_mode = bool(getattr(controller, 'is_real_hardware', requested_mode))
            self._handle_controller_mode_change(actual_mode, requested_mode)
            return controller, fallback_attempted

        if requested_mode and allow_fallback:
            fallback_attempted = True
            controller = FX2000Controller.connect(use_real_hardware=False)
            if controller:
                self._handle_controller_mode_change(False, requested_mode)
                return controller, fallback_attempted

        return None, fallback_attempted

    def _setup_initial_state(self):
        """根据传入的硬件模式，设置复选框的初始状态。"""
        self._sync_hardware_mode_action()

    def _handle_hardware_mode_change(self, checked):
        """Handle hardware mode toggle from the menu."""
        previous_mode = self.use_real_hardware
        if checked != previous_mode:
            reply = QMessageBox.information(
                self,
                self.tr("Restart Required"),
                self.tr("Switching hardware mode requires restarting the application.\n\nClick 'OK' to return to the launcher."),
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Ok
            )

            if reply == QMessageBox.Ok:
                self.use_real_hardware = checked
                if self.use_real_hardware:
                    self._hardware_mode_warning_shown = False
                self._sync_hardware_mode_action()
                self._request_restart()
            else:
                self._sync_hardware_mode_action()

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
        requested_mode = self.use_real_hardware
        controller, fallback_attempted = self._establish_controller(requested_mode, allow_fallback=True)
        self.controller = controller
        if not self.controller:
            if requested_mode and fallback_attempted:
                error_message = self.tr(
                    "Failed to initialize the spectrometer in both real-hardware and mock modes.\n"
                    "Please verify the hardware connection and the mock API configuration."
                )
            elif requested_mode:
                error_message = self.tr("Failed to connect to the real spectrometer.\n\nPlease verify:\n1. The device is connected via USB.\n2. The driver is installed correctly.")
            else:
                error_message = self.tr("Failed to start the mock API. Please check the code.")

            QMessageBox.critical(self, self.tr("Hardware Error"), error_message)
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
            name = os.path.basename(file_path) if file_path else self.tr("Loaded Spectrum")
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
            self,
            self.tr("Select Folder Containing Spectra Files"),
            default_load_path
        )
        if not dir_path:
            return

        spectra_list = load_spectra_from_path(dir_path, mode='folder')

        if spectra_list:
            print(self.tr("Successfully loaded {0} spectra from the selected folder.").format(len(spectra_list)))
            win = AnalysisWindow(spectra_data=spectra_list, parent=self)
            self.analysis_windows.append(win)
            win.show()
        else:
            QMessageBox.warning(
                self,
                self.tr("Info"),
                self.tr("No spectra were found in the selected folder.")
            )

    def _trigger_import_multiple_from_file(self):
        """专门处理从单个多列文件导入的逻辑。"""
        # 【核心修复】获取并使用默认加载路径
        default_load_path = self.app_settings.get('default_load_path', '')
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Choose a multi-column spectra file"),
            default_load_path,
            self.tr("Data Files (*.xlsx *.xls *.csv *.txt)")
        )
        if not file_path:
            return

        spectra_list = load_spectra_from_path(file_path, mode='file')

        if spectra_list:
            print(self.tr("Successfully loaded {0} spectra from the selected file.").format(len(spectra_list)))
            win = AnalysisWindow(spectra_data=spectra_list, parent=self)
            self.analysis_windows.append(win)
            win.show()
        else:
            QMessageBox.warning(
                self,
                self.tr("Info"),
                self.tr("No spectra could be loaded from the selected file.")
            )

    def _trigger_find_peaks(self):
        if self.stacked_widget.currentWidget() is self.measurement_page:
            self.measurement_page._find_all_peaks()
        else:
            print(self.tr("Please switch to the measurement page before using the peak finding feature."))

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

            QMessageBox.information(
                self,
                self.tr("Success"),
                self.tr("Default paths have been saved.")
            )

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
        QMessageBox.information(
            self,
            self.tr("Info"),
            self.tr("Feature '{feature_name}' is under development.").format(feature_name=feature_name)
        )

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
            QMessageBox.warning(
                self,
                self.tr("Error"),
                self.tr("A valid output folder must be selected.")
            )
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
        self.batch_worker.error.connect(
            lambda msg: QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr(msg) if isinstance(msg, str) else msg
            )
        )
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
        if result == QDialog.Accepted and getattr(self.batch_worker, 'run_status', None) == 'completed':
            reply = QMessageBox.question(
                self,
                self.tr("Task Complete"),
                self.tr(
                    "Batch acquisition finished. Data saved to:\n{output_folder}\n\n"
                    "Would you like to run batch analysis now?"
                ).format(output_folder=output_folder),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Yes:
                analysis_dialog = DataAnalysisDialog(self, initial_folder=output_folder)
                analysis_dialog.exec_()

    def _abort_batch_task(self):
        """Abort batch acquisition and fully reset the hardware controller."""
        print("正在中止批量采集任务...")
        if hasattr(self, 'batch_worker') and self.batch_worker:
            self.batch_worker.stop()

        print("正在执行硬件控制器断开连接...")
        FX2000Controller.disconnect()

        time.sleep(0.2)

        print("正在重新连接硬件控制器...")
        requested_mode = self.use_real_hardware
        controller, fallback_attempted = self._establish_controller(requested_mode, allow_fallback=True)
        self.controller = controller

        if not self.controller:
            if requested_mode and fallback_attempted:
                message = self.tr("Hardware reconnection failed in both real and mock modes. Please restart the application.")
            elif requested_mode:
                message = self.tr("Hardware reconnection failed in real mode. Please restart the application.")
            else:
                message = self.tr("Mock API reconnection failed. Please restart the application.")
            QMessageBox.critical(self, self.tr("Critical Error"), message)
            self.close()
        else:
            self.measurement_page.controller = self.controller
            self.processor.wavelengths = self.controller.wavelengths
            print("硬件重置并重新连接成功")

    def _on_batch_acquisition_finished(self):
        """
        当批量采集工作线程完成其任务后，此槽函数被调用。
        """
        # 1. 检查对话框是否存在并关闭它
        if hasattr(self, 'run_dialog') and self.run_dialog:
            self.run_dialog.accept()  # accept()会关闭对话框并设置result为Accepted

        # 2. 检查任务是否是正常完成的（即用户没有点击中止）
        # self.batch_worker 此时可能已经被 deleteLater 清理，需要检查
        if hasattr(self, 'batch_worker') and self.batch_worker and getattr(self.batch_worker, 'run_status', None) == 'completed':

            output_folder = self.batch_worker.output_folder

            reply = QMessageBox.question(
                self,
                self.tr("Task Complete"),
                self.tr(
                    "Batch acquisition finished. Data saved to:\n{output_folder}\n\n"
                    "Would you like to run batch analysis now?"
                ).format(output_folder=output_folder),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

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

    def _load_translator(self, language: str) -> str:
        """
        Install translator for the requested language and return the language that was actually applied.
        """
        app = QApplication.instance()
        if app is None:
            return 'en'

        if self.translator:
            app.removeTranslator(self.translator)

        self.translator = None
        if language == 'zh':
            translation_path = os.path.join('nanosense', 'translations', 'chinese.qm')
            translator = QTranslator()
            if os.path.exists(translation_path) and translator.load(translation_path):
                app.installTranslator(translator)
                self.translator = translator
                print("Chinese translation loaded.")
                return 'zh'
            print(f"Warning: Chinese translation file not found or failed to load from {translation_path}.")
        return 'en'

    def _switch_language(self, language):
        """
        加载并安装指定语言的翻译文件，并手动更新所有UI。
        """
        applied_language = self._load_translator(language)

        # Step 4: update language toggle state
        is_chinese = (applied_language == "zh")
        self.menuBar().language_zh_action.setChecked(is_chinese)
        self.menuBar().language_en_action.setChecked(not is_chinese)

        # Step 5: persist selection
        self.app_settings["language"] = applied_language
        self.current_language = applied_language
        save_settings(self.app_settings)

        # Step 6: refresh all visible UI
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
        if hasattr(self, 'colorimetry_page') and hasattr(self.colorimetry_page, '_retranslate_ui'):
            self.colorimetry_page._retranslate_ui()
        for window in getattr(self, 'analysis_windows', []):
            if window and hasattr(window, '_retranslate_ui'):
                window._retranslate_ui()
        if getattr(self, 'db_explorer_window', None) and hasattr(self.db_explorer_window, '_retranslate_ui'):
            self.db_explorer_window._retranslate_ui()

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



