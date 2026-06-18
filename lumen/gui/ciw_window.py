"""
Lumen Circuit Studio — APW (Analog Pilot Window)

The main hub window, analogous to Cadence Virtuoso's APW.
- Compact window with menu bar for launching other tools
- Command line input for scripting
- Output log for messages
- Manages lifecycle of Library Manager, Schematic Editors, etc.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QLabel, QStatusBar, QMessageBox, QApplication,
    QProgressDialog, QInputDialog, QFileDialog
)
from PyQt6.QtCore import Qt, QSize, QThread, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence, QFont, QTextCursor

import os
from pathlib import Path
from lumen.core.database import LibraryDatabase
from lumen.core.layout_xl import LayoutXLService
from lumen.core.pdk_service import get_registry, resolve_workspace, clear_registry_cache
from lumen.core.project_system import ProjectSystem
from lumen.core.simulator_runtime import SimulatorRuntimeManager
from lumen.gui.branding import apply_window_branding, logo_label, logo_url
from lumen.gui.simulator_manager_window import SimulatorManagerWindow
from lumen.gui.theme import THEME_DARK, THEME_LIGHT, apply_theme, current_theme


class APWWindow(QMainWindow):
    """Analog Pilot Window — the main application hub."""

    def __init__(self, startup_status=None):
        super().__init__()
        self._startup_status_cb = startup_status
        self._startup_status("Initializing APW...")
        self.setWindowTitle("Lumen Circuit Studio — APW")
        apply_window_branding(self)
        self.setMinimumSize(700, 400)
        self.resize(800, 450)

        self._startup_status("Loading project context...")
        self.project_system = ProjectSystem()
        self.project_info = self.project_system.get_current_project()
        requested_workspace = resolve_workspace(self.project_system.get_current_workspace())
        self.workspace = self._pick_writable_workspace(requested_workspace)
        os.environ["LUMEN_WORKSPACE"] = self.workspace

        # Initialize database
        self._startup_status("Initializing workspace database...")
        self.db = LibraryDatabase(self.workspace)
        self.layout_service = LayoutXLService(self.db)
        self.sim_runtime = SimulatorRuntimeManager(self.workspace)
        self.sim_runtime.apply_environment_overrides()

        # Track child windows
        self._lib_manager = None
        self._editor_windows: list = []
        self._simenv_windows: list = []
        self._sigview_windows: list = []
        self._pdk_manager = None
        self._sim_manager = None
        self._recent_projects_menu = None

        # Initialize PDK registry
        self._startup_status("Loading PDK registry...")
        self.pdk_registry = get_registry(self.workspace)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(60_000)
        self._autosave_timer.timeout.connect(self._autosave_session)
        self._autosave_timer.start()

        # Build UI
        self._startup_status("Building APW interface...")
        self._build_central_widget()
        self._startup_status("Configuring APW theme...")
        self._apply_local_theme_styles()
        self._startup_status("Creating APW actions...")
        self._create_actions()
        self._startup_status("Creating APW menus...")
        self._create_menus()
        self._startup_status("Creating APW status bar...")
        self._create_status_bar()

        self.log("Lumen Circuit Studio v0.5")
        self.log(
            f"Project: {self.project_info.name}"
            if self.project_info else "Project: <default workspace>"
        )
        self.log(f"Workspace: {self.workspace}")
        active_pdk = self.pdk_registry.get_active_pdk()
        if active_pdk:
            self.log(f"Active PDK: {active_pdk.display_name} ({active_pdk.node})")
        else:
            self.log("No active PDK — use Tools > PDK Manager to set one.")
        self.log("Type 'help' for available commands.\n")
        # Run recovery prompt after initial startup settles to avoid splash deadlocks.
        QTimer.singleShot(600, self._maybe_offer_recovery)
        self._startup_status("APW ready")

    def _pick_writable_workspace(self, requested_workspace: str) -> str:
        """Return a writable workspace path, falling back if needed."""
        candidates = [
            Path(requested_workspace).expanduser(),
            Path.cwd() / "LumenWorkspace",
            Path.home() / ".lumen" / "workspace",
        ]
        for candidate in candidates:
            try:
                candidate = candidate.resolve()
            except Exception:
                continue
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                probe = candidate / ".lumen_write_probe"
                with open(probe, "w", encoding="utf-8") as f:
                    f.write("ok")
                probe.unlink(missing_ok=True)
                if str(candidate) != str(Path(requested_workspace).expanduser().resolve()):
                    self._startup_status(f"Workspace fallback: {candidate}")
                return str(candidate)
            except Exception:
                continue
        raise RuntimeError(
            "No writable workspace found. Please configure a writable workspace path."
        )

    # ── Central Widget ────────────────────────────────────────

    def _startup_status(self, message: str):
        cb = self._startup_status_cb
        if callable(cb):
            try:
                cb(message)
            except Exception:
                pass

    def _build_central_widget(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Banner
        banner = logo_label(260, self)
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

    def _apply_local_theme_styles(self):
        light = current_theme() == THEME_LIGHT
        if light:
            self.output_log.setStyleSheet("""
                QTextEdit {
                    background-color: #ffffff;
                    color: #1f2937;
                    border: 1px solid #d8dee9;
                    border-radius: 4px;
                    padding: 4px;
                }
            """)
            self.cmd_input.setStyleSheet("""
                QLineEdit {
                    background-color: #ffffff;
                    color: #1f2937;
                    border: 1px solid #cfd6e4;
                    border-radius: 4px;
                    padding: 6px 8px;
                }
                QLineEdit:focus { border: 1px solid #2563eb; }
            """)
        else:
            self.output_log.setStyleSheet("""
                QTextEdit {
                    background-color: #1a1a1a;
                    color: #b0b0b0;
                    border: 1px solid #3c3c3c;
                    border-radius: 4px;
                    padding: 4px;
                }
            """)
            self.cmd_input.setStyleSheet("""
                QLineEdit {
                    background-color: #1a1a1a;
                    color: #cccccc;
                    border: 1px solid #3c3c3c;
                    border-radius: 4px;
                    padding: 6px 8px;
                }
                QLineEdit:focus { border: 1px solid #6b9ece; }
            """)

    # ── Actions ───────────────────────────────────────────────

    def _create_actions(self):
        self.act_new_project = QAction("New Project...", self)
        self.act_new_project.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.act_new_project.triggered.connect(self._on_new_project)

        self.act_open_project = QAction("Open Project...", self)
        self.act_open_project.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.act_open_project.triggered.connect(self._on_open_project)

        self.act_recover_session = QAction("Recover Last Session", self)
        self.act_recover_session.triggered.connect(self._on_recover_session)

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

        self.act_open_layout = QAction("Open Layout (KLayout)...", self)
        self.act_open_layout.triggered.connect(self._on_open_layout_prompt)

        self.act_klayout_runtime = QAction("KLayout Runtime...", self)
        self.act_klayout_runtime.triggered.connect(self._on_klayout_runtime)
        self.act_sim_runtime = QAction("Simulator Manager...", self)
        self.act_sim_runtime.triggered.connect(self.open_simulator_manager)
        self.act_sigview = QAction("Open SigView", self)
        self.act_sigview.triggered.connect(self.open_sigview)

        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)

        self.act_theme_dark = QAction("Dark Mode", self)
        self.act_theme_dark.setCheckable(True)
        self.act_theme_dark.triggered.connect(lambda: self._set_theme(THEME_DARK))
        self.theme_group.addAction(self.act_theme_dark)

        self.act_theme_light = QAction("Light Mode", self)
        self.act_theme_light.setCheckable(True)
        self.act_theme_light.triggered.connect(lambda: self._set_theme(THEME_LIGHT))
        self.theme_group.addAction(self.act_theme_light)

        self._sync_theme_actions()

    # ── Menus ─────────────────────────────────────────────────

    def _create_menus(self):
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_new_project)
        file_menu.addAction(self.act_open_project)
        self._recent_projects_menu = file_menu.addMenu("Open Recent Project")
        self._refresh_recent_projects_menu()
        file_menu.addAction(self.act_recover_session)
        file_menu.addSeparator()
        file_menu.addAction(self.act_new_lib)
        file_menu.addSeparator()
        file_menu.addAction(self.act_exit)

        # Tools
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(self.act_lib_manager)
        tools_menu.addSeparator()
        act_ade = QAction("SimENV - Simulation Environment", self)
        act_ade.triggered.connect(self._on_open_simenv_prompt)
        tools_menu.addAction(act_ade)
        tools_menu.addAction(self.act_sigview)
        tools_menu.addSeparator()
        tools_menu.addAction(self.act_open_layout)
        tools_menu.addAction(self.act_klayout_runtime)
        tools_menu.addAction(self.act_sim_runtime)
        tools_menu.addSeparator()
        act_pdk = QAction("PDK Manager...", self)
        act_pdk.setShortcut(QKeySequence("Ctrl+P"))
        act_pdk.triggered.connect(self.open_pdk_manager)
        tools_menu.addAction(act_pdk)

        view_menu = menubar.addMenu("&View")
        theme_menu = view_menu.addMenu("Theme")
        theme_menu.addAction(self.act_theme_dark)
        theme_menu.addAction(self.act_theme_light)

        # Help
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(QAction("Documentation", self))
        help_menu.addAction(self.act_about)

    # ── Status Bar ────────────────────────────────────────────

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage("Ready")

    def _sync_theme_actions(self):
        theme = current_theme()
        self.act_theme_dark.setChecked(theme == THEME_DARK)
        self.act_theme_light.setChecked(theme == THEME_LIGHT)

    def _set_theme(self, theme: str):
        selected = apply_theme(QApplication.instance(), theme)
        self._apply_local_theme_styles()
        self._sync_theme_actions()
        self.log(f"Theme changed to {selected} mode")
        self.statusBar().showMessage(f"Theme: {selected}", 3000)

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

    def open_simulator_manager(self):
        """Open the Simulator Manager window (singleton)."""
        if self._sim_manager is None or not self._sim_manager.isVisible():
            self._sim_manager = SimulatorManagerWindow(self.workspace, ciw=self, parent=self)
            self._sim_manager.show()
        else:
            self._sim_manager.raise_()
            self._sim_manager.activateWindow()
        self.log("Opened Simulator Manager")

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

        try:
            from lumen.gui.schematic_editor_window import SchematicEditorWindow
            editor = SchematicEditorWindow(self.db, library, cell, view, ciw=self)
            editor.show()
            self._editor_windows.append(editor)
            self.log(f"Opened editor: {library}/{cell}/{view}")
        except Exception as exc:
            self.log(f"Failed to open editor {library}/{cell}/{view}: {exc}")
            QMessageBox.critical(
                self,
                "Open Editor Failed",
                f"Could not open {library}/{cell}/{view}.\n\n{exc}",
            )

    def open_cellview(self, library: str, cell: str, view: str = "schematic"):
        """Open any cellview with the best available editor."""
        if view == "schematic":
            self.open_schematic_editor(library, cell, view)
            return
        if view == "symbol":
            self.open_symbol_editor(library, cell, view)
            return
        if view == "simenv":
            self.open_ade(library, cell)
            return

        for win in self._editor_windows:
            if (win.isVisible() and getattr(win, "library", "") == library
                    and getattr(win, "cell", "") == cell
                    and getattr(win, "view", "") == view):
                win.raise_()
                win.activateWindow()
                return

        try:
            from lumen.gui.cellview_window import CellViewWindow
            editor = CellViewWindow(self.db, library, cell, view, ciw=self)
            editor.show()
            self._editor_windows.append(editor)
            self.log(f"Opened editor: {library}/{cell}/{view}")
        except Exception as exc:
            self.log(f"Failed to open editor {library}/{cell}/{view}: {exc}")
            QMessageBox.critical(
                self,
                "Open Cellview Failed",
                f"Could not open {library}/{cell}/{view}.\n\n{exc}",
            )

    def open_symbol_editor(self, library: str, cell: str, view: str = "symbol"):
        """Open a symbol editor window for the given cell."""
        for win in self._editor_windows:
            if (win.isVisible() and getattr(win, "library", "") == library
                    and getattr(win, "cell", "") == cell
                    and getattr(win, "view", "") == view):
                win.raise_()
                win.activateWindow()
                return

        try:
            from lumen.gui.symbol_editor_window import SymbolEditorWindow
            editor = SymbolEditorWindow(self.db, library, cell, view, ciw=self)
            editor.show()
            self._editor_windows.append(editor)
            self.log(f"Opened editor: {library}/{cell}/{view}")
        except Exception as exc:
            self.log(f"Failed to open editor {library}/{cell}/{view}: {exc}")
            QMessageBox.critical(
                self,
                "Open Symbol Editor Failed",
                f"Could not open {library}/{cell}/{view}.\n\n{exc}",
            )

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
            self.log("  project_new <name> [parent_dir] - Create and open project")
            self.log("  project_open <path> - Open existing project")
            self.log("  project_list - List recent projects")
            self.log("  lib_manager    — Open Library Manager")
            self.log("  new_lib <name> — Create a new library")
            self.log("  list_libs      — List all libraries")
            self.log("  open <lib> <cell> [view] - Open an editor")
            self.log("  simenv <lib> <cell> - Open SimENV")
            self.log("  sigview - Open SigView")
            self.log("  layout <lib> <cell> - Open layout in KLayout")
            self.log("  klayout - Show KLayout runtime status")
            self.log("  help           - Show this help")
            self.log("  exit           — Exit application")
        elif verb == "project_new" and len(parts) >= 2:
            parent = parts[2] if len(parts) >= 3 else ""
            self._create_and_open_project(parts[1], parent)
        elif verb == "project_open" and len(parts) >= 2:
            self._switch_project(parts[1])
        elif verb == "project_list":
            recents = self.project_system.list_recent_projects()
            if not recents:
                self.log("No recent projects.")
            for proj in recents:
                self.log(f"  {proj.name}: {proj.path}")
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
            self.open_cellview(lib, cell, view)
        elif verb == 'exit':
            self.close()
        elif verb in ('simenv', 'ade') and len(parts) >= 3:
            self.open_ade(parts[1], parts[2])
        elif verb in ("sigview", "wave", "waveform"):
            self.open_sigview()
        elif verb == "layout" and len(parts) >= 3:
            self.open_layout(parts[1], parts[2])
        elif verb == "klayout":
            summary = self.layout_service.runtime_summary()
            active = summary.get("active_executable", "") or "<not configured>"
            version = summary.get("active_version", "") or "unknown"
            self.log(f"KLayout runtime: {active}")
            self.log(f"KLayout version: {version}")
            self.log(f"Discovered installations: {len(summary.get('discovered', []))}")
        else:
            self.log(f"Unknown command: {cmd}")
        self._autosave_session()

    # ── Helpers ───────────────────────────────────────────────

    def _refresh_recent_projects_menu(self):
        if self._recent_projects_menu is None:
            return
        self._recent_projects_menu.clear()
        recents = self.project_system.list_recent_projects()
        if not recents:
            empty = QAction("(No recent projects)", self)
            empty.setEnabled(False)
            self._recent_projects_menu.addAction(empty)
            return
        for proj in recents:
            action = QAction(f"{proj.name}  ({proj.path})", self)
            action.triggered.connect(lambda _checked=False, p=proj.path: self._switch_project(p))
            self._recent_projects_menu.addAction(action)

    def _on_new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if not ok or not name.strip():
            return
        parent = QFileDialog.getExistingDirectory(
            self,
            "Project Parent Folder",
            self.project_system.default_projects_root(),
        )
        if not parent:
            return
        self._create_and_open_project(name.strip(), parent)

    def _create_and_open_project(self, name: str, parent_dir: str = ""):
        try:
            info = self.project_system.create_project(name, parent_dir)
        except ValueError as exc:
            QMessageBox.warning(self, "New Project", str(exc))
            return
        self._switch_project(info.path)

    def _on_open_project(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Open Project Folder",
            self.project_system.default_projects_root(),
        )
        if not folder:
            return
        self._switch_project(folder)

    def _switch_project(self, project_path: str):
        try:
            info = self.project_system.open_project(project_path)
        except ValueError as exc:
            QMessageBox.warning(self, "Open Project", str(exc))
            return

        self._autosave_session()
        self._close_child_windows()
        self.project_info = info
        self._reinitialize_workspace(info.path)
        self._refresh_recent_projects_menu()
        self.log(f"Switched project: {info.name}")
        self.log(f"Workspace: {self.workspace}")
        self.statusBar().showMessage(f"Project: {info.name}", 5000)
        self._maybe_offer_recovery()

    def _reinitialize_workspace(self, workspace: str):
        clear_registry_cache(self.workspace if hasattr(self, "workspace") else "")
        self.workspace = resolve_workspace(workspace)
        os.environ["LUMEN_WORKSPACE"] = self.workspace
        self.db = LibraryDatabase(self.workspace)
        self.layout_service = LayoutXLService(self.db)
        self.pdk_registry = get_registry(self.workspace)

    def _close_child_windows(self):
        if self._lib_manager:
            self._lib_manager.close()
            self._lib_manager = None
        for win in list(self._editor_windows):
            win.close()
        self._editor_windows.clear()
        for win in list(self._simenv_windows):
            win.close()
        self._simenv_windows.clear()
        for win in list(self._sigview_windows):
            win.close()
        self._sigview_windows.clear()
        if self._pdk_manager:
            self._pdk_manager.close()
            self._pdk_manager = None

    def _collect_session_snapshot(self) -> dict:
        editors = []
        for win in self._editor_windows:
            if not win.isVisible():
                continue
            editors.append({
                "library": getattr(win, "library", ""),
                "cell": getattr(win, "cell", ""),
                "view": getattr(win, "view", "schematic"),
            })
        simenvs = []
        for win in self._simenv_windows:
            if not win.isVisible():
                continue
            simenvs.append({
                "library": getattr(win, "library", ""),
                "cell": getattr(win, "cell", ""),
            })
        return {
            "dirty": True,
            "workspace": self.workspace,
            "project_name": self.project_info.name if self.project_info else "",
            "open_editors": editors,
            "open_simenv": simenvs,
            "log_tail": self.output_log.toPlainText().splitlines()[-120:],
        }

    def _autosave_session(self, dirty: bool = True):
        payload = self._collect_session_snapshot()
        payload["dirty"] = bool(dirty)
        self.project_system.save_autosave(payload, self.workspace)

    def _maybe_offer_recovery(self):
        if not self.project_system.has_recovery_data(self.workspace):
            return
        choice = QMessageBox.question(
            self,
            "Recover Session",
            "A recoverable session was found for this project.\n\nRestore open windows now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Yes:
            self._on_recover_session()

    def _on_recover_session(self):
        data = self.project_system.load_autosave(self.workspace)
        if not data:
            QMessageBox.information(self, "Recover Session", "No saved recovery data found.")
            return
        self._apply_recovery_payload(data)
        data["dirty"] = False
        self.project_system.save_autosave(data, self.workspace)
        self.statusBar().showMessage("Session recovered", 5000)

    def _apply_recovery_payload(self, payload: dict):
        for entry in payload.get("open_editors", []):
            lib = str(entry.get("library", ""))
            cell = str(entry.get("cell", ""))
            view = str(entry.get("view", "schematic"))
            if lib and cell:
                self.open_cellview(lib, cell, view)

        for entry in payload.get("open_simenv", []):
            lib = str(entry.get("library", ""))
            cell = str(entry.get("cell", ""))
            if lib and cell:
                self.open_ade(lib, cell)

        self.log("[Recovery] Restored open editor windows.")
        log_tail = payload.get("log_tail", [])
        if isinstance(log_tail, list) and log_tail:
            self.log("[Recovery] Previous log tail:")
            for line in log_tail[-30:]:
                self.log(f"  {line}")

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
            f"<p align='center'><img src='{logo_url()}' width='260'></p>"
            "<p>Version 0.5.0</p>"
            "<p>Next-Generation Open-Source Analog/Mixed-Signal EDA Suite</p>"
            "<p>Powered by GSPICE Simulator Engine</p>"
            "<hr>"
            "<p>Features: Schematic Capture · Symbol Editor · "
            "Library Manager · SimENV · SigView · PDK Manager</p>"
        )

    def log(self, msg: str):
        """Write a message to the APW output log."""
        self.output_log.append(msg)
        # Auto-scroll to bottom
        cursor = self.output_log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.output_log.setTextCursor(cursor)

    def closeEvent(self, event):
        """Close all child windows when APW closes."""
        self._autosave_session(dirty=False)
        self._close_child_windows()
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
        """Open SimENV window for a cell."""
        for win in self._editor_windows:
            if (win.isVisible()
                    and getattr(win, "library", "") == library
                    and getattr(win, "cell", "") == cell
                    and hasattr(win, "open_simenv_tab")):
                simenv = win.open_simenv_tab()
                if simenv is not None:
                    win.raise_()
                    win.activateWindow()
                    return

        try:
            from lumen.gui.ade_window import ADEWindow
            ade = ADEWindow(
                self.db,
                library,
                cell,
                ciw=self,
                pdk_registry=self.pdk_registry,
            )
            ade.show()
            self._simenv_windows.append(ade)
            self.log(f"Opened SimENV: {library}/{cell}")
        except Exception as exc:
            self.log(f"Failed to open SimENV {library}/{cell}: {exc}")
            QMessageBox.critical(
                self,
                "Open SimENV Failed",
                f"Could not open SimENV for {library}/{cell}.\n\n{exc}",
            )

    def open_sigview(self, waveforms: dict | None = None):
        """Open SigView, optionally preloaded with waveform data."""
        try:
            from lumen.gui.waveform_viewer import SigViewWindow
            viewer = SigViewWindow(parent=None)
            if isinstance(waveforms, dict) and waveforms:
                viewer.load_results(waveforms)
            viewer.show()
            self._sigview_windows.append(viewer)
            self.log("Opened SigView")
        except Exception as exc:
            self.log(f"Failed to open SigView: {exc}")
            QMessageBox.critical(
                self,
                "Open SigView Failed",
                f"Could not open SigView.\n\n{exc}",
            )

    def _on_open_simenv_prompt(self):
        from PyQt6.QtWidgets import QInputDialog
        libs = [l.name for l in self.db.get_libraries()]
        if not libs:
            QMessageBox.warning(self, "Error", "No libraries found.")
            return
        lib, ok = QInputDialog.getItem(self, "SimENV", "Library:", libs)
        if not ok:
            return
        cells = self.db.get_cells(lib)
        if not cells:
            QMessageBox.warning(self, "Error", f"No cells in {lib}.")
            return
        cell, ok = QInputDialog.getItem(self, "SimENV", "Cell:", cells)
        if ok:
            self.open_ade(lib, cell)

    def _on_open_layout_prompt(self):
        from PyQt6.QtWidgets import QInputDialog
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
                if install.logs:
                    for line in install.logs[-8:]:
                        self.log(f"[KLayout install] {line}")
                self.log(install.message)
                if not install.success:
                    QMessageBox.warning(self, "KLayout Install Failed", install.message)
                    return
            else:
                return

        libs = [l.name for l in self.db.get_libraries()]
        if not libs:
            QMessageBox.warning(self, "Layout", "No libraries found.")
            return
        lib, ok = QInputDialog.getItem(self, "Open Layout", "Library:", libs)
        if not ok:
            return
        cells = self.db.get_cells(lib)
        if not cells:
            QMessageBox.warning(self, "Layout", f"No cells in {lib}.")
            return
        cell, ok = QInputDialog.getItem(self, "Open Layout", "Cell:", cells)
        if ok:
            self.open_layout(lib, cell)

    class _KLayoutInstallThread(QThread):
        def __init__(self, layout_service, parent=None):
            super().__init__(parent)
            self.layout_service = layout_service
            self.result = None

        def run(self):
            self.result = self.layout_service.install_runtime_if_missing()

    def open_layout(self, library: str, cell: str):
        """Open/focus KLayout for the selected design."""
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
                if install.logs:
                    for line in install.logs[-5:]:
                        self.log(f"[KLayout install] {line}")
                self.log(install.message)
                if not install.success:
                    QMessageBox.warning(self, "KLayout Install Failed", install.message)
                    return
            else:
                return

        for win in self._editor_windows:
            if (
                win.isVisible()
                and getattr(win, "library", "") == library
                and getattr(win, "cell", "") == cell
                and hasattr(win, "open_layout_editor")
            ):
                launched = win.open_layout_editor()
                if launched:
                    win.raise_()
                    win.activateWindow()
                    return

        result = self.layout_service.open_layout_editor(library, cell)
        self.log(result.message)
        if result.success:
            self.statusBar().showMessage("KLayout launched", 3000)
        else:
            QMessageBox.warning(self, "Open Layout Failed", result.message)

    def _on_klayout_runtime(self):
        from PyQt6.QtWidgets import QInputDialog

        summary = self.layout_service.runtime_summary()
        discovered = summary.get("discovered", [])
        active = summary.get("active_executable", "") or "<not configured>"
        active_version = summary.get("active_version", "") or "unknown"
        if not discovered and active == "<not configured>":
            install_choice = QMessageBox.question(
                self,
                "KLayout Runtime",
                "No KLayout installation was detected.\n\nInstall automatically now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if install_choice == QMessageBox.StandardButton.Yes:
                install = self._run_klayout_install()
                if install.logs:
                    for line in install.logs[-8:]:
                        self.log(f"[KLayout install] {line}")
                self.log(install.message)
                if install.success:
                    self.statusBar().showMessage("KLayout installed and configured", 5000)
                else:
                    QMessageBox.warning(self, "KLayout Install Failed", install.message)
                summary = self.layout_service.runtime_summary()
                discovered = summary.get("discovered", [])
                active = summary.get("active_executable", "") or "<not configured>"
                active_version = summary.get("active_version", "") or "unknown"
        lines = [
            f"Active runtime: {active}",
            f"Active version: {active_version}",
            "",
            "Discovered runtimes:",
        ]
        for idx, item in enumerate(discovered, start=1):
            version = item.get("version", "") or "unknown"
            source = item.get("source", "auto")
            lines.append(f"{idx}. {item.get('executable', '')} ({version}, {source})")
        if not discovered:
            lines.append("  none found automatically")

        lines.append("")
        lines.append("Enter a custom executable path to override, or leave blank to keep current.")
        path, ok = QInputDialog.getText(
            self,
            "KLayout Runtime",
            "\n".join(lines),
            text=active if active != "<not configured>" else "",
        )
        if not ok:
            return
        path = path.strip()
        if not path:
            return
        if self.layout_service.set_runtime_executable(path):
            refreshed = self.layout_service.runtime_summary()
            runtime = refreshed.get("active_executable", path)
            version = refreshed.get("active_version", "unknown")
            self.log(f"KLayout runtime set to: {runtime}")
            self.log(f"KLayout runtime version: {version}")
            self.statusBar().showMessage("KLayout runtime updated", 4000)
        else:
            QMessageBox.warning(
                self,
                "KLayout Runtime",
                "The provided executable path is invalid or not runnable.",
            )

    def _run_klayout_install(self):
        """Install KLayout in a worker thread so UI remains responsive."""
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


# Backward compatibility alias for older imports/references.
CIWWindow = APWWindow




