from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsPathItem
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPainterPath
from PySide6.QtCore import Qt, QRectF, QPointF

class SchematicSymbol(QGraphicsItem):
    def __init__(self, name, label=""):
        super().__init__()
        self.name = name
        self.label = label
        self.properties = {}
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.grid_size = 20

    def get_connection_points(self):
        # Default implementation: center
        return [self.scenePos()]

    def to_dict(self):
        return {
            "type": self.__class__.__name__,
            "pos": [self.pos().x(), self.pos().y()],
            "properties": self.properties
        }

    @staticmethod
    def from_dict(data):
        cls_name = data["type"]
        if cls_name == "ResistorSymbol": sym = ResistorSymbol("res")
        elif cls_name == "NfetSymbol": sym = NfetSymbol("nfet")
        else: return None
        sym.setPos(data["pos"][0], data["pos"][1])
        sym.properties = data["properties"]
        return sym

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            new_pos = value
            x = round(new_pos.x() / self.grid_size) * self.grid_size
            y = round(new_pos.y() / self.grid_size) * self.grid_size
            return QPointF(x, y)
        return super().itemChange(change, value)

class ResistorSymbol(SchematicSymbol):
    def __init__(self, name, label="R1"):
        super().__init__(name, label)
        self.properties = {"Value": "10k", "Instance Name": label}

    def get_connection_points(self):
        # Resistors connect at left and right edges
        p1 = self.mapToScene(-40, 0)
        p2 = self.mapToScene(40, 0)
        return [p1, p2]

    def boundingRect(self): return QRectF(-40, -25, 80, 50)
    def paint(self, painter, option, widget):
        color = QColor("#FFFFFF") if self.isSelected() else QColor("#FFFF00")
        painter.setPen(QPen(color, 2))
        points = [QPointF(-40, 0), QPointF(-30, 0), QPointF(-25, -10), QPointF(-15, 10),
                  QPointF(-5, -10), QPointF(5, 10), QPointF(15, -10), QPointF(25, 10),
                  QPointF(30, 0), QPointF(40, 0)]
        for i in range(len(points) - 1): painter.drawLine(points[i], points[i+1])
        painter.setPen(QColor("#FFFFFF")); painter.setFont(QFont("Arial", 9))
        painter.drawText(-20, -15, self.properties["Instance Name"])
        painter.setPen(QColor("#00FF00")); painter.drawText(-20, 25, self.properties["Value"])

class NfetSymbol(SchematicSymbol):
    def __init__(self, name, label="M1"):
        super().__init__(name, label)
        self.properties = {"W": "1u", "L": "0.18u", "Instance Name": label}

    def get_connection_points(self):
        # Gate, Source, Drain
        g = self.mapToScene(-20, 0)
        d = self.mapToScene(20, -20)
        s = self.mapToScene(20, 20)
        return [g, d, s]

    def boundingRect(self): return QRectF(-25, -45, 60, 90)
    def paint(self, painter, option, widget):
        color = QColor("#FFFFFF") if self.isSelected() else QColor("#FFFF00")
        painter.setPen(QPen(color, 2))
        painter.drawLine(-10, -20, -10, 20); painter.drawLine(-20, 0, -10, 0)
        painter.drawLine(0, -20, 0, 20); painter.drawLine(0, -20, 20, -20); painter.drawLine(0, 20, 20, 20)
        painter.drawLine(0, 20, 10, 10); painter.drawLine(0, 20, 10, 30)
        painter.setPen(QColor("#FFFFFF")); painter.setFont(QFont("Arial", 9))
        painter.drawText(15, -30, self.properties["Instance Name"])
        painter.setPen(QColor("#00FF00")); painter.drawText(15, 40, f"W={self.properties['W']}"); painter.drawText(15, 55, f"L={self.properties['L']}")

class PinSymbol(SchematicSymbol):
    def __init__(self, name, label="P1", direction="input"):
        super().__init__(name, label); self.properties = {"Name": label, "Direction": direction}
    def get_connection_points(self): return [self.scenePos()]
    def to_dict(self): d = super().to_dict(); d["type"] = "PinSymbol"; return d
    def boundingRect(self): return QRectF(-10, -10, 20, 20)
    def paint(self, painter, option, widget):
        color = QColor("#FFFFFF") if self.isSelected() else QColor("#FF00FF")
        painter.setPen(QPen(color, 2)); painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 50)))
        painter.drawRect(-5, -5, 10, 10); painter.setPen(QColor("#FFFFFF")); painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(10, 5, self.properties["Name"])

class LabelSymbol(SchematicSymbol):
    def __init__(self, name, text="net1"):
        super().__init__(name, text); self.properties = {"Text": text}
    def to_dict(self): d = super().to_dict(); d["type"] = "LabelSymbol"; return d
    def boundingRect(self): return QRectF(-20, -10, 100, 20)
    def paint(self, painter, option, widget):
        color = QColor("#FFFFFF") if self.isSelected() else QColor("#00FFFF")
        painter.setPen(QPen(color, 1)); painter.setFont(QFont("Arial", 9)); painter.drawText(0, 5, self.properties["Text"])

class SolderDot(QGraphicsItem):
    def __init__(self, pos):
        super().__init__(); self.setPos(pos); self.setZValue(-2); self.setFlag(QGraphicsItem.ItemIsSelectable)
    def get_connection_points(self): return [self.scenePos()]
    def to_dict(self): return {"type": "SolderDot", "pos": [self.pos().x(), self.pos().y()]}
    @staticmethod
    def from_dict(data): return SolderDot(QPointF(data["pos"][0], data["pos"][1]))
    def boundingRect(self): return QRectF(-4, -4, 8, 8)
    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing); color = QColor("#FFFFFF") if self.isSelected() else QColor("#00FFFF")
        painter.setBrush(QBrush(color)); painter.setPen(Qt.NoPen); painter.drawEllipse(-4, -4, 8, 8)

class WireItem(QGraphicsPathItem):
    def __init__(self, path, parent=None):
        super().__init__(path, parent); self.setZValue(-1); self.setFlag(QGraphicsItem.ItemIsSelectable)
    def get_connection_points(self):
        p = self.path(); p1 = self.mapToScene(p.elementAt(0).x, p.elementAt(0).y); p2 = self.mapToScene(p.elementAt(p.elementCount()-1).x, p.elementAt(p.elementCount()-1).y)
        return [p1, p2]
    def paint(self, painter, option, widget):
        color = QColor("#FFFFFF") if self.isSelected() else QColor("#00FFFF"); pen = QPen(color, 2); painter.setPen(pen); painter.drawPath(self.path())
    def to_dict(self):
        pts = []; p = self.path()
        for i in range(p.elementCount()): el = p.elementAt(i); pts.append([el.x, el.y])
        return {"type": "Wire", "points": pts}
    @staticmethod
    def from_dict(data):
        path = QPainterPath(); pts = data["points"]
        if not pts: return None
        path.moveTo(pts[0][0], pts[0][1])
        for p in pts[1:]: path.lineTo(p[0], p[1])
        return WireItem(path)
