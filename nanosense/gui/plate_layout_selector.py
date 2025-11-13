# nanosense/gui/plate_layout_selector.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QGridLayout,
    QPushButton,
    QDialogButtonBox,
    QHBoxLayout,
    QSpinBox,
)


@dataclass
class PlateLayout:
    key: str
    name: str
    rows: int
    cols: int


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
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QLabel(self.tr("Choose a plate layout before configuration"))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(header)

        grid = QGridLayout()
        grid.setSpacing(16)

        self.layouts = [
            PlateLayout("48", self.tr("48-well Plate"), rows=6, cols=8),
            PlateLayout("96", self.tr("96-well Plate"), rows=8, cols=12),
            PlateLayout("384", self.tr("384-well Plate"), rows=16, cols=24),
        ]

        for idx, layout_def in enumerate(self.layouts):
            button = QPushButton(layout_def.name)
            button.setMinimumSize(230, 100)
            button.setCheckable(False)
            button.clicked.connect(lambda _=False, d=layout_def: self._select_layout(d))
            row = idx // 2
            col = idx % 2
            grid.addWidget(button, row, col)

        custom_button = QPushButton(self.tr("Custom Layout"))
        custom_button.setMinimumSize(230, 100)
        custom_button.clicked.connect(self._custom_layout)

        grid.addWidget(custom_button, len(self.layouts) // 2, len(self.layouts) % 2)
        layout.addLayout(grid)

        tips = QLabel(
            self.tr("You can always load a saved layout after choosing a plate size.")
        )
        tips.setWordWrap(True)
        tips.setAlignment(Qt.AlignCenter)
        tips.setStyleSheet("color: #888;")
        layout.addWidget(tips)

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
