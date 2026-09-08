from datetime import datetime, timedelta
import json

from html import escape

from PyQt6.QtCore import QEvent, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLayout, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QSpinBox,
    QRadioButton, QStyle, QStyleOptionSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from hotkey_builder import HotkeyBuilder
from hotkey_parser import parse_hotkey
from ui_polish import apply_numeric_font, polish_button

from .datetime_input import DateTimeInput
from .deadline import deadline_badge_text
from .editor_shortcut_settings import (
    DEFAULT_ALWAYS_TOP, DEFAULT_POSTIT, SETTING_ALWAYS_TOP, SETTING_POSTIT,
    EditorShortcutSettingsDialog,
)
from .note_shortcuts import TIME_SHORTCUTS, bind_time_shortcuts, modifier_setting, shortcut_text
from .recurrence import RecurrenceRule
from .recurrence_controls import RecurrenceControls
from .rich_memo_edit import RichMemoTextEdit
from .rich_text import plain_text_from_content
from .sqlite_store import DATETIME_FMT
from .find_bar import MemoFindBar
from .text_format_toolbar import TextFormatToolbar


SAVED_STATUS_TEXTS = (
    "● 자동 저장 켜짐", "● 수동 저장 · Ctrl+S", "● 00:00 자동 저장됨", "● 저장 실패",
)

COLORS = {
    "vanilla": ("바닐라", "#fff3bf"), "mint": ("민트", "#dcfce7"),
    "sky": ("하늘", "#dbeafe"), "peach": ("복숭아", "#fee2e2"),
    "lavender": ("라벤더", "#ede9fe"),
}


