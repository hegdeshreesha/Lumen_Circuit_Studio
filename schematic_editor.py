import json
from PySide6.QtWidgets import (QMainWindow, QGraphicsView, QGraphicsScene, 
                                 QVBoxLayout, QHBoxLayout, QWidget, QStatusBar, 
                                 QToolBar, QToolButton, QFrame, QLabel, QInputDialog, 
                                 QGraphicsPathItem, QDialog, QFormLayout, QDialogButtonBox, 
                                 QLineEdit, QFileDialog, QRubberBand)
from PySide6.QtGui import (QPainter, QPen, QColor, QBrush, QTransform, QFont, QAction, QKeyEvent, QPainterPath)
from PySide6.QtCore import Qt, QPointF, QRectF, QSize, QRect, Signal
from symbols import SchematicSymbol, ResistorSymbol, NfetSymbol, SolderDot, WireItem, PinSymbol, LabelSymbol

# --- LUMEN SCHEMATIC COLORS ---
COLOR_BG = "#000000"
COLOR_GRID = "#555555"
COLOR_WIRE = "#00FFFF"
COLOR_INST = "#FFFF00"

class PropertyDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle(f"Edit Properties: {item.name}")
        self.layout = QFormLayout(self)
        self.inputs = {}
        for key, value in item.properties.items():
            line_edit = QLineEdit(str(value))
            self.layout.addRow(key, line_edit)
            self.inputs[key] = line_edit
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_values(self):
        return {key: edit.text() for key, edit in self.inputs.items()}

class SchematicView(QGraphicsView):
    debug_msg = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_size = 20
        self.setBackgroundBrush(QColor(COLOR_BG))
        self.setDragMode(QGraphicsView.NoDrag)
        
        # State Control
        self._is_panning = False
        self._is_wiring = False
        self._is_selecting = False
        self._is_zooming = False
        
        self._rubber_band = QRubberBand(QRubberBand.Rectangle, self)
        self._origin = QPointF()
        self._wire_start = None
        self._temp_path = None

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, self.backgroundBrush())
        painter.setPen(QPen(QColor(COLOR_GRID), 1.5))
        left = int(rect.left()) - (int(rect.left()) % self.grid_size)
        top = int(rect.top()) - (int(rect.top()) % self.grid_size)
        for x in range(left, int(rect.right()), self.grid_size):
            for y in range(top, int(rect.bottom()), self.grid_size):
                painter.drawPoint(x, y)

    def snap_to_grid(self, pos):
        x = round(pos.x() / self.grid_size) * self.grid_size
        y = round(pos.y() / self.grid_size) * self.grid_size
        return QPointF(x, y)

    def toggle_wire_mode(self, force_off=False):
        if force_off: self._is_wiring = False
        else: self._is_wiring = not self._is_wiring
        
        self.setCursor(Qt.CrossCursor if self._is_wiring else Qt.ArrowCursor)
        if not self._is_wiring:
            if self._temp_path: self.scene().removeItem(self._temp_path); self._temp_path = None
            self._wire_start = None
        self.debug_msg.emit(f"Mode: {'WIRE' if self._is_wiring else 'SELECT'}")

    def check_for_junction(self, pos):
        items = self.scene().items(pos, Qt.IntersectsItemShape, Qt.DescendingOrder)
        wire_count = sum(1 for i in items if isinstance(i, WireItem))
        if wire_count >= 2:
            if not any(isinstance(i, SolderDot) for i in items):
                self.scene().addItem(SolderDot(pos))

    def mousePressEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        self._origin = event.pos()

        if event.button() == Qt.MiddleButton:
            self._is_panning = True
            self._last_pan_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() == Qt.RightButton:
            self._is_zooming = True
            self._rubber_band.setGeometry(QRect(self._origin, QSize()))
            self._rubber_band.show()
            return

        if event.button() == Qt.LeftButton:
            if self._is_wiring:
                pos = self.snap_to_grid(scene_pos)
                if self._wire_start is None:
                    self.check_for_junction(pos); self._wire_start = pos
                else:
                    path = QPainterPath(); path.moveTo(self._wire_start)
                    inter = QPointF(pos.x(), self._wire_start.y())
                    path.lineTo(inter); path.lineTo(pos)
                    self.scene().addItem(WireItem(path))
                    self.check_for_junction(pos); self._wire_start = pos
            else:
                item = self.itemAt(event.pos())
                if item:
                    super().mousePressEvent(event) # Handle Move/Click
                else:
                    self._is_selecting = True
                    self.scene().clearSelection()
                    self._rubber_band.setGeometry(QRect(self._origin, QSize()))
                    self._rubber_band.show()

    def mouseMoveEvent(self, event):
        if self._is_panning:
            delta = event.pos() - self._last_pan_pos
            self._last_pan_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        elif self._is_zooming or self._is_selecting:
            self._rubber_band.setGeometry(QRect(self._origin, event.pos()).normalized())
        elif self._is_wiring and self._wire_start:
            pos = self.snap_to_grid(self.mapToScene(event.pos()))
            if self._temp_path: self.scene().removeItem(self._temp_path)
            path = QPainterPath(); path.moveTo(self._wire_start)
            inter = QPointF(pos.x(), self._wire_start.y())
            path.lineTo(inter); path.lineTo(pos)
            self._temp_path = self.scene().addPath(path, QPen(QColor(COLOR_WIRE), 1, Qt.DashLine))
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # UNIVERSAL CLEANUP: Reset all drag states regardless of button
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor if not self._is_wiring else Qt.CrossCursor)
        
        if self._is_zooming:
            self._is_zooming = False
            self._rubber_band.hide()
            if self._rubber_band.width() > 10:
                self.fitInView(self.mapToScene(self._rubber_band.geometry()).boundingRect(), Qt.KeepAspectRatio)
        
        if self._is_selecting:
            self._is_selecting = False
            self._rubber_band.hide()
            scene_rect = self.mapToScene(self._rubber_band.geometry()).boundingRect()
            path = QPainterPath(); path.addRect(scene_rect)
            self.scene().setSelectionArea(path)

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if self._is_wiring:
            # Double click finishes the wire net
            self.toggle_wire_mode(force_off=True)
            self.debug_msg.emit("Wiring finished via double-click")
        elif item:
            self.select_entire_net(item)
        else:
            super().mouseDoubleClickEvent(event)

    def select_entire_net(self, start_item):
        self.scene().clearSelection()
        connected = set(); to_process = [start_item]
        while to_process:
            curr = to_process.pop()
            if curr in connected: continue
            connected.add(curr); curr.setSelected(True)
            if hasattr(curr, 'get_connection_points'):
                for pt in curr.get_connection_points():
                    for found in self.scene().items(QRectF(pt.x()-1, pt.y()-1, 2, 2)):
                        if found != curr and hasattr(found, 'get_connection_points'):
                            to_process.append(found)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 0.85
        self.scale(factor, factor)

