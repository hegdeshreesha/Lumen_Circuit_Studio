"""
Lumen Circuit Studio — Property Editor Widget

Displays and edits properties of selected schematic components.
"""
from lumen.qt.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView, QComboBox
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
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#ffd166;background:transparent;padding:3px;")
        layout.addWidget(self.status_label)

        self._current_item = None
        self._callback = None
        self._row_keys: dict[int, str] = {}

    def show_properties(self, name: str, properties: dict,
                        callback=None, parameter_specs: list | None = None):
        """Display properties for a selected item.
        
        Args:
            name: Display name (e.g., "R0 (resistor)")
            properties: Dict of property name -> value
            callback: Called with (key, new_value) when user edits
        """
        self._callback = callback
        self.title_label.setText(name)
        self.status_label.clear()
        self.table.blockSignals(True)
        self._row_keys = {}
        self.table.setRowCount(len(properties))
        spec_by_label = {}
        for spec in parameter_specs or []:
            label = str(spec.get("display") or spec.get("name") or "")
            if spec.get("unit"):
                label = f"{label} ({spec.get('unit')})"
            spec_by_label[label] = spec
            spec_by_label[str(spec.get("name") or "")] = spec
        for row, (key, value) in enumerate(properties.items()):
            key_item = QTableWidgetItem(str(key))
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, key_item)
            spec = spec_by_label.get(str(key), {})
            self._row_keys[row] = str(spec.get("name") or key)
            choices = spec.get("choices") or spec.get("enum") or []
            if choices:
                combo = QComboBox()
                combo.addItems([str(item) for item in choices])
                current = str(value)
                if current and combo.findText(current) < 0:
                    combo.addItem(current)
                idx = combo.findText(current)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                combo.currentTextChanged.connect(lambda text, r=row: self._emit_row_changed(r, text))
                self.table.setCellWidget(row, 1, combo)
            else:
                val_item = QTableWidgetItem(str(value))
                if key in {"Instance", "Cell", "Library"} or spec.get("read_only") or spec.get("readonly"):
                    val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    val_item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row, 1, val_item)
        self.table.blockSignals(False)

    def clear_properties(self):
        """Clear the property display."""
        self.title_label.setText("No selection")
        self.table.setRowCount(0)
        self._callback = None
        self._row_keys = {}
        self.status_label.clear()

    def set_status(self, message: str, error: bool = False):
        self.status_label.setStyleSheet(
            "color:#ff8fa3;background:transparent;padding:3px;" if error
            else "color:#74c69d;background:transparent;padding:3px;"
        )
        self.status_label.setText(str(message or ""))

    def _on_cell_changed(self, row: int, col: int):
        """Handle user editing a property value."""
        if col == 1 and self._callback:
            key = self._row_keys.get(row) or self.table.item(row, 0).text()
            value = self.table.item(row, 1).text()
            self._callback(key, value)

    def _emit_row_changed(self, row: int, value: str):
        if self._callback:
            key = self._row_keys.get(row) or self.table.item(row, 0).text()
            self._callback(key, value)
