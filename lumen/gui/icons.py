"""Small generated toolbar icons for the editor UI."""

from lumen.qt.QtCore import Qt, QRectF
from lumen.qt.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


ICON_COLOR = QColor("#36b8d0")
ACCENT_COLOR = QColor("#ffd166")
MUTED_COLOR = QColor("#b8c1d1")


def editor_icon(name: str) -> QIcon:
    """Return a lightweight vector-style icon for editor actions."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(ICON_COLOR, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    accent = QPen(ACCENT_COLOR, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    muted = QPen(MUTED_COLOR, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    if name == "open":
        p.drawRect(6, 11, 20, 13)
        p.drawLine(6, 11, 12, 7)
        p.drawLine(12, 7, 26, 7)
    elif name == "save":
        p.drawRect(7, 5, 18, 22)
        p.drawRect(10, 8, 10, 6)
        p.drawLine(11, 23, 21, 23)
    elif name == "check":
        p.drawRect(6, 6, 20, 20)
        p.setPen(accent)
        p.drawLine(10, 17, 14, 21)
        p.drawLine(14, 21, 23, 11)
    elif name == "undo":
        p.drawArc(QRectF(8, 9, 18, 16), 40 * 16, 250 * 16)
        p.drawLine(9, 13, 6, 8)
        p.drawLine(9, 13, 14, 12)
    elif name == "redo":
        p.drawArc(QRectF(6, 9, 18, 16), -110 * 16, 250 * 16)
        p.drawLine(23, 13, 26, 8)
        p.drawLine(23, 13, 18, 12)
    elif name == "move":
        p.drawLine(16, 5, 16, 27)
        p.drawLine(5, 16, 27, 16)
        p.drawLine(16, 5, 12, 9)
        p.drawLine(16, 5, 20, 9)
        p.drawLine(16, 27, 12, 23)
        p.drawLine(16, 27, 20, 23)
        p.drawLine(5, 16, 9, 12)
        p.drawLine(5, 16, 9, 20)
        p.drawLine(27, 16, 23, 12)
        p.drawLine(27, 16, 23, 20)
    elif name == "stretch":
        p.drawRect(7, 9, 18, 14)
        p.setPen(accent)
        p.drawLine(5, 16, 11, 16)
        p.drawLine(21, 16, 27, 16)
    elif name == "wire":
        path = QPainterPath()
        path.moveTo(5, 22)
        path.lineTo(12, 22)
        path.lineTo(12, 10)
        path.lineTo(24, 10)
        p.drawPath(path)
        p.setBrush(ACCENT_COLOR)
        p.drawEllipse(3, 20, 4, 4)
        p.drawEllipse(22, 8, 4, 4)
    elif name == "bus":
        for y in (10, 16, 22):
            p.drawLine(5, y, 27, y)
    elif name == "instance":
        p.drawRect(9, 8, 14, 16)
        p.drawLine(5, 12, 9, 12)
        p.drawLine(5, 20, 9, 20)
        p.drawLine(23, 12, 27, 12)
        p.drawLine(23, 20, 27, 20)
    elif name == "pin":
        p.drawLine(6, 16, 22, 16)
        p.setBrush(ACCENT_COLOR)
        p.drawEllipse(20, 14, 5, 5)
    elif name == "label":
        p.drawRect(6, 9, 20, 14)
        p.drawLine(10, 14, 22, 14)
        p.drawLine(10, 19, 18, 19)
    elif name == "zoom_in":
        p.drawEllipse(6, 6, 14, 14)
        p.drawLine(18, 18, 26, 26)
        p.drawLine(13, 10, 13, 17)
        p.drawLine(10, 13, 17, 13)
    elif name == "zoom_out":
        p.drawEllipse(6, 6, 14, 14)
        p.drawLine(18, 18, 26, 26)
        p.drawLine(10, 13, 17, 13)
    elif name == "zoom_fit":
        p.drawRect(7, 7, 18, 18)
        p.drawLine(7, 12, 12, 7)
        p.drawLine(25, 12, 20, 7)
        p.drawLine(7, 20, 12, 25)
        p.drawLine(25, 20, 20, 25)
    elif name == "netlist":
        p.drawRect(8, 5, 16, 22)
        p.drawLine(12, 11, 20, 11)
        p.drawLine(12, 16, 20, 16)
        p.drawLine(12, 21, 17, 21)
    elif name == "run":
        p.setBrush(ICON_COLOR)
        pts = [(10, 7), (25, 16), (10, 25)]
        path = QPainterPath()
        path.moveTo(*pts[0])
        path.lineTo(*pts[1])
        path.lineTo(*pts[2])
        path.closeSubpath()
        p.drawPath(path)
    elif name == "stop":
        p.setBrush(ICON_COLOR)
        p.drawRect(10, 10, 12, 12)
    elif name == "wave":
        path = QPainterPath()
        path.moveTo(4, 18)
        path.cubicTo(9, 6, 13, 28, 18, 16)
        path.cubicTo(22, 6, 25, 20, 28, 12)
        p.drawPath(path)
    elif name == "health":
        p.drawEllipse(6, 6, 20, 20)
        p.setPen(accent)
        p.drawLine(11, 17, 15, 21)
        p.drawLine(15, 21, 22, 12)
    elif name == "palette":
        p.drawEllipse(6, 7, 20, 16)
        p.setBrush(ACCENT_COLOR)
        p.drawEllipse(11, 11, 3, 3)
        p.drawEllipse(17, 10, 3, 3)
        p.drawEllipse(20, 16, 3, 3)
    else:
        p.setPen(muted)
        p.drawRect(8, 8, 16, 16)

    p.end()
    return QIcon(pixmap)
