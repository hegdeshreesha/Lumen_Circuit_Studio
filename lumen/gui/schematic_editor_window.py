"""
Lumen Circuit Studio — Schematic Editor Window

Standalone schematic editor window with its own menu bar,
toolbars, property panel, and canvas. Opens one per design.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QDockWidget, QToolBar,
    QStatusBar, QLabel, QMessageBox, QTextEdit, QInputDialog, QFileDialog,
    QTabWidget, QApplication, QProgressDialog
)
from PyQt6.QtCore import Qt, QSize, QThread
from PyQt6.QtGui import QAction, QKeySequence

from lumen.core.database import LibraryDatabase
from lumen.core.layout_xl import LayoutXLService
from lumen.gui.schematic_editor import SchematicEditor
from lumen.gui.property_editor import PropertyEditorWidget
from lumen.gui.branding import apply_window_branding
from lumen.gui.icons import editor_icon


class SchematicEditorWindow(QMainWindow):
    """Standalone window for editing a schematic."""

    def __init__(self, db: LibraryDatabase, library: str, cell: str,
                 view: str = "schematic", ciw=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.library = library
        self.cell = cell
        self.view = view
        self.ciw = ciw
        self.layout_service = LayoutXLService(self.db)
        self._hierarchy_stack: list[tuple[str, str, str]] = []

        self.setWindowTitle(f"Lumen — {cell} ({view}) — [{library}]")
        apply_window_branding(self)
        self.setMinimumSize(1000, 700)
        self.resize(1300, 850)

        # Create the schematic editor canvas
        self.editor = SchematicEditor(db, library, cell, view, parent=self)
        self.editor.coord_changed.connect(self._update_coords)
        self.editor.mode_changed.connect(self._update_mode)
        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setDocumentMode(True)
        self.workspace_tabs.setTabsClosable(True)
        self.workspace_tabs.tabCloseRequested.connect(self._on_workspace_tab_close)
        self.workspace_tabs.addTab(self.editor, f"{cell}/{view}")
        self.setCentralWidget(self.workspace_tabs)
        self._simenv_tab = None

        # Build UI
        self._create_actions()
        self._create_menus()
        self._create_toolbars()
        self._create_dock_panels()
        self._create_status_bar()

    # ── Actions ───────────────────────────────────────────────

    def _make_action(self, text: str, shortcut: str = "", slot=None,
                     checkable: bool = False) -> QAction:
        """Create a QAction with consistent shortcut and fallback handling."""
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        if slot:
            action.triggered.connect(lambda _=False, s=slot: s())
        else:
            action.triggered.connect(lambda _=False, t=text: self._not_implemented(t))
        return action

    def _create_actions(self):
        # File
        self.act_save = QAction("Save", self)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save.triggered.connect(self._on_save)

        self.act_save_as = QAction("Save As...", self)
        self.act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.act_save_as.triggered.connect(self._on_save_as)

        self.act_close = QAction("Close", self)
        self.act_close.setShortcut(QKeySequence("Ctrl+W"))
        self.act_close.triggered.connect(self.close)

        # Edit
        self.act_undo = QAction("Undo", self)
        self.act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self.act_undo.triggered.connect(lambda: self.editor.undo())

        self.act_redo = QAction("Redo", self)
        self.act_redo.setShortcut(QKeySequence("Ctrl+Y"))
        self.act_redo.triggered.connect(lambda: self.editor.redo())

        self.act_copy = QAction("Copy", self)
        self.act_copy.setShortcut(QKeySequence("Ctrl+C"))
        self.act_copy.triggered.connect(lambda: self.editor.copy_selected())

        self.act_paste = QAction("Paste", self)
        self.act_paste.setShortcut(QKeySequence("Ctrl+V"))
        self.act_paste.triggered.connect(lambda: self.editor.paste_clipboard())

        self.act_delete = QAction("Delete", self)
        self.act_delete.setShortcut(QKeySequence("Delete"))
        self.act_delete.triggered.connect(lambda: self.editor.delete_selected())

        self.act_select_all = QAction("Select All", self)
        self.act_select_all.setShortcut(QKeySequence("Ctrl+A"))
        self.act_select_all.triggered.connect(self.editor.select_all)

        self.act_rotate = QAction("Rotate (R)", self)
        self.act_rotate.setShortcut(QKeySequence("R"))
        self.act_rotate.triggered.connect(lambda: self.editor.rotate_selected())

        self.act_mirror_x = QAction("Mirror X", self)
        self.act_mirror_x.setShortcut(QKeySequence("X"))
        self.act_mirror_x.triggered.connect(lambda: self.editor.mirror_selected_x())

        self.act_mirror_y = QAction("Mirror Y", self)
        self.act_mirror_y.triggered.connect(lambda: self.editor.mirror_selected_y())

        # View
        self.act_zoom_in = QAction("Zoom In", self)
        self.act_zoom_in.setShortcut(QKeySequence("Ctrl+="))
        self.act_zoom_in.triggered.connect(self.editor.zoom_in)

        self.act_zoom_out = QAction("Zoom Out", self)
        self.act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        self.act_zoom_out.triggered.connect(self.editor.zoom_out)

        self.act_zoom_fit = QAction("Zoom Fit", self)
        self.act_zoom_fit.setShortcut(QKeySequence("F"))
        self.act_zoom_fit.triggered.connect(self.editor.zoom_fit)

        # Draw
        self.act_wire = QAction("Wire (W)", self)
        self.act_wire.setShortcut(QKeySequence("W"))
        self.act_wire.triggered.connect(lambda: self.editor.set_mode("wire"))

        self.act_instance = QAction("Instance (I)", self)
        self.act_instance.setShortcut(QKeySequence("I"))
        self.act_instance.triggered.connect(
            self.editor.start_instance_placement)

        self.act_pin = QAction("Pin (P)", self)
        self.act_pin.setShortcut(QKeySequence("P"))
        self.act_pin.triggered.connect(lambda: self.editor.set_mode("pin"))

        self.act_label = QAction("Net Label (L)", self)
        self.act_label.setShortcut(QKeySequence("L"))
        self.act_label.triggered.connect(lambda: self.editor.set_mode("label"))

        self.act_escape = QAction("Cancel", self)
        self.act_escape.setShortcut(QKeySequence("Escape"))
        self.act_escape.triggered.connect(
            lambda: self.editor.set_mode("select"))

        # Hierarchy
        self.act_push_down = QAction("Descend (E)", self)
        self.act_push_down.setShortcut(QKeySequence("E"))
        self.act_push_down.triggered.connect(self._on_descend)

        self.act_pop_up = QAction("Return (Ctrl+E)", self)
        self.act_pop_up.setShortcut(QKeySequence("Ctrl+E"))
        self.act_pop_up.triggered.connect(self._on_return)

        # Simulation
        self.act_check_save = QAction("Check && Save", self)
        self.act_check_save.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.act_check_save.triggered.connect(self._on_save)

        self.act_netlist = QAction("Generate Netlist", self)
        self.act_netlist.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.act_netlist.triggered.connect(self._on_generate_netlist)

        self.act_simulate = QAction("Run Simulation", self)
        self.act_simulate.setShortcut(QKeySequence("F5"))
        self.act_simulate.triggered.connect(self._on_simulate)

        self.act_waveform = QAction("Waveform Viewer", self)
        self.act_waveform.triggered.connect(self._on_open_waveform)

        # Layout integration actions
        self.act_open_layout = self._make_action(
            "Open Layout (KLayout)", "Ctrl+Shift+L", self._on_open_layout)
        self.act_update_layout = self._make_action(
            "Update Layout From Schematic", slot=self._on_update_layout)
        self.act_layout_runtime = self._make_action(
            "KLayout Runtime...", slot=self._on_layout_runtime)
        self.act_run_drc = self._make_action("Run DRC...", slot=self._on_run_drc)
        self.act_run_lvs = self._make_action("Run LVS...", slot=self._on_run_lvs)

        # Cadence-style file/design commands
        self.act_new_cellview = self._make_action("New Cellview...", "Ctrl+N", self._on_new_cellview)
        self.act_open_cellview = self._make_action("Open Cellview...", "Ctrl+O", self._on_open_cellview)
        self.act_print = self._make_action("Print / Plot...", "Ctrl+P", self._on_export_image)
        self.act_export_image = self._make_action("Export Image...", slot=self._on_export_image)
        self.act_import_spice = self._make_action("Import SPICE...", slot=self._on_import_spice)
        self.act_import_verilog = self._make_action("Import Verilog-A...", slot=self._on_import_verilog)

        # Cadence-style edit commands
        self.act_move = self._make_action("Move (M)", "M", lambda: self.editor.set_mode("select"))
        self.act_stretch = self._make_action("Stretch (S)", "S", self._on_stretch)
        self.act_duplicate = self._make_action(
            "Duplicate", "Ctrl+D", self.editor.duplicate_selected)
        self.act_properties = self._make_action(
            "Object Properties (Q)", "Q", self._on_object_properties)
        self.act_find = self._make_action("Find / Select...", "Ctrl+F", self._on_find_select)
        self.act_descend_edit = self._make_action("Descend Edit", "Shift+E", self._on_descend)
        self.act_return_read = self._make_action("Return Read", "Ctrl+Shift+E", self._on_return)

        # Cadence-style display commands
        self.act_redraw = self._make_action("Redraw", "Ctrl+R", self.editor.redraw)
        self.act_pan = self._make_action("Pan", slot=self.editor.set_pan_mode)
        self.act_display_options = self._make_action("Display Options...", slot=self._on_display_options)
        self.act_grid_options = self._make_action("Grid / Snap Options...", slot=self._on_grid_options)
        self.act_layer_palette = self._make_action("Layer Palette...", slot=self._on_layer_palette)

        # Cadence-style create commands
        self.act_bus = self._make_action("Bus (B)", "B", lambda: self.editor.set_mode("bus"))
        self.act_bus_tap = self._make_action("Bus Tap", slot=self._on_bus_tap)
        self.act_wire_name = self._make_action("Wire Name...", slot=self._on_wire_name)
        self.act_note = self._make_action("Note / Annotation", slot=self._on_note)
        self.act_text = self._make_action("Text", slot=self._on_note)
        self.act_sheet_pin = self._make_action("Sheet Pin", slot=lambda: self.editor.set_mode("pin"))
        self.act_symbol = self._make_action(
            "Create Symbol From Cellview...", slot=self._on_create_symbol)

        # Lumen extras beyond Virtuoso
        self.act_quick_probe = self._make_action("Quick Probe Selected", slot=self._on_quick_probe)
        self.act_health_check = self._make_action(
            "Design Health Check", slot=self._on_health_check)
        self.act_command_palette = self._make_action("Command Palette...", "Ctrl+K", self._on_command_palette)
        self.act_ai_assist = self._make_action("Lumen Assistant Suggestions", slot=self._on_ai_assist)
        self._assign_action_icons()

    def _assign_action_icons(self):
        """Assign compact generated icons to commonly used toolbar actions."""
        icon_map = {
            self.act_open_cellview: "open",
            self.act_save: "save",
            self.act_check_save: "check",
            self.act_undo: "undo",
            self.act_redo: "redo",
            self.act_move: "move",
            self.act_stretch: "stretch",
            self.act_wire: "wire",
            self.act_bus: "bus",
            self.act_instance: "instance",
            self.act_pin: "pin",
            self.act_label: "label",
            self.act_zoom_in: "zoom_in",
            self.act_zoom_out: "zoom_out",
            self.act_zoom_fit: "zoom_fit",
            self.act_netlist: "netlist",
            self.act_simulate: "run",
            self.act_waveform: "wave",
            self.act_open_layout: "open",
            self.act_health_check: "health",
            self.act_command_palette: "palette",
        }
        for action, icon_name in icon_map.items():
            action.setIcon(editor_icon(icon_name))

    # ── Menus ─────────────────────────────────────────────────

    def _create_menus(self):
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_new_cellview)
        file_menu.addAction(self.act_open_cellview)
        file_menu.addSeparator()
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_check_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_print)
        file_menu.addAction(self.act_export_image)
        file_menu.addSeparator()
        file_menu.addAction(self.act_import_spice)
        file_menu.addAction(self.act_import_verilog)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close)

        # Edit
        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_copy)
        edit_menu.addAction(self.act_paste)
        edit_menu.addAction(self.act_duplicate)
        edit_menu.addAction(self.act_delete)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_move)
        edit_menu.addAction(self.act_stretch)
        edit_menu.addAction(self.act_rotate)
        edit_menu.addAction(self.act_mirror_x)
        edit_menu.addAction(self.act_mirror_y)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_select_all)
        edit_menu.addAction(self.act_find)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_properties)

        # View
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        view_menu.addAction(self.act_zoom_fit)
        view_menu.addAction(self.act_redraw)
        view_menu.addAction(self.act_pan)
        view_menu.addSeparator()
        view_menu.addAction(self.act_display_options)
        view_menu.addAction(self.act_grid_options)
        view_menu.addAction(self.act_layer_palette)

        # Draw
        draw_menu = menubar.addMenu("&Draw")
        draw_menu.addAction(self.act_wire)
        draw_menu.addAction(self.act_bus)
        draw_menu.addAction(self.act_bus_tap)
        draw_menu.addAction(self.act_instance)
        draw_menu.addAction(self.act_pin)
        draw_menu.addAction(self.act_sheet_pin)
        draw_menu.addAction(self.act_label)
        draw_menu.addAction(self.act_wire_name)
        draw_menu.addSeparator()
        draw_menu.addAction(self.act_text)
        draw_menu.addAction(self.act_note)

        # Hierarchy
        hier_menu = menubar.addMenu("&Hierarchy")
        hier_menu.addAction(self.act_push_down)
        hier_menu.addAction(self.act_pop_up)
        hier_menu.addAction(self.act_descend_edit)
        hier_menu.addAction(self.act_return_read)
        hier_menu.addSeparator()
        hier_menu.addAction(self.act_symbol)

        layout_menu = menubar.addMenu("&Layout")
        layout_menu.addAction(self.act_open_layout)
        layout_menu.addAction(self.act_update_layout)
        layout_menu.addSeparator()
        layout_menu.addAction(self.act_run_drc)
        layout_menu.addAction(self.act_run_lvs)
        layout_menu.addSeparator()
        layout_menu.addAction(self.act_layout_runtime)

        # Simulation
        sim_menu = menubar.addMenu("&Simulation")
        sim_menu.addAction(self.act_check_save)
        sim_menu.addSeparator()
        sim_menu.addAction(self.act_netlist)
        sim_menu.addAction(self.act_simulate)
        sim_menu.addSeparator()
        act_ade = QAction("SimENV - Simulation Environment", self)
        act_ade.triggered.connect(self._on_open_ade)
        sim_menu.addAction(act_ade)
        sim_menu.addSeparator()
        sim_menu.addAction(self.act_waveform)

        verify_menu = menubar.addMenu("&Verify")
        verify_menu.addAction(self.act_health_check)
        verify_menu.addAction(self.act_quick_probe)

        lumen_menu = menubar.addMenu("&Lumen")
        lumen_menu.addAction(self.act_command_palette)
        lumen_menu.addAction(self.act_ai_assist)

    # ── Toolbars ──────────────────────────────────────────────

    def _create_toolbars(self):
        # File
        file_tb = QToolBar("File")
        file_tb.setIconSize(QSize(18, 18))
        file_tb.addAction(self.act_open_cellview)
        file_tb.addAction(self.act_save)
        file_tb.addAction(self.act_check_save)
        self.addToolBar(file_tb)

        # Edit
        edit_tb = QToolBar("Edit")
        edit_tb.setIconSize(QSize(18, 18))
        edit_tb.addAction(self.act_undo)
        edit_tb.addAction(self.act_redo)
        edit_tb.addAction(self.act_move)
        edit_tb.addAction(self.act_stretch)
        self.addToolBar(edit_tb)

        # Draw
        draw_tb = QToolBar("Draw")
        draw_tb.setIconSize(QSize(18, 18))
        draw_tb.addAction(self.act_wire)
        draw_tb.addAction(self.act_bus)
        draw_tb.addAction(self.act_instance)
        draw_tb.addAction(self.act_pin)
        draw_tb.addAction(self.act_label)
        self.addToolBar(draw_tb)

        # View
        view_tb = QToolBar("View")
        view_tb.setIconSize(QSize(18, 18))
        view_tb.addAction(self.act_zoom_in)
        view_tb.addAction(self.act_zoom_out)
        view_tb.addAction(self.act_zoom_fit)
        self.addToolBar(view_tb)

        # Simulation
        sim_tb = QToolBar("Simulation")
        sim_tb.setIconSize(QSize(18, 18))
        sim_tb.addAction(self.act_netlist)
        sim_tb.addAction(self.act_simulate)
        sim_tb.addAction(self.act_waveform)
        self.addToolBar(sim_tb)

        layout_tb = QToolBar("Layout")
        layout_tb.setIconSize(QSize(18, 18))
        layout_tb.addAction(self.act_open_layout)
        layout_tb.addAction(self.act_run_drc)
        layout_tb.addAction(self.act_run_lvs)
        self.addToolBar(layout_tb)

        smart_tb = QToolBar("Lumen")
        smart_tb.setIconSize(QSize(18, 18))
        smart_tb.addAction(self.act_health_check)
        smart_tb.addAction(self.act_command_palette)
        self.addToolBar(smart_tb)

    # ── Dock Panels ───────────────────────────────────────────

    def _create_dock_panels(self):
        # Property editor (right)
        self.prop_editor = PropertyEditorWidget(parent=self)
        prop_dock = QDockWidget("Properties", self)
        prop_dock.setWidget(self.prop_editor)
        prop_dock.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, prop_dock)

        # Netlist / output log (bottom)
        from PyQt6.QtGui import QFont
        self.netlist_view = QTextEdit()
        self.netlist_view.setReadOnly(True)
        self.netlist_view.setFont(QFont("Consolas", 9))
        self.netlist_view.setMaximumHeight(200)
        self.netlist_view.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #b0b0b0;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
            }
        """)
        netlist_dock = QDockWidget("Netlist / Output", self)
        netlist_dock.setWidget(self.netlist_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, netlist_dock)

    # ── Status Bar ────────────────────────────────────────────

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        self.mode_label = QLabel("Mode: Select")
        self.mode_label.setStyleSheet(
            "color: #ffffff; font-weight: bold; padding: 0 12px;")
        self.coord_label = QLabel("X: 0  Y: 0")
        self.coord_label.setStyleSheet("color: #ffffff; padding: 0 12px;")
        self.grid_label = QLabel("Grid: 10")
        self.grid_label.setStyleSheet("color: #ffffff; padding: 0 12px;")
        self.cell_label = QLabel(f"{self.library}/{self.cell}")
        self.cell_label.setStyleSheet("color: #ffffff; padding: 0 12px;")

        sb.addWidget(self.cell_label)
        sb.addPermanentWidget(self.mode_label)
        sb.addPermanentWidget(self.coord_label)
        sb.addPermanentWidget(self.grid_label)

    # ── Slots ─────────────────────────────────────────────────

    def _update_coords(self, x: float, y: float):
        self.coord_label.setText(f"X: {x:.1f}  Y: {y:.1f}")

    def _update_mode(self, mode: str):
        self.mode_label.setText(f"Mode: {mode.capitalize()}")

    def _not_implemented(self, action_name: str):
        """Show a clear placeholder for planned Virtuoso-parity commands."""
        self.statusBar().showMessage(f"{action_name}: UI command is planned", 4000)
        QMessageBox.information(
            self,
            "Command Planned",
            f"'{action_name}' is part of the Cadence-style GUI surface.\n\n"
            "The command is visible now so we can shape the workflow, but "
            "the underlying behavior still needs implementation.",
        )

    def _on_create_symbol(self):
        """Open the symbol editor for this cell."""
        if self.ciw:
            self.ciw.open_symbol_editor(self.library, self.cell, "symbol")
            return

        from lumen.gui.symbol_editor_window import SymbolEditorWindow
        win = SymbolEditorWindow(self.db, self.library, self.cell, "symbol")
        win.show()
        if not hasattr(self, "_symbol_windows"):
            self._symbol_windows = []
        self._symbol_windows.append(win)

    def _on_new_cellview(self):
        cell, ok = QInputDialog.getText(self, "New Cellview", "Cell name:")
        if not ok or not cell:
            return
        view, ok = QInputDialog.getItem(
            self, "New Cellview", "View:", ["schematic", "symbol", "veriloga", "config"], 0, False)
        if not ok:
            return
        if not self.db.cell_exists(self.library, cell):
            self.db.create_cell(self.library, cell)
        if view == "schematic":
            self.db.save_view(self.library, cell, view, {
                "type": "schematic", "name": cell, "library": self.library,
                "wires": [], "instances": [], "labels": [], "pins": []
            })
            win = SchematicEditorWindow(self.db, self.library, cell, view, self.ciw)
            win.show()
            self._child_window = win
        elif view == "symbol":
            from lumen.gui.symbol_editor_window import SymbolEditorWindow
            win = SymbolEditorWindow(self.db, self.library, cell, view, self.ciw)
            win.show()
            self._child_window = win
        else:
            self.db.save_view(self.library, cell, view, {
                "type": view, "name": cell, "library": self.library, "bindings": {}
            })
        self.statusBar().showMessage(f"Created {self.library}/{cell}/{view}", 3000)

    def _on_open_cellview(self):
        cell, ok = QInputDialog.getText(
            self, "Open Cellview", "Cell name:", text=self.cell)
        if not ok or not cell:
            return
        views = self.db.get_views(self.library, cell) or ["schematic"]
        view, ok = QInputDialog.getItem(self, "Open Cellview", "View:", views, 0, False)
        if not ok:
            return
        if view == "symbol":
            from lumen.gui.symbol_editor_window import SymbolEditorWindow
            win = SymbolEditorWindow(self.db, self.library, cell, view, self.ciw)
        else:
            win = SchematicEditorWindow(self.db, self.library, cell, view, self.ciw)
        win.show()
        self._child_window = win

    def _on_save_as(self):
        cell, ok = QInputDialog.getText(
            self, "Save As", "New cell name:", text=f"{self.cell}_copy")
        if not ok or not cell:
            return
        self.editor.save_as(self.library, cell, self.view)
        self.statusBar().showMessage(f"Saved as {self.library}/{cell}/{self.view}", 3000)

    def _on_export_image(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Schematic Image", f"{self.cell}.png", "PNG Image (*.png)")
        if not path:
            return
        self.editor.canvas.grab().save(path)
        self.statusBar().showMessage(f"Exported image: {path}", 4000)

    def _on_import_spice(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import SPICE", "", "SPICE Netlist (*.sp *.cir *.net *.spice);;All Files (*)")
        if not path:
            return
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        self.netlist_view.setPlainText(text)
        self.statusBar().showMessage("SPICE imported into Netlist / Output for review", 4000)

    def _on_import_verilog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Verilog-A", "", "Verilog-A (*.va *.vams);;All Files (*)")
        if not path:
            return
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        self.db.save_view(self.library, self.cell, "veriloga", {
            "type": "veriloga", "name": self.cell, "library": self.library,
            "source": text, "source_path": path,
        })
        self.statusBar().showMessage(f"Imported Verilog-A view from {path}", 4000)

    def _on_stretch(self):
        dx, ok = QInputDialog.getDouble(self, "Stretch", "Delta X:", 10.0)
        if not ok:
            return
        dy, ok = QInputDialog.getDouble(self, "Stretch", "Delta Y:", 0.0)
        if not ok:
            return
        self.editor.stretch_selected(dx, dy)
        self.statusBar().showMessage(f"Stretched selection by ({dx:g}, {dy:g})", 3000)

    def _on_display_options(self):
        visible = not self.editor.canvas.show_grid
        self.editor.set_grid_visible(visible)
        self.statusBar().showMessage(f"Grid {'shown' if visible else 'hidden'}", 3000)

    def _on_grid_options(self):
        import lumen.gui.schematic_editor as schematic_editor
        value, ok = QInputDialog.getInt(
            self, "Grid / Snap Options", "Grid size:", schematic_editor.GRID_SIZE, 1, 500, 1)
        if not ok:
            return
        self.editor.set_grid_size(value)
        self.grid_label.setText(f"Grid: {value}")

    def _on_layer_palette(self):
        summary = self.layout_service.runtime_summary()
        active = summary.get("active_executable", "") or "<not configured>"
        version = summary.get("active_version", "") or "unknown"
        QMessageBox.information(
            self,
            "Layer Palette",
            "Schematic layers available now:\n\n"
            "- wire: signal wire\n- bus: vector/bus wire\n- pin: top-level port\n"
            "- label: net label\n- annotation: note/text\n\n"
            f"KLayout runtime: {active}\n"
            f"KLayout version: {version}\n\n"
            "Use Layout menu for Open Layout / DRC / LVS actions.",
        )

    def _on_open_layout(self):
        self.open_layout_editor()

    def open_layout_editor(self) -> bool:
        ok, msg = self.layout_service.ensure_runtime(auto_install=False)
        if not ok:
            choice = QMessageBox.question(
                self,
                "KLayout Not Found",
                f"{msg}\n\nInstall KLayout automatically now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if choice == QMessageBox.StandardButton.Yes:
                install = self._run_klayout_install()
                if install.logs and self.ciw:
                    for line in install.logs[-5:]:
                        self.ciw.log(f"[KLayout install] {line}")
                if not install.success:
                    QMessageBox.warning(self, "KLayout Install Failed", install.message)
                    return False
            else:
                return False

        result = self.layout_service.open_layout_editor(self.library, self.cell)
        self.statusBar().showMessage(result.message, 5000)
        if self.ciw:
            self.ciw.log(f"[Layout] {result.message}")
        if not result.success:
            QMessageBox.warning(self, "Open Layout Failed", result.message)
        return result.success

    def _on_update_layout(self):
        result = self.layout_service.update_layout_from_schematic(self.library, self.cell)
        self.statusBar().showMessage(result.message, 5000)
        if self.ciw:
            self.ciw.log(f"[Layout] {result.message}")
        QMessageBox.information(self, "Update Layout", result.message)

    def _on_layout_runtime(self):
        summary = self.layout_service.runtime_summary()
        active = summary.get("active_executable", "") or ""
        version = summary.get("active_version", "") or "unknown"
        discovered = summary.get("discovered", [])
        if not discovered and not active:
            install_choice = QMessageBox.question(
                self,
                "KLayout Runtime",
                "No KLayout installation was detected.\n\nInstall automatically now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if install_choice == QMessageBox.StandardButton.Yes:
                install = self._run_klayout_install()
                if install.logs and self.ciw:
                    for line in install.logs[-8:]:
                        self.ciw.log(f"[KLayout install] {line}")
                if install.success:
                    self.statusBar().showMessage("KLayout installed and configured", 5000)
                else:
                    QMessageBox.warning(self, "KLayout Install Failed", install.message)
                summary = self.layout_service.runtime_summary()
                active = summary.get("active_executable", "") or ""
                version = summary.get("active_version", "") or "unknown"
                discovered = summary.get("discovered", [])
        lines = [f"Active runtime: {active or '<not configured>'}", f"Version: {version}", ""]
        lines.append("Discovered runtimes:")
        if discovered:
            for idx, item in enumerate(discovered, start=1):
                item_version = item.get("version", "") or "unknown"
                lines.append(f"{idx}. {item.get('executable', '')} ({item_version})")
        else:
            lines.append("  none found automatically")
        lines.append("")
        lines.append("Enter executable path to override (blank to keep current).")

        path, ok = QInputDialog.getText(
            self,
            "KLayout Runtime",
            "\n".join(lines),
            text=active,
        )
        if not ok:
            return
        path = path.strip()
        if not path:
            return
        if self.layout_service.set_runtime_executable(path):
            refreshed = self.layout_service.runtime_summary()
            runtime = refreshed.get("active_executable", path)
            runtime_version = refreshed.get("active_version", "unknown")
            msg = f"KLayout runtime set to {runtime} ({runtime_version})"
            self.statusBar().showMessage(msg, 5000)
            if self.ciw:
                self.ciw.log(f"[Layout] {msg}")
        else:
            QMessageBox.warning(
                self,
                "KLayout Runtime",
                "The provided executable path is invalid or not runnable.",
            )

    class _KLayoutInstallThread(QThread):
        def __init__(self, layout_service, parent=None):
            super().__init__(parent)
            self.layout_service = layout_service
            self.result = None

        def run(self):
            self.result = self.layout_service.install_runtime_if_missing()

    def _run_klayout_install(self):
        worker = self._KLayoutInstallThread(self.layout_service, self)
        progress = QProgressDialog("Installing KLayout. This may take a few minutes...", "", 0, 0, self)
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setWindowTitle("Installing KLayout")
        progress.show()

        worker.start()
        while worker.isRunning():
            QApplication.processEvents()
            worker.wait(100)

        progress.close()
        return worker.result

    def _on_run_drc(self):
        script_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select KLayout DRC Script",
            "",
            "KLayout DRC (*.lydrc *.drc *.rb *.py);;All Files (*)",
        )
        if not script_path:
            return
        result = self.layout_service.run_drc(self.library, self.cell, script_path)
        self.statusBar().showMessage(result.message, 7000)
        if self.ciw:
            self.ciw.log(f"[Layout] {result.message}")
        if result.success:
            QMessageBox.information(self, "DRC", result.message)
        else:
            QMessageBox.warning(self, "DRC Failed", result.message)

    def _on_run_lvs(self):
        script_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select KLayout LVS Script",
            "",
            "KLayout LVS (*.lylvs *.lvs *.rb *.py);;All Files (*)",
        )
        if not script_path:
            return
        netlist_path, _ = QFileDialog.getOpenFileName(
            self,
            "Optional: Select Schematic Netlist",
            "",
            "SPICE Netlist (*.sp *.cir *.net *.spice);;All Files (*)",
        )
        result = self.layout_service.run_lvs(
            self.library,
            self.cell,
            script_path,
            schematic_netlist=netlist_path or "",
        )
        self.statusBar().showMessage(result.message, 7000)
        if self.ciw:
            self.ciw.log(f"[Layout] {result.message}")
        if result.success:
            QMessageBox.information(self, "LVS", result.message)
        else:
            QMessageBox.warning(self, "LVS Failed", result.message)

    def _on_wire_name(self):
        name, ok = QInputDialog.getText(self, "Wire Name", "Net/bus name:")
        if not ok or not name:
            return
        self.editor.name_selected_wires(name, "[" in name and "]" in name)
        self.statusBar().showMessage(f"Named selected wire(s): {name}", 3000)

    def _on_bus_tap(self):
        name, ok = QInputDialog.getText(self, "Bus Tap", "Tap name, e.g. data<0> or data[0]:")
        if not ok or not name:
            return
        if not self.editor.add_bus_tap(name):
            QMessageBox.information(self, "Bus Tap", "Select a bus/wire first, then add a tap.")

    def _on_note(self):
        text, ok = QInputDialog.getMultiLineText(self, "Note / Text", "Text:")
        if not ok or not text:
            return
        self.editor.add_note(text)

    def _on_quick_probe(self):
        summary = self.editor.selected_summary()
        if not summary:
            summary = "Select an instance, wire, pin, or label first."
        QMessageBox.information(self, "Quick Probe", summary)

    def _on_descend(self):
        inst = self.editor.selected_instance()
        if not inst:
            QMessageBox.information(self, "Descend", "Select an instance to descend into.")
            return
        if not self.db.view_exists(inst.library_name, inst.cell_name, "schematic"):
            QMessageBox.information(
                self,
                "Descend",
                f"{inst.library_name}/{inst.cell_name} has no schematic view.",
            )
            return
        self._hierarchy_stack.append((self.library, self.cell, self.view))
        win = SchematicEditorWindow(
            self.db, inst.library_name, inst.cell_name, "schematic", self.ciw)
        win._hierarchy_stack = list(self._hierarchy_stack)
        win.show()
        self._child_window = win

    def _on_return(self):
        if not self._hierarchy_stack:
            QMessageBox.information(self, "Return", "Already at the top of this edit stack.")
            return
        library, cell, view = self._hierarchy_stack.pop()
        win = SchematicEditorWindow(self.db, library, cell, view, self.ciw)
        win._hierarchy_stack = list(self._hierarchy_stack)
        win.show()
        self._child_window = win

    def _on_command_palette(self):
        commands = [
            "Wire (W)", "Bus (B)", "Instance (I)", "Pin (P)", "Label (L)",
            "Find / Select (Ctrl+F)", "Object Properties (Q)",
            "Generate Netlist (Ctrl+Shift+N)", "Run Simulation (F5)",
            "Zoom Fit (F)", "Right-drag zoom window",
        ]
        QMessageBox.information(self, "Command Palette", "\n".join(commands))

    def _on_ai_assist(self):
        data = self.editor.to_data()
        issues = []
        if not data.get("pins"):
            issues.append("Add top-level pins before generating a reusable symbol.")
        if data.get("instances") and not data.get("wires"):
            issues.append("Instances are present but no wiring exists yet.")
        if not issues:
            issues.append("Design structure looks ready for check/save and netlisting.")
        QMessageBox.information(self, "Lumen Assistant Suggestions", "\n".join(f"- {i}" for i in issues))

    def _on_health_check(self):
        """Lightweight schematic health check that is useful today."""
        data = self.db.load_view(self.library, self.cell, self.view) or {}
        wires = len(data.get("wires", []))
        instances = len(data.get("instances", []))
        labels = len(data.get("labels", []))
        pins = len(data.get("pins", []))

        issues = []
        if instances and not wires:
            issues.append("Instances exist but no wires are present.")
        if instances and not labels and not pins:
            issues.append("No net labels are present; generated nets will be auto-named.")
        if not instances:
            issues.append("No instances are present.")

        summary = (
            f"Instances: {instances}\nWires: {wires}\nLabels: {labels}\nPins: {pins}"
        )
        if issues:
            summary += "\n\nSuggestions:\n- " + "\n- ".join(issues)
        else:
            summary += "\n\nNo obvious schematic hygiene issues found."
        QMessageBox.information(self, "Design Health Check", summary)

    def _on_find_select(self):
        """Find objects by visible design name and select the matches."""
        query, ok = QInputDialog.getText(
            self,
            "Find / Select",
            "Instance, cell, library, net, label, or pin name:",
        )
        if not ok or not query:
            return
        query_l = query.lower()
        self.editor.scene.clearSelection()
        matches = 0

        for inst in self.editor.instances:
            haystack = " ".join([
                inst.instance_name,
                inst.cell_name,
                inst.library_name,
            ]).lower()
            if query_l in haystack:
                inst.setSelected(True)
                matches += 1

        for label in self.editor.labels:
            if query_l in label.toPlainText().lower():
                label.setSelected(True)
                matches += 1

        for pin in getattr(self.editor, "pins", []):
            if query_l in pin.toPlainText().lower():
                pin.setSelected(True)
                matches += 1

        for wire in self.editor.wires:
            if query_l in (wire.net_name or "").lower():
                wire.setSelected(True)
                matches += 1

        self.statusBar().showMessage(f"Find selected {matches} object(s)", 3000)
        if matches:
            self.editor.zoom_fit()

    def _on_object_properties(self):
        """Show properties for the currently selected object."""
        shown = self.editor.show_selected_properties()
        if shown:
            self.prop_editor.setFocus()
            self.statusBar().showMessage("Object properties updated", 2000)
        else:
            self.prop_editor.clear_properties()
            self.statusBar().showMessage("No object selected", 3000)

    def _on_save(self):
        self.editor.save()
        if self.ciw:
            self.ciw.log(f"Saved: {self.library}/{self.cell}/{self.view}")
        self.statusBar().showMessage("Saved", 3000)

    def _on_generate_netlist(self):
        """Generate and display the SPICE netlist."""
        try:
            self.editor.save()  # Save first
            from lumen.core.netlist import NetlistGenerator
            gen = NetlistGenerator(self.db)
            gen.set_target_simulator("GSPICE")
            netlist = gen.generate(self.library, self.cell, self.view)
            self.netlist_view.setPlainText(netlist)
            errors = gen.get_errors()
            if errors:
                for e in errors:
                    self.netlist_view.append(f"\n* WARNING: {e}")
            if self.ciw:
                self.ciw.log(f"Netlist generated for {self.library}/{self.cell}")
                if errors:
                    for e in errors:
                        self.ciw.log(f"  Warning: {e}")
            self.statusBar().showMessage(
                f"Netlist: {len(netlist.splitlines())} lines", 5000)
        except Exception as exc:
            import traceback
            details = traceback.format_exc()
            self.netlist_view.setPlainText(
                f"* ERROR: Netlist generation crashed\n"
                f"* {exc}\n\n{details}"
            )
            if self.ciw:
                self.ciw.log(f"Netlist generation crashed: {exc}")
            self.statusBar().showMessage("Netlist generation failed", 5000)

    def _on_simulate(self):
        """Generate netlist and run GSPICE simulation."""
        try:
            self.editor.save()
            from lumen.core.netlist import NetlistGenerator
            from lumen.core.simulator import SimulatorBridge

            gen = NetlistGenerator(self.db)
            gen.set_target_simulator("GSPICE")
            netlist = gen.generate(self.library, self.cell, self.view)
            self.netlist_view.setPlainText(netlist)
        except Exception as exc:
            import traceback
            details = traceback.format_exc()
            self.netlist_view.setPlainText(
                f"* ERROR: Netlist generation crashed before simulation\n"
                f"* {exc}\n\n{details}"
            )
            if self.ciw:
                self.ciw.log(f"Simulation aborted: netlist crash: {exc}")
            self.statusBar().showMessage("Simulation aborted (netlist failure)", 5000)
            return

        bridge = SimulatorBridge()
        if not bridge.is_available():
            self.netlist_view.append(
                "\n* GSPICE not found. Netlist generated but simulation skipped.")
            self.netlist_view.append(
                f"* Searched: {bridge.exe_path}")
            self.netlist_view.append(
                "* Build GSPICE or set the path in Tools > Options.")
            if self.ciw:
                self.ciw.log("GSPICE not found — simulation skipped")
            return

        self.statusBar().showMessage("Simulating...")
        if self.ciw:
            self.ciw.log(f"Running GSPICE simulation: {self.cell}")

        result = bridge.simulate(netlist, sim_name=self.cell)

        if result.success:
            self.netlist_view.append(f"\n* Simulation completed successfully")
            self.netlist_view.append(f"* Output: {result.output_path}")
            if self.ciw:
                self.ciw.log("Simulation completed successfully")
            # Open waveform viewer with results
            if result.waveforms:
                self._show_waveforms(result.waveforms)
        else:
            self.netlist_view.append(f"\n* SIMULATION FAILED (exit code {result.return_code})")
            for e in result.errors:
                self.netlist_view.append(f"* ERROR: {e}")
            if self.ciw:
                self.ciw.log("Simulation FAILED")
                for e in result.errors:
                    self.ciw.log(f"  {e}")
        if result.warnings:
            self.netlist_view.append("* WARNINGS:")
            for warning in result.warnings:
                self.netlist_view.append(f"* WARNING: {warning}")
        if result.command:
            self.netlist_view.append(f"* COMMAND: {' '.join(result.command)}")

        self.statusBar().showMessage(
            "Simulation done" if result.success else "Simulation failed", 5000)

    def _show_waveforms(self, waveforms: dict):
        """Open the waveform viewer with results."""
        from lumen.gui.waveform_viewer import WaveformViewerWindow
        viewer = WaveformViewerWindow(parent=None)
        viewer.load_results(waveforms)
        viewer.show()
        # Keep reference so window isn't garbage collected
        if not hasattr(self, '_waveform_viewers'):
            self._waveform_viewers = []
        self._waveform_viewers.append(viewer)

    def _on_open_waveform(self):
        """Open an empty waveform viewer."""
        from lumen.gui.waveform_viewer import WaveformViewerWindow
        viewer = WaveformViewerWindow(parent=None)
        viewer.show()
        if not hasattr(self, '_waveform_viewers'):
            self._waveform_viewers = []
        self._waveform_viewers.append(viewer)

    def _on_open_ade(self):
        """Open SimENV for this cell."""
        self.open_simenv_tab()

    def open_simenv_tab(self):
        """Open or focus SimENV as an editor tab for this schematic."""
        try:
            if self._simenv_tab is not None:
                index = self.workspace_tabs.indexOf(self._simenv_tab)
                if index >= 0:
                    self.workspace_tabs.setCurrentIndex(index)
                    self.raise_()
                    self.activateWindow()
                    return self._simenv_tab

            from lumen.gui.ade_window import ADEWindow
            pdk_registry = getattr(self.ciw, "pdk_registry", None) if self.ciw else None
            simenv = ADEWindow(
                self.db,
                self.library,
                self.cell,
                ciw=self.ciw,
                pdk_registry=pdk_registry,
                parent=self,
            )
            simenv.setWindowFlags(Qt.WindowType.Widget)
            simenv.setProperty("embeddedSimEnv", True)
            self._simenv_tab = simenv
            index = self.workspace_tabs.addTab(simenv, f"SimENV: {self.cell}")
            self.workspace_tabs.setCurrentIndex(index)
            self.statusBar().showMessage("Opened SimENV tab", 3000)
            if self.ciw:
                self.ciw.log(f"Opened SimENV tab: {self.library}/{self.cell}")
            return simenv
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Open SimENV Failed",
                f"Could not open SimENV for {self.library}/{self.cell}.\n\n{exc}",
            )
            return None

    def _on_workspace_tab_close(self, index: int):
        widget = self.workspace_tabs.widget(index)
        if widget is self.editor:
            self.close()
            return
        if widget is self._simenv_tab:
            self._simenv_tab = None
        self.workspace_tabs.removeTab(index)
        widget.deleteLater()


