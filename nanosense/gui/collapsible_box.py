# nanosense/gui/collapsible_box.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QToolButton, QFrame, QScrollArea, QSizePolicy
from PyQt5.QtCore import Qt,QPropertyAnimation, QParallelAnimationGroup, QAbstractAnimation, QEasingCurve, pyqtSignal


class CollapsibleBox(QWidget):
    """
    一个可折叠的自定义控件，类似于可以独立展开/收起的QGroupBox。
    """

    def __init__(self, title="", parent=None):
        super(CollapsibleBox, self).__init__(parent)

        self.toggle_button = QToolButton(text=title, checkable=True, checked=False)
        self.toggle_button.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.RightArrow)
        self.toggle_button.pressed.connect(self._toggle)

        self.content_area = QScrollArea(maximumHeight=0, minimumHeight=0)
        self.content_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.content_area.setFrameShape(QFrame.NoFrame)
        self.content_area.setWidgetResizable(True)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.toggle_button)
        main_layout.addWidget(self.content_area)

        self.toggle_animation = QParallelAnimationGroup(self)
        self.content_animation = QPropertyAnimation(self.content_area, b"maximumHeight")

        self.toggle_animation.addAnimation(self.content_animation)

    def _toggle(self):
        """【已修复】根据按钮的选中状态正确设置动画和箭头方向。"""
        checked = self.toggle_button.isChecked()
        # 如果按钮被选中(checked=True)，我们希望它展开：箭头向下，动画向前
        self.toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.toggle_animation.setDirection(QAbstractAnimation.Forward if checked else QAbstractAnimation.Backward)
        self.toggle_animation.start()

    def setContentLayout(self, layout):
        # 将传入的布局放入一个临时的QWidget中，再将这个QWidget放入QScrollArea
        content_widget = QWidget()
        content_widget.setLayout(layout)
        self.content_area.setWidget(content_widget)

        collapsed_height = self.sizeHint().height() - self.content_area.maximumHeight()
        content_height = layout.sizeHint().height()

        self.content_animation.setDuration(300)
        self.content_animation.setStartValue(0)
        self.content_animation.setEndValue(content_height)
        self.content_animation.setEasingCurve(QEasingCurve.InOutCubic)

    def set_expanded(self, expanded=True):
        """
        一个专门用于从外部代码控制折叠框展开/折叠状态的方法。
        """
        # 只有当请求的状态与当前状态不同时才执行操作，避免不必要的动画
        if expanded != self.toggle_button.isChecked():
            # setChecked() 会触发 pressed 信号，从而调用我们的 _toggle 方法
            self.toggle_button.setChecked(expanded)
            self._toggle()
