from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont
from PySide6.QtCore import Qt, QRectF, QPointF

class SchematicSymbol(QGraphicsItem):
    def __init__(self, name, label=""):
        super().__init__()
        self.name = name
        self.label = label
        self.properties = {} # Property storage
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.grid_size = 20

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

    def boundingRect(self):
        return QRectF(-40, -25, 80, 50)

    def paint(self, painter, option, widget):
        color = QColor("#FFFFFF") if self.isSelected() else QColor("#FFFF00")
        painter.setPen(QPen(color, 2))
        
        # Zig-zag
        points = [QPointF(-40, 0), QPointF(-30, 0), QPointF(-25, -10), QPointF(-15, 10),
                  QPointF(-5, -10), QPointF(5, 10), QPointF(15, -10), QPointF(25, 10),
                  QPointF(30, 0), QPointF(40, 0)]
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i+1])
        
        # Labels (Industrial Look)
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Arial", 9))
        painter.drawText(-20, -15, self.properties["Instance Name"])
        painter.setPen(QColor("#00FF00")) # Green for values
        painter.drawText(-20, 25, self.properties["Value"])

class NfetSymbol(SchematicSymbol):
    def __init__(self, name, label="M1"):
        super().__init__(name, label)
        self.properties = {"W": "1u", "L": "0.18u", "Instance Name": label}

    def boundingRect(self):
        return QRectF(-25, -45, 60, 90)

    def paint(self, painter, option, widget):
        color = QColor("#FFFFFF") if self.isSelected() else QColor("#FFFF00")
        painter.setPen(QPen(color, 2))
        
        # Gate, Source, Drain
        painter.drawLine(-10, -20, -10, 20)
        painter.drawLine(-20, 0, -10, 0)
        painter.drawLine(0, -20, 0, 20)
        painter.drawLine(0, -20, 20, -20)
        painter.drawLine(0, 20, 20, 20)
        painter.drawLine(0, 20, 10, 10)
        painter.drawLine(0, 20, 10, 30)

        # Labels
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Arial", 9))
        painter.drawText(15, -30, self.properties["Instance Name"])
        painter.setPen(QColor("#00FF00"))
        painter.drawText(15, 40, f"W={self.properties['W']}")
        painter.drawText(15, 55, f"L={self.properties['L']}")

class SolderDot(QGraphicsItem):
    def __init__(self, pos):
        super().__init__()
        self.setPos(pos)
        self.setZValue(-2) # Just below wires
        
    def boundingRect(self):
        return QRectF(-4, -4, 8, 8)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor("#00FFFF"))) # Same as Wire
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(-4, -4, 8, 8)
