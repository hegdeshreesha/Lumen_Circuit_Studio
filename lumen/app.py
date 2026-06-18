"""
Lumen Circuit Studio - Application Bootstrap
"""
import sys
import os
from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtGui import QFont, QPixmap, QColor, QPainter
from PyQt6.QtCore import Qt, QTimer
from lumen.gui.branding import app_icon, logo_path
from lumen.gui.theme import apply_theme, get_stylesheet


def _set_windows_app_user_model_id():
    """Ensure Windows taskbar uses Lumen identity/icon instead of python.exe."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        app_id = "LumenCircuitStudio.APW.0_5"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        # Non-fatal: window/app icons are still set via Qt branding.
        pass


def main():
    """Main entry point for Lumen Circuit Studio."""
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    _set_windows_app_user_model_id()

    app = QApplication(sys.argv)
    app.setApplicationName("Lumen Circuit Studio")
    app.setOrganizationName("LumenEDA")
    app.setApplicationVersion("0.5.0")
    app.setWindowIcon(app_icon())
    app.setFont(QFont("Segoe UI", 9))

    logo_pix = QPixmap(logo_path())
    splash_pix = QPixmap(560, 300)
    splash_pix.fill(QColor("#ffffff"))
    if not logo_pix.isNull():
        logo_scaled = logo_pix.scaledToWidth(360, Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(splash_pix)
        x = (splash_pix.width() - logo_scaled.width()) // 2
        y = max(20, (splash_pix.height() - logo_scaled.height()) // 2 - 24)
        painter.drawPixmap(x, y, logo_scaled)
        painter.end()
    splash = QSplashScreen(splash_pix)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.show()

    def update_splash(status: str):
        splash.showMessage(
            f"  {status}",
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
            QColor("#1f3555"),
        )
        app.processEvents()

    update_splash("Starting Lumen Circuit Studio...")
    apply_theme(app)
    update_splash("Theme loaded")

    from lumen.gui.apw_window import APWWindow
    apw = APWWindow(startup_status=update_splash)
    apw.show()

    def _handoff_to_apw():
        # Make APW the active top-level window and force splash dismissal.
        try:
            apw.showNormal()
            apw.raise_()
            apw.activateWindow()
        except Exception:
            pass
        try:
            splash.finish(apw)
        except Exception:
            pass
        splash.close()
        app.processEvents()
        QTimer.singleShot(50, apw.open_library_manager)

    QTimer.singleShot(0, _handoff_to_apw)

    return app.exec()


def _get_stylesheet() -> str:
    """Compatibility wrapper for callers that still request the dark stylesheet."""
    return get_stylesheet("dark")


if __name__ == "__main__":
    sys.exit(main())