class SchematicEditor(QMainWindow):
    def __init__(self, cell_name="untitled", theme="dark"):
        super().__init__()
        self.cell_name = cell_name
        self.setWindowTitle(f"Lumen Schematic - {cell_name}")
        self.resize(1100, 750)
        central = QWidget(); self.setCentralWidget(central)
        self.main_layout = QHBoxLayout(central)
        self.main_layout.setContentsMargins(0, 0, 0, 0); self.main_layout.setSpacing(0)
        self.view = SchematicView()
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(-5000, -5000, 10000, 10000)
        self.view.setScene(self.scene)
        self.toolbar = self.create_lumen_toolbar()
        self.main_layout.addWidget(self.toolbar); self.main_layout.addWidget(self.view)
        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.status.setStyleSheet("background-color: #111; color: #888;")
        self.build_menus(); self.apply_theme(theme)

    def build_menus(self):
        menubar = self.menuBar(); file_menu = menubar.addMenu("File")
        save_act = QAction("Save (Ctrl+S)", self); save_act.setShortcut("Ctrl+S")
        save_act.triggered.connect(self.save_schematic); file_menu.addAction(save_act)
        open_act = QAction("Open...", self); open_act.triggered.connect(self.load_schematic); file_menu.addAction(open_act)

    def save_schematic(self):
        data = {"cell": self.cell_name, "items": [i.to_dict() for i in self.scene.items() if hasattr(i, "to_dict")]}
        path, _ = QFileDialog.getSaveFileName(self, "Save Schematic", f"{self.cell_name}.json", "Lumen Files (*.json)")
        if path:
            with open(path, 'w') as f: json.dump(data, f, indent=4)
            self.status.showMessage(f"Saved to {path}")

    def load_schematic(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Schematic", "", "Lumen Files (*.json)")
        if path:
            with open(path, 'r') as f: data = json.load(f)
            self.scene.clear(); self.cell_name = data.get("cell", "untitled")
            self.setWindowTitle(f"Lumen Schematic - {self.cell_name}")
            for d in data["items"]:
                itype = d["type"]; item = None
                if itype == "ResistorSymbol": item = ResistorSymbol.from_dict(d)
                elif itype == "NfetSymbol": item = NfetSymbol.from_dict(d)
                elif itype == "PinSymbol": item = PinSymbol.from_dict(d)
                elif itype == "LabelSymbol": item = LabelSymbol.from_dict(d)
                elif itype == "SolderDot": item = SolderDot.from_dict(d)
                elif itype == "Wire": item = WireItem.from_dict(d)
                if item: self.scene.addItem(item)
            self.status.showMessage(f"Loaded {path}")

    def create_lumen_toolbar(self):
        c = QFrame(); c.setFixedWidth(50); c.setStyleSheet("background-color: #141414; border-right: 1px solid #222;")
        l = QVBoxLayout(c); l.setContentsMargins(5, 10, 5, 10)
        self.add_tool_btn(l, "👆", "Select (Esc)", self.exit_modes)
        self.add_tool_btn(l, "📦", "Instance (I)", self.prompt_instance)
        self.add_tool_btn(l, "📈", "Wire (W)", self.view.toggle_wire_mode)
        self.add_tool_btn(l, "📍", "Pin (P)", self.add_pin_prompt)
        self.add_tool_btn(l, "🖊", "Label (L)", self.add_label_prompt)
        l.addStretch(); return c

    def add_tool_btn(self, layout, icon, tip, func):
        btn = QToolButton(); btn.setText(icon); btn.setToolTip(tip); btn.setFixedSize(40, 40)
        btn.clicked.connect(func); btn.setStyleSheet("QToolButton { background: transparent; font-size: 16pt; color: #aaa; } QToolButton:hover { background: #333; }")
        layout.addWidget(btn)

    def exit_modes(self):
        self.view.toggle_wire_mode(force_off=True)
        self.status.showMessage("Select Mode")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_I: self.prompt_instance()
        elif event.key() == Qt.Key_P: self.add_pin_prompt()
        elif event.key() == Qt.Key_L: self.add_label_prompt()
        elif event.key() == Qt.Key_Q: self.edit_properties()
        elif event.key() == Qt.Key_W: self.view.toggle_wire_mode()
        elif event.key() == Qt.Key_Escape: self.exit_modes()
        elif event.key() in [Qt.Key_Delete, Qt.Key_Backspace]:
            for item in self.scene.selectedItems(): self.scene.removeItem(item)
        super().keyPressEvent(event)

    def add_pin_prompt(self):
        name, ok = QInputDialog.getText(self, "Add Pin", "Pin Name:")
        if ok and name: sym = PinSymbol("pin", label=name); self.place_on_grid(sym)

    def add_label_prompt(self):
        text, ok = QInputDialog.getText(self, "Add Label", "Label Text:")
        if ok and text: sym = LabelSymbol("label", text=text); self.place_on_grid(sym)

    def place_on_grid(self, sym):
        c = self.view.mapToScene(self.view.viewport().rect().center())
        sym.setPos(round(c.x()/20)*20, round(c.y()/20)*20); self.scene.addItem(sym)

    def edit_properties(self):
        sel = self.scene.selectedItems()
        if not sel or not hasattr(sel[0], 'properties'): return
        dialog = PropertyDialog(sel[0], self)
        if dialog.exec(): sel[0].properties = dialog.get_values(); sel[0].update()

    def prompt_instance(self):
        item, ok = QInputDialog.getItem(self, "Add Instance", "Select Component:", ["Resistor", "NFET"], 0, False)
        if ok and item: self.add_instance(item)

    def add_instance(self, comp_type):
        if comp_type == "Resistor": sym = ResistorSymbol("res", label=f"R{len(self.scene.items())}")
        else: sym = NfetSymbol("nfet", label=f"M{len(self.scene.items())}")
        self.place_on_grid(sym)

    def apply_theme(self, theme):
        if theme == "dark":
            self.view.setBackgroundBrush(QColor(COLOR_BG))
            self.setStyleSheet("QMainWindow { background-color: #000; color: #eee; } QMenuBar { background-color: #333; color: #eee; }")
        else:
            self.view.setBackgroundBrush(QColor("#FFFFFF"))
            self.setStyleSheet("QMainWindow { background-color: #F0F0F0; }")
