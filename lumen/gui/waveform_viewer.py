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
from bisect import bisect_left, bisect_right
import ast
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

from lumen.qt.QtCore import Qt, QPoint, QPointF, QRectF, QSize, Signal
from lumen.qt.QtGui import (
    QAction,
    QIcon,
    QPainter,
    QPen,
    QColor,
    QFont,
    QPainterPath,
    QPolygonF,
    QKeySequence,
    QWheelEvent,
)
from lumen.qt.QtWidgets import (
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
    QMenu,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
)

from lumen.gui.branding import apply_window_branding
from lumen.core.simulator import SimulatorBridge
from lumen.core.waveform_calculator import WaveformCalculator
from lumen.gui.calculator_window import CalculatorWindow


class WaveVector:
    """Numeric waveform vector used by SigView's safe calculator."""

    def __init__(self, x_data: list[float], y_data: list[float], label: str = ""):
        self.x_data = list(x_data or [])
        self.y_data = list(y_data or [])
        self.label = label

    def _binary(self, other, op, label: str) -> "WaveVector":
        if isinstance(other, WaveVector):
            n = min(len(self.x_data), len(self.y_data), len(other.y_data))
            return WaveVector(self.x_data[:n], [op(a, b) for a, b in zip(self.y_data[:n], other.y_data[:n])], label)
        try:
            value = float(other)
        except (TypeError, ValueError):
            return NotImplemented
        return WaveVector(self.x_data[:len(self.y_data)], [op(a, value) for a in self.y_data], label)

    def _rbinary(self, other, op, label: str) -> "WaveVector":
        try:
            value = float(other)
        except (TypeError, ValueError):
            return NotImplemented
        return WaveVector(self.x_data[:len(self.y_data)], [op(value, a) for a in self.y_data], label)

    def __add__(self, other):
        return self._binary(other, lambda a, b: a + b, f"({self.label}+{_label_for(other)})")

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        return self._binary(other, lambda a, b: a - b, f"({self.label}-{_label_for(other)})")

    def __rsub__(self, other):
        return self._rbinary(other, lambda a, b: a - b, f"({_label_for(other)}-{self.label})")

    def __mul__(self, other):
        return self._binary(other, lambda a, b: a * b, f"({self.label}*{_label_for(other)})")

    def __rmul__(self, other):
        return self.__mul__(other)

    def __truediv__(self, other):
        return self._binary(other, lambda a, b: a / b if b else math.nan, f"({self.label}/{_label_for(other)})")

    def __rtruediv__(self, other):
        return self._rbinary(other, lambda a, b: a / b if b else math.nan, f"({_label_for(other)}/{self.label})")

    def __pow__(self, other):
        return self._binary(other, lambda a, b: math.pow(a, b), f"pow({self.label},{_label_for(other)})")

    def __neg__(self):
        return WaveVector(self.x_data[:len(self.y_data)], [-a for a in self.y_data], f"-{self.label}")

    def __abs__(self):
        return WaveVector(self.x_data[:len(self.y_data)], [abs(a) for a in self.y_data], f"abs({self.label})")


def _label_for(value) -> str:
    return value.label if isinstance(value, WaveVector) else str(value)


def _vector_unary(value, fn, label: str):
    if isinstance(value, WaveVector):
        return WaveVector(value.x_data[:len(value.y_data)], [fn(v) for v in value.y_data], f"{label}({value.label})")
    return fn(float(value))


def _vector_stat(value, fn) -> float:
    vals = value.y_data if isinstance(value, WaveVector) else [float(value)]
    finite = [v for v in vals if isinstance(v, (int, float)) and math.isfinite(v)]
    return fn(finite) if finite else math.nan


def _vector_deriv(value):
    if not isinstance(value, WaveVector):
        return 0.0
    n = min(len(value.x_data), len(value.y_data))
    y_out: list[float] = []
    for i in range(n):
        if i == 0:
            dx = value.x_data[1] - value.x_data[0] if n > 1 else 1.0
            dy = value.y_data[1] - value.y_data[0] if n > 1 else 0.0
        elif i == n - 1:
            dx = value.x_data[i] - value.x_data[i - 1]
            dy = value.y_data[i] - value.y_data[i - 1]
        else:
            dx = value.x_data[i + 1] - value.x_data[i - 1]
            dy = value.y_data[i + 1] - value.y_data[i - 1]
        y_out.append(dy / dx if dx else math.nan)
    return WaveVector(value.x_data[:n], y_out, f"deriv({value.label})")


def _vector_integ(value):
    if not isinstance(value, WaveVector):
        return float(value)
    n = min(len(value.x_data), len(value.y_data))
    if n <= 0:
        return WaveVector([], [], f"integ({value.label})")
    acc = 0.0
    y_out = [0.0]
    for i in range(1, n):
        dx = value.x_data[i] - value.x_data[i - 1]
        acc += 0.5 * (value.y_data[i] + value.y_data[i - 1]) * dx
        y_out.append(acc)
    return WaveVector(value.x_data[:n], y_out, f"integ({value.label})")


def _vector_clip(value, lo, hi):
    lo_f = float(lo)
    hi_f = float(hi)
    return _vector_unary(value, lambda v: min(max(v, lo_f), hi_f), "clip")


def _vector_phase(value):
    return _vector_unary(value, lambda v: 0.0 if v >= 0 else 180.0, "phase")


def _vector_freq(value) -> float:
    if not isinstance(value, WaveVector):
        return math.nan
    n = min(len(value.x_data), len(value.y_data))
    if n < 3:
        return math.nan
    finite_y = [v for v in value.y_data[:n] if isinstance(v, (int, float)) and math.isfinite(v)]
    if not finite_y:
        return math.nan
    threshold = 0.5 * (min(finite_y) + max(finite_y))
    crossings: list[float] = []
    for i in range(1, n):
        y0 = value.y_data[i - 1] - threshold
        y1 = value.y_data[i] - threshold
        if y0 < 0 <= y1:
            x0 = value.x_data[i - 1]
            x1 = value.x_data[i]
            denom = value.y_data[i] - value.y_data[i - 1]
            frac = (threshold - value.y_data[i - 1]) / denom if denom else 0.0
            crossings.append(x0 + frac * (x1 - x0))
    if len(crossings) < 2:
        return math.nan
    periods = [b - a for a, b in zip(crossings, crossings[1:]) if b > a]
    avg_period = sum(periods) / len(periods) if periods else math.nan
    return 1.0 / avg_period if avg_period and math.isfinite(avg_period) else math.nan


class SigViewCalculatorEngine:
    """Safe expression evaluator for industry-style waveform calculations."""

    _ALLOWED_AST_NODES = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Call,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.USub,
        ast.UAdd,
    )

    def __init__(self, traces: dict[str, TraceRecord]):
        self._traces = traces

    def evaluate(self, expression: str):
        expr = self._preprocess(expression)
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, self._ALLOWED_AST_NODES):
                raise ValueError(f"Unsupported calculator syntax: {type(node).__name__}")
            if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
                raise ValueError("Only built-in SigView calculator functions are supported.")
        env = self._environment()
        try:
            return eval(compile(tree, "<sigview-calculator>", "eval"), {"__builtins__": {}}, env)
        except NameError as exc:
            raise ValueError(f"Unknown signal or function in expression: {exc}") from exc

    def _preprocess(self, expression: str) -> str:
        expr = (expression or "").strip()
        if not expr:
            raise ValueError("Enter a calculator expression.")

        def repl(match: re.Match) -> str:
            fn = match.group(1)
            body = match.group(2).strip()
            if body.startswith(("'", '"')):
                return match.group(0)
            return f'{fn}("{body}")'

        return re.sub(r"\b([VI])\(\s*([^)'\"()]+?)\s*\)", repl, expr)

    def _environment(self) -> dict:
        def trace_by_name(name: str, kind: str = "") -> WaveVector:
            text = str(name).strip()
            candidates = [text]
            if kind:
                candidates.insert(0, f"{kind}({text})")
            for candidate in candidates:
                if candidate in self._traces:
                    t = self._traces[candidate]
                    return WaveVector(t.x_data, t.y_data, t.name)
            lower_map = {k.lower(): k for k in self._traces}
            for candidate in candidates:
                hit = lower_map.get(candidate.lower())
                if hit:
                    t = self._traces[hit]
                    return WaveVector(t.x_data, t.y_data, t.name)
            raise ValueError(f"Signal not found: {name}")

        return {
            "V": lambda name: trace_by_name(name, "V"),
            "I": lambda name: trace_by_name(name, "I"),
            "sig": lambda name: trace_by_name(name),
            "abs": abs,
            "mag": abs,
            "sqrt": lambda v: _vector_unary(v, math.sqrt, "sqrt"),
            "ln": lambda v: _vector_unary(v, math.log, "ln"),
            "log": lambda v: _vector_unary(v, math.log10, "log10"),
            "log10": lambda v: _vector_unary(v, math.log10, "log10"),
            "exp": lambda v: _vector_unary(v, math.exp, "exp"),
            "sin": lambda v: _vector_unary(v, math.sin, "sin"),
            "cos": lambda v: _vector_unary(v, math.cos, "cos"),
            "tan": lambda v: _vector_unary(v, math.tan, "tan"),
            "db20": lambda v: _vector_unary(v, lambda x: 20.0 * math.log10(abs(x)) if x else math.nan, "dB20"),
            "dB20": lambda v: _vector_unary(v, lambda x: 20.0 * math.log10(abs(x)) if x else math.nan, "dB20"),
            "db10": lambda v: _vector_unary(v, lambda x: 10.0 * math.log10(abs(x)) if x else math.nan, "dB10"),
            "phase": _vector_phase,
            "deriv": _vector_deriv,
            "ddt": _vector_deriv,
            "integ": _vector_integ,
            "idt": _vector_integ,
            "clip": _vector_clip,
            "avg": lambda v: _vector_stat(v, lambda vals: sum(vals) / len(vals)),
            "mean": lambda v: _vector_stat(v, lambda vals: sum(vals) / len(vals)),
            "rms": lambda v: _vector_stat(v, lambda vals: math.sqrt(sum(x * x for x in vals) / len(vals))),
            "min": lambda v: _vector_stat(v, min),
            "max": lambda v: _vector_stat(v, max),
            "pkpk": lambda v: _vector_stat(v, lambda vals: max(vals) - min(vals)),
            "freq": _vector_freq,
            "period": lambda v: (1.0 / _vector_freq(v)) if _vector_freq(v) else math.nan,
            "pi": math.pi,
            "e": math.e,
        }


