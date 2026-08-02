"""
Lumen Circuit Studio — Property Editor Widget

Displays and edits properties of selected schematic components.
"""
from lumen.qt.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView
)
from lumen.qt.QtCore import Qt


class PropertyEditorWidget(QWidget):
    """Property panel showing attributes of selected items."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.title_label = QLabel("No selection")
        self.title_label.setStyleSheet("""
            font-weight: bold;
            font-size: 12px;
            color: #6b9ece;
            padding: 4px;
            background: transparent;
        """)
        layout.addWidget(self.title_label)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Property", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

        self._current_item = None
        self._callback = None

    def show_properties(self, name: str, properties: dict,
                        callback=None):
        """Display properties for a selected item.
        
        Args:
            name: Display name (e.g., "R0 (resistor)")
            properties: Dict of property name -> value
            callback: Called with (key, new_value) when user edits
        """
        self._callback = callback
        self.title_label.setText(name)
        self.table.blockSignals(True)
        self.table.setRowCount(len(properties))
        for row, (key, value) in enumerate(properties.items()):
            key_item = QTableWidgetItem(str(key))
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            val_item = QTableWidgetItem(str(value))
            self.table.setItem(row, 0, key_item)
            self.table.setItem(row, 1, val_item)
        self.table.blockSignals(False)

    def clear_properties(self):
        """Clear the property display."""
        self.title_label.setText("No selection")
        self.table.setRowCount(0)
        self._callback = None

    def _on_cell_changed(self, row: int, col: int):
        """Handle user editing a property value."""
        if col == 1 and self._callback:
            key = self.table.item(row, 0).text()
            value = self.table.item(row, 1).text()
            self._callback(key, value)
