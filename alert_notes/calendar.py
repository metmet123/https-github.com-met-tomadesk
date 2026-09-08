from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PyQt6.QtCore import QDate, QEvent, QPoint, QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QBoxLayout, QCalendarWidget, QCheckBox, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ui_polish import apply_numeric_font, polish_button
from .calendar_canvas import CalendarCanvas
from .categories import CATEGORIES, CATEGORY_COLORS
from .deadline import deadline_chip_text, deadline_title, deadline_urgency, parse_deadline
from .calendar_month_view import CalendarMonthView
from .calendar_quick_editor import CalendarQuickEditor
from .schedule_editor import ScheduleEditor
from .schedule_popover import SchedulePopover
from .sqlite_store import DATETIME_FMT


COLORS = {
    "vanilla": "#fff3bf", "mint": "#dcfce7", "sky": "#dbeafe",
    "peach": "#fee2e2", "lavender": "#ede9fe",
}
INTERACTION_HINTS = {
    "day": "빈 시간을 클릭하면 일정 추가 · 일정을 클릭하면 편집 · 드래그하면 기간 지정",
    "week": "빈 시간을 클릭하면 일정 추가 · 일정을 클릭하면 편집 · 드래그하면 기간 지정",
    "month": "날짜를 클릭하면 일정 추가 · 일정을 클릭하면 편집",
    "list": "일정을 더블클릭하면 편집합니다.",
}



