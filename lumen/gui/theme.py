"""Application theme management for Lumen Circuit Studio."""

from lumen.qt.QtCore import QSettings


THEME_DARK = "dark"
THEME_LIGHT = "light"
THEMES = (THEME_DARK, THEME_LIGHT)


def current_theme() -> str:
    """Return the persisted UI theme."""
    theme = QSettings("LumenEDA", "Lumen Circuit Studio").value(
        "ui/theme", THEME_DARK)
    return theme if theme in THEMES else THEME_DARK


def set_current_theme(theme: str) -> str:
    """Persist and return a normalized UI theme name."""
    normalized = theme if theme in THEMES else THEME_DARK
    QSettings("LumenEDA", "Lumen Circuit Studio").setValue("ui/theme", normalized)
    return normalized


def apply_theme(app, theme: str | None = None) -> str:
    """Apply a global stylesheet to the QApplication and persist the choice."""
    selected = set_current_theme(theme or current_theme())
    app.setProperty("lumenTheme", selected)
    app.setStyleSheet(get_stylesheet(selected))
    return selected


def is_light_theme(app=None) -> bool:
    """Return True when the active or persisted theme is light."""
    if app is not None and app.property("lumenTheme"):
        return app.property("lumenTheme") == THEME_LIGHT
    return current_theme() == THEME_LIGHT


def get_stylesheet(theme: str) -> str:
    """Return the application-wide stylesheet for the requested theme."""
    return _light_stylesheet() if theme == THEME_LIGHT else _dark_stylesheet()


def _dark_stylesheet() -> str:
    return """
    /* ===== Lumen Circuit Studio - Professional Dark Theme ===== */
    QMainWindow, QDialog, QWidget {
        background-color: #1e1e1e;
        color: #cccccc;
        font-family: "Segoe UI", sans-serif;
    }
    QMenuBar, QMenu, QToolBar, QDockWidget::title, QHeaderView::section {
        background-color: #2d2d2d;
        color: #cccccc;
        border-color: #3c3c3c;
    }
    QMenuBar { border-bottom: 1px solid #3c3c3c; padding: 2px; }
    QMenu { border: 1px solid #3c3c3c; border-radius: 4px; padding: 4px; }
    QMenuBar::item:selected, QMenu::item:selected, QToolButton:hover {
        background-color: #3c3c3c;
    }
    QToolBar {
        border: none;
        spacing: 4px;
        padding: 4px;
    }
    QToolButton {
        background-color: #2d2d2d;
        border: 1px solid transparent;
        border-radius: 5px;
        padding: 5px;
        min-width: 26px;
        min-height: 26px;
        color: #cccccc;
    }
    QToolButton:hover {
        background-color: #35383d;
        border-color: #4e6074;
    }
    QToolButton:pressed, QMenu::item:selected {
        background-color: #0e5a88;
        border-color: #6b9ece;
    }
    QDockWidget { color: #cccccc; }
    QDockWidget::title {
        padding: 6px;
        border: 1px solid #3c3c3c;
        font-weight: bold;
    }
    QTreeView, QTreeWidget, QTableWidget, QTableView, QTextEdit {
        background-color: #252526;
        color: #cccccc;
        border: 1px solid #3c3c3c;
        border-radius: 4px;
        gridline-color: #333333;
    }
    QTreeView::item:hover { background-color: #2a2d2e; }
    QTreeView::item:selected, QTableWidget::item:selected {
        background-color: #094771;
        color: #ffffff;
    }
    QTabWidget::pane {
        border: 1px solid #3c3c3c;
        background-color: #1e1e1e;
    }
    QTabBar::tab {
        background-color: #2d2d2d;
        color: #808080;
        border: 1px solid #3c3c3c;
        border-bottom: none;
        padding: 6px 16px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #1e1e1e;
        color: #cccccc;
        border-bottom: 2px solid #6b9ece;
    }
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
        background-color: #3c3c3c;
        color: #cccccc;
        border: 1px solid #4d4d4d;
        border-radius: 4px;
        padding: 4px 8px;
    }
    QLineEdit:focus, QComboBox:focus { border: 1px solid #6b9ece; }
    QPushButton {
        background-color: #33363a;
        color: #f0f3f6;
        border: 1px solid #535963;
        border-radius: 5px;
        padding: 6px 14px;
        min-height: 24px;
        font-weight: 600;
    }
    QPushButton:hover {
        background-color: #3d4652;
        border-color: #6b9ece;
    }
    QPushButton:pressed {
        background-color: #0e5a88;
        border-color: #8fb8dc;
    }
    QPushButton:disabled {
        background-color: #292b2f;
        color: #777f88;
        border-color: #3a3d42;
    }
    QPushButton#primaryButton, QPushButton#adePrimaryButton {
        background-color: #0e639c;
        color: #ffffff;
        border-color: #2f86c7;
    }
    QPushButton#primaryButton:hover, QPushButton#adePrimaryButton:hover {
        background-color: #1177bb;
        border-color: #63a8db;
    }
    QLabel { color: #cccccc; background: transparent; }
    QGroupBox {
        border: 1px solid #3c3c3c;
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 16px;
    }
    QGroupBox::title { color: #6b9ece; left: 12px; padding: 0 4px; }
    QStatusBar { background-color: #007acc; color: #ffffff; }
    QScrollBar:vertical, QScrollBar:horizontal { background-color: #1e1e1e; }
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
        background-color: #424242;
        border-radius: 5px;
    }
    QToolTip {
        background-color: #2d2d2d;
        color: #cccccc;
        border: 1px solid #4d4d4d;
    }
    """


