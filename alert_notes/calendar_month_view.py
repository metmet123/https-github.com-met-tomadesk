from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from .sqlite_store import DATETIME_FMT


CATEGORY_COLORS = {
    "sky": ("#E7F0FF", "#234F9A"),
    "mint": ("#E4F8EE", "#176448"),
    "peach": ("#FFE9E7", "#9C3D37"),
    "vanilla": ("#FFF4D6", "#815B10"),
    "lavender": ("#F0EAFE", "#6042A6"),
}


class CalendarMonthView(QTableWidget):
    """Six-week month grid that exposes the small QCalendarWidget API we used."""

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
        self.setObjectName("scheduleMonthGrid")
        self.setAccessibleName("월간 일정 캘린더")
        self.setHorizontalHeaderLabels(list("월화수목금토일"))
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().hide()
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setShowGrid(False)
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
            day = datetime.strptime(item["display_start_at"], DATETIME_FMT).date()
            self._events_by_day.setdefault(day, []).append(item)
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
        self.clearContents()
        first = date(self._year, self._month, 1)
        grid_start = first - timedelta(days=first.weekday())
        today = date.today()
        for index in range(42):
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

    def _cell_widget(self, day: date, events: list) -> QFrame:
        frame = QFrame()
        frame.setObjectName("monthDayCell")
        frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        frame.setProperty("outside", day.month != self._month)
        frame.setProperty("today", day == date.today())
        frame.setProperty("selected", day == self._selected)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 7, 8, 6)
        layout.setSpacing(3)
        day_label = QLabel(str(day.day))
        day_label.setObjectName("monthDayNumber")
        # Saturdays and Sundays get their own colour so weeks are countable.
        day_label.setProperty(
            "weekday", "sat" if day.weekday() == 5 else "sun" if day.weekday() == 6 else "day"
        )
        layout.addWidget(day_label)
        for countdown, title in getattr(self, "_deadlines", {}).get(day, [])[:2]:
            chip = QLabel(f"{countdown} {title}")
            chip.setObjectName("monthDeadlineChip")
            chip.setToolTip(f"D-Day · {title}")
            layout.addWidget(chip)
        # A past schedule is a fact that already happened, so it steps back.  A
        # past D-Day is work still owed, so it keeps its colour — hence the chips
        # above are untouched.
        past_day = self._dim_past and day < date.today()
        for event in events[:3]:
            label = QLabel(("✓ " if event["status"] == "completed" else "") + str(event["title"]))
            label.setObjectName("monthEventChip")
            label.setProperty("category", str(event["category"]))
            label.setProperty("completed", event["status"] == "completed")
            label.setProperty("past", past_day)
            label.setToolTip(str(event["title"]))
            layout.addWidget(label)
        if len(events) > 3:
            more = QLabel(f"+{len(events) - 3}개 더보기")
            more.setObjectName("monthMoreLabel")
            layout.addWidget(more)
        layout.addStretch()
        return frame

    def _select_cell(self, row: int, column: int) -> None:
        item = self.item(row, column)
        if item is None:
            return
        self._selected = item.data(Qt.ItemDataRole.UserRole)
        self._render()
        self.dateSelectionChanged.emit()

    def _activate_cell(self, row: int, column: int) -> None:
        item = self.item(row, column)
        if item is None:
            return
        values = item.data(Qt.ItemDataRole.UserRole + 1) or []
        if values:
            item_id, occurrence_at = values[0]
            self.scheduleActivated.emit(item_id, occurrence_at)
            return
        # An empty day used to do nothing, even though the hint promised
        # "날짜를 클릭하면 일정 추가".
        day = item.data(Qt.ItemDataRole.UserRole)
        if day is not None:
            self.dateActivated.emit(QDate(day.year, day.month, day.day))
