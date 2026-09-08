"""클릭한 자리에서 끝내는 일정 입력 팝오버.

고정 사이드 패널은 화면의 4분의 1을 상시 차지하면서, 정작 "겹치나?"를 보려고
연 캘린더를 가렸다.  이 팝오버는 드래그한 자리 옆에 떠서 제목·시간·분류 셋만
묻고, 알림·반복·메모·D-Day는 ＋로 필요할 때만 펼친다.  더 많은 설정이 필요하면
"전체 편집 ↗"으로 기존 편집기에 그대로 넘긴다.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from PyQt6.QtCore import QDate, QRect, QTime, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from .categories import CATEGORIES, CATEGORY_COLORS, category_name
from .datetime_input import CompactDateEdit, CompactTimeEdit
from . import ko_schedule_parser
from .schedule_recurrence import DATETIME_FMT, normalize_rule


# 30분·1시간·2시간이 실제로 쓰이는 길이다.  종일은 시각을 지우는 쪽이라 끝에 둔다.
DURATION_PRESETS = (("30분", 30), ("1시간", 60), ("1시간 30분", 90), ("2시간", 120), ("종일", 0))
REPEAT_CHOICES = (("매일", "daily"), ("매주", "weekly"), ("매월", "monthly"), ("매년", "yearly"))
REPEAT_LABELS = {key: label for label, key in REPEAT_CHOICES}
POPOVER_WIDTH = 336
# 창을 좁혀도 이 아래로는 줄이지 않는다.  분류 칩 다섯 개와 저장 줄이 들어가는
# 최소 폭이다.  자리가 이보다 좁으면 폭을 줄이는 대신 왼쪽으로 붙여 세운다.
POPOVER_MIN_WIDTH = 300
POPOVER_MAX_WIDTH = POPOVER_WIDTH + 72


class SchedulePopover(QFrame):
    saved = pyqtSignal(int)
    deleted = pyqtSignal(int)
    full_edit_requested = pyqtSignal(dict)
    closed = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setObjectName("schedulePopover")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # 폭을 못 박아 두면 글꼴이 조금만 넓어져도 오른쪽이 잘린다.  기본은
        # 336px 그대로 두되, 한 줄이 넘칠 때만 그만큼 넓어지게 여유를 준다.
        self.setMinimumWidth(POPOVER_WIDTH)
        self.setMaximumWidth(POPOVER_MAX_WIDTH)
        self.store = store
        self.item_id: int | None = None
        self.occurrence_at: str | None = None
        self._base: dict = {}
        self._category = CATEGORIES[0][1]
        self._all_day = False
        self._start = datetime.now().replace(second=0, microsecond=0)
        self._end = self._start + timedelta(hours=1)
        # 마지막으로 세운 자리.  내용이 늘어나 높이를 다시 잴 때 같은 자리에 다시 세운다.
        self._anchor: QRect | None = None
        self._anchor_margin = 12
        # 부모가 아니라 '실제로 보이는 자리'.  캘린더는 창보다 넓어질 수 있어서
        # 부모 폭만 보고 세우면 화면 밖에 놓인다.
        self._bounds: QRect | None = None
        # 사람이 손으로 고친 항목.  파서는 여기 든 것을 다시 건드리지 않는다.
        self._touched: set[str] = set()
        # 파서가 채운 항목.  표현을 지우면 여기 든 것만 되돌린다.
        self._parser_fields: set[str] = set()
        self._parsed = None
        self._origin: tuple[datetime, datetime] | None = None
        self._loading = False
        self._build_ui()
        self.hide()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.heading = QLabel("새 일정")
        self.heading.setObjectName("popoverHeading")
        header.addWidget(self.heading)
        self.range_label = QLabel()
        self.range_label.setObjectName("popoverRange")
        header.addWidget(self.range_label)
        header.addStretch()
        # 조작법을 문장으로 설명하는 대신, 닫는 키를 그 자리에 눌러 볼 수 있게 둔다.
        self.escape_button = QPushButton("Esc")
        self.escape_button.setObjectName("popoverEscButton")
        self.escape_button.setAccessibleName("일정 입력 닫기")
        header.addWidget(self.escape_button)
        root.addLayout(header)

        # 본문만 스크롤한다.  항목을 다 펼쳐 캘린더보다 길어져도 제목줄과
        # 저장 버튼은 늘 제자리에 남는다.
        self.body = QWidget()
        self.body.setAutoFillBackground(False)
        body_root = QVBoxLayout(self.body)
        body_root.setContentsMargins(0, 0, 0, 0)
        body_root.setSpacing(10)
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidget(self.body)
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_scroll.viewport().setAutoFillBackground(False)
        shell, root = root, body_root
        shell.addWidget(self.body_scroll)

        # 편집으로 열렸을 때 무엇을 고치는 중인지 한 줄로 못 박는다.  이 줄이
        # 없으면 새 일정을 만드는 화면으로 착각해 기존 일정을 덮어쓰게 된다.
        self.editing_label = QLabel()
        self.editing_label.setObjectName("popoverHint")
        self.editing_label.setWordWrap(True)
        self.editing_label.hide()
        root.addWidget(self.editing_label)

        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("popoverTitleEdit")
        self.title_edit.setPlaceholderText("제목 추가")
        self.title_edit.setAccessibleName("일정 제목")
        root.addWidget(self.title_edit)

        # 무엇을 날짜로 읽었는지 적는 줄.  파서가 틀렸을 때 저장 전에 보인다.
        self.parse_label = QLabel()
        self.parse_label.setObjectName("popoverParse")
        self.parse_label.setWordWrap(True)
        self.parse_label.hide()
        root.addWidget(self.parse_label)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.time_chip = QPushButton()
        self.time_chip.setObjectName("popoverTimeChip")
        self.time_chip.setCheckable(True)
        self.time_chip.setAccessibleName("시간 편집")
        chips.addWidget(self.time_chip)
        self.duration_chip = QPushButton("1시간")
        self.duration_chip.setObjectName("popoverDurationChip")
        self.duration_chip.setAccessibleName("길이 선택")
        chips.addWidget(self.duration_chip)
        chips.addStretch()
        root.addLayout(chips)

        # 날짜·시작·종료를 한 줄에 세우면 팝오버 폭(336px)을 훌쩍 넘겨 오른쪽이
        # 잘렸다.  날짜를 위로 올리고 시작–종료만 나란히 둔다.
        self.time_row = QWidget()
        time_layout = QVBoxLayout(self.time_row)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(6)
        self.date_edit = _flat_field(CompactDateEdit(), "popoverDateField", 156)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setAccessibleName("일정 날짜")
        date_row = QHBoxLayout()
        date_row.setSpacing(6)
        date_row.addWidget(self.date_edit)
        date_row.addStretch()
        time_layout.addLayout(date_row)
        span_row = QHBoxLayout()
        span_row.setSpacing(6)
        self.start_time_edit = _flat_field(CompactTimeEdit(), "popoverTimeField", 104)
        self.start_time_edit.setAccessibleName("시작 시각")
        self.end_time_edit = _flat_field(CompactTimeEdit(), "popoverTimeField", 104)
        self.end_time_edit.setAccessibleName("종료 시각")
        dash = QLabel("–")
        dash.setObjectName("popoverFieldLabel")
        span_row.addWidget(self.start_time_edit)
        span_row.addWidget(dash)
        span_row.addWidget(self.end_time_edit)
        span_row.addStretch()
        time_layout.addLayout(span_row)
        self.time_row.hide()
        root.addWidget(self.time_row)

        category_label = QLabel("분류")
        category_label.setObjectName("popoverFieldLabel")
        root.addWidget(category_label)
        category_row = QHBoxLayout()
        category_row.setSpacing(5)
        self.category_chips = {}
        for name, key in CATEGORIES:
            chip = QPushButton(name)
            chip.setObjectName("popoverCategoryChip")
            chip.setCheckable(True)
            chip.setAccessibleName(f"{name} 분류")
            chip.clicked.connect(lambda _checked=False, value=key: self._pick_category(value, manual=True))
            self.category_chips[key] = chip
            category_row.addWidget(chip)
        category_row.addStretch()
        root.addLayout(category_row)

        extras = QHBoxLayout()
        extras.setSpacing(4)
        self.reminder_chip = _add_chip("알림", "알림 추가")
        self.repeat_chip = _add_chip("반복", "반복 설정")
        self.memo_chip = _add_chip("메모", "메모 추가")
        self.dday_chip = _add_chip("D-Day", "D-Day로 함께 등록")
        for chip in (self.reminder_chip, self.repeat_chip, self.memo_chip, self.dday_chip):
            extras.addWidget(chip)
        extras.addStretch()
        root.addLayout(extras)

        self.reminder_edit = QLineEdit()
        self.reminder_edit.setPlaceholderText("10, 30 (분 전, 최대 5개)")
        self.reminder_edit.setAccessibleName("미리 알림")
        self.reminder_edit.hide()
        root.addWidget(self.reminder_edit)

        self.repeat_combo = QComboBox()
        for label, key in REPEAT_CHOICES:
            self.repeat_combo.addItem(label, key)
        self.repeat_combo.setAccessibleName("반복 주기")
        self.repeat_combo.hide()
        root.addWidget(self.repeat_combo)

        self.memo_edit = QTextEdit()
        self.memo_edit.setPlaceholderText("메모와 준비 사항")
        self.memo_edit.setMaximumHeight(64)
        self.memo_edit.setAccessibleName("일정 메모")
        self.memo_edit.hide()
        root.addWidget(self.memo_edit)

        self.dday_hint = QLabel("저장할 때 같은 제목의 D-Day 메모를 함께 만듭니다.")
        self.dday_hint.setObjectName("popoverHint")
        self.dday_hint.setWordWrap(True)
        self.dday_hint.hide()
        root.addWidget(self.dday_hint)

        divider = QFrame()
        divider.setObjectName("popoverDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        shell.addWidget(divider)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.full_edit_button = QPushButton("전체 편집 ↗")
        self.full_edit_button.setObjectName("popoverLinkButton")
        self.full_edit_button.setAccessibleName("전체 편집 열기")
        footer.addWidget(self.full_edit_button)
        self.delete_button = QPushButton("삭제")
        self.delete_button.setObjectName("popoverLinkButton")
        self.delete_button.setAccessibleName("일정 삭제")
        self.delete_button.hide()
        footer.addWidget(self.delete_button)
        footer.addStretch()
        enter_hint = QLabel("Enter")
        enter_hint.setObjectName("popoverKeyHint")
        footer.addWidget(enter_hint)
        self.save_button = QPushButton("저장")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setAccessibleName("일정 저장")
        footer.addWidget(self.save_button)
        shell.addLayout(footer)

        self.escape_button.clicked.connect(self.dismiss)
        self.save_button.clicked.connect(self.save)
        self.title_edit.returnPressed.connect(self.save)
        self.full_edit_button.clicked.connect(self._request_full_edit)
        self.delete_button.clicked.connect(self._delete)
        self.time_chip.toggled.connect(self._toggle_time_row)
        self.duration_chip.clicked.connect(self._pick_duration)
        self.reminder_chip.toggled.connect(self._toggle_extra(self.reminder_edit))
        self.repeat_chip.toggled.connect(self._toggle_extra(self.repeat_combo))
        self.memo_chip.toggled.connect(self._toggle_extra(self.memo_edit))
        self.dday_chip.toggled.connect(self._toggle_extra(self.dday_hint))
        self.date_edit.dateChanged.connect(self._time_edited)
        self.start_time_edit.timeChanged.connect(self._time_edited)
        self.end_time_edit.timeChanged.connect(self._time_edited)
        self.title_edit.textChanged.connect(self._title_changed)
        self.reminder_edit.textEdited.connect(lambda _text: self._touched.add("reminder"))
        self.repeat_combo.activated.connect(lambda _index: self._touched.add("repeat"))
        self.reminder_chip.clicked.connect(lambda _checked: self._touched.add("reminder"))
        self.repeat_chip.clicked.connect(lambda _checked: self._touched.add("repeat"))
        self._pick_category(self._category)

    # ------------------------------------------------------------- 열기/닫기 --
    def open_new(self, start: datetime, end: datetime | None = None) -> None:
        """드래그·클릭한 시간을 그대로 기본값으로 받는다."""
        self._reset()
        self._set_range(start, end or start + timedelta(hours=1))
        # 자연어가 날짜를 말하지 않거나 지웠을 때 돌아올 자리.
        self._origin = (self._start, self._end)
        self.heading.setText("새 일정")
        self.delete_button.hide()
        self.title_edit.setFocus()

    def current_range(self):
        """지금 담고 있는 시작·종료.  창을 다시 앉힐 때 쓴다."""
        return self._start, self._end

    def move_to_date(self, day) -> bool:
        """작성 중인 새 일정만 다른 날짜로 옮긴다.

        달력을 눌러 돌아다니는 것만으로 이미 저장된 일정의 날짜가 바뀌면
        안 되므로, 아직 저장하지 않은 초안일 때만 따라간다.  시간과 길이는
        그대로 두고 날짜만 갈아 끼운다.
        """
        if self.item_id is not None or not self.isVisible():
            return False
        target = day.toPyDate() if hasattr(day, "toPyDate") else day
        if target == self._start.date():
            return False
        span = self._end - self._start
        moved = self._start.replace(
            year=target.year, month=target.month, day=target.day
        )
        self._set_range(moved, moved + span)
        self._origin = (self._start, self._end)
        return True

    def open_item(self, item_id: int, occurrence_at: str | None = None) -> bool:
        item = self.store.schedules.item(item_id)
        if item is None:
            return False
        if item["source_reminder_id"] is not None:
            # 메모 알림이 만든 일정은 여기서 고칠 수 없다.  부르는 쪽이 전체 편집을 연다.
            return False
        self._reset()
        self._base = dict(item)
        self.item_id = int(item["id"])
        self.occurrence_at = occurrence_at
        self.heading.setText("일정 편집")
        self.editing_label.setText(f"‘{item['title']}’ 을(를) 수정하는 중입니다. 저장하면 이 일정이 바뀝니다.")
        self.editing_label.show()
        self._loading = True
        try:
            self.title_edit.setText(str(item["title"]))
        finally:
            self._loading = False
        self._pick_category(str(item["category"]))
        start = datetime.strptime(str(item["start_at"]), DATETIME_FMT)
        end = datetime.strptime(str(item["end_at"]), DATETIME_FMT)
        if occurrence_at:
            moved = datetime.strptime(str(occurrence_at), DATETIME_FMT)
            end = moved + (end - start)
            start = moved
        self._all_day = bool(item["all_day"])
        self._set_range(start, end)
        self._origin = (self._start, self._end)
        details = str(item["details"] or "")
        if details:
            self.memo_edit.setPlainText(details)
            self.memo_chip.setChecked(True)
        reminders = self.store.schedules.notifications(self.item_id)
        if reminders:
            self.reminder_edit.setText(", ".join(str(value) for value in reminders))
            self.reminder_chip.setChecked(True)
        rule = normalize_rule(item["recurrence_rule"])
        if rule["frequency"] != "none":
            self.repeat_combo.setCurrentIndex(max(0, self.repeat_combo.findData(rule["frequency"])))
            self.repeat_chip.setChecked(True)
        self.delete_button.show()
        self.title_edit.setFocus()
        self.title_edit.selectAll()
        return True

    def place_near(self, anchor, margin: int = 12, bounds=None) -> None:
        """드래그한 블록 옆에 세운다.  자리가 좁으면 반대쪽으로 접는다.

        ``bounds``는 실제로 보이는 영역이다.  캘린더가 창보다 넓어 잘려 있을 때
        부모 폭을 기준으로 삼으면 팝오버가 보이지 않는 자리에 놓인다.
        """
        self._anchor, self._anchor_margin = QRect(anchor), margin
        self._bounds = QRect(bounds) if bounds is not None and not QRect(bounds).isEmpty() else None
        self._relayout()

    def _bounds_rect(self) -> QRect:
        if self._bounds is not None and self._bounds.width() > 80:
            return self._bounds
        parent = self.parentWidget()
        return parent.rect() if parent is not None else QRect(0, 0, POPOVER_WIDTH, 600)

    def reposition(self) -> None:
        """부모 크기가 바뀐 뒤 같은 칸 옆에 다시 세운다."""
        if self._anchor is not None:
            self._relayout()

    def _relayout(self) -> None:
        """내용이 바뀐 만큼 팝오버 높이를 다시 잡는다.

        이 팝오버는 창이 아니라 캘린더 위에 좌표로 얹은 자식 위젯이라, 자식이
        보이기만 해서는 크기가 따라오지 않는다.  알림·반복·메모·D-Day를 켜면
        늘어난 내용이 옛 높이 안으로 눌려 들어가며 서로 겹쳤다.
        """
        self._fit_width()
        layout = self.body.layout()
        width = self.width() or POPOVER_WIDTH
        inner = max(120, width - 32)
        wanted = max(layout.totalSizeHint().height(), layout.heightForWidth(inner))
        self.body_scroll.setFixedHeight(wanted)
        self.layout().activate()
        parent = self.parentWidget()
        if parent is not None:
            excess = self.sizeHint().height() - (self._bounds_rect().height() - 16)
            if excess > 0:
                # 캘린더보다 길어지면 본문만 줄여서 스크롤한다.  저장 버튼은 남는다.
                self.body_scroll.setFixedHeight(max(140, wanted - excess))
                self.layout().activate()
        self.adjustSize()
        self._position()

    def _fit_width(self) -> None:
        """부모보다 넓어지면 오른쪽이 잘린다.  자리에 맞춰 폭을 먼저 줄인다.

        창을 좁히면 캘린더 폭도 함께 줄어드는데, 팝오버는 제 최소 폭을 그대로
        들고 있어 부모 밖으로 밀려났다.  세우기 전에 남은 자리를 재고 그 안으로
        폭을 맞춘다.
        """
        if self.parentWidget() is None:
            return
        bounds = self._bounds_rect()
        if bounds.width() <= 0:
            return
        room = max(POPOVER_MIN_WIDTH, min(POPOVER_MAX_WIDTH, bounds.width() - 16))
        self.setMinimumWidth(min(POPOVER_WIDTH, room))
        self.setMaximumWidth(room)

    def _position(self) -> None:
        anchor = self._anchor
        if anchor is None:
            return
        margin = self._anchor_margin
        parent = self.parentWidget()
        if parent is None:
            self.move(anchor.right() + margin, anchor.top())
            return
        bounds = self._bounds_rect()
        # 실제로 놓일 크기로 재야 한다.  sizeHint는 폭 제한을 반영하지 않는다.
        width = min(max(self.sizeHint().width(), self.minimumWidth()), self.maximumWidth())
        height = min(self.sizeHint().height(), max(120, bounds.height() - 16))
        left, right = bounds.left() + 8, bounds.right() - 8
        x = anchor.right() + margin
        if x + width > right:
            # 오른쪽이 좁으면 왼쪽으로 접고, 그마저 좁으면 오른쪽 끝에 붙인다.
            x = anchor.left() - width - margin
            if x < left:
                x = right - width
        x = max(left, min(x, max(left, right - width)))
        if width > bounds.width():
            x = max(0, bounds.left())
        top, bottom = bounds.top() + 8, bounds.bottom() - 8
        y = max(top, min(anchor.top(), max(top, bottom - height)))
        self.move(x, y)

    def dismiss(self) -> None:
        if not self.isVisible():
            return
        self.hide()
        self.closed.emit()

    def _reset(self) -> None:
        self.item_id = None
        self.occurrence_at = None
        self._base = {}
        self._all_day = False
        self._touched.clear()
        self._parser_fields.clear()
        self._parsed = None
        self._origin = None
        self.editing_label.hide()
        self.parse_label.hide()
        self._loading = True
        try:
            self.title_edit.clear()
        finally:
            self._loading = False
        self.memo_edit.clear()
        self.reminder_edit.clear()
        self.repeat_combo.setCurrentIndex(0)
        for chip in (self.reminder_chip, self.repeat_chip, self.memo_chip, self.dday_chip):
            chip.setChecked(False)
        self.time_chip.setChecked(False)
        self._pick_category(CATEGORIES[0][1])

    # ---------------------------------------------------------------- 시간 --
    def _set_range(self, start: datetime, end: datetime) -> None:
        if end <= start:
            end = start + timedelta(hours=1)
        self._start = start.replace(second=0, microsecond=0)
        self._end = end.replace(second=0, microsecond=0)
        self._sync_time_widgets()
        self._sync_time_labels()

    def _sync_time_widgets(self) -> None:
        self.date_edit.blockSignals(True)
        self.start_time_edit.blockSignals(True)
        self.end_time_edit.blockSignals(True)
        try:
            self.date_edit.setDate(QDate(self._start.year, self._start.month, self._start.day))
            self.start_time_edit.setTime(QTime(self._start.hour, self._start.minute))
            self.end_time_edit.setTime(QTime(self._end.hour, self._end.minute))
        finally:
            self.date_edit.blockSignals(False)
            self.start_time_edit.blockSignals(False)
            self.end_time_edit.blockSignals(False)

    def _sync_time_labels(self) -> None:
        if self._all_day:
            self.range_label.setText(f"{_day_label(self._start)} · 종일")
            self.time_chip.setText("종일")
            self.duration_chip.setText("종일")
            return
        self.range_label.setText(_day_label(self._start))
        self.time_chip.setText(f"{self._start:%H:%M} – {self._end:%H:%M}")
        self.duration_chip.setText(_duration_text(self._end - self._start))

    def _toggle_time_row(self, checked: bool) -> None:
        self.time_row.setVisible(checked)
        self._relayout()
        if checked:
            self.start_time_edit.setFocus()

    def _time_edited(self, *_args) -> None:
        self._touched.add("time")
        day = self.date_edit.date().toPyDate()
        start_time = self.start_time_edit.time().toPyTime()
        end_time = self.end_time_edit.time().toPyTime()
        start = datetime.combine(day, start_time)
        end = datetime.combine(day, end_time)
        if end <= start:
            end = start + timedelta(hours=1)
        self._all_day = False
        self._start, self._end = start, end
        self._sync_time_labels()

    def _pick_duration(self) -> None:
        menu = QMenu(self)
        for label, minutes in DURATION_PRESETS:
            menu.addAction(label).setData(minutes)
        chosen = menu.exec(self.duration_chip.mapToGlobal(self.duration_chip.rect().bottomLeft()))
        if chosen is None:
            return
        minutes = int(chosen.data())
        self._touched.add("time")
        if minutes == 0:
            self._all_day = True
            self._start = datetime.combine(self._start.date(), time.min)
            self._end = datetime.combine(self._start.date(), time(23, 59))
        else:
            self._all_day = False
            self._end = self._start + timedelta(minutes=minutes)
        self._sync_time_widgets()
        self._sync_time_labels()
        # '종일'로 바꾸면 머리글 글자 길이가 달라져 줄바꿈이 생길 수 있다.
        self._relayout()

    # ---------------------------------------------------------------- 분류 --
    def _pick_category(self, key: str, manual: bool = False) -> None:
        if manual:
            self._touched.add("category")
        self._category = key if key in self.category_chips else CATEGORIES[0][1]
        for value, chip in self.category_chips.items():
            background, foreground = CATEGORY_COLORS.get(value, ("#E7F0FF", "#234F9A"))
            selected = value == self._category
            chip.setChecked(selected)
            chip.setStyleSheet(
                f"background:{foreground if selected else background};"
                f"color:{'#ffffff' if selected else foreground};"
                f"border:1px solid {foreground};border-radius:11px;"
                "padding:2px 10px;min-height:22px;font-weight:600;"
            )

    def _toggle_extra(self, widget: QWidget):
        def apply(checked: bool) -> None:
            widget.setVisible(checked)
            # 보이게만 하고 끝내면 늘어난 내용이 옛 높이 안에서 서로 겹친다.
            self._relayout()
            # 파서가 켠 칸으로 초점이 튀면 제목을 계속 칠 수 없다.
            if checked and not self._loading:
                widget.setFocus()
        return apply

    # ------------------------------------------------------------ 자연어 --
    def _nlp_enabled(self) -> bool:
        try:
            return str(self.store.setting("schedule_nlp_enabled", "true")).lower() != "false"
        except Exception:
            return True

    def _title_changed(self, text: str) -> None:
        """제목 칸이 곧 자연어 입력이다.  적는 동안 칩이 따라 바뀐다."""
        if self._loading or not self._nlp_enabled():
            return
        base, base_end = self._origin or (self._start, self._end)
        self._parsed = ko_schedule_parser.parse(text, base=base, base_end=base_end)
        self._apply_parsed(self._parsed)

    def _apply_parsed(self, parsed) -> None:
        """읽은 값을 칩에 반영한다.  손으로 고친 항목은 건드리지 않는다."""
        fields = self._parser_fields
        self._loading = True
        try:
            if "time" not in self._touched:
                if parsed.start is not None:
                    self._all_day = parsed.all_day
                    self._set_range(parsed.start, parsed.end or parsed.start + timedelta(hours=1))
                    fields.add("time")
                elif "time" in fields and self._origin is not None:
                    # 날짜 표현을 지웠으면 끌어 둔 시각으로 돌아간다.
                    self._all_day = False
                    self._set_range(*self._origin)
                    fields.discard("time")
            if "category" not in self._touched:
                if parsed.category:
                    self._pick_category(parsed.category)
                    fields.add("category")
                elif "category" in fields:
                    self._pick_category(CATEGORIES[0][1])
                    fields.discard("category")
            if "reminder" not in self._touched:
                if parsed.reminders:
                    self.reminder_edit.setText(", ".join(str(value) for value in parsed.reminders))
                    self.reminder_chip.setChecked(True)
                    fields.add("reminder")
                elif "reminder" in fields:
                    self.reminder_edit.clear()
                    self.reminder_chip.setChecked(False)
                    fields.discard("reminder")
            if "repeat" not in self._touched:
                rule = parsed.recurrence
                if rule and rule.get("frequency", "none") != "none":
                    self.repeat_combo.setCurrentIndex(
                        max(0, self.repeat_combo.findData(rule["frequency"]))
                    )
                    self.repeat_chip.setChecked(True)
                    fields.add("repeat")
                elif "repeat" in fields:
                    self.repeat_chip.setChecked(False)
                    fields.discard("repeat")
        finally:
            self._loading = False
        self._show_parse_summary(parsed)

    def _show_parse_summary(self, parsed) -> None:
        if parsed is None or parsed.is_empty:
            self.parse_label.hide()
            self._relayout()
            return
        pieces = []
        if parsed.start is not None:
            if parsed.all_day:
                pieces.append(f"{parsed.start:%m월 %d일} 종일")
            else:
                pieces.append(f"{parsed.start:%m월 %d일} {parsed.start:%H:%M}–{parsed.end:%H:%M}")
        if parsed.category:
            pieces.append(category_name(parsed.category))
        if parsed.reminders:
            pieces.append(f"{parsed.reminders[0]}분 전")
        if parsed.recurrence and parsed.recurrence.get("frequency", "none") != "none":
            pieces.append(REPEAT_LABELS.get(parsed.recurrence["frequency"], "반복"))
        self.parse_label.setText("읽음 · " + " · ".join(pieces) if pieces else "")
        self.parse_label.setVisible(bool(pieces))
        self._relayout()

    def parsed_title(self) -> str:
        """저장에 쓸 제목.  인식한 날짜·표시자는 빼고 남은 말이다."""
        raw = self.title_edit.text().strip()
        parsed = self._parsed
        if parsed is None or parsed.is_empty or not self._nlp_enabled():
            return raw
        return parsed.title.strip() or raw

    # ---------------------------------------------------------------- 저장 --
    def values(self) -> dict:
        base = self._base
        start, end = self._start, self._end
        if self._all_day:
            start = datetime.combine(start.date(), time.min)
            end = datetime.combine(start.date(), time(23, 59))
        return {
            "id": self.item_id,
            "title": self.parsed_title() or "새 일정",
            "details": self.memo_edit.toPlainText() if self.memo_chip.isChecked() else "",
            "item_type": str(base.get("item_type") or "event"),
            "start_at": start.strftime(DATETIME_FMT),
            "end_at": end.strftime(DATETIME_FMT),
            "all_day": self._all_day,
            "category": self._category,
            "priority": int(base.get("priority") or 0),
            "note_id": base.get("note_id"),
            "status": str(base.get("status") or "pending"),
            "recurrence_rule": self._rule_values(),
            "reminders": self._reminder_values(),
            "hotkey": str(base.get("hotkey") or ""),
            "hotkey_action": str(base.get("hotkey_action") or "open"),
        }

    def _rule_values(self) -> dict:
        base_rule = normalize_rule(self._base.get("recurrence_rule") if self._base else {})
        frequency = self.repeat_combo.currentData() if self.repeat_chip.isChecked() else "none"
        if frequency == base_rule["frequency"]:
            # 이미 있던 반복은 간격·요일·종료 조건까지 그대로 지킨다.
            return base_rule
        return {"frequency": frequency, "interval": 1, "weekdays": [], "until": "", "count": 0}

    def _reminder_values(self) -> list[int]:
        if not self.reminder_chip.isChecked():
            return []
        values = []
        for piece in self.reminder_edit.text().replace(" ", "").split(","):
            if piece.isdigit():
                values.append(int(piece))
        return values[:5]

    def save(self) -> bool:
        values = self.values()
        try:
            if self.item_id and self.occurrence_at and self._is_recurring():
                self.store.schedules.move_occurrence(
                    self.item_id, self.occurrence_at, values["start_at"], values["end_at"]
                )
                item_id = self.item_id
            else:
                item_id = self.store.schedules.save_item(values)
            if self.dday_chip.isChecked():
                self._link_dday(item_id, values)
        except Exception as exc:
            QMessageBox.warning(self, "일정 저장", str(exc))
            return False
        self.item_id = item_id
        self.hide()
        self.saved.emit(item_id)
        return True

    def _is_recurring(self) -> bool:
        return normalize_rule(self._base.get("recurrence_rule") if self._base else {})["frequency"] != "none"

    def _link_dday(self, item_id: int, values: dict) -> None:
        """일정에서 D-Day로 넘어가는 한 걸음을 여기서 끝낸다."""
        note_id = values.get("note_id") or self.store.create_note(values["title"], values["details"])
        self.store.update_note(int(note_id), d_day_at=values["start_at"], d_day_label=values["title"])
        if values.get("note_id") != note_id:
            self.store.schedules.save_item(dict(values, id=item_id, note_id=int(note_id)))

    def _delete(self) -> None:
        if self.item_id is None:
            return
        if QMessageBox.question(self, "일정 삭제", "선택한 일정을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        item_id = self.item_id
        self.store.schedules.delete_item(item_id)
        self.hide()
        self.deleted.emit(item_id)

    def _request_full_edit(self) -> None:
        self.full_edit_requested.emit(self.values())

    # ------------------------------------------------------------- 키 입력 --
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier or not self.memo_edit.hasFocus():
                self.save()
                event.accept()
                return
        super().keyPressEvent(event)


def _day_label(value: datetime) -> str:
    return f"{value.month}/{value.day} ({'월화수목금토일'[value.weekday()]})"


def _flat_field(widget, object_name: str, width: int):
    """칩과 같은 말투로 그리되, 스핀 버튼과 달력 버튼은 그대로 둔다.

    누를 곳이 사라지면 마우스만 쓰는 사람은 시간을 못 바꾼다.  버튼은 남기고
    폭만 못 박아, 글꼴이 넓어져도 팝오버 밖으로 밀려나지 않게 한다.
    """
    widget.setObjectName(object_name)
    widget.setFixedWidth(width)
    widget.setMinimumHeight(30)
    widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return widget


def _add_chip(name: str, accessible_name: str) -> QPushButton:
    chip = QPushButton(f"＋{name}")
    chip.setObjectName("popoverAddChip")
    chip.setCheckable(True)
    chip.setAccessibleName(accessible_name)
    chip.toggled.connect(lambda checked, button=chip, label=name: button.setText(f"{'−' if checked else '＋'}{label}"))
    return chip


def _duration_text(span: timedelta) -> str:
    minutes = max(1, int(span.total_seconds() // 60))
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}시간 {remainder}분"
    if hours:
        return f"{hours}시간"
    return f"{remainder}분"
