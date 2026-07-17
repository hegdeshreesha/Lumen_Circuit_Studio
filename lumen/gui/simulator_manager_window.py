"""
Simulator Manager UI and missing-simulator install prompt.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from lumen.core.simulator import SIMULATOR_INFO, SimulatorBridge, get_simulator_label
from lumen.core.simulator_runtime import ACTIVE_SIMULATORS, SimulatorRuntimeManager
from lumen.gui.branding import apply_window_branding


class SimulatorManagerWindow(QMainWindow):
    """Manage simulator installations and executable paths."""

    def __init__(self, workspace: str, ciw=None, parent=None):
        super().__init__(parent)
        self.workspace = str(Path(workspace).expanduser().resolve())
        self.ciw = ciw
        self.runtime = SimulatorRuntimeManager(self.workspace)
        self.runtime.apply_environment_overrides()

        self.setWindowTitle("Lumen — Simulator Manager")
        apply_window_branding(self)
        self.setMinimumSize(860, 420)
        self.resize(980, 500)

        self._build_ui()
        self._create_toolbar()
        self._create_status_bar()
        self._refresh()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        hint = QLabel(
            "Configure simulator runtimes for this workspace. "
            "If a simulator is missing, you can install it automatically or point to an existing executable."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8c9aa8;background:transparent;")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Simulator", "Status", "Executable", "Version", "Source"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        self.install_btn = QPushButton("Install")
        self.install_btn.clicked.connect(self._on_install)
        row.addWidget(self.install_btn)

        self.locate_btn = QPushButton("Locate Executable...")
        self.locate_btn.clicked.connect(self._on_locate)
        row.addWidget(self.locate_btn)

        self.clear_btn = QPushButton("Clear Selected Path")
        self.clear_btn.clicked.connect(self._on_clear)
        row.addWidget(self.clear_btn)

        row.addStretch()
        layout.addLayout(row)

    def _create_toolbar(self):
        tb = QToolBar("Simulator")
        act_refresh = QAction("Refresh", self)
        act_refresh.triggered.connect(self._refresh)
        tb.addAction(act_refresh)
        act_close = QAction("Close", self)
        act_close.triggered.connect(self.close)
        tb.addAction(act_close)
        self.addToolBar(tb)

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color:#ffffff;padding:0 8px;")
        sb.addWidget(self.status_label)

    def _selected_simulator(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        if not item:
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or ""

    def _refresh(self):
        sims = list(ACTIVE_SIMULATORS)
        self.table.setRowCount(len(sims))
        available_count = 0
        for r, sim in enumerate(sims):
            exe = self.runtime.get_active_executable(sim)
            bridge = SimulatorBridge(sim, exe_path=exe)
            available = bridge.is_available()
            if available:
                available_count += 1
            version = self.runtime.probe_version(sim, bridge.exe_path if available else exe)
            source = ""
            discovered = self.runtime.discover_installations(sim)
            if discovered:
                source = discovered[0].source
            if exe:
                source = self.runtime._config.get("simulators", {}).get(sim, {}).get("active_source", source)  # noqa: SLF001

            sim_item = QTableWidgetItem(get_simulator_label(sim))
            sim_item.setData(Qt.ItemDataRole.UserRole, sim)
            status_item = QTableWidgetItem("✓ Found" if available else "✗ Missing")
            if available:
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            else:
                status_item.setForeground(Qt.GlobalColor.darkRed)

            exe_item = QTableWidgetItem(bridge.exe_path or exe or "")
            ver_item = QTableWidgetItem(version or "")
            src_item = QTableWidgetItem(source or "")

            for item in (sim_item, status_item, exe_item, ver_item, src_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(r, 0, sim_item)
            self.table.setItem(r, 1, status_item)
            self.table.setItem(r, 2, exe_item)
            self.table.setItem(r, 3, ver_item)
            self.table.setItem(r, 4, src_item)

        self.status_label.setText(f"{available_count}/{len(sims)} simulators available")

    def _on_install(self):
        sim = self._selected_simulator()
        if not sim:
            QMessageBox.information(self, "Simulator Manager", "Select a simulator first.")
            return
        result = self.runtime.install_if_missing(sim)
        self.runtime.apply_environment_overrides()
        self._refresh()
        if self.ciw:
            self.ciw.log(f"[Simulator] {result.message}")
            if result.logs:
                for line in result.logs[-8:]:
                    self.ciw.log(f"[Simulator install] {line}")
        if result.success:
            QMessageBox.information(self, "Install Complete", result.message)
        else:
            QMessageBox.warning(self, "Install Failed", result.message)

    def _on_locate(self):
        sim = self._selected_simulator()
        if not sim:
            QMessageBox.information(self, "Simulator Manager", "Select a simulator first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Locate {sim} Executable",
            "",
            "Executable (*.exe);;All Files (*)",
        )
        if not path:
            return
        if self.runtime.set_active_executable(sim, path):
            self.runtime.apply_environment_overrides()
            self._refresh()
            if self.ciw:
                self.ciw.log(f"[Simulator] Set {sim} executable: {path}")
        else:
            QMessageBox.warning(self, "Simulator Manager", "Selected file is not a valid executable path.")

    def _on_clear(self):
        sim = self._selected_simulator()
        if not sim:
            QMessageBox.information(self, "Simulator Manager", "Select a simulator first.")
            return
        self.runtime.clear_active_executable(sim)
        self.runtime.apply_environment_overrides()
        self._refresh()
        if self.ciw:
            self.ciw.log(f"[Simulator] Cleared pinned path for {sim}")


def ensure_simulator_available(parent, workspace: str, simulator: str, logger=None) -> bool:
    """Prompt user to install/configure simulator when missing."""
    runtime = SimulatorRuntimeManager(workspace)
    runtime.apply_environment_overrides()
    bridge = SimulatorBridge(simulator, exe_path=runtime.get_active_executable(simulator))
    if bridge.is_available():
        return True

    sim_label = get_simulator_label(simulator)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Simulator Not Found")
    box.setText(f"{sim_label} is not available.")
    box.setInformativeText(
        "Choose how to proceed:\n"
        "• Install automatically\n"
        "• Locate an existing executable\n"
        "• Open Simulator Manager"
    )
    btn_install = box.addButton("Install Automatically", QMessageBox.ButtonRole.AcceptRole)
    btn_locate = box.addButton("Locate Executable...", QMessageBox.ButtonRole.ActionRole)
    btn_manage = box.addButton("Open Simulator Manager...", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()

    clicked = box.clickedButton()
    if clicked == btn_install:
        result = runtime.install_if_missing(simulator)
        runtime.apply_environment_overrides()
        if logger:
            logger(f"{result.message}")
            if result.logs:
                for line in result.logs[-6:]:
                    logger(line)
        if not result.success:
            QMessageBox.warning(parent, "Install Failed", result.message)
    elif clicked == btn_locate:
        path, _ = QFileDialog.getOpenFileName(
            parent,
            f"Locate {simulator} Executable",
            "",
            "Executable (*.exe);;All Files (*)",
        )
        if path:
            if not runtime.set_active_executable(simulator, path):
                QMessageBox.warning(parent, "Invalid Executable", "Could not configure that executable.")
            runtime.apply_environment_overrides()
    elif clicked == btn_manage:
        win = SimulatorManagerWindow(workspace, parent=parent)
        win.show()
        setattr(parent, "_sim_manager_window", win)
        return False
    else:
        return False

    check = SimulatorBridge(simulator, exe_path=runtime.get_active_executable(simulator))
    return check.is_available()
