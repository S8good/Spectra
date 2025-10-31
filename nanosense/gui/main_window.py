# nanosense/gui/main_window.py

import json

import os

import time
from typing import Any, Dict, List, Optional
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



        # ±£´æÓ²¼þÄ£Ê½×´Ì¬

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



        # Ö±½ÓÔÚ¹¹Ôìº¯ÊýÖÐ³¢ÊÔÁ¬½ÓÓ²¼þ

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

        self.apply_styles()  # ±£³ÖÄãÔ­ÓÐµÄÑùÊ½¼ÓÔØ

        self._setup_initial_state()



        self._setup_initial_language()

    # ¡¾ÐÂÔö¡¿³õÊ¼»¯Êý¾Ý¿âÁ¬½Ó

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

    # ¡¾ÐÂÔö¡¿²éÕÒ»ò´´½¨Ä¬ÈÏÏîÄ¿

    def _find_or_create_default_project(self):

        if self.db_manager:

            project_name = "Default Project"

            self.current_project_id = self.db_manager.find_or_create_project(

                name=project_name,

                description="Default project for general experiments."

            )

            print(f"µ±Ç°ÏîÄ¿ÒÑÉèÖÃÎª '{project_name}' (ID: {self.current_project_id})")

    # ¡¾ÐÂÔö¡¿»ñÈ¡µ±Ç°ÊµÑéID£¬Èç¹û²»´æÔÚÔò´´½¨

    def get_or_create_current_experiment_id(self):

        """»ñÈ¡µ±Ç°ÊµÑéID£¬Èç¹û²»´æÔÚÔò´´½¨¡£ÏÖÔÚÔö¼ÓÁË¶ÔÏîÄ¿IDµÄ¼ì²é¡£"""

        if not self.db_manager:

            return None



        # ¡¾ÐÂÔö¡¿Ë«ÖØ¼ì²é£¬È·±£ÔÚ´´½¨ÊµÑéÇ°£¬ÏîÄ¿IDÊÇÓÐÐ§µÄ

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

                print(f"ÐÂÊµÑé '{text}' ÒÑ´´½¨£¬ID: {self.current_experiment_id}")

            else:

                return None  # ÓÃ»§È¡Ïû



        return self.current_experiment_id



    def _create_global_actions(self):

        self.go_home_action = QAction(self.tr('Back to Welcome Screen'), self)

        self.go_home_action.setShortcut('Ctrl+H')

        self.go_home_action.setShortcutContext(Qt.ApplicationShortcut)

        self.exit_action = QAction(self.tr('Exit'), self)

        self.exit_action.setShortcut('Ctrl+Q')

        self.exit_action.setShortcutContext(Qt.ApplicationShortcut)



    def init_ui(self):

        # ¡¾ÐÞ¸Ä¡¿´´½¨MenuBarÊ±£¬½«È«¾ÖAction´«µÝ½øÈ¥

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

        """´ò¿ª¼ì²âÐÔÄÜ·ÖÎö¶Ô»°¿ò£¬¿ÉÒÔÑ¡ÔñÐÔµØ´«ÈëÐ±ÂÊ¡£"""

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

        ³¢ÊÔ¸ù¾ÝÇëÇóµÄÓ²¼þÄ£Ê½½¨Á¢¿ØÖÆÆ÷ÊµÀý¡£

        :param requested_mode: True ±íÊ¾ÕæÊµÓ²¼þ£¬False ±íÊ¾Ä£ÄâÄ£Ê½

        :param allow_fallback: µ±ÕæÊµÓ²¼þÊ§°ÜÊ±ÊÇ·ñ³¢ÊÔ×Ô¶¯»ØÍËµ½Ä£ÄâÄ£Ê½

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

        """¸ù¾Ý´«ÈëµÄÓ²¼þÄ£Ê½£¬ÉèÖÃ¸´Ñ¡¿òµÄ³õÊ¼×´Ì¬¡£"""

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

        print(f"Ö÷´°¿Ú½ÓÊÕµ½³õÊ¼Ä£Ê½: {mode_name}")



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

                        background-color: #1A202C; /* ÉîÀ¶»ÒÉ«±³¾° */

                        color: #E2E8F0; /* ÈáºÍµÄ°×É«ÎÄ×Ö */

                        font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;

                        font-size: 14px;

                    }

                    

                    /* ===== Main Content Panel Style  ===== */

                    #plotsContainer {

                        background-color: #2D3748; /* Ê¹ÓÃÒ»¸ö±ÈÖ÷±³¾°ÉÔÁÁµÄÑÕÉ« */

                        border-radius: 8px;      /* Ìí¼ÓÔ²½ÇÊ¹Æä¿´ÆðÀ´¸üÈáºÍ */

                    }

                    /* ===== Custom CollapsibleBox Style ===== */

                    CollapsibleBox {

                        /* ÎªÕû¸ö¿Ø¼þÉèÖÃÍâ±ß¾à£¬´´ÔìºôÎü¸Ð */

                        margin-bottom: 4px; 

                    }

                    

                    CollapsibleBox > QToolButton {

                        background-color: #2D3748; /* ±êÌâÀ¸±³¾°É« */

                        border: 1px solid #4A5568;

                        border-radius: 4px;

                        font-weight: bold;

                        font-size: 15px;

                        padding: 8px; /* ¼Ó´óÄÚ±ß¾à */

                        color: #CBD5E0;

                        text-align: left; /* ÎÄ×Ö¾Ó×ó */

                    }

                    

                    CollapsibleBox > QScrollArea {

                        background-color: #2D3748;

                        border: none;

                        border-top: 1px solid #4A5568; /* Ö»±£ÁôÉÏ±ß¿ò×÷Îª·Ö¸îÏß */

                        margin: 0px 5px 0px 5px; /* ×óÓÒÁô³öÒ»Ð©±ß¾à */

                    }



                    /* ===== GroupBox & Custom CollapsibleBox ===== */

                    QGroupBox {

                        background-color: #2D3748; /* ÉÔÁÁµÄÃæ°å±³¾° */

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

                        background-color: #3182CE; /* À¶É«Ö÷µ÷ */

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

                        border: 1px solid #3182CE; /* ½¹µã×´Ì¬Ê±¸ßÁÁ */

                    }

                    QComboBox::drop-down {

                        border: none;

                    }

                    QComboBox::down-arrow {

                        image: url(nanosense/gui/assets/down_arrow.svg); /* (ÐèÒªÒ»¸ö°×É«ÏòÏÂ¼ýÍ·SVGÍ¼±ê) */

                    }

                    QComboBox QAbstractItemView {

                        background-color: #2D3748;

                        color: #E2E8F0;

                        border: 1px solid #4A5568;

                        selection-background-color: #3182CE; /* Ñ¡ÖÐÏîµÄ±³¾°É« */

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

                    /* ===== Tab Widget Style (ÐÂÔö) ===== */

                    QTabWidget::pane { /* TabÒ³µÄ±ß¿òºÍ±³¾° */

                        border: 1px solid #4A5568;

                        border-top: none; /* ¶¥²¿±ß¿òÓÉTab°´Å¥Ìá¹©£¬´Ë´¦È¥µô */

                        border-radius: 0 0 4px 4px;

                    }



                    QTabBar::tab { /* Tab°´Å¥µÄÑùÊ½ */

                        background-color: #2D3748; /* Î´Ñ¡ÖÐÊ±µÄ±³¾°É« */

                        color: #A0AEC0; /* Î´Ñ¡ÖÐÊ±µÄÎÄ×ÖÑÕÉ« */

                        border: 1px solid #4A5568;

                        border-bottom: none; /* µ×±ß¿òÈ¥µô£¬ÓëpaneÁ¬½Ó */

                        padding: 8px 16px;

                        border-top-left-radius: 4px;

                        border-top-right-radius: 4px;

                    }



                    QTabBar::tab:selected { /* Tab°´Å¥±»Ñ¡ÖÐÊ±µÄÑùÊ½ */

                        background-color: #1A202C; /* Ñ¡ÖÐÊ±Ê¹ÓÃ¸üÉîµÄ±³¾°É«£¬ÓëÖ÷´°¿ÚÈÚºÏ */

                        color: white; /* Ñ¡ÖÐÊ±Ê¹ÓÃ¸üÁÁµÄÎÄ×ÖÑÕÉ« */

                        border-bottom: 1px solid #1A202C; /* ¸²¸ÇpaneµÄÉÏ±ß¿ò£¬ÊµÏÖÈÚºÏÐ§¹û */

                    }



                    QTabBar::tab:hover { /* Êó±êÐüÍ£ÔÚTab°´Å¥ÉÏÊ± */

                        background-color: #384253;

                    }

                    

                    /* ===== Menu Bar Style (ÐÂÔö) ===== */

                    QMenuBar {

                        background-color: #1A202C; /* Æ¥ÅäÖ÷´°¿Ú±³¾°É« */

                        color: #E2E8F0;

                        border-bottom: 1px solid #4A5568; /* µ×²¿¼ÓÒ»ÌõÏ¸Î¢·Ö¸îÏß£¬Ôö¼Ó²ã´Î¸Ð */

                    }

                    

                    QMenuBar::item {

                        background-color: transparent;

                        padding: 5px 10px;

                        margin: 2px;

                    }

                    

                    QMenuBar::item:selected { /* µ±Êó±êÐüÍ£»òÑ¡ÖÐ¶¥¼¶²Ëµ¥ÏîÊ± */

                        background-color: #2D3748; /* Ê¹ÓÃÃæ°åµÄ±³¾°É«×÷Îª¸ßÁÁ */

                        color: white;

                        border-radius: 4px;

                    }

                    

                    QMenu { /* ÏÂÀ­²Ëµ¥±¾ÉíµÄÑùÊ½ */

                        background-color: #2D3748;

                        color: #E2E8F0;

                        border: 1px solid #4A5568;

                    }

                    

                    QMenu::item {

                        padding: 8px 25px; /* ÎªÏÂÀ­²Ëµ¥ÏîÌá¹©¸ü¶à¿Õ¼ä */

                    }

                    

                    QMenu::item:selected { /* µ±Êó±êÐüÍ£»òÑ¡ÖÐÏÂÀ­²Ëµ¥ÀïµÄÏîÄ¿Ê± */

                        background-color: #3182CE; /* Ê¹ÓÃÎÒÃÇµÄÖ÷ÌâÀ¶É«×÷Îª¸ßÁÁ */

                        color: white;

                    }

                    

                    QMenu::separator {

                        height: 1px;

                        background-color: #4A5568;

                        margin: 5px 0px;

                    }

                    

                """)



    def closeEvent(self, event):

        # ¡¾ÐÞ¸Ä¡¿ÔÚ¹Ø±ÕÇ°¹Ø±ÕÊý¾Ý¿âÁ¬½Ó

        if self.db_manager:

            self.db_manager.close()

            print("Êý¾Ý¿âÁ¬½ÓÒÑ¹Ø±Õ¡£")

        if hasattr(self, 'measurement_page'):

            self.measurement_page.stop_all_activities()

        print("³ÌÐòÍË³ö...")

        event.accept()




    def _persist_imported_spectra(self, base_label: str, spectra_entries: List[Dict[str, Any]], import_context: Dict[str, Any]):
        if not self.db_manager or not spectra_entries:
            return
        try:
            if self.current_project_id is None:
                self._find_or_create_default_project()
                if self.current_project_id is None:
                    return
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            experiment_name = f"Import-{base_label}-{time.strftime('%Y%m%d-%H%M%S')}"
            source_files = import_context.get('source_files') or []
            config_payload = {
                'import': {
                    'mode': import_context.get('mode'),
                    'source_files': source_files,
                    'source_folder': import_context.get('source_folder')
                }
            }
            experiment_id = self.db_manager.create_experiment(
                project_id=self.current_project_id,
                name=experiment_name,
                exp_type="Imported Data",
                timestamp=timestamp,
                operator=import_context.get('operator') or "GUI Import",
                notes=f"Imported via {import_context.get('mode', 'GUI import')}",
                config_snapshot=json.dumps(config_payload, ensure_ascii=False)
            )
            if not experiment_id:
                return
            instrument_config = {
                'source': 'gui_import',
                'mode': import_context.get('mode')
            }
            if source_files:
                instrument_config['source_files'] = source_files
            if import_context.get('source_folder'):
                instrument_config['source_folder'] = import_context['source_folder']
            instrument_info = {'config': instrument_config}
            processing_base = {
                'name': 'gui_import',
                'version': '1.0',
                'parameters': {
                    'mode': import_context.get('mode'),
                    'spectra_count': len(spectra_entries)
                }
            }
            for entry in spectra_entries:
                label = entry.get('label') or "Imported Spectrum"
                x_values = entry.get('x')
                y_values = entry.get('y')
                if x_values is None or y_values is None:
                    continue
                metadata = entry.get('metadata') or {}
                processing_parameters = dict(processing_base['parameters'])
                processing_parameters['spectrum_label'] = label
                for key, value in metadata.items():
                    processing_parameters[f"meta_{key}"] = value
                processing_info = {
                    'name': processing_base['name'],
                    'version': processing_base['version'],
                    'parameters': processing_parameters
                }
                self.db_manager.save_spectrum(
                    experiment_id,
                    label,
                    timestamp,
                    x_values,
                    y_values,
                    instrument_info=instrument_info,
                    processing_info=processing_info
                )
        except Exception as exc:
            print(f"Failed to persist imported spectra: {exc}")



    def _trigger_import_single_spectrum(self):
        default_load_path = self.app_settings.get('default_load_path', '')
        x_data, y_data, file_path = load_spectrum(self, default_load_path)
        if x_data is not None:
            name = os.path.basename(file_path) if file_path else self.tr("Loaded Spectrum")
            single_spectrum_data = {'x': x_data, 'y': y_data, 'name': name}
            analysis_win = AnalysisWindow(spectra_data=single_spectrum_data, parent=self)
            self.analysis_windows.append(analysis_win)
            analysis_win.show()
            self._persist_imported_spectra(
                base_label=name,
                spectra_entries=[{
                    'label': name,
                    'x': x_data,
                    'y': y_data,
                    'metadata': {'source_file': file_path}
                }],
                import_context={
                    'mode': 'single_file_import',
                    'source_files': [file_path] if file_path else []
                }
            )


    def _trigger_import_three_files(self):
        dialog = ThreeFileImportDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            all_data = dialog.get_data()
            if all_data and all_data.get('result'):
                analysis_win = AnalysisWindow(spectra_data=all_data, parent=self)
                self.analysis_windows.append(analysis_win)
                analysis_win.show()
                entries = []
                paths = (all_data.get('source_paths') or {})
                if all_data.get('signal'):
                    entries.append({
                        'label': 'Signal',
                        'x': all_data['signal'][0],
                        'y': all_data['signal'][1],
                        'metadata': {'source_file': paths.get('signal'), 'kind': 'signal'}
                    })
                if all_data.get('background'):
                    entries.append({
                        'label': 'Background',
                        'x': all_data['background'][0],
                        'y': all_data['background'][1],
                        'metadata': {'source_file': paths.get('background'), 'kind': 'background'}
                    })
                if all_data.get('reference'):
                    entries.append({
                        'label': 'Reference',
                        'x': all_data['reference'][0],
                        'y': all_data['reference'][1],
                        'metadata': {'source_file': paths.get('reference'), 'kind': 'reference'}
                    })
                if all_data.get('result'):
                    entries.append({
                        'label': 'Result',
                        'x': all_data['result'][0],
                        'y': all_data['result'][1],
                        'metadata': {'kind': 'result'}
                    })
                self._persist_imported_spectra(
                    base_label=self.tr("Three File Import"),
                    spectra_entries=entries,
                    import_context={
                        'mode': 'three_file_import',
                        'source_files': [p for p in paths.values() if p]
                    }
                )


    def _trigger_import_multiple_from_folder(self):
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
            entries = [
                {
                    'label': item['name'],
                    'x': item['x'],
                    'y': item['y'],
                    'metadata': {'source_file': os.path.join(dir_path, item['name'])}
                }
                for item in spectra_list
            ]
            self._persist_imported_spectra(
                base_label=os.path.basename(dir_path),
                spectra_entries=entries,
                import_context={
                    'mode': 'folder_import',
                    'source_folder': dir_path,
                    'source_files': [os.path.join(dir_path, item['name']) for item in spectra_list]
                }
            )
        else:
            QMessageBox.warning(
                self,
                self.tr("Info"),
                self.tr("No spectra were found in the selected folder.")
            )


    def _trigger_import_multiple_from_file(self):
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
            entries = [
                {
                    'label': item['name'],
                    'x': item['x'],
                    'y': item['y'],
                    'metadata': {'source_file': file_path}
                }
                for item in spectra_list
            ]
            self._persist_imported_spectra(
                base_label=os.path.basename(file_path),
                spectra_entries=entries,
                import_context={
                    'mode': 'multi_column_file_import',
                    'source_files': [file_path]
                }
            )
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

        ´ò¿ªÉèÖÃ¶Ô»°¿ò£¬²¢´¦Àí·µ»Ø½á¹û¡£

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

        """´ò¿ªÒ»¼üÉú³É·ÖÎö±¨¸æµÄ¶Ô»°¿ò¡£"""

        dialog = BatchReportDialog(self)

        dialog.exec_()



    def _trigger_realtime_noise_analysis(self):  # <--- ÖØÐÂÌí¼Ó´Ë·½·¨

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

                self.tr("A valid output folder must be selected."),

            )

            return



        if not self.db_manager:

            QMessageBox.warning(

                self,

                self.tr("Database Not Configured"),

                self.tr("Please configure a database file before running batch acquisition."),

            )

            return



        if self.current_project_id is None:

            self._find_or_create_default_project()

            if self.current_project_id is None:

                QMessageBox.critical(

                    self,

                    self.tr("Database Error"),

                    self.tr("Unable to resolve a project for batch acquisition."),

                )

                return



        integration_time = None

        if hasattr(self, "measurement_page") and getattr(self.measurement_page, "integration_time_spinbox", None):

            integration_time = float(self.measurement_page.integration_time_spinbox.value())



        instrument_info = {

            "device_serial": getattr(self.controller, "serial_number", None),

            "integration_time_ms": integration_time,

            "config": {

                "source": "batch_acquisition",

                "points_per_well": points_per_well,

                "crop_start_nm": crop_start,

                "crop_end_nm": crop_end,

                "auto_enabled": is_auto_enabled,

                "file_extension": file_extension,

            },

        }

        instrument_config = {k: v for k, v in instrument_info["config"].items() if v is not None}

        if instrument_config:

            instrument_info["config"] = instrument_config

        else:

            instrument_info.pop("config", None)

        if all(instrument_info.get(key) is None for key in ("device_serial", "integration_time_ms", "averaging", "temperature")) and "config" not in instrument_info:

            instrument_info = None



        processing_parameters = {

            "source": "batch_acquisition",

            "points_per_well": points_per_well,

            "crop_start_nm": crop_start,

            "crop_end_nm": crop_end,

            "auto_enabled": is_auto_enabled,

            "intra_well_interval_s": intra_well_interval,

            "inter_well_interval_s": inter_well_interval,

            "layout_well_count": len(layout_data),

            "file_extension": file_extension,

        }

        processing_parameters = {k: v for k, v in processing_parameters.items() if v is not None}

        processing_info = {

            "name": "batch_acquisition",

            "version": "1.0",

            "parameters": processing_parameters,

        }



        operator_name = None

        if hasattr(self, "app_settings") and isinstance(self.app_settings, dict):

            operator_name = self.app_settings.get("operator_name") or self.app_settings.get("default_operator")

        operator_name = operator_name or self.tr("Batch Operator")



        self.run_dialog = BatchRunDialog(self)

        self.batch_thread = QThread()



        self.batch_worker = BatchAcquisitionWorker(

            self.controller, layout_data, output_folder, file_extension,

            points_per_well=points_per_well,

            crop_start_wl=crop_start,

            crop_end_wl=crop_end,

            is_auto_enabled=is_auto_enabled,

            intra_well_interval=intra_well_interval,

            inter_well_interval=inter_well_interval,

            db_manager=self.db_manager,

            project_id=self.current_project_id,

            operator=operator_name,

            instrument_info=instrument_info,

            processing_info=processing_info,

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



        # Èç¹ûÈÎÎñ²»ÊÇ±»ÓÃ»§ÖÐÖ¹µÄ£¬¶øÊÇÕý³£Íê³ÉµÄ

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

        print("ÕýÔÚÖÐÖ¹ÅúÁ¿²É¼¯ÈÎÎñ...")

        if hasattr(self, 'batch_worker') and self.batch_worker:

            self.batch_worker.stop()



        print("ÕýÔÚÖ´ÐÐÓ²¼þ¿ØÖÆÆ÷¶Ï¿ªÁ¬½Ó...")

        FX2000Controller.disconnect()



        time.sleep(0.2)



        print("ÕýÔÚÖØÐÂÁ¬½ÓÓ²¼þ¿ØÖÆÆ÷...")

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

            print("Ó²¼þÖØÖÃ²¢ÖØÐÂÁ¬½Ó³É¹¦")



    def _on_batch_acquisition_finished(self):

        """

        µ±ÅúÁ¿²É¼¯¹¤×÷Ïß³ÌÍê³ÉÆäÈÎÎñºó£¬´Ë²Ûº¯Êý±»µ÷ÓÃ¡£

        """

        # 1. ¼ì²é¶Ô»°¿òÊÇ·ñ´æÔÚ²¢¹Ø±ÕËü

        if hasattr(self, 'run_dialog') and self.run_dialog:

            self.run_dialog.accept()  # accept()»á¹Ø±Õ¶Ô»°¿ò²¢ÉèÖÃresultÎªAccepted



        # 2. ¼ì²éÈÎÎñÊÇ·ñÊÇÕý³£Íê³ÉµÄ£¨¼´ÓÃ»§Ã»ÓÐµã»÷ÖÐÖ¹£©

        # self.batch_worker ´ËÊ±¿ÉÄÜÒÑ¾­±» deleteLater ÇåÀí£¬ÐèÒª¼ì²é

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

                # ×Ô¶¯´ò¿ªÅúÁ¿·ÖÎö¶Ô»°¿ò

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

        ¼ÓÔØ²¢°²×°Ö¸¶¨ÓïÑÔµÄ·­ÒëÎÄ¼þ£¬²¢ÊÖ¶¯¸üÐÂËùÓÐUI¡£

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

        ÖØÐÂ·­Òëµ±Ç°´°¿ÚµÄËùÓÐUIÎÄ±¾¡£

        """

        print("Retranslating UI...")

        self.setWindowTitle(self.tr("Nanophotonics sensing detection data visualization analysis system"))



        # ÖØÐÂ·­ÒëÈ«¾ÖActionµÄÎÄ±¾

        self.go_home_action.setText(self.tr('Back to Welcome Screen'))

        self.exit_action.setText(self.tr('Exit'))



        # ÖØÐÂ·­Òë²Ëµ¥À¸

        if hasattr(self.menuBar(), '_retranslate_ui'):

            self.menuBar()._retranslate_ui()



        # ÃüÁî×ÓÒ³ÃæÒ²½øÐÐ×ÔÎÒ·­Òë

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

        ÔÚ³ÌÐòÆô¶¯Ê±£¬¸ù¾ÝÅäÖÃÎÄ¼þÉèÖÃ³õÊ¼ÓïÑÔ¡£

        """

        # ´ÓÉèÖÃÖÐ¶ÁÈ¡±£´æµÄÓïÑÔ£¬Èç¹û²»´æÔÚ£¬ÔòÄ¬ÈÏÎª 'en' (Ó¢ÎÄ)

        language = self.app_settings.get('language', 'en')



        # ¸ù¾Ý¶ÁÈ¡µ½µÄÓïÑÔ£¬ÉèÖÃ²Ëµ¥ÏîµÄ¹´Ñ¡×´Ì¬

        if language == 'zh':

            self.menuBar().language_zh_action.setChecked(True)

        else:

            self.menuBar().language_en_action.setChecked(True)



        # µ÷ÓÃÓïÑÔÇÐ»»º¯Êý£¬ÒÔÈ·±£³ÌÐòÆô¶¯Ê±¾Í¼ÓÔØÕýÈ·µÄ·­Òë

        self._switch_language(language)



    def _open_mock_api_config_dialog(self):

        """

        ´ò¿ªÄ£ÄâAPIÅäÖÃ¶Ô»°¿ò£¬²¢ÔÚÓÃ»§È·ÈÏºó±£´æÉèÖÃ¡£

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

        """¡¾ÐÞ¸Ä¡¿ÒÔ·ÇÄ£Ì¬·½Ê½´ò¿ªÊý¾Ý¿âä¯ÀÀÆ÷£¬²¢·ÀÖ¹ÖØ¸´´ò¿ª¡£"""

        if not self.db_manager:

            QMessageBox.warning(self, self.tr("Database Error"),

                                self.tr("Database is not connected. Please check the settings."))

            return



        # Èç¹û´°¿ÚÒÑ¾­´ò¿ª£¬ÔòÖ±½Ó¼¤»î²¢ÏÔÊ¾ÔÚ×îÇ°¶Ë£¬¶ø²»ÊÇ´´½¨ÐÂµÄ

        if self.db_explorer_window and self.db_explorer_window.isVisible():

            self.db_explorer_window.activateWindow()

            return



        # ´´½¨ÐÂÊµÀý²¢½«Æä´æ´¢ÔÚ self.db_explorer_window ÖÐ

        self.db_explorer_window = DatabaseExplorerDialog(parent=self)

        self.db_explorer_window.load_spectra_requested.connect(self._open_analysis_window_from_db)



        # Ê¹ÓÃ .show() ¶ø²»ÊÇ .exec_()

        self.db_explorer_window.show()



    def _open_analysis_window_from_db(self, spectra_list):

        """¸ù¾Ý´ÓÊý¾Ý¿â¼ÓÔØµÄ¹âÆ×ÁÐ±í£¬´´½¨Ò»¸öÐÂµÄ·ÖÎö´°¿Ú¡£"""

        if not spectra_list:

            return



        print(f"´ÓÊý¾Ý¿â¼ÓÔØÁË {len(spectra_list)} Ìõ¹âÆ×£¬ÕýÔÚ´ò¿ª·ÖÎö´°¿Ú...")



        # ´´½¨²¢ÏÔÊ¾ AnalysisWindow À´Õ¹Ê¾ÕâÐ©Êý¾Ý

        analysis_win = AnalysisWindow(spectra_data=spectra_list, parent=self)

        self.analysis_windows.append(analysis_win)

        analysis_win.show()








