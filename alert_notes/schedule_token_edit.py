"""일정 자연어에서 읽은 구간을 색으로 보여 주는 한 줄 입력칸."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QLineEdit


TOKEN_COLORS = {
    "date": QColor("#dff5df"),
    "time": QColor("#dbeafe"),
    "reminder": QColor("#fef3c7"),
}
TOKEN_BORDERS = {
    "date": QColor("#86c99a"),
    "time": QColor("#8ab4ec"),
    "reminder": QColor("#e4ba59"),
}


@dataclass(frozen=True)
class DisplayTokenSpan:
    start: int
    end: int
    kind: str
    text: str


class ScheduleTokenLineEdit(QLineEdit):
    """파서 범위를 표시하고 더블클릭한 범위를 해제하도록 알린다."""

    token_double_clicked = pyqtSignal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token_spans: tuple = ()
        self._preediting = False
        self.setToolTip("색으로 표시된 날짜·시간·알람은 더블클릭하면 일정 해석을 취소합니다.")

    def set_token_spans(self, spans) -> None:
        shown = []
        for span in sorted(
            (span for span in (spans or ()) if getattr(span, "kind", "") in TOKEN_COLORS),
            key=lambda value: (value.start, value.end),
        ):
            if shown and shown[-1].kind == span.kind and span.start <= shown[-1].end:
                previous = shown[-1]
                shown[-1] = DisplayTokenSpan(
                    previous.start, max(previous.end, span.end), previous.kind,
                    self.text()[previous.start:max(previous.end, span.end)],
                )
            else:
                shown.append(DisplayTokenSpan(span.start, span.end, span.kind, span.text))
        # 파서가 삼킨 구분 공백은 원문에 유지하되 칩 안의 비대칭 여백으로 그리지 않는다.
        trimmed = []
        for span in shown:
            start, end = span.start, span.end
            while start < end and self.text()[start].isspace():
                start += 1
            while end > start and self.text()[end - 1].isspace():
                end -= 1
            if start < end:
                trimmed.append(DisplayTokenSpan(start, end, span.kind, self.text()[start:end]))
        self._token_spans = tuple(trimmed)
        self.update()

    def token_spans(self) -> tuple:
        return self._token_spans

    def token_rect(self, span) -> QRect:
        """현재 가로 스크롤을 반영한 토큰 사각형. 테스트와 히트 검사에서 공유한다."""
        text = self.displayText()
        start = max(0, min(int(span.start), len(text)))
        end = max(start, min(int(span.end), len(text)))
        metrics = self.fontMetrics()
        cursor = len(text.encode("utf-16-le")[:self.cursorPosition() * 2].decode("utf-16-le", errors="ignore"))
        # cursorRect는 커서 선보다 좌우로 넓은 재그리기 영역이다.
        # 왼쪽 끝을 기준으로 쓰면 칩이 왼쪽으로 치우친다.
        caret_x = self.cursorRect().center().x() + 1
        origin_x = caret_x - metrics.horizontalAdvance(text[:cursor])
        x = origin_x + metrics.horizontalAdvance(text[:start])
        width = max(2, metrics.horizontalAdvance(text[start:end]))
        content = self.contentsRect().adjusted(1, 2, -1, -2)
        # 한 칸 띄어 쓴 인접 토큰의 테두리가 서로 겹치지 않게 한다.
        padding = max(2, round(metrics.height() * .12))
        height = min(content.height(), metrics.height() + 6)
        return QRect(x - padding, self.cursorRect().center().y() - height // 2,
                     width + padding * 2, height)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._token_spans or self._preediting:
            return
        painter = QPainter(self)
        painter.setClipRect(self.contentsRect().adjusted(1, 1, -1, -1))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for span in self._token_spans:
            color = QColor(TOKEN_COLORS[span.kind])
            color.setAlpha(112)
            painter.setBrush(color)
            painter.setPen(QPen(TOKEN_BORDERS[span.kind], 1.0))
            painter.drawRoundedRect(self.token_rect(span), 7, 7)

    def mouseDoubleClickEvent(self, event) -> None:
        qt_position = self.cursorPositionAt(event.position().toPoint())
        position = len(self.text().encode("utf-16-le")[:qt_position * 2].decode("utf-16-le", errors="ignore"))
        for span in self._token_spans:
            if (self.token_rect(span).contains(event.position().toPoint())
                    and span.start <= position <= span.end):
                self.token_double_clicked.emit(span.start, span.end, span.kind)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def inputMethodEvent(self, event) -> None:
        self._preediting = bool(event.preeditString())
        super().inputMethodEvent(event)
        self.update()
