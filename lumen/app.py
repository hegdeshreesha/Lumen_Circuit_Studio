"""
Lumen Circuit Studio — Application Bootstrap
"""
import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtCore import Qt


def main():
    """Main entry point for Lumen Circuit Studio."""
    # High DPI support
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("Lumen Circuit Studio")
    app.setOrganizationName("LumenEDA")
    app.setApplicationVersion("0.1.0")

    # Set default font
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    # Apply dark theme
    app.setStyleSheet(_get_stylesheet())

    # Create and show CIW (Command Interpreter Window)
    from lumen.gui.ciw_window import CIWWindow
    ciw = CIWWindow()
    ciw.show()

    # Auto-open Library Manager on first launch
    ciw.open_library_manager()

    return app.exec()


def _get_stylesheet() -> str:
    """Return the application-wide dark theme stylesheet."""
    return """
    /* ===== Lumen Circuit Studio — Muted Professional Dark Theme ===== */

    QMainWindow, QDialog {
        background-color: #1e1e1e;
        color: #cccccc;
    }

    QWidget {
        background-color: #1e1e1e;
        color: #cccccc;
        font-family: "Segoe UI", sans-serif;
    }

    /* Menu Bar */
    QMenuBar {
        background-color: #2d2d2d;
        color: #cccccc;
        border-bottom: 1px solid #3c3c3c;
        padding: 2px;
    }
    QMenuBar::item:selected {
        background-color: #3c3c3c;
        border-radius: 4px;
    }
    QMenu {
        background-color: #2d2d2d;
        color: #cccccc;
        border: 1px solid #3c3c3c;
        border-radius: 4px;
        padding: 4px;
    }
    QMenu::item:selected {
        background-color: #094771;
        border-radius: 3px;
    }
    QMenu::separator {
        height: 1px;
        background: #3c3c3c;
        margin: 4px 8px;
    }

    /* Tool Bar */
    QToolBar {
        background-color: #2d2d2d;
        border: none;
        spacing: 3px;
        padding: 3px;
    }
    QToolBar::separator {
        width: 1px;
        background: #3c3c3c;
        margin: 4px 2px;
    }
    QToolButton {
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 4px;
        color: #cccccc;
    }
    QToolButton:hover {
        background-color: #3c3c3c;
        border: 1px solid #4d4d4d;
    }
    QToolButton:pressed {
        background-color: #094771;
    }

    /* Dock Widgets */
    QDockWidget {
        color: #cccccc;
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }
    QDockWidget::title {
        background-color: #2d2d2d;
        padding: 6px;
        border: 1px solid #3c3c3c;
        border-radius: 4px 4px 0 0;
        font-weight: bold;
    }

    /* Tree View */
    QTreeView, QTreeWidget {
        background-color: #252526;
        border: 1px solid #3c3c3c;
        border-radius: 4px;
        color: #cccccc;
        outline: none;
    }
    QTreeView::item:hover {
        background-color: #2a2d2e;
    }
    QTreeView::item:selected {
        background-color: #094771;
        color: #e0e0e0;
    }
    QTreeView::branch:has-children:!has-siblings:closed,
    QTreeView::branch:closed:has-children:has-siblings {
        border-image: none;
    }

    /* Tab Widget */
    QTabWidget::pane {
        border: 1px solid #3c3c3c;
        border-radius: 4px;
        background-color: #1e1e1e;
    }
    QTabBar::tab {
        background-color: #2d2d2d;
        color: #808080;
        border: 1px solid #3c3c3c;
        border-bottom: none;
        padding: 6px 16px;
        margin-right: 2px;
        border-radius: 4px 4px 0 0;
    }
    QTabBar::tab:selected {
        background-color: #1e1e1e;
        color: #cccccc;
        border-bottom: 2px solid #6b9ece;
    }
    QTabBar::tab:hover:!selected {
        background-color: #353535;
    }

    /* Scroll Bars */
    QScrollBar:vertical {
        background-color: #1e1e1e;
        width: 10px;
        border-radius: 5px;
    }
    QScrollBar::handle:vertical {
        background-color: #424242;
        border-radius: 5px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: #5a5a5a;
    }
    QScrollBar:horizontal {
        background-color: #1e1e1e;
        height: 10px;
        border-radius: 5px;
    }
    QScrollBar::handle:horizontal {
        background-color: #424242;
        border-radius: 5px;
        min-width: 30px;
    }
    QScrollBar::add-line, QScrollBar::sub-line {
        height: 0px;
        width: 0px;
    }

    /* Splitter */
    QSplitter::handle {
        background-color: #3c3c3c;
    }
    QSplitter::handle:horizontal { width: 2px; }
    QSplitter::handle:vertical { height: 2px; }

    /* Status Bar */
    QStatusBar {
        background-color: #007acc;
        color: #ffffff;
        border-top: none;
    }

    /* Line Edit */
    QLineEdit {
        background-color: #3c3c3c;
        border: 1px solid #4d4d4d;
        border-radius: 4px;
        padding: 4px 8px;
        color: #cccccc;
    }
    QLineEdit:focus {
        border: 1px solid #6b9ece;
    }

    /* Push Button */
    QPushButton {
        background-color: #3c3c3c;
        color: #cccccc;
        border: 1px solid #4d4d4d;
        border-radius: 4px;
        padding: 6px 16px;
    }
    QPushButton:hover {
        background-color: #094771;
        border-color: #6b9ece;
        color: #e0e0e0;
    }
    QPushButton:pressed {
        background-color: #007acc;
    }

    /* Labels */
    QLabel {
        color: #cccccc;
        background: transparent;
    }

    /* Group Box */
    QGroupBox {
        border: 1px solid #3c3c3c;
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 16px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: #6b9ece;
    }

    /* Table / Properties */
    QTableWidget, QTableView {
        background-color: #252526;
        border: 1px solid #3c3c3c;
        border-radius: 4px;
        gridline-color: #333333;
        color: #cccccc;
    }
    QHeaderView::section {
        background-color: #2d2d2d;
        color: #cccccc;
        border: 1px solid #3c3c3c;
        padding: 4px;
        font-weight: bold;
    }

    /* Combo Box */
    QComboBox {
        background-color: #3c3c3c;
        border: 1px solid #4d4d4d;
        border-radius: 4px;
        padding: 4px 8px;
        color: #cccccc;
    }
    QComboBox::drop-down {
        border: none;
        width: 20px;
    }
    QComboBox QAbstractItemView {
        background-color: #2d2d2d;
        border: 1px solid #3c3c3c;
        color: #cccccc;
        selection-background-color: #094771;
    }

    /* Tooltip */
    QToolTip {
        background-color: #2d2d2d;
        color: #cccccc;
        border: 1px solid #4d4d4d;
        border-radius: 4px;
        padding: 4px;
    }
    """


if __name__ == "__main__":
    sys.exit(main())
