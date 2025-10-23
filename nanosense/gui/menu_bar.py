# nanosense/gui/menu_bar.py (最终修复版)

from PyQt5.QtWidgets import QMenuBar, QAction, QActionGroup

class MenuBar(QMenuBar):

    def __init__(self, go_home_action, exit_action, parent=None):
        super().__init__(parent)

        self.go_home_action = go_home_action
        self.exit_action = exit_action

        self._create_actions()
        self._create_menus()

    def _create_actions(self):
        """创建所有的 QAction 对象。"""
        # File Menu Actions
        self.import_spectra_action = QAction(self.tr('Import Spectra data'), self)
        self.import_three_file_action = QAction(self.tr('Import Spectra Data (Three File)'), self)
        self.import_from_folder_action = QAction(self.tr('From Folder...'), self)
        self.import_from_file_action = QAction(self.tr('From Multi-column File...'), self)

        # Analysis Menu Actions
        self.batch_report_action = QAction(self.tr('Generate Analysis Report...'), self)
        self.batch_report_action.setToolTip(
            self.tr('Generate a comprehensive analysis report from a single multi-spectrum file.'))
        self.sensitivity_action = QAction(self.tr('Sensitivity Calculation'), self)
        self.calibration_action = QAction(self.tr('Calibration Curve'), self)
        self.affinity_action = QAction(self.tr('Affinity Analysis (KD)'), self)
        self.kobs_linear_action = QAction(self.tr('k_obs Linearization'), self)
        self.import_noise_action = QAction(self.tr('Import Data Analysis...'), self)
        self.realtime_noise_action = QAction(self.tr('Real-time Data Analysis...'), self)
        self.performance_action = QAction(self.tr('Detection Performance (LOB/LOD/LOQ)...'), self)

        # Data Menu Actions
        self.batch_acquisition_action = QAction(self.tr('Batch Acquisition Setup'), self)
        self.data_analysis_action = QAction(self.tr('Batch Data Analysis'), self)
        self.database_explorer_action = QAction(self.tr('Database Explorer...'), self)

        # --- Settings Menu Actions ---
        self.hardware_mode_action = QAction(self.tr('Use Real Hardware'), self, checkable=True)
        self.language_en_action = QAction(self.tr('English'), self, checkable=True)
        self.language_zh_action = QAction(self.tr('Chinese'), self, checkable=True)
        self.default_paths_action = QAction(self.tr('Customize Parameters...'), self)
        self.mock_api_config_action = QAction(self.tr('Mock API Configuration...'), self)
        self.logging_system_action = QAction(self.tr('Logging System...'), self)
        self.about_action = QAction(self.tr('About'), self)

    def _create_menus(self):
        """创建所有主菜单，并将Action添加进去。"""
        # --- File Menu ---
        self.file_menu = self.addMenu(self.tr('&File'))
        self.file_menu.addAction(self.import_spectra_action)
        self.file_menu.addAction(self.import_three_file_action)

        self.import_multiple_menu = self.file_menu.addMenu(self.tr('Import Multiple Spectra'))
        self.import_multiple_menu.addAction(self.import_from_folder_action)
        self.import_multiple_menu.addAction(self.import_from_file_action)

        # --- Windows Menu ---
        self.windows_menu = self.addMenu(self.tr('&Windows'))
        self.windows_menu.addAction(self.go_home_action)
        self.windows_menu.addSeparator()
        self.windows_menu.addAction(self.exit_action)

        # --- Analysis Menu ---
        self.analysis_menu = self.addMenu(self.tr('&Analysis'))
        self.analysis_menu.addAction(self.batch_report_action)
        self.analysis_menu.addAction(self.sensitivity_action)
        self.analysis_menu.addAction(self.calibration_action)
        self.analysis_menu.addAction(self.performance_action)
        self.analysis_menu.addSeparator()
        self.analysis_menu.addAction(self.affinity_action)
        self.analysis_menu.addAction(self.kobs_linear_action)
        self.analysis_menu.addSeparator()
        self.noise_analysis_menu = self.analysis_menu.addMenu(self.tr('Noise Analysis'))
        self.noise_analysis_menu.addAction(self.import_noise_action)
        self.noise_analysis_menu.addAction(self.realtime_noise_action)


        # --- Data Menu ---
        self.data_menu = self.addMenu(self.tr('&Data'))
        self.data_menu.addAction(self.batch_acquisition_action)
        self.data_menu.addAction(self.data_analysis_action)
        self.data_menu.addSeparator()
        self.data_menu.addAction(self.database_explorer_action)

        # --- Settings Menu ---
        self.settings_menu = self.addMenu(self.tr('&Settings'))
        self.settings_menu.addAction(self.hardware_mode_action)

        self.language_menu = self.settings_menu.addMenu(self.tr('Language'))
        # 之前修复的ActionGroup逻辑保持不变
        self.language_action_group = QActionGroup(self.language_menu)
        self.language_action_group.addAction(self.language_en_action)
        self.language_action_group.addAction(self.language_zh_action)
        self.language_menu.addAction(self.language_en_action)
        self.language_menu.addAction(self.language_zh_action)

        self.settings_menu.addAction(self.default_paths_action)
        self.settings_menu.addSeparator()

        self.advanced_menu = self.settings_menu.addMenu(self.tr('Advanced Options'))
        self.advanced_menu.addAction(self.mock_api_config_action)
        self.advanced_menu.addAction(self.logging_system_action)

        # --- Help Menu ---
        self.help_menu = self.addMenu(self.tr('&Help'))
        self.help_menu.addAction(self.about_action)

    def _retranslate_ui(self):
        """
        【已优化】重新翻译菜单栏自身的所有文本，包括菜单标题和所有菜单项。
        """
        # 1. 重新翻译所有 Action 的文本
        self.import_spectra_action.setText(self.tr('Import Spectra data'))
        self.import_three_file_action.setText(self.tr('Import Spectra Data (Three File)'))
        self.import_from_folder_action.setText(self.tr('From Folder...'))
        self.import_from_file_action.setText(self.tr('From Multi-column File...'))

        self.batch_acquisition_action.setText(self.tr('Batch Acquisition Setup'))
        self.sensitivity_action.setText(self.tr('Sensitivity Calculation'))
        self.calibration_action.setText(self.tr('Calibration Curve'))
        self.affinity_action.setText(self.tr('Affinity Analysis (KD)'))
        self.kobs_linear_action.setText(self.tr('k_obs Linearization'))
        self.noise_analysis_menu.setTitle(self.tr('Noise Analysis'))
        self.import_noise_action.setText(self.tr('Import Data Analysis...'))
        self.realtime_noise_action.setText(self.tr('Real-time Data Analysis...'))

        self.data_analysis_action.setText(self.tr('Batch Data Analysis'))
        self.database_explorer_action.setText(self.tr('Database Explorer...'))
        self.batch_report_action.setText(self.tr('Generate Analysis Report...'))
        self.batch_report_action.setToolTip(
            self.tr('Generate a comprehensive analysis report from a single multi-spectrum file.'))

        self.hardware_mode_action.setText(self.tr('Use Real Hardware'))
        self.language_en_action.setText(self.tr('English'))
        self.language_zh_action.setText(self.tr('Chinese'))
        self.default_paths_action.setText(self.tr('Customize Parameters...'))
        self.mock_api_config_action.setText(self.tr('Mock API Configuration...'))
        self.logging_system_action.setText(self.tr('Logging System...'))

        self.about_action.setText(self.tr('About'))

        # 2. 重新翻译所有菜单的标题
        self.file_menu.setTitle(self.tr('&File'))
        self.import_multiple_menu.setTitle(self.tr('Import Multiple Spectra'))
        self.windows_menu.setTitle(self.tr('&Windows'))
        self.analysis_menu.setTitle(self.tr('&Analysis'))
        self.data_menu.setTitle(self.tr('&Data'))
        self.settings_menu.setTitle(self.tr('&Settings'))
        self.language_menu.setTitle(self.tr('Language'))
        self.advanced_menu.setTitle(self.tr('Advanced Options'))
        self.help_menu.setTitle(self.tr('&Help'))