@dataclass
class TraceRecord:
    name: str
    color: QColor
    x_data: list[float]
    y_data: list[float]
    visible: bool = True
    source: str = ""
    np_x: Any = None
    np_y: Any = None
    cache_key: tuple | None = None
    cache_polygon: Any = None

    def get_np_arrays(self):
        if HAS_NUMPY and self.np_x is None and self.x_data and self.y_data:
            try:
                self.np_x = np.ascontiguousarray(self.x_data, dtype=np.float64)
                self.np_y = np.ascontiguousarray(self.y_data, dtype=np.float64)
            except Exception:
                pass
        return self.np_x, self.np_y


@dataclass
class MarkerRecord:
    name: str
    x: float
    color: QColor


class WaveformCanvas(QWidget):
    """Custom widget for high-performance waveform drawing."""

    hover_text_changed = Signal(str)
    cursor_text_changed = Signal(str)
    signal_context_requested = Signal(str, QPoint)

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
        self.display_mode = "line"

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
        self._right_press_pos: QPointF | None = None
        self._right_current_pos: QPointF | None = None
        self._right_press_trace = ""
        self._right_drag_active = False

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

    def set_display_mode(self, mode: str):
        clean = str(mode or "line").strip().lower()
        if clean not in {"line", "points", "line_points"}:
            clean = "line"
        self.display_mode = clean
        self.update()

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

    def zoom_in(self):
        self.zoom_by(0.78, y_axis=False)

    def zoom_out(self):
        self.zoom_by(1.0 / 0.78, y_axis=False)

    def zoom_by(self, factor: float, center: QPointF | None = None, x_axis: bool = True, y_axis: bool = True):
        if not self.traces or factor <= 0:
            return
        if center is None:
            plot = self._plot_rect()
            center = plot.center()
        cx, cy = self._screen_to_data(center.x(), center.y())
        self._zoom_about(cx, cy, factor, x_axis=x_axis, y_axis=y_axis)

    def _zoom_about(self, cx: float, cy: float, factor: float, x_axis: bool = True, y_axis: bool = True):
        self._auto_range = False
        if x_axis:
            self.x_min = cx + (self.x_min - cx) * factor
            self.x_max = cx + (self.x_max - cx) * factor
        if y_axis and not self.stacked_mode:
            self.y_min = cy + (self.y_min - cy) * factor
            self.y_max = cy + (self.y_max - cy) * factor
        elif x_axis and not self.stacked_mode:
            self._fit_y_to_visible_x()
        self._normalize_ranges()
        self.update()
        self._emit_cursor_text()

    def zoom_to_screen_rect(self, rect: QRectF):
        plot = self._plot_rect()
        clipped = rect.normalized().intersected(plot)
        if clipped.width() < 8 or clipped.height() < 8:
            return
        x0, y0 = self._screen_to_data(clipped.left(), clipped.bottom())
        x1, y1 = self._screen_to_data(clipped.right(), clipped.top())
        self._auto_range = False
        if x1 > x0:
            self.x_min = x0
            self.x_max = x1
        if not self.stacked_mode and y1 > y0:
            self.y_min = y0
            self.y_max = y1
        self._normalize_ranges()
        self.update()
        self._emit_cursor_text()

    def _fit_y_to_visible_x(self):
        y_lo = float("inf")
        y_hi = float("-inf")
        for trace in self.traces:
            if not trace.visible or not trace.x_data or not trace.y_data:
                continue
            n = min(len(trace.x_data), len(trace.y_data))
            lo, hi = self._visible_index_bounds(trace.x_data, self.x_min, self.x_max, n)
            if hi <= lo:
                continue
            for idx in range(lo, hi):
                v = trace.y_data[idx]
                if isinstance(v, (int, float)) and math.isfinite(v):
                    y_lo = min(y_lo, v)
                    y_hi = max(y_hi, v)
        if not math.isfinite(y_lo) or not math.isfinite(y_hi):
            return
        self.y_min = y_lo
        self.y_max = y_hi
        margin = (self.y_max - self.y_min) * 0.08 or 0.1
        self.y_min -= margin
        self.y_max += margin

    @staticmethod
    def _visible_index_bounds(x_data: list[float], x_min: float, x_max: float, n: int) -> tuple[int, int]:
        if n <= 0:
            return 0, 0
        if n <= 1 or x_data[0] <= x_data[n - 1]:
            i_start = bisect_left(x_data, x_min, 0, n)
            if i_start > 0:
                i_start -= 1
            i_end = bisect_right(x_data, x_max, 0, n)
            if i_end < n:
                i_end += 1
            return max(0, i_start), min(n, i_end)
        return 0, n

    def _normalize_ranges(self):
        if self.x_max == self.x_min:
            self.x_min -= 0.5
            self.x_max += 0.5
        if self.y_max == self.y_min:
            self.y_min -= 0.5
            self.y_max += 0.5

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

    def nearest_trace_name_at(self, sx: float, sy: float, tolerance_px: float = 18.0) -> str:
        if self.stacked_mode:
            return self._nearest_stacked_trace_name_at(sx, sy, tolerance_px)
        x, _ = self._screen_to_data(sx, sy)
        best_name = ""
        best_dist = float("inf")
        plot = self._plot_rect()
        for trace in self.traces:
            if not trace.visible:
                continue
            y = self._interpolate_value(trace.x_data, trace.y_data, x)
            if y is None:
                continue
            p = self._data_to_screen(x, y, plot, self.y_min, self.y_max)
            dist = abs(p.y() - sy)
            if dist < best_dist:
                best_name = trace.name
                best_dist = dist
        return best_name if best_dist <= tolerance_px else ""

    def _nearest_stacked_trace_name_at(self, sx: float, sy: float, tolerance_px: float) -> str:
        visible = [t for t in self.traces if t.visible and t.x_data and t.y_data]
        if not visible:
            return ""
        plot = self._plot_rect()
        if not plot.contains(QPointF(sx, sy)):
            return ""
        lane_h = plot.height() / max(len(visible), 1)
        lane_idx = int((sy - plot.top()) / (lane_h or 1.0))
        if lane_idx < 0 or lane_idx >= len(visible):
            return ""
        trace = visible[lane_idx]
        top = plot.top() + lane_idx * lane_h
        lane = QRectF(plot.left(), top, plot.width(), lane_h)
        x, _ = self._screen_to_data(sx, sy)
        y = self._interpolate_value(trace.x_data, trace.y_data, x)
        if y is None:
            return trace.name
        finite_y = [v for v in trace.y_data if isinstance(v, (int, float)) and math.isfinite(v)]
        if not finite_y:
            return trace.name
        y0 = min(finite_y)
        y1 = max(finite_y)
        margin = (y1 - y0) * 0.08 or 0.1
        p = self._data_to_screen(x, y, lane, y0 - margin, y1 + margin)
        return trace.name if abs(p.y() - sy) <= tolerance_px else trace.name

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
        self._draw_zoom_box(painter)
        painter.end()

    def _paint_overlay(self, painter: QPainter, plot: QRectF, traces: list[TraceRecord]):
        if self.show_grid:
            self._draw_grid(painter, plot, self.x_min, self.x_max, self.y_min, self.y_max)
        painter.save()
        painter.setClipRect(plot.adjusted(-4, -4, 4, 4))
        for trace in traces:
            self._draw_trace(painter, trace, plot, self.y_min, self.y_max)
        painter.restore()

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

            painter.save()
            painter.setClipRect(lane.adjusted(-4, -4, 4, 4))
            self._draw_trace(painter, trace, lane, y0, y1)
            painter.restore()
            painter.setPen(QPen(QColor("#8f9daa"), 1))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(int(lane.left() + 6), int(lane.top() + 14), trace.name)

            painter.setPen(QPen(QColor("#2b323a"), 1))
            painter.drawLine(int(lane.left()), int(lane.bottom()), int(lane.right()), int(lane.bottom()))

    def _draw_trace(self, painter: QPainter, trace: TraceRecord, rect: QRectF, y_min: float, y_max: float):
        if self.display_mode in {"line", "line_points"}:
            self._draw_trace_line(painter, trace, rect, y_min, y_max)
        if self.display_mode in {"points", "line_points"}:
            self._draw_trace_points(painter, trace, rect, y_min, y_max)

    def _draw_trace_line(self, painter: QPainter, trace: TraceRecord, rect: QRectF, y_min: float, y_max: float):
        try:
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

            width_px = max(200, int(rect.width()))
            height_px = max(200, int(rect.height()))
            cache_key = (
                round(self.x_min, 12),
                round(self.x_max, 12),
                round(y_min, 8),
                round(y_max, 8),
                int(rect.left()),
                int(rect.top()),
                width_px,
                height_px,
                trace.name == self.selected_trace_name
            )

            if trace.cache_key == cache_key and trace.cache_polygon is not None:
                if isinstance(trace.cache_polygon, QPolygonF):
                    painter.drawPolyline(trace.cache_polygon)
                    return
                elif isinstance(trace.cache_polygon, QPainterPath):
                    painter.drawPath(trace.cache_polygon)
                    return

            np_x, np_y = trace.get_np_arrays()
            polygon = None
            is_path = False

            if HAS_NUMPY and np_x is not None and np_y is not None and len(np_x) == n and len(np_y) == n:
                polygon, is_path = self._vectorized_line_render(np_x, np_y, self.x_min, self.x_max, y_min, y_max, rect)

            if polygon is None:
                draw_x, draw_y = self._line_render_samples(x_data[:n], y_data[:n], self.x_min, self.x_max, width_px)
                points = [
                    self._data_to_screen(xv, yv, lane_rect=rect, y_min=y_min, y_max=y_max)
                    for xv, yv in zip(draw_x, draw_y)
                    if isinstance(xv, (int, float)) and isinstance(yv, (int, float)) and math.isfinite(xv) and math.isfinite(yv)
                ]
                if not points:
                    return
                if len(points) > 120:
                    polygon = QPolygonF(points)
                    is_path = False
                else:
                    path = QPainterPath()
                    self._append_smooth_path(path, points)
                    polygon = path
                    is_path = True

            trace.cache_key = cache_key
            trace.cache_polygon = polygon

            if is_path:
                painter.drawPath(polygon)
            else:
                painter.drawPolyline(polygon)
        except Exception:
            pass

    def _vectorized_line_render(self, np_x: np.ndarray, np_y: np.ndarray, x_min: float, x_max: float, y_min: float, y_max: float, rect: QRectF):
        n = min(len(np_x), len(np_y))
        if n == 0:
            return QPolygonF(), False

        is_sorted = (n <= 1) or (np_x[0] <= np_x[n - 1])
        if is_sorted:
            i0 = max(0, int(np.searchsorted(np_x, x_min, side='left')) - 1)
            i1 = min(n, int(np.searchsorted(np_x, x_max, side='right')) + 1)
        else:
            i0 = 0
            i1 = n

        if i0 >= i1:
            i0 = 0
            i1 = n

        n_vis = i1 - i0
        width_px = max(200, int(rect.width()))
        target_bins = width_px

        if n_vis <= target_bins:
            x_sub = np_x[i0:i1]
            y_sub = np_y[i0:i1]
        else:
            bin_len = n_vis // target_bins
            if bin_len < 1:
                x_sub = np_x[i0:i1]
                y_sub = np_y[i0:i1]
            else:
                tot = target_bins * bin_len
                x_g = np_x[i0:i0 + tot].reshape(target_bins, bin_len)
                y_g = np_y[i0:i0 + tot].reshape(target_bins, bin_len)

                min_i = np.argmin(y_g, axis=1)
                max_i = np.argmax(y_g, axis=1)
                rows = np.arange(target_bins)

                idx1 = np.minimum(min_i, max_i)
                idx2 = np.maximum(min_i, max_i)

                x_sub = np.empty(target_bins * 2, dtype=np.float64)
                y_sub = np.empty(target_bins * 2, dtype=np.float64)

                x_sub[0::2] = x_g[rows, idx1]
                x_sub[1::2] = x_g[rows, idx2]
                y_sub[0::2] = y_g[rows, idx1]
                y_sub[1::2] = y_g[rows, idx2]

                tail_start = i0 + tot
                if tail_start < i1:
                    tail_x = np_x[tail_start:i1]
                    tail_y = np_y[tail_start:i1]
                    finite = np.isfinite(tail_x) & np.isfinite(tail_y)
                    if np.any(finite):
                        tail_x = tail_x[finite]
                        tail_y = tail_y[finite]
                        min_i = int(np.argmin(tail_y))
                        max_i = int(np.argmax(tail_y))
                        keep = sorted({min_i, max_i, len(tail_y) - 1})
                        x_sub = np.concatenate((x_sub, tail_x[keep]))
                        y_sub = np.concatenate((y_sub, tail_y[keep]))

        dx = (x_max - x_min) or 1.0
        dy = (y_max - y_min) or 1.0

        sx = rect.left() + ((x_sub - x_min) / dx) * rect.width()
        sy = rect.bottom() - ((y_sub - y_min) / dy) * rect.height()

        valid = np.isfinite(sx) & np.isfinite(sy)
        if not np.all(valid):
            sx = sx[valid]
            sy = sy[valid]

        points = [QPointF(float(px), float(py)) for px, py in zip(sx, sy)]
        if len(points) <= 120:
            path = QPainterPath()
            self._append_smooth_path(path, points)
            return path, True
        return QPolygonF(points), False

    @staticmethod
    def _line_render_samples(x_data: list[float], y_data: list[float], x_min: float, x_max: float, width_px: int) -> tuple[list[float], list[float]]:
        try:
            n = min(len(x_data), len(y_data))
            if n == 0:
                return [], []

            is_sorted = (n <= 1) or (x_data[0] <= x_data[n - 1])
            if is_sorted:
                i_start = bisect_left(x_data, x_min, 0, n)
                if i_start > 0:
                    i_start -= 1
                i_end = bisect_right(x_data, x_max, 0, n)
                if i_end < n:
                    i_end += 1
            else:
                i_start = 0
                i_end = n

            if i_start >= i_end:
                i_start = 0
                i_end = n

            n_vis = i_end - i_start
            target_bins = max(300, width_px)

            if n_vis <= target_bins:
                sub_x = x_data[i_start:i_end]
                sub_y = y_data[i_start:i_end]
                return [float(x) for x in sub_x], [float(y) for y in sub_y]

            bin_size = max(1.0, n_vis / target_bins)
            out_x: list[float] = []
            out_y: list[float] = []

            for b in range(target_bins):
                b0 = i_start + int(b * bin_size)
                b1 = min(n, i_start + int((b + 1) * bin_size))
                if b0 >= b1 or b0 >= n:
                    continue

                sub_y = y_data[b0:b1]
                if not sub_y:
                    continue

                min_idx = 0
                max_idx = 0
                min_val = float("inf")
                max_val = float("-inf")
                has_finite = False

                for k, v in enumerate(sub_y):
                    if isinstance(v, (int, float)) and math.isfinite(v):
                        has_finite = True
                        if v < min_val:
                            min_val = v
                            min_idx = k
                        if v > max_val:
                            max_val = v
                            max_idx = k

                if not has_finite:
                    continue

                idx1, idx2 = (min_idx, max_idx) if min_idx <= max_idx else (max_idx, min_idx)

                pos1 = b0 + idx1
                if 0 <= pos1 < n:
                    x1, y1 = x_data[pos1], y_data[pos1]
                    if isinstance(x1, (int, float)) and isinstance(y1, (int, float)) and math.isfinite(x1) and math.isfinite(y1):
                        out_x.append(float(x1))
                        out_y.append(float(y1))

                if idx1 != idx2:
                    pos2 = b0 + idx2
                    if 0 <= pos2 < n:
                        x2, y2 = x_data[pos2], y_data[pos2]
                        if isinstance(x2, (int, float)) and isinstance(y2, (int, float)) and math.isfinite(x2) and math.isfinite(y2):
                            out_x.append(float(x2))
                            out_y.append(float(y2))

            return out_x, out_y
        except Exception:
            target = max(600, width_px)
            stride = max(1, len(x_data) // target) if len(x_data) > 0 else 1
            return [float(x) for x in x_data[::stride]], [float(y) for y in y_data[::stride]]

    @staticmethod
    def _append_smooth_path(path: QPainterPath, points: list[QPointF]) -> None:
        if not points:
            return
        path.moveTo(points[0])
        if len(points) == 1:
            return
        if len(points) == 2:
            path.lineTo(points[1])
            return

        def clamp(value: float, lo: float, hi: float) -> float:
            if lo > hi:
                lo, hi = hi, lo
            return max(lo, min(hi, value))

        def clamped_control(raw: QPointF, a: QPointF, b: QPointF, prev: QPointF, nxt: QPointF) -> QPointF:
            y_lo = min(prev.y(), a.y(), b.y(), nxt.y())
            y_hi = max(prev.y(), a.y(), b.y(), nxt.y())
            return QPointF(
                clamp(raw.x(), a.x(), b.x()),
                clamp(raw.y(), y_lo, y_hi),
            )

        tension = 0.42
        for i in range(len(points) - 1):
            p0 = points[max(0, i - 1)]
            p1 = points[i]
            p2 = points[i + 1]
            p3 = points[min(len(points) - 1, i + 2)]
            if p2.x() <= p1.x():
                path.lineTo(p2)
                continue
            c1_raw = QPointF(
                p1.x() + (p2.x() - p0.x()) * tension / 3.0,
                p1.y() + (p2.y() - p0.y()) * tension / 3.0,
            )
            c2_raw = QPointF(
                p2.x() - (p3.x() - p1.x()) * tension / 3.0,
                p2.y() - (p3.y() - p1.y()) * tension / 3.0,
            )
            c1 = clamped_control(c1_raw, p1, p2, p0, p3)
            c2 = clamped_control(c2_raw, p1, p2, p0, p3)
            path.cubicTo(c1, c2, p2)

    def _draw_trace_points(self, painter: QPainter, trace: TraceRecord, rect: QRectF, y_min: float, y_max: float):
        try:
            x_data = trace.x_data
            y_data = trace.y_data
            n = min(len(x_data), len(y_data))
            if n < 1:
                return

            is_sorted = (n <= 1) or (x_data[0] <= x_data[n - 1])
            if is_sorted:
                i_start = bisect_left(x_data, self.x_min, 0, n)
                if i_start > 0:
                    i_start -= 1
                i_end = bisect_right(x_data, self.x_max, 0, n)
                if i_end < n:
                    i_end += 1
            else:
                i_start = 0
                i_end = n

            if i_start >= i_end:
                i_start = 0
                i_end = n

            n_vis = i_end - i_start
            target_points = max(300, int(rect.width()) * 3)
            stride = max(1, int(n_vis / target_points))
            radius = 3.0 if trace.name == self.selected_trace_name else 2.2
            fill = QColor(trace.color)
            fill.setAlpha(220)
            painter.setPen(QPen(trace.color, 1))
            painter.setBrush(fill)
            for idx in range(i_start, i_end, stride):
                if 0 <= idx < n:
                    xv = x_data[idx]
                    yv = y_data[idx]
                    if not (
                        isinstance(xv, (int, float)) and isinstance(yv, (int, float)) and
                        math.isfinite(xv) and math.isfinite(yv)
                    ):
                        continue
                    pp = self._data_to_screen(xv, yv, lane_rect=rect, y_min=y_min, y_max=y_max)
                    if rect.left() - radius <= pp.x() <= rect.right() + radius and rect.top() - radius <= pp.y() <= rect.bottom() + radius:
                        painter.drawEllipse(pp, radius, radius)
        except Exception:
            pass

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

    def _draw_zoom_box(self, painter: QPainter):
        if not self._right_drag_active or self._right_press_pos is None or self._right_current_pos is None:
            return
        rect = QRectF(self._right_press_pos, self._right_current_pos).normalized().intersected(self._plot_rect())
        if rect.width() < 3 or rect.height() < 3:
            return
        fill = QColor("#3aa6d0")
        fill.setAlpha(38)
        border = QColor("#6ed7ff")
        painter.fillRect(rect, fill)
        painter.setPen(QPen(border, 1, Qt.PenStyle.DashLine))
        painter.drawRect(rect)

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

        factor = 0.86 if event.angleDelta().y() > 0 else 1.0 / 0.86
        modifiers = event.modifiers()
        y_only = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        self.zoom_by(
            factor,
            center=event.position(),
            x_axis=not y_only,
            y_axis=y_only,
        )
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._right_press_pos = event.position()
            self._right_current_pos = event.position()
            self._right_press_trace = self.nearest_trace_name_at(event.position().x(), event.position().y())
            self._right_drag_active = False
            return

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

        if event.buttons() & Qt.MouseButton.RightButton and self._right_press_pos is not None:
            self._right_current_pos = event.position()
            distance = (self._right_current_pos - self._right_press_pos).manhattanLength()
            if distance > 6 and self._plot_rect().contains(self._right_press_pos):
                self._right_drag_active = True
            if self._right_drag_active:
                self.update()
            return

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
        if event.button() == Qt.MouseButton.RightButton:
            was_drag = self._right_drag_active
            press = self._right_press_pos
            current = self._right_current_pos or event.position()
            trace_name = self._right_press_trace
            self._right_press_pos = None
            self._right_current_pos = None
            self._right_press_trace = ""
            self._right_drag_active = False
            if was_drag and press is not None:
                self.zoom_to_screen_rect(QRectF(press, current))
            elif trace_name:
                self.signal_context_requested.emit(trace_name, event.globalPosition().toPoint())
            self.update()
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, _event):
        self.fit_all()


