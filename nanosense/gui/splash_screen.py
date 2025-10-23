# nanosense/gui/splash_screen.py

from PyQt5.QtWidgets import QSplashScreen, QProgressBar, QVBoxLayout, QWidget
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt


class SplashScreen(QSplashScreen):
    def __init__(self, pixmap_path):
        """
        初始化启动画面。
        :param pixmap_path: 启动画面的图片路径。
        """
        pixmap = QPixmap(pixmap_path)
        super().__init__(pixmap)

        # 创建一个主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 30)  # 底部留出更多空间给进度条

        # 使用一个占位符将进度条推到底部
        layout.addStretch()

        # 创建并配置进度条
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setStyleSheet("""
                    QProgressBar {
                        /* 边框和背景保持不变 */
                        border: 1px solid rgba(224, 224, 224, 0.6);
                        border-radius: 5px;
                        text-align: center;
                        background-color: rgba(0, 0, 0, 0.2);
                        color: white;
                    }
                    QProgressBar::chunk {
                        /* 进度条主体使用更深邃的蓝色渐变 */
                        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                                        stop:0 #4169E1, stop:1 #483D8B);
                        border-radius: 4px;
                    }
                """)

        # 将进度条添加到布局中
        layout.addWidget(self.progress_bar)

    def update_progress(self, value):
        """
        更新进度条的值。
        :param value: 0到100的整数。
        """
        self.progress_bar.setValue(value)