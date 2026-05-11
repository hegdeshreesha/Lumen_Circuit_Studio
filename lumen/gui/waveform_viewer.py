"""
Lumen Circuit Studio — Waveform Viewer Window

Displays simulation results as interactive waveform plots.
Supports multiple traces, zoom, pan, cursors, and measurements.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QStatusBar, QLabel, QToolBar,
    QCheckBox
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QSize
from PyQt6.QtGui import (
    QAction, QPainter, QPen, QBrush, QColor, QFont,
    QPainterPath, QWheelEvent
)
from lumen.gui.branding import apply_window_branding

import math


class WaveformCanvas(QWidget):
    """Custom widget for drawing waveform plots."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)

        # Data: list of (name, color, x_data, y_data)
        self.traces: list[tuple[str, QColor, list, list]] = []
        self.visible_traces: set[str] = set()

        # View state
        self.x_min = 0.0
        self.x_max = 1.0
        self.y_min = -1.0
        self.y_max = 1.0
        self._auto_range = True

        # Cursor
        self.cursor_x: float | None = None
        self.cursor_y: float | None = None

        # Interaction
        self._panning = False
        self._pan_start = QPointF()
        self._pan_x_start = 0.0
        self._pan_y_start = 0.0

        self.setMouseTracking(True)

    # ── Trace Management ──────────────────────────────────────

    TRACE_COLORS = [
        QColor("#6b9ece"),  # Steel blue
        QColor("#8bc78b"),  # Soft green
        QColor("#cc8888"),  # Muted red
        QColor("#c4a45c"),  # Gold
        QColor("#aa88cc"),  # Lavender
        QColor("#6bccc0"),  # Teal
        QColor("#cc99b8"),  # Pink
        QColor("#88aacc"),  # Light blue
    ]

    def add_trace(self, name: str, x_data: list, y_data: list,
                  color: QColor = None):
        """Add a waveform trace."""
        if color is None:
            idx = len(self.traces) % len(self.TRACE_COLORS)
            color = self.TRACE_COLORS[idx]
        self.traces.append((name, color, x_data, y_data))
        self.visible_traces.add(name)
        if self._auto_range:
            self._compute_auto_range()
        self.update()

    def clear_traces(self):
        self.traces.clear()
        self.visible_traces.clear()
        self.update()

    def set_trace_visible(self, name: str, visible: bool):
        if visible:
            self.visible_traces.add(name)
        else:
            self.visible_traces.discard(name)
        self.update()

    def _compute_auto_range(self):
        """Auto-fit the view to all visible data."""
        x_vals, y_vals = [], []
        for name, _, xd, yd in self.traces:
            if name in self.visible_traces and xd and yd:
                x_vals.extend(xd)
                y_vals.extend(yd)
        if x_vals:
            self.x_min = min(x_vals)
            self.x_max = max(x_vals)
            margin = (self.x_max - self.x_min) * 0.05 or 0.1
            self.x_min -= margin
            self.x_max += margin
        if y_vals:
            self.y_min = min(y_vals)
            self.y_max = max(y_vals)
            margin = (self.y_max - self.y_min) * 0.1 or 0.1
            self.y_min -= margin
            self.y_max += margin

    # ── Coordinate Mapping ────────────────────────────────────

    def _plot_rect(self) -> QRectF:
        """The rectangle available for plotting (inside margins)."""
        m = 60  # margin
        return QRectF(m, 10, self.width() - m - 20, self.height() - m - 10)

    def _data_to_screen(self, x: float, y: float) -> QPointF:
        r = self._plot_rect()
        x_range = self.x_max - self.x_min
        y_range = self.y_max - self.y_min
        sx = r.left() + (x - self.x_min) / (x_range or 1) * r.width()
        sy = r.bottom() - (y - self.y_min) / (y_range or 1) * r.height()
        return QPointF(sx, sy)

    def _screen_to_data(self, sx: float, sy: float) -> tuple[float, float]:
        r = self._plot_rect()
        x_range = self.x_max - self.x_min
        y_range = self.y_max - self.y_min
        x = self.x_min + (sx - r.left()) / (r.width() or 1) * x_range
        y = self.y_min + (r.bottom() - sy) / (r.height() or 1) * y_range
        return x, y

    # ── Paint ─────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        p.fillRect(self.rect(), QColor("#1a1a1a"))

        r = self._plot_rect()

        # Grid
        self._draw_grid(p, r)

        # Axes
        p.setPen(QPen(QColor("#4d4d4d"), 1))
        p.drawRect(r.toRect())

        # Traces
        for name, color, xd, yd in self.traces:
            if name not in self.visible_traces:
                continue
            if len(xd) < 2:
                continue
            pen = QPen(color, 2)
            pen.setCosmetic(True)
            p.setPen(pen)

            path = QPainterPath()
            pt = self._data_to_screen(xd[0], yd[0])
            path.moveTo(pt)
            for i in range(1, len(xd)):
                pt = self._data_to_screen(xd[i], yd[i])
                path.lineTo(pt)
            p.drawPath(path)

        # Cursor
        if self.cursor_x is not None:
            p.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DashLine))
            sx = self._data_to_screen(self.cursor_x, 0).x()
            if r.left() <= sx <= r.right():
                p.drawLine(int(sx), int(r.top()), int(sx), int(r.bottom()))

        # Axis labels
        self._draw_axis_labels(p, r)

        p.end()

    def _draw_grid(self, p: QPainter, r: QRectF):
        """Draw grid lines."""
        p.setPen(QPen(QColor("#2a2a2a"), 1))

        # Horizontal grid (Y axis)
        n_y = 5
        y_range = self.y_max - self.y_min
        for i in range(n_y + 1):
            y = self.y_min + i * y_range / n_y
            pt = self._data_to_screen(self.x_min, y)
            p.drawLine(int(r.left()), int(pt.y()), int(r.right()), int(pt.y()))

        # Vertical grid (X axis)
        n_x = 8
        x_range = self.x_max - self.x_min
        for i in range(n_x + 1):
            x = self.x_min + i * x_range / n_x
            pt = self._data_to_screen(x, self.y_min)
            p.drawLine(int(pt.x()), int(r.top()), int(pt.x()), int(r.bottom()))

    def _draw_axis_labels(self, p: QPainter, r: QRectF):
        """Draw axis tick labels."""
        font = QFont("Consolas", 8)
        p.setFont(font)
        p.setPen(QPen(QColor("#808080"), 1))

        # Y axis labels
        n_y = 5
        y_range = self.y_max - self.y_min
        for i in range(n_y + 1):
            y = self.y_min + i * y_range / n_y
            pt = self._data_to_screen(self.x_min, y)
            label = self._format_value(y)
            p.drawText(int(r.left() - 55), int(pt.y() + 4), label)

        # X axis labels
        n_x = 8
        x_range = self.x_max - self.x_min
        for i in range(n_x + 1):
            x = self.x_min + i * x_range / n_x
            pt = self._data_to_screen(x, self.y_min)
            label = self._format_value(x)
            p.drawText(int(pt.x() - 20), int(r.bottom() + 15), label)

    @staticmethod
    def _format_value(val: float) -> str:
        """Format a value with SI prefix."""
        if val == 0:
            return "0"
        abs_val = abs(val)
        prefixes = [
            (1e-15, "f"), (1e-12, "p"), (1e-9, "n"), (1e-6, "µ"),
            (1e-3, "m"), (1, ""), (1e3, "k"), (1e6, "M"), (1e9, "G")
        ]
        for scale, prefix in prefixes:
            if abs_val < scale * 1000:
                return f"{val/scale:.2f}{prefix}"
        return f"{val:.2e}"

    # ── Mouse Interaction ─────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent):
        """Zoom with scroll wheel."""
        self._auto_range = False
        factor = 0.85 if event.angleDelta().y() > 0 else 1.0 / 0.85

        # Zoom centered on mouse position
        mx, my = self._screen_to_data(
            event.position().x(), event.position().y())

        self.x_min = mx + (self.x_min - mx) * factor
        self.x_max = mx + (self.x_max - mx) * factor
        self.y_min = my + (self.y_min - my) * factor
        self.y_max = my + (self.y_max - my) * factor
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self._pan_x_start = self.x_min
            self._pan_y_start = self.y_min
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.LeftButton:
            # Place cursor
            x, y = self._screen_to_data(
                event.position().x(), event.position().y())
            self.cursor_x = x
            self.cursor_y = y
            self.update()

    def mouseMoveEvent(self, event):
        if self._panning:
            dx_px = event.position().x() - self._pan_start.x()
            dy_px = event.position().y() - self._pan_start.y()
            r = self._plot_rect()
            x_range = self.x_max - self.x_min
            y_range = self.y_max - self.y_min
            dx = -dx_px / (r.width() or 1) * x_range
            dy = dy_px / (r.height() or 1) * y_range
            self.x_min = self._pan_x_start + dx
            self.x_max = self.x_min + x_range
            self.y_min = self._pan_y_start + dy
            self.y_max = self.y_min + y_range
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        """Double-click to auto-fit."""
        self._auto_range = True
        self._compute_auto_range()
        self.update()


