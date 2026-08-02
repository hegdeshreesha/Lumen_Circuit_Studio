"""Qt binding compatibility layer."""

QT_BINDING = ""

try:
    import PySide6  # noqa: F401
except ImportError as exc:
    raise ImportError("Install PySide6 to run the Lumen GUI.") from exc

QT_BINDING = "PySide6"
