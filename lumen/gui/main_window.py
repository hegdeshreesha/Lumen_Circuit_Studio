"""
Lumen Circuit Studio — Main Window

The central application window with:
- Menu bar (File, Edit, View, Tools, Simulation, Help)
- Toolbars (drawing tools, navigation)
- Library browser dock (left)
- Property editor dock (right)
- Schematic canvas (center)
- Output/log panel (bottom)
- Status bar
"""
from PyQt6.QtWidgets import (
    QMainWindow, QDockWidget, QToolBar, QStatusBar,
    QTabWidget, QMessageBox, QFileDialog, QSplitter, QLabel,
    QWidget, QVBoxLayout, QTextEdit
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QKeySequence, QIcon

from lumen.core.database import LibraryDatabase
from lumen.gui.library_browser import LibraryBrowserWidget
from lumen.gui.schematic_editor import SchematicEditor
from lumen.gui.property_editor import PropertyEditorWidget

import os


class LumenMainWindow(QMainWindow):
    """Main application window for Lumen Circuit Studio."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumen Circuit Studio — v0.1.0")
        self.setMinimumSize(1280, 800)
        self.resize(1600, 1000)

        # Initialize database
        workspace = os.path.join(os.path.expanduser("~"), "LumenWorkspace")
        self.db = LibraryDatabase(workspace)

        # Central tab widget for editors
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setTabsClosable(True)
        self.editor_tabs.tabCloseRequested.connect(self._close_tab)

        # Create welcome tab
        self._add_welcome_tab()

        self.setCentralWidget(self.editor_tabs)

        # Build UI
        self._create_actions()
        self._create_menus()
        self._create_toolbars()
        self._create_dock_panels()
        self._create_status_bar()

    # ── Actions ───────────────────────────────────────────────

    def _create_actions(self):
        """Create all menu/toolbar actions."""
        # File
        self.act_new_lib = QAction("New Library...", self)
        self.act_new_lib.triggered.connect(self._on_new_library)

        self.act_new_cell = QAction("New Cell...", self)
        self.act_new_cell.triggered.connect(self._on_new_cell)

        self.act_new_sch = QAction("New Schematic", self)
        self.act_new_sch.setShortcut(QKeySequence("Ctrl+N"))
        self.act_new_sch.triggered.connect(self._on_new_schematic)

        self.act_open = QAction("Open...", self)
        self.act_open.setShortcut(QKeySequence("Ctrl+O"))

        self.act_save = QAction("Save", self)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save.triggered.connect(self._on_save)

        self.act_save_as = QAction("Save As...", self)
        self.act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))

        self.act_exit = QAction("Exit", self)
        self.act_exit.setShortcut(QKeySequence("Alt+F4"))
        self.act_exit.triggered.connect(self.close)

        # Edit
        self.act_undo = QAction("Undo", self)
        self.act_undo.setShortcut(QKeySequence("Ctrl+Z"))

        self.act_redo = QAction("Redo", self)
        self.act_redo.setShortcut(QKeySequence("Ctrl+Y"))

        self.act_copy = QAction("Copy", self)
        self.act_copy.setShortcut(QKeySequence("Ctrl+C"))

        self.act_paste = QAction("Paste", self)
        self.act_paste.setShortcut(QKeySequence("Ctrl+V"))

        self.act_delete = QAction("Delete", self)
        self.act_delete.setShortcut(QKeySequence("Delete"))

        self.act_select_all = QAction("Select All", self)
        self.act_select_all.setShortcut(QKeySequence("Ctrl+A"))

        # View
        self.act_zoom_in = QAction("Zoom In", self)
        self.act_zoom_in.setShortcut(QKeySequence("Ctrl+="))

        self.act_zoom_out = QAction("Zoom Out", self)
        self.act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))

        self.act_zoom_fit = QAction("Zoom to Fit", self)
        self.act_zoom_fit.setShortcut(QKeySequence("F"))

        # Draw
        self.act_add_wire = QAction("Wire (W)", self)
        self.act_add_wire.setShortcut(QKeySequence("W"))
        self.act_add_wire.triggered.connect(self._on_draw_wire)

        self.act_add_instance = QAction("Instance (I)", self)
        self.act_add_instance.setShortcut(QKeySequence("I"))
        self.act_add_instance.triggered.connect(self._on_add_instance)

        self.act_add_pin = QAction("Pin (P)", self)
        self.act_add_pin.setShortcut(QKeySequence("P"))

        self.act_add_label = QAction("Net Label (L)", self)
        self.act_add_label.setShortcut(QKeySequence("L"))
        self.act_add_label.triggered.connect(self._on_add_label)

        self.act_escape = QAction("Cancel", self)
        self.act_escape.setShortcut(QKeySequence("Escape"))
        self.act_escape.triggered.connect(self._on_escape)

        # Simulation
        self.act_netlist = QAction("Generate Netlist", self)
        self.act_netlist.setShortcut(QKeySequence("Ctrl+Shift+N"))

        self.act_simulate = QAction("Run Simulation", self)
        self.act_simulate.setShortcut(QKeySequence("F5"))

        self.act_ade = QAction("Open ADE...", self)

        # Hierarchy
        self.act_push_down = QAction("Push Down (E)", self)
        self.act_push_down.setShortcut(QKeySequence("E"))

        self.act_pop_up = QAction("Pop Up (Ctrl+E)", self)
        self.act_pop_up.setShortcut(QKeySequence("Ctrl+E"))

    # ── Menus ─────────────────────────────────────────────────

    def _create_menus(self):
        """Build the menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_new_lib)
        file_menu.addAction(self.act_new_cell)
        file_menu.addAction(self.act_new_sch)
        file_menu.addSeparator()
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_exit)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_copy)
        edit_menu.addAction(self.act_paste)
        edit_menu.addAction(self.act_delete)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_select_all)

        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        view_menu.addAction(self.act_zoom_fit)

        # Draw menu
        draw_menu = menubar.addMenu("&Draw")
        draw_menu.addAction(self.act_add_wire)
        draw_menu.addAction(self.act_add_instance)
        draw_menu.addAction(self.act_add_pin)
        draw_menu.addAction(self.act_add_label)

        # Hierarchy menu
        hier_menu = menubar.addMenu("&Hierarchy")
        hier_menu.addAction(self.act_push_down)
        hier_menu.addAction(self.act_pop_up)

        # Simulation menu
        sim_menu = menubar.addMenu("&Simulation")
        sim_menu.addAction(self.act_netlist)
        sim_menu.addAction(self.act_simulate)
        sim_menu.addSeparator()
        sim_menu.addAction(self.act_ade)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(QAction("PDK Manager...", self))
        tools_menu.addAction(QAction("Options...", self))

        # Help menu
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(QAction("Documentation", self))
        about_act = QAction("About Lumen Circuit Studio", self)
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

    # ── Toolbars ──────────────────────────────────────────────

    def _create_toolbars(self):
        """Create the main toolbars."""
        # File toolbar
        file_tb = QToolBar("File")
        file_tb.setIconSize(QSize(20, 20))
        file_tb.addAction(self.act_new_sch)
        file_tb.addAction(self.act_save)
        self.addToolBar(file_tb)

        # Edit toolbar
        edit_tb = QToolBar("Edit")
        edit_tb.setIconSize(QSize(20, 20))
        edit_tb.addAction(self.act_undo)
        edit_tb.addAction(self.act_redo)
        self.addToolBar(edit_tb)

        # Draw toolbar
        draw_tb = QToolBar("Draw")
        draw_tb.setIconSize(QSize(20, 20))
        draw_tb.addAction(self.act_add_wire)
        draw_tb.addAction(self.act_add_instance)
        draw_tb.addAction(self.act_add_pin)
        draw_tb.addAction(self.act_add_label)
        self.addToolBar(draw_tb)

        # View toolbar
        view_tb = QToolBar("View")
        view_tb.setIconSize(QSize(20, 20))
        view_tb.addAction(self.act_zoom_in)
        view_tb.addAction(self.act_zoom_out)
        view_tb.addAction(self.act_zoom_fit)
        self.addToolBar(view_tb)

        # Simulation toolbar
        sim_tb = QToolBar("Simulation")
        sim_tb.setIconSize(QSize(20, 20))
        sim_tb.addAction(self.act_netlist)
        sim_tb.addAction(self.act_simulate)
        self.addToolBar(sim_tb)

    # ── Dock Panels ───────────────────────────────────────────

    def _create_dock_panels(self):
        """Create the dockable side panels."""
        # Library browser (left)
        self.lib_browser = LibraryBrowserWidget(self.db, parent=self)
        self.lib_browser.view_open_requested.connect(self._open_view)

        lib_dock = QDockWidget("Library Browser", self)
        lib_dock.setWidget(self.lib_browser)
        lib_dock.setMinimumWidth(250)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, lib_dock)

        # Property editor (right)
        self.prop_editor = PropertyEditorWidget(parent=self)
        prop_dock = QDockWidget("Properties", self)
        prop_dock.setWidget(self.prop_editor)
        prop_dock.setMinimumWidth(250)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, prop_dock)

        # Output log (bottom)
        self.output_log = QTextEdit()
        self.output_log.setReadOnly(True)
        self.output_log.setMaximumHeight(180)
        self.output_log.setPlaceholderText("Output log...")
        log_dock = QDockWidget("Output", self)
        log_dock.setWidget(self.output_log)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, log_dock)

    # ── Status Bar ────────────────────────────────────────────

    def _create_status_bar(self):
        """Create the status bar."""
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.coord_label = QLabel("X: 0  Y: 0")
        self.coord_label.setStyleSheet("color: #ffffff; padding: 0 12px;")
        self.mode_label = QLabel("Mode: Select")
        self.mode_label.setStyleSheet(
            "color: #ffffff; font-weight: bold; padding: 0 12px;"
        )
        self.grid_label = QLabel("Grid: 10")
        self.grid_label.setStyleSheet("color: #ffffff; padding: 0 12px;")
        sb.addPermanentWidget(self.mode_label)
        sb.addPermanentWidget(self.coord_label)
        sb.addPermanentWidget(self.grid_label)
        sb.showMessage("Ready — Lumen Circuit Studio v0.1.0")

    # ── Welcome Tab ───────────────────────────────────────────

    def _add_welcome_tab(self):
        """Add a welcome/start tab."""
        welcome = QWidget()
        layout = QVBoxLayout(welcome)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("✦ Lumen Circuit Studio")
        title.setStyleSheet("""
            font-size: 32px;
            font-weight: bold;
            color: #6b9ece;
            background: transparent;
            padding: 20px;
        """)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Next-Generation Open-Source Analog/Mixed-Signal EDA Suite\n\n"
            "Create a new schematic (Ctrl+N) or open a design from the "
            "Library Browser"
        )
        subtitle.setStyleSheet("""
            font-size: 14px;
            color: #808080;
            background: transparent;
            padding: 10px;
        """)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        self.editor_tabs.addTab(welcome, "Welcome")

    # ── Slot: Open View ───────────────────────────────────────

    def _open_view(self, library: str, cell: str, view: str):
        """Open a schematic/symbol/layout view in a new tab."""
        tab_title = f"{cell} ({view})"
        # Check if already open
        for i in range(self.editor_tabs.count()):
            if self.editor_tabs.tabText(i) == tab_title:
                self.editor_tabs.setCurrentIndex(i)
                return

        if view == "schematic":
            editor = SchematicEditor(self.db, library, cell, view, parent=self)
            editor.coord_changed.connect(self._update_coords)
            editor.mode_changed.connect(self._update_mode)
            self.editor_tabs.addTab(editor, tab_title)
            self.editor_tabs.setCurrentWidget(editor)
            self.log(f"Opened {library}/{cell}/{view}")
        elif view == "symbol":
            # TODO: Symbol editor
            self.log(f"Symbol editor not yet implemented for {cell}")
        else:
            self.log(f"View type '{view}' not yet supported")

    # ── Slot Handlers ─────────────────────────────────────────

    def _on_new_library(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Library", "Library name:")
        if ok and name:
            try:
                self.db.create_library(name)
                self.lib_browser.refresh()
                self.log(f"Created library: {name}")
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))

    def _on_new_cell(self):
        from PyQt6.QtWidgets import QInputDialog
        libs = [lib.name for lib in self.db.get_libraries()]
        if not libs:
            QMessageBox.warning(self, "Error", "Create a library first.")
            return
        lib, ok = QInputDialog.getItem(self, "Select Library", "Library:", libs)
        if ok and lib:
            name, ok2 = QInputDialog.getText(self, "New Cell", "Cell name:")
            if ok2 and name:
                self.db.create_cell(lib, name)
                # Auto-create schematic view
                self.db.save_view(lib, name, "schematic", {
                    "type": "schematic", "name": name, "library": lib,
                    "instances": [], "wires": [], "labels": [], "pins": []
                })
                self.db.save_view(lib, name, "symbol", {
                    "type": "symbol", "name": name, "library": lib,
                    "pins": [], "shapes": [], "parameters": [],
                    "label": {"text": name, "x": 0, "y": 0}
                })
                self.lib_browser.refresh()
                self.log(f"Created cell: {lib}/{name}")

    def _on_new_schematic(self):
        """Create a new untitled schematic tab."""
        editor = SchematicEditor(self.db, "", "untitled", "schematic", parent=self)
        editor.coord_changed.connect(self._update_coords)
        editor.mode_changed.connect(self._update_mode)
        idx = self.editor_tabs.addTab(editor, "untitled (schematic)")
        self.editor_tabs.setCurrentIndex(idx)
        self.log("New schematic created")

    def _on_save(self):
        editor = self._current_editor()
        if editor and hasattr(editor, 'save'):
            editor.save()
            self.log("Saved")

    def _on_draw_wire(self):
        editor = self._current_editor()
        if editor and isinstance(editor, SchematicEditor):
            editor.set_mode("wire")

    def _on_add_instance(self):
        editor = self._current_editor()
        if editor and isinstance(editor, SchematicEditor):
            editor.start_instance_placement()

    def _on_add_label(self):
        editor = self._current_editor()
        if editor and isinstance(editor, SchematicEditor):
            editor.set_mode("label")

    def _on_escape(self):
        editor = self._current_editor()
        if editor and isinstance(editor, SchematicEditor):
            editor.set_mode("select")

    def _close_tab(self, index: int):
        if index > 0:  # Don't close welcome tab
            self.editor_tabs.removeTab(index)

    def _on_about(self):
        QMessageBox.about(
            self, "About Lumen Circuit Studio",
            "<h2>✦ Lumen Circuit Studio</h2>"
            "<p>Version 0.1.0</p>"
            "<p>Next-Generation Open-Source Analog/Mixed-Signal EDA Suite</p>"
            "<p>Powered by GSPICE Simulator Engine</p>"
            "<hr>"
            "<p>Features: Schematic Capture · Symbol Editor · "
            "Library Manager · ADE · Waveform Viewer · PDK Manager</p>"
        )

    # ── Helpers ───────────────────────────────────────────────

    def _current_editor(self) -> QWidget | None:
        return self.editor_tabs.currentWidget()

    def _update_coords(self, x: float, y: float):
        self.coord_label.setText(f"X: {x:.1f}  Y: {y:.1f}")

    def _update_mode(self, mode: str):
        self.mode_label.setText(f"Mode: {mode.capitalize()}")

    def log(self, msg: str):
        """Write a message to the output log."""
        self.output_log.append(f"→ {msg}")