class MemoEditor(QWidget):
    REMINDER_COLLAPSED_SETTING = "memo_reminder_collapsed"
    AUTO_SAVE_SETTING = "memo_auto_save_enabled"
    save_requested = pyqtSignal(dict)
    delete_requested = pyqtSignal()
    reminder_save_requested = pyqtSignal(dict)
    reminder_clear_requested = pyqtSignal(object)
    deadline_requested = pyqtSignal()
    monthly_requested = pyqtSignal()
    note_open_requested = pyqtSignal(int)
    page_created = pyqtSignal(int)
    page_removed = pyqtSignal(int)
    fullscreen_requested = pyqtSignal()
    sidebar_requested = pyqtSignal()

    # 목록을 숨겨 넓어져도 보조 줄까지 늘일 이유는 없다.  이 폭에서 멈추고
    # 왼쪽에 붙는다.  본문만 남은 자리를 다 쓴다.
    SIDE_ROW_WIDTH = 720
    # 왼쪽 칸이 이보다 좁아지면 알림 요약이 네 줄로 접혀 카드가 흉해진다.
    BOTTOM_LEFT_WIDTH = 440
    # 왼쪽 440 + 오른쪽 최소 413(서식 도구) + 여백.  그보다 좁으면 한 칸으로 쌓는다.
    TWO_COLUMN_WIDTH = 900
    # 두 칸일 때 오른쪽에 실제로 남는 폭.  바깥 여백 16 + 칸 사이 10.
    BOTTOM_GUTTER = 26
    # 색상·휴지통 줄이 한 줄로 들어가는 폭.  '지금 저장'은 자동 저장일 때
    # 숨으므로 위젯이 말하는 최소값(615)보다 실제로는 조금 덜 든다.
    ACTIONS_ROW_WIDTH = 605

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._shutdown = False
        self.note_id: int | None = None
        self.editing_reminder_id: int | None = None
        self.color = "vanilla"
        self.color_buttons = {}
        self._loading = True
        self._quick_time_active = False
        self._setting_quick_time = False
        self.auto_save_enabled = self.store.setting(self.AUTO_SAVE_SETTING, "true").lower() == "true"
        self.store.purge_expired_memo_drafts(7)
        self._manual_save_pending = False
        self._build_ui()
        self.manual_save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.manual_save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.manual_save_shortcut.activated.connect(self._manual_save)
        # 긴 메모의 토글을 한 번에 접거나 편다.
        self.fold_all_shortcut = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        self.fold_all_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.fold_all_shortcut.activated.connect(self._toggle_all_folds)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self._deferred_save)
        self.title_edit.textChanged.connect(self._queue_save)
        self.content_edit.textChanged.connect(self._queue_save)
        self.content_edit.page_created.connect(self.page_created)
        self.content_edit.page_open_requested.connect(self.note_open_requested)
        self.content_edit.page_removed.connect(self.page_removed)
        for checkbox in (self.always_top_check, self.postit_check, self.lock_check, self.hotkey_enabled):
            checkbox.toggled.connect(self._queue_save)
        self.opacity_combo.currentIndexChanged.connect(self._queue_save)
        self.hotkey_action_combo.currentIndexChanged.connect(self._queue_save)
        self.hotkey_edit.first_modifier.currentIndexChanged.connect(self._queue_save)
        self.hotkey_edit.second_modifier.currentIndexChanged.connect(self._queue_save)
        self.hotkey_edit.key_edit.textChanged.connect(self._queue_save)
        self.reload_shortcuts()
        self.deadline_timer = QTimer(self)
        self.deadline_timer.setInterval(60_000)
        self.deadline_timer.timeout.connect(self._refresh_deadline_badge)
        self.deadline_timer.start()
        self.set_note(None)

    def _build_ui(self) -> None:
        self.setObjectName("memoEditorPane")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        self._root = root
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)
        # 몇 층 안에 들어와 있는지 한 줄로 보여 준다.  눌러서 위로 올라간다.
        self.breadcrumb = QLabel()
        self.breadcrumb.setObjectName("memoBreadcrumb")
        self.breadcrumb.setAccessibleName("메모 위치")
        self.breadcrumb.setTextFormat(Qt.TextFormat.RichText)
        self.breadcrumb.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.breadcrumb.linkActivated.connect(self._breadcrumb_clicked)
        self.breadcrumb.hide()
        root.addWidget(self.breadcrumb)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(QLabel("제목"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("메모 제목")
        title_row.addWidget(self.title_edit, 1)
        self.deadline_badge = QLabel()
        self.deadline_badge.setObjectName("deadlineBadge")
        self.deadline_badge.setAccessibleName("D-Day 남은 시간")
        self.deadline_badge.hide()
        title_row.addWidget(self.deadline_badge)
        self.deadline_button = QPushButton("D-Day")
        self.deadline_button.setObjectName("compactUtilityButton")
        self.deadline_button.setAccessibleName("D-Day 설정")
        self.deadline_button.clicked.connect(self.deadline_requested)
        self.monthly_button = QPushButton("매달 반복")
        self.monthly_button.setObjectName("compactUtilityButton")
        self.monthly_button.setAccessibleName("매달 반복 설정")
        self.monthly_button.setToolTip("정한 날마다 이 메모를 포스트잇으로 띄웁니다.")
        self.monthly_button.clicked.connect(self.monthly_requested)
        # 편집만 크게 보기.  제목 줄 오른쪽 끝에 둔다.
        self.fullscreen_button = QPushButton("⛶")
        self.fullscreen_button.setObjectName("compactUtilityButton")
        self.fullscreen_button.setAccessibleName("편집 구역 크게 보기")
        self.fullscreen_button.setToolTip("편집 구역만 크게 봅니다 (F11)")
        self.fullscreen_button.setFixedWidth(34)
        self.fullscreen_button.clicked.connect(self.fullscreen_requested)
        # 메모 목록을 접었다 편다.
        self.sidebar_button = QPushButton("◀")
        self.sidebar_button.setObjectName("compactUtilityButton")
        self.sidebar_button.setAccessibleName("메모 목록 접기")
        self.sidebar_button.setToolTip("메모 목록을 접습니다")
        self.sidebar_button.setFixedWidth(30)
        self.sidebar_button.clicked.connect(self.sidebar_requested)
        title_row.addWidget(self.sidebar_button)
        title_row.addWidget(self.fullscreen_button)
        root.addLayout(title_row)
        self.content_edit = RichMemoTextEdit(self.store)
        self.content_edit.setObjectName("memoBodyEditor")
        self.content_edit.setPlaceholderText("메모 내용을 입력하세요")
        self.content_edit.setMinimumHeight(180)
        self.content_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.format_toolbar = TextFormatToolbar(self.content_edit, self.store)
        self.format_toolbar.layout().setSpacing(4)
        root.addWidget(self.format_toolbar)
        root.addWidget(self.content_edit, 1)
        # 본문 찾기 줄.  Ctrl+F 로 열리고 평소에는 자리도 차지하지 않는다.
        self.find_bar = MemoFindBar(self.content_edit, self)
        root.addWidget(self.find_bar)
        self.find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.find_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.find_shortcut.activated.connect(self.find_bar.open_bar)

        # 본문 아래 한 줄을 통째로 묶어 둔다.  목록을 접어 넓어졌을 때 이
        # 줄까지 늘어나면 서식 단추와 옵션이 화면 양 끝으로 갈라진다.
        self.below_host = QWidget()
        below_body = QHBoxLayout(self.below_host)
        below_body.setContentsMargins(0, 0, 0, 0)
        below_body.setSpacing(8)
        self.preset_host = QWidget()
        self.preset_layout = QHBoxLayout(self.preset_host)
        self.preset_layout.setContentsMargins(0, 0, 0, 0)
        self.preset_layout.setSpacing(6)
        self.format_toolbar.move_presets_to(self.preset_layout)
        below_body.addWidget(self.preset_host)
        below_body.addStretch(1)
        self.option_host = QWidget()
        self.option_layout = QGridLayout(self.option_host)
        self.option_layout.setContentsMargins(0, 0, 0, 0)
        self.option_layout.setHorizontalSpacing(6)
        self.option_layout.setVerticalSpacing(4)
        self.always_top_check = QCheckBox("항상 위")
        self.postit_check = QCheckBox("포스트잇 모드")
        self.saved_status = QLabel("● 자동 저장됨")
        self.saved_status.setObjectName("memoStatus")
        # The option row may shrink below its hint, which used to clip the text
        # into "자동 저장 켜".  Reserve room for the longest wording instead.
        self.saved_status.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        metrics = self.saved_status.fontMetrics()
        self.saved_status.setMinimumWidth(max(
            metrics.horizontalAdvance(text) for text in SAVED_STATUS_TEXTS
        ) + 10)
        self.shortcut_settings_button = QPushButton("단축키")
        self.shortcut_settings_button.clicked.connect(self._open_shortcut_settings)
        self.format_toolbar.set_auxiliary_button(self.shortcut_settings_button)
        below_body.addWidget(self.option_host)

        reminder = QFrame()
        reminder.setObjectName("memoSectionCard")
        reminder_layout = QVBoxLayout(reminder)
        reminder_layout.setContentsMargins(8, 6, 8, 6)
        reminder_layout.setSpacing(4)
        reminder_header = QHBoxLayout()
        reminder_header.setSpacing(8)
        self.reminder_toggle = QToolButton()
        self.reminder_toggle.setObjectName("memoReminderToggle")
        self.reminder_toggle.setText("알림 예약")
        self.reminder_toggle.setCheckable(True)
        self.reminder_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.reminder_toggle.setAccessibleName("알림 예약 펼치기")
        reminder_header.addWidget(self.reminder_toggle)
        self.datetime_input = DateTimeInput(show_quick=False, show_hint=False, show_summary=False)
        self.datetime_input.summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.datetime_input.summary.setWordWrap(True)
        self.datetime_input.summary.show()
        reminder_header.addWidget(self.datetime_input.summary, 1)
        reminder_header.addWidget(self.deadline_button)
        reminder_header.addWidget(self.monthly_button)
        reminder_layout.addLayout(reminder_header)
        self.reminder_details = QWidget()
        reminder_details_layout = QVBoxLayout(self.reminder_details)
        reminder_details_layout.setContentsMargins(0, 0, 0, 0)
        reminder_details_layout.setSpacing(4)
        self.due_edit = self.datetime_input
        reminder_details_layout.addWidget(self.datetime_input)
        self.recurrence = RecurrenceControls(self.datetime_input)
        self.recurrence.changed.connect(self._update_reminder_button)
        reminder_details_layout.addWidget(self.recurrence)
        quick = QHBoxLayout()
        quick.setSpacing(4)
        self.quick_buttons = {}
        shortcuts = list(TIME_SHORTCUTS)
        for index, (key, label, minutes) in enumerate(shortcuts):
            button = QPushButton()
            button.setObjectName("quickReminderButton")
            button.setMinimumHeight(34)
            button.setMaximumHeight(38)
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, value=minutes: self._set_quick_time(value))
            quick.addWidget(button)
            if index < len(shortcuts) - 1:
                quick.addStretch(1)
            self.quick_buttons[minutes] = button
        reminder_details_layout.addLayout(quick)
        reminder_actions = QHBoxLayout()
        reminder_actions.setSpacing(6)
        self.reminder_save_button = QPushButton("알림 저장")
        self.reminder_save_button.setObjectName("primaryButton")
        self.reminder_clear_button = QPushButton("알림 해제")
        self.clear_input_button = QPushButton("초기화")
        for button in (self.reminder_save_button, self.reminder_clear_button, self.clear_input_button):
            button.setMinimumHeight(30)
            polish_button(button)
        reminder_actions.addWidget(self.reminder_save_button, 1)
        reminder_actions.addWidget(self.reminder_clear_button, 1)
        reminder_actions.addWidget(self.clear_input_button, 1)
        reminder_details_layout.addLayout(reminder_actions)
        self.reminder_save_hint = QLabel("Ctrl+Enter로 알림 저장")
        self.reminder_save_hint.setObjectName("secondaryText")
        self.reminder_save_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        reminder_details_layout.addWidget(self.reminder_save_hint)
        self.reminder_save_button.clicked.connect(self._save_reminder)
        self.reminder_clear_button.clicked.connect(lambda: self.reminder_clear_requested.emit(self.editing_reminder_id))
        self.clear_input_button.clicked.connect(self._reset_reminder_input)
        self.datetime_input.changed.connect(self._on_datetime_changed)
        self.reminder_save_shortcut = QShortcut(QKeySequence("Ctrl+Enter"), self.reminder_details)
        self.reminder_save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.reminder_save_shortcut.activated.connect(self._save_reminder)
        reminder_layout.addWidget(self.reminder_details)
        self.reminder_toggle.toggled.connect(self._set_reminder_expanded)
        expanded = self.store.setting(self.REMINDER_COLLAPSED_SETTING, "true").lower() != "true"
        self.reminder_toggle.setChecked(expanded)
        self._set_reminder_expanded(expanded)
        self.reminder_card = reminder

        hotkey_card = QFrame()
        hotkey_card.setObjectName("memoSectionCard")
        hotkey_layout = QVBoxLayout(hotkey_card)
        hotkey_layout.setContentsMargins(8, 6, 8, 6)
        hotkey_layout.setSpacing(3)
        self.hotkey_toggle = QToolButton()
        self.hotkey_toggle.setObjectName("memoHotkeyToggle")
        self.hotkey_toggle.setText("메모 전역 단축키")
        self.hotkey_toggle.setCheckable(True)
        self.hotkey_toggle.setChecked(False)
        self.hotkey_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.hotkey_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.hotkey_toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.hotkey_toggle.setAccessibleName("메모 전역 단축키 펼치기")
        hotkey_layout.addWidget(self.hotkey_toggle)
        self.hotkey_body = QWidget()
        hotkey_body_layout = QGridLayout(self.hotkey_body)
        hotkey_body_layout.setContentsMargins(0, 3, 0, 0)
        hotkey_body_layout.setHorizontalSpacing(6)
        hotkey_body_layout.setVerticalSpacing(3)
        self.hotkey_enabled = QCheckBox("사용")
        self.hotkey_edit = HotkeyBuilder()
        self.hotkey_action_combo = QComboBox(self.hotkey_body)
        self.hotkey_action_combo.addItem("메모 열기", "open")
        self.hotkey_action_combo.addItem("포스트잇 표시·숨김", "postit")
        self.hotkey_action_combo.hide()
        self.hotkey_action_group = QButtonGroup(self.hotkey_body)
        self.hotkey_action_group.setExclusive(True)
        self.hotkey_action_buttons: dict[str, QRadioButton] = {}
        hotkey_action_row = QHBoxLayout()
        hotkey_action_row.setSpacing(10)
        for label, value in (("메모 열기", "open"), ("포스트잇 표시·숨김", "postit")):
            button = QRadioButton(label)
            button.setAccessibleName(f"메모 전역 단축키 동작 {label}")
            button.toggled.connect(
                lambda checked, action=value: self._select_hotkey_action(action) if checked else None
            )
            self.hotkey_action_group.addButton(button)
            self.hotkey_action_buttons[value] = button
            hotkey_action_row.addWidget(button)
        hotkey_action_row.addStretch(1)
        hotkey_body_layout.addWidget(self.hotkey_enabled, 0, 0)
        hotkey_body_layout.addLayout(hotkey_action_row, 0, 1)
        hotkey_body_layout.addWidget(self.hotkey_edit, 1, 0, 1, 2)
        hotkey_layout.addWidget(self.hotkey_body)
        self.hotkey_body.hide()
        self.hotkey_toggle.toggled.connect(self._set_hotkey_expanded)
        self.hotkey_enabled.toggled.connect(self.hotkey_edit.setEnabled)
        self.hotkey_enabled.toggled.connect(self._set_hotkey_action_enabled)
        self.hotkey_action_combo.currentIndexChanged.connect(self._sync_hotkey_action_buttons)
        self._sync_hotkey_action_buttons()
        self.hotkey_card = hotkey_card

        self.action_feedback = QLabel()
        self.action_feedback.setObjectName("memoActionFeedback")
        self.action_feedback.setWordWrap(True)
        self.action_feedback.hide()
        self.action_feedback_timer = QTimer(self)
        self.action_feedback_timer.setSingleShot(True)
        self.action_feedback_timer.timeout.connect(self.action_feedback.hide)

        # 맨 아래 줄도 한 덩어리로 묶어, 넓어졌을 때 왼쪽에 함께 붙게 한다.
        self.actions_host = QWidget()
        self.actions_layout = QGridLayout(self.actions_host)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setHorizontalSpacing(6)
        self.actions_layout.setVerticalSpacing(4)
        self.lock_check = QCheckBox("입력 잠금")
        for key, (label, color) in COLORS.items():
            button = QPushButton()
            button.setToolTip(label)
            button.setAccessibleName(f"포스트잇 색상 {label}")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(30, 30)
            button.setStyleSheet(f"background:{color}; border:2px solid #cbd5e1; border-radius:15px;")
            button.clicked.connect(lambda _checked=False, value=key: self.set_color(value))
            self.color_buttons[key] = button
        self.opacity_combo = QComboBox()
        self.opacity_combo.setAccessibleName("포스트잇 배경 투명도")
        self.opacity_combo.setToolTip("포스트잇 배경 투명도")
        for value in (0, 30, 50, 70, 100):
            self.opacity_combo.addItem(f"투명 {value}%", value)
        apply_numeric_font(self.opacity_combo)
        self.manual_save_button = QPushButton("지금 저장")
        self.manual_save_button.setToolTip("메모는 자동 저장되며, 이 버튼은 즉시 저장합니다.")
        self.manual_save_button.setObjectName("primaryButton")
        self.delete_button = QPushButton("휴지통으로 이동")
        self.delete_button.setObjectName("dangerButton")
        for button in (self.manual_save_button, self.delete_button):
            button.setMinimumHeight(30)
            polish_button(button)
        self.manual_save_button.clicked.connect(self._manual_save)
        self.delete_button.clicked.connect(self.delete_requested)

        # 보조 줄들을 담는 그릇.  폭이 넉넉하면 두 칸으로 갈라진다.
        self.bottom_host = QWidget()
        bottom_columns = QHBoxLayout(self.bottom_host)
        bottom_columns.setContentsMargins(0, 0, 0, 0)
        bottom_columns.setSpacing(10)
        self.bottom_left = QWidget()
        self.bottom_left.setMinimumWidth(self.BOTTOM_LEFT_WIDTH)
        self.bottom_left_layout = QVBoxLayout(self.bottom_left)
        self.bottom_left_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_left_layout.setSpacing(4)
        self.bottom_right = QWidget()
        self.bottom_right_layout = QVBoxLayout(self.bottom_right)
        self.bottom_right_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_right_layout.setSpacing(4)
        self.bottom_right.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        bottom_columns.addWidget(self.bottom_left, 1)
        bottom_columns.addWidget(self.bottom_right)
        root.addWidget(self.bottom_host)
        self._two_column_bottom: bool | None = None
        self._apply_bottom_layout(self.width())
        # 넓어져도 늘리지 않을 줄들.  본문만 남은 자리를 다 쓰고, 이 줄들은
        # 읽기 좋은 폭에서 멈춰 왼쪽에 붙는다.
        self.side_rows = (reminder, hotkey_card, self.below_host, self.actions_host)
        self._responsive_compact: bool | None = None
        self._apply_responsive_layout(self.width())
        self._compact_controls()
        self._sync_save_mode_ui()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "actions_layout"):
            self._apply_responsive_layout(event.size().width())
            self._apply_bottom_layout(event.size().width())

    @staticmethod
    def _drain(layout) -> None:
        """칸을 비운다.  위젯은 곧바로 다른 칸에 다시 담기므로 부모는 두 둔다."""
        while layout.count():
            layout.takeAt(0)

    def _apply_bottom_layout(self, width: int) -> None:
        """폭이 넉넉하면 보조 줄을 두 칸으로 갈라 본문에 자리를 내준다.

        넓을 때 왼쪽은 알림 예약과 전역 단축키, 오른쪽은 서식 도구와 그 아래
        서식 1~3 · 색상 줄이다.  좁을 때는 예전처럼 위아래로 쌓는다.  맨 아래
        색상 줄만 해도 615px 이 필요해, 그보다 좁으면 두 칸이 들어가지 않는다.
        """
        two = width >= self.TWO_COLUMN_WIDTH
        if self._two_column_bottom == two:
            return
        self._two_column_bottom = two
        self._root.removeWidget(self.format_toolbar)
        self._drain(self.bottom_left_layout)
        self._drain(self.bottom_right_layout)
        if two:
            for widget in (self.reminder_card, self.hotkey_card, self.action_feedback):
                self.bottom_left_layout.addWidget(widget)
            self.bottom_left_layout.addStretch(1)
            for widget in (self.format_toolbar, self.below_host, self.actions_host):
                self.bottom_right_layout.addWidget(widget)
            self.bottom_right_layout.addStretch(1)
        else:
            self._root.insertWidget(2, self.format_toolbar)
            for widget in (
                self.below_host, self.reminder_card, self.hotkey_card,
                self.action_feedback, self.actions_host,
            ):
                self.bottom_left_layout.addWidget(widget)
        self.bottom_right.setVisible(two)
        self.format_toolbar.show()

    def _right_column_width(self, width: int) -> int:
        """두 칸일 때 서식 도구와 색상 줄이 실제로 쓸 수 있는 폭."""
        if width < self.TWO_COLUMN_WIDTH:
            return width
        return width - self.BOTTOM_GUTTER - self.BOTTOM_LEFT_WIDTH

    def _apply_responsive_layout(self, width: int) -> None:
        if width < self.TWO_COLUMN_WIDTH:
            compact = width < 620
        else:
            compact = self._right_column_width(width) < self.ACTIONS_ROW_WIDTH
        if self._responsive_compact == compact:
            return
        self._responsive_compact = compact

        # The save status used to share the option row and pushed 포스트잇 모드
        # off the edge; it now rides with the actions instead of taking a
        # second line away from the editor.
        option_widgets = (self.always_top_check, self.postit_check)
        for widget in option_widgets:
            self.option_layout.removeWidget(widget)
        self.option_layout.removeWidget(self.saved_status)
        for column in range(10):
            self.option_layout.setColumnStretch(column, 0)
        self.option_layout.addWidget(self.always_top_check, 0, 0)
        self.option_layout.addWidget(self.postit_check, 0, 1)
        self.option_layout.setColumnStretch(2, 1)
        self.option_host.setSizePolicy(
            QSizePolicy.Policy.Preferred if compact else QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )

        action_widgets = [
            self.lock_check, *self.color_buttons.values(), self.opacity_combo,
            self.manual_save_button, self.delete_button, self.saved_status,
        ]
        for widget in action_widgets:
            self.actions_layout.removeWidget(widget)
        for column in range(12):
            self.actions_layout.setColumnStretch(column, 0)
        self.actions_layout.addWidget(self.lock_check, 0, 0)
        for column, button in enumerate(self.color_buttons.values(), start=1):
            self.actions_layout.addWidget(button, 0, column)
        self.actions_layout.addWidget(self.opacity_combo, 0, 6)
        if compact:
            self.actions_layout.addWidget(self.manual_save_button, 1, 5)
            self.actions_layout.addWidget(self.delete_button, 1, 6)
            # Same row as 휴지통, at its left — directly under 입력 잠금.
            self.actions_layout.addWidget(
                self.saved_status, 1, 0, 1, 4, Qt.AlignmentFlag.AlignLeft
            )
        else:
            self.actions_layout.setColumnStretch(7, 1)
            self.actions_layout.addWidget(self.manual_save_button, 0, 8)
            self.actions_layout.addWidget(self.delete_button, 0, 9)
            self.actions_layout.addWidget(
                self.saved_status, 0, 7, Qt.AlignmentFlag.AlignLeft
            )
        self.updateGeometry()

    def _compact_controls(self) -> None:
        """Reduce only editor control chrome while keeping every action available."""
        for button in self.findChildren(QAbstractButton):
            if button in self.color_buttons.values() or button.objectName() == "quickReminderButton":
                continue
            button.setMinimumHeight(28)
            button.setMaximumHeight(32)
        for field in self.findChildren((QLineEdit, QComboBox, QAbstractSpinBox)):
            field.setMaximumHeight(34)
        self._wheel_locked_controls = []
        for control in self.findChildren((QComboBox, QAbstractSpinBox)):
            control.installEventFilter(self)
            control.setMouseTracking(True)
            self._wheel_locked_controls.append(control)
            line_edit = control.lineEdit() if hasattr(control, "lineEdit") else None
            if line_edit is not None:
                line_edit.installEventFilter(self)
                line_edit.setMouseTracking(True)
                self._wheel_locked_controls.append(line_edit)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and watched in getattr(self, "_wheel_locked_controls", ()):
            event.ignore()
            return True
        if event.type() == QEvent.Type.MouseMove and isinstance(watched, QAbstractSpinBox):
            option = QStyleOptionSpinBox()
            watched.initStyleOption(option)
            subcontrol = watched.style().hitTestComplexControl(
                QStyle.ComplexControl.CC_SpinBox, option, event.position().toPoint(), watched,
            )
            cursor = Qt.CursorShape.ArrowCursor if subcontrol in (
                QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown,
            ) else Qt.CursorShape.IBeamCursor
            watched.setCursor(cursor)
        return super().eventFilter(watched, event)

    def _set_hotkey_expanded(self, expanded: bool) -> None:
        self.hotkey_body.setVisible(expanded)
        self.hotkey_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.hotkey_toggle.setAccessibleName(f"메모 전역 단축키 {'접기' if expanded else '펼치기'}")

    def _select_hotkey_action(self, action: str) -> None:
        index = self.hotkey_action_combo.findData(action)
        if index >= 0 and index != self.hotkey_action_combo.currentIndex():
            self.hotkey_action_combo.setCurrentIndex(index)

    def _sync_hotkey_action_buttons(self, *_args) -> None:
        current = str(self.hotkey_action_combo.currentData() or "open")
        for value, button in self.hotkey_action_buttons.items():
            button.blockSignals(True)
            button.setChecked(value == current)
            button.blockSignals(False)

    def _set_hotkey_action_enabled(self, enabled: bool) -> None:
        self.hotkey_action_combo.setEnabled(enabled)
        for button in self.hotkey_action_buttons.values():
            button.setEnabled(enabled)

    def _toggle_all_folds(self) -> None:
        if self.content_edit.toggle_all_folds():
            self.content_edit.setFocus()

    def set_wide_body(self, on: bool) -> None:
        """목록을 접어 넓어졌을 때 어디에 자리를 줄지 정한다.

        본문만 넓히고, 알림·단축키·서식 줄은 읽기 좋은 폭에서 멈춰 왼쪽에
        붙인다.  가로로 늘어나 봐야 빈 자리만 생기는 줄들이다.
        """
        for widget in self.side_rows:
            widget.setMaximumWidth(self.SIDE_ROW_WIDTH if on else 16777215)
        self.sidebar_button.setText("▶" if on else "◀")
        self.sidebar_button.setToolTip(
            "메모 목록을 다시 폅니다" if on else "메모 목록을 접습니다"
        )

    def set_fullscreen(self, on: bool) -> None:
        """크게 보는 동안에는 단추 글자만 바꾼다.  기능은 그대로다."""
        self.fullscreen_button.setText("⛶" if not on else "⤢")
        self.fullscreen_button.setToolTip(
            "원래 화면으로 (F11)" if on else "편집 구역만 크게 봅니다 (F11)"
        )

    def _breadcrumb_clicked(self, href: str) -> None:
        if str(href).isdigit():
            self.note_open_requested.emit(int(href))

    def refresh_breadcrumb(self) -> None:
        """이 메모가 어느 메모 안에 들어 있는지 보여 준다."""
        chain = []
        if self.store is not None and self.note_id is not None:
            chain = self.store.note_path(self.note_id)
        if len(chain) < 2:
            # 맨 위층 메모는 보여 줄 위치가 없다.
            self.breadcrumb.hide()
            self.breadcrumb.clear()
            return
        parts = []
        for row in chain[:-1]:
            title = escape(str(row["title"] or "제목 없음"))
            parts.append(f'<a href="{int(row["id"])}">{title}</a>')
        parts.append(escape(str(chain[-1]["title"] or "제목 없음")))
        self.breadcrumb.setText("  ›  ".join(parts))
        self.breadcrumb.show()

    def set_note(self, note) -> None:
        # 다른 메모로 넘어가기 전에, 치던 페이지 이름을 갈무리한다.
        self.content_edit.sync_page_titles()
        self._loading = True
        self.save_timer.stop() if hasattr(self, "save_timer") else None
        enabled = note is not None
        self.setEnabled(True)
        self.note_id = int(note["id"]) if enabled else None
        self._deadline_note = note
        self.content_edit.set_note_context(self.note_id)
        self.title_edit.setText(str(note["title"]) if enabled else "")
        self.content_edit.set_content(str(note["content"]) if enabled else "")
        # 하위 메모의 제목을 고치고 돌아왔을 수 있다.  본문의 페이지 줄을 지금
        # 제목으로 맞춘다.  아직 저장하지 않은 본문이어서 set_content 가 그냥
        # 지나갔을 때도 맞춰야 하므로 따로 부른다.
        self.content_edit._refresh_page_links()
        self.refresh_breadcrumb()
        self.postit_check.setChecked(bool(note["postit"]) if enabled else False)
        self.always_top_check.setChecked(bool(note["always_on_top"]) if enabled else True)
        self.lock_check.setChecked(bool(note["input_locked"]) if enabled else False)
        note_hotkey = str(note["hotkey"] or "") if enabled else ""
        self.hotkey_enabled.setChecked(bool(note_hotkey))
        self.hotkey_edit.setText(note_hotkey or "Ctrl+Alt+1")
        self.hotkey_edit.setEnabled(enabled and bool(note_hotkey))
        self.hotkey_action_combo.setCurrentIndex(
            max(0, self.hotkey_action_combo.findData(str(note["hotkey_action"]))) if enabled else 0
        )
        self._set_hotkey_action_enabled(enabled and bool(note_hotkey))
        self.set_color(str(note["color"]) if enabled else "vanilla")
        index = self.opacity_combo.findData(int(note["background_transparency"]) if enabled else 0)
        self.opacity_combo.setCurrentIndex(max(0, index))
        due = str(note["reminder_due_at"] or "") if enabled else ""
        self.datetime_input.set_datetime(
            datetime.strptime(due, DATETIME_FMT) if due else datetime.now() + timedelta(minutes=10)
        )
        self.datetime_input.set_scheduled(bool(due))
        self.editing_reminder_id = None
        self.recurrence.set_rule(RecurrenceRule())
        self.reminder_save_button.setText("알림 저장")
        self.saved_status.setText("● 자동 저장됨" if enabled else "● 입력 대기")
        self.delete_button.setEnabled(enabled)
        self._loading = False
        self._sync_save_mode_ui()
        if enabled and not due:
            self.reminder_toggle.setChecked(False)
        if enabled and not self.auto_save_enabled:
            self._restore_draft()
        self._update_reminder_button()
        self._refresh_deadline_badge()

    def bind_note_id(self, note_id: int, default_title: str = "새 메모") -> None:
        """Bind a just-created draft without reloading its document or cursor."""
        self.note_id = int(note_id)
        self.content_edit.bind_current_document(self.note_id)
        self.delete_button.setEnabled(True)
        if not self.title_edit.text().strip():
            blocked = self.title_edit.blockSignals(True)
            self.title_edit.setText(default_title)
            self.title_edit.blockSignals(blocked)

    def has_meaningful_content(self) -> bool:
        return bool(self.title_edit.text().strip() or self.content_edit.toPlainText().strip())

    def set_reminder(self, reminder) -> None:
        if reminder is None:
            self.editing_reminder_id = None
            self.recurrence.set_rule(RecurrenceRule())
            self.reminder_save_button.setText("알림 저장")
            self.datetime_input.set_scheduled(False)
            return
        self.editing_reminder_id = int(reminder["id"])
        self.datetime_input.set_datetime(datetime.strptime(str(reminder["due_at"]), DATETIME_FMT))
        self.datetime_input.set_scheduled(True)
        self.recurrence.set_rule(
            self.store.recurrence_rule(reminder), int(reminder["generated_count"] or 1),
        )
        self.reminder_save_button.setText("알림 변경")

    def _queue_save(self) -> None:
        if self._shutdown or self._loading:
            return
        self.saved_status.setText("저장 중…" if self.auto_save_enabled else "초안 저장 중…")
        self.save_timer.start()

    def _deferred_save(self) -> None:
        if self.auto_save_enabled:
            self._auto_save()
        else:
            self._save_draft()

    def _auto_save(self) -> None:
        if not self._shutdown:
            self.save_requested.emit(self.values())

    def _draft_key(self) -> str:
        return f"memo_draft_{int(self.note_id)}" if self.note_id is not None else ""

    def _save_draft(self) -> None:
        key = self._draft_key()
        if not key or self._shutdown:
            return
        try:
            values = self.values()
        except Exception:
            values = {
                "title": self.title_edit.text(), "content": self.content_edit.content(),
                "postit": self.postit_check.isChecked(), "always_on_top": self.always_top_check.isChecked(),
                "input_locked": self.lock_check.isChecked(), "color": self.color,
                "background_transparency": int(self.opacity_combo.currentData()),
                "hotkey": "", "hotkey_action": self.hotkey_action_combo.currentData(),
            }
        payload = {"saved_at": datetime.now().strftime(DATETIME_FMT), "values": values}
        self.store.set_setting(key, json.dumps(payload, ensure_ascii=False))
        self.saved_status.setText(f"{datetime.now():%H:%M} 초안 저장됨")

    def _restore_draft(self) -> None:
        key = self._draft_key()
        raw = self.store.setting(key, "") if key else ""
        if not raw:
            return
        try:
            payload = json.loads(raw)
            saved_at = datetime.strptime(str(payload["saved_at"]), DATETIME_FMT)
            values = dict(payload["values"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.store.delete_setting(key)
            return
        if saved_at < datetime.now() - timedelta(days=7):
            self.store.delete_setting(key)
            return
        self._loading = True
        try:
            self.title_edit.setText(str(values.get("title", "")))
            self.content_edit.set_content(str(values.get("content", "")))
            self.postit_check.setChecked(bool(values.get("postit", False)))
            self.always_top_check.setChecked(bool(values.get("always_on_top", True)))
            self.lock_check.setChecked(bool(values.get("input_locked", False)))
            self.set_color(str(values.get("color", "vanilla")))
            opacity = self.opacity_combo.findData(int(values.get("background_transparency", 0)))
            self.opacity_combo.setCurrentIndex(max(0, opacity))
        finally:
            self._loading = False
        self.saved_status.setText(f"{saved_at:%m-%d %H:%M} 초안 복원됨")
        self.show_action_feedback("7일 안에 저장한 미저장 초안을 복원했습니다.", "info")

    def _clear_draft(self) -> None:
        key = self._draft_key()
        if key:
            self.store.delete_setting(key)

    def set_auto_save_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        changed = enabled != self.auto_save_enabled
        self.auto_save_enabled = enabled
        self._sync_save_mode_ui()
        if changed and enabled and self.note_id is not None:
            self._manual_save_pending = False
            self._auto_save()

    def _sync_save_mode_ui(self) -> None:
        if not hasattr(self, "manual_save_button"):
            return
        self.manual_save_button.setVisible(not self.auto_save_enabled)
        self.manual_save_shortcut.setEnabled(not self.auto_save_enabled) if hasattr(self, "manual_save_shortcut") else None
        if self.note_id is not None:
            self.saved_status.setText(
                "● 자동 저장 켜짐" if self.auto_save_enabled else "● 수동 저장 · Ctrl+S"
            )

    def _manual_save(self) -> None:
        self.save_timer.stop()
        self._manual_save_pending = True
        self._auto_save()

    def flush_pending_save(self) -> None:
        # 페이지 줄에 친 이름이 아직 반영되지 않았을 수 있다.  먼저 맞춘다.
        self.content_edit.sync_page_titles()
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._deferred_save()

    def shutdown(self) -> None:
        """Cancel pending memo work before the panel closes its SQLite store."""
        if self._shutdown:
            return
        self.flush_pending_save()
        self._shutdown = True
        self.deadline_timer.stop()
        self.save_timer.stop()
        self.format_toolbar.shutdown()

    def mark_saved(self, success: bool = True) -> None:
        manual = self._manual_save_pending
        self._manual_save_pending = False
        stamp = datetime.now().strftime("%H:%M")
        self.saved_status.setText(
            (f"● {stamp} 자동 저장됨" if self.auto_save_enabled else f"● {stamp} 저장됨")
            if success else "● 저장 실패"
        )
        if success:
            self.content_edit.mark_document_saved()
            self._clear_draft()
            if manual:
                self.show_action_feedback("메모를 저장했습니다.", "success")

    def mark_draft(self) -> None:
        self.saved_status.setText("입력 대기")

    def _refresh_deadline_badge(self) -> None:
        note = getattr(self, "_deadline_note", None)
        text = deadline_badge_text(note) if note is not None else ""
        self.deadline_badge.setText(text)
        self.deadline_badge.setVisible(bool(text))

    def _save_reminder(self) -> None:
        if not self.reminder_save_button.isEnabled():
            return
        memo = self.content_edit.toPlainText().strip() or self.title_edit.text().strip()
        if not memo:
            QMessageBox.information(self, "알림 설정", "알림에 사용할 메모 내용을 입력해 주세요.")
            return
        self.reminder_save_requested.emit({
            "id": self.editing_reminder_id, "due_at": self.due_key(), "memo": memo,
            "rule": self.recurrence.rule(),
        })

    def _quick_reminder(self, minutes: int, _label: str = "") -> None:
        """Keyboard shortcut: preserve the existing set-and-save behavior."""
        self.datetime_input.set_datetime(datetime.now() + timedelta(minutes=minutes))
        self._quick_time_active = False
        self._save_reminder()

    def _set_quick_time(self, minutes: int) -> None:
        """On-screen quick buttons only prepare a time for user confirmation."""
        now = datetime.now().replace(second=0, microsecond=0)
        base = self.datetime_input.datetime() if self._quick_time_active else now
        if base < now:
            base = now
        self._setting_quick_time = True
        try:
            self.datetime_input.set_datetime(base + timedelta(minutes=minutes))
        finally:
            self._setting_quick_time = False
        self._quick_time_active = True

    def _on_datetime_changed(self) -> None:
        if not self._setting_quick_time:
            self._quick_time_active = False
        self._update_reminder_button()

    def _set_reminder_expanded(self, expanded: bool) -> None:
        self.reminder_details.setVisible(expanded)
        self.reminder_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow,
        )
        self.reminder_toggle.setAccessibleName(
            "알림 예약 접기" if expanded else "알림 예약 펼치기",
        )
        self.store.set_setting(self.REMINDER_COLLAPSED_SETTING, "false" if expanded else "true")
        self.updateGeometry()

    def show_action_feedback(self, message: str, level: str = "success") -> None:
        colors = {
            "success": ("#ecfdf5", "#047857", "#a7f3d0"),
            "error": ("#fff1f2", "#be123c", "#fecdd3"),
            "info": ("#eff6ff", "#1d4ed8", "#bfdbfe"),
        }
        background, foreground, border = colors.get(level, colors["info"])
        self.action_feedback.setText(message)
        self.action_feedback.setStyleSheet(
            f"background:{background};color:{foreground};border:1px solid {border};"
            "border-radius:8px;padding:8px 10px;"
        )
        self.action_feedback.show()
        self.action_feedback_timer.start(2600)

    def _reset_reminder_input(self) -> None:
        self._quick_time_active = False
        self.datetime_input.set_datetime(datetime.now() + timedelta(minutes=10))

    def _update_reminder_button(self) -> None:
        valid = self.datetime_input.is_valid() and self.datetime_input.datetime() > datetime.now()
        self.reminder_save_button.setEnabled(valid and self.recurrence.is_valid())

    def _open_shortcut_settings(self) -> None:
        if EditorShortcutSettingsDialog(self.store, self).exec():
            self.reload_shortcuts()

    def reload_shortcuts(self) -> None:
        for shortcut in getattr(self, "time_shortcuts", []):
            shortcut.deleteLater()
        self.time_shortcuts = bind_time_shortcuts(self, self.store, self._quick_reminder)
        modifier = modifier_setting(self.store)
        for key, label, minutes in TIME_SHORTCUTS:
            button = self.quick_buttons[minutes]
            button.setText(f"{label}\n{shortcut_text(modifier, key)}")
            button.updateGeometry()
        self.format_toolbar.reload_shortcuts()
        if not hasattr(self, "always_top_shortcut"):
            self.always_top_shortcut = QShortcut(QKeySequence(), self)
            self.postit_shortcut = QShortcut(QKeySequence(), self)
            self.always_top_shortcut.activated.connect(self.always_top_check.toggle)
            self.postit_shortcut.activated.connect(self.postit_check.toggle)
        self.always_top_shortcut.setKey(QKeySequence(self.store.setting(SETTING_ALWAYS_TOP, DEFAULT_ALWAYS_TOP)))
        self.postit_shortcut.setKey(QKeySequence(self.store.setting(SETTING_POSTIT, DEFAULT_POSTIT)))

    def set_color(self, color: str) -> None:
        self.color = color if color in COLORS else "vanilla"
        for key, button in self.color_buttons.items():
            button.setStyleSheet(
                f"background:{COLORS[key][1]}; border:"
                f"{'3px solid #2563eb' if key == self.color else '2px solid #cbd5e1'}; border-radius:15px;"
            )
        if hasattr(self, "save_timer"):
            self._queue_save()

    def values(self) -> dict:
        hotkey = self.hotkey_edit.text().strip() if self.hotkey_enabled.isChecked() else ""
        if hotkey:
            hotkey = parse_hotkey(hotkey).text
        return {
            "title": self.title_edit.text(), "content": self.content_edit.content(),
            "postit": self.postit_check.isChecked(), "always_on_top": self.always_top_check.isChecked(),
            "input_locked": self.lock_check.isChecked(), "color": self.color,
            "background_transparency": int(self.opacity_combo.currentData()), "hotkey": hotkey,
            "hotkey_action": self.hotkey_action_combo.currentData(),
        }

    def due_key(self) -> str:
        return self.datetime_input.datetime().strftime(DATETIME_FMT)

    def plain_content(self) -> str:
        return plain_text_from_content(self.content_edit.content())
