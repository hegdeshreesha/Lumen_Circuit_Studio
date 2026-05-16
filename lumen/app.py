"""
Lumen Circuit Studio - Application Bootstrap
"""
import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from lumen.gui.branding import app_icon
from lumen.gui.theme import apply_theme, get_stylesheet


def main():
    """Main entry point for Lumen Circuit Studio."""
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("Lumen Circuit Studio")
    app.setOrganizationName("LumenEDA")
    app.setApplicationVersion("0.3.0")
    app.setWindowIcon(app_icon())
    app.setFont(QFont("Segoe UI", 9))

    apply_theme(app)

    from lumen.gui.ciw_window import CIWWindow
    ciw = CIWWindow()
    ciw.show()
    ciw.open_library_manager()

    return app.exec()


def _get_stylesheet() -> str:
    """Compatibility wrapper for callers that still request the dark stylesheet."""
    return get_stylesheet("dark")


if __name__ == "__main__":
    sys.exit(main())
