from PySide6.QtWidgets import (QMainWindow, QGraphicsView, QGraphicsScene, 
                                 QVBoxLayout, QHBoxLayout, QWidget, QStatusBar, 
                                 QToolBar, QToolButton, QFrame, QLabel, QInputDialog, 
                                 QGraphicsPathItem, QDialog, QFormLayout, QDialogButtonBox, QLineEdit)
from PySide6.QtGui import (QPainter, QPen, QColor, QBrush, QTransform, QFont, QAction, QKeyEvent, QPainterPath)
from PySide6.QtCore import Qt, QPointF, QRectF, QSize
from symbols import SchematicSymbol, ResistorSymbol, NfetSymbol, SolderDot

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
            line_edit = QLineEdit(value)
            self.layout.addRow(key, line_edit)
            self.inputs[key] = line_edit
            
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_values(self):
        return {key: edit.text() for key, edit in self.inputs.items()}

class SchematicView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_size = 20
        self.setBackgroundBrush(QColor(COLOR_BG))
        
        # State
        self._is_panning = False
        self._is_wiring = False
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

    def toggle_wire_mode(self):
        self._is_wiring = not self._is_wiring
        if self._is_wiring:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.RubberBandDrag)
            self.setCursor(Qt.ArrowCursor)
            if self._temp_path:
                self.scene().removeItem(self._temp_path)
                self._temp_path = None
            self._wire_start = None

    def snap_to_grid(self, pos):
        x = round(pos.x() / self.grid_size) * self.grid_size
        y = round(pos.y() / self.grid_size) * self.grid_size
        return QPointF(x, y)

    def check_for_junction(self, pos):
        items = self.scene().items(pos, Qt.IntersectsItemShape, Qt.DescendingOrder)
        wire_count = 0
        for item in items:
            if isinstance(item, QGraphicsPathItem):
                wire_count += 1
        if wire_count >= 2:
            if not any(isinstance(i, SolderDot) for i in items):
                dot = SolderDot(pos)
                self.scene().addItem(dot)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._is_panning = True
            self._last_pan_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        elif self._is_wiring and event.button() == Qt.LeftButton:
            pos = self.snap_to_grid(self.mapToScene(event.pos()))
            if self._wire_start is None:
                self.check_for_junction(pos)
                self._wire_start = pos
            else:
                path = QPainterPath()
                path.moveTo(self._wire_start)
                inter = QPointF(pos.x(), self._wire_start.y())
                path.lineTo(inter)
                path.lineTo(pos)
                wire_item = self.scene().addPath(path, QPen(QColor(COLOR_WIRE), 2))
                wire_item.setZValue(-1)
                self.check_for_junction(pos)
                self._wire_start = pos
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning:
            delta = event.pos() - self._last_pan_pos
            self._last_pan_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        elif self._is_wiring and self._wire_start:
            pos = self.snap_to_grid(self.mapToScene(event.pos()))
            if self._temp_path:
                self.scene().removeItem(self._temp_path)
            path = QPainterPath()
            path.moveTo(self._wire_start)
            inter = QPointF(pos.x(), self._wire_start.y())
            path.lineTo(inter)
            path.lineTo(pos)
            self._temp_path = self.scene().addPath(path, QPen(QColor(COLOR_WIRE), 1, Qt.DashLine))
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._is_panning = False
            self.setCursor(Qt.CrossCursor if self._is_wiring else Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 0.85
        self.scale(factor, factor)

class SchematicEditor(QMainWindow):
    def __init__(self, cell_name="untitled", theme="dark"):
        super().__init__()
        self.setWindowTitle(f"Lumen Schematic - {cell_name}")
        self.resize(1100, 750)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.view = SchematicView()
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(-5000, -5000, 10000, 10000)
        self.view.setScene(self.scene)

        self.toolbar = self.create_lumen_toolbar()
        self.main_layout.addWidget(self.toolbar)
        self.main_layout.addWidget(self.view)
        
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.setStyleSheet("background-color: #111; color: #888;")
        self.apply_theme(theme)

    def create_lumen_toolbar(self):
        container = QFrame()
        container.setFixedWidth(50)
        container.setStyleSheet("background-color: #141414; border-right: 1px solid #222;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 10, 5, 10)
        self.add_tool_btn(layout, "👆", "Select (Esc)", self.exit_modes)
        self.add_tool_btn(layout, "📦", "Instance (I)", self.prompt_instance)
        self.add_tool_btn(layout, "📈", "Wire (W)", self.view.toggle_wire_mode)
        layout.addStretch()
        return container

    def add_tool_btn(self, layout, icon, tip, func):
        btn = QToolButton()
        btn.setText(icon)
        btn.setToolTip(tip)
        btn.setFixedSize(40, 40)
        btn.clicked.connect(func)
        btn.setStyleSheet("QToolButton { background: transparent; font-size: 16pt; color: #aaa; } QToolButton:hover { background: #333; }")
        layout.addWidget(btn)

    def exit_modes(self):
        if self.view._is_wiring:
            self.view.toggle_wire_mode()
        self.view.setDragMode(QGraphicsView.RubberBandDrag)
        self.status.showMessage("Select Mode")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_I:
            self.prompt_instance()
        elif event.key() == Qt.Key_Q:
            self.edit_properties()
        elif event.key() == Qt.Key_W:
            self.view.toggle_wire_mode()
            state = "ON" if self.view._is_wiring else "OFF"
            self.status.showMessage(f"Wire Mode: {state}")
        elif event.key() == Qt.Key_Escape:
            self.exit_modes()
        elif event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            for item in self.scene.selectedItems():
                self.scene.removeItem(item)
        super().keyPressEvent(event)

    def edit_properties(self):
        selected = self.scene.selectedItems()
        if not selected or not isinstance(selected[0], SchematicSymbol):
            self.status.showMessage("Please select a component first.")
            return
        
        item = selected[0]
        dialog = PropertyDialog(item, self)
        if dialog.exec():
            item.properties = dialog.get_values()
            item.update()
            self.status.showMessage(f"Updated {item.properties['Instance Name']}")

    def prompt_instance(self):
        items = ["Resistor", "NFET"]
        item, ok = QInputDialog.getItem(self, "Add Instance", "Select Component:", items, 0, False)
        if ok and item:
            self.add_instance(item)

    def add_instance(self, comp_type):
        if comp_type == "Resistor":
            sym = ResistorSymbol("res", label=f"R{len(self.scene.items())}")
        elif comp_type == "NFET":
            sym = NfetSymbol("nfet", label=f"M{len(self.scene.items())}")
        
        center = self.view.mapToScene(self.view.viewport().rect().center())
        grid = 20
        snap_x = round(center.x() / grid) * grid
        snap_y = round(center.y() / grid) * grid
        sym.setPos(snap_x, snap_y)
        self.scene.addItem(sym)
        self.status.showMessage(f"Added {comp_type}")

    def apply_theme(self, theme):
        if theme == "dark":
            self.view.setBackgroundBrush(QColor(COLOR_BG))
            self.setStyleSheet("QMainWindow { background-color: #000; }")
        else:
            self.view.setBackgroundBrush(QColor("#FFFFFF"))
            self.setStyleSheet("QMainWindow { background-color: #F0F0F0; }")