class CalendarPanel(QWidget):
    note_open_requested = pyqtSignal(int)
    note_created = pyqtSignal(int)
    schedule_changed = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._popover_slot = (None, None)
        self._last_move = None
        self._responsive_width = 1440
        self._drawer_open = False
        self.anchor = datetime.now().date()
        saved_mode = store.setting("calendar_view_mode", "")
        self._mode_was_saved = bool(saved_mode)
        self.mode = saved_mode if saved_mode in {"day", "week", "month", "list"} else "day"
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.root_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.root_layout.setContentsMargins(16, 14, 16, 14)
        self.root_layout.setSpacing(14)

        self.navigation = QFrame()
        self.navigation.setObjectName("calendarNavigation")
        self.navigation.setMinimumWidth(0)
        self.navigation.setMaximumWidth(220)
        nav = QVBoxLayout(self.navigation)
        nav.setContentsMargins(14, 16, 14, 16)
        nav.setSpacing(8)
        nav_title = QLabel("나의 일정")
        nav_title.setObjectName("pageTitle")
        nav.addWidget(nav_title)
        nav_subtitle = QLabel("오늘의 흐름과 할 일을 한눈에 확인하세요.")
        nav_subtitle.setObjectName("mutedLabel")
        nav_subtitle.setWordWrap(True)
        nav.addWidget(nav_subtitle)
        # 오늘 and 이번 주 are a place you are, so they sit together and show
        # which one you are on; 빠른 메모 is an action and stands apart.
        self.nav_today_button = _button("오늘", "오늘 일정 보기")
        self.nav_week_button = _button("이번 주", "이번 주 일정 보기")
        self.quick_memo_button = _button("빠른 메모", "빠른 메모 열기")
        nav_range = QVBoxLayout()
        nav_range.setContentsMargins(0, 0, 0, 0)
        nav_range.setSpacing(2)
        for button in (self.nav_today_button, self.nav_week_button):
            button.setObjectName("calendarNavButton")
            button.setCheckable(True)
            nav_range.addWidget(button)
        nav.addLayout(nav_range)
        nav.addSpacing(6)
        self.quick_memo_button.setObjectName("calendarNavButton")
        nav.addWidget(self.quick_memo_button)
        nav.addSpacing(10)
        # C3: jumping to a date used to mean clicking ‹ › over and over.
        self.mini_calendar = QCalendarWidget()
        self.mini_calendar.setObjectName("calendarMiniMonth")
        self.mini_calendar.setGridVisible(False)
        self.mini_calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.mini_calendar.setMaximumHeight(190)
        self.mini_calendar.setAccessibleName("날짜 이동 달력")
        self.mini_calendar.clicked.connect(self._jump_to_date)
        nav.addWidget(self.mini_calendar)
        nav.addSpacing(10)
        category_title = QLabel("카테고리")
        category_title.setObjectName("sectionTitle")
        nav.addWidget(category_title)
        # The legend used to draw five identical dark dots, so the colour coded
        # nothing.  Paint each one with the category's real colour instead.
        self.category_labels = {}
        for name, key in CATEGORIES:
            _background, foreground = CATEGORY_COLORS.get(key, ("#e2e8f0", "#475569"))
            label = QLabel(f'<span style="color:{foreground}">●</span>&nbsp;&nbsp;{name}')
            label.setObjectName("calendarCategoryLabel")
            label.setAccessibleName(f"{name} 카테고리")
            label.setToolTip(f"{name} 일정에 사용하는 색입니다.")
            self.category_labels[key] = label
            nav.addWidget(label)
        nav.addStretch()
        self.root_layout.addWidget(self.navigation)
        self.navigation.hide()

        self.calendar_body = QWidget()
        left = QVBoxLayout(self.calendar_body)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)
        header = QHBoxLayout()
        self.previous_button = _button("‹", "이전 기간")
        self.today_button = _button("오늘", "오늘로 이동")
        self.next_button = _button("›", "다음 기간")
        for button in (self.previous_button, self.today_button, self.next_button):
            header.addWidget(button)
        self._stacked_size = 0
        self.period_label = QLabel()
        self.period_label.setObjectName("pageTitle")
        apply_numeric_font(self.period_label)
        header.addStretch()
        header.addWidget(self.period_label)
        header.addStretch()
        # View switches are a state, actions are a verb: keep them apart and let
        # the current view read as selected instead of looking like four buttons.
        self.mode_buttons = {}
        self.mode_group = QWidget()
        mode_row = QHBoxLayout(self.mode_group)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(0)
        for mode, label in (("day", "일간"), ("week", "주간"), ("month", "월간"), ("list", "목록")):
            button = _button(label, f"{label} 일정 보기")
            button.setObjectName("calendarModeButton")
            button.setCheckable(True)
            button.setProperty("segment", "middle")
            button.clicked.connect(lambda _checked=False, value=mode: self._set_mode(value))
            self.mode_buttons[mode] = button
            mode_row.addWidget(button)
        self.mode_buttons["day"].setProperty("segment", "first")
        self.mode_buttons["list"].setProperty("segment", "last")
        header.addWidget(self.mode_group)
        header.addSpacing(14)
        self.header_quick_memo_button = _button("빠른 메모", "빠른 메모 열기")
        self.header_quick_memo_button.hide()
        header.addWidget(self.header_quick_memo_button)
        self.day_button = self.mode_buttons["day"]
        self.week_button = self.mode_buttons["week"]
        self.new_schedule_button = _button("+ 새 일정", "전체 일정 편집 열기")
        self.new_schedule_button.setObjectName("primaryButton")
        header.addWidget(self.new_schedule_button)
        self.new_task_button = _button("+ 새 할 일", "전체 할 일 편집 열기")
        header.addWidget(self.new_task_button)
        self.fullscreen_button = _button("전체 화면", "캘린더 전체 화면 열기")
        header.addWidget(self.fullscreen_button)
        left.addLayout(header)

        self.calendar_filter_bar = QFrame()
        self.calendar_filter_bar.setObjectName("scheduleSubCard")
        filter_layout = QHBoxLayout(self.calendar_filter_bar)
        filter_layout.setContentsMargins(10, 4, 8, 4)
        filter_layout.setSpacing(10)
        filter_layout.addWidget(QLabel("표시"))
        self.calendar_filter_checks: dict[str, QCheckBox] = {}
        for key, label in (
            ("events", "일정"), ("tasks", "할 일"), ("dday", "D-Day")
        ):
            check = QCheckBox(label)
            check.setAccessibleName(f"캘린더에 {label} 표시")
            check.setChecked(self._calendar_filter_value(key, True))
            check.toggled.connect(self._calendar_filter_changed)
            self.calendar_filter_checks[key] = check
            filter_layout.addWidget(check)
        filter_layout.addStretch()
        self.dday_only_button = QPushButton("D-Day만")
        self.dday_only_button.setAccessibleName("D-Day만 보기")
        self.dday_only_button.clicked.connect(self._show_only_dday)
        filter_layout.addWidget(self.dday_only_button)
        left.addWidget(self.calendar_filter_bar)
        self.calendar_deadline_strip = QLabel()
        self.calendar_deadline_strip.setObjectName("scheduleMirrorNotice")
        self.calendar_deadline_strip.setWordWrap(True)
        self.calendar_deadline_strip.setAccessibleName("현재 범위 D-Day")
        self.calendar_deadline_strip.hide()
        left.addWidget(self.calendar_deadline_strip)
        # 조작법을 상시 문장으로 붙여 두는 대신 커서(crosshair)·툴팁·드래그 블록이
        # 스스로 드러내게 한다.  라벨은 화면 낭독기를 위해 남기되 보이지 않는다.
        self.interaction_hint = QLabel(INTERACTION_HINTS["day"])
        self.interaction_hint.setObjectName("mutedLabel")
        self.interaction_hint.setWordWrap(True)
        self.interaction_hint.setAccessibleName("캘린더 조작 안내")
        self.interaction_hint.hide()
        left.addWidget(self.interaction_hint)

        self.view_stack = QStackedWidget()
        self.canvas = self._build_canvas()
        self.view_stack.addWidget(self.canvas)
        self.month_page = self._build_month_page()
        self.view_stack.addWidget(self.month_page)
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("scheduleAgendaList")
        self.list_widget.setAccessibleName("다가오는 일정 목록")
        self.list_widget.setToolTip("일정을 더블클릭하면 편집합니다.")
        self.list_widget.itemDoubleClicked.connect(self._open_list_item)
        self.view_stack.addWidget(self.list_widget)
        left.addWidget(self.view_stack, 1)
        self.move_status = QFrame()
        self.move_status.setObjectName("calendarMoveStatus")
        move_layout = QHBoxLayout(self.move_status)
        move_layout.setContentsMargins(12, 4, 6, 4)
        self.move_status_label = QLabel("일정을 이동했습니다.")
        move_layout.addWidget(self.move_status_label)
        move_layout.addStretch()
        self.undo_move_button = _button("이동 취소", "마지막 일정 이동 취소")
        move_layout.addWidget(self.undo_move_button)
        self.move_status.hide()
        left.addWidget(self.move_status)
        self.root_layout.addWidget(self.calendar_body, 1)

        self.drawer_frame = QFrame()
        self.drawer_frame.setObjectName("scheduleDrawer")
        self.drawer_frame.setMinimumWidth(0)
        self.drawer_frame.setMaximumWidth(400)
        drawer_layout = QVBoxLayout(self.drawer_frame)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        self.drawer_stack = QStackedWidget()
        self.drawer_stack.setMinimumWidth(0)
        self.drawer_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.side_tabs = self.drawer_stack
        self.quick_card = CalendarQuickEditor(self.store)
        self.title_edit = self.quick_card.title_edit
        self.content_edit = self.quick_card.content_edit
        self.datetime_input = self.quick_card.datetime_input
        self.create_button = self.quick_card.save_button
        self.schedule_editor = ScheduleEditor(self.store)
        self.schedule_editor.setMinimumWidth(0)
        self.schedule_editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.drawer_stack.addWidget(self.schedule_editor)
        quick_page = QWidget()
        quick_layout = QVBoxLayout(quick_page)
        quick_header = QHBoxLayout()
        quick_title = QLabel("빠른 메모")
        quick_title.setObjectName("sectionTitle")
        quick_header.addWidget(quick_title)
        quick_header.addStretch()
        self.quick_close_button = _button("닫기", "빠른 메모 닫기")
        quick_header.addWidget(self.quick_close_button)
        quick_layout.addLayout(quick_header)
        quick_layout.addWidget(self.quick_card)
        self.drawer_stack.addWidget(quick_page)
        self.side_scroll = QScrollArea()
        self.side_scroll.setObjectName("scheduleSideScroll")
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setMinimumWidth(0)
        self.side_scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.side_scroll.setWidget(self.drawer_stack)
        drawer_layout.addWidget(self.side_scroll)
        self.root_layout.addWidget(self.drawer_frame)
        self.drawer_frame.hide()

        # 일정 입력의 기본 경로.  클릭·드래그한 자리 옆에 떠서 제목·시간·분류만
        # 묻고, 더 필요하면 위 서랍의 전체 편집기로 넘긴다.
        # 캘린더 본문이 아니라 패널 전체를 부모로 삼는다.  본문만 부모로 두면
        # 창을 좁혔을 때 본문 폭이 팝오버보다 작아지면서 오른쪽이 잘렸다.
        self.schedule_popover = SchedulePopover(self.store, self)
        self.schedule_popover.saved.connect(self._popover_saved)
        self.schedule_popover.deleted.connect(self._popover_deleted)
        self.schedule_popover.full_edit_requested.connect(self._open_full_editor)
        self.schedule_popover.closed.connect(self._hide_popover)

        self.previous_button.clicked.connect(lambda: self._move(-1))
        self.next_button.clicked.connect(lambda: self._move(1))
        self.today_button.clicked.connect(self._today)
        self.new_schedule_button.clicked.connect(lambda: self._new_full_item("event"))
        self.new_task_button.clicked.connect(lambda: self._new_full_item("task"))
        self.undo_move_button.clicked.connect(self._undo_last_move)
        self.quick_card.note_saved.connect(self._quick_saved)
        self.schedule_editor.saved.connect(self._schedule_saved)
        self.schedule_editor.deleted.connect(self._schedule_deleted)
        self.schedule_editor.close_requested.connect(self._close_drawer)
        self.quick_close_button.clicked.connect(self._close_drawer)
        self.quick_memo_button.clicked.connect(self._open_quick_memo)
        self.header_quick_memo_button.clicked.connect(self._open_quick_memo)
        self.nav_today_button.clicked.connect(lambda: (self._set_mode("day"), self._today()))
        self.nav_week_button.clicked.connect(lambda: self._set_mode("week"))
        self.month_calendar.dateSelectionChanged.connect(self._month_selection_changed)
        self.month_calendar.scheduleActivated.connect(self._open_schedule)
        self.month_calendar.dateActivated.connect(self._new_schedule_on_date)
        self.month_agenda.itemDoubleClicked.connect(self._open_list_item)
        self._set_mode(self.mode, refresh=False, persist=False)

    def _build_canvas(self) -> CalendarCanvas:
        canvas = CalendarCanvas()
        canvas.setToolTip(INTERACTION_HINTS["day"])
        canvas.installEventFilter(self)
        canvas.view.installEventFilter(self)
        canvas.rangeSelected.connect(self._canvas_range)
        canvas.scheduleClicked.connect(self._open_schedule)
        canvas.scheduleActivated.connect(self._activate_schedule)
        canvas.scheduleMoved.connect(self._canvas_changed)
        canvas.scheduleResized.connect(self._canvas_changed)
        return canvas

    def _build_month_page(self) -> QWidget:
        page = QWidget()
        layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.month_calendar = CalendarMonthView()
        self.month_agenda_title = QLabel("선택 날짜 일정")
        self.month_agenda_title.setObjectName("sectionTitle")
        self.month_agenda = QListWidget()
        self.month_agenda.setObjectName("scheduleAgendaList")
        self.month_agenda.setMinimumHeight(180)
        layout.addWidget(self.month_calendar, 1)
        layout.addWidget(self.month_agenda_title)
        layout.addWidget(self.month_agenda)
        self.month_agenda_title.hide()
        self.month_agenda.hide()
        return page

    def eventFilter(self, watched, event):
        canvas = getattr(self, "canvas", None)
        if canvas is None or event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)
        if watched not in (canvas, canvas.view):
            return super().eventFilter(watched, event)
        control = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if event.key() == Qt.Key.Key_Home:
            self._today()
            return True
        if event.key() == Qt.Key.Key_PageUp:
            self._move(-1)
            return True
        if event.key() == Qt.Key.Key_PageDown:
            self._move(1)
            return True
        if control and event.key() == Qt.Key.Key_Z:
            # 직접 조작에는 되돌리기가 반드시 함께 간다.
            self._undo_last_move()
            return True
        if control and event.key() == Qt.Key.Key_N:
            self._new_schedule(self._default_new_start())
            return True
        return super().eventFilter(watched, event)

    def _set_mode(self, mode: str, refresh: bool = True, persist: bool = True) -> None:
        self.mode = mode if mode in {"day", "week", "month", "list"} else "week"
        for name, button in self.mode_buttons.items():
            button.setChecked(name == self.mode)
        self.view_stack.setCurrentIndex(0 if self.mode in {"day", "week"} else 1 if self.mode == "month" else 2)
        # Month and list views have no time slots, so the hint follows the view.
        hint = INTERACTION_HINTS.get(self.mode, INTERACTION_HINTS["day"])
        self.interaction_hint.setText(hint)
        self.canvas.setToolTip(hint)
        self.month_calendar.setToolTip(hint)
        self._hide_popover()
        if persist:
            self.store.set_setting("calendar_view_mode", self.mode)
            self._mode_was_saved = True
        self._sync_nav_range()
        if refresh:
            self.refresh()
        # 탭을 고른 것은 "지금을 보여 달라"는 뜻이다.  스크롤을 내렸던 자리에
        # 그대로 두지 않고 현재 시각으로 다시 맞춘다.
        if self.mode in {"day", "week"}:
            self.canvas.scroll_to_now(force=True)

    def _sync_nav_range(self) -> None:
        """Light the button for the range on screen, so a click leaves a mark."""
        if not hasattr(self, "nav_today_button"):
            return
        today = date.today()
        start, end = self._range()
        self.nav_today_button.setChecked(self.mode == "day" and self.anchor == today)
        self.nav_week_button.setChecked(self.mode == "week" and start <= today < end)

    def _move(self, amount: int) -> None:
        self._hide_popover()
        if self.mode == "month":
            month_index = self.anchor.year * 12 + self.anchor.month - 1 + amount
            year, month = divmod(month_index, 12)
            self.anchor = date(year, month + 1, 1)
        else:
            self.anchor += timedelta(days=amount * (1 if self.mode == "day" else 7 if self.mode == "week" else 30))
        self.refresh()

    def _today(self) -> None:
        self._hide_popover()
        self.anchor = datetime.now().date()
        self.month_calendar.setSelectedDate(QDate.currentDate())
        self.refresh()
        if self.mode in {"day", "week"}:
            self.canvas.scroll_to_now(force=True)

    def _range(self):
        if self.mode == "week":
            start = self.anchor - timedelta(days=self.anchor.weekday())
            return start, start + timedelta(days=7)
        if self.mode == "month":
            start = self.anchor.replace(day=1)
            next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            return start, next_month
        if self.mode == "list":
            return self.anchor, self.anchor + timedelta(days=60)
        return self.anchor, self.anchor + timedelta(days=1)

    # The month view stacks the year over the month, the month three times the
    # year, so the month reads first and the year stays available underneath it.
    MONTH_LABEL_RATIO = 3
    MONTH_LABEL_BAND = 50
    MONTH_LABEL_LEADING = 80

    def _stacked_period_html(self, year: int, month: int, small: int) -> str:
        return (
            f'<div style="line-height:{self.MONTH_LABEL_LEADING}%">'
            f'<span style="font-size:{small}px; font-weight:500">{year}년</span><br>'
            f'<span style="font-size:{small * self.MONTH_LABEL_RATIO}px; font-weight:700">{month}월</span>'
            f'</div>'
        )

    def _set_stacked_period(self, year: int, month: int) -> None:
        self.period_label.setText(
            self._stacked_period_html(year, month, self._stacked_year_size(year, month))
        )

    def _stacked_year_size(self, year: int, month: int) -> int:
        """Biggest pair that still fits the header band — measured, not guessed.

        Font metrics differ by machine, so a size computed from the band height
        alone overflowed on this one.  Ask the label how tall it would actually be.
        """
        if self._stacked_size:
            return self._stacked_size
        probe = QLabel(self)
        probe.setObjectName("pageTitle")
        probe.setVisible(False)
        chosen = 7
        for candidate in range(12, 6, -1):
            probe.setText(self._stacked_period_html(year, month, candidate))
            if probe.sizeHint().height() <= self.MONTH_LABEL_BAND:
                chosen = candidate
                break
        probe.deleteLater()
        self._stacked_size = chosen
        return chosen

    def refresh(self) -> None:
        self._sync_nav_range()
        self.month_calendar.set_dim_past(
            str(self.store.setting("calendar_dim_past", "true")).lower() == "true"
        )
        start, end = self._range()
        if self.mode == "week":
            last = end - timedelta(days=1)
            self.period_label.setText(f"{start.month}/{start.day} – {last.month}/{last.day}")
        elif self.mode == "month":
            self._set_stacked_period(start.year, start.month)
        elif self.mode == "list":
            self.period_label.setText("다가오는 60일")
        else:
            self.period_label.setText(f"{start.month}월 {start.day}일")
        self._refresh_deadline_strip(start, end)
        if self.mode in {"day", "week"}:
            self._refresh_timeline(start, end)
        elif self.mode == "month":
            self._refresh_month_formats(start, end)
            self._refresh_month_agenda()
        else:
            self._fill_agenda(self.list_widget, start, end)

    def _refresh_timeline(self, start: date, end: date) -> None:
        items = self._filtered_schedule_items(start, end)
        self.canvas.render_range(start, end, items)

    def _refresh_month_agenda(self) -> None:
        selected = self.month_calendar.selectedDate().toPyDate()
        self.month_agenda_title.setText(f"{selected:%m월 %d일} 일정")
        self._fill_agenda(self.month_agenda, selected, selected + timedelta(days=1))

    def _refresh_month_formats(self, start: date, end: date) -> None:
        grid_start = start - timedelta(days=start.weekday())
        grid_end = grid_start + timedelta(days=42)
        items = self._filtered_schedule_items(grid_start, grid_end)
        self.month_calendar.set_deadlines(self._deadlines_by_day(grid_start, grid_end))
        self.month_calendar.set_month(start.year, start.month, items)

    def _jump_to_date(self, value: QDate) -> None:
        """Move the current view to the picked day, whatever view that is."""
        self._hide_popover()
        self.anchor = value.toPyDate()
        self.month_calendar.setSelectedDate(value)
        self.refresh()

    def _deadlines_by_day(self, start: date, end: date) -> dict:
        """D-Day belongs on the calendar too, not only in the memo list."""
        grouped: dict = {}
        if not self.calendar_filter_checks["dday"].isChecked():
            return grouped
        try:
            rows = self.store.deadline_notes()
        except Exception:
            return grouped
        for row in rows:
            moment = parse_deadline(str(row["d_day_at"] or ""))
            if (
                moment is None
                or deadline_urgency(row) == "done"
                or not (start <= moment.date() < end)
            ):
                continue
            grouped.setdefault(moment.date(), []).append(
                (deadline_chip_text(row), deadline_title(row))
            )
        return grouped

    def _fill_agenda(self, widget: QListWidget, start: date, end: date) -> None:
        widget.clear()
        items = self._filtered_schedule_items(start, end)
        entries: list[tuple[datetime, QListWidgetItem]] = []
        for event in items:
            begin = datetime.strptime(event["display_start_at"], DATETIME_FMT)
            marker = "✓" if event["status"] == "completed" else "□" if event["item_type"] == "task" else "●"
            item = QListWidgetItem(f"{begin:%m/%d %H:%M}  {marker}  {event['title']}")
            item.setData(Qt.ItemDataRole.UserRole, (int(event["id"]), str(event["occurrence_at"])))
            item.setToolTip(str(event["details"]))
            item.setForeground(QColor("#64748b" if event["status"] == "completed" else "#0f172a"))
            entries.append((begin, item))
        if self.calendar_filter_checks["dday"].isChecked():
            for row in self._deadline_rows(start, end):
                moment = parse_deadline(str(row["d_day_at"] or ""))
                if moment is None:
                    continue
                item = QListWidgetItem(
                    f"{moment:%m/%d %H:%M}  {deadline_chip_text(row)}  {deadline_title(row)}"
                )
                item.setData(Qt.ItemDataRole.UserRole, ("deadline", int(row["id"])))
                item.setForeground(QColor("#b42318"))
                item.setToolTip(f"D-Day 목표 · {moment:%Y-%m-%d %H:%M}")
                entries.append((moment, item))
        for _moment, item in sorted(entries, key=lambda pair: pair[0]):
            widget.addItem(item)
        if not entries:
            empty = QListWidgetItem("아직 일정이 없습니다. 위 ‘＋ 새 일정’으로 만들어 보세요.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            widget.addItem(empty)

    def _filtered_schedule_items(self, start: date, end: date) -> list[dict]:
        show_events = self.calendar_filter_checks["events"].isChecked()
        show_tasks = self.calendar_filter_checks["tasks"].isChecked()
        show_dday = self.calendar_filter_checks["dday"].isChecked()
        result = []
        for item in self.store.schedules.items_for_range(_day_key(start), _day_key(end)):
            item_type = str(item.get("item_type") or "event")
            if item_type == "event" and show_events:
                result.append(item)
            elif item_type == "task" and (
                show_tasks or (show_dday and bool(item.get("count_as_dday")))
            ):
                result.append(item)
        return result

    def _deadline_rows(self, start: date, end: date) -> list:
        try:
            rows = self.store.deadline_notes()
        except Exception:
            return []
        result = []
        for row in rows:
            moment = parse_deadline(str(row["d_day_at"] or ""))
            if (
                moment is not None
                and deadline_urgency(row) != "done"
                and start <= moment.date() < end
            ):
                result.append(row)
        return result

    def _refresh_deadline_strip(self, start: date, end: date) -> None:
        if not self.calendar_filter_checks["dday"].isChecked():
            self.calendar_deadline_strip.hide()
            return
        rows = self._deadline_rows(start, end)
        if not rows:
            self.calendar_deadline_strip.hide()
            return
        labels = []
        for row in rows[:3]:
            moment = parse_deadline(str(row["d_day_at"] or ""))
            if moment is not None:
                labels.append(
                    f"{deadline_chip_text(row)}  {deadline_title(row)}  {moment:%m/%d %H:%M}"
                )
        if len(rows) > 3:
            labels.append(f"외 {len(rows) - 3}건")
        self.calendar_deadline_strip.setText("D-Day · " + "   |   ".join(labels))
        self.calendar_deadline_strip.show()

    def _calendar_filter_value(self, key: str, default: bool) -> bool:
        return str(
            self.store.setting(
                f"calendar_filter_{key}", "true" if default else "false"
            )
        ).lower() == "true"

    def _calendar_filter_changed(self, *_args) -> None:
        if not hasattr(self, "calendar_filter_checks"):
            return
        for key, check in self.calendar_filter_checks.items():
            self.store.set_setting(
                f"calendar_filter_{key}", "true" if check.isChecked() else "false"
            )
        self.refresh()

    def _show_only_dday(self) -> None:
        for key, check in self.calendar_filter_checks.items():
            check.blockSignals(True)
            check.setChecked(key == "dday")
            check.blockSignals(False)
        self._calendar_filter_changed()

    def _canvas_range(self, start: datetime, end: datetime) -> None:
        """빈 자리를 끌어 만든 범위.  그 자리에 팝오버를 연다."""
        self.quick_card.select_slot(start)
        self._open_popover_new(start, end)

    def _canvas_changed(
        self, item_id: int, occurrence_at: str,
        old_start: datetime, old_end: datetime, new_start: datetime, new_end: datetime,
    ) -> None:
        """옮기거나 늘인 결과를 저장한다.  한 걸음은 되돌릴 수 있게 기억해 둔다."""
        item = self.store.schedules.item(item_id)
        if item is None:
            return
        if item["source_reminder_id"] is not None:
            QMessageBox.information(
                self, "연결 일정",
                "메모 알림에서 만들어진 일정은 메모의 알림 설정에서 변경해 주세요.",
            )
            self.refresh()
            return
        rule = str(item["recurrence_rule"] or "{}")
        if '"frequency": "none"' not in rule and occurrence_at:
            self.store.schedules.move_occurrence(
                item_id, occurrence_at,
                new_start.strftime(DATETIME_FMT), new_end.strftime(DATETIME_FMT),
            )
            self._last_move = ("exception", item_id, occurrence_at)
        else:
            values = dict(item)
            values.update({
                "id": item_id,
                "start_at": new_start.strftime(DATETIME_FMT),
                "end_at": new_end.strftime(DATETIME_FMT),
                "reminders": self.store.schedules.notifications(item_id),
            })
            self.store.schedules.save_item(values)
            self._last_move = (
                "master", item_id,
                old_start.strftime(DATETIME_FMT), old_end.strftime(DATETIME_FMT),
            )
        self.undo_move_button.setEnabled(True)
        self.undo_move_button.show()
        self.move_status_label.setText(
            f"{new_start:%H:%M} – {new_end:%H:%M} 으로 옮겼습니다.  Ctrl+Z 로 되돌립니다."
        )
        self.move_status.show()
        QTimer.singleShot(5000, self.move_status.hide)
        self.refresh()
        self.schedule_changed.emit()

    def _undo_last_move(self) -> None:
        if not self._last_move:
            return
        kind, item_id, *values = self._last_move
        if kind == "deleted":
            self.store.schedules.restore_item(item_id)
        elif kind == "exception":
            self.store.schedules.clear_occurrence_exception(item_id, values[0])
        else:
            item = self.store.schedules.item(item_id)
            if item is not None:
                data = dict(item)
                data.update({
                    "id": item_id, "start_at": values[0], "end_at": values[1],
                    "reminders": self.store.schedules.notifications(item_id),
                })
                self.store.schedules.save_item(data)
        self._last_move = None
        self.undo_move_button.setEnabled(False)
        self.move_status.hide()
        self.refresh()
        self.schedule_changed.emit()

    def _activate_schedule(self, item_id: int, occurrence_at: str) -> None:
        """더블클릭·Enter — 메모에 물린 일정은 메모를 연다."""
        schedule = self.store.schedules.item(item_id)
        if schedule and schedule["note_id"]:
            self.note_open_requested.emit(int(schedule["note_id"]))
        else:
            self._open_schedule(item_id, occurrence_at)

    def _new_schedule_on_date(self, value: QDate) -> None:
        """Month cells have no clock, so start the day at 09:00."""
        day = value.toPyDate()
        self._new_schedule(datetime.combine(day, time(hour=9)))

    def _default_new_start(self) -> datetime:
        """Honour the date the user picked instead of always using today."""
        if self.mode == "month":
            picked = self.month_calendar.selectedDate().toPyDate()
        else:
            picked = self.anchor
        if picked == datetime.now().date():
            return datetime.now().replace(second=0, microsecond=0)
        return datetime.combine(picked, time(hour=9))

    def _new_schedule(self, start: datetime | None = None) -> None:
        start = (start or self._default_new_start()).replace(second=0, microsecond=0)
        self._open_popover_new(start, start + timedelta(hours=1))

    def _new_full_item(self, item_type: str) -> None:
        """머리말의 두 진입점은 정해진 종류의 전체 편집기를 연다."""
        self._hide_popover()
        start = self._default_new_start().replace(second=0, microsecond=0)
        self.schedule_editor.new_item(
            start,
            start + timedelta(hours=1),
            item_type="task" if item_type == "task" else "event",
        )
        self._open_drawer(0)

    def _open_schedule(self, item_id: int, occurrence_at: str | None = None) -> None:
        """Edit where the item sits.  Mirrors keep going to the full editor."""
        self._close_drawer()
        if not self.schedule_popover.open_item(item_id, occurrence_at):
            self.schedule_editor.load_item(item_id, occurrence_at)
            self._open_drawer(0)
            return
        moment = self._item_moment(item_id, occurrence_at)
        self._popover_slot = (moment, None)
        self.schedule_popover.place_near(
            self._anchor_rect(moment), bounds=self._visible_bounds()
        )
        self.schedule_popover.show()
        self.schedule_popover.raise_()

    # ------------------------------------------------------------- 팝오버 --
    def _open_popover_new(self, start: datetime, end: datetime) -> None:
        self._close_drawer()
        self.schedule_popover.open_new(start, end)
        self._popover_slot = (start, end)
        self.schedule_popover.place_near(
            self._anchor_rect(start, end), bounds=self._visible_bounds()
        )
        self.schedule_popover.show()
        self.schedule_popover.raise_()

    def _visible_bounds(self) -> QRect:
        """패널에서 지금 실제로 보이는 사각형.

        캘린더는 제 최소 폭(시간표 620px + 여백)을 지키느라 창보다 넓어질 수
        있고, 그때 탭이 오른쪽을 잘라 낸다.  팝오버를 그 잘린 자리에 세우면
        화면에서 사라지므로, 부모 폭이 아니라 보이는 영역을 기준으로 삼는다.
        """
        window = self.window()
        if window is None or window is self:
            return self.rect()
        # 창의 사각형을 패널 좌표로 옮겨 겹치는 부분만 남긴다.  visibleRegion()은
        # 아직 그려지지 않은 상태에서 잘린 범위를 알려 주지 않는다.
        area = QRect(self.mapFrom(window, QPoint(0, 0)), window.size()).intersected(self.rect())
        if area.width() < 200 or area.height() < 160:
            return self.rect()
        return area

    def _hide_popover(self) -> None:
        popover = getattr(self, "schedule_popover", None)
        if popover is not None:
            popover.hide()

    def _item_moment(self, item_id: int, occurrence_at: str | None) -> datetime | None:
        if occurrence_at:
            try:
                return datetime.strptime(str(occurrence_at), DATETIME_FMT)
            except ValueError:
                pass
        item = self.store.schedules.item(item_id)
        if item is None:
            return None
        try:
            return datetime.strptime(str(item["start_at"]), DATETIME_FMT)
        except ValueError:
            return None

    def _anchor_rect(self, start: datetime | None, end: datetime | None = None) -> QRect:
        """팝오버를 그 시간 칸 옆에 세운다."""
        fallback = QRect(max(0, self.width() // 2 - 40), 120, 80, 60)
        if start is None or self.mode not in {"day", "week"}:
            return fallback
        rect = self.canvas.rect_for_range(start, end or start + timedelta(hours=1))
        if rect is None:
            return fallback
        origin = self.canvas.mapTo(self, rect.topLeft())
        return QRect(origin, rect.size())

    def _popover_saved(self, _item_id: int) -> None:
        self.refresh()
        self._show_status("일정을 저장했습니다.")
        self.schedule_changed.emit()

    def _popover_deleted(self, item_id: int) -> None:
        # 삭제도 직접 조작이다.  Ctrl+Z 한 번으로 돌아와야 한다.
        self._last_move = ("deleted", item_id)
        self.refresh()
        self.move_status_label.setText("일정을 삭제했습니다.  Ctrl+Z 로 되돌립니다.")
        self.undo_move_button.setEnabled(True)
        self.undo_move_button.show()
        self.move_status.show()
        QTimer.singleShot(5000, self.move_status.hide)
        self.schedule_changed.emit()

    def _open_full_editor(self, values: dict) -> None:
        """팝오버에 적은 것을 잃지 않고 전체 편집기로 넘긴다."""
        occurrence_at = self.schedule_popover.occurrence_at
        self.schedule_popover.hide()
        item_id = values.get("id")
        if item_id:
            self.schedule_editor.load_item(int(item_id), occurrence_at)
        else:
            self.schedule_editor.apply_draft(values)
        self._open_drawer(0)

    def _open_list_item(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        if value:
            item_id, occurrence_at = value
            if item_id == "deadline":
                self.note_open_requested.emit(int(occurrence_at))
            else:
                self._open_schedule(int(item_id), str(occurrence_at))

    def _month_selection_changed(self) -> None:
        picked = self.month_calendar.selectedDate()
        self.anchor = picked.toPyDate()
        self._refresh_month_agenda()
        # Clicking a day while a draft is open used to change nothing, so the
        # editor kept the date it opened with.  A saved item is left alone.
        # 새 일정은 이제 팝오버로 열리므로 둘 다 따라가게 한다.
        if self.schedule_popover.move_to_date(picked):
            # 창도 새 날짜 칸 옆으로 따라간다.
            self._popover_slot = self.schedule_popover.current_range()
            self.schedule_popover.place_near(
                self._anchor_rect(*self._popover_slot), bounds=self._visible_bounds()
            )
        elif self._drawer_open and self.drawer_stack.currentIndex() == 0:
            self.schedule_editor.move_to_date(picked)

    def _quick_saved(self, note_id: int) -> None:
        self.note_created.emit(note_id)
        self._close_drawer()
        self.refresh()

    def _schedule_saved(self, _item_id: int) -> None:
        self.refresh()
        self._close_drawer()
        self._show_status("일정을 저장했습니다.")
        self.schedule_changed.emit()

    def _schedule_deleted(self, _item_id: int) -> None:
        self.refresh()
        self._close_drawer()
        self._show_status("일정을 삭제했습니다.")
        self.schedule_changed.emit()

    def _create_note(self) -> None:
        self.quick_card.save()

    def _open_quick_memo(self) -> None:
        self._open_drawer(1)
        self.quick_card.title_edit.setFocus()

    def _open_drawer(self, page: int = 0) -> None:
        self.drawer_stack.setCurrentIndex(page)
        self._drawer_open = True
        self._sync_drawer_placement()
        self.drawer_frame.show()
        if self._responsive_width < 900:
            self.calendar_body.hide()
            self.drawer_frame.setMinimumWidth(0)
            self.drawer_frame.setMaximumWidth(16_777_215)
        else:
            self.drawer_frame.setMinimumWidth(360)
            self.drawer_frame.setMaximumWidth(400)

    def _close_drawer(self) -> None:
        self._drawer_open = False
        self.drawer_frame.hide()
        self.calendar_body.show()
        self.drawer_frame.setMinimumWidth(0)
        self.drawer_frame.setMaximumWidth(400)

    def _show_status(self, message: str) -> None:
        self.move_status_label.setText(message)
        self.undo_move_button.hide()
        self.move_status.show()
        QTimer.singleShot(3500, self.move_status.hide)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.schedule_popover.isVisible():
            self.schedule_popover.dismiss()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._drawer_open:
            if self.drawer_stack.currentIndex() == 0:
                self.schedule_editor.request_close()
            else:
                self._close_drawer()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        """창을 좁히면 팝오버가 붙어 있던 칸도 자리를 옮긴다.

        칸의 화면 좌표를 다시 재서 그 옆에 세우지 않으면, 폭만 줄어든 채 옛
        좌표에 남아 오른쪽이 잘린다.
        """
        super().resizeEvent(event)
        popover = getattr(self, "schedule_popover", None)
        if popover is None or not popover.isVisible():
            return
        start, end = getattr(self, "_popover_slot", (None, None))
        popover.place_near(self._anchor_rect(start, end), bounds=self._visible_bounds())

    def update_responsive_layout(self, width: int) -> None:
        self._responsive_width = width
        narrow = width < 900
        self.root_layout.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        show_navigation = width >= 1180 and not narrow
        self.navigation.setVisible(show_navigation)
        # The sidebar carries 빠른 메모; when it hides, the header has to.
        self.header_quick_memo_button.setVisible(not show_navigation)
        self.fullscreen_button.setVisible(width >= 1180)
        self._sync_drawer_placement()
        if narrow:
            self.drawer_frame.setMinimumWidth(0)
            self.drawer_frame.setMaximumWidth(16_777_215)
            self.side_scroll.setMinimumHeight(520)
            self.side_scroll.setMaximumHeight(16_777_215)
            self.calendar_body.setVisible(not self._drawer_open)
        else:
            self.drawer_frame.setMinimumWidth(360 if self._drawer_open else 0)
            self.drawer_frame.setMaximumWidth(400)
            self.side_scroll.setMinimumHeight(0)
            self.side_scroll.setMaximumHeight(16_777_215)
            self.calendar_body.show()
        if width < 900 and not self._mode_was_saved:
            self._set_mode("day")
        if width < 900 and self.mode == "week":
            self.canvas.setMinimumWidth(620)

    def _sync_drawer_placement(self) -> None:
        medium_overlay = 900 <= self._responsive_width < 1180
        in_layout = self.root_layout.indexOf(self.drawer_frame) >= 0
        if medium_overlay:
            if in_layout:
                self.root_layout.removeWidget(self.drawer_frame)
                self.drawer_frame.setParent(self)
            self.drawer_frame.setGeometry(
                max(0, self.width() - 400), 14, 386, max(320, self.height() - 28)
            )
            self.drawer_frame.raise_()
        elif not in_layout:
            self.drawer_frame.setParent(self)
            self.root_layout.addWidget(self.drawer_frame)

    def shutdown(self) -> None:
        """Release item-owned Python payloads before the backing store closes."""
        self._hide_popover()
        self.canvas.clearContents()
        self.month_calendar.clearContents()
        self.list_widget.clear()
        self.month_agenda.clear()


def _button(text: str, accessible_name: str) -> QPushButton:
    button = QPushButton(text)
    button.setMinimumHeight(40)
    button.setAccessibleName(accessible_name)
    polish_button(button)
    return button


def _day_key(value: date) -> str:
    return datetime.combine(value, time.min).strftime(DATETIME_FMT)
