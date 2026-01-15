# nanosense/gui/spectrum_classification_dialog.py

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QDialogButtonBox,
    QCheckBox,
)
from PyQt5.QtCore import Qt


class SpectrumClassificationDialog(QDialog):
    CATEGORY_OPTIONS = [
        ("Absorbance", "absorbance"),
        ("Reference", "reference"),
        ("Background", "background"),
    ]

    def __init__(self, spectrum_names, default_categories, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Confirm Spectrum Categories"))
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("Review and adjust spectrum categories:")))

        self.table = QTableWidget(len(spectrum_names), 2, self)
        self.table.setHorizontalHeaderLabels([
            self.tr("Spectrum"),
            self.tr("Category"),
        ])
        self.table.verticalHeader().setVisible(False)

        self._combos = []
        for row, name in enumerate(spectrum_names):
            name_item = QTableWidgetItem(str(name))
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, name_item)

            combo = QComboBox(self.table)
            for label, value in self.CATEGORY_OPTIONS:
                combo.addItem(self.tr(label), value)
            default_value = default_categories[row] if row < len(default_categories) else "absorbance"
            for idx in range(combo.count()):
                if combo.itemData(idx) == default_value:
                    combo.setCurrentIndex(idx)
                    break
            self.table.setCellWidget(row, 1, combo)
            self._combos.append(combo)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        self.remember_checkbox = QCheckBox(self.tr("Don't prompt again this session"), self)
        layout.addWidget(self.remember_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_results(self):
        categories = [combo.currentData() for combo in self._combos]
        return categories, self.remember_checkbox.isChecked()
