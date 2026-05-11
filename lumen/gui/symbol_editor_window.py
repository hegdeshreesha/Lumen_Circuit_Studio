"""
Lumen Circuit Studio - Symbol Editor Window

Standalone shell for editing symbol views.
"""
from PyQt6.QtWidgets import QMainWindow, QStatusBar, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence

from lumen.core.database import LibraryDatabase
from lumen.gui.symbol_editor import SymbolEditor


class SymbolEditorWindow(QMainWindow):
    """Standalone window for editing a symbol view."""

    def __init__(self, db: LibraryDatabase, library: str, cell: str,
                 view: str = "symbol", ciw=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.library = library
        self.cell = cell
        self.view = view
        self.ciw = ciw

        self.setWindowTitle(f"Lumen - {cell} ({view}) - [{library}]")
        self.setMinimumSize(900, 650)
        self.resize(1100, 760)

        self.editor = SymbolEditor(db, library, cell, view, parent=self)
        self.editor.coord_changed.connect(self._update_coords)
        self.setCentralWidget(self.editor)

        self._create_actions()
        self._create_menus()
        self._create_status_bar()

    def _create_actions(self):
        self.act_save = QAction("Save", self)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save.triggered.connect(self._on_save)

        self.act_close = QAction("Close", self)
        self.act_close.setShortcut(QKeySequence("Ctrl+W"))
        self.act_close.triggered.connect(self.close)

    def _create_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.act_save)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close)

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        self.cell_label = QLabel(f"{self.library}/{self.cell}")
        self.cell_label.setStyleSheet("color: #ffffff; padding: 0 12px;")
        self.coord_label = QLabel("X: 0  Y: 0")
        self.coord_label.setStyleSheet("color: #ffffff; padding: 0 12px;")

        sb.addWidget(self.cell_label)
        sb.addPermanentWidget(self.coord_label)

    def _update_coords(self, x: float, y: float):
        self.coord_label.setText(f"X: {x:.1f}  Y: {y:.1f}")

    def _on_save(self):
        self.editor.save()
        if self.ciw:
            self.ciw.log(f"Saved {self.library}/{self.cell}/{self.view}")
        self.statusBar().showMessage("Saved", 2000)
