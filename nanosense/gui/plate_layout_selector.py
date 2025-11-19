# nanosense/gui/plate_layout_selector.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QGridLayout,
    QPushButton,
    QDialogButtonBox,
    QHBoxLayout,
    QSpinBox,
    QSizePolicy,
    QGraphicsDropShadowEffect,
)


@dataclass
class PlateLayout:
    key: str
    name: str
    rows: int
    cols: int


class PlateLayoutButton(QPushButton):
    """Custom button with hover shadow and rounded corners."""

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setProperty("plateButton", True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(48)
        self.setMinimumWidth(240)
        self._shadow_effect = QGraphicsDropShadowEffect(self)
        self._shadow_effect.setBlurRadius(18)
        self._shadow_effect.setOffset(0, 2)
        self._shadow_effect.setColor(QColor(0, 0, 0, 25))
        self.setGraphicsEffect(self._shadow_effect)

    def enterEvent(self, event):
        self._apply_shadow(offset_y=3, alpha=38, blur=24)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_shadow(offset_y=2, alpha=25, blur=18)
        super().leaveEvent(event)

    def _apply_shadow(self, offset_y: int, alpha: int, blur: int) -> None:
        if not self._shadow_effect:
            return
        self._shadow_effect.setOffset(0, offset_y)
        self._shadow_effect.setBlurRadius(blur)
        self._shadow_effect.setColor(QColor(0, 0, 0, alpha))


class CustomLayoutDialog(QDialog):
    """Dialog that lets the user define a custom plate size."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Custom Plate Layout"))
        layout = QVBoxLayout(self)

        form = QGridLayout()
        self.row_spin = QSpinBox()
        self.row_spin.setRange(1, 26)  # At most letters A-Z
        self.row_spin.setValue(8)
        form.addWidget(QLabel(self.tr("Number of Rows")), 0, 0)
        form.addWidget(self.row_spin, 0, 1)

        self.col_spin = QSpinBox()
        self.col_spin.setRange(1, 48)
        self.col_spin.setValue(12)
        form.addWidget(QLabel(self.tr("Number of Columns")), 1, 0)
        form.addWidget(self.col_spin, 1, 1)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> PlateLayout:
        rows = self.row_spin.value()
        cols = self.col_spin.value()
        name = self.tr("{rows} x {cols} Custom").format(rows=rows, cols=cols)
        return PlateLayout(key="custom", name=name, rows=rows, cols=cols)


class PlateLayoutSelectionDialog(QDialog):
    """First-step dialog to select which plate layout to use."""

    def __init__(self, parent=None, default_key: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Select Plate Layout"))
        self.selected_layout: Optional[PlateLayout] = None
        self._setup_styling()
        self._init_ui()
        # Make the initial dialog wide enough for localized text.
        self.setMinimumWidth(520)
        hint = self.sizeHint()
        self.resize(max(hint.width(), 580), hint.height())

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 10)
        layout.setSpacing(16)

        header = QLabel(self.tr("Choose a plate layout before configuration"))
        header.setObjectName("layoutHeader")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.layouts = [
            PlateLayout("48", self.tr("48-well Plate"), rows=6, cols=8),
            PlateLayout("96", self.tr("96-well Plate"), rows=8, cols=12),
            PlateLayout("384", self.tr("384-well Plate"), rows=16, cols=24),
        ]

        for idx, layout_def in enumerate(self.layouts):
            button = PlateLayoutButton(layout_def.name)
            button.clicked.connect(lambda _=False, d=layout_def: self._select_layout(d))
            row = idx // 2
            col = idx % 2
            grid.addWidget(button, row, col)

        custom_button = PlateLayoutButton(self.tr("Custom Layout"))
        custom_button.clicked.connect(self._custom_layout)

        grid.addWidget(custom_button, len(self.layouts) // 2, len(self.layouts) % 2)
        layout.addLayout(grid)

        tips = QLabel(
            self.tr("You can always load a saved layout after choosing a plate size.")
        )
        layout.addSpacing(12)
        tips.setWordWrap(True)
        tips.setAlignment(Qt.AlignCenter)
        tips.setObjectName("layoutTip")
        layout.addWidget(tips)

    def _setup_styling(self) -> None:
        self.setObjectName("plateLayoutDialog")
        self.setStyleSheet(
            """
            QDialog#plateLayoutDialog {
                background-color: #1E2128;
            }
            QLabel#layoutHeader {
                color: #F0F2F5;
                font-size: 16px;
                font-weight: 600;
            }
            QLabel#layoutTip {
                color: #B0B3B8;
                font-size: 12px;
            }
            QPushButton[plateButton="true"] {
                background-color: #4A90E2;
                border: none;
                border-radius: 8px;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 500;
                padding: 0 24px;
                min-height: 48px;
            }
            QPushButton[plateButton="true"]:hover {
                background-color: #68A8F5;
            }
            QPushButton[plateButton="true"]:pressed {
                background-color: #357ABD;
            }
            """
        )

    def _select_layout(self, layout_def: PlateLayout) -> None:
        self.selected_layout = layout_def
        if isinstance(self.parent(), QDialog):
            self.parent().setProperty("selected_plate_layout", layout_def.key)
        self.accept()

    def _custom_layout(self) -> None:
        dialog = CustomLayoutDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.selected_layout = dialog.values()
            self.accept()
