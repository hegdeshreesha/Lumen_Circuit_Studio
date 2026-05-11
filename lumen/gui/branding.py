"""Shared branding assets for Lumen Circuit Studio."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QLabel


LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


def logo_path() -> str:
    """Return the absolute path to the application logo asset."""
    return str(LOGO_PATH)


def logo_url() -> str:
    """Return a file URL suitable for Qt rich-text image tags."""
    return LOGO_PATH.as_uri()


def app_icon() -> QIcon:
    """Return the logo as a window/application icon."""
    return QIcon(logo_path())


def apply_window_branding(window) -> None:
    """Apply the shared logo to a top-level window title bar."""
    window.setWindowIcon(app_icon())


def logo_label(width: int = 260, parent=None) -> QLabel:
    """Create a QLabel that displays the shared logo scaled to width."""
    label = QLabel(parent)
    pixmap = QPixmap(logo_path())
    if not pixmap.isNull():
        label.setPixmap(
            pixmap.scaledToWidth(
                width,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("background: transparent;")
    return label
