"""
Lumen Circuit Studio — Symbol Editor

Interactive symbol editor with:
- Drawing tools (line, rectangle, circle, arc, polygon)
- Pin editor (add/move/rotate, set direction, reorder)
- Auto-symbol generation from schematic
- Template-based PDK symbol generation
- Grid snapping and cross-hair cursor
"""
import math
from typing import Optional
from lumen.qt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsLineItem, QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsItemGroup,
    QInputDialog, QDialog, QDialogButtonBox, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QFormLayout, QLineEdit,
    QComboBox, QCheckBox, QMessageBox, QToolBar, QRubberBand
)
from lumen.qt.QtCore import Qt, QPointF, QRect, QRectF, Signal, QLineF
from lumen.qt.QtGui import (
    QPen, QBrush, QColor, QPainter, QPainterPath, QFont,
    QTransform, QWheelEvent, QKeyEvent, QAction, QCursor
)

from lumen.core.database import LibraryDatabase


# ── Constants ─────────────────────────────────────────────────

GRID_SIZE = 10
SYMBOL_COLOR = QColor("#e94560")
SYMBOL_WIDTH = 1.5
PIN_COLOR = QColor("#ffd60a")
PIN_RADIUS = 3
PIN_NAME_COLOR = QColor("#90e0ef")
GRID_COLOR_MAJOR = QColor(55, 55, 55)
GRID_COLOR_MINOR = QColor(35, 35, 35)
BG_COLOR = QColor("#0a0a0a")

PIN_DIRECTIONS = ["input", "output", "inout", "power", "ground"]
PIN_ORIENTATIONS = ["R0", "R90", "R180", "R270"]


def snap(val: float) -> float:
    return round(val / GRID_SIZE) * GRID_SIZE


# ── Pin Graphics Item ─────────────────────────────────────────

class PinItem(QGraphicsItemGroup):
    """A symbol pin that can be moved/edited."""

    def __init__(self, name: str, x: float, y: float,
                 direction: str = "inout", index: int = 0,
                 orientation: str = "R0"):
        super().__init__()
        self.pin_name = name
        self.pin_direction = direction
        self.pin_index = index
        self.pin_orientation = orientation if orientation in PIN_ORIENTATIONS else "R0"
        self._label = None
        self._build_graphics()

        self.setPos(x, y)
        self.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

    def _orientation_vector(self) -> tuple[int, int]:
        return {
            "R0": (1, 0),
            "R90": (0, -1),
            "R180": (-1, 0),
            "R270": (0, 1),
        }.get(self.pin_orientation, (1, 0))

    def _build_graphics(self):
        """Build a industry-style symbol terminal: square anchor, stub, name."""
        for item in list(self.childItems()):
            self.removeFromGroup(item)
            if item.scene():
                item.scene().removeItem(item)

        pen = QPen(PIN_COLOR, 1.4)
        vx, vy = self._orientation_vector()

        terminal = QGraphicsRectItem(-PIN_RADIUS, -PIN_RADIUS, PIN_RADIUS * 2, PIN_RADIUS * 2)
        terminal.setPen(pen)
        terminal.setBrush(QBrush(PIN_COLOR))
        self.addToGroup(terminal)

        stub = QGraphicsLineItem(0, 0, vx * 18, vy * 18)
        stub.setPen(pen)
        self.addToGroup(stub)

        self._label = QGraphicsTextItem(self.pin_name)
        self._label.setDefaultTextColor(PIN_NAME_COLOR)
        self._label.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        lx = vx * 22
        ly = vy * 22 - 6
        if self.pin_orientation == "R180":
            lx -= max(28, len(self.pin_name) * 7)
        self._label.setPos(lx, ly)
        self.addToGroup(self._label)

        dir_tag = QGraphicsTextItem(self.pin_direction[:1].upper())
        dir_tag.setDefaultTextColor(QColor("#101010"))
        dir_tag.setFont(QFont("Consolas", 5, QFont.Weight.Bold))
        dir_tag.setPos(-2.5, -7)
        self.addToGroup(dir_tag)

    def set_pin_name(self, name: str):
        self.pin_name = name
        self._build_graphics()

    def set_direction(self, direction: str):
        self.pin_direction = direction if direction in PIN_DIRECTIONS else self.pin_direction
        self._build_graphics()

    def set_orientation(self, orientation: str):
        self.pin_orientation = orientation if orientation in PIN_ORIENTATIONS else self.pin_orientation
        self._build_graphics()

    def get_data(self) -> dict:
        pos = self.pos()
        return {
            "name": self.pin_name,
            "x": pos.x(),
            "y": pos.y(),
            "direction": self.pin_direction,
            "orientation": self.pin_orientation,
        }


