# nanosense/gui/about_dialog.py

import os
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt, QEvent


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._init_ui()
        self._retranslate_ui() # 设置初始文本

    def _init_ui(self):
        # --- 设置窗口图标 ---
        icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'app_icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # --- 左侧：放置应用Logo ---
        logo_label = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), 'assets', 'splash.png')
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path).scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pixmap)
        main_layout.addWidget(logo_label, 0, Qt.AlignTop)

        # --- 右侧：放置文本信息和按钮 ---
        right_panel_layout = QVBoxLayout()

        self.text_label = QLabel() # 创建一个空的 QLabel
        self.text_label.setWordWrap(True)
        self.text_label.setOpenExternalLinks(True)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)

        right_panel_layout.addWidget(self.text_label)
        right_panel_layout.addStretch()
        right_panel_layout.addWidget(button_box, 0, Qt.AlignRight)

        main_layout.addLayout(right_panel_layout)

    def changeEvent(self, event):
        """
        响应语言变化事件。
        """
        if event.type() == QEvent.LanguageChange:
            self._retranslate_ui()
        super().changeEvent(event)

    def _retranslate_ui(self):
        """
        【已优化】重新构建并翻译所有UI文本。
        """
        self.setWindowTitle(self.tr("About Nanosense Platform"))

        # 【核心修改】先将所有需要翻译的短语赋值给变量
        version_str = self.tr("Version:")
        copyright_str = self.tr("Copyright:")
        p1_str = self.tr(
            "This software platform is an integrated system for nanophotonics sensing signal processing and analysis.")
        p2_str = self.tr(
            "It aims to provide researchers with a one-stop solution from device control and data acquisition to advanced algorithm analysis.")
        tech_support_str = self.tr("Technical Support:")
        framework_str = self.tr("Core Framework:")
        computing_str = self.tr("Scientific Computing:")

        # 然后使用这些变量来构建HTML
        about_text = f"""
        <h2>Nanophotonics Sensing Platform</h2>
        <p><b>{version_str}</b> 1.0.0</p>
        <p><b>{copyright_str}</b> Copyright &copy; 2025, Professor Geng Lab</p>
        <hr>
        <p>{p1_str}</p>
        <p>{p2_str}</p>
        <p>{tech_support_str}
        <ul>
            <li><b>{framework_str}</b> Python, PyQt5, PyQtGraph</li>
            <li><b>{computing_str}</b> NumPy, SciPy, Pandas</li>
        </ul>
        </p>
        """
        self.text_label.setText(about_text)
        self.setFixedSize(self.sizeHint())