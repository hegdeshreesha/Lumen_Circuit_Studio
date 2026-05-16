"""
Lumen Circuit Studio — Schematic Editor

Interactive schematic editor with:
- QGraphicsView-based canvas with zoom/pan
- Wire drawing mode
- Component instance placement
- Net label placement
- Grid snapping
- Selection, move, delete
"""
import math
import copy
import re
from collections import defaultdict
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsLineItem, QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsItemGroup,
    QInputDialog, QDialog, QDialogButtonBox, QListWidget,
    QListWidgetItem, QLabel, QHBoxLayout, QApplication, QRubberBand
)
from PyQt6.QtCore import Qt, QPointF, QRect, QRectF, pyqtSignal, QLineF
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainter, QPainterPath, QFont,
    QTransform, QWheelEvent, QKeyEvent
)

from lumen.core.database import LibraryDatabase
from lumen.core.commands import (
    CommandStack, AddItemCommand, DeleteItemsCommand, MoveItemsCommand,
    CompoundCommand, RotateCommand, MirrorCommand, LabelCommand
)
from lumen.gui.branding import apply_window_branding


# ── Constants ─────────────────────────────────────────────────

GRID_SIZE = 10
WIRE_COLOR = QColor("#00b4d8")
WIRE_WIDTH = 2
INSTANCE_COLOR = QColor("#e94560")
INSTANCE_WIDTH = 1.5
PIN_COLOR = QColor("#ffd60a")
PIN_RADIUS = 3
LABEL_COLOR = QColor("#90e0ef")
SELECTION_COLOR = QColor("#533483")
GRID_COLOR_MAJOR = QColor(35, 35, 35)
GRID_COLOR_MINOR = QColor(25, 25, 25)
BG_COLOR = QColor("#0a0a0a")
PIN_GRAVITY_RADIUS = 6.0
WIRE_ENDPOINT_GRAVITY_RADIUS = 3.5


def snap(val: float) -> float:
    """Snap a value to the nearest grid point."""
    return round(val / GRID_SIZE) * GRID_SIZE


# ── Custom Graphics Items ────────────────────────────────────

class WireItem(QGraphicsLineItem):
    """A single wire segment."""

    def __init__(self, x1, y1, x2, y2):
        super().__init__(x1, y1, x2, y2)
        pen = QPen(WIRE_COLOR, WIRE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setFlag(QGraphicsLineItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsLineItem.GraphicsItemFlag.ItemIsMovable)
        self.net_name = ""

    def itemChange(self, change, value):
        if change == QGraphicsLineItem.GraphicsItemChange.ItemSelectedChange:
            if value:
                self.setPen(QPen(SELECTION_COLOR, WIRE_WIDTH + 1))
            else:
                self.setPen(QPen(WIRE_COLOR, WIRE_WIDTH))
        return super().itemChange(change, value)


class NetLabelItem(QGraphicsTextItem):
    """A net name label attached to a wire/net."""

    def __init__(self, text: str, x: float, y: float):
        super().__init__(text)
        self.setPos(x, y)
        self.setDefaultTextColor(LABEL_COLOR)
        font = QFont("Consolas", 9)
        font.setBold(True)
        self.setFont(font)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable)


class SchematicPinItem(QGraphicsItemGroup):
    """Cadence-style schematic terminal with an anchor, direction, and label."""

    DIRECTIONS = ["input", "output", "inout", "power", "ground"]
    USAGES = ["signal", "power", "ground", "clock", "analog"]
    ORIENTATIONS = ["R0", "R90", "R180", "R270"]

    def __init__(self, name: str, x: float, y: float,
                 direction: str = "input", usage: str = "signal",
                 orientation: str = "R0"):
        super().__init__()
        self.pin_name = name
        self.pin_direction = direction if direction in self.DIRECTIONS else "input"
        self.pin_usage = usage if usage in self.USAGES else "signal"
        self.pin_orientation = orientation if orientation in self.ORIENTATIONS else "R0"
        self._items: list = []
        self._build_graphics()
        self.setPos(x, y)
        self.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsMovable)

    def _color(self) -> QColor:
        if self.pin_usage == "power":
            return QColor("#ffb703")
        if self.pin_usage == "ground":
            return QColor("#8ecae6")
        if self.pin_usage == "clock":
            return QColor("#c77dff")
        return PIN_COLOR

    def _orientation_vector(self) -> tuple[int, int]:
        return {
            "R0": (1, 0),
            "R90": (0, -1),
            "R180": (-1, 0),
            "R270": (0, 1),
        }.get(self.pin_orientation, (1, 0))

    def _clear_group(self):
        for item in list(self.childItems()):
            self.removeFromGroup(item)
            if item.scene():
                item.scene().removeItem(item)

    def _build_graphics(self):
        self._clear_group()
        color = self._color()
        pen = QPen(color, 1.2)
        brush = QBrush(color)

        # Reuse xschem pin geometry exactly (ipin/opin/iopin), then orient it.
        def orient_point(x: float, y: float) -> tuple[float, float]:
            if self.pin_orientation == "R90":
                return (y, -x)
            if self.pin_orientation == "R180":
                return (-x, -y)
            if self.pin_orientation == "R270":
                return (-y, x)
            return (x, y)

        pin_kind = self.pin_direction
        if pin_kind in ("power", "ground"):
            pin_kind = "inout"

        if pin_kind == "input":
            line_start = (-5.0, 0.0)
            line_end = (0.0, 0.0)
            poly_pts = [
                (-5.0, 0.0), (-8.75, -5.0), (-17.5, -5.0),
                (-13.75, 0.0), (-17.5, 5.0), (-8.75, 5.0), (-5.0, 0.0),
            ]
            label_anchor = (-18.75, -8.75)
        elif pin_kind == "output":
            line_start = (0.0, 0.0)
            line_end = (8.75, 0.0)
            poly_pts = [
                (17.5, 0.0), (13.75, -5.0), (5.0, -5.0),
                (8.75, 0.0), (5.0, 5.0), (13.75, 5.0), (17.5, 0.0),
            ]
            label_anchor = (20.0, -8.75)
        else:
            line_start = (0.0, 0.0)
            line_end = (3.125, 0.0)
            poly_pts = [
                (13.75, 5.0), (17.5, 0.0), (13.75, -5.0),
                (6.875, -5.0), (3.125, 0.0), (6.875, 5.0), (13.75, 5.0),
            ]
            label_anchor = (19.8438, -9.375)

        # Xschem pin box: B 5 -1.25 -1.25 1.25 1.25
        marker_pts = [orient_point(-1.25, -1.25), orient_point(1.25, 1.25)]
        marker_x = min(marker_pts[0][0], marker_pts[1][0])
        marker_y = min(marker_pts[0][1], marker_pts[1][1])
        marker_w = abs(marker_pts[1][0] - marker_pts[0][0])
        marker_h = abs(marker_pts[1][1] - marker_pts[0][1])
        marker = QGraphicsRectItem(marker_x, marker_y, marker_w, marker_h)
        marker.setPen(pen)
        marker.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.addToGroup(marker)

        lsx, lsy = orient_point(*line_start)
        lex, ley = orient_point(*line_end)
        stub = QGraphicsLineItem(lsx, lsy, lex, ley)
        stub.setPen(pen)
        self.addToGroup(stub)

        poly_path = QPainterPath()
        first = orient_point(*poly_pts[0])
        poly_path.moveTo(first[0], first[1])
        for px, py in poly_pts[1:]:
            ox, oy = orient_point(px, py)
            poly_path.lineTo(ox, oy)
        poly_path.closeSubpath()
        poly_item = QGraphicsPathItem(poly_path)
        poly_item.setPen(pen)
        poly_item.setBrush(brush)
        self.addToGroup(poly_item)

        label = QGraphicsTextItem(self.pin_name)
        label.setDefaultTextColor(color)
        label.setFont(QFont("Consolas", 8, QFont.Weight.DemiBold))
        lx, ly = orient_point(*label_anchor)
        if self.pin_orientation in ("R90", "R270"):
            lx += 4
            ly -= 6
        label.setPos(lx, ly)
        self.addToGroup(label)

    def set_pin_name(self, name: str):
        self.pin_name = name
        self._build_graphics()

    def set_direction(self, direction: str):
        self.pin_direction = direction if direction in self.DIRECTIONS else self.pin_direction
        self._build_graphics()

    def set_usage(self, usage: str):
        self.pin_usage = usage if usage in self.USAGES else self.pin_usage
        self._build_graphics()

    def set_orientation(self, orientation: str):
        self.pin_orientation = orientation if orientation in self.ORIENTATIONS else self.pin_orientation
        self._build_graphics()

    def get_data(self) -> dict:
        pos = self.pos()
        return {
            "name": self.pin_name,
            "x": pos.x(),
            "y": pos.y(),
            "direction": self.pin_direction,
            "usage": self.pin_usage,
            "orientation": self.pin_orientation,
        }


