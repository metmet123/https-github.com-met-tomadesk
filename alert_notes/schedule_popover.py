"""클릭한 자리에서 끝내는 일정 입력 팝오버.

고정 사이드 패널은 화면의 4분의 1을 상시 차지하면서, 정작 "겹치나?"를 보려고
연 캘린더를 가렸다.  이 팝오버는 드래그한 자리 옆에 떠서 제목·시간·분류 셋만
묻고, 시간·알림·반복·메모·D-Day는 같은 창 안에서 아래로 펼쳐 편집한다. 더 많은 설정이 필요하면
"전체 편집 ↗"으로 기존 편집기에 그대로 넘긴다.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from PyQt6.QtCore import QDate, QEvent, QPoint, QRect, QSize, QTime, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget, QBoxLayout, QWidgetAction, QLayout,
)

from .categories import (
    category_spec, schedule_categories,
    schedule_category_colors, schedule_category_name, recommend_schedule_category,
)
from .schedule_category_dialog import ScheduleCategoryDialog
from .datetime_input import CompactDateEdit, CompactTimeEdit
from . import ko_schedule_parser
from .note_shortcuts import TIME_SHORTCUTS, bind_time_shortcuts, modifier_setting, shortcut_text
from .schedule_recurrence import DATETIME_FMT, normalize_rule
from .schedule_token_edit import ScheduleTokenLineEdit
from .schedule_reminders import parse_reminder_value, reminder_input_value, reminder_label
from ui_theme import scaled_stylesheet


# 30분·1시간·2시간이 실제로 쓰이는 길이다.  종일은 시각을 지우는 쪽이라 끝에 둔다.
DURATION_PRESETS = (("30분", 30), ("1시간", 60), ("1시간 30분", 90), ("2시간", 120), ("종일", 0))
REPEAT_CHOICES = (("매일", "daily"), ("매주", "weekly"), ("매월", "monthly"), ("매년", "yearly"))
REPEAT_LABELS = {key: label for label, key in REPEAT_CHOICES}
POPOVER_WIDTH = 336
# 창을 좁혀도 이 아래로는 줄이지 않는다.  분류 칩 다섯 개와 저장 줄이 들어가는
# 최소 폭이다.  자리가 이보다 좁으면 폭을 줄이는 대신 왼쪽으로 붙여 세운다.
POPOVER_MIN_WIDTH = 300
POPOVER_MAX_WIDTH = POPOVER_WIDTH + 72


UNTITLED_SCHEDULE = "제목없음"


class _ParseSummaryLabel(QLabel):
    """두 줄 공간은 고정하고 긴 설명은 툴팁에 보존한다."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        metrics = self.fontMetrics()
        box = self.contentsRect().adjusted(2, 0, -2, 0)
        for index, line in enumerate(self.text().splitlines()[:2]):
            rect = QRect(box.x(), box.y() + index * metrics.lineSpacing(),
                         box.width(), metrics.lineSpacing())
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             metrics.elidedText(line, Qt.TextElideMode.ElideRight, box.width()))


