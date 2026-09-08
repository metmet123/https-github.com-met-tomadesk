"""일정을 좌표와 크기를 가진 조각으로 그리는 시간표.

표 위젯에서는 일정이 "칸에 든 글자"였다.  글자에는 잡을 모서리가 없어 길이를
바꿀 수 없었고, 칸이 한 시간짜리라 10시 30분 일정도 10시 칸 꼭대기에 붙었다.
여기서는 1분 = 1픽셀로 두고 일정마다 사각형 조각을 만든다.  그래서

* 10:30은 10시와 11시 사이 정확한 자리에 놓이고,
* 아래 모서리를 끌면 길이가 바뀌며,
* 겹치는 일정은 폭을 나눠 나란히 선다.

바깥에서 쓰는 것은 :class:`CalendarCanvas` 하나다.  ``render_range``로 그리고,
조작 결과는 신호로 알린다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPen
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QVBoxLayout, QWidget,
)

from .categories import CATEGORY_COLORS, category_name
from .sqlite_store import DATETIME_FMT


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
        self.locked = bool(event.get("locked"))
        self.start: datetime = event["start"]
        self.end: datetime = event["end"]
        self._press_mode = None
        self._press_offset = 0.0
        self._origin = (self.start, self.end)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setToolTip(self._tooltip())
        self.setZValue(10)

    # ------------------------------------------------------------------ 그림 --
    def _tooltip(self) -> str:
        span = "종일" if self.start.time() == time.min and self.end.time() >= time(23, 59) else \
            f"{self.start:%H:%M} – {self.end:%H:%M}"
        return f"{self.title}\n{self.start:%m월 %d일} {span} · {category_name(self.category)}"

    def paint(self, painter, option, widget=None) -> None:
        background, foreground = CATEGORY_COLORS.get(self.category, ("#E7F0FF", "#234F9A"))
        if self.status == "completed":
            foreground = GUTTER_INK
        rect = self.rect()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(background))
        pen = QPen(QColor(SELECT_INK if self.isSelected() else foreground))
        pen.setWidth(2 if self.isSelected() else 1)
        painter.setPen(pen)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        painter.setPen(QColor(foreground))
        text_rect = rect.adjusted(9, 5, -9, -5)
        if text_rect.height() >= 16 and text_rect.width() > 24:
            font = QFont(painter.font())
            font.setBold(True)
            painter.setFont(font)
            head = f"{self.start:%H:%M}  {self.title}"
            painter.drawText(
                text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), head
            )
        if text_rect.height() >= 34:
            font = QFont(painter.font())
            font.setBold(False)
            painter.setFont(font)
            marker = "완료" if self.status == "completed" else "할 일" if self.item_type == "task" else "일정"
            painter.drawText(
                text_rect.adjusted(0, 17, 0, 0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                f"{category_name(self.category)} · {marker}",
            )
        if not self.locked and rect.height() >= 26:
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
        return not self.locked and position.y() >= self.rect().bottom() - EDGE_GRIP

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
        self._press_mode = "locked" if self.locked else ("resize" if edge else "move")
        self._press_offset = scene_y - self.rect().top()

    def drag_to(self, scene_y: float, step: int = SNAP_MINUTES) -> None:
        if self._press_mode == "move":
            length = max(MIN_MINUTES, int((self.end - self.start).total_seconds() // 60))
            top = snap(scene_y - self._press_offset, step)
            top = max(0, min(top, DAY_MINUTES - length))
            self.start = self._day_at(top)
            self.end = self.start + timedelta(minutes=length)
        elif self._press_mode == "resize":
            start_minutes = self.start.hour * 60 + self.start.minute
            bottom = snap(scene_y, step)
            bottom = max(start_minutes + MIN_MINUTES, min(DAY_MINUTES, bottom))
            self.end = self._day_at(bottom, base=self.start.date())
        else:
            return
        self.canvas.preview_block(self)

    def mousePressEvent(self, event) -> None:
        self.setSelected(True)
        self.begin_press(event.scenePos().y(), self._on_edge(event.pos()))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._press_mode not in {"move", "resize"}:
            return
        step = 1 if event.modifiers() & Qt.KeyboardModifier.AltModifier else SNAP_MINUTES
        self.drag_to(event.scenePos().y(), step)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
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
        painter.setPen(QPen(QColor(GRID_HALF)))
        for minutes in range(0, DAY_MINUTES + 1, 30):
            if minutes % 60:
                painter.drawLine(QPointF(left, minutes), QPointF(rect.right(), minutes))
        painter.setPen(QPen(QColor(GRID_LINE)))
        for hour in range(25):
            y = hour * 60
            painter.drawLine(QPointF(left - 8, y), QPointF(rect.right(), y))
        for column in range(1, self.canvas.column_count):
            x = self.canvas.column_left(column)
            painter.drawLine(QPointF(x, 0), QPointF(x, DAY_MINUTES))
        painter.setPen(QColor(GUTTER_INK))
        font = QFont(painter.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1))
        painter.setFont(font)
        for hour in range(24):
            painter.drawText(QRectF(6, hour * 60 + 3, GUTTER - 14, 18),
                             int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop),
                             f"{hour:02d}:00")

    def drawForeground(self, painter, rect: QRectF) -> None:
        column = self.canvas.column_for_date(datetime.now().date())
        if column is None:
            return
        minutes = datetime.now().hour * 60 + datetime.now().minute
        left = self.canvas.column_left(column)
        right = left + self.canvas.column_width()
        painter.setPen(QPen(QColor(NOW_LINE), 1.5))
        painter.drawLine(QPointF(left, minutes), QPointF(right, minutes))
        painter.setBrush(QColor(NOW_LINE))
        painter.drawEllipse(QPointF(left + 3, minutes), 3.5, 3.5)

    # ---------------------------------------------------------------- 드래그 --
    def mousePressEvent(self, event) -> None:
        if self.itemAt(event.pos()) is not None:
            super().mousePressEvent(event)
            return
        point = self.mapToScene(event.pos())
        column = self.canvas.column_at(point.x())
        if column is None:
            return
        minutes = snap(point.y(), 1 if event.modifiers() & Qt.KeyboardModifier.AltModifier else SNAP_MINUTES)
        self._band_origin = (column, minutes)
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
        self._update_band(snap(point.y(), step))

    def mouseReleaseEvent(self, event) -> None:
        if self._band_origin is None:
            super().mouseReleaseEvent(event)
            return
        column, origin = self._band_origin
        point = self.mapToScene(event.pos())
        step = 1 if event.modifiers() & Qt.KeyboardModifier.AltModifier else SNAP_MINUTES
        first, last = sorted((origin, snap(point.y(), step)))
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
        self._band.setRect(QRectF(left, first, max(10, self.canvas.column_width() - 4), max(2, last - first)))

    def _clear_band(self) -> None:
        if self._band is not None:
            self.scene().removeItem(self._band)
            self._band = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.canvas.reflow()

    def keyPressEvent(self, event) -> None:
        if self.canvas.handle_key(event):
            return
        super().keyPressEvent(event)


class CalendarCanvas(QWidget):
    """바깥에서 쓰는 시간표 위젯."""

    rangeSelected = pyqtSignal(datetime, datetime)
    scheduleClicked = pyqtSignal(int, str)
    scheduleActivated = pyqtSignal(int, str)
    scheduleMoved = pyqtSignal(int, str, datetime, datetime, datetime, datetime)
    scheduleResized = pyqtSignal(int, str, datetime, datetime, datetime, datetime)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("scheduleCanvas")
        self._start = date.today()
        self.column_count = 1
        self._blocks: list[ScheduleBlock] = []
        self._headers: list[str] = []
        self.header = _DayHeader(self)
        self.view = TimelineView(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.view, 1)
        self.setAccessibleName("일정 시간표")
        self._scrolled_once = False
        # 사람이 손으로 굴린 뒤에는 시계가 화면을 빼앗지 않는다.
        self._user_scrolled = False
        bar = self.view.verticalScrollBar()
        bar.sliderPressed.connect(self.mark_user_scroll)
        bar.actionTriggered.connect(lambda _action: self.mark_user_scroll())

    # ------------------------------------------------------------------ 좌표 --
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
        self._start = start
        self.column_count = max(1, (end - start).days)
        weekdays = "월화수목금토일"
        self._headers = [
            f"{weekdays[(start + timedelta(days=i)).weekday()]} {(start + timedelta(days=i)):%m/%d}"
            for i in range(self.column_count)
        ]
        self.header.update()
        self.clearContents()
        for event in items:
            try:
                begin = datetime.strptime(str(event["display_start_at"]), DATETIME_FMT)
                finish = datetime.strptime(str(event["display_end_at"]), DATETIME_FMT)
            except (ValueError, KeyError):
                continue
            if self.column_for_date(begin.date()) is None:
                continue
            if finish <= begin:
                finish = begin + timedelta(minutes=MIN_MINUTES)
            block = ScheduleBlock(self, {
                "id": event["id"], "occurrence_at": event["occurrence_at"], "title": event["title"],
                "category": event["category"], "status": event["status"], "item_type": event["item_type"],
                "locked": event["source_reminder_id"] is not None if "source_reminder_id" in event.keys() else False,
                "start": begin, "end": finish,
            })
            self.view.scene().addItem(block)
            self._blocks.append(block)
        self.reflow()
        if not self._scrolled_once:
            self._scrolled_once = True
            self.scroll_to_now(force=True)

    def clearContents(self) -> None:
        for block in self._blocks:
            self.view.scene().removeItem(block)
        self._blocks = []

    def reflow(self) -> None:
        """겹치는 일정을 폭으로 나눠 나란히 세운다."""
        width = self.column_width()
        self.view.setSceneRect(QRectF(0, 0, GUTTER + width * self.column_count, DAY_MINUTES))
        for column in range(self.column_count):
            blocks = sorted(
                (block for block in self._blocks if self.column_for_date(block.start.date()) == column),
                key=lambda item: (item.start, item.end),
            )
            # 서로 물려 있는 덩어리마다 따로 폭을 나눈다.  하루 전체로 한 번에
            # 나누면 겹치지도 않는 일정까지 반 폭이 된다.
            for cluster in _clusters(blocks):
                lanes: list[datetime] = []
                placed: list[tuple[ScheduleBlock, int]] = []
                for block in cluster:
                    lane = next(
                        (index for index, busy in enumerate(lanes) if busy <= block.start), len(lanes)
                    )
                    if lane == len(lanes):
                        lanes.append(block.end)
                    else:
                        lanes[lane] = block.end
                    placed.append((block, lane))
                total = max(1, len(lanes))
                for block, lane in placed:
                    self._place(block, column, lane, total)
        self.view.viewport().update()

    def _place(self, block: ScheduleBlock, column: int, lane: int, lanes: int) -> None:
        width = self.column_width()
        share = (width - 6) / max(1, lanes)
        left = self.column_left(column) + 3 + lane * share
        top = block.start.hour * 60 + block.start.minute
        height = max(MIN_MINUTES, int((block.end - block.start).total_seconds() // 60))
        block.setPos(0, 0)
        block.setRect(QRectF(left, top, max(28.0, share - LANE_GAP), height))

    def preview_block(self, block: ScheduleBlock) -> None:
        """끄는 동안에는 그 조각만 다시 그린다."""
        column = self.column_for_date(block.start.date())
        if column is None:
            return
        rect = block.rect()
        top = block.start.hour * 60 + block.start.minute
        height = max(MIN_MINUTES, int((block.end - block.start).total_seconds() // 60))
        block.setRect(QRectF(rect.left(), top, rect.width(), height))
        block.setToolTip(block._tooltip())

    def mark_user_scroll(self) -> None:
        self._user_scrolled = True

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
        centre = now.hour * 60 + now.minute
        target = int(centre - self.view.viewport().height() / 2)
        bar.setValue(max(bar.minimum(), min(target, bar.maximum())))
        self._user_scrolled = False

    def scroll_to_hour(self, hour: int) -> None:
        self.view.verticalScrollBar().setValue(max(0, hour * 60))

    def rect_for_range(self, start: datetime, end: datetime) -> QRect | None:
        """팝오버를 세울 자리.  캔버스 좌표로 돌려준다."""
        column = self.column_for_date(start.date())
        if column is None:
            return None
        top = start.hour * 60 + start.minute
        bottom = max(top + MIN_MINUTES, int((end - start).total_seconds() // 60) + top)
        top_left = self.view.mapFromScene(QPointF(self.column_left(column), top))
        bottom_right = self.view.mapFromScene(
            QPointF(self.column_left(column) + self.column_width(), bottom)
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
        origin = (block.start, block.end)
        delta = timedelta(minutes=-step if key == Qt.Key.Key_Up else step)
        if shift:
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
        if current and reach is not None and block.start >= reach:
            groups.append(current)
            current, reach = [], None
        current.append(block)
        reach = block.end if reach is None else max(reach, block.end)
    if current:
        groups.append(current)
    return groups


class _DayHeader(QWidget):
    """요일 머리줄.  시간축과 같은 폭으로 나뉜다."""

    def __init__(self, canvas: CalendarCanvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.setFixedHeight(44)
        self.setObjectName("scheduleCanvasHeader")

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
        for column, label in enumerate(self.canvas._headers):
            left = GUTTER + column * width
            painter.drawText(
                QRectF(left, 0, width, self.height()),
                int(Qt.AlignmentFlag.AlignCenter), label,
            )
