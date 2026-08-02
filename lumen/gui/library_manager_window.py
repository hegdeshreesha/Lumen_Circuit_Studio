"""
Lumen Circuit Studio — Library Manager Window

Standalone window for managing libraries, cells, and views.
Analogous to Cadence's Library Manager (CDB Browser).
"""
from lumen.qt.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QLineEdit, QLabel, QPushButton, QMenu, QMenuBar, QToolBar,
    QStatusBar, QMessageBox, QInputDialog, QHeaderView, QTextEdit
)
from lumen.qt.QtCore import Qt, QSize
from lumen.qt.QtGui import QAction, QKeySequence, QBrush, QColor, QFont
from pathlib import Path

from lumen.core.database import LibraryDatabase
from lumen.gui.branding import apply_window_branding


class LibraryManagerWindow(QMainWindow):
    """Standalone Library Manager window."""

    ICONS = {
        "library": "📚",
        "cell": "🔲",
        "schematic": "📋",
        "symbol": "⬡",
        "layout": "🏗",
        "config": "⚙",
        "veriloga": "📄",
        "simenv": "[S]",
    }

    def __init__(self, db: LibraryDatabase, ciw=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.ciw = ciw  # Reference to APW for opening editors
        self.setWindowTitle("Lumen — Library Manager")
        apply_window_branding(self)
        self.setMinimumSize(900, 550)
        self.resize(1000, 600)

        self._selected_library = ""
        self._selected_cell = ""

        self._build_ui()
        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_status_bar()
        self.refresh()

    # ── UI Construction ───────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Search bar
        search_layout = QHBoxLayout()
        search_label = QLabel("Filter:")
        search_label.setStyleSheet("background: transparent;")
        search_layout.addWidget(search_label)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search libraries and cells...")
        self.search_box.textChanged.connect(self._on_search)
        search_layout.addWidget(self.search_box)
        layout.addLayout(search_layout)

        # Main splitter: Library tree | Cell list | View list
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Library tree (left) ──
        lib_panel = QWidget()
        lib_layout = QVBoxLayout(lib_panel)
        lib_layout.setContentsMargins(0, 0, 0, 0)
        lib_header = QLabel("Libraries")
        lib_header.setStyleSheet("""
            font-weight: bold; color: #6b9ece;
            padding: 4px; background: transparent;
        """)
        lib_layout.addWidget(lib_header)

        self.lib_tree = QTreeWidget()
        self.lib_tree.setHeaderHidden(True)
        self.lib_tree.setIndentation(12)
        self.lib_tree.currentItemChanged.connect(self._on_lib_selected)
        self.lib_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lib_tree.customContextMenuRequested.connect(self._on_lib_context)
        lib_layout.addWidget(self.lib_tree)
        splitter.addWidget(lib_panel)

        # ── Cell list (middle) ──
        cell_panel = QWidget()
        cell_layout = QVBoxLayout(cell_panel)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        self.cell_header = QLabel("Cells")
        self.cell_header.setStyleSheet("""
            font-weight: bold; color: #6b9ece;
            padding: 4px; background: transparent;
        """)
        cell_layout.addWidget(self.cell_header)

        self.cell_table = QTableWidget(0, 1)
        self.cell_table.setHorizontalHeaderLabels(["Cell Name"])
        self.cell_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.cell_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.cell_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self.cell_table.verticalHeader().setVisible(False)
        self.cell_table.currentItemChanged.connect(self._on_cell_selected)
        self.cell_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cell_table.customContextMenuRequested.connect(self._on_cell_context)
        cell_layout.addWidget(self.cell_table)
        splitter.addWidget(cell_panel)

        # ── View list (right) ──
        view_panel = QWidget()
        view_layout = QVBoxLayout(view_panel)
        view_layout.setContentsMargins(0, 0, 0, 0)
        self.view_header = QLabel("Views")
        self.view_header.setStyleSheet("""
            font-weight: bold; color: #6b9ece;
            padding: 4px; background: transparent;
        """)
        view_layout.addWidget(self.view_header)

        self.view_table = QTableWidget(0, 2)
        self.view_table.setHorizontalHeaderLabels(["View", "Type"])
        self.view_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.view_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.view_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.view_table.verticalHeader().setVisible(False)
        self.view_table.doubleClicked.connect(self._on_view_double_click)
        self.view_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view_table.customContextMenuRequested.connect(self._on_view_context)
        view_layout.addWidget(self.view_table)
        splitter.addWidget(view_panel)

        # Set proportions
        splitter.setSizes([250, 350, 300])
        layout.addWidget(splitter)

        # ── Status Panel (bottom) ──
        status_panel = QWidget()
        status_panel.setMaximumHeight(120)
        status_panel.setStyleSheet("background-color: #252525; border-top: 1px solid #3c3c3c;")
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(6, 4, 6, 4)
        status_layout.setSpacing(2)

        self.lib_count_label = QLabel("0 libraries · 0 cells")
        self.lib_count_label.setStyleSheet("color: #808080; font-size: 10px; border: none;")
        status_layout.addWidget(self.lib_count_label)

        self.lib_details = QTextEdit()
        self.lib_details.setReadOnly(True)
        self.lib_details.setFrameShape(QTextEdit.Shape.NoFrame)
        self.lib_details.setStyleSheet("background: transparent; color: #b0b0b0; font-size: 11px;")
        status_layout.addWidget(self.lib_details)

        layout.addWidget(status_panel)

    # ── Actions ───────────────────────────────────────────────

    def _create_actions(self):
        self.act_new_lib = QAction("New Library...", self)
        self.act_new_lib.setShortcut(QKeySequence("Ctrl+N"))
        self.act_new_lib.triggered.connect(self._on_new_library)

        self.act_new_cell = QAction("New Cell...", self)
        self.act_new_cell.triggered.connect(self._on_new_cell)

        self.act_refresh = QAction("Refresh", self)
        self.act_refresh.setShortcut(QKeySequence("F5"))
        self.act_refresh.triggered.connect(self.refresh)

        self.act_close = QAction("Close", self)
        self.act_close.setShortcut(QKeySequence("Ctrl+W"))
        self.act_close.triggered.connect(self.close)

    # ── Menus ─────────────────────────────────────────────────

    def _create_menus(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_new_lib)
        file_menu.addAction(self.act_new_cell)
        file_menu.addSeparator()
        file_menu.addAction(self.act_refresh)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(QAction("Rename...", self))
        edit_menu.addAction(QAction("Copy...", self))
        act_delete = QAction("Delete", self)
        act_delete.setShortcut(QKeySequence("Delete"))
        edit_menu.addAction(act_delete)

    # ── Toolbar ───────────────────────────────────────────────

    def _create_toolbar(self):
        tb = QToolBar("Library Manager")
        tb.setIconSize(QSize(18, 18))
        tb.addAction(self.act_new_lib)
        tb.addAction(self.act_new_cell)
        tb.addSeparator()
        tb.addAction(self.act_refresh)
        self.addToolBar(tb)

    # ── Status Bar ────────────────────────────────────────────

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lib_count_label = QLabel()
        self.lib_count_label.setStyleSheet("color: #ffffff; padding: 0 8px;")
        sb.addPermanentWidget(self.lib_count_label)

    # ── Refresh / Load ────────────────────────────────────────

    def refresh(self):
        """Reload all library data including active PDK."""
        self.lib_tree.clear()
        libs = self.db.get_libraries()

        for lib in libs:
            item = QTreeWidgetItem([f"{self.ICONS['library']} {lib.name}"])
            item.setData(0, Qt.ItemDataRole.UserRole, lib.name)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, "user")  # type
            item.setForeground(0, QBrush(QColor("#8caacc")))
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            self.lib_tree.addTopLevelItem(item)

        # Add active PDK as virtual library
        pdk_registry = None
        if self.ciw and hasattr(self.ciw, 'pdk_registry'):
            pdk_registry = self.ciw.pdk_registry
        if pdk_registry:
            pdk = pdk_registry.get_active_pdk()
            if pdk:
                pdk_item = QTreeWidgetItem(
                    [f"\U0001f4e6 {pdk.display_name}"])
                pdk_item.setData(0, Qt.ItemDataRole.UserRole, f"pdk:{pdk.name}")
                pdk_item.setData(0, Qt.ItemDataRole.UserRole + 1, "pdk")
                pdk_item.setForeground(0, QBrush(QColor("#8bc78b")))
                font = pdk_item.font(0)
                font.setBold(True)
                pdk_item.setFont(0, font)
                self.lib_tree.addTopLevelItem(pdk_item)

        count = len(libs)
        total_cells = sum(len(self.db.get_cells(l.name)) for l in libs)
        self.lib_count_label.setText(
            f"{count} libraries · {total_cells} cells")

    # ── Library Selection ─────────────────────────────────────

    def _on_lib_selected(self, current, previous):
        if current is None:
            return
        lib_key = current.data(0, Qt.ItemDataRole.UserRole)
        if not lib_key:
            return
        lib_type = current.data(0, Qt.ItemDataRole.UserRole + 1) or "user"
        self._selected_library = lib_key
        self._selected_cell = ""

        # Update details pane
        lib_info = self.db.get_library(lib_key)
        if lib_info:
            desc = lib_info.description or "No description."
            self.lib_details.setText(
                f"<b>Path:</b> {lib_info.path}<br>"
                f"<b>Tech:</b> {lib_info.tech or 'None'}<br>"
                f"<br><b>Description:</b><br>{desc}"
            )
        elif lib_type == "pdk":
            pdk_name = lib_key.replace("pdk:", "")
            if self.ciw and hasattr(self.ciw, 'pdk_registry'):
                pdk = self.ciw.pdk_registry.get_pdk(pdk_name)
                if pdk:
                    self.lib_details.setText(
                        f"<b>Foundry:</b> {pdk.foundry}<br>"
                        f"<b>Process:</b> {pdk.process}<br>"
                        f"<b>Node:</b> {pdk.node}<br>"
                        f"<br><b>Description:</b><br>{pdk.description}"
                    )
        else:
            self.lib_details.clear()

        # Update cell list
        self.cell_table.setRowCount(0)
        
        if lib_type == "pdk":
            pdk_name = lib_key.replace("pdk:", "")
            if self.ciw and hasattr(self.ciw, 'pdk_registry'):
                pdk = self.ciw.pdk_registry.get_pdk(pdk_name)
                if pdk:
                    cats = {
                        "MOSFET": "\u22de", "Resistor": "\u23da", 
                        "Capacitor": "\u229f", "Diode": "\u25ee", 
                        "BJT": "\u22b3", "Inductor": "\u223f"
                    }
                    self.cell_table.setRowCount(len(pdk.devices))
                    for row, dev in enumerate(pdk.devices):
                        category = dev.category.value if hasattr(dev.category, "value") else str(dev.category)
                        icon = cats.get(category, "\u25fb")
                        item = QTableWidgetItem(f" {icon}  {dev.name}")
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.cell_table.setItem(row, 0, item)
        else:
            cells = self.db.get_cells(lib_key)
            self.cell_table.setRowCount(len(cells))
            for row, cell in enumerate(cells):
                views = self.db.get_views(lib_key, cell)
                icon = self.ICONS.get(views[0], self.ICONS['schematic']) if views else "\U0001f4c4"
                item = QTableWidgetItem(f" {icon}  {cell}")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.cell_table.setItem(row, 0, item)

        self.view_table.setRowCount(0)
        self.view_header.setText("Views")

    # ── Cell Selection ────────────────────────────────────────

    def _on_cell_selected(self, current, previous):
        if current is None:
            return
        cell_name = current.text().strip()
        for icon in self.ICONS.values():
            cell_name = cell_name.replace(icon, "").strip()
        # Also strip PDK category icons
        for ch in "\u22de\u23da\u229f\u25ee\u22b3\u223f\u25fb":
            cell_name = cell_name.replace(ch, "").strip()
        self._selected_cell = cell_name
        self.view_header.setText(f"Views \u2014 {cell_name}")
        
        if not self._selected_library:
            return

        if self._selected_library.startswith("pdk:"):
            # PDK device — show symbol view
            self.view_table.setRowCount(1)
            name_item = QTableWidgetItem(f" {self.ICONS['symbol']}  symbol")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            type_item = QTableWidgetItem("symbol")
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.view_table.setItem(0, 0, name_item)
            self.view_table.setItem(0, 1, type_item)
        else:
            # Regular library
            views = self.db.get_views(self._selected_library, cell_name)
            self.view_table.setRowCount(len(views))
            for row, view_name in enumerate(views):
                icon = self.ICONS.get(view_name, "\U0001f4c4")
                name_item = QTableWidgetItem(f" {icon}  {view_name}")
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                type_item = QTableWidgetItem(view_name)
                type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.view_table.setItem(row, 0, name_item)
                self.view_table.setItem(row, 1, type_item)

    # ── View Double-Click → Open Editor ───────────────────────

    def _on_view_double_click(self, index):
        if not self._selected_library or not self._selected_cell:
            return
        row = index.row()
        type_item = self.view_table.item(row, 1)
        if type_item:
            view = type_item.text().strip()
            self._open_editor(self._selected_library, self._selected_cell, view)

    def _open_editor(self, library: str, cell: str, view: str):
        """Ask the APW to open the appropriate editor."""
        if self.ciw:
            if hasattr(self.ciw, "open_cellview"):
                self.ciw.open_cellview(library, cell, view)
            else:
                self.ciw.open_schematic_editor(library, cell, view)
        self.statusBar().showMessage(f"Opened {library}/{cell}/{view}")

    # ── Context Menus ─────────────────────────────────────────

    def _on_lib_context(self, pos):
        menu = QMenu(self)
        item = self.lib_tree.itemAt(pos)
        if item:
            lib_name = item.data(0, Qt.ItemDataRole.UserRole)
            act_new_cell = menu.addAction("New Cell...")
            act_new_cell.triggered.connect(lambda: self._on_new_cell(lib_name))
            menu.addSeparator()
            act_rename = menu.addAction("Rename Library...")
            act_rename.triggered.connect(lambda: self._rename_library(lib_name))
            act_delete = menu.addAction("Delete Library")
            act_delete.triggered.connect(lambda: self._delete_library(lib_name))
        else:
            act_new = menu.addAction("New Library...")
            act_new.triggered.connect(self._on_new_library)
        menu.exec(self.lib_tree.viewport().mapToGlobal(pos))

    def _on_cell_context(self, pos):
        if not self._selected_library:
            return
        menu = QMenu(self)
        row = self.cell_table.rowAt(pos.y())
        if row >= 0:
            item = self.cell_table.item(row, 0)
            cell_name = item.text().strip()
            for icon in self.ICONS.values():
                cell_name = cell_name.replace(icon, "").strip()

            act_open_sch = menu.addAction("Open Schematic")
            act_open_sch.triggered.connect(
                lambda: self._open_editor(
                    self._selected_library, cell_name, "schematic"))
            act_open_sym = menu.addAction("Open Symbol")
            act_open_sym.triggered.connect(
                lambda: self._open_editor(
                    self._selected_library, cell_name, "symbol"))
            menu.addSeparator()
            act_del = menu.addAction("Delete Cell")
            act_del.triggered.connect(
                lambda: self._delete_cell(self._selected_library, cell_name))
        else:
            act_new = menu.addAction("New Cell...")
            act_new.triggered.connect(
                lambda: self._on_new_cell(self._selected_library))
        menu.exec(self.cell_table.viewport().mapToGlobal(pos))

    def _on_view_context(self, pos):
        if not self._selected_library or not self._selected_cell:
            return
        menu = QMenu(self)
        row = self.view_table.rowAt(pos.y())
        if row >= 0:
            type_item = self.view_table.item(row, 1)
            if type_item:
                view = type_item.text().strip()
                act_open = menu.addAction("Open")
                act_open.triggered.connect(
                    lambda: self._open_editor(
                        self._selected_library, self._selected_cell, view))
        menu.exec(self.view_table.viewport().mapToGlobal(pos))

    # ── Operations ────────────────────────────────────────────

    def _on_new_library(self):
        name, ok = QInputDialog.getText(self, "New Library", "Library name:")
        if ok and name:
            try:
                self.db.create_library(name)
                self.refresh()
                if self.ciw:
                    self.ciw.log(f"Created library: {name}")
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))

    def _on_new_cell(self, library: str = ""):
        if not library:
            library = self._selected_library
        if not library:
            libs = [l.name for l in self.db.get_libraries()]
            if not libs:
                QMessageBox.warning(self, "Error", "Create a library first.")
                return
            library, ok = QInputDialog.getItem(
                self, "Select Library", "Library:", libs)
            if not ok:
                return

        name, ok = QInputDialog.getText(self, "New Cell", "Cell name:")
        if ok and name:
            try:
                lib_info = self.db.get_library(library)
                default_cell_path = str(Path(lib_info.path) / name) if lib_info else name
                cell_path, ok_path = QInputDialog.getText(
                    self,
                    "New Cell Path",
                    f"Path for {library}/{name}:",
                    text=default_cell_path,
                )
                if not ok_path or not cell_path.strip():
                    return
                self.db.create_cell(library, name, cell_path.strip())
                # Auto-create schematic and symbol views
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
                # Re-select the library to refresh cell list
                for i in range(self.lib_tree.topLevelItemCount()):
                    item = self.lib_tree.topLevelItem(i)
                    if item.data(0, Qt.ItemDataRole.UserRole) == library:
                        self.lib_tree.setCurrentItem(item)
                        break
                if self.ciw:
                    self.ciw.log(f"Created cell: {library}/{name}")
            except ValueError as exc:
                QMessageBox.warning(self, "New Cell", str(exc))

    def _rename_library(self, old_name: str):
        new_name, ok = QInputDialog.getText(
            self, "Rename Library", "New name:", text=old_name)
        if ok and new_name and new_name != old_name:
            try:
                self.db.rename_library(old_name, new_name)
                self.refresh()
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))

    def _delete_library(self, name: str):
        reply = QMessageBox.question(
            self, "Delete Library",
            f"Delete library '{name}' and all its contents?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_library(name)
            self.refresh()
            self.cell_table.setRowCount(0)
            self.view_table.setRowCount(0)

    def _delete_cell(self, library: str, cell: str):
        reply = QMessageBox.question(
            self, "Delete Cell",
            f"Delete cell '{cell}' from '{library}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_cell(library, cell)
            # Refresh cell list
            for i in range(self.lib_tree.topLevelItemCount()):
                item = self.lib_tree.topLevelItem(i)
                if item.data(0, Qt.ItemDataRole.UserRole) == library:
                    self.lib_tree.setCurrentItem(item)
                    break

    # ── Search / Filter ───────────────────────────────────────

    def _on_search(self, text: str):
        text = text.lower()
        for i in range(self.lib_tree.topLevelItemCount()):
            item = self.lib_tree.topLevelItem(i)
            lib_name = item.data(0, Qt.ItemDataRole.UserRole) or ""
            visible = not text or text in lib_name.lower()
            # Also check cells
            if not visible:
                cells = self.db.get_cells(lib_name)
                for c in cells:
                    if text in c.lower():
                        visible = True
                        break
            item.setHidden(not visible)
