"""
Lumen Circuit Studio — Schematic Editor Window

Standalone schematic editor window with its own menu bar,
toolbars, property panel, and canvas. Opens one per design.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QDockWidget, QToolBar,
    QStatusBar, QLabel, QMessageBox, QTextEdit
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QKeySequence

from lumen.core.database import LibraryDatabase
from lumen.gui.schematic_editor import SchematicEditor
from lumen.gui.property_editor import PropertyEditorWidget


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

        self.setWindowTitle(f"Lumen — {cell} ({view}) — [{library}]")
        self.setMinimumSize(1000, 700)
        self.resize(1300, 850)

        # Create the schematic editor canvas
        self.editor = SchematicEditor(db, library, cell, view, parent=self)
        self.editor.coord_changed.connect(self._update_coords)
        self.editor.mode_changed.connect(self._update_mode)
        self.setCentralWidget(self.editor)

        # Build UI
        self._create_actions()
        self._create_menus()
        self._create_toolbars()
        self._create_dock_panels()
        self._create_status_bar()

    # ── Actions ───────────────────────────────────────────────

    def _create_actions(self):
        # File
        self.act_save = QAction("Save", self)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save.triggered.connect(self._on_save)

        self.act_save_as = QAction("Save As...", self)
        self.act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))

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

        self.act_zoom_out = QAction("Zoom Out", self)
        self.act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))

        self.act_zoom_fit = QAction("Zoom Fit", self)
        self.act_zoom_fit.setShortcut(QKeySequence("F"))

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

        self.act_pop_up = QAction("Return (Ctrl+E)", self)
        self.act_pop_up.setShortcut(QKeySequence("Ctrl+E"))

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

    # ── Menus ─────────────────────────────────────────────────

    def _create_menus(self):
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close)

        # Edit
        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_copy)
        edit_menu.addAction(self.act_paste)
        edit_menu.addAction(self.act_delete)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_rotate)
        edit_menu.addAction(self.act_mirror_x)
        edit_menu.addAction(self.act_mirror_y)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_select_all)

        # View
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        view_menu.addAction(self.act_zoom_fit)

        # Draw
        draw_menu = menubar.addMenu("&Draw")
        draw_menu.addAction(self.act_wire)
        draw_menu.addAction(self.act_instance)
        draw_menu.addAction(self.act_pin)
        draw_menu.addAction(self.act_label)

        # Hierarchy
        hier_menu = menubar.addMenu("&Hierarchy")
        hier_menu.addAction(self.act_push_down)
        hier_menu.addAction(self.act_pop_up)

        # Simulation
        sim_menu = menubar.addMenu("&Simulation")
        sim_menu.addAction(self.act_check_save)
        sim_menu.addSeparator()
        sim_menu.addAction(self.act_netlist)
        sim_menu.addAction(self.act_simulate)
        sim_menu.addSeparator()
        act_ade = QAction("ADE — Analog Design Environment", self)
        act_ade.triggered.connect(self._on_open_ade)
        sim_menu.addAction(act_ade)
        sim_menu.addSeparator()
        sim_menu.addAction(self.act_waveform)

    # ── Toolbars ──────────────────────────────────────────────

    def _create_toolbars(self):
        # File
        file_tb = QToolBar("File")
        file_tb.setIconSize(QSize(18, 18))
        file_tb.addAction(self.act_save)
        self.addToolBar(file_tb)

        # Edit
        edit_tb = QToolBar("Edit")
        edit_tb.setIconSize(QSize(18, 18))
        edit_tb.addAction(self.act_undo)
        edit_tb.addAction(self.act_redo)
        self.addToolBar(edit_tb)

        # Draw
        draw_tb = QToolBar("Draw")
        draw_tb.setIconSize(QSize(18, 18))
        draw_tb.addAction(self.act_wire)
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
        self.addToolBar(sim_tb)

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

    def _on_save(self):
        self.editor.save()
        if self.ciw:
            self.ciw.log(f"Saved: {self.library}/{self.cell}/{self.view}")
        self.statusBar().showMessage("Saved", 3000)

    def _on_generate_netlist(self):
        """Generate and display the SPICE netlist."""
        self.editor.save()  # Save first
        from lumen.core.netlist import NetlistGenerator
        gen = NetlistGenerator(self.db)
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

    def _on_simulate(self):
        """Generate netlist and run GSPICE simulation."""
        self.editor.save()
        from lumen.core.netlist import NetlistGenerator
        from lumen.core.simulator import SimulatorBridge

        gen = NetlistGenerator(self.db)
        netlist = gen.generate(self.library, self.cell, self.view)
        self.netlist_view.setPlainText(netlist)

        bridge = SimulatorBridge()
        if not bridge.is_available():
            self.netlist_view.append(
                "\n* GSPICE not found. Netlist generated but simulation skipped.")
            self.netlist_view.append(
                f"* Searched: {bridge.gspice_exe}")
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
            self.netlist_view.append(f"\n* SIMULATION FAILED")
            for e in result.errors:
                self.netlist_view.append(f"* ERROR: {e}")
            if self.ciw:
                self.ciw.log("Simulation FAILED")
                for e in result.errors:
                    self.ciw.log(f"  {e}")

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
        """Open ADE for this cell."""
        if self.ciw:
            self.ciw.open_ade(self.library, self.cell)
        else:
            try:
                from lumen.gui.ade_window import ADEWindow
                ade = ADEWindow(self.db, self.library, self.cell)
                ade.show()
                if not hasattr(self, '_ade_windows'):
                    self._ade_windows = []
                self._ade_windows.append(ade)
            except Exception as exc:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(
                    self,
                    "Open ADE Failed",
                    f"Could not open ADE for {self.library}/{self.cell}.\n\n{exc}",
                )
