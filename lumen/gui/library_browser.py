"""
Lumen Circuit Studio — Library Browser Widget

Tree-based library/cell/view navigator, similar to Cadence's Library Manager.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QMenu, QMessageBox, QInputDialog, QHBoxLayout, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QBrush, QFont

from lumen.core.database import LibraryDatabase


class LibraryBrowserWidget(QWidget):
    """Tree-based library browser dock widget."""

    # Signal: (library, cell, view) when user wants to open a view
    view_open_requested = pyqtSignal(str, str, str)

    # Icons as Unicode characters (will be replaced with proper icons later)
    ICONS = {
        "library": "📚",
        "cell": "🔲",
        "schematic": "📋",
        "symbol": "⬡",
        "layout": "🏗",
        "config": "⚙",
        "veriloga": "📄",
    }

    def __init__(self, db: LibraryDatabase, parent=None):
        super().__init__(parent)
        self.db = db
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search libraries...")
        self.search_box.textChanged.connect(self._on_search)
        search_layout.addWidget(self.search_box)

        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setFixedSize(28, 28)
        self.refresh_btn.setToolTip("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        search_layout.addWidget(self.refresh_btn)
        layout.addLayout(search_layout)

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Type"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setAlternatingRowColors(False)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree)

    def refresh(self):
        """Reload the tree from the database."""
        self.tree.clear()
        for lib in self.db.get_libraries():
            lib_item = QTreeWidgetItem([
                f"{self.ICONS['library']} {lib.name}", "Library"
            ])
            lib_item.setData(0, Qt.ItemDataRole.UserRole, ("library", lib.name))
            lib_item.setForeground(0, QBrush(QColor("#6b9ece")))
            font = lib_item.font(0)
            font.setBold(True)
            lib_item.setFont(0, font)

            # Add cells
            for cell_name in self.db.get_cells(lib.name):
                cell_item = QTreeWidgetItem([
                    f"{self.ICONS['cell']} {cell_name}", "Cell"
                ])
                cell_item.setData(0, Qt.ItemDataRole.UserRole,
                                  ("cell", lib.name, cell_name))
                cell_item.setForeground(0, QBrush(QColor("#8caacc")))

                # Add views
                for view_name in self.db.get_views(lib.name, cell_name):
                    icon = self.ICONS.get(view_name, "📄")
                    view_item = QTreeWidgetItem([
                        f"  {icon} {view_name}", "View"
                    ])
                    view_item.setData(0, Qt.ItemDataRole.UserRole,
                                      ("view", lib.name, cell_name, view_name))
                    view_item.setForeground(0, QBrush(QColor("#808080")))
                    cell_item.addChild(view_item)

                lib_item.addChild(cell_item)

            self.tree.addTopLevelItem(lib_item)
            lib_item.setExpanded(True)

    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        """Open a view when double-clicked."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "view":
            _, lib, cell, view = data
            self.view_open_requested.emit(lib, cell, view)

    def _on_context_menu(self, pos):
        """Show context menu based on what's selected."""
        item = self.tree.itemAt(pos)
        menu = QMenu(self)

        if item is None:
            # Click on empty space
            act_new_lib = menu.addAction("New Library...")
            act_new_lib.triggered.connect(self._ctx_new_library)
        else:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data[0] == "library":
                act_new_cell = menu.addAction("New Cell...")
                act_new_cell.triggered.connect(
                    lambda: self._ctx_new_cell(data[1]))
                menu.addSeparator()
                act_rename = menu.addAction("Rename Library...")
                act_rename.triggered.connect(
                    lambda: self._ctx_rename_library(data[1]))
                act_del = menu.addAction("Delete Library")
                act_del.triggered.connect(
                    lambda: self._ctx_delete_library(data[1]))
            elif data[0] == "cell":
                act_open_sch = menu.addAction("Open Schematic")
                act_open_sch.triggered.connect(
                    lambda: self.view_open_requested.emit(
                        data[1], data[2], "schematic"))
                act_open_sym = menu.addAction("Open Symbol")
                act_open_sym.triggered.connect(
                    lambda: self.view_open_requested.emit(
                        data[1], data[2], "symbol"))
                menu.addSeparator()
                act_del = menu.addAction("Delete Cell")
                act_del.triggered.connect(
                    lambda: self._ctx_delete_cell(data[1], data[2]))
            elif data[0] == "view":
                act_open = menu.addAction("Open")
                act_open.triggered.connect(
                    lambda: self.view_open_requested.emit(
                        data[1], data[2], data[3]))

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_search(self, text: str):
        """Filter the tree based on search text."""
        text = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            lib_item = self.tree.topLevelItem(i)
            lib_visible = False
            for j in range(lib_item.childCount()):
                cell_item = lib_item.child(j)
                data = cell_item.data(0, Qt.ItemDataRole.UserRole)
                cell_name = data[2] if data else ""
                visible = not text or text in cell_name.lower()
                cell_item.setHidden(not visible)
                if visible:
                    lib_visible = True
            lib_item.setHidden(not lib_visible and bool(text))

    # ── Context Menu Actions ──────────────────────────────────

    def _ctx_new_library(self):
        name, ok = QInputDialog.getText(self, "New Library", "Library name:")
        if ok and name:
            try:
                self.db.create_library(name)
                self.refresh()
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))

    def _ctx_new_cell(self, library: str):
        name, ok = QInputDialog.getText(self, "New Cell", "Cell name:")
        if ok and name:
            self.db.create_cell(library, name)
            self.db.save_view(library, name, "schematic", {
                "type": "schematic", "name": name, "library": library,
                "instances": [], "wires": [], "labels": [], "pins": []
            })
            self.db.save_view(library, name, "symbol", {
                "type": "symbol", "name": name, "library": library,
                "pins": [], "shapes": [], "parameters": [],
                "label": {"text": name, "x": 0, "y": 0}
            })
            self.refresh()

    def _ctx_rename_library(self, old_name: str):
        new_name, ok = QInputDialog.getText(
            self, "Rename Library", "New name:", text=old_name)
        if ok and new_name and new_name != old_name:
            try:
                self.db.rename_library(old_name, new_name)
                self.refresh()
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))

    def _ctx_delete_library(self, name: str):
        reply = QMessageBox.question(
            self, "Delete Library",
            f"Are you sure you want to delete library '{name}' "
            f"and all its contents?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_library(name)
            self.refresh()

    def _ctx_delete_cell(self, library: str, cell: str):
        reply = QMessageBox.question(
            self, "Delete Cell",
            f"Delete cell '{cell}' from library '{library}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_cell(library, cell)
            self.refresh()