class SchedulePopover(QFrame):
    saved = pyqtSignal(int)
    deleted = pyqtSignal(int)
    full_edit_requested = pyqtSignal(dict)
    closed = pyqtSignal()
    categories_changed = pyqtSignal()

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
        self._category_specs = schedule_categories(store)
        self.item_id: int | None = None
        self.occurrence_at: str | None = None
        self._base: dict = {}
        self._category = self._category_specs[0]["id"]
        self._all_day = False
        self._time_mode = "range"
        self._end_mode = "end"
        self._weekday_repeat = False
        self._detail_alarm_invalid = False
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
        self._ignored_tokens: set[tuple[int, int, str]] = set()
        self._parse_source = ""
        self._parsed_time_signature = None
        self._parsed_date_signature = None
        self._auto_reminders: set[int] = set()
        self._time_fixed_on_open = True
        self._auto_category = False
        self._manual_day = None
        self._manual_time = None
        self._origin: tuple[datetime, datetime] | None = None
        self._relative_base: datetime | None = None
        self._loading = False
        self._active_detail = None
        self._page_visibility = {}
        self._page_focus = None
        self._ui_scale = 1.0
        self._build_ui()
        self.hide()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.shell_layout = root
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.back_button = QPushButton("‹")
        self.back_button.setObjectName("popoverEscButton")
        self.back_button.setAccessibleName("일정 입력으로 돌아가기")
        self.back_button.clicked.connect(self._close_detail_page)
        self.back_button.hide()
        header.addWidget(self.back_button)
        self.heading = QLabel("새 일정")
        self.heading.setObjectName("popoverHeading")
        header.addWidget(self.heading)
        self.range_label = QPushButton()
        self.range_label.setObjectName("popoverHeaderDate")
        self.range_label.setAccessibleName("일정 날짜 변경")
        self.range_label.setToolTip("날짜 변경")
        self.date_menu = QMenu(self.range_label)
        date_action = QWidgetAction(self.date_menu)
        date_host = QWidget()
        date_host_layout = QHBoxLayout(date_host)
        date_host_layout.setContentsMargins(8, 8, 8, 8)
        self.date_edit = _flat_field(CompactDateEdit(), "popoverDateField", 156)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setAccessibleName("일정 날짜")
        date_host_layout.addWidget(self.date_edit)
        date_action.setDefaultWidget(date_host)
        self.date_menu.addAction(date_action)
        self.range_label.setMenu(self.date_menu)
        header.addWidget(self.range_label)
        header.addStretch()
        self.clear_detail_button = QPushButton("설정 해제")
        self.clear_detail_button.setObjectName("popoverLinkButton")
        self.clear_detail_button.clicked.connect(self._clear_detail_setting)
        self.clear_detail_button.hide()
        header.addWidget(self.clear_detail_button)
        # 조작법을 문장으로 설명하는 대신, 닫는 키를 그 자리에 눌러 볼 수 있게 둔다.
        self.escape_button = QPushButton("×")
        self.escape_button.setObjectName("popoverEscButton")
        self.escape_button.setAccessibleName("일정 입력 닫기")
        self.escape_button.setToolTip("Esc")
        self.escape_button.setFixedSize(28, 28)
        header.addWidget(self.escape_button)
        root.addLayout(header)

        # 본문만 스크롤한다.  항목을 다 펼쳐 캘린더보다 길어져도 제목줄과
        # 저장 버튼은 늘 제자리에 남는다.
        self.body = QWidget()
        self.body.setAutoFillBackground(False)
        self.body.setMinimumWidth(0)
        self.body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        body_root = QVBoxLayout(self.body)
        self.body_layout = body_root
        body_root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        body_root.setContentsMargins(0, 0, 0, 0)
        body_root.setSpacing(8)
        self.body_scroll = QScrollArea()
        self.body_scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.body_scroll.setWidget(self.body)
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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

        self.title_edit = ScheduleTokenLineEdit()
        self.title_edit.setObjectName("popoverTitleEdit")
        self.title_edit.setPlaceholderText("제목 추가")
        self.title_edit.setAccessibleName("일정 제목")
        self.title_edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.title_edit.setMinimumWidth(0)
        root.addWidget(self.title_edit)

        # 해석 설명은 제목 입력의 툴팁에만 둔다. 기존 참조용 위젯은 행을 차지하지 않는다.
        self.parse_label = _ParseSummaryLabel()
        self.parse_label.setObjectName("popoverParse")
        self.parse_label.setWordWrap(False)
        self.parse_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.parse_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.parse_label.hide()

        time_summary_row = QHBoxLayout()
        time_summary_row.setSpacing(6)
        self.time_icon = QLabel()
        self.time_icon.setPixmap(_schedule_icon("clock").pixmap(18, 18))
        self.time_icon.setAccessibleName("시간")
        time_summary_row.addWidget(self.time_icon)
        self.time_summary_button = QPushButton()
        self.time_summary_button.setObjectName("popoverTimeSummary")
        self.time_summary_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.time_summary_button.setAccessibleName("일정 시간 수정")
        self.time_summary_button.clicked.connect(self._toggle_time_summary)
        time_summary_row.addWidget(self.time_summary_button, 1)
        self.duration_label = QLabel()
        self.duration_label.setObjectName("popoverDurationText")
        time_summary_row.addWidget(self.duration_label)
        root.addLayout(time_summary_row)

        chips = QHBoxLayout()
        chips.setContentsMargins(24, 0, 0, 0)
        chips.setSpacing(0)
        self.time_chip = QPushButton("종료 시각")
        self.duration_chip = QPushButton("소요")
        self.point_chip = QPushButton("종료 없음")
        for index, button in enumerate((self.time_chip, self.duration_chip, self.point_chip)):
            button.setObjectName("popoverEndModeSegment")
            button.setProperty("segment", ("first", "middle", "last")[index])
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            chips.addWidget(button)
        chips.addStretch()
        root.addLayout(chips)

        self.time_row = QWidget()
        span_row = QHBoxLayout(self.time_row)
        span_row.setContentsMargins(24, 0, 0, 0)
        span_row.setSpacing(6)
        self.start_time_edit = _flat_field(CompactTimeEdit(), "popoverTimeField", 104)
        self.start_time_edit.setAccessibleName("시작 시각")
        self.end_time_edit = _flat_field(CompactTimeEdit(), "popoverTimeField", 104)
        self.end_time_edit.setAccessibleName("종료 시각")
        self.time_dash = QLabel("-")
        self.time_dash.setObjectName("popoverFieldLabel")
        span_row.addWidget(self.start_time_edit)
        span_row.addWidget(self.time_dash)
        span_row.addWidget(self.end_time_edit)
        span_row.addStretch()
        self.time_row.hide()
        root.addWidget(self.time_row)
        self.duration_row = QWidget()
        duration_layout = QVBoxLayout(self.duration_row)
        duration_layout.setContentsMargins(24, 0, 0, 0)
        for presets in (DURATION_PRESETS[:3], DURATION_PRESETS[3:]):
            row = QHBoxLayout()
            for label, minutes in presets:
                button = QPushButton(label)
                button.setObjectName("popoverReminderPreset")
                button.clicked.connect(lambda _checked=False, value=minutes: self._apply_duration(value))
                row.addWidget(button)
            duration_layout.addLayout(row)
        self.duration_row.hide()
        root.addWidget(self.duration_row)

        alarm_row = QHBoxLayout()
        alarm_row.setSpacing(5)
        self.alarm_icon = QLabel()
        self.alarm_icon.setPixmap(_schedule_icon("bell").pixmap(16, 16))
        self.alarm_icon.setAccessibleName("알림")
        alarm_row.addWidget(self.alarm_icon)
        self.none_reminder_button = QPushButton("없음")
        self.none_reminder_button.setObjectName("popoverAlarmChip")
        self.none_reminder_button.setCheckable(True)
        self.at_time_button = QPushButton("정각")
        self.at_time_button.setObjectName("popoverAlarmChip")
        self.at_time_button.setCheckable(True)
        self.at_time_button.setToolTip("일정 시작 시각에 알림")
        self.five_before_button = QPushButton("5분")
        self.five_before_button.setObjectName("popoverAlarmChip")
        self.five_before_button.setCheckable(True)
        self.ten_before_button = QPushButton("10분")
        self.ten_before_button.setObjectName("popoverAlarmChip")
        self.ten_before_button.setCheckable(True)
        self.reminder_edit = QLineEdit()
        self.reminder_edit.setObjectName("popoverAlarmInput")
        self.reminder_edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.reminder_edit.setMinimumWidth(50)
        self.reminder_edit.setPlaceholderText("예: 10, 5, 3분 전")
        self.reminder_edit.setToolTip("예: 10, 5, 3 → 각각 10분·5분·3분 전 알림 (최대 5개)")
        self.reminder_edit.setAccessibleName("알림 시간 직접 입력")
        for button in (self.none_reminder_button, self.at_time_button, self.five_before_button,
                       self.ten_before_button):
            alarm_row.addWidget(button)
        alarm_row.addWidget(self.reminder_edit, 1)
        self.reminder_chip = QPushButton("상세")
        self.reminder_chip.setToolTip("알림 상세 설정")
        self.reminder_chip.setObjectName("popoverDetailLink")
        self.reminder_chip.setCheckable(True)
        self.reminder_chip.setAccessibleName("알림 상세 설정")
        alarm_row.addWidget(self.reminder_chip)
        root.addLayout(alarm_row)

        category_row = QHBoxLayout()
        category_row.setSpacing(4)
        self.category_row = category_row
        self.category_icon = QLabel()
        self.category_icon.setPixmap(_schedule_icon("tag").pixmap(16, 16))
        self.category_icon.setAccessibleName("분류")
        category_row.addWidget(self.category_icon)
        self.category_chips = {}
        self.category_label = self.category_icon
        self._render_category_chips()
        root.addLayout(category_row)

        extras = QHBoxLayout()
        self.extras_layout = extras
        extras.setContentsMargins(24, 0, 0, 0)
        extras.setSpacing(4)
        self.repeat_chip = _add_chip("반복", "반복 설정")
        self.memo_chip = _add_chip("메모", "메모 추가")
        self.dday_chip = _add_chip("D-Day", "D-Day로 함께 등록")
        for chip in (self.repeat_chip, self.memo_chip, self.dday_chip):
            extras.addWidget(chip)
        extras.addStretch()
        root.addLayout(extras)

        self.reminder_details = self._build_reminder_details()
        self.reminder_details.hide()
        root.addWidget(self.reminder_details)
        root.removeWidget(self.reminder_details)
        category_index = next(
            (index for index in range(root.count()) if root.itemAt(index).layout() is self.category_row),
            root.count(),
        )
        root.insertWidget(category_index, self.reminder_details)

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
        self.memo_edit.textChanged.connect(self._sync_extra_labels)
        self.memo_edit.hide()
        root.addWidget(self.memo_edit)

        self.dday_hint = QLabel("저장할 때 같은 제목의 D-Day 메모를 함께 만듭니다.")
        self.dday_hint.setObjectName("popoverHint")
        self.dday_hint.setWordWrap(True)
        self.dday_hint.hide()
        root.addWidget(self.dday_hint)

        # 세부 영역은 각 필/칩의 ▴ 토글로 닫는다. 설정 해제만 필요한 경우에만
        # 작은 보조 동작을 남긴다.
        header.removeWidget(self.back_button)
        header.removeWidget(self.clear_detail_button)
        self.detail_actions = QWidget()
        action_row = QHBoxLayout(self.detail_actions)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(self.clear_detail_button)
        action_row.addStretch()
        root.addWidget(self.detail_actions)
        self.detail_actions.hide()

        footer_host = QWidget()
        footer_host.setObjectName("popoverFooter")
        footer_host.setStyleSheet("QWidget#popoverFooter { border-top: 1px solid #dce3ec; }")
        footer = QHBoxLayout(footer_host)
        self.footer_layout = footer
        footer.setContentsMargins(0, 8, 0, 0)
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
        self.save_button = QPushButton("저장")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setAccessibleName("일정 저장, Ctrl+S")
        self.save_button.setToolTip("일정 저장 (Ctrl+S)")
        self.save_button.setMinimumWidth(52)
        footer.addWidget(self.save_button)
        shell.addWidget(footer_host)

        self.escape_button.clicked.connect(self._escape_requested)
        self.save_button.clicked.connect(self.save)
        self.full_edit_button.clicked.connect(self._request_full_edit)
        self.delete_button.clicked.connect(self._delete)
        self.point_chip.clicked.connect(lambda: self._select_time_mode("point"))
        self.time_chip.clicked.connect(lambda: self._select_time_mode("range"))
        self.duration_chip.clicked.connect(lambda: self._select_time_mode("duration"))
        self.reminder_chip.toggled.connect(self._toggle_reminder_view)
        for chip, widget in ((self.repeat_chip, self.repeat_combo), (self.memo_chip, self.memo_edit),
                             (self.dday_chip, self.dday_hint)):
            chip.clicked.connect(lambda _checked, c=chip, w=widget: self._toggle_inline_extra(c, w))
        self.date_edit.dateChanged.connect(self._time_edited)
        self.start_time_edit.timeChanged.connect(self._time_edited)
        self.end_time_edit.timeChanged.connect(self._time_edited)
        self.title_edit.textChanged.connect(self._title_changed)
        self.title_edit.token_double_clicked.connect(self._cancel_parsed_token)
        # 제목 칸이 곧 한 줄 입력이다.  Enter로 바로 저장한다.
        self.title_edit.returnPressed.connect(self.save)
        self.reminder_edit.textChanged.connect(self._reminder_text_edited)
        self.none_reminder_button.clicked.connect(self._clear_reminders)
        self.at_time_button.clicked.connect(lambda checked: self._select_main_reminder(0, checked))
        self.five_before_button.clicked.connect(lambda checked: self._select_main_reminder(5, checked))
        self.ten_before_button.clicked.connect(lambda checked: self._select_main_reminder(10, checked))
        self.repeat_combo.activated.connect(self._repeat_combo_activated)
        self.repeat_combo.currentIndexChanged.connect(self._sync_extra_labels)
        self.repeat_chip.clicked.connect(lambda _checked: self._touched.add("repeat"))
        self.repeat_chip.toggled.connect(lambda _checked: self._sync_reminder_repeat_buttons())
        self._normal_reminder_view_widgets = [
            self.editing_label, self.title_edit, self.parse_label, self.point_chip, self.time_chip,
            self.duration_chip, self.time_row, self.alarm_icon, self.none_reminder_button, self.at_time_button,
            self.five_before_button, self.ten_before_button, self.reminder_edit, self.category_icon,
            *self.category_chips.values(), self.reminder_chip, self.repeat_chip, self.memo_chip,
            self.dday_chip, self.repeat_combo, self.memo_edit, self.dday_hint,
        ]
        self.body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._normal_reminder_visibility = {}
        self._pick_category(self._category)
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.save_shortcut.activated.connect(self._save_with_notice)
        self.escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        self.escape_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.escape_shortcut.activated.connect(self._escape_requested)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)
        self.reminder_shortcuts = bind_time_shortcuts(self, self.store, self._quick_reminder)

    def _build_reminder_details(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        date_row = QHBoxLayout()
        date_row.setSpacing(4)
        date_label = QLabel("날짜")
        date_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        date_row.addWidget(date_label)
        self.reminder_date_edit = _flat_field(CompactDateEdit(), "popoverDateField", 120)
        self.reminder_date_edit.setCalendarPopup(True)
        self.reminder_date_edit.setAccessibleName("알림 날짜")
        date_row.addWidget(self.reminder_date_edit)
        time_label = QLabel("시간")
        time_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        date_row.addWidget(time_label)
        self.reminder_time_edit = _flat_field(CompactTimeEdit(), "popoverTimeField", 84)
        self.reminder_time_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.reminder_time_edit.setAccessibleName("알림 시각")
        date_row.addWidget(self.reminder_time_edit)
        layout.addLayout(date_row)

        repeat_row = QHBoxLayout()
        repeat_row.setSpacing(3)
        repeat_label = QLabel("반복")
        repeat_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        repeat_row.addWidget(repeat_label)
        self.reminder_repeat_buttons = {}
        for text, key in (("안 함", "none"), ("매일", "daily"), ("평일", "weekdays"),
                          ("매주", "weekly"), ("매월", "monthly")):
            button = QPushButton(text)
            button.setObjectName("popoverReminderPreset")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, value=key: self._pick_reminder_repeat(value))
            repeat_row.addWidget(button)
            self.reminder_repeat_buttons[key] = button
        layout.addLayout(repeat_row)

        self.reminder_preset_buttons = {}
        for row_values in (
            ((0, "지금"), (5, "5분"), (30, "30분"), (60, "1시간")),
            ((120, "2시간"), (180, "3시간"), (240, "4시간"),
             (300, "5시간"), (360, "6시간"), (1440, "1일 전")),
        ):
            row = QHBoxLayout()
            row.setSpacing(3)
            for minutes, text in row_values:
                button = QPushButton(text)
                button.setObjectName("popoverReminderPreset")
                button.setCheckable(True)
                button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                button.clicked.connect(
                    lambda checked=False, value=minutes: self._select_reminder_preset(value, checked)
                )
                row.addWidget(button)
                self.reminder_preset_buttons[minutes] = button
            layout.addLayout(row)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        clear_button = QPushButton("알림 해제")
        clear_button.setObjectName("popoverReminderAction")
        clear_button.clicked.connect(self._clear_reminders)
        reset_button = QPushButton("초기화")
        reset_button.setObjectName("popoverReminderAction")
        reset_button.clicked.connect(self._reset_reminder_details)
        apply_button = QPushButton("적용")
        apply_button.setObjectName("popoverReminderAction")
        apply_button.clicked.connect(lambda: self.reminder_chip.setChecked(False))
        for button in (clear_button, reset_button, apply_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.reminder_date_edit.dateChanged.connect(self._detail_alarm_time_edited)
        self.reminder_time_edit.timeChanged.connect(self._detail_alarm_time_edited)
        return panel

    def _reload_reminder_shortcuts(self) -> None:
        modifier = modifier_setting(self.store)
        for shortcut, (key, _label, _minutes) in zip(self.reminder_shortcuts, TIME_SHORTCUTS):
            shortcut.setKey(QKeySequence(shortcut_text(modifier, key)))

    # ------------------------------------------------------------- 열기/닫기 --
    def open_new(
        self, start: datetime, end: datetime | None = None,
        *, relative_base: datetime | None = None, time_given: bool = True,
    ) -> None:
        """드래그·클릭한 시간을 그대로 기본값으로 받는다.

        ``time_given`` 이 False 면 시각은 ‘지금’으로 채워 둔 자리일 뿐이라
        사람이 시간을 정하기 전까지 정각 알림을 켜지 않는다.
        """
        self._reload_reminder_shortcuts()
        self._reset()
        self._time_fixed_on_open = bool(time_given)
        self._set_range(start, end or start + timedelta(hours=1))
        # 자연어가 날짜를 말하지 않거나 지웠을 때 돌아올 자리.
        self._origin = (self._start, self._end)
        self._relative_base = (relative_base or datetime.now()).replace(second=0, microsecond=0)
        self.heading.setText("새 일정")
        self.heading.setToolTip("")
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
        self._reload_reminder_shortcuts()
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
        # 헤더의 ‘일정 편집’과 제목 입력칸으로 편집 대상을 표시한다.
        # 같은 제목을 반복하는 가변 높이 안내는 고정 크기 입력 영역을 밀어내지 않는다.
        self.heading.setToolTip(self.editing_label.text())
        self._loading = True
        try:
            self.title_edit.setText(str(item["title"]))
        finally:
            self._loading = False
        self._pick_category(str(item["category"]))
        # 기존 일정의 저장 분류는 제목의 자동 추천보다 우선한다.
        self._touched.add("category")
        start = datetime.strptime(str(item["start_at"]), DATETIME_FMT)
        end = datetime.strptime(str(item["end_at"]), DATETIME_FMT)
        if occurrence_at:
            moved = datetime.strptime(str(occurrence_at), DATETIME_FMT)
            end = moved + (end - start)
            start = moved
        self._all_day = bool(item["all_day"])
        if str(item["time_mode"]) == "point":
            end = start + timedelta(hours=1)
        self._time_mode = str(item["time_mode"])
        self._end_mode = "none" if self._time_mode == "point" else "end"
        self._set_range(start, end)
        self._origin = (self._start, self._end)
        details = str(item["details"] or "")
        if details:
            self.memo_edit.setPlainText(details)
            self.memo_chip.setChecked(True)
        reminders = self.store.schedules.notifications(self.item_id)
        if reminders:
            self._set_reminder_values(reminders)
        rule = normalize_rule(item["recurrence_rule"])
        if rule["frequency"] != "none":
            self.repeat_combo.setCurrentIndex(max(0, self.repeat_combo.findData(rule["frequency"])))
            self.repeat_chip.setChecked(True)
            self._weekday_repeat = rule["frequency"] == "weekly" and rule["weekdays"] == [0, 1, 2, 3, 4]
        self._sync_reminder_repeat_buttons()
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
        self._apply_scale_dimensions(self._inherited_ui_scale())
        self._relayout()

    def _inherited_ui_scale(self) -> float:
        parent = self.parentWidget()
        while parent is not None:
            scale = getattr(parent, "_ui_scale", None)
            if isinstance(scale, (int, float)):
                return float(scale)
            parent = parent.parentWidget()
        # 독립 캘린더처럼 배율 소유자가 없는 경우 실제 상속 테마의 제목 글꼴을 사용한다.
        self.heading.ensurePolished()
        pixels = self.heading.font().pixelSize()
        return max(0.75, round(pixels / 14 * 4) / 4) if pixels > 0 else 1.0

    def _apply_scale_dimensions(self, scale: float) -> None:
        self._ui_scale = scale
        for widget, height in ((self.escape_button, 28), (self.title_edit, 36),
                               (self.time_summary_button, 30), (self.time_chip, 26),
                               (self.duration_chip, 26), (self.point_chip, 26),
                               (self.none_reminder_button, 28), (self.at_time_button, 28),
                               (self.five_before_button, 28), (self.ten_before_button, 28),
                               (self.reminder_edit, 28), (self.reminder_chip, 28),
                               (self.repeat_chip, 26), (self.memo_chip, 26),
                               (self.dday_chip, 26), (self.full_edit_button, 28),
                               (self.save_button, 32)):
            widget.setFixedHeight(round(height * scale))
        self.footer_layout.setContentsMargins(0, round(8 * scale), 0, 0)
        icon_size = round(18 * scale)
        self.time_icon.setPixmap(_schedule_icon("clock", icon_size).pixmap(icon_size, icon_size))
        self.alarm_icon.setPixmap(_schedule_icon("bell", icon_size).pixmap(icon_size, icon_size))
        self.category_icon.setPixmap(_schedule_icon("tag", icon_size).pixmap(icon_size, icon_size))
        self.shell_layout.setSpacing(round(8 * scale))
        self.body_layout.setSpacing(round(7 * scale))
        self.reminder_details.layout().setSpacing(0 if scale >= 1.4 else 3)
        self.setFixedWidth(_scaled_popover_width(scale))
        self.reminder_date_edit.setFixedWidth(round(120 + max(0, scale - 1) * 70))
        self.reminder_time_edit.setFixedWidth(round(84 + max(0, scale - 1) * 16))
        self.date_edit.setFixedWidth(round(156 * scale))
        self.start_time_edit.setFixedWidth(round(104 * scale))
        self.end_time_edit.setFixedWidth(round(104 * scale))
        self.save_button.setMinimumWidth(round(52 * scale))

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
        """실제 보이는 내용만큼만 높이를 쓰고, 낮은 화면에서만 스크롤한다."""
        self._fit_width()
        self.body_layout.activate()
        # QScrollArea 뷰포트 프레임/반올림 오차만큼 여유를 줘, 내용이 정확히
        # 맞는 기본 상태에서 2~4px짜리 가짜 스크롤이 생기지 않게 한다.
        body_height = max(1, self.body_layout.sizeHint().height() + 6)
        self.body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_scroll.setFixedHeight(body_height)
        self.shell_layout.activate()
        target = self.shell_layout.sizeHint().height()
        bounds = getattr(self, "_standalone_bounds", None)
        if bounds is None and self.parentWidget() is not None:
            bounds = self._bounds_rect()
        if bounds is not None and bounds.height() > 100:
            maximum = bounds.height() - 16
            if target > maximum:
                overflow = target - maximum
                self.body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                self.body_scroll.setFixedHeight(max(100, body_height - overflow))
                target = maximum
        self.setFixedHeight(target)
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
        desired = _scaled_popover_width(self._ui_scale)
        width = min(desired, room)
        changed = self.width() != width
        self.setFixedWidth(width)
        if changed and hasattr(self, "category_row"):
            self._render_category_chips()

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
        width, height = self.width(), self.height()
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
        self._close_detail_page()
        self._category_specs = schedule_categories(self.store)
        self.item_id = None
        self.occurrence_at = None
        self._base = {}
        self._all_day = False
        self._time_mode = "range"
        self._end_mode = "end"
        self._touched.clear()
        self._parser_fields.clear()
        self._parsed = None
        self._ignored_tokens.clear()
        self._parsed_time_signature = None
        self._parsed_date_signature = None
        self._auto_reminders.clear()
        self._auto_category = False
        self._manual_day = None
        self._manual_time = None
        self._origin = None
        self._relative_base = None
        self.editing_label.hide()
        self.parse_label.clear()
        self.parse_label.hide()
        self._loading = True
        try:
            self.title_edit.clear()
            self.title_edit.set_token_spans(())
        finally:
            self._loading = False
        self.memo_edit.clear()
        self._set_reminder_values([])
        self._weekday_repeat = False
        self.repeat_combo.setCurrentIndex(0)
        for chip in (self.reminder_chip, self.repeat_chip, self.memo_chip, self.dday_chip):
            chip.setChecked(False)
        self.time_row.hide()
        self._sync_reminder_repeat_buttons()
        self._pick_category(self._category_specs[0]["id"])

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
        selections = (
            (self.time_chip, self._time_mode == "range" and self._end_mode == "end"),
            (self.duration_chip, self._time_mode == "range" and self._end_mode == "duration"),
            (self.point_chip, self._time_mode == "point"),
        )
        for button, selected in selections:
            button.blockSignals(True)
            button.setChecked(selected)
            button.blockSignals(False)
        self.time_dash.setVisible(self._time_mode == "range")
        self.end_time_edit.setVisible(self._time_mode == "range")
        arrow = "▴" if self._active_detail is self.time_row else "▾"
        self.range_label.setText(_day_label(self._start))
        if self._all_day:
            self.time_summary_button.setText(f"종일 {arrow}")
            self.duration_label.setText("종일")
            self._apply_default_reminder()
            self._refresh_reminder_details()
            return
        span = (f"{self._start:%H:%M}" if self._time_mode == "point"
                else f"{self._start:%H:%M} - {self._end:%H:%M}")
        self.time_summary_button.setText(f"{span} {arrow}")
        self.duration_label.setText(
            "종료 없음" if self._time_mode == "point" else _duration_text(self._end - self._start)
        )
        self._apply_default_reminder()
        self._refresh_reminder_details()

    def _apply_default_reminder(self) -> None:
        """새 일정에 시각이 있으면 정각 알림을 기본으로 켠다.  종일이면 끈다.

        사람이 알림을 고쳤거나 제목에서 알림을 읽었으면 그 값을 따른다.
        """
        if (
            self.item_id is not None or self._loading
            or "reminder" in self._touched or "reminder" in self._parser_fields
        ):
            return
        timed = self._time_fixed_on_open or self._time_was_given()
        wanted = [0] if timed and not self._all_day else []
        if sorted(self._reminder_values()) != wanted:
            self._set_reminder_values(wanted)

    def _toggle_time_summary(self) -> None:
        if self._active_detail is self.time_row:
            self._close_detail_page()
        else:
            self._show_detail_page(self.time_row)

    def _select_time_mode(self, mode: str) -> None:
        self._touched.add("time")
        self._time_mode = "point" if mode == "point" else "range"
        self._end_mode = "none" if mode == "point" else mode
        self._all_day = False
        if self._time_mode == "range" and self._end <= self._start + timedelta(minutes=1):
            self._end = self._start + timedelta(hours=1)
        self._remember_manual_time()
        self._sync_time_labels()
        if mode == "duration":
            if self._active_detail is self.duration_row:
                self._close_detail_page()
            else:
                self._show_detail_page(self.duration_row)
        else:
            if self._active_detail is self.duration_row:
                self._close_detail_page()
        self._relayout()

    def _toggle_time_row(self, checked: bool) -> None:
        if not checked and self._active_detail is self.time_row:
            self._close_detail_page()

    def _time_edited(self, *_args) -> None:
        self._touched.add("date" if self.sender() is self.date_edit else "time")
        if self.sender() is self.end_time_edit:
            self._time_mode = "range"
            self._end_mode = "end"
        day = self.date_edit.date().toPyDate()
        start_time = self.start_time_edit.time().toPyTime()
        end_time = self.end_time_edit.time().toPyTime()
        start = datetime.combine(day, start_time)
        end = datetime.combine(day, end_time)
        if end <= start:
            end = start + timedelta(hours=1)
        self._all_day = False
        self._start, self._end = start, end
        if self.sender() is self.date_edit:
            self._manual_day = day
        else:
            self._remember_manual_time()
        self._sync_time_labels()

    def _remember_manual_time(self) -> None:
        self._manual_time = (
            self._start.time(), self._end - self._start, self._all_day,
            self._time_mode, self._end_mode,
        )

    def _pick_duration(self) -> None:
        if self._active_detail is self.duration_row:
            self._close_detail_page()
        else:
            self._show_detail_page(self.duration_row)

    def _apply_duration(self, minutes: int) -> None:
        self._touched.add("time")
        if minutes == 0:
            self._all_day = True
            self._time_mode = "range"
            self._end_mode = "duration"
            self._start = datetime.combine(self._start.date(), time.min)
            self._end = datetime.combine(self._start.date(), time(23, 59))
        else:
            self._all_day = False
            self._time_mode = "range"
            self._end_mode = "duration"
            self._end = self._start + timedelta(minutes=minutes)
        self._remember_manual_time()
        self._sync_time_widgets()
        self._sync_time_labels()
        # '종일'로 바꾸면 머리글 글자 길이가 달라져 줄바꿈이 생길 수 있다.
        self._relayout()

    # ---------------------------------------------------------------- 분류 --
    def _render_category_chips(self) -> None:
        while self.category_row.count():
            item = self.category_row.takeAt(0)
            if item.widget() is not None:
                if item.widget() is getattr(self, "category_icon", None):
                    continue
                item.widget().hide()
                item.widget().deleteLater()
        self.category_chips = {}
        self.category_row.addWidget(self.category_icon)
        # 현재 폼의 실제 사용 폭에서 5개까지 배치한다. 선택값은 메뉴에 숨기지 않는다.
        # 폭은 스타일이 적용된 실제 칩의 sizeHint로 잰다. 팝오버 글꼴로 재면 첫 표시(스타일 적용 전)와
        # 칩을 누른 뒤의 측정값이 달라져, 선택할 때마다 보이는 칩 수가 바뀐다.

        def make_chip(row) -> QPushButton:
            name = row["name"]
            chip = QPushButton(name[:4] + ("…" if len(name) > 4 else ""), self)
            chip.setObjectName("popoverCategoryChip")
            chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            chip.setIconSize(QSize(round(6 * self._ui_scale), round(6 * self._ui_scale)))
            chip.setIcon(_category_dot(schedule_category_colors(self._category_specs, row["id"])[1]))
            chip.hide()
            chip.ensurePolished()
            return chip

        def measured(widget: QPushButton) -> int:
            widget.ensurePolished()
            return widget.sizeHint().width()

        form_width = self.form.width() if hasattr(self, "form") else self.width()
        margins = self.shell_layout.contentsMargins()
        budget = max(100, form_width - margins.left() - margins.right()
                     - self.category_icon.sizeHint().width() - self.category_row.spacing())
        self._category_render_budget = budget
        selected = category_spec(self._category_specs, self._category)
        candidates = {row["id"]: make_chip(row) for row in self._category_specs[:5]}
        if selected is not None and selected["id"] not in candidates:
            candidates[selected["id"]] = make_chip(selected)
        widths = {key: measured(chip) for key, chip in candidates.items()}
        probe = QPushButton(f"+{len(self._category_specs)} ▾", self)
        probe.setObjectName("popoverCategoryOverflow")
        probe.setMenu(QMenu(probe))  # 메뉴가 붙은 버튼은 표시 폭이 달라진다.
        probe.hide()
        more_width = measured(probe)
        probe.deleteLater()
        visible = self._category_specs[:1]
        for count in range(min(5, len(self._category_specs)), 0, -1):
            trial = self._category_specs[:count]
            if selected is not None and selected not in trial:
                trial = [*trial[:-1], selected]
            has_more = len(self._category_specs) > count
            required = sum(widths[row["id"]] for row in trial)
            required += self.category_row.spacing() * (len(trial) - 1 + int(has_more))
            required += more_width if has_more else 0
            if required <= budget:
                visible = trial
                break
        visible_ids = {row["id"] for row in visible}
        for key, chip in candidates.items():
            if key not in visible_ids:
                chip.deleteLater()
        for row in visible:
            key, name = row["id"], row["name"]
            chip = candidates[key]
            chip.setFixedWidth(widths[key])
            chip.setFixedHeight(round(24 * self._ui_scale))
            chip.setCheckable(True)
            chip.setAccessibleName(f"{name} 분류")
            chip.clicked.connect(lambda _checked=False, value=key: self._pick_category(value, manual=True))
            self.category_chips[key] = chip
            self.category_row.addWidget(chip)
            chip.show()
        remaining = [row for row in self._category_specs if row["id"] not in visible_ids]
        more = QPushButton(f"+{len(remaining)} ▾")
        more.setObjectName("popoverCategoryOverflow")
        more.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        more.setFixedWidth(more_width)
        more.setFixedHeight(round(24 * self._ui_scale))
        more.setAccessibleName("다른 일정 분류와 관리")
        menu = QMenu(more)
        for row in remaining:
            action = menu.addAction(
                row["name"],
                lambda _checked=False, value=row["id"]: self._pick_category(value, manual=True),
            )
            action.setCheckable(True)
            action.setChecked(row["id"] == self._category)
        if remaining:
            menu.addSeparator()
        menu.addAction("관리", self._manage_categories)
        more.setMenu(menu)
        self.category_overflow_button = more
        self.category_manage_button = more
        if remaining:
            self.category_row.addWidget(more)
        else:
            more.hide()
        self.category_icon.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        try:
            self.category_icon.customContextMenuRequested.disconnect()
        except TypeError:
            pass
        self.category_icon.customContextMenuRequested.connect(
            lambda pos: menu.exec(self.category_icon.mapToGlobal(pos))
        )
        self.category_row.addStretch()
        for key, chip in self.category_chips.items():
            selected = key == self._category
            chip.setChecked(selected)
            chip.setToolTip(f"{schedule_category_name(self._category_specs, key)}{' · 선택됨' if selected else ''}")
        if hasattr(self, "category_icon"):
            self.category_icon.setToolTip("분류 · 자동 추천" if self._auto_category else "분류")

    def _manage_categories(self) -> None:
        dialog = ScheduleCategoryDialog(self.store, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.reload_categories()
        self.categories_changed.emit()
        self._relayout()

    def reload_categories(self) -> None:
        self._category_specs = schedule_categories(self.store)
        if category_spec(self._category_specs, self._category) is None:
            self._category = self._category_specs[0]["id"]
            self._auto_category = False
        self._render_category_chips()

    def _pick_category(self, key: str, manual: bool = False) -> None:
        if manual:
            self._touched.add("category")
            self._auto_category = False
        self._category = key if category_spec(self._category_specs, key) else self._category_specs[0]["id"]
        self._render_category_chips()

    def _toggle_extra(self, widget: QWidget):
        def apply(checked: bool) -> None:
            if checked and not self._loading:
                self._show_detail_page(widget)
                widget.setFocus()
            elif not checked and self._active_detail is widget:
                self._close_detail_page()
            else:
                widget.hide()
            self._sync_extra_labels()
        return apply

    def _toggle_reminder_view(self, checked: bool) -> None:
        if checked:
            self._show_detail_page(self.reminder_details)
            self.reminder_chip.blockSignals(True)
            self.reminder_chip.setChecked(True)
            self.reminder_chip.blockSignals(False)
            self._refresh_reminder_details()
        else:
            if self._active_detail is self.reminder_details:
                self._close_detail_page()

    def _show_detail_page(self, widget: QWidget) -> None:
        if self._active_detail is widget:
            return
        if self._active_detail is not None:
            self._close_detail_page()
        self._page_focus = QApplication.focusWidget()
        if self.isVisible() and hasattr(self, "_standalone_bounds"):
            self._manual_position = self.pos()
        self._page_visibility = {}
        self._active_detail = widget
        widget.show()
        can_clear = widget in (self.repeat_combo, self.memo_edit, self.dday_hint)
        self.body_layout.removeWidget(self.detail_actions)
        self.body_layout.insertWidget(self.body_layout.indexOf(widget) + 1, self.detail_actions)
        self.detail_actions.setVisible(can_clear)
        self.back_button.hide()
        self.clear_detail_button.setVisible(can_clear)
        self._sync_time_labels()
        self._relayout()

    def _close_detail_page(self) -> None:
        if self._active_detail is None:
            return
        self._active_detail.hide()
        self._active_detail = None
        self.detail_actions.hide()
        for widget, visible in self._page_visibility.items():
            widget.setVisible(visible)
        self._page_visibility.clear()
        self.reminder_chip.blockSignals(True)
        self.reminder_chip.setChecked(False)
        self.reminder_chip.blockSignals(False)
        self.back_button.hide()
        self.clear_detail_button.hide()
        self._sync_extra_labels()
        self._sync_time_labels()
        self._relayout()
        if self._page_focus is not None and self._page_focus.isVisible():
            self._page_focus.setFocus()

    def _reopen_extra(self, chip, widget) -> None:
        chip.setChecked(True)
        self._show_detail_page(widget)
        widget.setFocus()

    def _toggle_inline_extra(self, chip, widget) -> None:
        chip.blockSignals(True)
        chip.setChecked(True)
        chip.blockSignals(False)
        if self._active_detail is widget:
            self._close_detail_page()
        else:
            self._show_detail_page(widget)
            widget.setFocus()
        self._sync_extra_labels()
        self._sync_reminder_repeat_buttons()

    def _clear_detail_setting(self) -> None:
        chip = {self.memo_edit: self.memo_chip, self.repeat_combo: self.repeat_chip,
                self.dday_hint: self.dday_chip}.get(self._active_detail)
        if chip is None:
            return
        chip.setChecked(False)
        self._close_detail_page()

    def eventFilter(self, watched, event) -> bool:
        if (event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape
                and QApplication.activePopupWidget() is None):
            self._escape_requested()
            return True
        return super().eventFilter(watched, event)

    def _sync_extra_labels(self, *_args) -> None:
        self.repeat_chip.setText("+ 반복")
        self.memo_chip.setText("+ 메모")
        self.dday_chip.setText("+ D-Day")

    def _escape_requested(self) -> None:
        if self._active_detail is not None:
            self._close_detail_page()
        else:
            self.dismiss()

    def _set_reminder_values(self, values) -> None:
        minutes = sorted({int(value) for value in values})[:5]
        for button, value in ((self.at_time_button, 0), (self.five_before_button, 5),
                              (self.ten_before_button, 10)):
            button.blockSignals(True)
            button.setChecked(value in minutes)
            button.blockSignals(False)
        self.none_reminder_button.blockSignals(True)
        self.none_reminder_button.setChecked(not minutes)
        self.none_reminder_button.blockSignals(False)
        self.reminder_edit.blockSignals(True)
        self.reminder_edit.setText(", ".join(
            reminder_input_value(value) for value in minutes if value not in (0, 5, 10)
        ))
        self.reminder_edit.blockSignals(False)
        self._refresh_reminder_details()

    def _reminder_text_edited(self, _text: str) -> None:
        self._touched.add("reminder")
        self._auto_reminders.intersection_update({0, 5})
        self._refresh_reminder_details()

    def _reminder_selection_changed(self) -> None:
        if not self._loading:
            self._touched.add("reminder")
        self._refresh_reminder_details()

    def _select_main_reminder(self, minutes: int, checked: bool) -> None:
        self._touched.add("reminder")
        self._auto_reminders.clear()
        values = set(self._reminder_values())
        if checked:
            values.add(minutes)
        else:
            values.discard(minutes)
        if len(values) > 5:
            self._show_status("알림은 최대 5개")
            values.discard(minutes)
        self._set_reminder_values(values)

    def _select_reminder_preset(self, minutes: int, checked: bool) -> None:
        self._touched.add("reminder")
        self._auto_reminders.clear()
        values = set(self._reminder_values())
        if checked:
            values.add(minutes)
        else:
            values.discard(minutes)
        if len(values) > 5:
            self._show_status("알림은 최대 5개")
            values.discard(minutes)
        self._set_reminder_values(values)

    def _quick_reminder(self, minutes: int, _label: str = "") -> None:
        values = set(self._reminder_values())
        if minutes in values:
            values.remove(minutes)
        elif len(values) < 5:
            values.add(minutes)
        else:
            self._show_status("알림은 최대 5개")
            return
        self._touched.add("reminder")
        self._auto_reminders.discard(minutes)
        self._set_reminder_values(values)

    def _refresh_reminder_details(self) -> None:
        if not hasattr(self, "reminder_date_edit"):
            return
        self._detail_alarm_invalid = False
        values = self._reminder_values()
        self.none_reminder_button.blockSignals(True)
        self.none_reminder_button.setChecked(not values)
        self.none_reminder_button.blockSignals(False)
        self._update_alarm_summary()
        for minutes, button in self.reminder_preset_buttons.items():
            button.setChecked(minutes in values)
        if values:
            first = min(values)
            due = self._start - timedelta(minutes=first)
        else:
            due = self._start
        if self.reminder_chip.isChecked():
            self.reminder_chip.setToolTip(f"알림 {due:%m/%d %H:%M}" if values else "알림 상세 설정")
        self._detail_selected_minutes = min(values) if values else None
        self.reminder_date_edit.blockSignals(True)
        self.reminder_time_edit.blockSignals(True)
        try:
            self.reminder_date_edit.setDate(QDate(due.year, due.month, due.day))
            self.reminder_time_edit.setTime(QTime(due.hour, due.minute))
        finally:
            self.reminder_date_edit.blockSignals(False)
            self.reminder_time_edit.blockSignals(False)

    def _detail_alarm_time_edited(self, *_args) -> None:
        due = datetime.combine(
            self.reminder_date_edit.date().toPyDate(),
            self.reminder_time_edit.time().toPyTime(),
        )
        minutes = int((self._start - due).total_seconds() // 60)
        if abs(minutes) > 525600:
            self._detail_alarm_invalid = True
            self._show_status("시작 전후 365일 이내")
            return
        values = set(self._reminder_values())
        if self._detail_selected_minutes is not None:
            values.discard(self._detail_selected_minutes)
        if len(values) >= 5 and minutes not in values:
            self._detail_alarm_invalid = True
            self._show_status("알림은 최대 5개")
            return
        values.add(minutes)
        self._touched.add("reminder")
        self._auto_reminders.discard(self._detail_selected_minutes)
        self._auto_reminders.discard(minutes)
        self._set_reminder_values(values)

    def _clear_reminders(self, *_args) -> None:
        self._touched.add("reminder")
        self._auto_reminders.clear()
        self._set_reminder_values([])

    def _reset_reminder_details(self) -> None:
        self._clear_reminders()
        self._pick_reminder_repeat("none")

    def _pick_reminder_repeat(self, key: str) -> None:
        was_loading = self._loading
        self._loading = True
        self._touched.add("repeat")
        self._weekday_repeat = key == "weekdays"
        if key == "none":
            self.repeat_chip.setChecked(False)
        else:
            self.repeat_chip.setChecked(True)
            frequency = "weekly" if key == "weekdays" else key
            self.repeat_combo.setCurrentIndex(max(0, self.repeat_combo.findData(frequency)))
        self._sync_reminder_repeat_buttons()
        self._loading = was_loading
        self._sync_extra_labels()

    def _repeat_combo_activated(self, _index: int) -> None:
        self._touched.add("repeat")
        self._weekday_repeat = False
        self._sync_reminder_repeat_buttons()

    def _sync_reminder_repeat_buttons(self) -> None:
        if not hasattr(self, "reminder_repeat_buttons"):
            return
        chosen = "none" if not self.repeat_chip.isChecked() else str(self.repeat_combo.currentData())
        if chosen == "weekly" and getattr(self, "_weekday_repeat", False):
            chosen = "weekdays"
        for key, button in self.reminder_repeat_buttons.items():
            button.setChecked(key == chosen)

    # ------------------------------------------------------------ 자연어 --
    def _nlp_enabled(self) -> bool:
        try:
            return str(self.store.setting("schedule_nlp_enabled", "true")).lower() != "false"
        except Exception:
            return True

    def _title_changed(self, text: str) -> None:
        """제목 칸이 곧 자연어 입력이다.  적는 동안 칩이 따라 바뀐다."""
        self._ignored_tokens = ko_schedule_parser.remap_ignored_spans(
            self._parse_source, text, self._ignored_tokens,
        )
        self._parse_source = text
        if self._loading or not self._nlp_enabled():
            return
        base, base_end = self._origin or (self._start, self._end)
        self._parsed = ko_schedule_parser.parse(
            text, base=base, base_end=base_end,
            relative_base=self._relative_base,
            ignored_spans=tuple(sorted(self._ignored_tokens)),
            category_keys={row["name"]: row["id"] for row in self._category_specs},
        )
        self.title_edit.set_token_spans(self._parsed.spans)
        self._apply_parsed(self._parsed)

    def _cancel_parsed_token(self, start: int, end: int, kind: str) -> None:
        parsed = self._parsed
        if parsed is None:
            return
        if kind == "time":
            # `10~18시`는 내부적으로 시작/끝 두 범위여도 사용자에게는 한 시간 표현이다.
            targets = [span for span in parsed.spans if span.kind == "time"]
        else:
            targets = [
                span for span in parsed.spans
                if span.kind == kind and span.start < end and start < span.end
            ]
        self._ignored_tokens.update((span.start, span.end, span.kind) for span in targets)
        self._title_changed(self.title_edit.text())

    def _apply_parsed(self, parsed) -> None:
        """읽은 값을 칩에 반영한다.  손으로 고친 항목은 건드리지 않는다."""
        if parsed.issues:
            self._show_parse_summary(parsed)
            return
        fields = self._parser_fields
        parsed_time_signature = tuple(s.text.strip() for s in parsed.spans if s.kind == "time")
        parsed_date_signature = tuple(s.text.strip() for s in parsed.spans if s.kind == "date")
        explicit_time_changed = (
            bool(parsed_time_signature)
            and parsed_time_signature != self._parsed_time_signature
        )
        explicit_date_changed = (
            bool(parsed_date_signature) and parsed_date_signature != self._parsed_date_signature
        )
        self._loading = True
        try:
            if parsed.start is not None or ("time" in fields and self._origin is not None):
                origin_start, origin_end = self._origin or (self._start, self._end)
                start, end = self._start, self._end
                day = start.date()
                clock = start.time()
                length = end - start
                if "date" not in self._touched or explicit_date_changed:
                    day = (parsed.start or origin_start).date()
                elif self._parsed_date_signature and not parsed_date_signature and self._manual_day is not None:
                    day = self._manual_day
                if "time" not in self._touched or explicit_time_changed:
                    clock = (parsed.start if parsed_time_signature else origin_start).time()
                    length = ((parsed.end - parsed.start) if parsed_time_signature
                              else origin_end - origin_start)
                    self._all_day = parsed.all_day
                    self._time_mode = parsed.time_mode or "range"
                    self._end_mode = "none" if self._time_mode == "point" else "end"
                elif self._parsed_time_signature and not parsed_time_signature and self._manual_time is not None:
                    clock, length, self._all_day, self._time_mode, self._end_mode = self._manual_time
                start = datetime.combine(day, clock)
                self._set_range(start, start + length)
                if parsed.start is not None:
                    fields.add("time")
                else:
                    fields.discard("time")
            if "category" not in self._touched:
                recommended = parsed.category or recommend_schedule_category(parsed.title, self._category_specs)
                if recommended:
                    self._pick_category(recommended)
                    self._auto_category = not bool(parsed.category)
                    fields.add("category")
                elif "category" in fields:
                    self._pick_category(self._category_specs[0]["id"])
                    self._auto_category = False
                    fields.discard("category")
            if "reminder" not in self._touched:
                if parsed.reminders:
                    self._set_reminder_values(parsed.reminders)
                    fields.add("reminder")
                elif "reminder" in fields:
                    self._set_reminder_values([])
                    fields.discard("reminder")
                self._auto_reminders = set(parsed.reminders)
            else:
                removed = self._auto_reminders - set(parsed.reminders)
                if removed:
                    self._set_reminder_values(set(self._reminder_values()) - removed)
                self._auto_reminders.intersection_update(parsed.reminders)
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
            self._parsed_time_signature = parsed_time_signature
            self._parsed_date_signature = parsed_date_signature
        self._apply_default_reminder()
        self.category_icon.setToolTip("분류 · 자동 추천" if self._auto_category else "분류")
        self._show_parse_summary(parsed)

    def _show_parse_summary(self, parsed) -> None:
        if parsed is not None and parsed.issues:
            self.parse_label.setText(" · ".join(parsed.issues))
            self.parse_label.setToolTip(self.parse_label.text())
            self.title_edit.setToolTip(self.parse_label.toolTip())
            self.parse_label.hide()
            self._relayout()
            return
        self._update_alarm_summary()
        self._relayout()

    def _update_alarm_summary(self) -> None:
        if self._parsed is not None and self._parsed.issues:
            return
        values = self._reminder_values()
        kinds = {span.kind for span in self._parsed.spans} if self._parsed else set()
        if getattr(self, "_mini_origin", None) is not None or getattr(self, "_mini_time_selected", False):
            kinds.update(("date", "time"))
        if kinds & {"date", "time", "reminder"}:
            def clock(value):
                return f"{value:%H:%M}"

            parts = []
            when = ""
            if "date" in kinds:
                when = f"{self._start.month}월 {self._start.day}일"
            if "time" in kinds:
                if self._all_day:
                    span = "종일"
                elif self._time_mode == "point":
                    span = clock(self._start)
                else:
                    first = clock(self._start)
                    last = clock(self._end)
                    if self._end.date() != self._start.date():
                        last = f"{self._end.month}월{self._end.day}일 {last}"
                    span = f"{first}–{last}"
                when = f"{when} · {span}" if when else span
            if when:
                parts.append(when)
            if values:
                alarms = []
                for value in values:
                    due = self._start - timedelta(minutes=value)
                    stamp = f"{due:%H:%M}" if due.date() == self._start.date() else f"{due:%m/%d %H:%M}"
                    label = "정각" if value == 0 else reminder_label(value)
                    alarms.append(f"{clock(self._start)}의 {label} 알람 · {stamp}")
                parts.append(alarms[0] + (f" 외 {len(alarms) - 1}개" if len(alarms) > 1 else ""))
            summary = "\n".join(parts)
            self.parse_label.setText(summary)
            self.parse_label.setToolTip("\n".join(([when] if when else []) + (alarms if values else [])))
        elif values:
            due = self._start - timedelta(minutes=max(values))
            stamp = f"{due:%H:%M}" if due.date() == self._start.date() else f"{due:%m/%d %H:%M}"
            self.parse_label.setText(f"알림 {stamp}" + (f" 외 {len(values) - 1}개" if len(values) > 1 else ""))
            self.parse_label.setToolTip(" · ".join(reminder_label(value) for value in values))
        else:
            self.parse_label.clear()
            self.parse_label.setToolTip("")
        # 이미 지난 시각으로 새 일정을 만들면 제목 툴팁에 한 줄 덧붙여 알린다.
        past = (
            "지난 시각입니다. 날짜·시간을 확인해 주세요."
            if "time" in kinds and self.item_id is None and not self._all_day
            and self._start < datetime.now() else ""
        )
        self.title_edit.setToolTip("\n".join(text for text in (self.parse_label.toolTip(), past) if text))
        self.parse_label.hide()

    def _show_status(self, message: str) -> None:
        """입력 경고를 제목 툴팁에 남긴다."""
        self.parse_label.setText(message)
        self.parse_label.setToolTip(message)
        self.title_edit.setToolTip(message)
        self.parse_label.hide()
        self._relayout()

    def parsed_title(self) -> str:
        """저장에 쓸 제목.  인식한 날짜·표시자는 빼고 남은 말이다."""
        raw = self.title_edit.text().strip()
        parsed = self._parsed
        if parsed is None or parsed.is_empty or not self._nlp_enabled():
            return raw
        return parsed.title.strip()

    def _fallback_title(self) -> str:
        """제목 없이 날짜·시간만 정했을 때 쓸 제목.  기본 팝오버는 제목을 요구한다."""
        return ""

    def _time_was_given(self) -> bool:
        """사람이 날짜·시간을 직접 정했는가.  열 때 채워 둔 현재 시각은 치지 않는다."""
        kinds = {span.kind for span in self._parsed.spans} if self._parsed is not None else set()
        return bool(kinds & {"date", "time"}) or bool(self._touched & {"date", "time"})             or bool(getattr(self, "_mini_time_selected", False))

    # ---------------------------------------------------------------- 저장 --
    def values(self) -> dict:
        base = self._base
        start, end = self._start, self._end
        if self._time_mode == "point" and not self._all_day:
            end = start + timedelta(minutes=1)
        if self._all_day:
            start = datetime.combine(start.date(), time.min)
            end = datetime.combine(start.date(), time(23, 59))
        return {
            "id": self.item_id,
            "title": self.parsed_title() or self._fallback_title(),
            "details": self.memo_edit.toPlainText() if self.memo_chip.isChecked() else "",
            "item_type": str(base.get("item_type") or "event"),
            "start_at": start.strftime(DATETIME_FMT),
            "end_at": end.strftime(DATETIME_FMT),
            "time_mode": self._time_mode,
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
        if frequency == "weekly" and getattr(self, "_weekday_repeat", False):
            return {"frequency": "weekly", "interval": 1,
                    "weekdays": [0, 1, 2, 3, 4], "until": "", "count": 0}
        if frequency == base_rule["frequency"]:
            # 이미 있던 반복은 간격·요일·종료 조건까지 그대로 지킨다.
            return base_rule
        return {"frequency": frequency, "interval": 1, "weekdays": [], "until": "", "count": 0}

    def _reminder_values(self) -> list[int]:
        values = []
        if self.at_time_button.isChecked():
            values.append(0)
        if self.five_before_button.isChecked():
            values.append(5)
        if self.ten_before_button.isChecked():
            values.append(10)
        for piece in self.reminder_edit.text().split(","):
            if piece.strip():
                try:
                    values.append(parse_reminder_value(piece))
                except ValueError:
                    pass  # 입력 중인 값은 반영하지 않고 저장할 때 오류를 안내한다.
        return sorted(set(values))

    def _save_with_notice(self) -> None:
        # Ctrl+S도 저장 버튼과 같다.  저장 확인 창을 한 번 더 띄우지 않는다.
        self.save()

    def save(self, _checked: bool = False, *, show_confirmation: bool = False) -> bool:
        if self._parsed is not None and self._parsed.issues:
            QMessageBox.warning(self, "일정 입력", "\n".join(self._parsed.issues))
            return False
        if self._detail_alarm_invalid:
            QMessageBox.warning(self, "알림 시간", "알림 날짜·시간을 확인해 주세요.")
            return False
        raw_parts = [part.strip() for part in self.reminder_edit.text().split(",") if part.strip()]
        try:
            for part in raw_parts:
                parse_reminder_value(part)
        except ValueError as exc:
            QMessageBox.warning(self, "알림 시간", str(exc))
            return False
        if len(self._reminder_values()) > 5:
            QMessageBox.warning(self, "알림 시간", "알림은 최대 5개까지 선택할 수 있습니다.")
            return False
        values = self.values()
        if not values["title"].strip():
            QMessageBox.warning(self, "일정 제목", "날짜·시간 외에 일정 제목을 입력해 주세요.")
            self.title_edit.setFocus()
            return False
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
        if show_confirmation:
            QMessageBox.information(self, "일정 저장", "일정이 저장되었습니다.")
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
            self._escape_requested()
            event.accept()
            return
        super().keyPressEvent(event)


class StandaloneSchedulePopover(SchedulePopover):
    """Show the same compact editor without making the main window visible."""

    def _fallback_title(self) -> str:
        # 빠른 일정 창: 시간만 적으면 ‘제목없음’으로 저장하고 그 시각에 알린다.
        return UNTITLED_SCHEDULE if self._time_was_given() else ""

    def __init__(self, store):
        super().__init__(store)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._standalone_bounds: QRect | None = None
        self._theme_scale: float | None = None
        self._compact_height: int | None = None
        self._manual_position: QPoint | None = None
        self._drag_offset: QPoint | None = None
        from .mini_schedule_timeline import MiniScheduleTimeline
        self.form = QWidget(self)
        # Qt transfers the existing layout and its children from this window.
        self.form.setLayout(self.shell_layout)
        self.outer_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.outer_layout.setContentsMargins(0, 0, 0, 0)
        self.outer_layout.setSpacing(8)
        self.mini_timeline = MiniScheduleTimeline(store, self)
        self.outer_layout.addWidget(self.mini_timeline)
        self.outer_layout.addWidget(self.form)
        self.timeline_toggle = QPushButton("시간 ▾")
        self.timeline_toggle.setObjectName("popoverAddChip")
        self.timeline_toggle.setCheckable(True)
        self.timeline_toggle.setAccessibleName("시간 선택 펼치기")
        self.footer_layout.insertWidget(2, self.timeline_toggle)
        self.timeline_toggle.hide()
        self.timeline_toggle.toggled.connect(self._toggle_timeline)
        self._mini_origin = None
        self._mini_time_selected = False
        self.mini_timeline.selectionStarted.connect(self._mini_started)
        self.mini_timeline.selectionCanceled.connect(self._mini_cancel)
        self.mini_timeline.rangePreview.connect(self._mini_preview)
        self.mini_timeline.rangeSelected.connect(self._mini_selected)
        for label in (self.heading,):
            label.setCursor(Qt.CursorShape.OpenHandCursor)
            label.installEventFilter(self)

    def open_at_current_time(self, scale: float = 1.0) -> None:
        self._compact_height = None
        self.setMinimumHeight(0)
        self._apply_scale_dimensions(scale)
        if self._theme_scale != scale:
            self.setStyleSheet(scaled_stylesheet(scale))
            self._theme_scale = scale
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._standalone_bounds = (
            screen.availableGeometry() if screen is not None else QRect(0, 0, 900, 650)
        )
        now = datetime.now().replace(second=0, microsecond=0)
        self.open_new(now, now + timedelta(hours=1), relative_base=now, time_given=False)
        self.mini_timeline.set_draft(*self.current_range(), refresh=True)
        self._relayout()
        # 표시되면서 실제 글꼴/QSS 최소 높이가 확정된다. 그 뒤 한 번 더 재면
        # 아래 시간표를 펼칠 때 푸터가 10px가량 뛰는 초기 지오메트리 오차가 없다.
        self.show()
        self._relayout()
        QTimer.singleShot(0, self._relayout)
        self._compact_height = self.height()
        self.raise_()
        self.activateWindow()
        self.title_edit.setFocus()

    def open_new(self, start, end=None, *, relative_base=None, time_given=True):
        self._mini_time_selected = False
        self._mini_origin = None
        if hasattr(self, "timeline_toggle"):
            self.timeline_toggle.setChecked(False)
        super().open_new(start, end, relative_base=relative_base, time_given=time_given)

    def _relayout(self) -> None:
        if not hasattr(self, "mini_timeline"):
            return super()._relayout()
        form_width = _scaled_popover_width(self._ui_scale)
        bounds = self._standalone_bounds
        side = bounds is None or bounds.width() >= form_width + 220 + 24
        self.form.setFixedWidth(form_width)
        margins = self.shell_layout.contentsMargins()
        category_budget = max(100, form_width - margins.left() - margins.right()
                              - self.category_icon.sizeHint().width() - self.category_row.spacing())
        if getattr(self, "_category_render_budget", None) != category_budget:
            self._render_category_chips()
        self.outer_layout.removeWidget(self.mini_timeline)
        self.outer_layout.setDirection(QBoxLayout.Direction.LeftToRight if side else QBoxLayout.Direction.TopToBottom)
        if side:
            self.outer_layout.insertWidget(0, self.mini_timeline)
        else:
            self.outer_layout.addWidget(self.mini_timeline)
        self.timeline_toggle.setVisible(not side)
        self.mini_timeline.setVisible(side or self.timeline_toggle.isChecked())
        self.mini_timeline.setFixedWidth(220 if side else form_width)
        self.mini_timeline.setMinimumHeight(0)
        self.mini_timeline.setMaximumHeight(16777215)
        border_width = self.contentsMargins().left() + self.contentsMargins().right()
        border_height = self.contentsMargins().top() + self.contentsMargins().bottom()
        self.setFixedWidth(form_width + (228 if side else 0) + border_width)
        self.body_layout.activate()
        body_height = max(1, self.body_layout.sizeHint().height() + 6)
        self.body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_scroll.setFixedHeight(body_height)
        self.shell_layout.activate()
        form_height = self.shell_layout.sizeHint().height()
        maximum = bounds.height() - 16 - border_height if bounds is not None else form_height
        timeline_height = 0
        if not side and self.timeline_toggle.isChecked():
            timeline_height = max(160, min(220, maximum - form_height - 8))
            maximum -= timeline_height + 8
        if form_height > maximum:
            self.body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.body_scroll.setFixedHeight(max(100, body_height - (form_height - maximum)))
            form_height = self.shell_layout.sizeHint().height()
        self.form.setFixedHeight(form_height)
        if side:
            self.mini_timeline.setFixedHeight(form_height)
        elif timeline_height:
            self.mini_timeline.setFixedHeight(timeline_height)
        self.setFixedHeight(form_height + (timeline_height + 8 if timeline_height else 0) + border_height)
        self.outer_layout.activate()
        self._position()

    def _toggle_timeline(self, checked):
        self.timeline_toggle.setText("시간 ▴" if checked else "시간 ▾")
        self.timeline_toggle.setAccessibleName("시간 선택 접기" if checked else "시간 선택 펼치기")
        if checked and self._active_detail is not None:
            self._close_detail_page()
        self._relayout()
        if checked:
            self.mini_timeline.center_draft()

    def _show_detail_page(self, widget):
        if hasattr(self, "timeline_toggle") and self.timeline_toggle.isVisible():
            self.timeline_toggle.setChecked(False)
        super()._show_detail_page(widget)

    def _escape_requested(self):
        if getattr(self, "_mini_origin", None) is not None:
            self.mini_timeline.canvas.view._clear_band()
            self.mini_timeline.canvas.view._band_origin = None
            self._mini_cancel()
        elif hasattr(self, "timeline_toggle") and self.timeline_toggle.isVisible() and self.timeline_toggle.isChecked():
            self.timeline_toggle.setChecked(False)
        else:
            super()._escape_requested()

    def _sync_time_labels(self):
        super()._sync_time_labels()
        if hasattr(self, "mini_timeline"):
            self.mini_timeline.set_draft(self._start, self._end, point=self._time_mode == "point", all_day=self._all_day)

    def _mini_started(self):
        self._mini_origin = (self._start, self._end, self._time_mode, self._all_day, self._end_mode)

    def _mini_preview(self, start, end):
        self._time_mode, self._all_day = "range", False
        self._end_mode = "end"
        self._set_range(start, end)
        self._update_alarm_summary()

    def _mini_selected(self, start, end):
        self._mini_preview(start, end)
        self._touched.add("time")
        self._remember_manual_time()
        self._mini_time_selected = True
        self._mini_origin = None
        self._apply_default_reminder()
        self._update_alarm_summary()
        self.title_edit.setFocus()

    def _mini_cancel(self):
        if self._mini_origin is not None:
            start, end, self._time_mode, self._all_day, self._end_mode = self._mini_origin
            self._mini_origin = None
            self._set_range(start, end)
            self._update_alarm_summary()

    def _position(self) -> None:
        bounds = getattr(self, "_standalone_bounds", None)
        if bounds is None:
            return
        preferred = self._manual_position or QPoint(
            bounds.left() + (bounds.width() - self.width()) // 2,
            bounds.top() + (bounds.height() - self.height()) // 2,
        )
        self.move(
            max(bounds.left(), min(preferred.x(), bounds.right() - self.width() + 1)),
            max(bounds.top(), min(preferred.y(), bounds.bottom() - self.height() + 1)),
        )

    def _drag_header_event(self, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            return True
        if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
            target = event.globalPosition().toPoint()
            screen = QGuiApplication.screenAt(target) or self.screen()
            if screen is not None:
                self._standalone_bounds = screen.availableGeometry()
            self._manual_position = target - self._drag_offset
            self._position()
            self._manual_position = self.pos()
            return True
        if event.type() == QEvent.Type.MouseButtonRelease and self._drag_offset is not None:
            self._drag_offset = None
            return True
        return False

    def eventFilter(self, watched, event) -> bool:
        if watched is self.heading and self._drag_header_event(event):
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        if (
            event.position().y() < self.title_edit.mapTo(self, QPoint()).y()
            and self._drag_header_event(event)
        ):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_header_event(event):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_header_event(event):
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _day_label(value: datetime) -> str:
    return f"{value.month}/{value.day} ({'월화수목금토일'[value.weekday()]})"


def _category_dot(color: str) -> QIcon:
    """분류 칩 앞의 색 점. 아이콘 크기는 칩 쪽 iconSize로 정한다."""
    dot = QPixmap(16, 16)
    dot.fill(Qt.GlobalColor.transparent)
    painter = QPainter(dot)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(2, 2, 12, 12)
    painter.end()
    return QIcon(dot)


def _scaled_popover_width(scale: float) -> int:
    """배율이 커질 때 글자와 내부 여백이 1~4px 밖으로 밀리지 않을 폭."""
    return min(POPOVER_MAX_WIDTH, round(POPOVER_WIDTH + max(0, scale - 1) * 144))


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
    chip = QPushButton(f"+ {name}")
    chip.setObjectName("popoverAddChip")
    chip.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    chip.setMinimumWidth(60)
    chip.setCheckable(True)
    chip.setAccessibleName(accessible_name)
    chip.toggled.connect(
        lambda _checked, button=chip, label=name: button.setText(f"+ {label}")
    )
    return chip


def _schedule_icon(kind: str, size: int = 18) -> QIcon:
    """작은 단색 선 아이콘을 그려 OS 이모지 글꼴에 의존하지 않는다."""
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 18, size / 18)
    painter.setPen(QPen(QColor("#4263eb"), 1.5))
    if kind == "calendar":
        painter.drawRoundedRect(2, 3, 14, 13, 2, 2)
        painter.drawLine(2, 7, 16, 7)
        painter.drawLine(6, 1, 6, 5)
        painter.drawLine(12, 1, 12, 5)
    elif kind == "bell":
        shape = QPainterPath()
        shape.moveTo(4, 13)
        shape.lineTo(5.5, 11)
        shape.lineTo(5.5, 7)
        shape.cubicTo(5.5, 2, 12.5, 2, 12.5, 7)
        shape.lineTo(12.5, 11)
        shape.lineTo(14, 13)
        shape.closeSubpath()
        painter.drawPath(shape)
        painter.drawArc(7, 12, 4, 4, 180 * 16, 180 * 16)
    elif kind == "clock":
        painter.drawEllipse(2, 2, 14, 14)
        painter.drawLine(9, 5, 9, 9)
        painter.drawLine(9, 9, 12, 11)
    elif kind == "tag":
        shape = QPainterPath()
        shape.moveTo(3, 4)
        shape.lineTo(9, 2)
        shape.lineTo(16, 9)
        shape.lineTo(9, 16)
        shape.lineTo(2, 9)
        shape.closeSubpath()
        painter.drawPath(shape)
        painter.drawEllipse(6, 5, 2, 2)
    painter.end()
    return QIcon(canvas)


def _duration_text(span: timedelta) -> str:
    minutes = max(1, int(span.total_seconds() // 60))
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}시간 {remainder}분"
    if hours:
        return f"{hours}시간"
    return f"{remainder}분"
