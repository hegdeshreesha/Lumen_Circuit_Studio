"""
Lumen Circuit Studio - Generic Cellview Window

Lightweight editor for non-schematic/non-symbol views (e.g., veriloga, config).
"""
from __future__ import annotations

import json

from lumen.qt.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QMessageBox,
    QStatusBar,
)
from lumen.qt.QtGui import QAction, QKeySequence, QFont

from lumen.core.database import LibraryDatabase
from lumen.gui.branding import apply_window_branding


class CellViewWindow(QMainWindow):
    """Generic text/JSON cellview editor."""

    def __init__(self, db: LibraryDatabase, library: str, cell: str, view: str,
                 ciw=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.library = library
        self.cell = cell
        self.view = view
        self.ciw = ciw
        self._mode = "json"  # json | source
        self._source_key = "source"
        self._payload: dict = {}

        self.setWindowTitle(f"Lumen - {cell} ({view}) - [{library}]")
        apply_window_branding(self)
        self.resize(980, 680)
        self.setMinimumSize(760, 520)

        self._build_ui()
        self._create_actions()
        self._create_menus()
        self._load_view()

    def _build_ui(self):
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        self.setCentralWidget(central)

        self.editor = QTextEdit(self)
        self.editor.setFont(QFont("Consolas", 10))
        layout.addWidget(self.editor)

        sb = QStatusBar(self)
        self.setStatusBar(sb)
        sb.showMessage("Ready")

    def _create_actions(self):
        self.act_save = QAction("Save", self)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save.triggered.connect(self._on_save)

        self.act_reload = QAction("Reload", self)
        self.act_reload.setShortcut(QKeySequence("F5"))
        self.act_reload.triggered.connect(self._load_view)

        self.act_close = QAction("Close", self)
        self.act_close.setShortcut(QKeySequence("Ctrl+W"))
        self.act_close.triggered.connect(self.close)

    def _create_menus(self):
        menubar = self.menuBar()
        menubar.clear()
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_reload)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close)

    def _default_payload(self) -> dict:
        if self.view in ("veriloga", "verilog", "vhdl"):
            return {
                "type": self.view,
                "name": self.cell,
                "library": self.library,
                "source": "",
            }
        return {
            "type": self.view,
            "name": self.cell,
            "library": self.library,
        }

    def _load_view(self):
        data = self.db.load_view(self.library, self.cell, self.view)
        if not isinstance(data, dict):
            data = self._default_payload()
        self._payload = dict(data)

        if isinstance(data.get("source"), str):
            self._mode = "source"
            self._source_key = "source"
            self.editor.setPlainText(data.get("source", ""))
            self.statusBar().showMessage("Source view loaded", 3000)
            return

        self._mode = "json"
        text = json.dumps(data, indent=2, ensure_ascii=False)
        self.editor.setPlainText(text)
        self.statusBar().showMessage("JSON view loaded", 3000)

    def _on_save(self):
        try:
            if self._mode == "source":
                payload = dict(self._payload)
                payload["type"] = payload.get("type", self.view)
                payload["name"] = payload.get("name", self.cell)
                payload["library"] = payload.get("library", self.library)
                payload[self._source_key] = self.editor.toPlainText()
            else:
                raw = self.editor.toPlainText().strip()
                parsed = json.loads(raw) if raw else {}
                if not isinstance(parsed, dict):
                    raise ValueError("Cellview JSON must be an object at top level.")
                payload = parsed
                payload["type"] = payload.get("type", self.view)
                payload["name"] = payload.get("name", self.cell)
                payload["library"] = payload.get("library", self.library)

            self.db.save_view(self.library, self.cell, self.view, payload)
            self._payload = dict(payload)
            self.statusBar().showMessage("Saved", 3000)
            if self.ciw:
                self.ciw.log(f"Saved {self.library}/{self.cell}/{self.view}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