def _light_stylesheet() -> str:
    return """
    /* ===== Lumen Circuit Studio - Clean Light Theme ===== */
    QMainWindow, QDialog, QWidget {
        background-color: #f6f7fb;
        color: #1f2937;
        font-family: "Segoe UI", sans-serif;
    }
    QMenuBar, QMenu, QToolBar, QDockWidget::title, QHeaderView::section {
        background-color: #ffffff;
        color: #1f2937;
        border-color: #d8dee9;
    }
    QMenuBar { border-bottom: 1px solid #d8dee9; padding: 2px; }
    QMenu { border: 1px solid #d8dee9; border-radius: 4px; padding: 4px; }
    QMenuBar::item:selected, QMenu::item:selected, QToolButton:hover {
        background-color: #e8f1ff;
    }
    QToolBar {
        border: none;
        spacing: 4px;
        padding: 4px;
    }
    QToolButton {
        background-color: #ffffff;
        border: 1px solid transparent;
        border-radius: 5px;
        padding: 5px;
        min-width: 26px;
        min-height: 26px;
        color: #1f2937;
    }
    QToolButton:hover {
        background-color: #eef4ff;
        border-color: #9dbbec;
    }
    QToolButton:pressed, QMenu::item:selected {
        background-color: #cfe3ff;
        border-color: #2563eb;
    }
    QDockWidget { color: #1f2937; }
    QDockWidget::title {
        padding: 6px;
        border: 1px solid #d8dee9;
        font-weight: bold;
    }
    QTreeView, QTreeWidget, QTableWidget, QTableView, QTextEdit {
        background-color: #ffffff;
        color: #1f2937;
        border: 1px solid #d8dee9;
        border-radius: 4px;
        gridline-color: #e5e7eb;
    }
    QTreeView::item:hover { background-color: #eef4ff; }
    QTreeView::item:selected, QTableWidget::item:selected {
        background-color: #cfe3ff;
        color: #111827;
    }
    QTabWidget::pane {
        border: 1px solid #d8dee9;
        background-color: #ffffff;
    }
    QTabBar::tab {
        background-color: #eef2f7;
        color: #526071;
        border: 1px solid #d8dee9;
        border-bottom: none;
        padding: 6px 16px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #ffffff;
        color: #111827;
        border-bottom: 2px solid #2563eb;
    }
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
        background-color: #ffffff;
        color: #1f2937;
        border: 1px solid #cfd6e4;
        border-radius: 4px;
        padding: 4px 8px;
    }
    QLineEdit:focus, QComboBox:focus { border: 1px solid #2563eb; }
    QPushButton {
        background-color: #ffffff;
        color: #172033;
        border: 1px solid #b8c3d4;
        border-radius: 5px;
        padding: 6px 14px;
        min-height: 24px;
        font-weight: 600;
    }
    QPushButton:hover {
        background-color: #eef4ff;
        border-color: #2563eb;
    }
    QPushButton:pressed {
        background-color: #d6e6ff;
        border-color: #1d4ed8;
    }
    QPushButton:disabled {
        background-color: #eef1f5;
        color: #8b95a5;
        border-color: #d6dde8;
    }
    QPushButton#primaryButton, QPushButton#adePrimaryButton {
        background-color: #2563eb;
        color: #ffffff;
        border-color: #1d4ed8;
    }
    QPushButton#primaryButton:hover, QPushButton#adePrimaryButton:hover {
        background-color: #1d4ed8;
        border-color: #1e40af;
    }
    QLabel { color: #1f2937; background: transparent; }
    QGroupBox {
        border: 1px solid #d8dee9;
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 16px;
    }
    QGroupBox::title { color: #2563eb; left: 12px; padding: 0 4px; }
    QStatusBar { background-color: #2563eb; color: #ffffff; }
    QScrollBar:vertical, QScrollBar:horizontal { background-color: #f6f7fb; }
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
        background-color: #c6ceda;
        border-radius: 5px;
    }
    QToolTip {
        background-color: #ffffff;
        color: #1f2937;
        border: 1px solid #cfd6e4;
    }
    """
