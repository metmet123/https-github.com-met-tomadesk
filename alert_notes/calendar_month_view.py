from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from .sqlite_store import DATETIME_FMT


class _ActionLabel(QLabel):
    activated = pyqtSignal()

    def __init__(self, text):
        super().__init__(text)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(0)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.activated.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
        else:
            super().keyPressEvent(event)


CATEGORY_COLORS = {
    "sky": ("#E7F0FF", "#234F9A"),
    "mint": ("#E4F8EE", "#176448"),
    "peach": ("#FFE9E7", "#9C3D37"),
    "vanilla": ("#FFF4D6", "#815B10"),
    "lavender": ("#F0EAFE", "#6042A6"),
}


class CalendarMonthView(QTableWidget):
    """Compact month grid with independently actionable event chips."""

    dateSelectionChanged = pyqtSignal()
    scheduleActivated = pyqtSignal(int, str)
    dateActivated = pyqtSignal(QDate)

    def __init__(self, parent=None):
        super().__init__(6, 7, parent)
        self._year = date.today().year
        self._month = date.today().month
        self._selected = date.today()
        self._dim_past = True
        self._events_by_day: dict[date, list] = {}
        self._span_labels = []
        self._span_rows = {}
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._render)
        self.setObjectName("scheduleMonthGrid")
        self.setAccessibleName("월간 일정 캘린더")
        self.setHorizontalHeaderLabels(list("월화수목금토일"))
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().hide()
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setShowGrid(True)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.cellClicked.connect(self._select_cell)
        self.cellDoubleClicked.connect(self._activate_cell)

    def set_deadlines(self, deadlines: dict) -> None:
        """date -> [(countdown, title)], so the month shows D-Day next to events."""
        self._deadlines = dict(deadlines or {})

    def set_month(self, year: int, month: int, items) -> None:
        self._year, self._month = year, month
        self._events_by_day = {}
        for item in items:
            begin = datetime.strptime(item["display_start_at"], DATETIME_FMT)
            finish = datetime.strptime(item["display_end_at"], DATETIME_FMT)
            first = date(year, month, 1)
            grid_start = first - timedelta(days=first.weekday())
            day = max(grid_start, begin.date())
            last = min(grid_start + timedelta(days=42), (max(finish, begin + timedelta(minutes=1)) - timedelta(microseconds=1)).date() + timedelta(days=1))
            while day < last:
                self._events_by_day.setdefault(day, []).append(item)
                day += timedelta(days=1)
        self._render()

    def set_dim_past(self, value: bool) -> None:
        if bool(value) == self._dim_past:
            return
        self._dim_past = bool(value)
        self._render()

    def setCurrentPage(self, year: int, month: int) -> None:
        self._year, self._month = year, month
        self._render()

    def setSelectedDate(self, value: QDate) -> None:
        self._selected = value.toPyDate()
        self._render()

    def selectedDate(self) -> QDate:
        return QDate(self._selected.year, self._selected.month, self._selected.day)

    def _render(self) -> None:
        for label in self._span_labels:
            label.hide()
            label.deleteLater()
        self._span_labels = []
        self.clearContents()
        first = date(self._year, self._month, 1)
        self.setRowCount((first.weekday() + calendar.monthrange(self._year, self._month)[1] + 6) // 7)
        grid_start = first - timedelta(days=first.weekday())
        self._span_rows = {}
        for row in range(self.rowCount()):
            row_start = grid_start + timedelta(days=row * 7)
            row_end = row_start + timedelta(days=7)
            spans, seen, lanes = [], set(), []
            for offset in range(7):
                for event in self._events_by_day.get(row_start + timedelta(days=offset), []):
                    key = (event["id"], event["occurrence_at"])
                    begin = datetime.strptime(event["display_start_at"], DATETIME_FMT)
                    end = datetime.strptime(event["display_end_at"], DATETIME_FMT)
                    if key in seen or not event.get("all_day") or (end - timedelta(microseconds=1)).date() <= begin.date():
                        continue
                    seen.add(key)
                    first_col = max(0, (begin.date() - row_start).days)
                    last_col = min(7, ((end - timedelta(microseconds=1)).date() - row_start).days + 1)
                    lane = next((i for i, occupied in enumerate(lanes) if occupied <= first_col), len(lanes))
                    if lane == len(lanes):
                        lanes.append(last_col)
                    else:
                        lanes[lane] = last_col
                    spans.append((event, first_col, last_col, lane))
            self._span_rows[row] = (spans, min(2, len(lanes)))
        today = date.today()
        for index in range(self.rowCount() * 7):
            day = grid_start + timedelta(days=index)
            row, column = divmod(index, 7)
            events = self._events_by_day.get(day, [])
            lines = [str(day.day)]
            for event in events[:3]:
                marker = "✓ " if event["status"] == "completed" else ""
                lines.append(f"{marker}{str(event['title'])[:13]}")
            if len(events) > 3:
                lines.append(f"+{len(events) - 3}개 더보기")
            item = QTableWidgetItem("\n".join(lines))
            item.setData(Qt.ItemDataRole.UserRole, day)
            item.setData(
                Qt.ItemDataRole.UserRole + 1,
                [(int(event["id"]), str(event["occurrence_at"])) for event in events],
            )
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            item.setToolTip("\n".join(str(event["title"]) for event in events))
            if day.month != self._month:
                item.setForeground(QColor("#A7B0BF"))
                item.setBackground(QColor("#F8FAFC"))
            elif column >= 5:
                item.setBackground(QColor("#FBFCFF"))
            if events:
                background, foreground = CATEGORY_COLORS.get(str(events[0]["category"]), ("#E7F0FF", "#234F9A"))
                item.setBackground(QColor(background))
                item.setForeground(QColor("#64748B" if events[0]["status"] == "completed" else foreground))
            if day == today:
                item.setData(Qt.ItemDataRole.UserRole + 2, "today")
            if day == self._selected:
                item.setData(Qt.ItemDataRole.UserRole + 3, "selected")
            self.setItem(row, column, item)
            self.setCellWidget(row, column, self._cell_widget(day, events))
        for row, (spans, lane_count) in self._span_rows.items():
            for event, first_col, last_col, lane in spans:
                if lane >= lane_count:
                    continue
                rect = self.visualItemRect(self.item(row, first_col)).united(self.visualItemRect(self.item(row, last_col - 1)))
                label = _ActionLabel("종일 " + str(event["title"]))
                label.setParent(self.viewport())
                label.setObjectName("monthEventChip")
                label.setProperty("category", str(event["category"]))
                label.setToolTip(str(event["title"]))
                label.activated.connect(lambda item_id=int(event["id"]), occurrence=str(event["occurrence_at"]): self.scheduleActivated.emit(item_id, occurrence))
                label.setGeometry(rect.left() + 3, rect.top() + 27 + lane * 25, rect.width() - 6, 23)
                label.show()
                self._span_labels.append(label)

    def _cell_widget(self, day: date, events: list) -> QFrame:
        frame = QFrame()
        frame.setObjectName("monthDayCell")
        frame.setProperty("outside", day.month != self._month)
        frame.setProperty("today", day == date.today())
        frame.setProperty("selected", day == self._selected)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(2)
        day_label = QLabel(str(day.day))
        day_label.setObjectName("monthDayNumber")
        day_label.setFixedWidth(max(26, self.fontMetrics().horizontalAdvance("30") + 10))
        day_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # Saturdays and Sundays get their own colour so weeks are countable.
        day_label.setProperty(
            "weekday", "sat" if day.weekday() == 5 else "sun" if day.weekday() == 6 else "day"
        )
        layout.addWidget(day_label)
        first = date(self._year, self._month, 1)
        row = (day - (first - timedelta(days=first.weekday()))).days // 7
        spans, span_count = self._span_rows.get(row, ([], 0))
        drawn = {(event["id"], event["occurrence_at"]) for event, _, _, lane in spans if lane < span_count}
        events = [event for event in events if (event["id"], event["occurrence_at"]) not in drawn]
        if span_count:
            layout.addSpacing(span_count * 25)
        for countdown, title in getattr(self, "_deadlines", {}).get(day, [])[:2]:
            chip = QLabel(f"{countdown} {title}")
            chip.setObjectName("monthDeadlineChip")
            chip.setToolTip(f"D-Day · {title}")
            layout.addWidget(chip)
        # A past schedule is a fact that already happened, so it steps back.  A
        # past D-Day is work still owed, so it keeps its colour — hence the chips
        # above are untouched.
        past_day = self._dim_past and day < date.today()
        deadlines = len(getattr(self, "_deadlines", {}).get(day, [])[:2])
        line_height = max(23, self.fontMetrics().height() + 8)
        capacity = max(1, (self.viewport().height() // max(1, self.rowCount()) - 30 - span_count * 25) // line_height - deadlines)
        shown = max(0, capacity - 1) if len(events) > capacity else capacity
        for event in events[:shown]:
            begin = datetime.strptime(event["display_start_at"], DATETIME_FMT)
            prefix = "종일 " if event.get("all_day") else "← " if begin.date() < day else f"{begin:%H:%M} "
            label = _ActionLabel(("✓ " if event["status"] == "completed" else "") + prefix + str(event["title"]))
            label.activated.connect(lambda item_id=int(event["id"]), occurrence=str(event["occurrence_at"]): self.scheduleActivated.emit(item_id, occurrence))
            label.setFixedHeight(line_height - 2)
            label.setObjectName("monthEventChip")
            label.setProperty("category", str(event["category"]))
            label.setProperty("completed", event["status"] == "completed")
            label.setProperty("past", past_day)
            label.setToolTip(str(event["title"]))
            layout.addWidget(label)
        if len(events) > shown:
            more = _ActionLabel(f"+{len(events) - shown}개 더보기")
            more.activated.connect(lambda value=day: self._select_day(value))
            more.setObjectName("monthMoreLabel")
            layout.addWidget(more)
        layout.addStretch()
        return frame

    def _select_cell(self, row: int, column: int) -> None:
        item = self.item(row, column)
        if item is None:
            return
        self._select_day(item.data(Qt.ItemDataRole.UserRole))

    def _select_day(self, day: date) -> None:
        self._selected = day
        for row in range(self.rowCount()):
            for column in range(7):
                frame = self.cellWidget(row, column)
                item = self.item(row, column)
                if frame is not None and item is not None:
                    frame.setProperty("selected", item.data(Qt.ItemDataRole.UserRole) == day)
                    frame.style().unpolish(frame)
                    frame.style().polish(frame)
                    frame.update()
        self.dateSelectionChanged.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_resize_timer"):
            self._resize_timer.start(60)

    def _activate_cell(self, row: int, column: int) -> None:
        item = self.item(row, column)
        if item is None:
            return
        # An empty day used to do nothing, even though the hint promised
        # "날짜를 클릭하면 일정 추가".
        day = item.data(Qt.ItemDataRole.UserRole)
        if day is not None:
            self.dateActivated.emit(QDate(day.year, day.month, day.day))