# ── Symbol Canvas ─────────────────────────────────────────────

class SymbolCanvas(QGraphicsView):
    """Canvas for symbol editing."""

    coord_changed = Signal(float, float)

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(BG_COLOR))
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setMouseTracking(True)

        self._zoom = 1.0
        self._panning = False
        self._pan_start = QPointF()
        self._zoom_band: QRubberBand | None = None
        self._zoom_origin = QPointF()

    def zoom_by(self, factor: float):
        self._zoom *= factor
        self._zoom = max(0.05, min(self._zoom, 100.0))
        self.scale(factor, factor)

    def zoom_in(self):
        self.zoom_by(1.25)

    def zoom_out(self):
        self.zoom_by(0.8)

    def fit_to_items(self):
        rect = self.scene().itemsBoundingRect()
        if rect.isNull() or rect.width() < 1 or rect.height() < 1:
            rect = self.sceneRect()
        margin = max(40.0, min(rect.width(), rect.height()) * 0.2)
        rect = rect.adjusted(-margin, -margin, margin, margin)
        self.resetTransform()
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def zoom_to_view_rect(self, view_rect: QRect):
        if view_rect.width() < 8 or view_rect.height() < 8:
            return
        scene_rect = self.mapToScene(view_rect.normalized()).boundingRect()
        if scene_rect.width() < 1 or scene_rect.height() < 1:
            return
        self.fitInView(scene_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15
        if event.angleDelta().y() > 0:
            self.zoom_by(factor)
        else:
            self.zoom_by(1 / factor)

    def mousePressEvent(self, event):
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
        super().drawBackground(painter, rect)
        gs = GRID_SIZE
        left = int(rect.left()) - (int(rect.left()) % gs)
        top = int(rect.top()) - (int(rect.top()) % gs)

        painter.setPen(QPen(GRID_COLOR_MINOR, 1))
        points = []
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                points.append(QPointF(x, y))
                y += gs
            x += gs
        if points and gs >= 4:
            painter.drawPoints(points)

        # Origin crosshair
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(rect.left()), 0, int(rect.right()), 0)
        painter.drawLine(0, int(rect.top()), 0, int(rect.bottom()))


# ── Symbol Editor Widget ──────────────────────────────────────

