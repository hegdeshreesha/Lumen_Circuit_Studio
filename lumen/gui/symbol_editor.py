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
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsLineItem, QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsItemGroup,
    QInputDialog, QDialog, QDialogButtonBox, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QFormLayout, QLineEdit,
    QComboBox, QCheckBox, QMessageBox, QToolBar
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QLineF
from PyQt6.QtGui import (
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


def snap(val: float) -> float:
    return round(val / GRID_SIZE) * GRID_SIZE


# ── Pin Graphics Item ─────────────────────────────────────────

class PinItem(QGraphicsItemGroup):
    """A symbol pin that can be moved/edited."""

    def __init__(self, name: str, x: float, y: float,
                 direction: str = "inout", index: int = 0):
        super().__init__()
        self.pin_name = name
        self.pin_direction = direction
        self.pin_index = index

        # Pin dot
        self._dot = QGraphicsEllipseItem(
            -PIN_RADIUS, -PIN_RADIUS, PIN_RADIUS * 2, PIN_RADIUS * 2)
        self._dot.setPen(QPen(PIN_COLOR, 1))
        self._dot.setBrush(QBrush(PIN_COLOR))
        self.addToGroup(self._dot)

        # Pin name label
        self._label = QGraphicsTextItem(name)
        self._label.setDefaultTextColor(PIN_NAME_COLOR)
        self._label.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        self._label.setPos(6, -6)
        self.addToGroup(self._label)

        # Direction indicator (small arrow)
        self._arrow = None
        self._update_arrow()

        self.setPos(x, y)
        self.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

    def _update_arrow(self):
        """Update the direction arrow based on direction."""
        if self._arrow and self._arrow in self.childItems():
            self.removeFromGroup(self._arrow)

        if self.pin_direction == "input":
            # Arrow pointing into symbol
            self._arrow = QGraphicsLineItem(-8, 0, -4, 0)
        elif self.pin_direction == "output":
            # Arrow pointing out of symbol
            self._arrow = QGraphicsLineItem(4, 0, 8, 0)
        elif self.pin_direction in ("power", "ground"):
            # Power pin: small bar
            self._arrow = QGraphicsLineItem(-3, -3, -3, 3)
        else:
            self._arrow = QGraphicsLineItem(0, 0, 0, 0)

        if self._arrow:
            self._arrow.setPen(QPen(PIN_COLOR.lighter(130), 1))
            self._arrow.setOpacity(0.7)
            self.addToGroup(self._arrow)

    def set_pin_name(self, name: str):
        self.pin_name = name
        self._label.setPlainText(name)

    def get_data(self) -> dict:
        pos = self.pos()
        return {
            "name": self.pin_name,
            "x": pos.x(),
            "y": pos.y(),
            "direction": self.pin_direction,
        }


# ── Symbol Canvas ─────────────────────────────────────────────

class SymbolCanvas(QGraphicsView):
    """Canvas for symbol editing."""

    coord_changed = pyqtSignal(float, float)

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

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15
        if event.angleDelta().y() > 0:
            self._zoom *= factor
            self.scale(factor, factor)
        else:
            self._zoom /= factor
            self.scale(1 / factor, 1 / factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())
        self.coord_changed.emit(scene_pos.x(), scene_pos.y())
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
        if event.button() == Qt.MouseButton.MiddleButton:
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

    coord_changed = pyqtSignal(float, float)

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

        pen = QPen(SYMBOL_COLOR, SYMBOL_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        for shape in data.get("shapes", []):
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
            elif stype == "polyline":
                pts = shape["points"]
                path = QPainterPath()
                path.moveTo(pts[0][0], pts[0][1])
                for p in pts[1:]:
                    path.lineTo(p[0], p[1])
                item = QGraphicsPathItem(path)
            elif stype == "polygon":
                pts = shape["points"]
                path = QPainterPath()
                path.moveTo(pts[0][0], pts[0][1])
                for p in pts[1:]:
                    path.lineTo(p[0], p[1])
                path.closeSubpath()
                item = QGraphicsPathItem(path)
                item.setBrush(QBrush(SYMBOL_COLOR.darker(200)))
            elif stype == "arc":
                rect = QRectF(
                    shape["cx"] - shape["rx"], shape["cy"] - shape["ry"],
                    shape["rx"] * 2, shape["ry"] * 2)
                path = QPainterPath()
                path.arcMoveTo(rect, shape.get("start", 0))
                path.arcTo(rect, shape.get("start", 0), shape.get("span", 90))
                item = QGraphicsPathItem(path)

            if item:
                item.setPen(pen)
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

        # Determine prefix from first character of cell name (heuristic)
        prefix = self.cell[0].upper() if self.cell else "X"
        if any(p.lower() in self.cell.lower() for p in ["nmos", "pmos"]):
            prefix = "M"
        elif any(p in self.cell.lower() for p in ["res", "r"]):
            prefix = "R"
        elif any(p in self.cell.lower() for p in ["cap", "c"]):
            prefix = "C"
        elif any(p in self.cell.lower() for p in ["ind", "l"]):
            prefix = "L"

        data = {
            "type": "symbol",
            "name": self.cell,
            "library": self.library,
            "prefix": prefix,
            "spice_model": self.cell,
            "pins": pins,
            "shapes": shapes,
            "parameters": [],
            "label": {"text": "@name", "x": 15, "y": -25},
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
        return None

    # ── Pin Operations ────────────────────────────────────────

    def _add_pin(self, name: str, x: float, y: float,
                 direction: str = "inout"):
        """Add a pin to the symbol."""
        pin = PinItem(name, x, y, direction, len(self._pins))
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

        self._add_pin(name, snap(x), snap(y), direction)

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

        # Also check for port labels in the schematic
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
        self.scene.addItem(label)

    # ── Drawing Operations ────────────────────────────────────

    def _scene_mouse_press(self, event):
        pos = event.scenePos()
        sx, sy = snap(pos.x()), snap(pos.y())

        if event.button() == Qt.MouseButton.LeftButton:
            if self._tool == "pin":
                self._handle_pin_click(sx, sy)
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