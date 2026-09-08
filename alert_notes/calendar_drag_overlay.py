"""시간축을 끄는 동안 따라오는 점선 블록.

끌고 있는 범위를 손을 떼기 전에 보여 준다.  "빈 시간을 클릭하면…" 같은 안내
문구가 상시 떠 있어야 했던 이유가 조작이 스스로 드러나지 않아서였으므로,
안내 대신 결과를 그 자리에 그린다.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget


ACCENT = "#4263eb"
FILL = "#eaf2ff"


class DragRangeOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAccessibleName("드래그한 시간 범위")
        self._text = ""
        self.hide()

    def show_range(self, rect: QRect, text: str) -> None:
        self._text = text
        self.setGeometry(rect)
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = self.rect().adjusted(1, 1, -2, -2)
        painter.fillRect(body, QColor(FILL))
        pen = QPen(QColor(ACCENT))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(body, 8, 8)
        painter.setPen(QColor(ACCENT))
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            body.adjusted(10, 6, -10, -6),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            self._text,
        )