class InstanceItem(QGraphicsItemGroup):
    """A component instance on the schematic."""

    def __init__(self, symbol_data: dict, instance_name: str,
                 x: float, y: float, params: dict = None):
        super().__init__()
        self.symbol_data = symbol_data
        self.instance_name = instance_name
        self.cell_name = symbol_data.get("name", "?")
        self.library_name = symbol_data.get("library", "?")
        self.parameters = dict(params) if params else {}
        self.pin_positions: dict[str, QPointF] = {}

        # Load default parameters
        for p in symbol_data.get("parameters", []):
            if p["name"] not in self.parameters:
                self.parameters[p["name"]] = p.get("default", "")

        self._build_graphics()
        self.setPos(x, y)
        self.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsMovable)

    def _build_graphics(self):
        """Build the visual representation from symbol data."""
        pen = QPen(INSTANCE_COLOR, INSTANCE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        render_options = self.symbol_data.get("render_options", {})
        xschem_symbol = self.symbol_data.get("source_format") == "xschem"

        for shape in self.symbol_data.get("shapes", []):
            stype = shape.get("type", "")
            if stype == "line":
                item = QGraphicsLineItem(
                    shape["x1"], shape["y1"], shape["x2"], shape["y2"])
                item.setPen(pen)
                self.addToGroup(item)
            elif stype == "polyline":
                pts = shape["points"]
                for i in range(len(pts) - 1):
                    item = QGraphicsLineItem(
                        pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
                    item.setPen(pen)
                    self.addToGroup(item)
            elif stype == "circle":
                r = shape["r"]
                item = QGraphicsEllipseItem(
                    shape["cx"] - r, shape["cy"] - r, r * 2, r * 2)
                item.setPen(pen)
                item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                self.addToGroup(item)
            elif stype == "polygon":
                pts = shape["points"]
                path = QPainterPath()
                path.moveTo(pts[0][0], pts[0][1])
                for p in pts[1:]:
                    path.lineTo(p[0], p[1])
                path.closeSubpath()
                item = QGraphicsPathItem(path)
                item.setPen(pen)
                if shape.get("fill"):
                    item.setBrush(QBrush(INSTANCE_COLOR))
                else:
                    item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                self.addToGroup(item)
            elif stype == "rect":
                item = QGraphicsRectItem(
                    shape["x"], shape["y"], shape["w"], shape["h"])
                item.setPen(pen)
                self.addToGroup(item)
            elif stype == "arc":
                rect = QRectF(
                    shape["cx"] - shape["rx"], shape["cy"] - shape["ry"],
                    shape["rx"] * 2, shape["ry"] * 2)
                path = QPainterPath()
                path.arcMoveTo(rect, shape["start"])
                path.arcTo(rect, shape["start"], shape["span"])
                item = QGraphicsPathItem(path)
                item.setPen(pen)
                self.addToGroup(item)
            elif stype == "text":
                text = self._substitute_display_text(shape.get("text", ""))
                if not text:
                    continue
                item = QGraphicsTextItem(text)
                item.setPos(shape.get("x", 0), shape.get("y", 0))
                default_color = "#8fd7e8" if xschem_symbol else "#90e0ef"
                item.setDefaultTextColor(QColor(shape.get("color", default_color)))
                size = int(shape.get("size", 8))
                weight = QFont.Weight.Bold if shape.get("bold", True) else QFont.Weight.Normal
                item.setFont(QFont("Consolas", size, weight))
                if shape.get("rotation"):
                    item.setRotation(float(shape.get("rotation", 0)))
                self.addToGroup(item)

        # Draw pins
        pin_pen = QPen(PIN_COLOR, 1)
        draw_pin_markers = bool(render_options.get("draw_pin_markers", True))
        pin_marker_style = render_options.get("pin_marker_style", "dot")
        marker_size = float(render_options.get("pin_marker_size", PIN_RADIUS * 2))
        for pin in self.symbol_data.get("pins", []):
            px, py = pin["x"], pin["y"]
            if draw_pin_markers:
                if pin_marker_style == "xschem_box":
                    bbox = pin.get("bbox") or []
                    if len(bbox) == 4:
                        x1, y1, x2, y2 = [float(v) for v in bbox]
                        x = min(x1, x2)
                        y = min(y1, y2)
                        w = max(abs(x2 - x1), marker_size)
                        h = max(abs(y2 - y1), marker_size)
                        if w == marker_size:
                            x = px - marker_size / 2
                        if h == marker_size:
                            y = py - marker_size / 2
                    else:
                        x = px - marker_size / 2
                        y = py - marker_size / 2
                        w = marker_size
                        h = marker_size
                    marker = QGraphicsRectItem(x, y, w, h)
                    marker.setPen(pin_pen)
                    marker.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    self.addToGroup(marker)
                elif pin_marker_style == "terminal_box":
                    marker = QGraphicsRectItem(
                        px - marker_size / 2, py - marker_size / 2,
                        marker_size, marker_size)
                    marker.setPen(pin_pen)
                    marker.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    self.addToGroup(marker)
                else:
                    dot = QGraphicsEllipseItem(
                        px - PIN_RADIUS, py - PIN_RADIUS,
                        PIN_RADIUS * 2, PIN_RADIUS * 2)
                    dot.setPen(pin_pen)
                    dot.setBrush(QBrush(PIN_COLOR))
                    self.addToGroup(dot)
            self.pin_positions[pin["name"]] = QPointF(px, py)

        # Instance label
        if render_options.get("use_text_shapes_for_labels"):
            return
        label_data = self.symbol_data.get("label", {})
        label_text = self.instance_name
        if label_data.get("text"):
            label_text = label_data["text"]
            label_text = label_text.replace("@name", self.instance_name)
            for k, v in self.parameters.items():
                label_text = label_text.replace(f"@{k}", str(v))

        lx = label_data.get("x", 15)
        ly = label_data.get("y", -10)
        text_item = QGraphicsTextItem(label_text)
        text_item.setPos(lx, ly - 10)
        text_item.setDefaultTextColor(QColor("#90e0ef"))
        text_item.setFont(QFont("Consolas", 7))
        self.addToGroup(text_item)

    def _substitute_display_text(self, text: str) -> str:
        """Evaluate Cadence-CDF-style display labels such as @name and w=@w."""
        if not text:
            return ""

        values = {
            "name": self.instance_name,
            "inst": self.instance_name,
            "model": self.symbol_data.get("spice_model", self.cell_name),
            "symname": self.cell_name,
            "cell": self.cell_name,
        }
        values.update({str(k): str(v) for k, v in self.parameters.items()})

        def replace(match):
            key = match.group(1)
            return str(values.get(key, match.group(0)))

        return re.sub(r"@([A-Za-z_][A-Za-z0-9_]*)", replace, text)

    def get_properties(self) -> dict:
        """Return a dict of all properties for the property editor."""
        props = {
            "Instance": self.instance_name,
            "Cell": self.cell_name,
            "Library": self.library_name,
        }
        props.update(self.parameters)
        return props

    def get_pin_scene_pos(self, pin_name: str) -> QPointF | None:
        """Get the scene position of a pin."""
        local = self.pin_positions.get(pin_name)
        if local:
            return self.mapToScene(local)
        return None


class JunctionDot(QGraphicsEllipseItem):
    """A small dot indicating a wire junction."""

    def __init__(self, x: float, y: float):
        r = 3.2
        super().__init__(x - r, y - r, r * 2, r * 2)
        self.setPen(QPen(WIRE_COLOR, 1))
        self.setBrush(QBrush(WIRE_COLOR))
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setZValue(8)


# ── Schematic Canvas (QGraphicsView) ─────────────────────────

class SchematicCanvas(QGraphicsView):
    """The main schematic drawing canvas with zoom/pan."""

    coord_changed = pyqtSignal(float, float)

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(BG_COLOR))
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        self._zoom = 1.0
        self._panning = False
        self._pan_start = QPointF()
        self._zoom_band: QRubberBand | None = None
        self._zoom_origin = QPointF()
        self.show_grid = True

    def zoom_by(self, factor: float):
        """Zoom around the current mouse/view anchor."""
        self._zoom *= factor
        self._zoom = max(0.05, min(self._zoom, 100.0))
        self.scale(factor, factor)

    def zoom_in(self):
        self.zoom_by(1.25)

    def zoom_out(self):
        self.zoom_by(0.8)

    def fit_to_items(self):
        """Fit visible design objects, falling back to the scene."""
        rect = self.scene().itemsBoundingRect()
        if rect.isNull() or rect.width() < 1 or rect.height() < 1:
            rect = self.sceneRect()
        margin = max(40.0, min(rect.width(), rect.height()) * 0.15)
        rect = rect.adjusted(-margin, -margin, margin, margin)
        self.resetTransform()
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def zoom_to_view_rect(self, view_rect: QRect):
        """Zoom to a selected rectangle in viewport coordinates."""
        if view_rect.width() < 8 or view_rect.height() < 8:
            return
        scene_rect = self.mapToScene(view_rect.normalized()).boundingRect()
        if scene_rect.width() < 1 or scene_rect.height() < 1:
            return
        self.fitInView(scene_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def wheelEvent(self, event: QWheelEvent):
        """Zoom with mouse wheel."""
        factor = 1.15
        if event.angleDelta().y() > 0:
            self.zoom_by(factor)
        else:
            self.zoom_by(1 / factor)

    def mousePressEvent(self, event):
        """Start panning with middle button."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self._zoom_origin = event.position()
            self._zoom_band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
            origin = self._zoom_origin.toPoint()
            self._zoom_band.setGeometry(QRect(origin, origin))
            self._zoom_band.show()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())
        self.coord_changed.emit(scene_pos.x(), scene_pos.y())
        if self._zoom_band:
            self._zoom_band.setGeometry(
                QRect(self._zoom_origin.toPoint(), event.position().toPoint()).normalized())
            event.accept()
            return
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y()))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self._zoom_band:
            band_rect = self._zoom_band.geometry()
            self._zoom_band.hide()
            self._zoom_band.deleteLater()
            self._zoom_band = None
            self.zoom_to_view_rect(band_rect)
            event.accept()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """Draw the grid background."""
        super().drawBackground(painter, rect)
        if not self.show_grid:
            return

        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE)
        top = int(rect.top()) - (int(rect.top()) % GRID_SIZE)

        # Minor grid (dots)
        painter.setPen(QPen(GRID_COLOR_MINOR, 1))
        points = []
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                points.append(QPointF(x, y))
                y += GRID_SIZE
            x += GRID_SIZE
        if points:
            painter.drawPoints(points)

        # Major grid (every 5th)
        major = GRID_SIZE * 5
        left_m = int(rect.left()) - (int(rect.left()) % major)
        top_m = int(rect.top()) - (int(rect.top()) % major)
        painter.setPen(QPen(GRID_COLOR_MAJOR, 1))
        points = []
        x = left_m
        while x < rect.right():
            y = top_m
            while y < rect.bottom():
                points.append(QPointF(x, y))
                y += major
            x += major
        if points:
            painter.drawPoints(points)


# ── Schematic Editor (Top-level widget) ──────────────────────

class SchematicEditor(QWidget):
    """Complete schematic editor widget with canvas and interaction logic."""

    coord_changed = pyqtSignal(float, float)
    mode_changed = pyqtSignal(str)

    def __init__(self, db: LibraryDatabase, library: str, cell: str,
                 view: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.library = library
        self.cell = cell
        self.view = view
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._mode = "select"
        self._wire_start: QPointF | None = None
        self._wire_preview: QGraphicsLineItem | None = None
        self._wire_preview_h: QGraphicsLineItem | None = None
        self._instance_counter: dict[str, int] = {}
        self._placement_ghost: InstanceItem | None = None
        self._placement_sym_data: dict | None = None
        self._move_start_positions: dict | None = None
        self._clipboard: list[dict] = []

        # Undo/redo
        self.cmd_stack = CommandStack()

        # Data
        self.wires: list[WireItem] = []
        self.instances: list[InstanceItem] = []
        self.labels: list[NetLabelItem] = []
        self.pins: list[SchematicPinItem] = []
        self.junction_dots: list[JunctionDot] = []

        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scene = QGraphicsScene(-2000, -2000, 4000, 4000)
        self.canvas = SchematicCanvas(self.scene, self)
        self.canvas.coord_changed.connect(self.coord_changed.emit)
        self.canvas.setMouseTracking(True)

        # Install event filter for mouse events on scene
        self.scene.mousePressEvent = self._scene_mouse_press
        self.scene.mouseMoveEvent = self._scene_mouse_move
        self.scene.mouseReleaseEvent = self._scene_mouse_release

        layout.addWidget(self.canvas)

    def zoom_in(self):
        self.canvas.zoom_in()

    def zoom_out(self):
        self.canvas.zoom_out()

    def zoom_fit(self):
        self.canvas.fit_to_items()

    def redraw(self):
        self.scene.update()
        self.canvas.viewport().update()

    def set_grid_visible(self, visible: bool):
        self.canvas.show_grid = visible
        self.redraw()

    def set_grid_size(self, value: int):
        global GRID_SIZE
        GRID_SIZE = max(1, int(value))
        self.redraw()

    def set_pan_mode(self):
        self.set_mode("select")
        self.canvas.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.canvas.setCursor(Qt.CursorShape.OpenHandCursor)

    def select_all(self):
        for item in self.wires + self.instances + self.labels + self.pins:
            item.setSelected(True)

    def _get_sym_data(self, library: str, cell: str) -> dict | None:
        """Resolve symbol data, supporting dynamic PDK symbols."""
        if library.startswith("pdk:"):
            pdk_name = library.replace("pdk:", "")
            win = self.window()
            if hasattr(win, 'ciw') and win.ciw and hasattr(win.ciw, 'pdk_registry'):
                registry = win.ciw.pdk_registry
                pdk = registry.get_pdk(pdk_name)
                if pdk:
                    for dev in pdk.devices:
                        if dev.name == cell:
                            if isinstance(getattr(dev, "symbol_data", None), dict):
                                return dev.symbol_data
                            from lumen.core.pdk import generate_symbol_data
                            try:
                                return generate_symbol_data(dev, pdk_name)
                            except Exception:
                                return None
            return None
        return self.db.load_view(library, cell, "symbol")

    def _load_data(self):
        """Load schematic data from the database."""
        if not self.library:
            return
            
        data = None
        if self.library.startswith("pdk:") and self.view == "symbol":
            data = self._get_sym_data(self.library, self.cell)
        else:
            data = self.db.load_view(self.library, self.cell, self.view)
            
        if data:
            if data.get("type") == "symbol":
                # Render symbol directly if opening a symbol view
                item = InstanceItem(data, self.cell, 0, 0)
                item.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable, False)
                item.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsMovable, False)
                self.scene.addItem(item)
                return

            for w in data.get("wires", []):
                wire = WireItem(w["x1"], w["y1"], w["x2"], w["y2"])
                wire.net_name = w.get("net", "")
                wire.wire_kind = w.get("kind", "wire")
                if wire.wire_kind == "bus":
                    wire.setPen(QPen(QColor("#2dd4bf"), WIRE_WIDTH + 1))
                self.scene.addItem(wire)
                self.wires.append(wire)
            for inst in data.get("instances", []):
                sym_data = self._get_sym_data(inst["library"], inst["cell"])
                if sym_data:
                    item = InstanceItem(
                        sym_data, inst["name"],
                        inst["x"], inst["y"], inst.get("params", {}))
                    item.setRotation(float(inst.get("rotation", inst.get("rot", 0))))
                    transform = inst.get("transform")
                    if transform:
                        item.setTransform(QTransform(
                            float(transform.get("m11", 1)),
                            float(transform.get("m12", 0)),
                            float(transform.get("m21", 0)),
                            float(transform.get("m22", 1)),
                            float(transform.get("dx", 0)),
                            float(transform.get("dy", 0)),
                        ))
                    self.scene.addItem(item)
                    self.instances.append(item)
            for lbl in data.get("labels", []):
                item = NetLabelItem(lbl["text"], lbl["x"], lbl["y"])
                self.scene.addItem(item)
                self.labels.append(item)
            for pin in data.get("pins", []):
                item = SchematicPinItem(
                    pin.get("name", ""),
                    pin.get("x", 0),
                    pin.get("y", 0),
                    pin.get("direction", "input"),
                    pin.get("usage", "signal"),
                    pin.get("orientation", "R0"),
                )
                self.scene.addItem(item)
                self.pins.append(item)
            self._refresh_junction_dots()

    def save(self):
        """Save the schematic to the database."""
        if not self.library:
            return
        self.db.save_view(self.library, self.cell, self.view, self.to_data())

    def save_as(self, library: str, cell: str, view: str = "schematic"):
        """Save the current schematic data into another cellview."""
        if not self.db.cell_exists(library, cell):
            self.db.create_cell(library, cell)
        data = self.to_data()
        data["name"] = cell
        data["library"] = library
        self.db.save_view(library, cell, view, data)

    def to_data(self) -> dict:
        """Serialize the current schematic state without writing it."""
        wire_data = []
        for w in self.wires:
            line = w.line()
            pos = w.pos()
            wire_data.append({
                "x1": line.x1() + pos.x(), "y1": line.y1() + pos.y(),
                "x2": line.x2() + pos.x(), "y2": line.y2() + pos.y(),
                "net": w.net_name,
                "kind": getattr(w, "wire_kind", "wire"),
            })
        inst_data = []
        for inst in self.instances:
            pos = inst.pos()
            transform = inst.transform()
            inst_data.append({
                "name": inst.instance_name,
                "cell": inst.cell_name,
                "library": inst.library_name,
                "x": pos.x(), "y": pos.y(),
                "params": inst.parameters,
                "rotation": inst.rotation(),
                "transform": {
                    "m11": transform.m11(),
                    "m12": transform.m12(),
                    "m21": transform.m21(),
                    "m22": transform.m22(),
                    "dx": transform.dx(),
                    "dy": transform.dy(),
                },
            })
        label_data = []
        for lbl in self.labels:
            pos = lbl.pos()
            label_data.append({
                "text": lbl.toPlainText(),
                "x": pos.x(), "y": pos.y()
            })
        pin_data = []
        for pin in self.pins:
            pin_data.append(pin.get_data())
        return {
            "type": "schematic",
            "name": self.cell,
            "library": self.library,
            "wires": wire_data,
            "instances": inst_data,
            "labels": label_data,
            "pins": pin_data
        }

    # ── Mode Management ───────────────────────────────────────

    def set_mode(self, mode: str):
        """Switch the editor mode."""
        self._mode = mode
        self._cancel_current_action()
        self.mode_changed.emit(mode)
        if mode == "select":
            self.canvas.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        elif mode in ("wire", "bus"):
            self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        elif mode in ("place", "pin"):
            self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag)

    def _cancel_current_action(self):
        """Cancel any in-progress action."""
        if self._wire_preview:
            self.scene.removeItem(self._wire_preview)
            self._wire_preview = None
        if self._wire_preview_h:
            self.scene.removeItem(self._wire_preview_h)
            self._wire_preview_h = None
        if self._placement_ghost:
            self.scene.removeItem(self._placement_ghost)
            self._placement_ghost = None
            self._placement_sym_data = None
        self._wire_start = None

    # ── Undo / Redo ───────────────────────────────────────────

    def undo(self):
        if self.cmd_stack.undo():
            self._refresh_junction_dots()

    def redo(self):
        if self.cmd_stack.redo():
            self._refresh_junction_dots()

    def _execute_command(self, command):
        """Execute a command and keep derived visuals like junctions in sync."""
        self.cmd_stack.execute(command)
        self._refresh_junction_dots()

    def _clear_junction_dots(self):
        for dot in self.junction_dots:
            self.scene.removeItem(dot)
        self.junction_dots.clear()

    def _wire_segments(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for wire in self.wires:
            line = wire.line()
            pos = wire.pos()
            a = (line.x1() + pos.x(), line.y1() + pos.y())
            b = (line.x2() + pos.x(), line.y2() + pos.y())
            if (abs(a[0] - b[0]) < 1e-9) and (abs(a[1] - b[1]) < 1e-9):
                continue
            segments.append((a, b))
        return segments

    def _pin_connection_candidates(self) -> list[tuple[float, float]]:
        """Collect pin anchors used for light wire-gravity snapping."""
        points: list[tuple[float, float]] = []

        # Top-level schematic pins.
        for pin in self.pins:
            pos = pin.scenePos()
            points.append((pos.x(), pos.y()))

        # Instance pins (symbol pins transformed into scene coords).
        for inst in self.instances:
            for pin_name in inst.pin_positions.keys():
                p = inst.get_pin_scene_pos(pin_name)
                if p is not None:
                    points.append((p.x(), p.y()))

        return points

    def _wire_endpoint_candidates(self) -> list[tuple[float, float]]:
        """Collect existing wire endpoints for continuity snapping."""
        points: list[tuple[float, float]] = []
        for a, b in self._wire_segments():
            points.append(a)
            points.append(b)
        return points

    def _snap_to_connection(self, x: float, y: float) -> tuple[float, float]:
        """Apply slight gravity while wiring: prefer pins, lightly snap wire ends."""
        best = (x, y)
        best_d2 = PIN_GRAVITY_RADIUS * PIN_GRAVITY_RADIUS
        snapped = False

        # Primary gravity: pins only (what users expect most while wiring).
        for cx, cy in self._pin_connection_candidates():
            dx = cx - x
            dy = cy - y
            d2 = (dx * dx) + (dy * dy)
            if d2 <= best_d2:
                best_d2 = d2
                best = (cx, cy)
                snapped = True

        # Secondary gravity: existing wire endpoints, weaker radius.
        if not snapped:
            endpoint_d2 = WIRE_ENDPOINT_GRAVITY_RADIUS * WIRE_ENDPOINT_GRAVITY_RADIUS
            for cx, cy in self._wire_endpoint_candidates():
                dx = cx - x
                dy = cy - y
                d2 = (dx * dx) + (dy * dy)
                if d2 <= endpoint_d2:
                    endpoint_d2 = d2
                    best = (cx, cy)
        return best

    def _norm_point(self, x: float, y: float) -> tuple[int, int]:
        return (int(round(x)), int(round(y)))

    def _point_on_segment(self, px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> bool:
        ax, ay = a
        bx, by = b
        cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
        if abs(cross) > 1e-6:
            return False
        min_x, max_x = sorted((ax, bx))
        min_y, max_y = sorted((ay, by))
        return min_x - 1e-6 <= px <= max_x + 1e-6 and min_y - 1e-6 <= py <= max_y + 1e-6

    def _is_endpoint(self, p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
        return (
            (abs(p[0] - a[0]) < 1e-6 and abs(p[1] - a[1]) < 1e-6) or
            (abs(p[0] - b[0]) < 1e-6 and abs(p[1] - b[1]) < 1e-6)
        )

    def _segment_intersection(
        self,
        a1: tuple[float, float],
        a2: tuple[float, float],
        b1: tuple[float, float],
        b2: tuple[float, float],
    ) -> tuple[float, float] | None:
        # We mostly draw Manhattan wires; this handles orthogonal and touching endpoints.
        a_vertical = abs(a1[0] - a2[0]) < 1e-6
        b_vertical = abs(b1[0] - b2[0]) < 1e-6

        if a_vertical == b_vertical:
            # Parallel segments: only shared endpoints matter for junction logic.
            for p in (a1, a2):
                if self._point_on_segment(p[0], p[1], b1, b2):
                    return p
            for p in (b1, b2):
                if self._point_on_segment(p[0], p[1], a1, a2):
                    return p
            return None

        v1, v2 = (a1, a2) if a_vertical else (b1, b2)
        h1, h2 = (b1, b2) if a_vertical else (a1, a2)
        x = v1[0]
        y = h1[1]
        if self._point_on_segment(x, y, v1, v2) and self._point_on_segment(x, y, h1, h2):
            return (x, y)
        return None

    def _refresh_junction_dots(self):
        """Show solder dots where three or more wire branches meet."""
        self._clear_junction_dots()
        segments = self._wire_segments()
        if not segments:
            return

        candidates: set[tuple[int, int]] = set()
        for a, b in segments:
            candidates.add(self._norm_point(*a))
            candidates.add(self._norm_point(*b))

        for i, (a1, a2) in enumerate(segments):
            for b1, b2 in segments[i + 1:]:
                ip = self._segment_intersection(a1, a2, b1, b2)
                if ip is not None:
                    candidates.add(self._norm_point(*ip))

        contributions: dict[tuple[int, int], int] = defaultdict(int)
        for nx, ny in candidates:
            px, py = float(nx), float(ny)
            count = 0
            for a, b in segments:
                if not self._point_on_segment(px, py, a, b):
                    continue
                count += 1 if self._is_endpoint((px, py), a, b) else 2
            if count >= 3:
                contributions[(nx, ny)] = count

        for (x, y) in contributions.keys():
            dot = JunctionDot(float(x), float(y))
            self.scene.addItem(dot)
            self.junction_dots.append(dot)

    # ── Delete Selected ───────────────────────────────────────

    def delete_selected(self):
        """Delete all selected items."""
        selected = self.scene.selectedItems()
        if not selected:
            return
        items_to_delete = []
        lists_map = {}
        for item in selected:
            # Walk up to top-level group
            top = item
            while top.parentItem():
                top = top.parentItem()
            if top not in items_to_delete:
                items_to_delete.append(top)
                if isinstance(top, WireItem):
                    lists_map[top] = self.wires
                elif isinstance(top, InstanceItem):
                    lists_map[top] = self.instances
                elif isinstance(top, SchematicPinItem):
                    lists_map[top] = self.pins
                elif isinstance(top, NetLabelItem):
                    lists_map[top] = self.labels
        if items_to_delete:
            cmd = DeleteItemsCommand(self.scene, items_to_delete, lists_map)
            self._execute_command(cmd)

    # ── Rotate / Mirror ───────────────────────────────────────

    def rotate_selected(self, angle: float = 90):
        """Rotate selected instances by angle degrees (with undo)."""
        # Collect top-level instance items
        items_to_rotate = []
        for item in self.scene.selectedItems():
            top = item
            while top.parentItem():
                top = top.parentItem()
            if isinstance(top, InstanceItem):
                items_to_rotate.append(top)

        if not items_to_rotate:
            return

        # Rotate placement ghost (no undo for this, it's temporary)
        if self._placement_ghost:
            self._placement_ghost.setRotation(
                self._placement_ghost.rotation() + angle)

        # Execute rotate command (for undo/redo)
        cmd = RotateCommand(items_to_rotate, angle)
        self._execute_command(cmd)

    def mirror_selected_x(self):
        """Mirror selected instances horizontally (with undo)."""
        # Collect top-level instance items
        items_to_mirror = []
        for item in self.scene.selectedItems():
            top = item
            while top.parentItem():
                top = top.parentItem()
            if isinstance(top, InstanceItem):
                items_to_mirror.append(top)

        if not items_to_mirror:
            return

        # Mirror placement ghost (no undo for this)
        if self._placement_ghost:
            t = self._placement_ghost.transform()
            self._placement_ghost.setTransform(QTransform(-1, 0, 0, 1, 0, 0) * t)

        # Execute mirror command
        cmd = MirrorCommand(items_to_mirror, 'x')
        self._execute_command(cmd)

    def mirror_selected_y(self):
        """Mirror selected instances vertically (with undo)."""
        # Collect top-level instance items
        items_to_mirror = []
        for item in self.scene.selectedItems():
            top = item
            while top.parentItem():
                top = top.parentItem()
            if isinstance(top, InstanceItem):
                items_to_mirror.append(top)

        if not items_to_mirror:
            return

        # Mirror placement ghost (no undo for this)
        if self._placement_ghost:
            t = self._placement_ghost.transform()
            self._placement_ghost.setTransform(QTransform(1, 0, 0, -1, 0, 0) * t)

        # Execute mirror command
        cmd = MirrorCommand(items_to_mirror, 'y')
        self._execute_command(cmd)

    # ── Copy / Paste ──────────────────────────────────────────

    def copy_selected(self):
        """Copy selected schematic objects to the internal clipboard."""
        self._clipboard.clear()
        for item in self.scene.selectedItems():
            top = item
            while top.parentItem():
                top = top.parentItem()
            if isinstance(top, InstanceItem):
                pos = top.pos()
                self._clipboard.append({
                    'type': 'instance', 'sym': top.symbol_data,
                    'name': top.instance_name, 'x': pos.x(), 'y': pos.y(),
                    'params': dict(top.parameters), 'rot': top.rotation(),
                    'transform': {
                        'm11': top.transform().m11(), 'm12': top.transform().m12(),
                        'm21': top.transform().m21(), 'm22': top.transform().m22(),
                        'dx': top.transform().dx(), 'dy': top.transform().dy(),
                    },
                    'library': top.library_name, 'cell': top.cell_name,
                })
            elif isinstance(top, WireItem):
                line = top.line()
                pos = top.pos()
                self._clipboard.append({
                    'type': 'wire',
                    'x1': line.x1() + pos.x(), 'y1': line.y1() + pos.y(),
                    'x2': line.x2() + pos.x(), 'y2': line.y2() + pos.y(),
                    'net': top.net_name,
                    'kind': getattr(top, "wire_kind", "wire"),
                })
            elif isinstance(top, SchematicPinItem):
                data = top.get_data()
                self._clipboard.append({
                    'type': 'pin',
                    'text': data['name'], 'x': data['x'], 'y': data['y'],
                    'direction': data['direction'],
                    'usage': data.get('usage', 'signal'),
                    'orientation': data.get('orientation', 'R0'),
                })
            elif isinstance(top, NetLabelItem):
                pos = top.pos()
                self._clipboard.append({
                    'type': 'label',
                    'text': top.toPlainText(), 'x': pos.x(), 'y': pos.y(),
                })

    def paste_clipboard(self):
        """Paste clipboard items with offset."""
        if not self._clipboard:
            return
        self.scene.clearSelection()
        cmds = []
        for entry in self._clipboard:
            if entry['type'] == 'instance':
                prefix = entry['sym'].get('prefix', 'X')
                count = self._instance_counter.get(prefix, 0)
                self._instance_counter[prefix] = count + 1
                name = f"{prefix}{count}"
                inst = InstanceItem(entry['sym'], name,
                                    entry['x'] + 20, entry['y'] + 20,
                                    dict(entry['params']))
                inst.setRotation(entry['rot'])
                transform = entry.get('transform')
                if transform:
                    inst.setTransform(QTransform(
                        float(transform.get("m11", 1)),
                        float(transform.get("m12", 0)),
                        float(transform.get("m21", 0)),
                        float(transform.get("m22", 1)),
                        float(transform.get("dx", 0)),
                        float(transform.get("dy", 0)),
                    ))
                inst.setSelected(True)
                cmds.append(AddItemCommand(self.scene, inst, self.instances))
            elif entry['type'] == 'wire':
                wire = WireItem(
                    entry['x1'] + 20, entry['y1'] + 20,
                    entry['x2'] + 20, entry['y2'] + 20)
                wire.net_name = entry.get('net', '')
                wire.wire_kind = entry.get('kind', 'wire')
                if wire.wire_kind == 'bus':
                    wire.setPen(QPen(QColor("#2dd4bf"), WIRE_WIDTH + 1))
                wire.setSelected(True)
                cmds.append(AddItemCommand(self.scene, wire, self.wires))
            elif entry['type'] in ('label', 'pin'):
                if entry['type'] == 'pin':
                    pin = SchematicPinItem(
                        entry['text'], entry['x'] + 20, entry['y'] + 20,
                        entry.get('direction', 'input'),
                        entry.get('usage', 'signal'),
                        entry.get('orientation', 'R0'),
                    )
                    cmds.append(AddItemCommand(self.scene, pin, self.pins))
                else:
                    label = NetLabelItem(entry['text'], entry['x'] + 20, entry['y'] + 20)
                    cmds.append(LabelCommand(self.scene, label, self.labels, add=True))
        if cmds:
            self._execute_command(CompoundCommand(cmds))

    def duplicate_selected(self):
        """Duplicate selected instances using the clipboard implementation."""
        self.copy_selected()
        self.paste_clipboard()

    def stretch_selected(self, dx: float, dy: float):
        """Stretch selected wires by moving their second endpoint; move other selected items."""
        moved_items = []
        wire_changed = False
        for item in self.scene.selectedItems():
            top = item
            while top.parentItem():
                top = top.parentItem()
            if isinstance(top, WireItem):
                line = top.line()
                top.setLine(line.x1(), line.y1(), line.x2() + dx, line.y2() + dy)
                wire_changed = True
            elif top not in moved_items and isinstance(top, (InstanceItem, NetLabelItem, SchematicPinItem)):
                moved_items.append(top)
        if moved_items:
            self._execute_command(MoveItemsCommand(moved_items, dx, dy))
        elif wire_changed:
            self._refresh_junction_dots()

    def name_selected_wires(self, net_name: str, as_bus: bool = False):
        """Assign a net or bus name to selected wires."""
        for item in self.scene.selectedItems():
            if isinstance(item, WireItem):
                item.net_name = net_name
                item.wire_kind = "bus" if as_bus else "wire"
                if as_bus:
                    item.setPen(QPen(QColor("#2dd4bf"), WIRE_WIDTH + 1))

    def add_bus_tap(self, name: str):
        """Create a named tap label at the midpoint of the first selected wire."""
        for item in self.scene.selectedItems():
            if isinstance(item, WireItem):
                line = item.line()
                pos = item.pos()
                x = pos.x() + (line.x1() + line.x2()) / 2
                y = pos.y() + (line.y1() + line.y2()) / 2
                label = NetLabelItem(name, x, y)
                label.setDefaultTextColor(QColor("#2dd4bf"))
                self._execute_command(LabelCommand(self.scene, label, self.labels, add=True))
                return True
        return False

    def add_note(self, text: str, x: float = 0, y: float = 0):
        """Add a schematic annotation as a non-net label."""
        note = NetLabelItem(text, x, y)
        note.is_note = True
        note.setDefaultTextColor(QColor("#d0d0d0"))
        self._execute_command(LabelCommand(self.scene, note, self.labels, add=True))

    def selected_summary(self) -> str:
        """Return a compact description of the current selection."""
        rows = []
        for item in self.scene.selectedItems():
            top = item
            while top.parentItem():
                top = top.parentItem()
            if isinstance(top, InstanceItem):
                rows.append(f"{top.instance_name}: {top.library_name}/{top.cell_name}")
            elif isinstance(top, WireItem):
                rows.append(f"Wire: {top.net_name or '<unnamed>'}")
            elif isinstance(top, SchematicPinItem):
                rows.append(f"Pin: {top.pin_name} ({top.pin_direction}, {top.pin_orientation})")
            elif isinstance(top, NetLabelItem):
                rows.append(f"Label: {top.toPlainText()}")
        return "\n".join(dict.fromkeys(rows))

    def selected_instance(self) -> InstanceItem | None:
        """Return the first selected top-level instance."""
        for item in self.scene.selectedItems():
            top = item
            while top.parentItem():
                top = top.parentItem()
            if isinstance(top, InstanceItem):
                return top
        return None

    # ── Keyboard ──────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard shortcuts."""
        key = event.key()
        mod = event.modifiers()

        if key == Qt.Key.Key_Escape:
            self.set_mode('select')
        elif key == Qt.Key.Key_W and mod == Qt.KeyboardModifier.NoModifier:
            self.set_mode('wire')
        elif key == Qt.Key.Key_I and mod == Qt.KeyboardModifier.NoModifier:
            self.start_instance_placement()
        elif key == Qt.Key.Key_L and mod == Qt.KeyboardModifier.NoModifier:
            self.set_mode('label')
        elif key == Qt.Key.Key_P and mod == Qt.KeyboardModifier.NoModifier:
            self.set_mode('pin')
        elif key == Qt.Key.Key_R and mod == Qt.KeyboardModifier.NoModifier:
            self.rotate_selected()
        elif key == Qt.Key.Key_X and mod == Qt.KeyboardModifier.NoModifier:
            self.mirror_selected_x()
        elif key == Qt.Key.Key_Y and mod == Qt.KeyboardModifier.NoModifier:
            self.mirror_selected_y()
        elif key == Qt.Key.Key_Delete:
            self.delete_selected()
        elif key == Qt.Key.Key_Z and mod == Qt.KeyboardModifier.ControlModifier:
            self.undo()
        elif key == Qt.Key.Key_Y and mod == Qt.KeyboardModifier.ControlModifier:
            self.redo()
        elif key == Qt.Key.Key_C and mod == Qt.KeyboardModifier.ControlModifier:
            self.copy_selected()
        elif key == Qt.Key.Key_V and mod == Qt.KeyboardModifier.ControlModifier:
            self.paste_clipboard()
        elif key == Qt.Key.Key_A and mod == Qt.KeyboardModifier.ControlModifier:
            self.select_all()
        else:
            super().keyPressEvent(event)

    # ── Mouse Event Handlers ──────────────────────────────────

    def _scene_mouse_press(self, event):
        """Handle mouse press on the scene."""
        pos = event.scenePos()
        sx, sy = snap(pos.x()), snap(pos.y())

        if event.button() != Qt.MouseButton.LeftButton:
            QGraphicsScene.mousePressEvent(self.scene, event)
            return

        if self._mode in ('wire', 'bus'):
            wx, wy = self._snap_to_connection(sx, sy)
            self._handle_wire_click(wx, wy)
        elif self._mode == 'place':
            self._handle_place_click(sx, sy)
        elif self._mode == 'label':
            self._handle_label_click(sx, sy)
        elif self._mode == 'pin':
            self._handle_pin_click(sx, sy)
        elif self._mode == 'select':
            item = self.scene.itemAt(pos, QTransform())
            if item:
                top = item
                while top.parentItem():
                    top = top.parentItem()
                if isinstance(top, InstanceItem):
                    self._show_instance_properties(top)
                elif isinstance(top, (SchematicPinItem, NetLabelItem, WireItem)):
                    top.setSelected(True)
                    self.show_selected_properties()
                # Record start positions for move tracking.
                self._move_start_positions = {}
                for sel in self.scene.selectedItems():
                    moving = sel
                    while moving.parentItem():
                        moving = moving.parentItem()
                    self._move_start_positions[id(moving)] = QPointF(moving.pos())
            QGraphicsScene.mousePressEvent(self.scene, event)

    def _scene_mouse_move(self, event):
        """Handle mouse move for previews."""
        pos = event.scenePos()
        sx, sy = snap(pos.x()), snap(pos.y())

        if self._mode in ('wire', 'bus') and self._wire_start:
            sx, sy = self._snap_to_connection(sx, sy)
            x1, y1 = self._wire_start.x(), self._wire_start.y()
            # Show Manhattan preview: horizontal segment + vertical segment
            if self._wire_preview:
                if abs(sx - x1) >= abs(sy - y1):
                    self._wire_preview.setLine(x1, y1, sx, y1)
                    if self._wire_preview_h:
                        self._wire_preview_h.setLine(sx, y1, sx, sy)
                        self._wire_preview_h.setVisible(y1 != sy)
                else:
                    self._wire_preview.setLine(x1, y1, x1, sy)
                    if self._wire_preview_h:
                        self._wire_preview_h.setLine(x1, sy, sx, sy)
                        self._wire_preview_h.setVisible(x1 != sx)

        elif self._mode == 'place' and self._placement_ghost:
            self._placement_ghost.setPos(sx, sy)

        QGraphicsScene.mouseMoveEvent(self.scene, event)

    def _scene_mouse_release(self, event):
        """Track moves and create undo command."""
        if self._mode == 'select' and self._move_start_positions:
            moved_items = []
            move_deltas = {}  # item -> (dx, dy)

            for item in self.scene.selectedItems():
                top = item
                while top.parentItem():
                    top = top.parentItem()
                old_pos = self._move_start_positions.get(id(top))
                if old_pos and (top.pos() - old_pos).manhattanLength() > 1:
                    dx = snap(top.pos().x()) - old_pos.x()
                    dy = snap(top.pos().y()) - old_pos.y()
                    top.setPos(snap(top.pos().x()), snap(top.pos().y()))
                    if (dx, dy) != (0, 0):
                        moved_items.append(top)
                        move_deltas[id(top)] = (dx, dy)

            # Create MoveItemsCommand for undo/redo if anything moved
            if moved_items:
                # Calculate total dx, dy for the command (average or most common)
                if moved_items:
                    # Just use the first item's delta for simplicity
                    # A more sophisticated approach would track per-item
                    first_delta = move_deltas.get(id(moved_items[0]), (0, 0))
                    cmd = MoveItemsCommand(moved_items, first_delta[0], first_delta[1])
                    self._execute_command(cmd)

            self._move_start_positions = None
        QGraphicsScene.mouseReleaseEvent(self.scene, event)

    # ── Wire Drawing ──────────────────────────────────────────

    def _handle_wire_click(self, x: float, y: float):
        """Handle a click while in wire-drawing mode."""
        if self._wire_start is None:
            self._wire_start = QPointF(x, y)
            preview_pen = QPen(WIRE_COLOR.lighter(130), 1, Qt.PenStyle.DashLine)
            self._wire_preview = QGraphicsLineItem(x, y, x, y)
            self._wire_preview.setPen(preview_pen)
            self.scene.addItem(self._wire_preview)
            self._wire_preview_h = QGraphicsLineItem(x, y, x, y)
            self._wire_preview_h.setPen(preview_pen)
            self.scene.addItem(self._wire_preview_h)
        else:
            x1, y1 = self._wire_start.x(), self._wire_start.y()
            x2, y2 = x, y
            if x1 != x2 or y1 != y2:
                cmds = []
                if abs(x2 - x1) >= abs(y2 - y1):
                    w1 = WireItem(x1, y1, x2, y1)
                    if self._mode == 'bus':
                        w1.wire_kind = 'bus'
                        w1.setPen(QPen(QColor("#2dd4bf"), WIRE_WIDTH + 1))
                    cmds.append(AddItemCommand(self.scene, w1, self.wires))
                    if y1 != y2:
                        w2 = WireItem(x2, y1, x2, y2)
                        if self._mode == 'bus':
                            w2.wire_kind = 'bus'
                            w2.setPen(QPen(QColor("#2dd4bf"), WIRE_WIDTH + 1))
                        cmds.append(AddItemCommand(self.scene, w2, self.wires))
                else:
                    w1 = WireItem(x1, y1, x1, y2)
                    if self._mode == 'bus':
                        w1.wire_kind = 'bus'
                        w1.setPen(QPen(QColor("#2dd4bf"), WIRE_WIDTH + 1))
                    cmds.append(AddItemCommand(self.scene, w1, self.wires))
                    if x1 != x2:
                        w2 = WireItem(x1, y2, x2, y2)
                        if self._mode == 'bus':
                            w2.wire_kind = 'bus'
                            w2.setPen(QPen(QColor("#2dd4bf"), WIRE_WIDTH + 1))
                        cmds.append(AddItemCommand(self.scene, w2, self.wires))
                self._execute_command(CompoundCommand(cmds))
            self._wire_start = QPointF(x2, y2)
            if self._wire_preview:
                self._wire_preview.setLine(x2, y2, x2, y2)
            if self._wire_preview_h:
                self._wire_preview_h.setLine(x2, y2, x2, y2)
                self._wire_preview_h.setVisible(False)

    # ── Instance Placement ────────────────────────────────────

    def start_instance_placement(self):
        """Open the instance browser, then enter placement mode."""
        dialog = InstanceBrowserDialog(self.db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Use get_symbol_data() which handles both user cells and PDK devices
            sym_data = dialog.get_symbol_data()
            if sym_data is None:
                # Fallback: try loading from DB directly
                lib, cell = dialog.selected_library, dialog.selected_cell
                if lib and cell:
                    sym_data = self.db.load_view(lib, cell, 'symbol')
            if sym_data:
                # Set mode FIRST, before creating ghost
                # (set_mode calls _cancel_current_action which would remove the ghost)
                self._mode = 'place'
                self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag)
                self.canvas.setCursor(Qt.CursorShape.CrossCursor)
                self.mode_changed.emit('place')
                
                # Now create and add the ghost
                self._placement_sym_data = sym_data
                ghost = InstanceItem(sym_data, '?', 0, 0)
                ghost.setOpacity(0.5)
                self.scene.addItem(ghost)
                self._placement_ghost = ghost

    def _handle_place_click(self, x: float, y: float):
        """Place the current component at clicked position."""
        if not self._placement_sym_data:
            return
        sym = self._placement_sym_data
        prefix = sym.get('prefix', 'X')
        count = self._instance_counter.get(prefix, 0)
        self._instance_counter[prefix] = count + 1
        name = f'{prefix}{count}'
        inst = InstanceItem(sym, name, x, y)
        # Copy rotation/mirror from ghost
        if self._placement_ghost:
            inst.setRotation(self._placement_ghost.rotation())
            inst.setTransform(self._placement_ghost.transform())
        cmd = AddItemCommand(self.scene, inst, self.instances)
        self._execute_command(cmd)
        # Keep placing more of the same component
        # (click again to place another, Escape to stop)

    # ── Label Placement ───────────────────────────────────────

    def _handle_label_click(self, x: float, y: float):
        """Place a net label at the clicked position (with undo)."""
        text, ok = QInputDialog.getText(self, "Net Label", "Net name:")
        if ok and text:
            label = NetLabelItem(text, x, y)
            # Use command stack for undo/redo
            cmd = LabelCommand(self.scene, label, self.labels, add=True)
            self._execute_command(cmd)

    def _handle_pin_click(self, x: float, y: float):
        """Place Cadence-style top-level schematic pin(s) at the clicked position."""
        names_text, ok = QInputDialog.getText(
            self, "Create Pin", "Pin name(s), separated by spaces or commas:")
        if not ok or not names_text:
            return
        direction, ok = QInputDialog.getItem(
            self,
            "Pin Direction",
            "Direction:",
            SchematicPinItem.DIRECTIONS,
            0,
            False,
        )
        if not ok:
            return
        usage_default = "power" if direction == "power" else "ground" if direction == "ground" else "signal"
        usage, ok = QInputDialog.getItem(
            self,
            "Pin Usage",
            "Usage:",
            SchematicPinItem.USAGES,
            SchematicPinItem.USAGES.index(usage_default),
            False,
        )
        if not ok:
            return
        orientation, ok = QInputDialog.getItem(
            self,
            "Pin Orientation",
            "Orientation:",
            SchematicPinItem.ORIENTATIONS,
            0,
            False,
        )
        if not ok:
            return
        names = [n for n in names_text.replace(",", " ").split() if n]
        cmds = []
        for index, name in enumerate(names):
            pin = SchematicPinItem(name, x, y + index * GRID_SIZE * 2,
                                   direction, usage, orientation)
            cmds.append(AddItemCommand(self.scene, pin, self.pins))
        if cmds:
            self._execute_command(CompoundCommand(cmds))

    # ── Property Display ──────────────────────────────────────

    def _show_instance_properties(self, inst: InstanceItem):
        """Show properties of a selected instance in the property editor."""
        main_win = self.window()
        if hasattr(main_win, 'prop_editor'):
            props = inst.get_properties()

            def on_change(key, value):
                if key in inst.parameters:
                    inst.parameters[key] = value

            main_win.prop_editor.show_properties(
                f"{inst.instance_name} ({inst.cell_name})",
                props, on_change
            )

    def show_selected_properties(self) -> bool:
        """Refresh the property editor for the current selection."""
        selected = self.scene.selectedItems()
        if not selected:
            return False

        for item in selected:
            top = item
            while top.parentItem():
                top = top.parentItem()
            if isinstance(top, InstanceItem):
                self._show_instance_properties(top)
                return True

        main_win = self.window()
        if not hasattr(main_win, "prop_editor"):
            return False

        item = selected[0]
        while item.parentItem():
            item = item.parentItem()
        if isinstance(item, WireItem):
            line = item.line()
            main_win.prop_editor.show_properties(
                "Wire",
                {
                    "Type": "Wire",
                    "Net": item.net_name or "",
                    "X1": f"{line.x1():.1f}",
                    "Y1": f"{line.y1():.1f}",
                    "X2": f"{line.x2():.1f}",
                    "Y2": f"{line.y2():.1f}",
                },
            )
            return True

        if isinstance(item, SchematicPinItem):
            data = item.get_data()

            def on_change(key, value):
                if key == "Name":
                    item.set_pin_name(value)
                elif key == "Direction":
                    item.set_direction(value)
                elif key == "Usage":
                    item.set_usage(value)
                elif key == "Orientation":
                    item.set_orientation(value)
                elif key == "X":
                    item.setPos(float(value), item.pos().y())
                elif key == "Y":
                    item.setPos(item.pos().x(), float(value))

            main_win.prop_editor.show_properties(
                f"Pin {item.pin_name}",
                {
                    "Type": "Schematic Pin",
                    "Name": data["name"],
                    "Direction": data["direction"],
                    "Usage": data["usage"],
                    "Orientation": data["orientation"],
                    "X": f"{data['x']:.1f}",
                    "Y": f"{data['y']:.1f}",
                },
                on_change,
            )
            return True

        if isinstance(item, NetLabelItem):
            pos = item.pos()
            is_pin = item in self.pins
            props = {
                "Type": "Schematic Pin" if is_pin else "Net Label",
                "Name" if is_pin else "Text": item.toPlainText(),
                "X": f"{pos.x():.1f}",
                "Y": f"{pos.y():.1f}",
            }
            if is_pin:
                props["Direction"] = getattr(item, "port_direction", "inout")
            main_win.prop_editor.show_properties(
                "Schematic Pin" if is_pin else "Net Label",
                props,
            )
            return True

        return False


# ── Instance Browser Dialog ──────────────────────────────────

class InstanceBrowserDialog(QDialog):
    """Dialog for selecting a component to instantiate.
    Shows both user-library cells and PDK devices."""

    def __init__(self, db: LibraryDatabase, parent=None):
        super().__init__(parent)
        self.db = db
        self.selected_library = ""
        self.selected_cell = ""
        self._pdk_device = None  # If a PDK device was selected
        self.setWindowTitle("Add Instance")
        apply_window_branding(self)
        self.setMinimumSize(600, 420)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)

        # Library list
        lib_panel = QVBoxLayout()
        lib_panel.addWidget(QLabel("Library:"))
        self.lib_list = QListWidget()
        for lib in self.db.get_libraries():
            self.lib_list.addItem(lib.name)
            
        # Add active PDK
        pdk_registry = self._get_pdk_registry()
        if pdk_registry:
            pdk = pdk_registry.get_active_pdk()
            if pdk:
                self.lib_list.addItem(f"[PDK] {pdk.display_name}")
                    
        self.lib_list.currentTextChanged.connect(self._on_lib_selected)
        lib_panel.addWidget(self.lib_list)
        layout.addLayout(lib_panel)

        # Cell list
        cell_panel = QVBoxLayout()
        cell_panel.addWidget(QLabel("Cell:"))
        self.cell_list = QListWidget()
        self.cell_list.currentTextChanged.connect(self._on_cell_selected)
        self.cell_list.itemDoubleClicked.connect(self._on_cell_double_clicked)
        cell_panel.addWidget(self.cell_list)

        # Info label
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color:#808080;background:transparent;padding:4px;")
        cell_panel.addWidget(self.info_label)
        layout.addLayout(cell_panel)

        # Buttons
        btn_layout = QVBoxLayout()
        btn_layout.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        btn_layout.addWidget(buttons)
        layout.addLayout(btn_layout)

    def _get_pdk_registry(self):
        editor = self.parent()
        if editor:
            win = editor.window()
            if hasattr(win, 'ciw') and win.ciw and hasattr(win.ciw, 'pdk_registry'):
                return win.ciw.pdk_registry
        return None

    def _on_lib_selected(self, lib_name: str):
        self.selected_library = lib_name
        self._pdk_device = None
        self.cell_list.clear()
        self.info_label.clear()

        if lib_name and lib_name.startswith("[PDK]"):
            # PDK library — list devices
            pdk_registry = self._get_pdk_registry()
            if pdk_registry:
                pdk = pdk_registry.get_active_pdk()
                if pdk:
                    for dev in pdk.devices:
                        category = dev.category.value if hasattr(dev.category, "value") else str(dev.category)
                        self.cell_list.addItem(
                            f"{dev.name}  ({category})")
        else:
            for cell in self.db.get_cells(lib_name):
                self.cell_list.addItem(cell)

    def _on_cell_selected(self, cell_text: str):
        if not cell_text:
            return
        self._pdk_device = None

        if self.selected_library and self.selected_library.startswith("[PDK]"):
            # Extract device name
            dev_name = cell_text.split("  (")[0].strip()
            self.selected_cell = dev_name
            pdk_registry = self._get_pdk_registry()
            if pdk_registry:
                pdk = pdk_registry.get_active_pdk()
                if pdk:
                    for dev in pdk.devices:
                        if dev.name == dev_name:
                            self._pdk_device = dev
                            if isinstance(dev.parameters, dict):
                                params = ", ".join(f"{k}={v}" for k, v in dev.parameters.items())
                            else:
                                params = ", ".join(
                                    f"{p.name}={p.default}" for p in dev.parameters if hasattr(p, "name")
                                )
                            pin_names = []
                            for pin in dev.pins:
                                if isinstance(pin, dict):
                                    pin_names.append(str(pin.get("name", "")))
                                else:
                                    pin_names.append(str(getattr(pin, "name", pin)))
                            self.info_label.setText(
                                f"{dev.description}\n"
                                f"Model: {dev.model}\n"
                                f"Pins: {', '.join([p for p in pin_names if p])}\n"
                                f"Defaults: {params}")
                            break
        else:
            self.selected_cell = cell_text
            self.info_label.clear()

    def _on_cell_double_clicked(self, item):
        """Accept the dialog when a cell is double-clicked."""
        if self.selected_library and self.selected_cell:
            self.accept()

    def get_symbol_data(self) -> dict | None:
        """Get symbol data for the selected component.
        Returns generated symbol for PDK devices, or loads from DB."""
        if self._pdk_device:
            if isinstance(getattr(self._pdk_device, "symbol_data", None), dict):
                return self._pdk_device.symbol_data
            from lumen.core.pdk import generate_symbol_data
            pdk_registry = self._get_pdk_registry()
            pdk = pdk_registry.get_active_pdk() if pdk_registry else None
            pdk_name = pdk.name if pdk else "pdk"
            try:
                return generate_symbol_data(self._pdk_device, pdk_name)
            except Exception:
                return None
        elif self.selected_library and self.selected_cell:
            return self.db.load_view(
                self.selected_library, self.selected_cell, "symbol")
        return None
