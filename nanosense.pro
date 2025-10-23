# Qt Project File for Nanosense Translation (Comprehensive Version)


# List all Python files that contain user-facing UI strings
SOURCES = main.py \
          main_acquisition_loop.py \
          mock_spectrometer_api.py \
          # GUI Layer (All files from the gui folder)
          nanosense/gui/__init__.py \
          nanosense/gui/about_dialog.py \
          nanosense/gui/affinity_analysis_dialog.py \
          nanosense/gui/analysis_window.py \
          nanosense/gui/batch_report_dialog.py \
          nanosense/gui/batch_setup_dialog.py \
          nanosense/gui/calibration_dialog.py \
          nanosense/gui/collapsible_box.py \
          nanosense/gui/colorimetry_widget.py \
          nanosense/gui/data_analysis_dialog.py \
          nanosense/gui/database_explorer.py \
          nanosense/gui/drift_correction_dialog.py \
          nanosense/gui/kinetics_analysis_dialog.py \
          nanosense/gui/kinetics_window.py \
          nanosense/gui/kobs_linearization_dialog.py \
          nanosense/gui/main_window.py \
          nanosense/gui/measurement_widget.py \
          nanosense/gui/menu_bar.py \
          nanosense/gui/mock_api_config_dialog.py \
          nanosense/gui/noise_analysis_dialog.py \
          nanosense/gui/noise_tools.py \
          nanosense/gui/peak_metrics_dialog.py \
          nanosense/gui/performance_dialog.py \
          nanosense/gui/plate_setup_dialog.py \
          nanosense/gui/preprocessing_dialog.py \
          nanosense/gui/realtime_noise_setup_dialog.py \
          nanosense/gui/sensitivity_dialog.py \
          nanosense/gui/settings_dialog.py \
          nanosense/gui/single_plot_window.py \
          nanosense/gui/splash_screen.py \
          nanosense/gui/three_file_import_dialog.py \
          nanosense/gui/welcome_widget.py \
          # Core Layer (Only files with UI-related strings)
          nanosense/core/__init__.py \
          nanosense/core/acquisition.py \
          nanosense/core/batch_acquisition.py \
          nanosense/core/controller.py \
          nanosense/core/database_manager.py \
          nanosense/core/spectrum_processor.py \
          # Utils Layer (Only files with user-facing text)
          nanosense/utils/__init__.py \
          nanosense/utils/config_manager.py \
          nanosense/utils/data_processor.py \
          nanosense/utils/file_io.py \
          nanosense/utils/plot_generator.py \
          nanosense/utils/report_generator.py \
          # Algorithms Layer (May contain error messages or names)
          nanosense/algorithms/__init__.py \
          nanosense/algorithms/colorimetry.py \
          nanosense/algorithms/kinetics.py \
          nanosense/algorithms/peak_analysis.py \
          nanosense/algorithms/performance.py \
          nanosense/algorithms/preprocessing.py

# Specify the output translation file
TRANSLATIONS = nanosense/translations/chinese.ts