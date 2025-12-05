# nanosense/gui/single_plot_window.py (智能缩放和国际化版本)

from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt5.QtCore import pyqtSignal, QEvent  # 【修改】导入 QEvent

import pyqtgraph as pg


class SinglePlotWindow(QMainWindow):
    closed = pyqtSignal(object)

    def __init__(self, title, initial_x_range=None, initial_y_range=None, parent=None):
        super().__init__(parent)
        # self.setWindowTitle(title)  # 标题将在 _retranslate_ui 中设置
        self.setGeometry(200, 200, 800, 600)

        # 【修改】保存原始标题，以便在语言切换时重新翻译
        # 注意：创建此窗口的父控件需要传递一个可被 tr() 函数翻译的源字符串
        self.window_title_source = title

        self.user_has_interacted = False

        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)

        self.plot_widget = pg.PlotWidget()
        # self.plot_widget.setTitle(title, color='#90A4AE', size='12pt') # 标题将在 _retranslate_ui 中设置
        self.plot_widget.showGrid(x=True, y=True)
        
        # 根据主题设置背景色
        from ..utils.config_manager import load_settings
        settings = load_settings()
        theme = settings.get('theme', 'dark')
        if theme == 'light':
            self.plot_widget.setBackground('#F0F0F0')
        else:
            self.plot_widget.setBackground('#1F2735')
        self.setCentralWidget(central_widget)

        self.curve = self.plot_widget.plot()

        if initial_x_range:
            self.plot_widget.getViewBox().setLimits(xMin=initial_x_range[0], xMax=initial_x_range[1])
            self.plot_widget.setXRange(*initial_x_range, padding=0)

        if initial_y_range:
            self.plot_widget.setYRange(*initial_y_range, padding=0)

        toolbar_layout = QHBoxLayout()
        # 【修改】创建空按钮，文本将在 _retranslate_ui 中设置
        self.reset_view_button = QPushButton()
        self.reset_view_button.setFixedWidth(100)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.reset_view_button)

        main_layout.addLayout(toolbar_layout)
        main_layout.addWidget(self.plot_widget)

        self.plot_widget.getViewBox().sigStateChanged.connect(self._handle_interaction)
        self.reset_view_button.clicked.connect(self._reset_view)

        # 【新增】在UI初始化完成后，调用一次翻译方法来设置所有初始文本
        self._retranslate_ui()

    def _handle_interaction(self):
        self.user_has_interacted = True

    def _reset_view(self):
        self.user_has_interacted = False
        self.plot_widget.autoRange()

    def update_data(self, x_data, y_data, pen):
        if x_data is not None and y_data is not None:
            self.curve.setData(x_data, y_data, pen=pen)
            if not self.user_has_interacted:
                self.plot_widget.autoRange()

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)

    def update_view_and_limits(self, x_range, y_range):
        if x_range:
            self.plot_widget.getViewBox().setLimits(xMin=x_range[0], xMax=x_range[1])
            self.plot_widget.setXRange(*x_range, padding=0)
        else:
            self.plot_widget.getViewBox().setLimits(xMin=None, xMax=None)
            self.plot_widget.autoRange()

        if y_range:
            self.plot_widget.setYRange(*y_range, padding=0)

    # --- 【新增】国际化支持的标准方法 ---
    def changeEvent(self, event):
        """处理语言变化事件。"""
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """重新翻译此窗口内的所有UI文本。"""
        # 翻译窗口和图表的标题
        translated_title = self.tr(self.window_title_source)
        self.setWindowTitle(translated_title)
        self.plot_widget.setTitle(translated_title, color='#90A4AE', size='12pt')

        # 翻译按钮文本
        self.reset_view_button.setText(self.tr("Reset View"))