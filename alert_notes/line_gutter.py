"""본문 왼쪽의 손잡이 칸.

줄 앞에 마우스를 가져가면 손잡이가 뜨고, 잡아 끌면 그 줄을 다른 자리로 옮긴다.
토글을 잡으면 그 안의 줄까지 한 덩어리로 따라간다.
"""

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QApplication, QWidget


class LineGutter(QWidget):
    WIDTH = 20
    DOT_COLOR = "#94a3b8"
    HOVER_BACKGROUND = QColor(59, 84, 232, 26)
    # 이만큼 움직여야 "끌기"로 본다.  그 전에는 그냥 누른 것이다.
    DRAG_THRESHOLD = 4

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self._hover_block = None
        self._press_at: QPoint | None = None
        self._dragging = False
        self._selecting = False
        self.setFixedWidth(self.WIDTH)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # --------------------------------------------------------- 그리기 --
    def hovered_block(self):
        return self._hover_block

    def handle_rect(self, block) -> QRect:
        line = self.editor.cursorRect(self.editor.block_cursor(block))
        height = max(line.height(), 16)
        return QRect(3, line.top() + (height - 16) // 2, self.WIDTH - 6, 16)

    def paintEvent(self, _event) -> None:
        block = self._hover_block
        if block is None or not block.isValid() or not block.isVisible():
            return
        rect = self.handle_rect(block)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.HOVER_BACKGROUND)
        painter.drawRoundedRect(rect, 4.0, 4.0)
        painter.setBrush(QColor(self.DOT_COLOR))
        centre = rect.center()
        for row in (-4, 0, 4):
            for column in (-2, 2):
                painter.drawEllipse(QPoint(centre.x() + column, centre.y() + row), 1, 1)
        painter.end()

    def _set_hover(self, block) -> None:
        current = self._hover_block
        same = (
            current is not None and block is not None
            and current.isValid() and block.isValid()
            and current.position() == block.position()
        )
        if same:
            return
        self._hover_block = block
        shape = (
            Qt.CursorShape.OpenHandCursor if block is not None
            else Qt.CursorShape.ArrowCursor
        )
        if self.cursor().shape() != shape:
            self.setCursor(shape)
        self.update()

    # --------------------------------------------------------- 마우스 --
    def mouseMoveEvent(self, event) -> None:
        point = event.position().toPoint()
        if self._selecting and event.buttons() & Qt.MouseButton.LeftButton:
            self.editor.update_block_selection(self.editor.block_at_gutter(point.y()))
            return
        if self._press_at is not None and event.buttons() & Qt.MouseButton.LeftButton:
            moved = (point - self._press_at).manhattanLength()
            if not self._dragging and moved >= self.DRAG_THRESHOLD:
                self._dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._dragging:
                self.editor.update_line_drag(self.mapTo(self.editor, point))
            return
        self._set_hover(self.editor.block_at_gutter(point.y()))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = event.position().toPoint()
        block = self.editor.block_at_gutter(point.y())
        self._set_hover(block)
        if block is None:
            return
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._selecting = True
            self.editor.begin_block_selection(block)
            event.accept()
            return
        self._press_at = point
        self.editor.begin_line_drag(block)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._selecting:
            self.editor.finish_block_selection()
        elif self._dragging:
            self.editor.finish_line_drag(
                self.mapTo(self.editor, event.position().toPoint())
            )
        else:
            self.editor.cancel_line_drag()
        self._press_at = None
        self._dragging = False
        self._selecting = False
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._hover_block else Qt.CursorShape.ArrowCursor)
        event.accept()

    def leaveEvent(self, event) -> None:
        if not self._dragging:
            self._set_hover(None)
        super().leaveEvent(event)
