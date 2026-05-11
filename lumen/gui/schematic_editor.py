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
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsLineItem, QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsItemGroup,
    QInputDialog, QDialog, QDialogButtonBox, QListWidget,
    QListWidgetItem, QLabel, QHBoxLayout, QApplication
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QLineF
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainter, QPainterPath, QFont,
    QTransform, QWheelEvent, QKeyEvent
)

from lumen.core.database import LibraryDatabase
from lumen.core.commands import (
    CommandStack, AddItemCommand, DeleteItemsCommand, MoveItemsCommand,
    CompoundCommand, RotateCommand, MirrorCommand, LabelCommand
)


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
                item.setBrush(QBrush(INSTANCE_COLOR.darker(200)))
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

        # Draw pins
        pin_pen = QPen(PIN_COLOR, 1)
        for pin in self.symbol_data.get("pins", []):
            px, py = pin["x"], pin["y"]
            dot = QGraphicsEllipseItem(
                px - PIN_RADIUS, py - PIN_RADIUS,
                PIN_RADIUS * 2, PIN_RADIUS * 2)
            dot.setPen(pin_pen)
            dot.setBrush(QBrush(PIN_COLOR))
            self.addToGroup(dot)
            self.pin_positions[pin["name"]] = QPointF(px, py)

        # Instance label
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
        r = 3
        super().__init__(x - r, y - r, r * 2, r * 2)
        self.setPen(QPen(WIRE_COLOR, 1))
        self.setBrush(QBrush(WIRE_COLOR))


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

    def wheelEvent(self, event: QWheelEvent):
        """Zoom with mouse wheel."""
        factor = 1.15
        if event.angleDelta().y() > 0:
            self._zoom *= factor
            self.scale(factor, factor)
        else:
            self._zoom /= factor
            self.scale(1 / factor, 1 / factor)

    def mousePressEvent(self, event):
        """Start panning with middle button."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y()))
            event.accept()
        else:
            # Report coordinates
            scene_pos = self.mapToScene(event.position().toPoint())
            self.coord_changed.emit(scene_pos.x(), scene_pos.y())
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """Draw the grid background."""
        super().drawBackground(painter, rect)

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
                self.scene.addItem(wire)
                self.wires.append(wire)
            for inst in data.get("instances", []):
                sym_data = self._get_sym_data(inst["library"], inst["cell"])
                if sym_data:
                    item = InstanceItem(
                        sym_data, inst["name"],
                        inst["x"], inst["y"], inst.get("params", {}))
                    self.scene.addItem(item)
                    self.instances.append(item)
            for lbl in data.get("labels", []):
                item = NetLabelItem(lbl["text"], lbl["x"], lbl["y"])
                self.scene.addItem(item)
                self.labels.append(item)

    def save(self):
        """Save the schematic to the database."""
        if not self.library:
            return
        wire_data = []
        for w in self.wires:
            line = w.line()
            pos = w.pos()
            wire_data.append({
                "x1": line.x1() + pos.x(), "y1": line.y1() + pos.y(),
                "x2": line.x2() + pos.x(), "y2": line.y2() + pos.y(),
                "net": w.net_name
            })
        inst_data = []
        for inst in self.instances:
            pos = inst.pos()
            inst_data.append({
                "name": inst.instance_name,
                "cell": inst.cell_name,
                "library": inst.library_name,
                "x": pos.x(), "y": pos.y(),
                "params": inst.parameters
            })
        label_data = []
        for lbl in self.labels:
            pos = lbl.pos()
            label_data.append({
                "text": lbl.toPlainText(),
                "x": pos.x(), "y": pos.y()
            })
        data = {
            "type": "schematic",
            "name": self.cell,
            "library": self.library,
            "wires": wire_data,
            "instances": inst_data,
            "labels": label_data,
            "pins": []
        }
        self.db.save_view(self.library, self.cell, self.view, data)

    # ── Mode Management ───────────────────────────────────────

    def set_mode(self, mode: str):
        """Switch the editor mode."""
        self._mode = mode
        self._cancel_current_action()
        self.mode_changed.emit(mode)
        if mode == "select":
            self.canvas.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        elif mode == "wire":
            self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == "place":
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
        self.cmd_stack.undo()

    def redo(self):
        self.cmd_stack.redo()

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
                elif isinstance(top, NetLabelItem):
                    lists_map[top] = self.labels
        if items_to_delete:
            cmd = DeleteItemsCommand(self.scene, items_to_delete, lists_map)
            self.cmd_stack.execute(cmd)

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
        self.cmd_stack.execute(cmd)

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
        self.cmd_stack.execute(cmd)

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
        self.cmd_stack.execute(cmd)

    # ── Copy / Paste ──────────────────────────────────────────

    def copy_selected(self):
        """Copy selected instances to clipboard."""
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
                    'params': dict(top.parameters), 'rot': top.rotation()
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
                inst.setSelected(True)
                cmds.append(AddItemCommand(self.scene, inst, self.instances))
        if cmds:
            self.cmd_stack.execute(CompoundCommand(cmds))

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
            for item in self.scene.items():
                item.setSelected(True)
        else:
            super().keyPressEvent(event)

    # ── Mouse Event Handlers ──────────────────────────────────

    def _scene_mouse_press(self, event):
        """Handle mouse press on the scene."""
        pos = event.scenePos()
        sx, sy = snap(pos.x()), snap(pos.y())

        if event.button() == Qt.MouseButton.RightButton:
            # Right-click cancels current action
            if self._mode != 'select':
                self.set_mode('select')
            return

        if event.button() != Qt.MouseButton.LeftButton:
            QGraphicsScene.mousePressEvent(self.scene, event)
            return

        if self._mode == 'wire':
            self._handle_wire_click(sx, sy)
        elif self._mode == 'place':
            self._handle_place_click(sx, sy)
        elif self._mode == 'label':
            self._handle_label_click(sx, sy)
        elif self._mode == 'select':
            item = self.scene.itemAt(pos, QTransform())
            if item:
                while item and not isinstance(item, InstanceItem):
                    item = item.parentItem()
                if isinstance(item, InstanceItem):
                    self._show_instance_properties(item)
                    # Record start positions for move tracking
                    self._move_start_positions = {}
                    for sel in self.scene.selectedItems():
                        top = sel
                        while top.parentItem():
                            top = top.parentItem()
                        self._move_start_positions[id(top)] = QPointF(top.pos())
            QGraphicsScene.mousePressEvent(self.scene, event)

    def _scene_mouse_move(self, event):
        """Handle mouse move for previews."""
        pos = event.scenePos()
        sx, sy = snap(pos.x()), snap(pos.y())

        if self._mode == 'wire' and self._wire_start:
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
                    self.cmd_stack.execute(cmd)

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
                    cmds.append(AddItemCommand(self.scene, w1, self.wires))
                    if y1 != y2:
                        w2 = WireItem(x2, y1, x2, y2)
                        cmds.append(AddItemCommand(self.scene, w2, self.wires))
                else:
                    w1 = WireItem(x1, y1, x1, y2)
                    cmds.append(AddItemCommand(self.scene, w1, self.wires))
                    if x1 != x2:
                        w2 = WireItem(x1, y2, x2, y2)
                        cmds.append(AddItemCommand(self.scene, w2, self.wires))
                self.cmd_stack.execute(CompoundCommand(cmds))
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
        self.cmd_stack.execute(cmd)
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
            self.cmd_stack.execute(cmd)

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
