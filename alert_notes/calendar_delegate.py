from datetime import datetime

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import QStyledItemDelegate


class CurrentTimeDelegate(QStyledItemDelegate):
    def __init__(self, range_provider, parent=None):
        super().__init__(parent)
        self.range_provider = range_provider

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        now = datetime.now()
        start, end = self.range_provider()
        if not (start <= now.date() < end) or index.row() != now.hour:
            return
        day_col = 1 + (now.date() - start).days
        if index.column() not in (0, day_col):
            return
        y = option.rect.top() + int(option.rect.height() * now.minute / 60)
        painter.save()
        painter.setPen(QPen(QColor("#ef4444"), 2))
        painter.drawLine(QPoint(option.rect.left(), y), QPoint(option.rect.right(), y))
        painter.restore()