class SymbolEditor(QWidget):
    """Interactive symbol editor widget."""

    coord_changed = Signal(float, float)

    def __init__(self, db: LibraryDatabase, library: str, cell: str,
                 view: str = "symbol", parent=None):
        super().__init__(parent)
        self.db = db
        self.library = library
        self.cell = cell
        self.view = view

        self._tool = "select"
        self._drawing = False
        self._draw_start = QPointF()
        self._preview_item = None
        self._clipboard: list[dict] = []
        self._metadata: dict = {}
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []

        # Data
        self._shapes: list[QGraphicsItem] = []
        self._pins: list[PinItem] = []

        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        tb = QHBoxLayout()
        tb.setContentsMargins(4, 2, 4, 2)

        self._tools = {}

        for tool_name, shortcut in [
            ("select", "Esc"),
            ("line", "L"),
            ("rect", "R"),
            ("circle", "C"),
            ("polygon", "P"),
            ("arc", "A"),
            ("pin", "I"),
        ]:
            btn = QPushButton(tool_name)
            btn.setCheckable(True)
            btn.setToolTip(f"{tool_name} ({shortcut})")
            btn.setFixedSize(60, 28)
            btn.clicked.connect(lambda checked, t=tool_name: self._set_tool(t))
            tb.addWidget(btn)
            self._tools[tool_name] = btn

        self._tools["select"].setChecked(True)

        tb.addStretch()

        # Action buttons
        self._btn_auto_gen = QPushButton("Auto-Generate")
        self._btn_auto_gen.setToolTip("Auto-generate symbol from schematic")
        self._btn_auto_gen.clicked.connect(self._auto_generate)
        tb.addWidget(self._btn_auto_gen)

        self._btn_save = QPushButton("Save")
        self._btn_save.clicked.connect(self.save)
        tb.addWidget(self._btn_save)

        layout.addLayout(tb)

        # Canvas
        self.scene = QGraphicsScene(-2000, -2000, 4000, 4000)
        self.canvas = SymbolCanvas(self.scene, self)
        self.canvas.coord_changed.connect(self.coord_changed.emit)
        self.canvas.coord_changed.connect(self._on_coord_changed)

        # Install event handlers
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

    def _snapshot(self) -> dict:
        shapes = []
        for item in self._shapes:
            shape = self._item_to_shape(item)
            if shape:
                shapes.append(shape)
        data = dict(self._metadata)
        data.update({
            "type": "symbol",
            "name": self.cell,
            "library": self.library,
            "pins": [pin.get_data() for pin in self._pins],
            "shapes": shapes,
        })
        return data

    def _push_undo(self):
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._snapshot())
        self._render_symbol(self._undo_stack.pop())
        return True

    def redo(self):
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot())
        self._render_symbol(self._redo_stack.pop())
        return True

    def select_all(self):
        for item in self._shapes + self._pins:
            item.setSelected(True)

    def delete_selected(self):
        self._push_undo()
        self._delete_selected()

    def copy_selected(self):
        self._clipboard.clear()
        for item in self.scene.selectedItems():
            if item in self._shapes:
                shape = self._item_to_shape(item)
                if shape:
                    self._clipboard.append({"type": "shape", "data": shape})
            elif item in self._pins:
                self._clipboard.append({"type": "pin", "data": item.get_data()})

    def paste_clipboard(self):
        if not self._clipboard:
            return
        self._push_undo()
        self.scene.clearSelection()
        for entry in self._clipboard:
            data = dict(entry["data"])
            if entry["type"] == "pin":
                name = data.get("name", "PIN")
                self._add_pin(
                    name,
                    float(data.get("x", 0)) + 20,
                    float(data.get("y", 0)) + 20,
                    data.get("direction", "inout"),
                )
                self._pins[-1].setSelected(True)
            elif entry["type"] == "shape":
                item = self._shape_to_item(self._offset_shape(data, 20, 20))
                if item:
                    self.scene.addItem(item)
                    self._shapes.append(item)
                    item.setSelected(True)

    def duplicate_selected(self):
        self.copy_selected()
        self.paste_clipboard()

    def rotate_selected(self, angle: float = 90):
        self._push_undo()
        for item in self.scene.selectedItems():
            if item in self._shapes or item in self._pins:
                item.setRotation(item.rotation() + angle)

    def mirror_selected(self):
        self._push_undo()
        for item in self.scene.selectedItems():
            if item in self._shapes or item in self._pins:
                item.setTransform(QTransform(-1, 0, 0, 1, 0, 0) * item.transform())

    def selected_properties(self) -> dict:
        selected = self.scene.selectedItems()
        if not selected:
            return {}
        item = selected[0]
        if item in self._pins:
            return item.get_data()
        if item in self._shapes:
            return self._item_to_shape(item) or {"type": type(item).__name__}
        return {"type": type(item).__name__}

    def prompt_add_text(self, label: bool = False):
        text, ok = QInputDialog.getText(
            self,
            "Instance Label" if label else "Text",
            "Text:",
            text="@name" if label else "",
        )
        if ok and text:
            self._push_undo()
            self._add_text(text, 0, 0, is_label=label)

    def pin_names(self) -> list[str]:
        return [pin.pin_name for pin in self._pins]

    def set_pin_order(self, names: list[str]):
        self._push_undo()
        ordered = []
        for name in names:
            for pin in self._pins:
                if pin.pin_name == name and pin not in ordered:
                    ordered.append(pin)
        ordered.extend([pin for pin in self._pins if pin not in ordered])
        self._pins = ordered
        for idx, pin in enumerate(self._pins):
            pin.pin_index = idx

    def update_selected_pin(self, name: str, direction: str, orientation: str = "R0"):
        for item in self.scene.selectedItems():
            if item in self._pins:
                self._push_undo()
                item.set_pin_name(name)
                item.set_direction(direction)
                item.set_orientation(orientation)
                return True
        return False

    def symbol_properties(self) -> dict:
        return {
            "prefix": self._metadata.get("prefix", self.cell[:1].upper() if self.cell else "X"),
            "spice_model": self._metadata.get("spice_model", self.cell),
            "label": self._metadata.get("label", {}).get("text", "@name"),
        }

    def update_symbol_properties(self, prefix: str, spice_model: str, label: str):
        self._push_undo()
        self._metadata["prefix"] = prefix or "X"
        self._metadata["spice_model"] = spice_model or self.cell
        label_data = dict(self._metadata.get("label", {}))
        label_data["text"] = label or "@name"
        label_data.setdefault("x", 15)
        label_data.setdefault("y", -25)
        self._metadata["label"] = label_data

    def cdf_lines(self) -> str:
        params = self._metadata.get("parameters", [])
        return "\n".join(
            f"{p.get('name', '')}={p.get('default', '')}" for p in params
        )

    def update_cdf_lines(self, text: str):
        self._push_undo()
        params = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                name, default = line.split("=", 1)
            else:
                name, default = line, ""
            params.append({
                "name": name.strip(),
                "default": default.strip(),
                "description": "",
            })
        self._metadata["parameters"] = params

    def _set_tool(self, tool: str):
        self._tool = tool
        self._drawing = False
        self._cancel_preview()
        for name, btn in self._tools.items():
            btn.setChecked(name == tool)

    def _cancel_preview(self):
        if self._preview_item:
            self.scene.removeItem(self._preview_item)
            self._preview_item = None

    def _on_coord_changed(self, x: float, y: float):
        # Update status
        pass

    # ── Data Loading / Saving ─────────────────────────────────

    def _load_data(self):
        """Load existing symbol data."""
        data = self.db.load_view(self.library, self.cell, self.view)
        if data:
            self._render_symbol(data)

    def _render_symbol(self, data: dict):
        """Render symbol data onto the canvas."""
        # Clear existing
        self._clear_canvas()
        self._metadata = dict(data)

        pen = QPen(SYMBOL_COLOR, SYMBOL_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        for shape in data.get("shapes", []):
            stype = shape.get("type", "")
            item = self._shape_to_item(shape)

            if item:
                item.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable)
                self.scene.addItem(item)
                self._shapes.append(item)

        # Render pins
        for pin_data in data.get("pins", []):
            self._add_pin(
                pin_data["name"],
                pin_data.get("x", 0),
                pin_data.get("y", 0),
                pin_data.get("direction", "inout"),
                pin_data.get("orientation", "R0"),
            )

    def _clear_canvas(self):
        """Remove all items from canvas."""
        for item in self._shapes:
            self.scene.removeItem(item)
        for pin in self._pins:
            self.scene.removeItem(pin)
        self._shapes.clear()
        self._pins.clear()

    def save(self):
        """Save symbol to database."""
        shapes = []
        for item in self._shapes:
            shape_data = self._item_to_shape(item)
            if shape_data:
                shapes.append(shape_data)

        pins = [pin.get_data() for pin in self._pins]

        # Determine prefix from metadata or first character of cell name (heuristic)
        prefix = self._metadata.get("prefix") or (self.cell[0].upper() if self.cell else "X")
        if any(p.lower() in self.cell.lower() for p in ["nmos", "pmos"]):
            prefix = self._metadata.get("prefix") or "M"
        elif any(p in self.cell.lower() for p in ["res", "r"]):
            prefix = self._metadata.get("prefix") or "R"
        elif any(p in self.cell.lower() for p in ["cap", "c"]):
            prefix = self._metadata.get("prefix") or "C"
        elif any(p in self.cell.lower() for p in ["ind", "l"]):
            prefix = self._metadata.get("prefix") or "L"

        data = {
            "type": "symbol",
            "name": self.cell,
            "library": self.library,
            "prefix": prefix,
            "spice_model": self._metadata.get("spice_model", self.cell),
            "pins": pins,
            "shapes": shapes,
            "parameters": self._metadata.get("parameters", []),
            "label": self._metadata.get("label", {"text": "@name", "x": 15, "y": -25}),
        }

        self.db.save_view(self.library, self.cell, self.view, data)

    def _item_to_shape(self, item: QGraphicsItem) -> Optional[dict]:
        """Convert a QGraphicsItem to a shape dict."""
        if isinstance(item, QGraphicsLineItem):
            line = item.line()
            return {
                "type": "line",
                "x1": line.x1(), "y1": line.y1(),
                "x2": line.x2(), "y2": line.y2(),
            }
        elif isinstance(item, QGraphicsRectItem):
            r = item.rect()
            return {"type": "rect", "x": r.x(), "y": r.y(),
                    "w": r.width(), "h": r.height()}
        elif isinstance(item, QGraphicsEllipseItem):
            r = item.rect()
            return {"type": "circle", "cx": r.center().x(), "cy": r.center().y(),
                    "r": r.width() / 2}
        elif isinstance(item, QGraphicsPathItem):
            # Cannot easily convert back to shape dict, skip
            return None
        elif isinstance(item, QGraphicsTextItem):
            pos = item.pos()
            return {
                "type": "text",
                "text": item.toPlainText(),
                "x": pos.x(),
                "y": pos.y(),
                "label": bool(getattr(item, "is_instance_label", False)),
            }
        return None

    def _shape_to_item(self, shape: dict):
        """Create a graphics item from saved shape data."""
        stype = shape.get("type", "")
        item = None
        if stype == "line":
            item = QGraphicsLineItem(
                shape["x1"], shape["y1"], shape["x2"], shape["y2"])
        elif stype == "rect":
            item = QGraphicsRectItem(
                shape["x"], shape["y"], shape["w"], shape["h"])
        elif stype == "circle":
            r = shape["r"]
            item = QGraphicsEllipseItem(
                shape["cx"] - r, shape["cy"] - r, r * 2, r * 2)
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        elif stype in ("polyline", "polygon"):
            pts = shape.get("points", [])
            if not pts:
                return None
            path = QPainterPath()
            path.moveTo(pts[0][0], pts[0][1])
            for p in pts[1:]:
                path.lineTo(p[0], p[1])
            if stype == "polygon":
                path.closeSubpath()
            item = QGraphicsPathItem(path)
            if stype == "polygon":
                item.setBrush(QBrush(SYMBOL_COLOR.darker(200)))
        elif stype == "arc":
            rect = QRectF(
                shape["cx"] - shape["rx"], shape["cy"] - shape["ry"],
                shape["rx"] * 2, shape["ry"] * 2)
            path = QPainterPath()
            path.arcMoveTo(rect, shape.get("start", 0))
            path.arcTo(rect, shape.get("start", 0), shape.get("span", 90))
            item = QGraphicsPathItem(path)
        elif stype == "text":
            item = QGraphicsTextItem(shape.get("text", ""))
            item.setPos(shape.get("x", 0), shape.get("y", 0))
            item.setDefaultTextColor(PIN_NAME_COLOR)
            item.setFont(QFont("Consolas", 8))
            item.is_instance_label = bool(shape.get("label", False))

        if item:
            if hasattr(item, "setPen"):
                pen = QPen(SYMBOL_COLOR, SYMBOL_WIDTH)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                item.setPen(pen)
            item.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable)
            item.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsMovable)
        return item

    def _offset_shape(self, shape: dict, dx: float, dy: float) -> dict:
        """Offset shape geometry for paste/duplicate."""
        stype = shape.get("type", "")
        if stype == "line":
            for key in ("x1", "x2"):
                shape[key] += dx
            for key in ("y1", "y2"):
                shape[key] += dy
        elif stype == "rect":
            shape["x"] += dx
            shape["y"] += dy
        elif stype == "circle":
            shape["cx"] += dx
            shape["cy"] += dy
        elif stype == "arc":
            shape["cx"] += dx
            shape["cy"] += dy
        elif stype in ("polyline", "polygon"):
            shape["points"] = [[x + dx, y + dy] for x, y in shape.get("points", [])]
        elif stype == "text":
            shape["x"] += dx
            shape["y"] += dy
        return shape

    def _add_text(self, text: str, x: float, y: float, is_label: bool = False):
        item = QGraphicsTextItem(text)
        item.setDefaultTextColor(PIN_NAME_COLOR if is_label else SYMBOL_COLOR.lighter(130))
        item.setFont(QFont("Consolas", 8, QFont.Weight.Bold if is_label else QFont.Weight.Normal))
        item.setPos(x, y)
        item.is_instance_label = is_label
        item.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable)
        item.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable)
        self.scene.addItem(item)
        self._shapes.append(item)

    # ── Pin Operations ────────────────────────────────────────

    def _add_pin(self, name: str, x: float, y: float,
                 direction: str = "inout", orientation: str = "R0"):
        """Add a pin to the symbol."""
        pin = PinItem(name, x, y, direction, len(self._pins), orientation)
        self.scene.addItem(pin)
        self._pins.append(pin)

    def _handle_pin_click(self, x: float, y: float):
        """Place a new pin at the clicked position."""
        name, ok = QInputDialog.getText(self, "Pin Name", "Pin name:")
        if not ok or not name:
            return

        direction, ok = QInputDialog.getItem(
            self, "Pin Direction", "Direction:", PIN_DIRECTIONS, 2)
        if not ok:
            return

        orientation, ok = QInputDialog.getItem(
            self, "Pin Orientation", "Orientation:", PIN_ORIENTATIONS, 0)
        if not ok:
            return

        self._push_undo()
        self._add_pin(name, snap(x), snap(y), direction, orientation)

    def _auto_generate(self):
        """Auto-generate symbol from schematic."""
        # Load schematic
        sch_data = self.db.load_view(self.library, self.cell, "schematic")
        if not sch_data:
            QMessageBox.warning(self, "Error",
                                f"No schematic found for {self.library}/{self.cell}")
            return

        self._clear_canvas()

        # Extract pin names and positions from instances and labels
        pins = []
        for inst in sch_data.get("instances", []):
            cell = inst.get("cell", "")
            # Skip special cells
            if cell in ("gnd", "vdd"):
                continue
            # Get symbol to find pins
            sym = self.db.load_view(inst.get("library", ""), cell, "symbol")
            if sym:
                for pin in sym.get("pins", []):
                    pin_name = pin["name"]
                    # Check if this instance is a top-level port (no parent)
                    # For now, collect all unique pin names
                    if pin_name not in pins:
                        pins.append(pin_name)

        # Also check for explicit top-level pins and port labels in the schematic
        for pin in sch_data.get("pins", []):
            name = pin.get("name", "")
            if name and name not in pins:
                pins.append(name)

        for label in sch_data.get("labels", []):
            text = label.get("text", "")
            # Port labels often start with specific prefixes
            if text and not text.startswith("net"):
                if text not in pins:
                    pins.append(text)

        # If no pins found, create default ones
        if not pins:
            pins = ["PLUS", "MINUS"]

        # Create box symbol
        num_pins = len(pins)
        box_h = max(40, num_pins * 15 + 10)
        box_w = 40

        # Draw box
        box = QGraphicsRectItem(-box_w//2, -box_h//2, box_w, box_h)
        box.setPen(QPen(SYMBOL_COLOR, SYMBOL_WIDTH))
        self.scene.addItem(box)
        self._shapes.append(box)

        # Add pins
        for i, pin_name in enumerate(pins):
            pin_y = -box_h//2 + 10 + i * 15
            self._add_pin(pin_name, -box_w//2 - 10, pin_y, "inout")
            # Add pin lead line
            lead = QGraphicsLineItem(-box_w//2 - 10, pin_y, -box_w//2, pin_y)
            lead.setPen(QPen(SYMBOL_COLOR, SYMBOL_WIDTH))
            self.scene.addItem(lead)
            self._shapes.append(lead)

        # Add label
        label = QGraphicsTextItem(f"@name")
        label.setDefaultTextColor(QColor("#90e0ef"))
        label.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        label.setPos(5, -box_h//2 - 5)
        label.is_instance_label = True
        label.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable)
        label.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable)
        self.scene.addItem(label)
        self._shapes.append(label)

    # ── Drawing Operations ────────────────────────────────────

    def _scene_mouse_press(self, event):
        pos = event.scenePos()
        sx, sy = snap(pos.x()), snap(pos.y())

        if event.button() == Qt.MouseButton.LeftButton:
            if self._tool == "pin":
                self._handle_pin_click(sx, sy)
                return
            elif self._tool in ("text", "label"):
                text, ok = QInputDialog.getText(
                    self,
                    "Instance Label" if self._tool == "label" else "Text",
                    "Text:",
                    text="@name" if self._tool == "label" else "",
                )
                if ok and text:
                    self._push_undo()
                    self._add_text(text, sx, sy, is_label=self._tool == "label")
                return
            elif self._tool in ("line", "rect", "circle", "polygon"):
                self._drawing = True
                self._draw_start = QPointF(sx, sy)
                return

        QGraphicsScene.mousePressEvent(self.scene, event)

    def _scene_mouse_move(self, event):
        pos = event.scenePos()
        sx, sy = snap(pos.x()), snap(pos.y())

        if self._drawing and self._tool in ("line", "rect", "circle"):
            self._cancel_preview()
            pen = QPen(SYMBOL_COLOR.lighter(130), 1, Qt.PenStyle.DashLine)
            x1, y1 = self._draw_start.x(), self._draw_start.y()

            if self._tool == "line":
                self._preview_item = QGraphicsLineItem(x1, y1, sx, sy)
            elif self._tool == "rect":
                self._preview_item = QGraphicsRectItem(
                    min(x1, sx), min(y1, sy), abs(sx - x1), abs(sy - y1))
            elif self._tool == "circle":
                r = math.sqrt((sx - x1)**2 + (sy - y1)**2)
                self._preview_item = QGraphicsEllipseItem(x1 - r, y1 - r, r*2, r*2)

            if self._preview_item:
                self._preview_item.setPen(pen)
                self.scene.addItem(self._preview_item)

        QGraphicsScene.mouseMoveEvent(self.scene, event)

    def _scene_mouse_release(self, event):
        if self._drawing and self._tool in ("line", "rect", "circle", "polygon"):
            self._drawing = False
            self._cancel_preview()

            pos = event.scenePos()
            sx, sy = snap(pos.x()), snap(pos.y())
            x1, y1 = self._draw_start.x(), self._draw_start.y()
            pen = QPen(SYMBOL_COLOR, SYMBOL_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)

            item = None
            if self._tool == "line" and (sx != x1 or sy != y1):
                item = QGraphicsLineItem(x1, y1, sx, sy)
            elif self._tool == "rect" and (sx != x1 and sy != y1):
                item = QGraphicsRectItem(
                    min(x1, sx), min(y1, sy), abs(sx - x1), abs(sy - y1))
            elif self._tool == "circle":
                r = math.sqrt((sx - x1)**2 + (sy - y1)**2)
                if r > 2:
                    item = QGraphicsEllipseItem(x1 - r, y1 - r, r*2, r*2)
                    item.setBrush(QBrush(Qt.BrushStyle.NoBrush))

            if item:
                self._push_undo()
                item.setPen(pen)
                item.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable)
                self.scene.addItem(item)
                self._shapes.append(item)

            self._cancel_preview()

        QGraphicsScene.mouseReleaseEvent(self.scene, event)

    # ── Keyboard Shortcuts ────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._set_tool("select")
            self._drawing = False
            self._cancel_preview()
        elif key == Qt.Key.Key_Delete:
            self._delete_selected()
        elif key == Qt.Key.Key_L:
            self._set_tool("line")
        elif key == Qt.Key.Key_R:
            self._set_tool("rect")
        elif key == Qt.Key.Key_C:
            self._set_tool("circle")
        elif key == Qt.Key.Key_P:
            self._set_tool("polygon")
        elif key == Qt.Key.Key_I:
            self._set_tool("pin")
        elif key == Qt.Key.Key_T:
            self._set_tool("text")
        elif key == Qt.Key.Key_S and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.save()
        else:
            super().keyPressEvent(event)

    def _delete_selected(self):
        """Delete selected items."""
        selected = self.scene.selectedItems()
        for item in selected:
            if item in self._shapes:
                self._shapes.remove(item)
                self.scene.removeItem(item)
            elif item in self._pins:
                self._pins.remove(item)
                self.scene.removeItem(item)
