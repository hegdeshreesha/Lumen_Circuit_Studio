"""
Lumen Circuit Studio — CIW (Command Interpreter Window)

The main hub window, analogous to Cadence Virtuoso's CIW.
- Compact window with menu bar for launching other tools
- Command line input for scripting
- Output log for messages
- Manages lifecycle of Library Manager, Schematic Editors, etc.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QLabel, QStatusBar, QMessageBox
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QKeySequence, QFont, QTextCursor

import os
from lumen.core.database import LibraryDatabase


class CIWWindow(QMainWindow):
    """Command Interpreter Window — the main application hub."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumen Circuit Studio — CIW")
        self.setMinimumSize(700, 400)
        self.resize(800, 450)

        # Initialize database
        workspace = os.path.join(os.path.expanduser("~"), "LumenWorkspace")
        self.db = LibraryDatabase(workspace)

        # Track child windows
        self._lib_manager = None
        self._editor_windows: list = []
        self._ade_windows: list = []
        self._pdk_manager = None

        # Initialize PDK registry
        from lumen.core.pdk import PDKRegistry
        self.pdk_registry = PDKRegistry(workspace)

        # Build UI
        self._build_central_widget()
        self._create_actions()
        self._create_menus()
        self._create_status_bar()

        self.log("Lumen Circuit Studio v0.1.0")
        self.log(f"Workspace: {workspace}")
        active_pdk = self.pdk_registry.get_active_pdk()
        if active_pdk:
            self.log(f"Active PDK: {active_pdk.display_name} ({active_pdk.node})")
        else:
            self.log("No active PDK — use Tools > PDK Manager to set one.")
        self.log("Type 'help' for available commands.\n")

    # ── Central Widget ────────────────────────────────────────

    def _build_central_widget(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Banner
        banner = QLabel("✦ Lumen Circuit Studio")
        banner.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #6b9ece;
            background: transparent;
            padding: 4px 0;
        """)
        layout.addWidget(banner)

        # Output log
        self.output_log = QTextEdit()
        self.output_log.setReadOnly(True)
        self.output_log.setFont(QFont("Consolas", 9))
        self.output_log.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #b0b0b0;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        layout.addWidget(self.output_log, stretch=1)

        # Command input line
        cmd_layout = QHBoxLayout()
        cmd_label = QLabel(">")
        cmd_label.setStyleSheet("""
            color: #6b9ece;
            font-family: Consolas;
            font-size: 12px;
            font-weight: bold;
            background: transparent;
            padding: 0 4px;
        """)
        cmd_layout.addWidget(cmd_label)

        self.cmd_input = QLineEdit()
        self.cmd_input.setFont(QFont("Consolas", 10))
        self.cmd_input.setPlaceholderText("Enter command...")
        self.cmd_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 6px 8px;
            }
            QLineEdit:focus {
                border: 1px solid #6b9ece;
            }
        """)
        self.cmd_input.returnPressed.connect(self._on_command)
        cmd_layout.addWidget(self.cmd_input)
        layout.addLayout(cmd_layout)

    # ── Actions ───────────────────────────────────────────────

    def _create_actions(self):
        # Tools
        self.act_lib_manager = QAction("Library Manager", self)
        self.act_lib_manager.setShortcut(QKeySequence("Ctrl+L"))
        self.act_lib_manager.triggered.connect(self.open_library_manager)

        self.act_new_lib = QAction("New Library...", self)
        self.act_new_lib.triggered.connect(self._on_new_library)

        self.act_exit = QAction("Exit", self)
        self.act_exit.setShortcut(QKeySequence("Alt+F4"))
        self.act_exit.triggered.connect(self.close)

        # Help
        self.act_about = QAction("About Lumen Circuit Studio", self)
        self.act_about.triggered.connect(self._on_about)

    # ── Menus ─────────────────────────────────────────────────

    def _create_menus(self):
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_new_lib)
        file_menu.addSeparator()
        file_menu.addAction(self.act_exit)

        # Tools
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(self.act_lib_manager)
        tools_menu.addSeparator()
        act_ade = QAction("ADE — Analog Design Environment", self)
        act_ade.triggered.connect(self._on_open_ade_prompt)
        tools_menu.addAction(act_ade)
        tools_menu.addSeparator()
        tools_menu.addSeparator()
        act_pdk = QAction("PDK Manager...", self)
        act_pdk.setShortcut(QKeySequence("Ctrl+P"))
        act_pdk.triggered.connect(self.open_pdk_manager)
        tools_menu.addAction(act_pdk)
        tools_menu.addAction(QAction("Options...", self))

        # Help
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(QAction("Documentation", self))
        help_menu.addAction(self.act_about)

    # ── Status Bar ────────────────────────────────────────────

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage("Ready")

    # ── Open Library Manager ──────────────────────────────────

    def open_library_manager(self):
        """Open the Library Manager window (singleton)."""
        if self._lib_manager is None or not self._lib_manager.isVisible():
            from lumen.gui.library_manager_window import LibraryManagerWindow
            self._lib_manager = LibraryManagerWindow(self.db, ciw=self)
            self._lib_manager.show()
        else:
            self._lib_manager.raise_()
            self._lib_manager.activateWindow()
        self.log("Opened Library Manager")

    # ── Open Schematic Editor ─────────────────────────────────

    def open_schematic_editor(self, library: str, cell: str, view: str = "schematic"):
        """Open a schematic editor window for the given cell."""
        # Check if already open
        for win in self._editor_windows:
            if (win.isVisible() and win.library == library
                    and win.cell == cell and win.view == view):
                win.raise_()
                win.activateWindow()
                return

        from lumen.gui.schematic_editor_window import SchematicEditorWindow
        editor = SchematicEditorWindow(self.db, library, cell, view, ciw=self)
        editor.show()
        self._editor_windows.append(editor)
        self.log(f"Opened editor: {library}/{cell}/{view}")

    # ── Command Handler ───────────────────────────────────────

    def _on_command(self):
        """Process a command from the command line."""
        cmd = self.cmd_input.text().strip()
        self.cmd_input.clear()
        if not cmd:
            return

        self.log(f"> {cmd}")

        parts = cmd.split()
        verb = parts[0].lower()

        if verb == "help":
            self.log("Available commands:")
            self.log("  lib_manager    — Open Library Manager")
            self.log("  new_lib <name> — Create a new library")
            self.log("  list_libs      — List all libraries")
            self.log("  open <lib> <cell> [view] — Open an editor")
            self.log("  help           — Show this help")
            self.log("  exit           — Exit application")
        elif verb == "lib_manager":
            self.open_library_manager()
        elif verb == "new_lib" and len(parts) >= 2:
            try:
                self.db.create_library(parts[1])
                self.log(f"Created library: {parts[1]}")
            except ValueError as e:
                self.log(f"Error: {e}")
        elif verb == "list_libs":
            libs = self.db.get_libraries()
            for lib in libs:
                cells = self.db.get_cells(lib.name)
                self.log(f"  {lib.name} ({len(cells)} cells)")
        elif verb == "open" and len(parts) >= 3:
            lib, cell = parts[1], parts[2]
            view = parts[3] if len(parts) > 3 else "schematic"
            self.open_schematic_editor(lib, cell, view)
        elif verb == 'exit':
            self.close()
        elif verb == 'ade' and len(parts) >= 3:
            self.open_ade(parts[1], parts[2])
        else:
            self.log(f"Unknown command: {cmd}")

    # ── Helpers ───────────────────────────────────────────────

    def _on_new_library(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Library", "Library name:")
        if ok and name:
            try:
                self.db.create_library(name)
                self.log(f"Created library: {name}")
                if self._lib_manager and self._lib_manager.isVisible():
                    self._lib_manager.refresh()
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))

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

    def log(self, msg: str):
        """Write a message to the CIW output log."""
        self.output_log.append(msg)
        # Auto-scroll to bottom
        cursor = self.output_log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.output_log.setTextCursor(cursor)

    def closeEvent(self, event):
        """Close all child windows when CIW closes."""
        if self._lib_manager:
            self._lib_manager.close()
        for win in self._editor_windows:
            win.close()
        for win in self._ade_windows:
            win.close()
        if self._pdk_manager:
            self._pdk_manager.close()
        event.accept()

    def open_pdk_manager(self):
        """Open the PDK Manager window (singleton)."""
        if self._pdk_manager is None or not self._pdk_manager.isVisible():
            from lumen.gui.pdk_manager_window import PDKManagerWindow
            self._pdk_manager = PDKManagerWindow(self.pdk_registry, ciw=self)
            self._pdk_manager.show()
        else:
            self._pdk_manager.raise_()
            self._pdk_manager.activateWindow()
        self.log("Opened PDK Manager")

    def open_ade(self, library: str, cell: str):
        """Open ADE window for a cell."""
        from lumen.gui.ade_window import ADEWindow
        ade = ADEWindow(self.db, library, cell, ciw=self)
        ade.show()
        self._ade_windows.append(ade)
        self.log(f"Opened ADE: {library}/{cell}")

    def _on_open_ade_prompt(self):
        from PyQt6.QtWidgets import QInputDialog
        libs = [l.name for l in self.db.get_libraries()]
        if not libs:
            QMessageBox.warning(self, "Error", "No libraries found.")
            return
        lib, ok = QInputDialog.getItem(self, "ADE", "Library:", libs)
        if not ok:
            return
        cells = self.db.get_cells(lib)
        if not cells:
            QMessageBox.warning(self, "Error", f"No cells in {lib}.")
            return
        cell, ok = QInputDialog.getItem(self, "ADE", "Cell:", cells)
        if ok:
            self.open_ade(lib, cell)