class WaveformViewerWindow(QMainWindow):
    """Standalone SigView waveform window."""

    send_to_simenv_output = Signal(object)
    send_to_simenv_measurement = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lumen - SigView")
        apply_window_branding(self)
        self.setMinimumSize(980, 620)
        self.resize(1260, 760)

        self._x_var = ""
        self._last_waveforms: dict[str, list[float]] = {}
        self._building_signal_list = False
        self._calculator_history: list[str] = []
        self._calculator_trace_specs: list[dict] = []
        self._trace_expression_map: dict[str, str] = {}
        self._simenv_attached = False

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
        self.signal_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.signal_list.customContextMenuRequested.connect(self._on_signal_list_context_menu)
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
        self.measure_table = QTableWidget(0, 10)
        self.measure_table.setHorizontalHeaderLabels(["Signal", "A", "B", "dY", "Min", "Max", "Avg", "RMS", "PkPk", "Freq"])
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
        self.expr_combo.addItems([
            "V(out)",
            "V(out)-V(in)",
            "db20(V(out)/V(in))",
            "deriv(V(out))",
            "integ(V(out))",
            "rms(V(out))",
            "pkpk(V(out))",
            "freq(V(out))",
        ])
        self.expr_combo.currentTextChanged.connect(self._on_calculator_preset)
        expr_layout.addWidget(self.expr_combo)
        self.calc_expr = QLineEdit()
        self.calc_expr.setPlaceholderText("Calculator expression, e.g. V(out)-V(in), db20(V(out)), deriv(V(out))")
        self.calc_expr.setText(self.expr_combo.currentText())
        expr_layout.addWidget(self.calc_expr)
        self.calc_name = QLineEdit()
        self.calc_name.setPlaceholderText("Optional result trace name")
        expr_layout.addWidget(self.calc_name)
        self.expr_value = QLineEdit()
        self.expr_value.setPlaceholderText("Legacy quick value for selected traces")
        expr_layout.addWidget(self.expr_value)
        self.calc_button = QPushButton("Create Calculator Trace")
        self.calc_button.clicked.connect(self._on_create_calculator_trace)
        expr_layout.addWidget(self.calc_button)
        calc_send_row = QHBoxLayout()
        self.btn_send_output = QPushButton("To SimENV Output")
        self.btn_send_output.clicked.connect(self._on_send_calculator_to_simenv_output)
        self.btn_send_measure = QPushButton("To SimENV Measurement")
        self.btn_send_measure.clicked.connect(self._on_send_calculator_to_simenv_measurement)
        calc_send_row.addWidget(self.btn_send_output)
        calc_send_row.addWidget(self.btn_send_measure)
        expr_layout.addLayout(calc_send_row)
        self.quick_combo = QComboBox()
        self.quick_combo.addItems(["Scale selected", "Offset selected", "Abs selected", "Derivative selected", "A - B", "A + B", "A / B"])
        expr_layout.addWidget(self.quick_combo)
        self.expr_button = QPushButton("Create Quick Trace")
        self.expr_button.clicked.connect(self._on_create_expression_trace)
        expr_layout.addWidget(self.expr_button)
        expr_layout.addStretch()
        self.side_tabs.addTab(expr_tab, "Calculator")

        splitter.addWidget(left)

        self.canvas = WaveformCanvas()
        self.canvas.hover_text_changed.connect(self._on_hover_text)
        self.canvas.cursor_text_changed.connect(self._on_cursor_text)
        self.canvas.signal_context_requested.connect(self._on_canvas_signal_context_menu)
        splitter.addWidget(self.canvas)
        splitter.setSizes([280, 980])

    def _create_menus(self):
        menubar = self.menuBar()
        menubar.clear()
        file_menu = menubar.addMenu("&File")
        act_open = QAction("Open Waveform...", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._on_open_waveform_file)
        file_menu.addAction(act_open)

        act_open_run = QAction("Open Run Folder...", self)
        act_open_run.triggered.connect(self._on_open_run_folder)
        file_menu.addAction(act_open_run)

        file_menu.addSeparator()
        act_save_session = QAction("Save SigView Session...", self)
        act_save_session.triggered.connect(self._on_save_session)
        file_menu.addAction(act_save_session)

        act_load_session = QAction("Load SigView Session...", self)
        act_load_session.triggered.connect(self._on_load_session)
        file_menu.addAction(act_load_session)

        file_menu.addSeparator()
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

        view_menu = menubar.addMenu("&View")
        act_zoom_in = QAction("Zoom In", self)
        act_zoom_in.setShortcut(QKeySequence("Ctrl+="))
        act_zoom_in.triggered.connect(self.canvas.zoom_in)
        view_menu.addAction(act_zoom_in)
        act_zoom_out = QAction("Zoom Out", self)
        act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        act_zoom_out.triggered.connect(self.canvas.zoom_out)
        view_menu.addAction(act_zoom_out)
        view_menu.addSeparator()
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
        view_menu.addSeparator()
        self.menu_display_line = QAction("Line", self)
        self.menu_display_points = QAction("Points", self)
        self.menu_display_line_points = QAction("Line + Points", self)
        for mode, action in (
            ("line", self.menu_display_line),
            ("points", self.menu_display_points),
            ("line_points", self.menu_display_line_points),
        ):
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, m=mode: self._on_display_mode_changed(m))
            view_menu.addAction(action)
        self.menu_display_line.setChecked(True)

        marker_menu = menubar.addMenu("&Markers")
        act_add_marker = QAction("Add Marker at Active Cursor", self)
        act_add_marker.triggered.connect(self._on_add_marker)
        marker_menu.addAction(act_add_marker)
        act_clear_markers = QAction("Clear Markers", self)
        act_clear_markers.triggered.connect(self._on_clear_markers)
        marker_menu.addAction(act_clear_markers)

        calc_menu = menubar.addMenu("&Calculator")
        act_calc = QAction("Create Calculator Trace", self)
        act_calc.setShortcut("Ctrl+Return")
        act_calc.triggered.connect(self._on_create_calculator_trace)
        calc_menu.addAction(act_calc)
        for expr in ("V(out)-V(in)", "db20(V(out))", "deriv(V(out))", "integ(V(out))", "rms(V(out))", "freq(V(out))"):
            action = QAction(expr, self)
            action.triggered.connect(lambda _checked=False, text=expr: self._set_calculator_expression(text))
            calc_menu.addAction(action)

    def _create_toolbar(self):
        tb = QToolBar("SigView")
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(tb)

        def add_emoji(action: QAction, emoji: str):
            label = action.text()
            action.setIcon(QIcon())
            action.setIconText(emoji)
            action.setToolTip(label)
            action.setStatusTip(label)
            tb.addAction(action)
            button = tb.widgetForAction(action)
            if button is not None:
                button.setText(emoji)
                button.setToolTip(label)
                font = button.font()
                font.setPointSize(18)
                button.setFont(font)
                button.setMinimumSize(34, 30)

        act_open = QAction("Open", self)
        act_open.triggered.connect(self._on_open_waveform_file)
        add_emoji(act_open, "📂")

        tb.addSeparator()

        act_zoom_in = QAction("Zoom In", self)
        act_zoom_in.setShortcut(QKeySequence("Ctrl+="))
        act_zoom_in.triggered.connect(self.canvas.zoom_in)
        add_emoji(act_zoom_in, "🔍")

        act_zoom_out = QAction("Zoom Out", self)
        act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        act_zoom_out.triggered.connect(self.canvas.zoom_out)
        add_emoji(act_zoom_out, "🔎")

        act_fit = QAction("Fit All", self)
        act_fit.triggered.connect(self.canvas.fit_all)
        add_emoji(act_fit, "⛶")

        act_fit_x = QAction("Fit X", self)
        act_fit_x.triggered.connect(self.canvas.fit_x)
        add_emoji(act_fit_x, "X")

        act_fit_y = QAction("Fit Y", self)
        act_fit_y.triggered.connect(self.canvas.fit_y)
        add_emoji(act_fit_y, "Y")

        tb.addSeparator()

        self.act_grid = QAction("Grid", self)
        self.act_grid.setCheckable(True)
        self.act_grid.setChecked(True)
        self.act_grid.toggled.connect(self._on_toggle_grid)
        add_emoji(self.act_grid, "#")

        self.act_stack = QAction("Stacked", self)
        self.act_stack.setCheckable(True)
        self.act_stack.setChecked(False)
        self.act_stack.toggled.connect(self._on_toggle_stacked)
        add_emoji(self.act_stack, "⇵")

        self.act_points = QAction("Points", self)
        self.act_points.setCheckable(True)
        self.act_points.setToolTip("Show saved waveform samples as points instead of connected lines")
        self.act_points.toggled.connect(lambda checked: self._on_display_mode_changed("points" if checked else "line"))
        add_emoji(self.act_points, "·")

        tb.addSeparator()

        self.act_cursor_a = QAction("Cursor A", self)
        self.act_cursor_a.setCheckable(True)
        self.act_cursor_a.setChecked(True)
        self.act_cursor_a.triggered.connect(lambda: self._set_cursor_mode("A"))
        add_emoji(self.act_cursor_a, "A")

        self.act_cursor_b = QAction("Cursor B", self)
        self.act_cursor_b.setCheckable(True)
        self.act_cursor_b.setChecked(False)
        self.act_cursor_b.triggered.connect(lambda: self._set_cursor_mode("B"))
        add_emoji(self.act_cursor_b, "B")

        act_clear_cur = QAction("Clear Cursors", self)
        act_clear_cur.triggered.connect(self.canvas.clear_cursors)
        act_clear_cur.triggered.connect(self._refresh_measurements)
        add_emoji(act_clear_cur, "⌫")

        tb.addSeparator()

        act_marker = QAction("Marker", self)
        act_marker.triggered.connect(self._on_add_marker)
        add_emoji(act_marker, "◆")

        act_calc = QAction("Calculator", self)
        act_calc.triggered.connect(lambda: self.side_tabs.setCurrentWidget(self.calc_expr.parentWidget()))
        add_emoji(act_calc, "∑")

        act_image = QAction("Image", self)
        act_image.triggered.connect(self._on_save_plot_image)
        add_emoji(act_image, "▧")

        act_export = QAction("Export Visible CSV", self)
        act_export.triggered.connect(self._on_export_visible_csv)
        add_emoji(act_export, "💾")

        tb.addSeparator()

        act_clear = QAction("Clear", self)
        act_clear.triggered.connect(self._on_clear)
        add_emoji(act_clear, "×")

    def _create_status_bar(self):
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_hover = QLabel("")
        self.status_cursor = QLabel("")
        status.addPermanentWidget(self.status_hover, 1)
        status.addPermanentWidget(self.status_cursor, 1)

    # ----- Data loading -----

    def load_results(
        self,
        waveforms: dict,
        x_var: str = "",
        visible_signals: list[str] | None = None,
        derived_expressions: list[dict] | None = None,
        preserve_user_expressions: bool = True,
    ):
        saved_specs = list(self._calculator_trace_specs) if preserve_user_expressions else []
        self._last_waveforms = dict(waveforms or {})
        self._x_var = self._detect_x_var(self._last_waveforms, x_var)

        self.canvas.clear_traces()
        self._trace_expression_map = {}
        self._building_signal_list = True
        self.signal_list.clear()
        self._building_signal_list = False
        self.measure_label.setText("")

        if not self._last_waveforms or not self._x_var:
            self.setWindowTitle("Lumen - SigView")
            return

        visible_set = None
        if visible_signals is not None:
            visible_set = {self._trace_key(name) for name in visible_signals if str(name).strip()}

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
            self._trace_expression_map[name] = self._default_expression_for_signal(name)
            if visible_set is not None:
                self.canvas.set_trace_visible(name, self._trace_key(name) in visible_set)
            loaded_count += 1

        specs_to_apply = self._merge_expression_specs(derived_expressions or [], saved_specs)
        skipped = self._apply_expression_specs(specs_to_apply, remember=False)

        self._rebuild_signal_list()
        self.canvas.x_label = self._x_var
        self.canvas.y_label = "value"
        self.canvas.fit_all()

        self.setWindowTitle(f"Lumen - SigView ({loaded_count} signals)")
        self._refresh_measurements()
        self._refresh_marker_table()
        if skipped:
            self.statusBar().showMessage(
                f"Skipped {len(skipped)} expression trace(s): " + ", ".join(skipped[:3]),
                6000,
            )

    def load_simenv_session(self, payload: dict):
        if not isinstance(payload, dict):
            self.load_results(payload or {})
            return
        self.load_results(
            payload.get("waveforms", {}) or {},
            payload.get("x_var", ""),
            visible_signals=payload.get("visible_signals"),
            derived_expressions=payload.get("derived_expressions"),
            preserve_user_expressions=bool(payload.get("preserve_user_expressions", True)),
        )
        focus_expr = str(payload.get("focus_expression", "") or "").strip()
        if focus_expr:
            self.set_calculator_expression(focus_expr)
        if bool(payload.get("show_calculator", False)):
            self.show_calculator()

    def show_calculator(self):
        if hasattr(self, "calc_expr"):
            self.side_tabs.setCurrentWidget(self.calc_expr.parentWidget())
            self.calc_expr.setFocus()

    def set_calculator_expression(self, text: str):
        self._set_calculator_expression(text)

    def attach_to_simenv(self):
        self._simenv_attached = True

    def _detect_x_var(self, waveforms: dict, x_var: str) -> str:
        if x_var and x_var in waveforms:
            return x_var
        for candidate in ("time", "frequency", "v-sweep", "sweep"):
            if candidate in waveforms:
                return candidate
        keys = [k for k in waveforms.keys() if not str(k).startswith("_")]
        return keys[0] if keys else ""

    @staticmethod
    def _trace_key(name: str) -> str:
        return re.sub(r"\s+", "", str(name or "")).lower()

    @staticmethod
    def _pair_numeric_points(x_data_raw: list, y_data_raw: list) -> tuple[list[float], list[float]]:
        pairs: list[tuple[float, float, int]] = []
        n = min(len(x_data_raw), len(y_data_raw))
        for i in range(n):
            try:
                xv = float(x_data_raw[i])
                yv = float(y_data_raw[i])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(xv) or not math.isfinite(yv):
                continue
            pairs.append((xv, yv, i))
        if not pairs:
            return [], []
        pairs.sort(key=lambda item: (item[0], item[2]))
        x_out: list[float] = []
        y_out: list[float] = []
        last_x: float | None = None
        for xv, yv, _idx in pairs:
            if last_x is not None and xv == last_x:
                y_out[-1] = yv
                continue
            x_out.append(xv)
            y_out.append(yv)
            last_x = xv
        return x_out, y_out

    def _merge_expression_specs(self, primary: list[dict], secondary: list[dict]) -> list[dict]:
        merged: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for collection in (primary, secondary):
            for spec in collection:
                if not isinstance(spec, dict):
                    continue
                expr = str(spec.get("expression", "") or "").strip()
                if not expr:
                    continue
                name = str(spec.get("name", "") or "").strip()
                key = (name.lower(), expr.lower())
                if key in seen:
                    continue
                seen.add(key)
                merged.append({
                    "name": name,
                    "expression": expr,
                    "visible": bool(spec.get("visible", True)),
                })
        return merged

    def _remember_expression(self, expression: str, name: str = "", visible: bool = True):
        expr = str(expression or "").strip()
        if not expr:
            return
        self._calculator_history = [item for item in self._calculator_history if item != expr]
        self._calculator_history.insert(0, expr)
        self._calculator_history = self._calculator_history[:24]
        lowered_name = str(name or "").strip().lower()
        self._calculator_trace_specs = [
            spec for spec in self._calculator_trace_specs
            if str(spec.get("name", "")).strip().lower() != lowered_name
            and str(spec.get("expression", "")).strip().lower() != expr.lower()
        ]
        self._calculator_trace_specs.append({
            "name": str(name or "").strip(),
            "expression": expr,
            "visible": bool(visible),
        })

    def _apply_expression_specs(self, specs: list[dict], remember: bool = False) -> list[str]:
        skipped: list[str] = []
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            expr = str(spec.get("expression", "") or "").strip()
            if not expr:
                continue
            try:
                result = SigViewCalculatorEngine(self.canvas._trace_by_name).evaluate(expr)
                trace_name, x_data, y_data = self._calculator_result_to_trace(expr, result)
            except Exception:
                skipped.append(expr)
                continue
            preferred_name = str(spec.get("name", "") or "").strip()
            if preferred_name:
                trace_name = preferred_name
            trace_name = self._unique_trace_name(trace_name)
            self.canvas.add_trace(trace_name, x_data, y_data, source="calculator")
            visible = bool(spec.get("visible", True))
            self.canvas.set_trace_visible(trace_name, visible)
            self._last_waveforms[trace_name] = list(y_data)
            self._trace_expression_map[trace_name] = expr
            if remember:
                self._remember_expression(expr, trace_name, visible=visible)
        return skipped

    def _default_expression_for_signal(self, name: str) -> str:
        text = str(name or "").strip()
        if re.match(r"^[VI]\s*\(.*\)$", text, re.IGNORECASE):
            return text
        return self._calculator_expression_for_signal(text)

    def _expression_for_trace(self, name: str) -> str:
        expr = str(self._trace_expression_map.get(name, "") or "").strip()
        return expr or self._default_expression_for_signal(name)

    def _update_stored_trace_visibility(self, name: str, visible: bool):
        key = str(name or "").strip().lower()
        for spec in self._calculator_trace_specs:
            if str(spec.get("name", "")).strip().lower() == key:
                spec["visible"] = bool(visible)

    def _on_open_waveform_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Waveform",
            str(Path.home()),
            "Waveforms (*.raw *.json);;Run manifests (*.json);;Raw files (*.raw);;All files (*)",
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
        bridge = SimulatorBridge("GSPICE")
        return bridge._parse_raw(path)

    def _load_waveform_folder(self, folder: str) -> dict:
        root = Path(folder)
        manifest = root / "run_manifest.json"
        if manifest.exists():
            return self._load_waveform_manifest(str(manifest))
        for name in ("selected_waveforms.raw", "waveforms.raw"):
            candidate = root / name
            if candidate.exists():
                return self._load_waveform_file(str(candidate))
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
            artifacts.get("selected_raw", ""),
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
        for name in ("selected_waveforms.raw", "waveforms.raw"):
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
        self._update_stored_trace_visibility(item.text(), visible)
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

    def _on_signal_list_context_menu(self, pos):
        item = self.signal_list.itemAt(pos)
        if not item:
            return
        if not item.isSelected():
            self.signal_list.clearSelection()
            item.setSelected(True)
            self.signal_list.setCurrentItem(item)
        names = [i.text() for i in self.signal_list.selectedItems()]
        if not names:
            names = [item.text()]
        self._show_signal_context_menu(names, self.signal_list.viewport().mapToGlobal(pos))

    def _on_canvas_signal_context_menu(self, name: str, global_pos: QPoint):
        if name not in self.canvas._trace_by_name:
            return
        for i in range(self.signal_list.count()):
            item = self.signal_list.item(i)
            if item and item.text() == name:
                self.signal_list.setCurrentItem(item)
                break
        self._show_signal_context_menu([name], global_pos)

    def _show_signal_context_menu(self, names: list[str], global_pos: QPoint):
        names = [n for n in names if n in self.canvas._trace_by_name]
        if not names:
            return
        primary = names[0]
        menu = QMenu(self)
        title = QAction(primary if len(names) == 1 else f"{len(names)} signals", self)
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()

        act_plot = QAction("Plot", self)
        act_plot.triggered.connect(lambda: self._set_signal_visibility(names, True, fit=True))
        menu.addAction(act_plot)

        act_unplot = QAction("Unplot", self)
        act_unplot.triggered.connect(lambda: self._set_signal_visibility(names, False, fit=False))
        menu.addAction(act_unplot)

        act_isolate = QAction("Plot Only This", self)
        act_isolate.triggered.connect(lambda: self._isolate_signals(names))
        menu.addAction(act_isolate)

        menu.addSeparator()
        calc_menu = menu.addMenu("Send To Calculator")
        calc_expr = self._expression_for_trace(primary)
        for label, expr in (
            ("Signal", calc_expr),
            ("dB20", f"db20({calc_expr})"),
            ("Derivative", f"deriv({calc_expr})"),
            ("Integral", f"integ({calc_expr})"),
            ("RMS", f"rms({calc_expr})"),
            ("Peak-to-Peak", f"pkpk({calc_expr})"),
            ("Frequency", f"freq({calc_expr})"),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, text=expr: self._set_calculator_expression(text))
            calc_menu.addAction(action)

        create_menu = menu.addMenu("Create Derived Trace")
        for label, expr in (
            ("Abs", f"abs({calc_expr})"),
            ("dB20", f"db20({calc_expr})"),
            ("Derivative", f"deriv({calc_expr})"),
            ("Integral", f"integ({calc_expr})"),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, text=expr: self._create_calculator_trace_from_expression(text))
            create_menu.addAction(action)

        menu.addSeparator()
        simenv_menu = menu.addMenu("Send To SimENV")
        simenv_menu.setEnabled(self._simenv_attached)
        act_send_output = QAction("Add Output", self)
        act_send_output.triggered.connect(lambda: self._emit_output_request(calc_expr, primary))
        simenv_menu.addAction(act_send_output)
        for label, meas_type in (
            ("Add AVG Measurement", "AVG"),
            ("Add RMS Measurement", "RMS"),
            ("Add Peak-to-Peak Measurement", "PP"),
            ("Add Frequency Measurement", "PARAM"),
        ):
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, expr=calc_expr, sig=primary, mtype=meas_type:
                self._emit_measurement_request(expr, mtype, sig)
            )
            simenv_menu.addAction(action)

        act_marker = QAction("Add Marker at Active Cursor", self)
        act_marker.triggered.connect(self._on_add_marker)
        menu.addAction(act_marker)

        act_main_form = QAction("Main Form...", self)
        act_main_form.triggered.connect(lambda: self._open_signal_main_form(primary))
        menu.addAction(act_main_form)

        menu.exec(global_pos)

    def _set_signal_visibility(self, names: list[str], visible: bool, fit: bool):
        for name in names:
            trace = self.canvas._trace_by_name.get(name)
            if trace:
                trace.visible = visible
                self._update_stored_trace_visibility(name, visible)
        self._rebuild_signal_list()
        if fit:
            self.canvas.fit_all()
        else:
            self.canvas.update()
        self._refresh_measurements()

    def _isolate_signals(self, names: list[str]):
        selected = set(names)
        for trace in self.canvas.traces:
            trace.visible = trace.name in selected
        self._rebuild_signal_list()
        self.canvas.fit_all()
        self._refresh_measurements()

    def _calculator_expression_for_signal(self, name: str) -> str:
        if re.match(r"^[A-Za-z]\(.*\)$", name):
            return name
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        return f'sig("{escaped}")'

    def _create_calculator_trace_from_expression(self, expression: str):
        self.calc_expr.setText(expression)
        self._on_create_calculator_trace()

    def _open_signal_main_form(self, name: str):
        trace = self.canvas._trace_by_name.get(name)
        if not trace:
            return
        metrics = self._trace_metrics(trace)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"SigView Main Form - {name}")
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.addRow("Signal:", QLabel(trace.name))
        form.addRow("Source:", QLabel(trace.source or "result"))
        form.addRow("Visible:", QLabel("Yes" if trace.visible else "No"))
        form.addRow("Color:", QLabel(trace.color.name()))
        form.addRow("Points:", QLabel(str(min(len(trace.x_data), len(trace.y_data)))))
        if trace.x_data:
            form.addRow("X Range:", QLabel(f"{self.canvas._format_value(min(trace.x_data))} to {self.canvas._format_value(max(trace.x_data))}"))
        for key, label in (
            ("min", "Minimum:"),
            ("max", "Maximum:"),
            ("avg", "Average:"),
            ("rms", "RMS:"),
            ("pkpk", "Peak-to-Peak:"),
            ("freq", "Frequency:"),
        ):
            form.addRow(label, QLabel(self._format_metric(metrics.get(key)) or "-"))
        layout.addLayout(form)

        buttons = QHBoxLayout()
        plot_btn = QPushButton("Plot")
        hide_btn = QPushButton("Unplot")
        isolate_btn = QPushButton("Plot Only")
        calc_btn = QPushButton("Send To Calculator")
        simenv_btn = QPushButton("Add To SimENV")
        plot_btn.clicked.connect(lambda: self._set_signal_visibility([name], True, fit=True))
        hide_btn.clicked.connect(lambda: self._set_signal_visibility([name], False, fit=False))
        isolate_btn.clicked.connect(lambda: self._isolate_signals([name]))
        calc_btn.clicked.connect(lambda: self._set_calculator_expression(self._expression_for_trace(name)))
        simenv_btn.clicked.connect(lambda: self._emit_output_request(self._expression_for_trace(name), name))
        buttons.addWidget(plot_btn)
        buttons.addWidget(hide_btn)
        buttons.addWidget(isolate_btn)
        buttons.addWidget(calc_btn)
        buttons.addWidget(simenv_btn)
        layout.addLayout(buttons)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(dialog.reject)
        layout.addWidget(close_buttons)
        dialog.exec()

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

    def _on_display_mode_changed(self, mode: str):
        clean = str(mode or "line").strip().lower()
        if clean not in {"line", "points", "line_points"}:
            clean = "line"
        self.canvas.set_display_mode(clean)
        for action_name, action_mode in (
            ("menu_display_line", "line"),
            ("menu_display_points", "points"),
            ("menu_display_line_points", "line_points"),
        ):
            action = getattr(self, action_name, None)
            if action is not None and action.isChecked() != (clean == action_mode):
                action.blockSignals(True)
                action.setChecked(clean == action_mode)
                action.blockSignals(False)
        if hasattr(self, "act_points") and self.act_points.isChecked() != (clean == "points"):
            self.act_points.blockSignals(True)
            self.act_points.setChecked(clean == "points")
            self.act_points.blockSignals(False)

    def _on_clear(self):
        self._last_waveforms = {}
        self._x_var = ""
        self._trace_expression_map = {}
        self._calculator_trace_specs = []
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

    def _on_calculator_preset(self, text: str):
        if text:
            self.calc_expr.setText(text)

    def _set_calculator_expression(self, text: str):
        self.calc_expr.setText(text)
        self.side_tabs.setCurrentWidget(self.calc_expr.parentWidget())
        self.calc_expr.setFocus()

    def _on_send_calculator_to_simenv_output(self):
        expression = self.calc_expr.text().strip()
        if not expression:
            QMessageBox.information(self, "SimENV Output", "Enter a calculator expression first.")
            return
        self._emit_output_request(expression, self.calc_name.text().strip())

    def _on_send_calculator_to_simenv_measurement(self):
        expression = self.calc_expr.text().strip()
        if not expression:
            QMessageBox.information(self, "SimENV Measurement", "Enter a calculator expression first.")
            return
        self._emit_measurement_request(expression, "AVG", self.calc_name.text().strip())

    def _emit_output_request(self, expression: str, name_hint: str = ""):
        expr = str(expression or "").strip()
        if not expr:
            return
        if not self._simenv_attached:
            QMessageBox.information(self, "SimENV Output", "This SigView window is not attached to a SimENV session.")
            return
        payload = {
            "signal": str(name_hint or "").strip() or expr,
            "expression": expr,
            "plot": True,
        }
        self.send_to_simenv_output.emit(payload)
        self.statusBar().showMessage(f"Sent expression to SimENV Outputs: {expr}", 4000)

    def _emit_measurement_request(self, expression: str, meas_type: str = "AVG", name_hint: str = ""):
        expr = str(expression or "").strip()
        if not expr:
            return
        if not self._simenv_attached:
            QMessageBox.information(self, "SimENV Measurement", "This SigView window is not attached to a SimENV session.")
            return
        from_time = ""
        to_time = ""
        if self.canvas.cursor_a_x is not None and self.canvas.cursor_b_x is not None:
            lo = min(self.canvas.cursor_a_x, self.canvas.cursor_b_x)
            hi = max(self.canvas.cursor_a_x, self.canvas.cursor_b_x)
            from_time = f"{lo:.16g}"
            to_time = f"{hi:.16g}"
        payload = {
            "name": str(name_hint or "").strip() or self._measurement_name_for_expression(expr, meas_type),
            "type": str(meas_type or "AVG").strip().upper(),
            "expression": expr,
            "target": "",
            "from": from_time,
            "to": to_time,
        }
        self.send_to_simenv_measurement.emit(payload)
        self.statusBar().showMessage(f"Sent measurement to SimENV: {payload['type']} {expr}", 4000)

    def _measurement_name_for_expression(self, expression: str, meas_type: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_]+", "_", expression).strip("_") or "expr"
        return f"{str(meas_type or 'avg').lower()}_{base[:24]}"

    def _on_create_calculator_trace(self):
        expression = self.calc_expr.text().strip()
        if not expression:
            QMessageBox.information(self, "Calculator", "Enter a SigView calculator expression.")
            return
        try:
            result = SigViewCalculatorEngine(self.canvas._trace_by_name).evaluate(expression)
            name, x_data, y_data = self._calculator_result_to_trace(expression, result)
        except Exception as exc:
            QMessageBox.warning(self, "Calculator", str(exc))
            return
        custom_name = self.calc_name.text().strip()
        if custom_name:
            name = custom_name
        name = self._unique_trace_name(name)
        self.canvas.add_trace(name, x_data, y_data, source="calculator")
        self._last_waveforms[name] = list(y_data)
        self._trace_expression_map[name] = expression
        self._remember_expression(expression, name, visible=True)
        self._rebuild_signal_list()
        self.canvas.fit_all()
        self._refresh_measurements()
        self.statusBar().showMessage(f"Created calculator trace: {name}", 4000)

    def _calculator_result_to_trace(self, expression: str, result) -> tuple[str, list[float], list[float]]:
        if isinstance(result, WaveVector):
            n = min(len(result.x_data), len(result.y_data))
            if n < 1:
                raise ValueError("Calculator expression produced an empty waveform.")
            return result.label or expression, list(result.x_data[:n]), list(result.y_data[:n])
        try:
            value = float(result)
        except (TypeError, ValueError) as exc:
            raise ValueError("Calculator expression did not produce numeric data.") from exc
        x_data = self._reference_x_data()
        if not x_data:
            x_data = [0.0, 1.0]
        return expression, list(x_data), [value for _ in x_data]

    def _reference_x_data(self) -> list[float]:
        current = self.signal_list.currentItem()
        if current:
            trace = self.canvas._trace_by_name.get(current.text())
            if trace and trace.x_data:
                return list(trace.x_data)
        for trace in self.canvas.traces:
            if trace.visible and trace.x_data:
                return list(trace.x_data)
        for trace in self.canvas.traces:
            if trace.x_data:
                return list(trace.x_data)
        return []

    def _unique_trace_name(self, base: str) -> str:
        clean = str(base or "calc").strip() or "calc"
        candidate = clean
        idx = 2
        while candidate in self.canvas._trace_by_name:
            candidate = f"{clean}_{idx}"
            idx += 1
        return candidate

    def _on_create_expression_trace(self):
        current = self.signal_list.currentItem()
        mode = self.quick_combo.currentText()
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
        expr = self._expression_for_quick_trace(mode, selected, value_text)
        if expr:
            self._trace_expression_map[name] = expr
            self._remember_expression(expr, name, visible=True)
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

    def _expression_for_quick_trace(self, mode: str, selected: list[str], value_text: str) -> str:
        if not selected:
            return ""
        expr_a = self._expression_for_trace(selected[0])
        if mode in ("Scale selected", "Offset selected"):
            value = str(value_text or "").strip()
            if not value:
                value = "1" if mode.startswith("Scale") else "0"
            return f"({expr_a})*({value})" if mode.startswith("Scale") else f"({expr_a})+({value})"
        if mode == "Abs selected":
            return f"abs({expr_a})"
        if mode == "Derivative selected":
            return f"deriv({expr_a})"
        if len(selected) < 2:
            return expr_a
        expr_b = self._expression_for_trace(selected[1])
        if mode == "A - B":
            return f"({expr_a})-({expr_b})"
        if mode == "A + B":
            return f"({expr_a})+({expr_b})"
        if mode == "A / B":
            return f"({expr_a})/({expr_b})"
        return ""

    # ----- Session persistence -----

    def _on_save_session(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save SigView Session",
            str(Path.home() / "sigview_session.json"),
            "SigView sessions (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self._session_state(), fh, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Save Session", f"Failed to save SigView session:\n{exc}")
            return
        self.statusBar().showMessage(f"Saved SigView session: {path}", 4000)

    def _on_load_session(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load SigView Session",
            str(Path.home()),
            "SigView sessions (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
            self._restore_session_state(state)
        except Exception as exc:
            QMessageBox.critical(self, "Load Session", f"Failed to load SigView session:\n{exc}")
            return
        self.statusBar().showMessage(f"Loaded SigView session: {path}", 4000)

    def _session_state(self) -> dict:
        traces = []
        for trace in self.canvas.traces:
            traces.append({
                "name": trace.name,
                "visible": trace.visible,
                "source": trace.source,
                "color": trace.color.name(),
            })
        return {
            "type": "lumen.sigview.session",
            "version": 1,
            "x_var": self._x_var,
            "waveforms": self._base_waveforms_for_session(),
            "calculator_history": list(self._calculator_history),
            "calculator_traces": list(self._calculator_trace_specs),
            "calculator_state": {
                "expression": self.calc_expr.text().strip() if hasattr(self, "calc_expr") else "",
                "name": self.calc_name.text().strip() if hasattr(self, "calc_name") else "",
            },
            "traces": traces,
            "markers": [{"name": m.name, "x": m.x, "color": m.color.name()} for m in self.canvas.markers],
            "cursors": {"a": self.canvas.cursor_a_x, "b": self.canvas.cursor_b_x, "active": self.canvas.active_cursor},
            "view": {
                "grid": self.canvas.show_grid,
                "stacked": self.canvas.stacked_mode,
                "display_mode": self.canvas.display_mode,
                "x_min": self.canvas.x_min,
                "x_max": self.canvas.x_max,
                "y_min": self.canvas.y_min,
                "y_max": self.canvas.y_max,
            },
        }

    def _base_waveforms_for_session(self) -> dict:
        data: dict[str, list[float]] = {}
        if self._x_var and self._x_var in self._last_waveforms:
            data[self._x_var] = list(self._last_waveforms.get(self._x_var, []))
        for trace in self.canvas.traces:
            if str(trace.source or "") != "result":
                continue
            data[trace.name] = list(trace.y_data)
            if self._x_var and self._x_var not in data and trace.x_data:
                data[self._x_var] = list(trace.x_data)
        return data or dict(self._last_waveforms)

    def _restore_session_state(self, state: dict):
        if not isinstance(state, dict) or state.get("type") != "lumen.sigview.session":
            raise ValueError("This is not a SigView session file.")
        waveforms = state.get("waveforms", {})
        self._calculator_history = [str(x).strip() for x in state.get("calculator_history", []) if str(x).strip()]
        self._calculator_trace_specs = [
            spec for spec in state.get("calculator_traces", [])
            if isinstance(spec, dict) and str(spec.get("expression", "")).strip()
        ]
        self.load_results(waveforms, state.get("x_var", ""), preserve_user_expressions=True)
        trace_state = {entry.get("name"): entry for entry in state.get("traces", []) if isinstance(entry, dict)}
        for trace in self.canvas.traces:
            entry = trace_state.get(trace.name, {})
            trace.visible = bool(entry.get("visible", trace.visible))
            color = entry.get("color")
            if color:
                trace.color = QColor(color)
        self.canvas.clear_markers()
        for entry in state.get("markers", []):
            if not isinstance(entry, dict):
                continue
            try:
                self.canvas.add_marker(entry.get("name", f"M{len(self.canvas.markers) + 1}"), float(entry.get("x", 0.0)), QColor(entry.get("color", "#ffd166")))
            except (TypeError, ValueError):
                continue
        cursors = state.get("cursors", {})
        self.canvas.cursor_a_x = cursors.get("a") if isinstance(cursors, dict) else None
        self.canvas.cursor_b_x = cursors.get("b") if isinstance(cursors, dict) else None
        self.canvas.set_active_cursor(cursors.get("active", "A") if isinstance(cursors, dict) else "A")
        view = state.get("view", {})
        if isinstance(view, dict):
            self._on_toggle_grid(bool(view.get("grid", True)))
            self._on_toggle_stacked(bool(view.get("stacked", False)))
            self._on_display_mode_changed(str(view.get("display_mode", "line")))
            for attr in ("x_min", "x_max", "y_min", "y_max"):
                if attr in view:
                    try:
                        setattr(self.canvas, attr, float(view[attr]))
                    except (TypeError, ValueError):
                        pass
            self.canvas._auto_range = False
        calc_state = state.get("calculator_state", {})
        if isinstance(calc_state, dict):
            self.calc_expr.setText(str(calc_state.get("expression", "") or ""))
            self.calc_name.setText(str(calc_state.get("name", "") or ""))
        self._rebuild_signal_list()
        self._refresh_marker_table()
        self._refresh_measurements()
        self.canvas.update()

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
        trace = self.canvas._trace_by_name.get(name)
        if trace:
            metrics = self._trace_metrics(trace)
            for key in ("min", "max", "avg", "rms", "pkpk", "freq"):
                value = metrics.get(key)
                if value is not None and math.isfinite(value):
                    label = key.upper() if key != "pkpk" else "PkPk"
                    lines.append(f"{label}: {self.canvas._format_value(value)}")

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
            metrics = self._trace_metrics(trace)
            values = [
                self.canvas._format_value(a) if a is not None and ax is not None else "",
                self.canvas._format_value(b) if b is not None and bx is not None else "",
                self.canvas._format_value(b - a) if a is not None and b is not None else "",
                self._format_metric(metrics.get("min")),
                self._format_metric(metrics.get("max")),
                self._format_metric(metrics.get("avg")),
                self._format_metric(metrics.get("rms")),
                self._format_metric(metrics.get("pkpk")),
                self._format_metric(metrics.get("freq")),
            ]
            for col, text in enumerate(values, start=1):
                self.measure_table.setItem(r, col, QTableWidgetItem(text))

    def _format_metric(self, value) -> str:
        if value is None:
            return ""
        try:
            if not math.isfinite(float(value)):
                return ""
        except (TypeError, ValueError):
            return ""
        return self.canvas._format_value(float(value))

    def _trace_metrics(self, trace: TraceRecord) -> dict[str, float | None]:
        finite = [v for v in trace.y_data if isinstance(v, (int, float)) and math.isfinite(v)]
        if not finite:
            return {"min": None, "max": None, "avg": None, "rms": None, "pkpk": None, "freq": None}
        avg = sum(finite) / len(finite)
        rms = math.sqrt(sum(v * v for v in finite) / len(finite))
        return {
            "min": min(finite),
            "max": max(finite),
            "avg": avg,
            "rms": rms,
            "pkpk": max(finite) - min(finite),
            "freq": _vector_freq(WaveVector(trace.x_data, trace.y_data, trace.name)),
        }


# Preferred user-facing alias.
SigViewWindow = WaveformViewerWindow