class WaveformViewerWindow(QMainWindow):
    """Standalone waveform viewer window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lumen — Waveform Viewer")
        apply_window_branding(self)
        self.setMinimumSize(800, 500)
        self.resize(1100, 650)

        self._build_ui()
        self._create_toolbar()
        self._create_status_bar()

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Signal list (left panel)
        signal_panel = QWidget()
        sig_layout = QVBoxLayout(signal_panel)
        sig_layout.setContentsMargins(4, 4, 4, 4)

        sig_header = QLabel("Signals")
        sig_header.setStyleSheet("""
            font-weight: bold; color: #6b9ece;
            padding: 4px; background: transparent;
        """)
        sig_layout.addWidget(sig_header)

        self.signal_list = QListWidget()
        self.signal_list.setMinimumWidth(180)
        sig_layout.addWidget(self.signal_list)
        splitter.addWidget(signal_panel)

        # Waveform canvas (right)
        self.canvas = WaveformCanvas()
        splitter.addWidget(self.canvas)

        splitter.setSizes([200, 800])

    def _create_toolbar(self):
        tb = QToolBar("Waveform")
        tb.setIconSize(QSize(18, 18))

        act_fit = QAction("Fit All", self)
        act_fit.triggered.connect(self._on_fit)
        tb.addAction(act_fit)

        act_clear = QAction("Clear", self)
        act_clear.triggered.connect(self._on_clear)
        tb.addAction(act_clear)

        self.addToolBar(tb)

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

    def load_results(self, waveforms: dict, x_var: str = ""):
        """Load simulation waveforms into the viewer.

        Args:
            waveforms: Dict of signal_name -> list of values
            x_var: Name of the X-axis variable (e.g., "time", "frequency")
        """
        self.canvas.clear_traces()
        self.signal_list.clear()

        if not waveforms:
            return

        # Detect X-axis variable
        if not x_var:
            for candidate in ["time", "frequency", "v-sweep", "sweep"]:
                if candidate in waveforms:
                    x_var = candidate
                    break
            if not x_var:
                x_var = list(waveforms.keys())[0]

        x_data = waveforms.get(x_var, [])

        for name, y_data in waveforms.items():
            if name == x_var or name.startswith("_"):
                continue
            if not y_data or not x_data:
                continue
            if len(y_data) != len(x_data):
                continue

            self.canvas.add_trace(name, x_data, y_data)

            # Add to signal list
            item = QListWidgetItem(name)
            item.setCheckState(Qt.CheckState.Checked)
            self.signal_list.addItem(item)

        self.signal_list.itemChanged.connect(self._on_signal_toggled)
        self.setWindowTitle(f"Lumen — Waveform Viewer ({len(self.canvas.traces)} signals)")

    def _on_signal_toggled(self, item: QListWidgetItem):
        name = item.text()
        visible = item.checkState() == Qt.CheckState.Checked
        self.canvas.set_trace_visible(name, visible)

    def _on_fit(self):
        self.canvas._auto_range = True
        self.canvas._compute_auto_range()
        self.canvas.update()

    def _on_clear(self):
        self.canvas.clear_traces()
        self.signal_list.clear()
