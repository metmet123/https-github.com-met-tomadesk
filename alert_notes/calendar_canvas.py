"""일정을 좌표와 크기를 가진 조각으로 그리는 시간표.

표 위젯에서는 일정이 "칸에 든 글자"였다.  글자에는 잡을 모서리가 없어 길이를
바꿀 수 없었고, 칸이 한 시간짜리라 10시 30분 일정도 10시 칸 꼭대기에 붙었다.
주간은 1분 = 1픽셀, 일간은 주 사용 시간 밖을 압축하는 공통 좌표를 쓴다. 그래서

* 10:30은 10시와 11시 사이 정확한 자리에 놓이고,
* 아래 모서리를 끌면 길이가 바뀌며,
* 겹치는 일정은 폭을 나눠 나란히 선다.

바깥에서 쓰는 것은 :class:`CalendarCanvas` 하나다.  ``render_range``로 그리고,
조작 결과는 신호로 알린다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from time import monotonic

from PyQt6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPen, QTransform
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QVBoxLayout, QWidget,
    QScrollArea, QGridLayout, QLabel, QPushButton, QApplication, QToolTip, QSizePolicy,
)

from .categories import CATEGORY_COLORS, category_name
from .sqlite_store import DATETIME_FMT
from .timeline_axis import TimelineAxis


GUTTER = 58                 # 시간 눈금이 앉는 왼쪽 띠
HOUR_HEIGHT = 60            # 1분 = 1픽셀
DAY_MINUTES = 24 * 60
SNAP_MINUTES = 15           # Alt를 누르면 1분
MIN_MINUTES = 15            # 이보다 짧게는 줄이지 않는다
EDGE_GRIP = 7               # 아래 모서리에서 손잡이로 치는 두께
LANE_GAP = 3

GRID_LINE = "#E4E9F0"
GRID_HALF = "#EFF2F7"
GUTTER_INK = "#64748B"
NOW_LINE = "#B42318"
SELECT_INK = "#4263EB"
BAND_FILL = "#EAF2FF"


def snap(minutes: float, step: int = SNAP_MINUTES) -> int:
    step = max(1, int(step))
    return int(max(0, min(DAY_MINUTES, round(minutes / step) * step)))


class ScheduleBlock(QGraphicsRectItem):
    """시간표 위의 일정 하나.  옮기고 늘일 수 있다."""

    def __init__(self, canvas: "CalendarCanvas", event: dict):
        super().__init__()
        self.canvas = canvas
        self.item_id = int(event["id"])
        self.occurrence_at = str(event["occurrence_at"])
        self.title = str(event["title"])
        self.category = str(event["category"])
        self.status = str(event["status"])
        self.item_type = str(event["item_type"])
        self.time_mode = str(event.get("time_mode") or "range")
        self.locked = bool(event.get("locked"))
        self.start: datetime = event["start"]
        self.end: datetime = event["end"]
        self.display_day = event.get("display_day", self.start.date())
        self._press_mode = None
        self._press_offset = 0.0
        self._origin = (self.start, self.end)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setToolTip(self._tooltip())
        self.setZValue(10)

    # ------------------------------------------------------------------ 그림 --
    @property
    def visible_start(self) -> datetime:
        return max(self.start, datetime.combine(self.display_day, time.min))

    @property
    def visible_end(self) -> datetime:
        return min(self.end, datetime.combine(self.display_day + timedelta(days=1), time.min))

    @property
    def continues_before(self) -> bool:
        return self.start < self.visible_start

    @property
    def continues_after(self) -> bool:
        return self.end > self.visible_end

    def display_title(self) -> str:
        prefix = "← " if self.continues_before else ""
        suffix = " · 종료 없음" if self.time_mode == "point" else " →" if self.continues_after else ""
        return prefix + self.title + suffix

    def _tooltip(self) -> str:
        span = f"{self.start:%H:%M} · 종료 없음" if self.time_mode == "point" else \
            f"{self.start:%m/%d %H:%M} – {self.end:%m/%d %H:%M}"
        return f"{self.title}\n{self.start:%m월 %d일} {span} · {category_name(self.category)}"

    def paint(self, painter, option, widget=None) -> None:
        background, foreground = CATEGORY_COLORS.get(self.category, ("#E7F0FF", "#234F9A"))
        if self.status == "completed":
            foreground = GUTTER_INK
        rect = self.rect()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(background))
        pen = QPen(QColor(SELECT_INK if self.isSelected() else "#DCE3EC"))
        pen.setWidth(2 if self.isSelected() else 1)
        painter.setPen(pen)
        if self.time_mode == "point":
            painter.drawLine(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.top()))
            painter.drawEllipse(QPointF(rect.left() + 3, rect.top()), 3, 3)
        else:
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            painter.fillRect(QRectF(rect.left(), rect.top() + 2, 3, max(1, rect.height() - 4)), QColor(foreground))
        painter.setPen(QColor(foreground))
        painter.save()
        scale = self.canvas.view.transform().m22()
        painter.scale(1, 1 / scale)
        text_rect = QRectF(rect.left() + 5, rect.top() * scale + 1, rect.width() - 10, rect.height() * scale - 2)
        if text_rect.width() > 4:
            font = QFont(painter.font())
            font.setBold(True)
            painter.setFont(font)
            head = painter.fontMetrics().elidedText(self.display_title(), Qt.TextElideMode.ElideRight, int(text_rect.width()))
            painter.drawText(
                text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), head
            )
        if text_rect.height() >= 40 and self.time_mode != "point":
            font = QFont(painter.font())
            font.setBold(False)
            painter.setFont(font)
            marker = "완료" if self.status == "completed" else "할 일" if self.item_type == "task" else "일정"
            painter.drawText(
                text_rect.adjusted(0, 17, 0, 0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                painter.fontMetrics().elidedText(f"{self.visible_start:%H:%M}–{self.visible_end:%H:%M}" + (f" · {marker}" if marker != "일정" else ""), Qt.TextElideMode.ElideRight, int(text_rect.width())),
            )
        painter.restore()
        if not self.locked and not self.continues_after and self.time_mode != "point" and rect.height() >= 26 and self.isSelected():
            # 잡을 곳이 있다는 걸 손잡이로 알린다.
            grip = QPen(QColor(foreground))
            grip.setWidth(2)
            grip.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(grip)
            middle = rect.center().x()
            painter.drawLine(
                QPointF(middle - 13, rect.bottom() - 4), QPointF(middle + 13, rect.bottom() - 4)
            )

    # ------------------------------------------------------------------ 조작 --
    def _on_edge(self, position: QPointF) -> bool:
        return not self.locked and not self.continues_after and self.time_mode != "point" and position.y() >= self.rect().bottom() - EDGE_GRIP

    def hoverMoveEvent(self, event) -> None:
        if self.locked:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._on_edge(event.pos()):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def begin_press(self, scene_y: float, edge: bool) -> None:
        """잡은 지점을 블록 위쪽에서부터의 거리로 기억한다.

        여기에 누른 지점의 절대 좌표를 넣으면 첫 움직임에서 그 값만큼 빼면서
        블록이 자정으로 튀어 올라갔다.  기억해야 하는 것은 "블록의 어디를
        잡았는가"이지 "화면의 어디를 눌렀는가"가 아니다.
        """
        self._origin = (self.start, self.end)
        self._press_scene = None
        self._press_day = self.display_day
        self._press_visible_start = self.visible_start
        self._press_mode = "locked" if self.locked else ("resize" if edge and self.time_mode != "point" and not self.continues_after else "move")
        self.canvas.mark_user_scroll()
        self._press_offset = self.canvas.y_to_minute(scene_y) - (self.visible_start.hour * 60 + self.visible_start.minute)

    def drag_to(self, scene_y: float, step: int = SNAP_MINUTES, scene_x: float | None = None) -> None:
        if self._press_mode == "move":
            top = snap(self.canvas.y_to_minute(scene_y) - self._press_offset, step)
            column = self.canvas.column_at(scene_x) if scene_x is not None else None
            self.display_day = self.canvas._start + timedelta(days=column) if column is not None else self._press_day
            target = datetime.combine(self.display_day, time.min) + timedelta(minutes=min(top, DAY_MINUTES - 1))
            delta = target - self._press_visible_start
            self.start, self.end = self._origin[0] + delta, self._origin[1] + delta
        elif self._press_mode == "resize":
            bottom = snap(self.canvas.y_to_minute(scene_y), step)
            self.end = max(self.start + timedelta(minutes=MIN_MINUTES), self._day_at(bottom, base=self.display_day))
        else:
            return
        self.canvas.preview_block(self)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self.canvas.view.scene().clearSelection()
        self.setSelected(True)
        self.setFocus()
        self.begin_press(event.scenePos().y(), self._on_edge(event.pos()))
        self._press_scene = event.screenPos()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._press_mode not in {"move", "resize"}:
            return
        if self._press_scene is not None and (event.screenPos() - self._press_scene).manhattanLength() < QApplication.startDragDistance():
            return
        self._press_scene = None
        for sibling in self.canvas.blocks():
            if sibling is not self and (sibling.item_id, sibling.occurrence_at) == (self.item_id, self.occurrence_at):
                sibling.hide()
        step = 1 if event.modifiers() & Qt.KeyboardModifier.AltModifier else SNAP_MINUTES
        self.drag_to(event.scenePos().y(), step, event.scenePos().x())
        self.canvas.auto_scroll(event.scenePos())
        self.canvas.track_drag(self, event.scenePos(), step)
        QToolTip.showText(event.screenPos(), f"{self.start:%m/%d %H:%M}–{self.end:%m/%d %H:%M} · Esc 취소", self.canvas.view)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.canvas.mark_user_scroll()
        QToolTip.hideText()
        self.canvas.stop_drag_scroll()
        for sibling in self.canvas.blocks():
            sibling.show()
        mode, self._press_mode = self._press_mode, None
        if mode == "move" and (self.start, self.end) != self._origin:
            self.canvas.commit_move(self, self._origin)
        elif mode == "resize" and (self.start, self.end) != self._origin:
            self.canvas.commit_resize(self, self._origin)
        elif mode in {"move", "resize", "locked"}:
            self.canvas.block_clicked(self)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.canvas.block_activated(self)
        event.accept()

    def _day_at(self, minutes: int, base: date | None = None) -> datetime:
        day = base or self.start.date()
        if minutes >= DAY_MINUTES:
            return datetime.combine(day + timedelta(days=1), time.min)
        return datetime.combine(day, time(minutes // 60, minutes % 60))


class TimelineView(QGraphicsView):
    """눈금과 지금 시각 선을 배경으로 깔고, 빈 자리를 끌면 범위를 만든다."""

    def __init__(self, canvas: "CalendarCanvas"):
        super().__init__(canvas)
        self.canvas = canvas
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(self.renderHints().Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.setAccessibleName("일정 시간표")
        self._band: QGraphicsRectItem | None = None
        self._band_origin: tuple[int, int] | None = None

    # 배경(눈금)은 아이템이 아니라 그림이다.  아이템으로 두면 수천 개가 된다.
    def drawBackground(self, painter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#FFFFFF"))
        left = self.canvas.column_left(0)
        axis = self.canvas.axis
        if axis.compressed:
            for first, last in ((0, 540), (1080, 1440)):
                painter.fillRect(QRectF(0, axis.y(first), rect.right(), axis.y(last) - axis.y(first)), QColor("#F3F5F8"))
        painter.setPen(QPen(QColor(GRID_HALF)))
        for minutes in range(0, DAY_MINUTES + 1, 30):
            if minutes % 60 and (not axis.compressed or 540 <= minutes < 1080):
                painter.drawLine(QPointF(left, axis.y(minutes)), QPointF(rect.right(), axis.y(minutes)))
        painter.setPen(QPen(QColor(GRID_LINE)))
        for hour in range(25):
            y = axis.y(hour * 60)
            painter.drawLine(QPointF(left - 8, y), QPointF(rect.right(), y))
        for column in range(1, self.canvas.column_count):
            x = self.canvas.column_left(column)
            painter.drawLine(QPointF(x, 0), QPointF(x, axis.y(DAY_MINUTES)))
        painter.setPen(QColor(GUTTER_INK))
        font = QFont(self.canvas.font())
        painter.setFont(font)
        for hour in range(25):
            painter.drawText(QRectF(2, axis.y(hour * 60) + 1, GUTTER - 8, painter.fontMetrics().height()),
                             int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop),
                             f"{hour:02d}:00")
        if axis.compressed:
            for minute, label in ((540, "09–18시 · 주 사용"), (1080, "이후 시간 · ⅓ 간격")):
                painter.setPen(QPen(QColor("#64748B")))
                painter.drawLine(QPointF(left, axis.y(minute)), QPointF(rect.right(), axis.y(minute)))
                height = painter.fontMetrics().height()
                area = QRectF(left + 5, axis.y(minute) - height - 2, max(0, rect.right() - left - 10), height)
                painter.drawText(area, int(Qt.AlignmentFlag.AlignRight), painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(area.width())))

    def drawForeground(self, painter, rect: QRectF) -> None:
        column = self.canvas.column_for_date(datetime.now().date())
        if column is None:
            return
        now = datetime.now()
        minutes = self.canvas.minute_to_y(now.hour * 60 + now.minute)
        left = self.canvas.column_left(column)
        right = left + self.canvas.column_width()
        painter.setPen(QPen(QColor(NOW_LINE), 1.5))
        painter.drawLine(QPointF(left, minutes), QPointF(right, minutes))
        painter.setBrush(QColor(NOW_LINE))
        painter.drawEllipse(QPointF(left + 3, minutes), 3.5, 3.5)
        height = painter.fontMetrics().height() + 2
        painter.fillRect(QRectF(0, minutes - height / 2, GUTTER - 4, height), QColor("#FFFFFF"))
        painter.drawText(QRectF(0, minutes - height / 2, GUTTER - 6, height), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), now.strftime("%H:%M"))

    # ---------------------------------------------------------------- 드래그 --
    def mousePressEvent(self, event) -> None:
        self.canvas.mark_user_scroll()
        if event.button() != Qt.MouseButton.LeftButton or (not self.canvas.selection_only and self.itemAt(event.pos()) is not None):
            super().mousePressEvent(event)
            return
        point = self.mapToScene(event.pos())
        column = self.canvas.column_at(point.x())
        if column is None or point.y() < 0 or point.y() >= self.canvas.minute_to_y(DAY_MINUTES):
            return
        minutes = snap(self.canvas.y_to_minute(point.y()), 1 if event.modifiers() & Qt.KeyboardModifier.AltModifier else SNAP_MINUTES)
        minutes = min(DAY_MINUTES - MIN_MINUTES, minutes)
        self._band_origin = (column, minutes)
        self.canvas.selectionStarted.emit()
        self._band = self.scene().addRect(QRectF(), QPen(QColor(SELECT_INK), 2, Qt.PenStyle.DashLine), QColor(BAND_FILL))
        self._band.setZValue(5)
        self._update_band(minutes)
        self.scene().clearSelection()

    def mouseMoveEvent(self, event) -> None:
        if self._band_origin is None:
            super().mouseMoveEvent(event)
            return
        point = self.mapToScene(event.pos())
        step = 1 if event.modifiers() & Qt.KeyboardModifier.AltModifier else SNAP_MINUTES
        self._update_band(snap(self.canvas.y_to_minute(point.y()), step))

    def mouseReleaseEvent(self, event) -> None:
        self.canvas.mark_user_scroll()
        if self._band_origin is None:
            super().mouseReleaseEvent(event)
            return
        column, origin = self._band_origin
        point = self.mapToScene(event.pos())
        step = 1 if event.modifiers() & Qt.KeyboardModifier.AltModifier else SNAP_MINUTES
        first, last = sorted((origin, snap(self.canvas.y_to_minute(point.y()), step)))
        if last - first < MIN_MINUTES:
            last = first + 60
        self._clear_band()
        self._band_origin = None
        self.canvas.range_selected(column, first, min(DAY_MINUTES, last))

    def _update_band(self, minutes: int) -> None:
        if self._band is None or self._band_origin is None:
            return
        column, origin = self._band_origin
        first, last = sorted((origin, minutes))
        left = self.canvas.column_left(column) + 2
        self._band.setRect(QRectF(left, self.canvas.minute_to_y(first), max(10, self.canvas.column_width() - 4), max(2, self.canvas.minute_to_y(last) - self.canvas.minute_to_y(first))))
        self.canvas.rangePreview.emit(self.canvas.datetime_at(column, first), self.canvas.datetime_at(column, min(DAY_MINUTES, max(first + MIN_MINUTES, last))))

    def _clear_band(self) -> None:
        if self._band is not None:
            self.scene().removeItem(self._band)
            self._band = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.canvas.reflow()

    def keyPressEvent(self, event) -> None:
        self.canvas.mark_user_scroll()
        if event.key() == Qt.Key.Key_Escape:
            self.canvas.stop_drag_scroll()
            self._clear_band()
            self._band_origin = None
            self.canvas.selectionCanceled.emit()
            for block in self.canvas.blocks():
                block.show()
                if block._press_mode:
                    block.start, block.end = block._origin
                    block.display_day = block._press_day
                    block._press_mode = None
            self.canvas.reflow()
            QToolTip.hideText()
            event.accept()
            return
        if self.canvas.handle_key(event):
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        self.canvas.mark_user_scroll()
        super().wheelEvent(event)


class CalendarCanvas(QWidget):
    """바깥에서 쓰는 시간표 위젯."""

    rangeSelected = pyqtSignal(datetime, datetime)
    rangePreview = pyqtSignal(datetime, datetime)
    selectionStarted = pyqtSignal()
    selectionCanceled = pyqtSignal()
    layoutChanged = pyqtSignal()
    scheduleClicked = pyqtSignal(int, str)
    scheduleActivated = pyqtSignal(int, str)
    scheduleMoved = pyqtSignal(int, str, datetime, datetime, datetime, datetime)
    scheduleResized = pyqtSignal(int, str, datetime, datetime, datetime, datetime)
    dateSelected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("scheduleCanvas")
        self._start = date.today()
        self.column_count = 1
        self.axis = TimelineAxis()
        self.selection_only = False
        self.follow_now = False
        self._last_interaction = float("-inf")
        self._editing = False
        self.editing_guard = lambda: False
        self._last_clock_minute = None
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._clock_tick)
        self._clock_timer.start()
        self._blocks: list[ScheduleBlock] = []
        self._drag_tracking = None
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(40)
        self._drag_timer.timeout.connect(self._drag_scroll_tick)
        self._headers: list[str] = []
        self.header = _DayHeader(self)
        self.all_day_area = QScrollArea(self)
        self.all_day_area.setWidgetResizable(True)
        self.all_day_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.all_day_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.all_day_area.setAccessibleName("종일 일정")
        self.all_day_area.hide()
        self._all_day_buttons = []
        self.view = TimelineView(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.all_day_area)
        layout.addWidget(self.view, 1)
        self.setAccessibleName("일정 시간표")
        self._scrolled_once = False
        # 사람이 손으로 굴린 뒤에는 시계가 화면을 빼앗지 않는다.
        self._user_scrolled = False
        bar = self.view.verticalScrollBar()
        bar.sliderPressed.connect(self.mark_user_scroll)
        bar.actionTriggered.connect(lambda _action: self.mark_user_scroll())

    # ------------------------------------------------------------------ 좌표 --
    def minute_to_y(self, minute):
        return self.axis.y(minute)

    def y_to_minute(self, y):
        return self.axis.minute(y)

    def set_working_hours(self, enabled: bool):
        self.axis = TimelineAxis(enabled)
        self.reflow()

    def set_editing(self, editing: bool):
        if self._editing != editing:
            self._editing = editing
            self.mark_user_scroll()

    def _clock_tick(self):
        if not self.isVisible():
            return
        now = datetime.now()
        minute = (now.date(), now.hour, now.minute)
        clock_changed = minute != self._last_clock_minute
        if clock_changed:
            self._last_clock_minute = minute
            self.view.viewport().update()
        busy = self._editing or self.editing_guard() or self.view._band_origin is not None or any(b._press_mode for b in self._blocks)
        busy = busy or self.view.verticalScrollBar().isSliderDown() or QApplication.activeModalWidget() is not None
        if busy:
            self.mark_user_scroll()
        elif self.follow_now and self.column_count == 1 and self._start == date.today() and monotonic() - self._last_interaction >= 10 and (clock_changed or self._user_scrolled):
            self.scroll_to_now(force=True)

    def column_width(self) -> float:
        width = max(200, self.view.viewport().width())
        return max(60.0, (width - GUTTER) / max(1, self.column_count))

    def column_left(self, column: int) -> float:
        return GUTTER + column * self.column_width()

    def column_at(self, x: float) -> int | None:
        if x < GUTTER:
            return None
        column = int((x - GUTTER) // self.column_width())
        return column if 0 <= column < self.column_count else None

    def column_for_date(self, value: date) -> int | None:
        offset = (value - self._start).days
        return offset if 0 <= offset < self.column_count else None

    def datetime_at(self, column: int, minutes: int) -> datetime:
        day = self._start + timedelta(days=column)
        if minutes >= DAY_MINUTES:
            return datetime.combine(day + timedelta(days=1), time.min)
        return datetime.combine(day, time(minutes // 60, minutes % 60))

    # ------------------------------------------------------------------ 그리기 --
    def render_range(self, start: date, end: date, items) -> None:
        self.stop_drag_scroll()
        self._start = start
        self.column_count = max(1, (end - start).days)
        weekdays = "월화수목금토일"
        self._headers = [
            f"{weekdays[(start + timedelta(days=i)).weekday()]} {(start + timedelta(days=i)):%m/%d}"
            for i in range(self.column_count)
        ]
        self.header.update()
        self.header.setFixedHeight(max(44, self.header.fontMetrics().height() * 2 + 8))
        self.clearContents()
        all_day_items = []
        for event in items:
            try:
                begin = datetime.strptime(str(event["display_start_at"]), DATETIME_FMT)
                finish = datetime.strptime(str(event["display_end_at"]), DATETIME_FMT)
            except (ValueError, KeyError):
                continue
            if finish <= begin:
                finish = begin + timedelta(minutes=MIN_MINUTES)
            if finish <= datetime.combine(start, time.min) or begin >= datetime.combine(end, time.min):
                continue
            if bool(event.get("all_day", False)):
                all_day_items.append((event, begin, finish))
                continue
            values = {
                "id": event["id"], "occurrence_at": event["occurrence_at"], "title": event["title"],
                "category": event["category"], "status": event["status"], "item_type": event["item_type"],
                "time_mode": event.get("time_mode", "range"),
                "locked": event["source_reminder_id"] is not None if "source_reminder_id" in event.keys() else False,
                "start": begin, "end": finish,
            }
            day = max(start, begin.date())
            while day < end and datetime.combine(day, time.min) < finish:
                block = ScheduleBlock(self, dict(values, display_day=day))
                if self.selection_only:
                    block.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    block.setAcceptHoverEvents(False)
                    block.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
                    block.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, False)
                    block.setOpacity(0.45)
                self.view.scene().addItem(block)
                self._blocks.append(block)
                day += timedelta(days=1)
        self._render_all_day(all_day_items)
        self.reflow()
        if not self._scrolled_once:
            self._scrolled_once = True
            self.scroll_to_now(force=True)

    def clearContents(self) -> None:
        self.stop_drag_scroll()
        for block in self._blocks:
            self.view.scene().removeItem(block)
        self._blocks = []

    def _render_all_day(self, items) -> None:
        old = self.all_day_area.takeWidget()
        if old is not None:
            old.deleteLater()
        self._all_day_buttons = []
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(GUTTER, 2, 0, 2)
        grid.setSpacing(3)
        for column in range(self.column_count):
            grid.setColumnStretch(column, 1)
            grid.setColumnMinimumWidth(column, max(1, int(self.column_width()) - 3))
        lane_ends = []
        for event, begin, finish in items:
            first = max(0, (begin.date() - self._start).days)
            last = min(self.column_count, ((finish - timedelta(microseconds=1)).date() - self._start).days + 1)
            lane = next((i for i, occupied in enumerate(lane_ends) if occupied <= first), len(lane_ends))
            if lane == len(lane_ends):
                lane_ends.append(last)
            else:
                lane_ends[lane] = last
            button = QPushButton(str(event["title"]))
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setFixedHeight(26)
            button.setToolTip(f"{event['title']}\n종일 · {begin:%m/%d}–{(finish - timedelta(microseconds=1)):%m/%d}")
            button.setAccessibleName(f"종일 일정 {event['title']}")
            background, foreground = CATEGORY_COLORS.get(event["category"], ("#E7F0FF", "#234F9A"))
            button.setStyleSheet(f"QPushButton {{min-height:0; text-align:left; padding:2px 6px; border:1px solid {background}; border-radius:4px; background:{background}; color:{foreground};}} QPushButton:focus {{border:1px solid #4263EB;}}")
            button.clicked.connect(lambda _checked=False, item_id=int(event["id"]), occurrence=str(event["occurrence_at"]): self.scheduleClicked.emit(item_id, occurrence))
            grid.addWidget(button, lane, first, 1, last - first)
            self._all_day_buttons.append(button)
        label = QLabel("종일", content)
        label.setGeometry(4, 3, GUTTER - 8, 24)
        self.all_day_area.setWidget(content)
        self.all_day_area.setFixedHeight(min(116, max(36, len(lane_ends) * 29 + 8)))
        self.all_day_area.setVisible(bool(items))

    def reflow(self) -> None:
        """겹치는 일정을 폭으로 나눠 나란히 세운다."""
        self.axis = TimelineAxis(self.axis.compressed, max(1.0, self.fontMetrics().height() / 16))
        self.header.setFixedHeight(max(44, self.header.fontMetrics().height() * 2 + 8))
        width = self.column_width()
        content = self.all_day_area.widget()
        if content is not None:
            for column in range(self.column_count):
                content.layout().setColumnMinimumWidth(column, max(1, int(width) - 3))
        pad = self.view.viewport().height() / (2 * self.view.transform().m22()) if (self.follow_now or self.selection_only) and self.column_count == 1 else 0
        self.view.setSceneRect(QRectF(0, -pad, GUTTER + width * self.column_count, self.minute_to_y(DAY_MINUTES) + self.minimum_block_height() + 2 * pad))
        for column in range(self.column_count):
            blocks = sorted(
                (block for block in self._blocks if self.column_for_date(block.display_day) == column),
                key=lambda item: (item.visible_start, item.visible_end),
            )
            # 서로 물려 있는 덩어리마다 따로 폭을 나눈다.  하루 전체로 한 번에
            # 나누면 겹치지도 않는 일정까지 반 폭이 된다.
            for cluster in _clusters(blocks):
                lanes: list[datetime] = []
                placed: list[tuple[ScheduleBlock, int]] = []
                for block in cluster:
                    lane = next(
                        (index for index, busy in enumerate(lanes) if busy <= block.visible_start), len(lanes)
                    )
                    if lane == len(lanes):
                        lanes.append(_visual_end(block))
                    else:
                        lanes[lane] = _visual_end(block)
                    placed.append((block, lane))
                total = max(1, len(lanes))
                for block, lane in placed:
                    self._place(block, column, lane, total)
        self.view.viewport().update()
        self.layoutChanged.emit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and hasattr(self, "view"):
            self.reflow()

    def _place(self, block: ScheduleBlock, column: int, lane: int, lanes: int) -> None:
        width = self.column_width()
        share = (width - 6) / max(1, lanes)
        left = self.column_left(column) + 3 + lane * share
        minute = block.visible_start.hour * 60 + block.visible_start.minute
        top = self.minute_to_y(minute)
        height = max(self.minimum_block_height(), self.minute_to_y(minute + (block.visible_end - block.visible_start).total_seconds() / 60) - top)
        block.setPos(0, 0)
        block.setRect(QRectF(left, top, max(1.0, share - LANE_GAP), height))

    def minimum_block_height(self) -> int:
        return int(max(22, self.fontMetrics().height() + 4) / self.view.transform().m22())

    def set_compact(self, compact: bool) -> None:
        old_scale = self.view.transform().m22()
        position = self.view.verticalScrollBar().value() / old_scale
        self.view.setTransform(QTransform.fromScale(1, 0.75 if compact else 1))
        self.reflow()
        self.view.verticalScrollBar().setValue(int(position * self.view.transform().m22()))

    def preview_block(self, block: ScheduleBlock) -> None:
        """끄는 동안에는 그 조각만 다시 그린다."""
        column = self.column_for_date(block.display_day)
        if column is None:
            return
        rect = block.rect()
        minute = block.visible_start.hour * 60 + block.visible_start.minute
        top = self.minute_to_y(minute)
        height = max(self.minimum_block_height(), self.minute_to_y(minute + (block.visible_end - block.visible_start).total_seconds() / 60) - top)
        block.setRect(QRectF(self.column_left(column) + 3, top, min(rect.width(), self.column_width() - 6), height))
        block.setToolTip(block._tooltip())

    def mark_user_scroll(self) -> None:
        self._user_scrolled = True
        self._last_interaction = monotonic()

    def auto_scroll(self, scene_position) -> None:
        y = self.view.mapFromScene(scene_position).y()
        bar = self.view.verticalScrollBar()
        if y < 28:
            bar.setValue(bar.value() - 18)
        elif y > self.view.viewport().height() - 28:
            bar.setValue(bar.value() + 18)

    def track_drag(self, block, scene_position, step):
        point = self.view.mapFromScene(scene_position)
        self._drag_tracking = (block, point, step)
        if point.y() < 28 or point.y() > self.view.viewport().height() - 28:
            self._drag_timer.start()
        else:
            self._drag_timer.stop()

    def stop_drag_scroll(self):
        self._drag_timer.stop()
        self._drag_tracking = None

    def _drag_scroll_tick(self):
        if self._drag_tracking is None:
            return
        block, point, step = self._drag_tracking
        if not block._press_mode:
            self.stop_drag_scroll()
            return
        self.auto_scroll(self.view.mapToScene(point))
        scene = self.view.mapToScene(point)
        block.drag_to(scene.y(), step, scene.x())

    def scroll_to_now(self, force: bool = False) -> None:
        """지금 시각을 화면 가운데로.

        탭을 고르거나 '오늘'을 누른 것은 "지금을 보여 달라"는 뜻이라 ``force``로
        따라간다.  그 밖의 다시 그리기는 사람이 굴려 둔 자리를 건드리지 않는다.
        """
        now = datetime.now()
        if self.column_for_date(now.date()) is None:
            if force or not self._user_scrolled:
                self.scroll_to_hour(8)
            return
        if self._user_scrolled and not force:
            return
        bar = self.view.verticalScrollBar()
        centre = self.minute_to_y(now.hour * 60 + now.minute)
        target = int(centre * self.view.transform().m22() - self.view.viewport().height() / 2)
        bar.setValue(max(bar.minimum(), min(target, bar.maximum())))
        self._user_scrolled = False

    def scroll_to_hour(self, hour: int) -> None:
        self.view.verticalScrollBar().setValue(int(self.minute_to_y(max(0, hour * 60)) * self.view.transform().m22()))

    def rect_for_range(self, start: datetime, end: datetime) -> QRect | None:
        """팝오버를 세울 자리.  캔버스 좌표로 돌려준다."""
        column = self.column_for_date(start.date())
        if column is None:
            return None
        top = start.hour * 60 + start.minute
        bottom = max(top + MIN_MINUTES, int((end - start).total_seconds() // 60) + top)
        top_left = self.view.mapFromScene(QPointF(self.column_left(column), self.minute_to_y(top)))
        bottom_right = self.view.mapFromScene(
            QPointF(self.column_left(column) + self.column_width(), self.minute_to_y(bottom))
        )
        origin = self.view.mapTo(self, top_left)
        return QRect(origin.x(), origin.y(), max(20, bottom_right.x() - top_left.x()),
                     max(20, bottom_right.y() - top_left.y()))

    # ------------------------------------------------------------------ 신호 --
    def range_selected(self, column: int, first: int, last: int) -> None:
        self.rangeSelected.emit(self.datetime_at(column, first), self.datetime_at(column, last))

    def block_clicked(self, block: ScheduleBlock) -> None:
        self.scheduleClicked.emit(block.item_id, block.occurrence_at)

    def block_activated(self, block: ScheduleBlock) -> None:
        self.scheduleActivated.emit(block.item_id, block.occurrence_at)

    def commit_move(self, block: ScheduleBlock, origin) -> None:
        self.scheduleMoved.emit(
            block.item_id, block.occurrence_at, origin[0], origin[1], block.start, block.end
        )

    def commit_resize(self, block: ScheduleBlock, origin) -> None:
        self.scheduleResized.emit(
            block.item_id, block.occurrence_at, origin[0], origin[1], block.start, block.end
        )

    # ------------------------------------------------------------------ 키보드 --
    def selected_block(self) -> ScheduleBlock | None:
        for block in self._blocks:
            if block.isSelected():
                return block
        return None

    def handle_key(self, event) -> bool:
        """마우스를 안 쓰는 사람도 옮기고 늘일 수 있어야 한다."""
        block = self.selected_block()
        if block is None or block.locked:
            return False
        step = 1 if event.modifiers() & Qt.KeyboardModifier.AltModifier else SNAP_MINUTES
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        key = event.key()
        if key not in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return False
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.block_activated(block)
            return True
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            ordered = sorted(self._blocks, key=lambda item: (item.visible_start, item.item_id))
            index = ordered.index(block)
            target = ordered[max(0, min(len(ordered) - 1, index + (-1 if key == Qt.Key.Key_Up else 1)))]
            self.view.scene().clearSelection()
            target.setSelected(True)
            self.view.ensureVisible(target)
            return True
        origin = (block.start, block.end)
        delta = timedelta(minutes=-step if key == Qt.Key.Key_Up else step)
        if shift:
            if block.time_mode == "point":
                return True
            # Shift는 길이 조정 — 마우스의 모서리 끌기와 같은 동작.
            end = max(block.start + timedelta(minutes=MIN_MINUTES), block.end + delta)
            if end.date() != block.start.date():
                return True
            block.end = end
            self.preview_block(block)
            self.commit_resize(block, origin)
            return True
        start = block.start + delta
        if start.date() != block.start.date() or start.hour * 60 + start.minute < 0:
            return True
        length = block.end - block.start
        block.start, block.end = start, start + length
        self.preview_block(block)
        self.commit_move(block, origin)
        return True

    def blocks(self) -> list[ScheduleBlock]:
        return list(self._blocks)


def _clusters(blocks: list[ScheduleBlock]) -> list[list[ScheduleBlock]]:
    """시간이 사슬처럼 물린 덩어리로 묶는다."""
    groups: list[list[ScheduleBlock]] = []
    current: list[ScheduleBlock] = []
    reach: datetime | None = None
    for block in blocks:
        if current and reach is not None and block.visible_start >= reach:
            groups.append(current)
            current, reach = [], None
        current.append(block)
        reach = _visual_end(block) if reach is None else max(reach, _visual_end(block))
    if current:
        groups.append(current)
    return groups


def _visual_end(block: ScheduleBlock) -> datetime:
    minute = block.visible_start.hour * 60 + block.visible_start.minute
    visual_minutes = block.canvas.y_to_minute(block.canvas.minute_to_y(minute) + block.canvas.minimum_block_height()) - minute
    return max(block.visible_start + timedelta(minutes=visual_minutes), block.visible_end)


class _DayHeader(QWidget):
    """요일 머리줄.  시간축과 같은 폭으로 나뉜다."""

    def __init__(self, canvas: CalendarCanvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.setFixedHeight(44)
        self.setObjectName("scheduleCanvasHeader")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            column = self.canvas.column_at(event.position().x())
            if column is not None:
                self.canvas.dateSelected.emit(self.canvas._start + timedelta(days=column))
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        from PyQt6.QtGui import QPainter

        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#F8FAFC"))
        painter.setPen(QPen(QColor(GRID_LINE)))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        painter.setPen(QColor(GUTTER_INK))
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        width = self.canvas.column_width()
        line_height = self.height() / 2
        for column, label in enumerate(self.canvas._headers):
            left = GUTTER + column * width
            day = self.canvas._start + timedelta(days=column)
            if day == date.today():
                painter.setBrush(QColor(SELECT_INK))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(left + width / 2, line_height * 1.5), line_height / 2 - 1, line_height / 2 - 1)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(QRectF(left, line_height, width, line_height), int(Qt.AlignmentFlag.AlignCenter), str(day.day))
                painter.setPen(QColor(GUTTER_INK))
                painter.drawText(QRectF(left, 0, width, line_height), int(Qt.AlignmentFlag.AlignCenter), "월화수목금토일"[day.weekday()])
                continue
            painter.drawText(
                QRectF(left, 0, width, self.height()),
                int(Qt.AlignmentFlag.AlignCenter), f"{'월화수목금토일'[day.weekday()]}\n{day.day}",
            )
