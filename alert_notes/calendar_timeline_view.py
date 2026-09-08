from __future__ import annotations

from datetime import date, datetime, timedelta

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from ui_polish import apply_numeric_font
from .sqlite_store import DATETIME_FMT


CATEGORY_COLORS = {
    "sky": ("#E7F0FF", "#234F9A"),
    "mint": ("#E4F8EE", "#176448"),
    "peach": ("#FFE9E7", "#9C3D37"),
    "vanilla": ("#FFF4D6", "#815B10"),
    "lavender": ("#F0EAFE", "#6042A6"),
}


class CalendarTimelineView(QTableWidget):
    # 한 시간이 한 행이고, 행 높이는 고정이다.  그래서 "지금 몇 시 몇 분"을
    # 픽셀로 바꾸는 계산이 정확히 떨어진다.
    ROW_HEIGHT = 52
    # 스타일시트의 ::item { padding: 8px } 와 같은 값.  칸 안에서 몇 번째
    # 일정을 눌렀는지 세려면 글자가 어디서 시작하는지 알아야 한다.
    CELL_PADDING = 8
    # 일정 하나가 차지하는 줄 수 — "14:00 제목" / "업무 · 일정"
    LINES_PER_EVENT = 2

    def __init__(self, parent=None):
        super().__init__(0, 8, parent)
        self.setObjectName("scheduleTimeline")
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        self.horizontalHeader().setMinimumHeight(46)
        self.setAccessibleName("일정 캘린더 시간표")
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 72)
        self.setMinimumWidth(620)
        # 분 단위로 가운데를 맞추려면 스크롤이 칸 단위가 아니라 픽셀 단위여야 한다.
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._shows_today = False
        # 직접 스크롤해서 다른 시간대를 보고 있는 사람에게서 화면을 빼앗지 않는다.
        self._follow_now = True
        self.verticalScrollBar().actionTriggered.connect(self._user_scrolled)
        self._clock = QTimer(self)
        self._clock.setInterval(60_000)
        self._clock.timeout.connect(self._minute_tick)
        self._clock.start()
        # 레이아웃이 끝난 뒤로 미루는 스크롤.  이 표를 부모로 두었으니 표가 먼저
        # 사라지면 타이머도 같이 사라져, 없어진 표를 건드리는 일이 없다.
        self._scroll_soon = QTimer(self)
        self._scroll_soon.setSingleShot(True)
        self._scroll_soon.timeout.connect(self._deferred_scroll)
        self._scroll_force = False
        apply_numeric_font(self)

    def render_range(self, start, end, items) -> None:
        day_count = (end - start).days
        self._shows_today = start <= date.today() < end
        self.setColumnCount(day_count + 1)
        weekdays = "월화수목금토일"
        self.setHorizontalHeaderLabels(
            ["시간"] + [f"{weekdays[(start + timedelta(days=i)).weekday()]}\n{(start + timedelta(days=i)):%m/%d}" for i in range(day_count)]
        )
        for column in range(1, self.columnCount()):
            self.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.setRowCount(24)
        self.clearSpans()
        self.clearContents()
        for row, hour in enumerate(range(24)):
            label = QTableWidgetItem(f"{hour:02d}:00")
            label.setFlags(Qt.ItemFlag.ItemIsEnabled)
            label.setForeground(QColor("#64748B"))
            self.setItem(row, 0, label)
        occupied = {}
        for event in items:
            due = datetime.strptime(event["display_start_at"], DATETIME_FMT)
            column, row = 1 + (due.date() - start).days, due.hour
            if not (0 <= row < 24 and 1 <= column < self.columnCount()):
                continue
            duration = max(1, round((datetime.strptime(event["display_end_at"], DATETIME_FMT) - due).total_seconds() / 60))
            span = max(1, min(24 - row, (duration + 59) // 60))
            top_row = occupied.get((row, column), row)
            existing = self.item(top_row, column)
            cell = existing if existing is not None else QTableWidgetItem()
            # 위에서부터 쌓아야 몇 번째 일정을 눌렀는지 좌표로 셀 수 있다.
            cell.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            refs = list(cell.data(Qt.ItemDataRole.UserRole) or [])
            refs.append((int(event["id"]), str(event["occurrence_at"])))
            cell.setData(Qt.ItemDataRole.UserRole, refs)
            status = "완료" if event["status"] == "completed" else "할 일" if event["item_type"] == "task" else "일정"
            line = f"{due:%H:%M}  {event['title']}\n{_category_name(event['category'])} · {status}"
            cell.setText((cell.text() + "\n" if cell.text() else "") + line)
            cell.setToolTip(cell.text())
            background, foreground = CATEGORY_COLORS.get(str(event["category"]), ("#E7F0FF", "#234F9A"))
            cell.setBackground(QColor(background))
            cell.setForeground(QColor("#64748B" if event["status"] == "completed" else foreground))
            if existing is None:
                self.setItem(top_row, column, cell)
            if top_row == row and all((value, column) not in occupied for value in range(row, row + span)):
                if span > 1:
                    self.setSpan(row, column, span, 1)
                for value in range(row, row + span):
                    occupied[(value, column)] = row
        # 첫 그리기에서는 뷰포트 높이가 아직 0이라 한 박자 뒤에 맞춘다.
        self.scroll_to_now_soon()

    # ------------------------------------------------------------ 현재 시각 --
    def _user_scrolled(self, _action) -> None:
        """휠·드래그·키로 움직였을 때만 불린다.  프로그램이 옮긴 스크롤은 조용하다."""
        self._follow_now = False

    def _minute_tick(self) -> None:
        self.viewport().update()
        self.scroll_to_now()

    def scroll_to_now_soon(self, force: bool = False) -> None:
        """레이아웃이 자리를 잡은 다음 프레임에 현재 시각으로 맞춘다."""
        self._scroll_force = self._scroll_force or force
        self._scroll_soon.start(0)

    def _deferred_scroll(self) -> None:
        force, self._scroll_force = self._scroll_force, False
        self.scroll_to_now(force=force)

    def scroll_to_now(self, force: bool = False) -> None:
        """현재 시각을 화면 정중앙에 둔다.

        force=False면 사용자가 한 번이라도 직접 스크롤한 뒤에는 따라가지 않는다.
        다른 시간대를 보고 있는 사람에게서 화면을 빼앗지 않기 위해서다.
        """
        if not self._shows_today:
            return
        if not force and not self._follow_now:
            return
        now = datetime.now()
        center = (now.hour + now.minute / 60) * self.ROW_HEIGHT
        bar = self.verticalScrollBar()
        value = int(center - self.viewport().height() / 2)
        bar.setValue(max(bar.minimum(), min(value, bar.maximum())))
        self._follow_now = True

    def stop_clock(self) -> None:
        self._clock.stop()
        self._scroll_soon.stop()

    # -------------------------------------------------------------- 클릭 위치 --
    def ref_at_point(self, row: int, col: int, point: QPoint | None = None) -> tuple | None:
        """누른 지점에 놓인 일정.  None은 "그 칸의 빈 자리"라는 뜻이다.

        한 칸이 한 시간이라 14:00 일정과 14:30 일정이 같은 칸에 쌓인다.  칸에
        일정이 있다는 이유만으로 첫 일정의 편집을 열면, 새 일정을 만들려던
        사람이 기존 일정을 덮어쓰게 된다.  그래서 누른 높이로 대상을 가른다.
        """
        item = self.item(row, col)
        refs = list(item.data(Qt.ItemDataRole.UserRole) or []) if item is not None else []
        if not refs:
            return None
        if point is None:
            # 키보드로 연 경우엔 위치가 없다.  예전처럼 첫 일정을 연다.
            return refs[0]
        rect = self.visualRect(self.model().index(row, col))
        if not rect.isValid():
            return refs[0]
        block = max(1, self.fontMetrics().height() * self.LINES_PER_EVENT)
        index = int(max(0, point.y() - rect.top() - self.CELL_PADDING) // block)
        return refs[index] if index < len(refs) else None

    def row_at_point(self, point: QPoint | None, fallback: int) -> int:
        """병합된 칸을 눌러도 실제로 누른 행을 돌려준다."""
        if point is None:
            return fallback
        row = self.rowAt(point.y())
        return row if row >= 0 else fallback


def _category_name(value) -> str:
    return {"sky": "업무", "mint": "개인", "peach": "중요", "vanilla": "학습", "lavender": "기타"}.get(str(value), "일정")
