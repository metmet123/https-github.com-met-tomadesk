"""Small single-colour line icons for the memo editor chrome.

Emoji and text glyphs render differently per Windows font (a colour gear, a
cut-off label), so compact buttons draw their own 18px strokes instead.
"""

from __future__ import annotations

import os
import tempfile

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ICON_COLOR = "#334155"


def _canvas(size: int = 18) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(ICON_COLOR), 1.6, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    return pixmap, painter


def _chevron(painter: QPainter, x: float, y: float) -> None:
    path = QPainterPath(QPointF(x, y))
    path.lineTo(x + 2.5, y + 2.5)
    path.lineTo(x + 5, y)
    painter.drawPath(path)


def import_backup_icon() -> QIcon:
    """Tray with an up arrow: import and back up memo files."""
    pixmap, painter = _canvas()
    tray = QPainterPath(QPointF(3, 11))
    tray.lineTo(3, 14.5)
    tray.lineTo(15, 14.5)
    tray.lineTo(15, 11)
    painter.drawPath(tray)
    arrow = QPainterPath(QPointF(6.5, 6))
    arrow.lineTo(9, 3.5)
    arrow.lineTo(11.5, 6)
    painter.drawPath(arrow)
    painter.drawLine(QPointF(9, 3.5), QPointF(9, 11))
    painter.end()
    return QIcon(pixmap)


def fold_current_icon() -> QIcon:
    """One chevron and a line: fold the heading or toggle at the caret."""
    pixmap, painter = _canvas()
    _chevron(painter, 3, 5.5)
    painter.drawLine(QPointF(10, 6.8), QPointF(15, 6.8))
    painter.drawLine(QPointF(4, 12), QPointF(15, 12))
    painter.end()
    return QIcon(pixmap)


def fold_all_icon() -> QIcon:
    """Two chevrons: fold or unfold every heading and toggle."""
    pixmap, painter = _canvas()
    _chevron(painter, 3, 3.5)
    _chevron(painter, 3, 9.5)
    painter.drawLine(QPointF(10, 4.8), QPointF(15, 4.8))
    painter.drawLine(QPointF(10, 10.8), QPointF(15, 10.8))
    painter.drawLine(QPointF(4, 15), QPointF(15, 15))
    painter.end()
    return QIcon(pixmap)


def gear_icon() -> QIcon:
    pixmap, painter = _canvas()
    pen = painter.pen()
    pen.setColor(QColor("#475569"))
    pen.setWidthF(1.5)
    painter.setPen(pen)
    painter.drawEllipse(QRectF(6.6, 6.6, 4.8, 4.8))
    for (x1, y1, x2, y2) in (
        (9, 2.5, 9, 4.5), (9, 13.5, 9, 15.5), (2.5, 9, 4.5, 9), (13.5, 9, 15.5, 9),
        (4.4, 4.4, 5.8, 5.8), (12.2, 12.2, 13.6, 13.6), (4.4, 13.6, 5.8, 12.2), (12.2, 5.8, 13.6, 4.4),
    ):
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    painter.end()
    return QIcon(pixmap)


def dot_icon(color: str, size: int = 10) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(1.5, 1.5, size - 3, size - 3))
    painter.end()
    return QIcon(pixmap)


_CHEVRON_PATH: str | None = None


def chevron_down_path() -> str:
    """A 9px grey chevron file for QComboBox::down-arrow.

    Style sheets only accept image files, and a styled drop-down otherwise loses
    its arrow.  The file is drawn once per run into the temp folder.
    """
    global _CHEVRON_PATH
    if _CHEVRON_PATH and os.path.exists(_CHEVRON_PATH):
        return _CHEVRON_PATH
    folder = os.path.join(tempfile.gettempdir(), "tomadesk_ui")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "chevron_down_v1.png")
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#475569"), 2.2, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    chevron = QPainterPath(QPointF(4, 7))
    chevron.lineTo(9, 12)
    chevron.lineTo(14, 7)
    painter.drawPath(chevron)
    painter.end()
    pixmap.save(path, "PNG")
    _CHEVRON_PATH = path.replace("\\", "/")
    return _CHEVRON_PATH


def compact_combo_style() -> str:
    return (
        "QComboBox{padding:0 2px 0 5px;}"
        "QComboBox::drop-down{border:0px;width:14px;subcontrol-origin:padding;"
        "subcontrol-position:center right;}"
        f"QComboBox::down-arrow{{image:url({chevron_down_path()});width:9px;height:9px;}}"
    )
