"""
Lumen Circuit Studio - SigView Window

Interactive waveform plotting window with:
- Signal search/filter and visibility management
- Overlay and stacked display modes
- Smooth zoom/pan
- Dual cursors (A/B) with delta readout
- CSV export for visible traces
"""

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
import csv
import json
import math
from pathlib import Path

from PyQt6.QtCore import Qt, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QPainter,
    QPen,
    QColor,
    QFont,
    QPainterPath,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QStatusBar,
    QLabel,
    QToolBar,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QAbstractItemView,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QComboBox,
)

from lumen.gui.branding import apply_window_branding
from lumen.gui.icons import editor_icon
from lumen.core.simulator import SimulatorBridge


@dataclass
class TraceRecord:
    name: str
    color: QColor
    x_data: list[float]
    y_data: list[float]
    visible: bool = True
    source: str = ""


@dataclass
class MarkerRecord:
    name: str
    x: float
    color: QColor


class WaveformCanvas(QWidget):
    """Custom widget for high-performance waveform drawing."""

    hover_text_changed = pyqtSignal(str)
    cursor_text_changed = pyqtSignal(str)

    TRACE_COLORS = [
        QColor("#56b6c2"),
        QColor("#98c379"),
        QColor("#e06c75"),
        QColor("#e5c07b"),
        QColor("#c678dd"),
        QColor("#61afef"),
        QColor("#d19a66"),
        QColor("#8be9fd"),
        QColor("#f1fa8c"),
        QColor("#ff79c6"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(500, 340)
        self.setMouseTracking(True)

        self.traces: list[TraceRecord] = []
        self._trace_by_name: dict[str, TraceRecord] = {}
        self.markers: list[MarkerRecord] = []
        self.selected_trace_name = ""

        self.x_label = "X"
        self.y_label = "Y"
        self.show_grid = True
        self.stacked_mode = False

        self.x_min = 0.0
        self.x_max = 1.0
        self.y_min = -1.0
        self.y_max = 1.0
        self._auto_range = True

        self.cursor_a_x: float | None = None
        self.cursor_b_x: float | None = None
        self.active_cursor = "A"
        self._hover_x: float | None = None
        self._hover_y: float | None = None

        self._panning = False
        self._pan_start = QPointF()
        self._pan_x_start = 0.0
        self._pan_y_start = 0.0

    # ----- Trace management -----

    def add_trace(self, name: str, x_data: list[float], y_data: list[float],
                  color: QColor | None = None, source: str = ""):
        if color is None:
            idx = len(self.traces) % len(self.TRACE_COLORS)
            color = self.TRACE_COLORS[idx]
        record = TraceRecord(name=name, color=color, x_data=x_data, y_data=y_data, visible=True, source=source)
        self.traces.append(record)
        self._trace_by_name[name] = record
        if self._auto_range:
            self._compute_auto_range()
        self.update()

    def clear_traces(self):
        self.traces.clear()
        self._trace_by_name.clear()
        self.markers.clear()
        self.selected_trace_name = ""
        self.cursor_a_x = None
        self.cursor_b_x = None
        self._hover_x = None
        self._hover_y = None
        self.update()
        self.cursor_text_changed.emit("")
        self.hover_text_changed.emit("")

    def set_trace_visible(self, name: str, visible: bool):
        trace = self._trace_by_name.get(name)
        if not trace:
            return
        trace.visible = visible
        if self._auto_range:
            self._compute_auto_range()
        self.update()
        self._emit_cursor_text()

    def get_trace_names(self) -> list[str]:
        return [t.name for t in self.traces]

    def get_visible_trace_names(self) -> list[str]:
        return [t.name for t in self.traces if t.visible]

    def set_selected_trace(self, name: str):
        self.selected_trace_name = name if name in self._trace_by_name else ""
        self.update()

    def remove_trace(self, name: str):
        trace = self._trace_by_name.pop(name, None)
        if not trace:
            return
        self.traces = [t for t in self.traces if t.name != name]
        if self.selected_trace_name == name:
            self.selected_trace_name = ""
        if self._auto_range:
            self._compute_auto_range()
        self.update()
        self._emit_cursor_text()

    def add_marker(self, name: str, x: float, color: QColor | None = None):
        if color is None:
            color = QColor("#ffd166")
        self.markers.append(MarkerRecord(name=name, x=float(x), color=color))
        self.update()

    def clear_markers(self):
        self.markers.clear()
        self.update()

    def set_stacked_mode(self, enabled: bool):
        self.stacked_mode = bool(enabled)
        if self._auto_range:
            self._compute_auto_range()
        self.update()
        self._emit_cursor_text()

    def set_grid_visible(self, enabled: bool):
        self.show_grid = bool(enabled)
        self.update()

    # ----- View / ranges -----

    def fit_all(self):
        self._auto_range = True
        self._compute_auto_range()
        self.update()
        self._emit_cursor_text()

    def fit_x(self):
        x_vals: list[float] = []
        for t in self.traces:
            if t.visible and t.x_data:
                x_vals.extend(t.x_data)
        if not x_vals:
            return
        self._auto_range = False
        self.x_min = min(x_vals)
        self.x_max = max(x_vals)
        margin = (self.x_max - self.x_min) * 0.03 or 0.1
        self.x_min -= margin
        self.x_max += margin
        self.update()

    def fit_y(self):
        if self.stacked_mode:
            self.update()
            return
        y_vals: list[float] = []
        for t in self.traces:
            if t.visible and t.y_data:
                y_vals.extend(v for v in t.y_data if isinstance(v, (int, float)) and math.isfinite(v))
        if not y_vals:
            return
        self._auto_range = False
        self.y_min = min(y_vals)
        self.y_max = max(y_vals)
        margin = (self.y_max - self.y_min) * 0.08 or 0.1
        self.y_min -= margin
        self.y_max += margin
        self.update()

    def _compute_auto_range(self):
        x_vals: list[float] = []
        y_vals: list[float] = []
        for trace in self.traces:
            if not trace.visible:
                continue
            if trace.x_data and trace.y_data:
                x_vals.extend(trace.x_data)
                if not self.stacked_mode:
                    y_vals.extend(v for v in trace.y_data if isinstance(v, (int, float)) and math.isfinite(v))

        if x_vals:
            self.x_min = min(x_vals)
            self.x_max = max(x_vals)
            x_margin = (self.x_max - self.x_min) * 0.03 or 0.1
            self.x_min -= x_margin
            self.x_max += x_margin

        if self.stacked_mode:
            self.y_min = 0.0
            self.y_max = float(max(len(self.get_visible_trace_names()), 1))
            return

        if y_vals:
            self.y_min = min(y_vals)
            self.y_max = max(y_vals)
            y_margin = (self.y_max - self.y_min) * 0.08 or 0.1
            self.y_min -= y_margin
            self.y_max += y_margin

    def _plot_rect(self) -> QRectF:
        left = 78
        top = 14
        right = 20
        bottom = 48
        return QRectF(left, top, max(60, self.width() - left - right), max(60, self.height() - top - bottom))

    def _data_to_screen(self, x: float, y: float, lane_rect: QRectF | None = None, y_min: float | None = None, y_max: float | None = None) -> QPointF:
        rect = lane_rect if lane_rect is not None else self._plot_rect()
        xmin, xmax = self.x_min, self.x_max
        ymin = self.y_min if y_min is None else y_min
        ymax = self.y_max if y_max is None else y_max
        sx = rect.left() + ((x - xmin) / ((xmax - xmin) or 1.0)) * rect.width()
        sy = rect.bottom() - ((y - ymin) / ((ymax - ymin) or 1.0)) * rect.height()
        return QPointF(sx, sy)

    def _screen_to_data(self, sx: float, sy: float) -> tuple[float, float]:
        rect = self._plot_rect()
        x = self.x_min + ((sx - rect.left()) / (rect.width() or 1.0)) * (self.x_max - self.x_min)
        y = self.y_min + ((rect.bottom() - sy) / (rect.height() or 1.0)) * (self.y_max - self.y_min)
        return x, y

    # ----- Cursor helpers -----

    def set_active_cursor(self, cursor_name: str):
        self.active_cursor = "B" if str(cursor_name).upper() == "B" else "A"
        self._emit_cursor_text()

    def clear_cursors(self):
        self.cursor_a_x = None
        self.cursor_b_x = None
        self.update()
        self._emit_cursor_text()

    def get_cursor_value(self, trace_name: str, cursor_name: str) -> float | None:
        x = self.cursor_b_x if str(cursor_name).upper() == "B" else self.cursor_a_x
        trace = self._trace_by_name.get(trace_name)
        if x is None or not trace:
            return None
        return self._interpolate_value(trace.x_data, trace.y_data, x)

    def _interpolate_value(self, x_data: list[float], y_data: list[float], x: float) -> float | None:
        if not x_data or not y_data:
            return None
        n = min(len(x_data), len(y_data))
        if n == 0:
            return None
        if n == 1:
            return y_data[0]

        ascending = x_data[0] <= x_data[n - 1]
        if not ascending:
            x_data = list(reversed(x_data[:n]))
            y_data = list(reversed(y_data[:n]))
        else:
            x_data = x_data[:n]
            y_data = y_data[:n]

        idx = bisect_left(x_data, x)
        if idx <= 0:
            return y_data[0]
        if idx >= n:
            return y_data[-1]

        x0, x1 = x_data[idx - 1], x_data[idx]
        y0, y1 = y_data[idx - 1], y_data[idx]
        if x1 == x0:
            return y0
        t = (x - x0) / (x1 - x0)
        return y0 + (y1 - y0) * t

    def _emit_cursor_text(self):
        if self.cursor_a_x is None and self.cursor_b_x is None:
            self.cursor_text_changed.emit("")
            return

        parts = []
        if self.cursor_a_x is not None:
            parts.append(f"A={self._format_value(self.cursor_a_x)}")
        if self.cursor_b_x is not None:
            parts.append(f"B={self._format_value(self.cursor_b_x)}")
        if self.cursor_a_x is not None and self.cursor_b_x is not None:
            parts.append(f"dX={self._format_value(self.cursor_b_x - self.cursor_a_x)}")
        self.cursor_text_changed.emit(" | ".join(parts))

    # ----- Painting -----

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101317"))

        plot = self._plot_rect()
        painter.setPen(QPen(QColor("#2b323a"), 1))
        painter.drawRect(plot.toRect())

        visible = [t for t in self.traces if t.visible and len(t.x_data) > 0 and len(t.y_data) > 0]
        if not visible:
            self._draw_empty_hint(painter, plot)
            painter.end()
            return

        if self.stacked_mode:
            self._paint_stacked(painter, plot, visible)
        else:
            self._paint_overlay(painter, plot, visible)

        self._draw_cursors(painter, plot)
        self._draw_markers(painter, plot)
        self._draw_axes_text(painter, plot)
        painter.end()

    def _paint_overlay(self, painter: QPainter, plot: QRectF, traces: list[TraceRecord]):
        if self.show_grid:
            self._draw_grid(painter, plot, self.x_min, self.x_max, self.y_min, self.y_max)
        for trace in traces:
            self._draw_trace_line(painter, trace, plot, self.y_min, self.y_max)

    def _paint_stacked(self, painter: QPainter, plot: QRectF, traces: list[TraceRecord]):
        count = len(traces)
        lane_h = plot.height() / max(count, 1)
        for idx, trace in enumerate(traces):
            top = plot.top() + idx * lane_h
            lane = QRectF(plot.left(), top, plot.width(), lane_h)

            finite_y = [v for v in trace.y_data if isinstance(v, (int, float)) and math.isfinite(v)]
            if not finite_y:
                continue
            y0 = min(finite_y)
            y1 = max(finite_y)
            margin = (y1 - y0) * 0.08 or 0.1
            y0 -= margin
            y1 += margin

            if self.show_grid:
                self._draw_grid(painter, lane, self.x_min, self.x_max, y0, y1, light=True)

            self._draw_trace_line(painter, trace, lane, y0, y1)
            painter.setPen(QPen(QColor("#8f9daa"), 1))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(int(lane.left() + 6), int(lane.top() + 14), trace.name)

            painter.setPen(QPen(QColor("#2b323a"), 1))
            painter.drawLine(int(lane.left()), int(lane.bottom()), int(lane.right()), int(lane.bottom()))

    def _draw_trace_line(self, painter: QPainter, trace: TraceRecord, rect: QRectF, y_min: float, y_max: float):
        width = 2.7 if trace.name == self.selected_trace_name else 1.8
        pen = QPen(trace.color, width)
        pen.setCosmetic(True)
        painter.setPen(pen)

        x_data = trace.x_data
        y_data = trace.y_data
        n = min(len(x_data), len(y_data))
        if n < 1:
            return
        if n == 1:
            xv = x_data[0]
            yv = y_data[0]
            if isinstance(xv, (int, float)) and isinstance(yv, (int, float)) and math.isfinite(xv) and math.isfinite(yv):
                pp = self._data_to_screen(xv, yv, lane_rect=rect, y_min=y_min, y_max=y_max)
                painter.drawEllipse(pp, 4.0, 4.0)
            return

        stride = max(1, int(n / max(2000, int(rect.width()) * 2)))
        path = QPainterPath()
        started = False
        idx = 0
        while idx < n:
            xv = x_data[idx]
            yv = y_data[idx]
            if isinstance(xv, (int, float)) and isinstance(yv, (int, float)) and math.isfinite(xv) and math.isfinite(yv):
                pp = self._data_to_screen(xv, yv, lane_rect=rect, y_min=y_min, y_max=y_max)
                if not started:
                    path.moveTo(pp)
                    started = True
                else:
                    path.lineTo(pp)
            else:
                started = False
            idx += stride

        if not path.isEmpty():
            plast_x = x_data[n - 1]
            plast_y = y_data[n - 1]
            if isinstance(plast_x, (int, float)) and isinstance(plast_y, (int, float)) and math.isfinite(plast_x) and math.isfinite(plast_y):
                path.lineTo(self._data_to_screen(plast_x, plast_y, lane_rect=rect, y_min=y_min, y_max=y_max))
        painter.drawPath(path)

    def _draw_grid(self, painter: QPainter, rect: QRectF, x0: float, x1: float, y0: float, y1: float, light: bool = False):
        grid_color = QColor("#232a31" if light else "#2a3038")
        tick_x = self._nice_ticks(x0, x1, 9)
        tick_y = self._nice_ticks(y0, y1, 6)

        painter.setPen(QPen(grid_color, 1))
        for xv in tick_x:
            sx = self._data_to_screen(xv, y0, lane_rect=rect, y_min=y0, y_max=y1).x()
            painter.drawLine(int(sx), int(rect.top()), int(sx), int(rect.bottom()))

        for yv in tick_y:
            sy = self._data_to_screen(x0, yv, lane_rect=rect, y_min=y0, y_max=y1).y()
            painter.drawLine(int(rect.left()), int(sy), int(rect.right()), int(sy))

    def _draw_axes_text(self, painter: QPainter, plot: QRectF):
        painter.setPen(QPen(QColor("#9aa6b2"), 1))
        painter.setFont(QFont("Consolas", 8))

        x_ticks = self._nice_ticks(self.x_min, self.x_max, 9)
        for xv in x_ticks:
            sx = self._data_to_screen(xv, self.y_min).x()
            painter.drawText(int(sx - 20), int(plot.bottom() + 18), self._format_value(xv))

        if not self.stacked_mode:
            y_ticks = self._nice_ticks(self.y_min, self.y_max, 6)
            for yv in y_ticks:
                sy = self._data_to_screen(self.x_min, yv).y()
                painter.drawText(int(plot.left() - 68), int(sy + 4), self._format_value(yv))

        painter.setFont(QFont("Consolas", 9))
        painter.drawText(int(plot.right() - 65), int(plot.bottom() + 36), self.x_label)
        if not self.stacked_mode:
            painter.drawText(int(plot.left() - 60), int(plot.top() - 2), self.y_label)

    def _draw_cursors(self, painter: QPainter, plot: QRectF):
        for cursor_name, x_value, color in (
            ("A", self.cursor_a_x, QColor("#ffb86c")),
            ("B", self.cursor_b_x, QColor("#50fa7b")),
        ):
            if x_value is None:
                continue
            sx = self._data_to_screen(x_value, 0.0).x()
            if not (plot.left() <= sx <= plot.right()):
                continue
            painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(sx), int(plot.top()), int(sx), int(plot.bottom()))
            painter.setPen(QPen(color, 1))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(int(sx + 4), int(plot.top() + (12 if cursor_name == "A" else 24)), cursor_name)

    def _draw_markers(self, painter: QPainter, plot: QRectF):
        for marker in self.markers:
            sx = self._data_to_screen(marker.x, 0.0).x()
            if not (plot.left() <= sx <= plot.right()):
                continue
            painter.setPen(QPen(marker.color, 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(sx), int(plot.top()), int(sx), int(plot.bottom()))
            painter.setPen(QPen(marker.color, 1))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(int(sx + 4), int(plot.bottom() - 8), marker.name)

    def _draw_empty_hint(self, painter: QPainter, plot: QRectF):
        painter.setPen(QPen(QColor("#617284"), 1))
        painter.setFont(QFont("Consolas", 10))
        painter.drawText(plot.toRect(), Qt.AlignmentFlag.AlignCenter, "No visible waveforms")

    @staticmethod
    def _nice_ticks(vmin: float, vmax: float, target_count: int) -> list[float]:
        if vmax <= vmin:
            return [vmin]
        span = vmax - vmin
        raw_step = span / max(target_count, 1)
        mag = 10 ** int(f"{raw_step:e}".split("e")[1])
        options = (1.0, 2.0, 5.0, 10.0)
        step = options[-1] * mag
        for opt in options:
            candidate = opt * mag
            if raw_step <= candidate:
                step = candidate
                break
        first = (vmin // step) * step
        ticks = []
        x = first
        limit = vmax + step * 0.5
        guard = 0
        while x <= limit and guard < 1000:
            if x >= vmin - step * 0.5:
                ticks.append(float(x))
            x += step
            guard += 1
        return ticks

    @staticmethod
    def _format_value(val: float) -> str:
        if val == 0:
            return "0"
        abs_val = abs(val)
        units = [
            (1e-12, "p"),
            (1e-9, "n"),
            (1e-6, "u"),
            (1e-3, "m"),
            (1.0, ""),
            (1e3, "k"),
            (1e6, "M"),
            (1e9, "G"),
        ]
        for scale, prefix in units:
            if abs_val < scale * 1000:
                return f"{val / scale:.4g}{prefix}"
        return f"{val:.3e}"

    # ----- Mouse interaction -----

    def wheelEvent(self, event: QWheelEvent):
        if not self.traces:
            return
        self._auto_range = False

        factor = 0.86 if event.angleDelta().y() > 0 else 1.0 / 0.86
        mx, my = self._screen_to_data(event.position().x(), event.position().y())
        shift_zoom_y_only = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if not shift_zoom_y_only:
            self.x_min = mx + (self.x_min - mx) * factor
            self.x_max = mx + (self.x_max - mx) * factor

        if not self.stacked_mode:
            self.y_min = my + (self.y_min - my) * factor
            self.y_max = my + (self.y_max - my) * factor

        self.update()
        self._emit_cursor_text()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self._pan_x_start = self.x_min
            self._pan_y_start = self.y_min
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            x, _ = self._screen_to_data(event.position().x(), event.position().y())
            if self.active_cursor == "B" or (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self.cursor_b_x = x
            else:
                self.cursor_a_x = x
            self.update()
            self._emit_cursor_text()

    def mouseMoveEvent(self, event):
        sx = event.position().x()
        sy = event.position().y()
        x, y = self._screen_to_data(sx, sy)
        self._hover_x = x
        self._hover_y = y
        self.hover_text_changed.emit(f"x={self._format_value(x)} y={self._format_value(y)}")

        if self._panning:
            dx_px = sx - self._pan_start.x()
            dy_px = sy - self._pan_start.y()
            rect = self._plot_rect()
            x_range = self.x_max - self.x_min
            y_range = self.y_max - self.y_min
            self.x_min = self._pan_x_start - (dx_px / (rect.width() or 1.0)) * x_range
            self.x_max = self.x_min + x_range
            if not self.stacked_mode:
                self.y_min = self._pan_y_start + (dy_px / (rect.height() or 1.0)) * y_range
                self.y_max = self.y_min + y_range
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, _event):
        self.fit_all()


class WaveformViewerWindow(QMainWindow):
    """Standalone SigView waveform window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lumen - SigView")
        apply_window_branding(self)
        self.setMinimumSize(980, 620)
        self.resize(1260, 760)

        self._x_var = ""
        self._last_waveforms: dict[str, list[float]] = {}
        self._building_signal_list = False

        self._build_ui()
        self._create_menus()
        self._create_toolbar()
        self._create_status_bar()

    # ----- UI setup -----

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(6)

        title = QLabel("Signals")
        title.setStyleSheet("font-weight: 600; color: #6aa8c9;")
        left_layout.addWidget(title)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter signals...")
        self.search_edit.textChanged.connect(self._on_filter_changed)
        left_layout.addWidget(self.search_edit)

        btn_row = QHBoxLayout()
        self.btn_show_all = QPushButton("Show All")
        self.btn_hide_all = QPushButton("Hide All")
        self.btn_show_all.clicked.connect(self._on_show_all)
        self.btn_hide_all.clicked.connect(self._on_hide_all)
        btn_row.addWidget(self.btn_show_all)
        btn_row.addWidget(self.btn_hide_all)
        left_layout.addLayout(btn_row)

        self.side_tabs = QTabWidget()
        left_layout.addWidget(self.side_tabs, 1)

        signals_tab = QWidget()
        signals_layout = QVBoxLayout(signals_tab)
        signals_layout.setContentsMargins(0, 0, 0, 0)
        signals_layout.setSpacing(6)

        self.signal_list = QListWidget()
        self.signal_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.signal_list.itemChanged.connect(self._on_signal_toggled)
        self.signal_list.currentItemChanged.connect(self._on_current_signal_changed)
        self.signal_list.itemDoubleClicked.connect(self._on_signal_isolate)
        signals_layout.addWidget(self.signal_list, 1)

        self.measure_label = QLabel("")
        self.measure_label.setWordWrap(True)
        self.measure_label.setStyleSheet("color: #9fb3c8; font-family: Consolas; font-size: 11px;")
        signals_layout.addWidget(self.measure_label)
        self.side_tabs.addTab(signals_tab, "Signals")

        measure_tab = QWidget()
        measure_layout = QVBoxLayout(measure_tab)
        measure_layout.setContentsMargins(0, 0, 0, 0)
        self.measure_table = QTableWidget(0, 7)
        self.measure_table.setHorizontalHeaderLabels(["Signal", "A", "B", "dY", "Min", "Max", "Avg"])
        self.measure_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.measure_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.measure_table.verticalHeader().setVisible(False)
        measure_layout.addWidget(self.measure_table)
        self.side_tabs.addTab(measure_tab, "Measurements")

        marker_tab = QWidget()
        marker_layout = QVBoxLayout(marker_tab)
        marker_layout.setContentsMargins(0, 0, 0, 0)
        marker_btn_row = QHBoxLayout()
        self.btn_add_marker = QPushButton("Add")
        self.btn_clear_markers = QPushButton("Clear")
        self.btn_add_marker.clicked.connect(self._on_add_marker)
        self.btn_clear_markers.clicked.connect(self._on_clear_markers)
        marker_btn_row.addWidget(self.btn_add_marker)
        marker_btn_row.addWidget(self.btn_clear_markers)
        marker_layout.addLayout(marker_btn_row)
        self.marker_table = QTableWidget(0, 2)
        self.marker_table.setHorizontalHeaderLabels(["Marker", "X"])
        self.marker_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.marker_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.marker_table.verticalHeader().setVisible(False)
        marker_layout.addWidget(self.marker_table)
        self.side_tabs.addTab(marker_tab, "Markers")

        expr_tab = QWidget()
        expr_layout = QVBoxLayout(expr_tab)
        expr_layout.setContentsMargins(0, 0, 0, 0)
        self.expr_combo = QComboBox()
        self.expr_combo.addItems(["Scale selected", "Offset selected", "Abs selected", "Derivative selected", "A - B", "A + B", "A / B"])
        expr_layout.addWidget(self.expr_combo)
        self.expr_value = QLineEdit()
        self.expr_value.setPlaceholderText("Scale/offset value or new trace name")
        expr_layout.addWidget(self.expr_value)
        self.expr_button = QPushButton("Create Trace")
        self.expr_button.clicked.connect(self._on_create_expression_trace)
        expr_layout.addWidget(self.expr_button)
        expr_layout.addStretch()
        self.side_tabs.addTab(expr_tab, "Expressions")

        splitter.addWidget(left)

        self.canvas = WaveformCanvas()
        self.canvas.hover_text_changed.connect(self._on_hover_text)
        self.canvas.cursor_text_changed.connect(self._on_cursor_text)
        splitter.addWidget(self.canvas)
        splitter.setSizes([280, 980])

    def _create_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        act_open = QAction("Open Waveform...", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._on_open_waveform_file)
        file_menu.addAction(act_open)

        act_open_run = QAction("Open Run Folder...", self)
        act_open_run.triggered.connect(self._on_open_run_folder)
        file_menu.addAction(act_open_run)

        act_export = QAction("Export Visible CSV...", self)
        act_export.triggered.connect(self._on_export_visible_csv)
        file_menu.addAction(act_export)

        act_image = QAction("Save Plot Image...", self)
        act_image.triggered.connect(self._on_save_plot_image)
        file_menu.addAction(act_image)

        file_menu.addSeparator()
        act_close = QAction("Close", self)
        act_close.setShortcut("Ctrl+W")
        act_close.triggered.connect(self.close)
        file_menu.addAction(act_close)

        view_menu = self.menuBar().addMenu("&View")
        for text, slot in (
            ("Fit All", self.canvas.fit_all),
            ("Fit X", self.canvas.fit_x),
            ("Fit Y", self.canvas.fit_y),
        ):
            action = QAction(text, self)
            action.triggered.connect(slot)
            view_menu.addAction(action)
        view_menu.addSeparator()
        self.menu_grid = QAction("Grid", self)
        self.menu_grid.setCheckable(True)
        self.menu_grid.setChecked(True)
        self.menu_grid.toggled.connect(self._on_toggle_grid)
        view_menu.addAction(self.menu_grid)
        self.menu_stack = QAction("Stacked", self)
        self.menu_stack.setCheckable(True)
        self.menu_stack.toggled.connect(self._on_toggle_stacked)
        view_menu.addAction(self.menu_stack)

        marker_menu = self.menuBar().addMenu("&Markers")
        act_add_marker = QAction("Add Marker at Active Cursor", self)
        act_add_marker.triggered.connect(self._on_add_marker)
        marker_menu.addAction(act_add_marker)
        act_clear_markers = QAction("Clear Markers", self)
        act_clear_markers.triggered.connect(self._on_clear_markers)
        marker_menu.addAction(act_clear_markers)

    def _create_toolbar(self):
        tb = QToolBar("SigView")
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        act_open = QAction("Open", self)
        act_open.setIcon(editor_icon("open"))
        act_open.triggered.connect(self._on_open_waveform_file)
        tb.addAction(act_open)

        tb.addSeparator()

        act_fit = QAction("Fit All", self)
        act_fit.setIcon(editor_icon("zoom_fit"))
        act_fit.triggered.connect(self.canvas.fit_all)
        tb.addAction(act_fit)

        act_fit_x = QAction("Fit X", self)
        act_fit_x.triggered.connect(self.canvas.fit_x)
        tb.addAction(act_fit_x)

        act_fit_y = QAction("Fit Y", self)
        act_fit_y.triggered.connect(self.canvas.fit_y)
        tb.addAction(act_fit_y)

        tb.addSeparator()

        self.act_grid = QAction("Grid", self)
        self.act_grid.setCheckable(True)
        self.act_grid.setChecked(True)
        self.act_grid.toggled.connect(self._on_toggle_grid)
        tb.addAction(self.act_grid)

        self.act_stack = QAction("Stacked", self)
        self.act_stack.setCheckable(True)
        self.act_stack.setChecked(False)
        self.act_stack.toggled.connect(self._on_toggle_stacked)
        tb.addAction(self.act_stack)

        tb.addSeparator()

        self.act_cursor_a = QAction("Cursor A", self)
        self.act_cursor_a.setCheckable(True)
        self.act_cursor_a.setChecked(True)
        self.act_cursor_a.triggered.connect(lambda: self._set_cursor_mode("A"))
        tb.addAction(self.act_cursor_a)

        self.act_cursor_b = QAction("Cursor B", self)
        self.act_cursor_b.setCheckable(True)
        self.act_cursor_b.setChecked(False)
        self.act_cursor_b.triggered.connect(lambda: self._set_cursor_mode("B"))
        tb.addAction(self.act_cursor_b)

        act_clear_cur = QAction("Clear Cursors", self)
        act_clear_cur.triggered.connect(self.canvas.clear_cursors)
        act_clear_cur.triggered.connect(self._refresh_measurements)
        tb.addAction(act_clear_cur)

        tb.addSeparator()

        act_marker = QAction("Marker", self)
        act_marker.triggered.connect(self._on_add_marker)
        tb.addAction(act_marker)

        act_image = QAction("Image", self)
        act_image.triggered.connect(self._on_save_plot_image)
        tb.addAction(act_image)

        act_export = QAction("Export Visible CSV", self)
        act_export.triggered.connect(self._on_export_visible_csv)
        tb.addAction(act_export)

        tb.addSeparator()

        act_clear = QAction("Clear", self)
        act_clear.triggered.connect(self._on_clear)
        tb.addAction(act_clear)

    def _create_status_bar(self):
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_hover = QLabel("")
        self.status_cursor = QLabel("")
        status.addPermanentWidget(self.status_hover, 1)
        status.addPermanentWidget(self.status_cursor, 1)

    # ----- Data loading -----

    def load_results(self, waveforms: dict, x_var: str = ""):
        self._last_waveforms = dict(waveforms or {})
        self._x_var = self._detect_x_var(self._last_waveforms, x_var)

        self.canvas.clear_traces()
        self._building_signal_list = True
        self.signal_list.clear()
        self._building_signal_list = False
        self.measure_label.setText("")

        if not self._last_waveforms or not self._x_var:
            self.setWindowTitle("Lumen - SigView")
            return

        x_data_raw = self._last_waveforms.get(self._x_var, [])
        loaded_count = 0

        for name in sorted(self._last_waveforms.keys(), key=lambda x: x.lower()):
            if name == self._x_var or name.startswith("_"):
                continue
            y_data_raw = self._last_waveforms.get(name, [])
            x_data, y_data = self._pair_numeric_points(x_data_raw, y_data_raw)
            if len(x_data) < 1 or len(y_data) < 1:
                continue
            self.canvas.add_trace(name, x_data, y_data, source="result")
            loaded_count += 1

        self._rebuild_signal_list()
        self.canvas.x_label = self._x_var
        self.canvas.y_label = "value"
        self.canvas.fit_all()

        self.setWindowTitle(f"Lumen - SigView ({loaded_count} signals)")
        self._refresh_measurements()
        self._refresh_marker_table()

    def _detect_x_var(self, waveforms: dict, x_var: str) -> str:
        if x_var and x_var in waveforms:
            return x_var
        for candidate in ("time", "frequency", "v-sweep", "sweep"):
            if candidate in waveforms:
                return candidate
        keys = [k for k in waveforms.keys() if not str(k).startswith("_")]
        return keys[0] if keys else ""

    @staticmethod
    def _pair_numeric_points(x_data_raw: list, y_data_raw: list) -> tuple[list[float], list[float]]:
        x_out: list[float] = []
        y_out: list[float] = []
        n = min(len(x_data_raw), len(y_data_raw))
        for i in range(n):
            try:
                xv = float(x_data_raw[i])
                yv = float(y_data_raw[i])
            except (TypeError, ValueError):
                continue
            x_out.append(xv)
            y_out.append(yv)
        return x_out, y_out

    def _on_open_waveform_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Waveform",
            str(Path.home()),
            "Waveforms (*.raw *.csv *.json);;Run manifests (*.json);;Raw files (*.raw);;CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            waveforms = self._load_waveform_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open Waveform", f"Could not open waveform file:\n{exc}")
            return
        if not waveforms:
            QMessageBox.warning(self, "Open Waveform", "No waveform data was found in the selected file.")
            return
        self.load_results(waveforms)
        self.statusBar().showMessage(f"Loaded {Path(path).name}", 4000)

    def _on_open_run_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Simulation Run Folder", str(Path.home()))
        if not folder:
            return
        try:
            waveforms = self._load_waveform_folder(folder)
        except Exception as exc:
            QMessageBox.critical(self, "Open Run Folder", f"Could not open simulation run:\n{exc}")
            return
        if not waveforms:
            QMessageBox.warning(self, "Open Run Folder", "No waveform data was found in the selected run folder.")
            return
        self.load_results(waveforms)
        self.statusBar().showMessage(f"Loaded run {Path(folder).name}", 4000)

    def _load_waveform_file(self, path: str) -> dict:
        p = Path(path)
        if p.is_dir():
            return self._load_waveform_folder(str(p))
        suffix = p.suffix.lower()
        if suffix == ".json":
            return self._load_waveform_manifest(str(p))
        if suffix == ".csv":
            return self._parse_csv_waveform(path)
        bridge = SimulatorBridge("GSPICE")
        return bridge._parse_raw(path)

    def _load_waveform_folder(self, folder: str) -> dict:
        root = Path(folder)
        manifest = root / "run_manifest.json"
        if manifest.exists():
            return self._load_waveform_manifest(str(manifest))
        for name in ("waveforms.csv", "waveforms.raw"):
            candidate = root / name
            if candidate.exists():
                return self._load_waveform_file(str(candidate))
        csvs = sorted(root.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if csvs:
            return self._parse_csv_waveform(str(csvs[0]))
        raws = sorted(root.glob("*.raw"), key=lambda p: p.stat().st_mtime, reverse=True)
        if raws:
            bridge = SimulatorBridge("GSPICE")
            return bridge._parse_raw(str(raws[0]))
        return {}

    def _load_waveform_manifest(self, path: str) -> dict:
        manifest_path = Path(path)
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        artifacts = manifest.get("artifacts", {}) if isinstance(manifest, dict) else {}
        candidates = [
            artifacts.get("waveforms", ""),
            artifacts.get("csv", ""),
            artifacts.get("raw", ""),
            manifest.get("output_path", "") if isinstance(manifest, dict) else "",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            p = Path(candidate)
            if not p.is_absolute():
                p = manifest_path.parent / p
            if p.exists() and p != manifest_path:
                return self._load_waveform_file(str(p))
        for name in ("waveforms.csv", "waveforms.raw"):
            candidate = manifest_path.parent / name
            if candidate.exists():
                return self._load_waveform_file(str(candidate))
        return {}

    def _parse_csv_waveform(self, path: str) -> dict:
        with open(path, "r", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            names = [str(h).strip() or f"col{i}" for i, h in enumerate(header)]
            data = {name: [] for name in names}
            for row in reader:
                for i, name in enumerate(names):
                    if i >= len(row):
                        continue
                    try:
                        data[name].append(float(row[i]))
                    except (TypeError, ValueError):
                        data[name].append(row[i])
        return data

    # ----- Signal panel actions -----

    def _rebuild_signal_list(self):
        selected = self.signal_list.currentItem().text() if self.signal_list.currentItem() else ""
        filter_text = self.search_edit.text().strip().lower()

        self._building_signal_list = True
        self.signal_list.clear()
        for trace in self.canvas.traces:
            if filter_text and filter_text not in trace.name.lower():
                continue
            item = QListWidgetItem(trace.name)
            item.setForeground(trace.color)
            item.setCheckState(Qt.CheckState.Checked if trace.visible else Qt.CheckState.Unchecked)
            self.signal_list.addItem(item)
            if trace.name == selected:
                self.signal_list.setCurrentItem(item)
        self._building_signal_list = False

    def _on_filter_changed(self, _text: str):
        self._rebuild_signal_list()

    def _on_show_all(self):
        for trace in self.canvas.traces:
            trace.visible = True
        self._rebuild_signal_list()
        self.canvas.fit_all()
        self._refresh_measurements()

    def _on_hide_all(self):
        for trace in self.canvas.traces:
            trace.visible = False
        self._rebuild_signal_list()
        self.canvas.update()
        self._refresh_measurements()

    def _on_signal_toggled(self, item: QListWidgetItem):
        if self._building_signal_list:
            return
        visible = item.checkState() == Qt.CheckState.Checked
        self.canvas.set_trace_visible(item.text(), visible)
        self._refresh_measurements()

    def _on_current_signal_changed(self, _curr: QListWidgetItem | None, _prev: QListWidgetItem | None):
        self.canvas.set_selected_trace(_curr.text() if _curr else "")
        self._refresh_measurements()

    def _on_signal_isolate(self, item: QListWidgetItem):
        target = item.text()
        for trace in self.canvas.traces:
            trace.visible = trace.name == target
        self._rebuild_signal_list()
        self.canvas.fit_all()
        self._refresh_measurements()

    # ----- Toolbar / cursor actions -----

    def _set_cursor_mode(self, mode: str):
        if mode == "B":
            self.act_cursor_a.setChecked(False)
            self.act_cursor_b.setChecked(True)
        else:
            self.act_cursor_a.setChecked(True)
            self.act_cursor_b.setChecked(False)
        self.canvas.set_active_cursor(mode)

    def _on_toggle_grid(self, checked: bool):
        self.canvas.set_grid_visible(checked)
        if hasattr(self, "menu_grid") and self.menu_grid.isChecked() != checked:
            self.menu_grid.setChecked(checked)
        if hasattr(self, "act_grid") and self.act_grid.isChecked() != checked:
            self.act_grid.setChecked(checked)

    def _on_toggle_stacked(self, checked: bool):
        if hasattr(self, "menu_stack") and self.menu_stack.isChecked() != checked:
            self.menu_stack.setChecked(checked)
        if hasattr(self, "act_stack") and self.act_stack.isChecked() != checked:
            self.act_stack.setChecked(checked)
        self.canvas.set_stacked_mode(checked)
        self.canvas.fit_all()

    def _on_clear(self):
        self._last_waveforms = {}
        self._x_var = ""
        self.canvas.clear_traces()
        self.signal_list.clear()
        self.search_edit.clear()
        self.measure_label.setText("")
        self.measure_table.setRowCount(0)
        self.marker_table.setRowCount(0)
        self.setWindowTitle("Lumen - SigView")

    def _on_add_marker(self):
        x = self.canvas.cursor_b_x if self.canvas.active_cursor == "B" else self.canvas.cursor_a_x
        if x is None:
            x = self.canvas.cursor_a_x if self.canvas.cursor_a_x is not None else self.canvas.cursor_b_x
        if x is None:
            QMessageBox.information(self, "Add Marker", "Place cursor A or B before adding a marker.")
            return
        name = f"M{len(self.canvas.markers) + 1}"
        self.canvas.add_marker(name, x)
        self._refresh_marker_table()

    def _on_clear_markers(self):
        self.canvas.clear_markers()
        self._refresh_marker_table()

    def _refresh_marker_table(self):
        self.marker_table.setRowCount(0)
        for marker in self.canvas.markers:
            r = self.marker_table.rowCount()
            self.marker_table.insertRow(r)
            name_item = QTableWidgetItem(marker.name)
            name_item.setForeground(marker.color)
            self.marker_table.setItem(r, 0, name_item)
            self.marker_table.setItem(r, 1, QTableWidgetItem(self.canvas._format_value(marker.x)))

    def _on_create_expression_trace(self):
        current = self.signal_list.currentItem()
        mode = self.expr_combo.currentText()
        new_name_hint = self.expr_value.text().strip()

        selected = [item.text() for item in self.signal_list.selectedItems()]
        if current and current.text() not in selected:
            selected.insert(0, current.text())

        try:
            trace = self._build_expression_trace(mode, selected, new_name_hint)
        except Exception as exc:
            QMessageBox.warning(self, "Create Trace", str(exc))
            return
        if trace is None:
            return
        name, x_data, y_data = trace
        self.canvas.add_trace(name, x_data, y_data, source="expression")
        self._last_waveforms[name] = list(y_data)
        self._rebuild_signal_list()
        self.canvas.fit_all()
        self._refresh_measurements()

    def _build_expression_trace(self, mode: str, selected: list[str], value_text: str) -> tuple[str, list[float], list[float]] | None:
        if not selected:
            raise ValueError("Select one or two traces first.")
        t0 = self.canvas._trace_by_name.get(selected[0])
        if not t0:
            raise ValueError("Selected trace is not available.")

        def unique_name(base: str) -> str:
            candidate = base
            idx = 2
            while candidate in self.canvas._trace_by_name:
                candidate = f"{base}_{idx}"
                idx += 1
            return candidate

        if mode in ("Scale selected", "Offset selected"):
            try:
                value = float(value_text) if value_text else (1.0 if mode.startswith("Scale") else 0.0)
            except ValueError:
                raise ValueError("Enter a numeric scale or offset value.")
            if mode.startswith("Scale"):
                return unique_name(f"{t0.name}*{value:g}"), list(t0.x_data), [y * value for y in t0.y_data]
            return unique_name(f"{t0.name}+{value:g}"), list(t0.x_data), [y + value for y in t0.y_data]

        if mode == "Abs selected":
            return unique_name(f"abs({t0.name})"), list(t0.x_data), [abs(y) for y in t0.y_data]

        if mode == "Derivative selected":
            y_out: list[float] = []
            n = min(len(t0.x_data), len(t0.y_data))
            for i in range(n):
                if i == 0:
                    dx = t0.x_data[1] - t0.x_data[0] if n > 1 else 1.0
                    dy = t0.y_data[1] - t0.y_data[0] if n > 1 else 0.0
                elif i == n - 1:
                    dx = t0.x_data[i] - t0.x_data[i - 1]
                    dy = t0.y_data[i] - t0.y_data[i - 1]
                else:
                    dx = t0.x_data[i + 1] - t0.x_data[i - 1]
                    dy = t0.y_data[i + 1] - t0.y_data[i - 1]
                y_out.append(dy / dx if dx else 0.0)
            return unique_name(f"deriv({t0.name})"), list(t0.x_data[:n]), y_out

        if len(selected) < 2:
            raise ValueError("Select two traces for binary expressions.")
        t1 = self.canvas._trace_by_name.get(selected[1])
        if not t1:
            raise ValueError("Second trace is not available.")
        n = min(len(t0.x_data), len(t0.y_data), len(t1.y_data))
        y0 = t0.y_data[:n]
        y1 = t1.y_data[:n]
        if mode == "A - B":
            y = [a - b for a, b in zip(y0, y1)]
            label = f"{t0.name}-{t1.name}"
        elif mode == "A + B":
            y = [a + b for a, b in zip(y0, y1)]
            label = f"{t0.name}+{t1.name}"
        else:
            y = [a / b if b else math.nan for a, b in zip(y0, y1)]
            label = f"{t0.name}/{t1.name}"
        return unique_name(value_text or label), list(t0.x_data[:n]), y

    # ----- Export -----

    def _on_export_visible_csv(self):
        visible_names = self.canvas.get_visible_trace_names()
        if not visible_names:
            QMessageBox.information(self, "Export CSV", "No visible traces to export.")
            return
        if not self._x_var:
            QMessageBox.warning(self, "Export CSV", "Missing X axis variable.")
            return

        default_dir = str(Path.home())
        default_name = "lumen_waveforms.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Visible Waveforms",
            str(Path(default_dir) / default_name),
            "CSV files (*.csv)",
        )
        if not path:
            return

        traces = [self.canvas._trace_by_name[name] for name in visible_names if name in self.canvas._trace_by_name]
        if not traces:
            QMessageBox.information(self, "Export CSV", "No valid traces to export.")
            return

        max_len = max(len(t.x_data) for t in traces)
        header = [self._x_var]
        for t in traces:
            header.append(t.name)

        try:
            with open(path, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                for i in range(max_len):
                    row = []
                    x_val = traces[0].x_data[i] if i < len(traces[0].x_data) else ""
                    row.append(x_val)
                    for t in traces:
                        row.append(t.y_data[i] if i < len(t.y_data) else "")
                    writer.writerow(row)
        except Exception as exc:
            QMessageBox.critical(self, "Export CSV", f"Failed to export CSV:\n{exc}")
            return

        QMessageBox.information(self, "Export CSV", f"Exported {len(traces)} trace(s) to:\n{path}")

    def _on_save_plot_image(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plot Image",
            str(Path.home() / "sigview_plot.png"),
            "PNG image (*.png);;JPEG image (*.jpg)",
        )
        if not path:
            return
        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            path += ".png"
        if not self.canvas.grab().save(path):
            QMessageBox.critical(self, "Save Plot Image", "Could not save the plot image.")
            return
        self.statusBar().showMessage(f"Saved plot image: {path}", 4000)

    # ----- Status / measurements -----

    def _on_hover_text(self, text: str):
        self.status_hover.setText(text)

    def _on_cursor_text(self, text: str):
        self.status_cursor.setText(text)
        self._refresh_measurements()

    def _refresh_measurements(self):
        self._refresh_measurement_table()
        item = self.signal_list.currentItem()
        if not item:
            self.measure_label.setText("")
            return

        name = item.text()
        a = self.canvas.get_cursor_value(name, "A")
        b = self.canvas.get_cursor_value(name, "B")
        ax = self.canvas.cursor_a_x
        bx = self.canvas.cursor_b_x

        lines = [f"Signal: {name}"]
        if ax is not None:
            if a is not None:
                lines.append(f"A: x={self.canvas._format_value(ax)} y={self.canvas._format_value(a)}")
            else:
                lines.append(f"A: x={self.canvas._format_value(ax)}")
        if bx is not None:
            if b is not None:
                lines.append(f"B: x={self.canvas._format_value(bx)} y={self.canvas._format_value(b)}")
            else:
                lines.append(f"B: x={self.canvas._format_value(bx)}")
        if ax is not None and bx is not None:
            lines.append(f"dX: {self.canvas._format_value(bx - ax)}")
            if a is not None and b is not None:
                lines.append(f"dY: {self.canvas._format_value(b - a)}")

        self.measure_label.setText("\n".join(lines))

    def _refresh_measurement_table(self):
        visible = [t for t in self.canvas.traces if t.visible]
        self.measure_table.setRowCount(0)
        ax = self.canvas.cursor_a_x
        bx = self.canvas.cursor_b_x
        for trace in visible:
            r = self.measure_table.rowCount()
            self.measure_table.insertRow(r)
            name_item = QTableWidgetItem(trace.name)
            name_item.setForeground(trace.color)
            self.measure_table.setItem(r, 0, name_item)

            a = self.canvas.get_cursor_value(trace.name, "A")
            b = self.canvas.get_cursor_value(trace.name, "B")
            finite = [v for v in trace.y_data if isinstance(v, (int, float)) and math.isfinite(v)]
            avg = sum(finite) / len(finite) if finite else None
            values = [
                self.canvas._format_value(a) if a is not None and ax is not None else "",
                self.canvas._format_value(b) if b is not None and bx is not None else "",
                self.canvas._format_value(b - a) if a is not None and b is not None else "",
                self.canvas._format_value(min(finite)) if finite else "",
                self.canvas._format_value(max(finite)) if finite else "",
                self.canvas._format_value(avg) if avg is not None else "",
            ]
            for col, text in enumerate(values, start=1):
                self.measure_table.setItem(r, col, QTableWidgetItem(text))


# Preferred user-facing alias.
SigViewWindow = WaveformViewerWindow
