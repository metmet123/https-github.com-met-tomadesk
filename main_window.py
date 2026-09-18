import html
import json
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import QByteArray, QEvent, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QKeySequence, QPainter, QShortcut
from PyQt6.QtWidgets import (
    QFileDialog, QAbstractItemView, QAbstractSpinBox, QBoxLayout, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QApplication, QHeaderView, QMenu, QScrollArea, QSlider, QSpinBox, QSplitter, QStackedWidget, QSystemTrayIcon,
    QSizePolicy, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from action_runner import ActionRunner
from alert_notes.database_bundle import export_database_bundle, import_database_bundle
from alert_notes.deadline import (
    deadline_chip_text, deadline_days_left, deadline_title, deadline_urgency,
    set_count_today_as_one,
)
from alert_notes.panel import AlertNotesPanel
from alert_notes.quick_capture import MemoSearchDialog, QuickMemoDialog
from alert_notes.quick_schedule import QuickScheduleDialog
from alert_notes.service import AlertService
from alert_notes.toma_pet_window import TomaPetController
from alert_notes.schedule_store import (
    EXCEPTION_COLUMNS, ITEM_COLUMNS, NOTIFICATION_COLUMNS, NOTIFICATION_LOG_COLUMNS,
)
from alert_notes.schedule_postit_settings import SchedulePostitPreferences
from alert_notes.sqlite_store import (
    ATTACHMENT_COLUMNS, HISTORY_COLUMNS, NOTE_COLUMNS, REMINDER_COLUMNS, SERIES_COLUMNS,
    SETTING_COLUMNS, NoteReminderStore,
)
from app_icon import application_icon
from app_config import APP_NAME
from app_utils import now_key
from excel_io import ExcelImportError, export_actions_xlsx, import_actions_xlsx
from excluded_apps_dialog import ExcludedAppsDialog
from foreground_app import (
    foreground_application,
    is_app_excluded,
    normalize_app_list,
    persisted_app_list,
)
from hotkey_builder import HotkeyBuilder
from hotkey_defs import HOTKEY_ID_START, HOTKEY_ID_STOP, HotkeyError
from hotkey_manager import HotkeyManager
from hotkey_parser import parse_hotkey
from macro_recorder import WindowsHookRecorder
from explorer_dblclick import ExplorerDoubleClickNavigator
from macro_playback_config import (
    MAX_REPEAT_COUNT,
    MIN_REPEAT_COUNT,
    editor_playback_speed,
    validate_playback_speed,
    validate_repeat_count,
    validate_timing_mode,
)
from macro_timing_editor import TimingEditorDialog
from select_all_header import SelectAllHeader
from settings_dialog import DEADLINE_OPTIONS, SettingsDialog
from shortcut_overlay import (
    GROUP_ACTIONS,
    GROUP_COMMON,
    GROUP_CONTENT,
    ShortcutOverlay,
    ShortcutOverlayEntry,
)
from store import (
    COLUMNS as HOTKEY_COLUMNS,
    EXPLORER_DBLCLICK_SETTING,
    EXPLORER_MIDDLE_CLICK_SETTING,
    TABLES as HOTKEY_TABLES,
    Store,
)
from storage_config import (
    copy_databases_preserving_existing,
    merge_storage_files,
    same_path,
    save_storage_paths,
)
from ui_feedback import apply_status, parse_splitter_sizes
from user_manual import UserManualDialog
from ui_polish import (
    ActiveStateItem,
    RegistrationDotDelegate,
    RegistrationStateItem,
    apply_numeric_font,
    polish_action_item,
    polish_button,
    refresh_property,
)
from ui_theme import scaled_stylesheet as theme_scaled_stylesheet
from window_title_bar import WindowTitleBar
from window_layout import collect_open_windows
from window_pin import WindowPinController


ACTION_LABELS = {
    "text": "문구 입력",
    "url": "사이트 열기",
    "path": "프로그램/폴더 열기",
    "macro": "반복작업",
    "layout": "창 배치",
}
RECORD_STOP_HOTKEY_ID = 998
RECORD_STOP_HOTKEY = "Ctrl+Alt+F12"
RECORD_STOP_HOTKEY_SETTING = "record_stop_hotkey"
PLAYBACK_STOP_HOTKEY = "Ctrl+Alt+Esc"
PLAYBACK_STOP_HOTKEY_SETTING = "playback_stop_hotkey"
MAIN_OPEN_HOTKEY_ID = 996
TRAY_HIDE_HOTKEY_ID = 997
EXIT_HOTKEY_ID = 995
QUICK_MEMO_HOTKEY_ID = 992
TODAY_VIEW_HOTKEY_ID = 993
MEMO_SEARCH_HOTKEY_ID = 994
NEW_MEMO_HOTKEY_ID = 991
QUICK_SCHEDULE_HOTKEY_ID = 990
SCHEDULE_POSTIT_HOTKEY_ID = 989
WINDOW_PIN_HOTKEY_ID = 988
SHORTCUT_OVERLAY_HOTKEY_ID = 987
MAIN_OPEN_HOTKEY = "Ctrl+Alt+F10"
TRAY_HIDE_HOTKEY = "Ctrl+Alt+F11"
EXIT_HOTKEY = "Ctrl+Alt+F9"
QUICK_MEMO_HOTKEY = "Ctrl+Alt+N"
NEW_MEMO_HOTKEY = "Ctrl+Alt+Shift+N"
TODAY_VIEW_HOTKEY = "Ctrl+Alt+C"
MEMO_SEARCH_HOTKEY = "Ctrl+Alt+M"
QUICK_SCHEDULE_HOTKEY = "Ctrl+Alt+A"
WINDOW_PIN_HOTKEY = "Ctrl+Alt+T"
SHORTCUT_OVERLAY_HOTKEY = "Ctrl+Alt+H"
MAIN_OPEN_HOTKEY_SETTING = "main_open_hotkey"
TRAY_HIDE_HOTKEY_SETTING = "tray_hide_hotkey"
EXIT_HOTKEY_SETTING = "exit_hotkey"
QUICK_MEMO_HOTKEY_SETTING = "quick_memo_hotkey"
NEW_MEMO_HOTKEY_SETTING = "new_memo_hotkey"
TODAY_VIEW_HOTKEY_SETTING = "today_view_hotkey"
MEMO_SEARCH_HOTKEY_SETTING = "memo_search_hotkey"
QUICK_SCHEDULE_HOTKEY_SETTING = "quick_schedule_hotkey"
WINDOW_PIN_HOTKEY_SETTING = "window_pin_hotkey"
SHORTCUT_OVERLAY_HOTKEY_SETTING = "shortcut_overlay_hotkey"
STARTUP_MODE_SETTING = "startup_mode"
SHOW_START_GUIDE_SETTING = "show_start_guide_on_launch"
MEMO_AUTO_SAVE_SETTING = "memo_auto_save_enabled"
DEADLINE_ANNOUNCED_SETTING = "deadline_announced_on"
# D-Day judgement calls the user decides in Settings, not the program.
DEADLINE_SETTING_DEFAULTS = {key: default for key, _l, _h, default in DEADLINE_OPTIONS}
TABLE_COLUMN_WIDTHS_SETTING = "main_table_column_widths"
TABLE_COLUMN_RATIOS_SETTING = "main_table_column_ratios"
# ID 열은 감춘다(폭 0).  상태 열은 글자 대신 점 하나라 좁아도 된다.
DEFAULT_COLUMN_WIDTHS = [38, 0, 66, 268, 124, 136, 46]
ID_COLUMN = 1
# The name column used to share width evenly with the rest, which truncated the
# one value that identifies a row.  Rebalance it, but only for users who never
# dragged the headers themselves.
LEGACY_FLEXIBLE_COLUMN_WIDTHS = [172, 124, 154, 112]
# ID 를 감추고 상태를 점으로 바꾸기 전의 기본값.  머리글을 직접 끌어 본 적이
# 없는 사람만 새 폭으로 옮긴다.
PREVIOUS_FLEXIBLE_COLUMN_WIDTHS = [230, 118, 130, 104]
TABLE_COLUMN_RATIOS_VERSION_SETTING = "action_table_column_ratio_version"
TABLE_COLUMN_RATIOS_VERSION = "3"
VERTICAL_MIN_TABLE_ROWS = 6
VERTICAL_TABLE_MAX_SHARE = 0.62
MACRO_HISTORY_LIMIT = 50
MACRO_HISTORY_DEBOUNCE_MS = 400
FOREGROUND_HOTKEY_SYNC_MS = 120


class ToggleSwitch(QCheckBox):
    """Compact ON/OFF switch used inside the active-state table column."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scale = 1.0
        self.set_scale(1.0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("클릭하여 활성/비활성 전환")

    def set_scale(self, scale: float) -> None:
        self._scale = scale
        self.setFixedSize(round(52 * scale), round(26 * scale))
        self.update()

    def hitButton(self, _position) -> bool:
        return True

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        margin = max(1, round(self._scale))
        track = QRectF(0, margin, width, height - 2 * margin)
        active = self.isChecked()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2563eb" if active else "#cbd5e1"))
        radius = track.height() / 2
        painter.drawRoundedRect(track, radius, radius)
        knob_size = max(12, round(18 * self._scale))
        knob_x = width - knob_size - max(2, round(3 * self._scale)) if active else max(2, round(3 * self._scale))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, (height - knob_size) / 2, knob_size, knob_size))
        painter.setPen(QColor("#ffffff" if active else "#475569"))
        painter.setFont(self.font())
        label_rect = QRectF(4 * self._scale, 0, width / 2, height) if active else QRectF(width / 2 - 2 * self._scale, 0, width / 2, height)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "ON" if active else "OFF")


class StartJourneyDialog(QDialog):
    """Equal-weight entry points for the product's three core journeys."""

    def __init__(self, actions: list[tuple[str, str, str, object]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("빠른 시작")
        self.setMinimumSize(620, 330)
        layout = QVBoxLayout(self)
        title = QLabel("무엇을 하고 싶으세요?")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("대표 작업을 선택하면 필요한 화면에서 바로 시작합니다.")
        subtitle.setObjectName("workspaceSubtitle")
        layout.addWidget(subtitle)
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.journey_buttons: list[QPushButton] = []
        for heading, description, action_label, callback in actions:
            card = QFrame()
            card.setObjectName("editorCard")
            card_layout = QVBoxLayout(card)
            card_title = QLabel(heading)
            card_title.setObjectName("journeyCardTitle")
            card_layout.addWidget(card_title)
            body = QLabel(description)
            body.setWordWrap(True)
            card_layout.addWidget(body, 1)
            # Three buttons all reading "시작" are indistinguishable to a screen
            # reader and to anyone scanning the row, so each says what it does.
            button = QPushButton(action_label)
            button.setObjectName("primaryButton")
            button.setAccessibleName(action_label)
            button.setAccessibleDescription(description)
            button.clicked.connect(lambda _checked=False, fn=callback: (self.accept(), fn()))
            card_layout.addWidget(button)
            self.journey_buttons.append(button)
            cards.addWidget(card, 1)
        layout.addLayout(cards, 1)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)


class TrashDialog(QDialog):
    COLUMN_WEIGHTS = (44, 110, 250, 150)
    COLUMN_MINIMUMS = (40, 82, 130, 118)

    def __init__(self, items: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("휴지통 · 7일 보관")
        self.resize(680, 420)
        layout = QVBoxLayout(self)
        info = QLabel("삭제한 작업·메모·일정은 7일 후 자동으로 영구 삭제됩니다.")
        info.setWordWrap(True)
        layout.addWidget(info)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "종류", "이름", "삭제 시각"])
        self.table_header = SelectAllHeader(self.table)
        self.table.setHorizontalHeader(self.table_header)
        self.table_header.setMinimumSectionSize(1)
        self.table_header.setSectionResizeMode(SelectAllHeader.ResizeMode.Fixed)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.setAccessibleName("7일 휴지통 목록")
        self.table.viewport().installEventFilter(self)
        self.table.itemChanged.connect(self._sync_select_all_state)
        self.table_header.check_state_changed.connect(self._set_all_checked)
        self._items = items
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, item)
            self.table.setItem(row, 0, check)
            for column, value in enumerate((item["kind"], item["title"], item["deleted_at"]), start=1):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.ItemDataRole.UserRole, item)
                self.table.setItem(row, column, cell)
        self._sync_select_all_state()
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        restore = QPushButton("선택 항목 복원")
        restore.setObjectName("primaryButton")
        restore.clicked.connect(self._restore_selected)
        close = QPushButton("닫기")
        close.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(restore)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _restore_selected(self) -> None:
        rows = [
            row for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        if not rows:
            QMessageBox.information(self, "휴지통", "복원할 항목을 선택해 주세요.")
            return
        for row in sorted(rows, reverse=True):
            item = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            item["restore"]()
            self._items.remove(item)
            self.table.removeRow(row)
        self._sync_select_all_state()

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self._resize_table_columns()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_table_columns()

    def _resize_table_columns(self) -> None:
        if not hasattr(self, "table"):
            return
        available = self.table.viewport().width()
        if available <= 0:
            return
        total_weight = sum(self.COLUMN_WEIGHTS)
        widths = [
            max(minimum, round(available * weight / total_weight))
            for weight, minimum in zip(self.COLUMN_WEIGHTS, self.COLUMN_MINIMUMS)
        ]
        difference = available - sum(widths)
        order = sorted(range(len(widths)), key=lambda index: self.COLUMN_WEIGHTS[index], reverse=True)
        while difference > 0:
            for index in order:
                if difference <= 0:
                    break
                widths[index] += 1
                difference -= 1
        while difference < 0:
            candidates = [index for index, width in enumerate(widths) if width > self.COLUMN_MINIMUMS[index]]
            if not candidates:
                break
            index = max(candidates, key=lambda value: widths[value] - self.COLUMN_MINIMUMS[value])
            widths[index] -= 1
            difference += 1
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)

    def _set_all_checked(self, checked) -> None:
        if not isinstance(checked, bool):
            checked = Qt.CheckState(checked) != Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        try:
            state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            for row in range(self.table.rowCount()):
                self.table.item(row, 0).setCheckState(state)
        finally:
            self.table.blockSignals(False)
        self._sync_select_all_state()

    def _sync_select_all_state(self, _item=None) -> None:
        total = self.table.rowCount()
        selected = sum(
            self.table.item(row, 0).checkState() == Qt.CheckState.Checked
            for row in range(total)
        )
        if selected == 0:
            state = Qt.CheckState.Unchecked
        elif selected == total:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        self.table_header.set_check_state(state)


class MainWindow(QMainWindow):
    def __init__(self, store: Store | None = None):
        super().__init__()
        self.store = store or Store()
        self.note_store = NoteReminderStore(self.store.data_dir / "alert_notes.db", default_title="새 메모")
        self.store.purge_expired_trash(7)
        self.note_store.purge_expired_trash(7)
        self.note_store.schedules.purge_expired_trash(7)
        self.record_stop_hotkey = self._record_stop_hotkey_from_store()
        self.playback_stop_hotkey = self._playback_stop_hotkey_from_store()
        self.main_open_hotkey = self._hotkey_from_store(MAIN_OPEN_HOTKEY_SETTING, MAIN_OPEN_HOTKEY)
        self.tray_hide_hotkey = self._hotkey_from_store(TRAY_HIDE_HOTKEY_SETTING, TRAY_HIDE_HOTKEY)
        self.exit_hotkey = self._hotkey_from_store(EXIT_HOTKEY_SETTING, EXIT_HOTKEY)
        self.quick_memo_hotkey = self._hotkey_from_store(QUICK_MEMO_HOTKEY_SETTING, QUICK_MEMO_HOTKEY)
        self.new_memo_hotkey = self._hotkey_from_store(NEW_MEMO_HOTKEY_SETTING, NEW_MEMO_HOTKEY)
        self.today_view_hotkey = self._hotkey_from_store(TODAY_VIEW_HOTKEY_SETTING, TODAY_VIEW_HOTKEY)
        self.memo_search_hotkey = self._hotkey_from_store(MEMO_SEARCH_HOTKEY_SETTING, MEMO_SEARCH_HOTKEY)
        self.quick_schedule_hotkey = self._hotkey_from_store(
            QUICK_SCHEDULE_HOTKEY_SETTING, QUICK_SCHEDULE_HOTKEY
        )
        self.window_pin_hotkey = self._hotkey_from_store(
            WINDOW_PIN_HOTKEY_SETTING, WINDOW_PIN_HOTKEY
        )
        self.shortcut_overlay_hotkey = self._hotkey_from_store(
            SHORTCUT_OVERLAY_HOTKEY_SETTING, SHORTCUT_OVERLAY_HOTKEY
        )
        self.schedule_postit_hotkey = SchedulePostitPreferences.load(self.note_store).hotkey
        self.startup_mode = self.store.setting(STARTUP_MODE_SETTING, "window")
        self.runner = ActionRunner(self.playback_stop_hotkey, settings_store=self.store)
        self._hidden_windows_exit_restored = False
        self._hidden_windows_startup_checked = False
        QApplication.instance().aboutToQuit.connect(self._restore_hidden_windows_on_exit)
        self.hotkeys = HotkeyManager(int(self.winId()))
        self.recorder = WindowsHookRecorder()
        self.recorder.ignore_click = self._is_own_window_click
        self._recording = False
        self._macro_playing = False
        self._explorer_double_click_navigator = None
        self._explorer_double_click_enabled = False
        self._explorer_middle_click_enabled = False
        self._configure_explorer_double_click_from_store()
        self._updating_macro_document = False
        self._original_macro_state: dict | None = None
        self._macro_undo_stack: list[dict] = []
        self._macro_redo_stack: list[dict] = []
        self._macro_history_current: dict | None = None
        self._macro_history_timer = QTimer(self)
        self._macro_history_timer.setSingleShot(True)
        self._macro_history_timer.setInterval(MACRO_HISTORY_DEBOUNCE_MS)
        self._macro_history_timer.timeout.connect(self._commit_macro_history_state)
        self.excluded_apps: list[dict] = []
        self._action_hotkey_rows: dict[int, object] = {}
        self._registered_action_hotkey_ids: set[int] = set()
        self._action_registration_status: dict[int, tuple[str, str]] = {}
        self._last_hotkey_failures: list[str] = []
        self._last_content_hotkey_signature: tuple = ()
        self._foreground_app_signature: tuple[str, str] | None = None
        self._foreground_hotkey_timer = QTimer(self)
        self._foreground_hotkey_timer.setInterval(FOREGROUND_HOTKEY_SYNC_MS)
        self._foreground_hotkey_timer.timeout.connect(self._sync_action_hotkeys_for_foreground)
        self._resize_drag = None
        self._quick_memo_dialog = None
        self._quick_schedule_dialog = None
        self._memo_search_dialog = None
        self._restoring_column_widths = False
        self._restoring_splitter_ratio = False
        self.current_id: int | None = None
        self._action_form_baseline: dict | None = None
        self._restoring_action_selection = False
        self._ui_scale = 1.0
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(application_icon())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setMinimumSize(820, 560)
        self.resize(1420, 720)
        self._build_ui()
        self.window_pin = WindowPinController(
            is_own_postit=self._is_own_postit_window,
            count_changed=lambda _count: self._refresh_tray_tooltip(),
        )
        QApplication.instance().aboutToQuit.connect(self.window_pin.shutdown)
        self.shortcut_overlay = ShortcutOverlay(self)
        self.shortcut_overlay.item_activated.connect(self._navigate_from_shortcut_overlay)
        self.pet_controller = TomaPetController(
            self.note_store, self.open_today_schedule, self.show_quick_memo,
        )
        self.alert_service = AlertService(
            self.note_store, self.open_alert_note, self.alert_panel.refresh,
            self.open_schedule_item, self, pet_controller=self.pet_controller,
        )
        self._build_tray()
        self.pet_controller.start()
        self._restore_window_geometry()
        self._apply_ui_scale()
        self._reset_macro_history()
        QApplication.instance().installEventFilter(self)
        self.refresh()
        self._set_action_form_baseline()
        QTimer.singleShot(1000, self._create_automatic_backup)
        self.alert_service.start()
        self.register_hotkeys(show_message=False)
        self.refresh_deadline_indicators()
        QTimer.singleShot(1200, self.announce_today_deadlines)
        # Offscreen Qt tests do not have a meaningful Windows foreground window.
        if QGuiApplication.platformName().casefold() != "offscreen":
            self._foreground_hotkey_timer.start()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.title_bar = WindowTitleBar(self)
        root_layout.addWidget(self.title_bar)
        mode_bar = QWidget()
        mode_bar.setObjectName("workspaceModeBar")
        self.workspace_mode_bar = mode_bar
        mode_layout = QHBoxLayout(mode_bar)
        mode_layout.setContentsMargins(12, 6, 12, 6)
        mode_layout.setSpacing(6)
        self.workspace_mode_layout = mode_layout
        self.shortcut_mode_button = QPushButton("단축키·반복작업")
        self.alert_mode_button = QPushButton("메모·일정")
        self.workspace_mode_group = QButtonGroup(self)
        self.workspace_mode_group.setExclusive(True)
        for index, button in enumerate((self.shortcut_mode_button, self.alert_mode_button)):
            button.setObjectName("workspaceModeButton")
            button.setCheckable(True)
            button.setMinimumHeight(36)
            # 글자에 맞춘 폭.  Preferred 는 남는 자리를 받아 가로로 늘어났다.
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.setAccessibleName(button.text() + " 화면")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.workspace_mode_group.addButton(button, index)
            mode_layout.addWidget(button)
        self.workspace_switch_hint = QLabel("Ctrl+Tab 전환")
        self.workspace_switch_hint.setObjectName("workspaceSwitchHint")
        self.workspace_switch_hint.setAccessibleName("Ctrl+Tab으로 작업공간 전환")
        self.workspace_switch_hint.setToolTip("Ctrl+Tab: 단축키·반복작업 ↔ 메모·일정")
        mode_layout.addWidget(self.workspace_switch_hint)
        self.workspace_subnav_separator = QFrame()
        self.workspace_subnav_separator.setObjectName("workspaceSubnavSeparator")
        self.workspace_subnav_separator.setFrameShape(QFrame.Shape.VLine)
        mode_layout.addWidget(self.workspace_subnav_separator)
        self.alert_tab_group = QButtonGroup(self)
        self.alert_tab_group.setExclusive(True)
        self.alert_tab_buttons = []
        for index, label in enumerate(("메모 편집", "캘린더", "알림내역")):
            button = QPushButton(label)
            button.setObjectName("workspaceSubTabButton")
            button.setCheckable(True)
            button.setMinimumHeight(34)
            button.setAccessibleName(label + " 탭")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.alert_tab_group.addButton(button, index)
            self.alert_tab_buttons.append(button)
            mode_layout.addWidget(button)
        # The one D-Day you must not forget, always on screen in one line.  It
        # sits with the tools on the right, not among the tabs: a chip wedged
        # between 알림내역 and the hint read as a fourth tab.
        self.deadline_chip = QPushButton("")
        self.deadline_chip.setObjectName("deadlineChip")
        self.deadline_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deadline_chip.setAccessibleName("가장 임박한 D-Day")
        self.deadline_chip.clicked.connect(self._open_deadline_summary)
        self.deadline_chip.hide()
        self.subtab_switch_hint = QLabel("Ctrl+Shift+Tab 전환")
        self.subtab_switch_hint.setObjectName("workspaceSwitchHint")
        self.subtab_switch_hint.setAccessibleName("Ctrl+Shift+Tab으로 메모·일정 탭 전환")
        self.subtab_switch_hint.setToolTip("Ctrl+Shift+Tab: 메모 편집 → 캘린더 → 알림내역")
        mode_layout.addWidget(self.subtab_switch_hint)
        mode_layout.addStretch(1)
        mode_layout.addWidget(self.deadline_chip)
        self.workspace_utility_buttons = []
        for text, callback, tooltip in (
            ("시작", self.show_start_guide, "단축키, 메모, 일정 중 하나를 빠르게 시작"),
            ("휴지통", self.show_trash, "최근 7일 안에 삭제한 작업·메모·일정 복원"),
            ("설정", self.show_settings, "전역 단축키와 시작 위치 설정"),
            ("설명서", self.show_help, "화면 그림으로 보는 사용 설명서 열기"),
        ):
            button = self._button(mode_layout, text, callback)
            button.setObjectName("workspaceUtilityButton")
            button.setToolTip(tooltip)
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self.workspace_utility_buttons.append(button)
        self.shortcut_mode_button.setChecked(True)
        self.workspace_mode_group.idClicked.connect(self._switch_workspace)
        self.workspace_switch_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        self.workspace_switch_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.workspace_switch_shortcut.activated.connect(self._toggle_workspace)
        # Shift+Tab arrives as Backtab on Windows, so bind both spellings.
        self.subtab_switch_shortcuts = []
        for sequence in ("Ctrl+Shift+Tab", "Ctrl+Shift+Backtab"):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(self._cycle_alert_tab)
            self.subtab_switch_shortcuts.append(shortcut)
        root_layout.addWidget(mode_bar)
        self.main_pages = QStackedWidget()
        root_layout.addWidget(self.main_pages, 1)
        self.splitter = QSplitter()
        self.main_pages.addWidget(self.splitter)
        self.setCentralWidget(root)
        self.table_panel = self._build_table_panel()
        self.splitter.addWidget(self.table_panel)
        self.form_panel = self._build_form_panel()
        self.splitter.addWidget(self.form_panel)
        self.table_panel.setMinimumWidth(520)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([660, 740])
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        self.alert_panel = AlertNotesPanel(self.note_store)
        self.alert_panel.editor_fullscreen_changed.connect(
            lambda on: self.workspace_mode_bar.setVisible(not on)
        )
        self.alert_panel.hotkey_validator = self._validate_content_hotkey
        self.alert_panel.calendar.schedule_editor.hotkey_validator = self._validate_content_hotkey
        self.alert_panel.shortcuts_changed.connect(self._on_content_shortcuts_changed)
        self.alert_panel.summary.deadline_changed.connect(self.refresh_deadline_indicators)
        self.alert_panel.tabs.currentChanged.connect(
            lambda _index: self.refresh_deadline_indicators()
        )
        self.main_pages.addWidget(self.alert_panel)
        self.alert_panel.tabs.tabBar().hide()
        self.alert_tab_group.idClicked.connect(self.alert_panel.tabs.setCurrentIndex)
        self.alert_panel.tabs.currentChanged.connect(self._sync_alert_tab_button)
        self._sync_alert_tab_button(self.alert_panel.tabs.currentIndex())
        self._update_workspace_subnav_visibility()
        self._wheel_locked_controls = tuple(self.findChildren((QComboBox, QAbstractSpinBox)))
        QTimer.singleShot(0, self._update_responsive_layout)

    def _switch_workspace(self, index: int) -> None:
        resolved = max(0, min(1, int(index)))
        if resolved != 1 and self.alert_panel.editor_fullscreen:
            self.alert_panel.toggle_editor_fullscreen(False)
        button = self.workspace_mode_group.button(resolved)
        if button is not None:
            button.setChecked(True)
        self.main_pages.setCurrentIndex(resolved)
        self._update_workspace_subnav_visibility()
        QTimer.singleShot(0, self._update_responsive_layout)

    def _sync_alert_tab_button(self, index: int) -> None:
        button = self.alert_tab_group.button(int(index))
        if button is not None:
            button.setChecked(True)

    def _update_workspace_subnav_visibility(self) -> None:
        visible = self.main_pages.currentIndex() == 1
        self.workspace_subnav_separator.setVisible(visible)
        for button in self.alert_tab_buttons:
            button.setVisible(visible)
        if hasattr(self, "subtab_switch_hint"):
            # The sub-tab hint belongs to the sub-tabs, so it comes and goes with them.
            self.subtab_switch_hint.setVisible(visible and self._hints_fit())

    def _hints_fit(self) -> bool:
        return self.width() >= round(1120 * self._ui_scale)

    def apply_deadline_counting(self) -> None:
        """One counting convention for the whole app, chosen once in settings."""
        set_count_today_as_one(
            self.deadline_options().get("deadline_count_today_as_one", False)
        )

    def deadline_options(self) -> dict:
        return {
            key: self.note_store.setting(key, "true" if default else "false").lower() == "true"
            for key, default in DEADLINE_SETTING_DEFAULTS.items()
        }

    def _open_deadline_summary(self) -> None:
        """칩을 누르면 가장 임박한 D-Day 메모가 바로 열린다.

        옆의 오늘 요약에 나머지 D-Day가 그대로 남아 있으므로, 하나를 열어도
        다른 것을 놓치지 않는다.  셀 것이 없으면 칩 자체가 숨어 있다.
        """
        self.restore_from_tray()
        self._switch_workspace(1)
        self.alert_panel.tabs.setCurrentIndex(0)
        note_id = getattr(self, "_nearest_deadline_id", None)
        if note_id is not None:
            self.alert_panel.show_note(int(note_id))

    def refresh_deadline_indicators(self) -> None:
        """Keep the top-bar chip and the tray tooltip in step with the notes."""
        if not hasattr(self, "deadline_chip"):
            return
        self.apply_deadline_counting()
        try:
            rows = [
                row for row in self.note_store.deadline_notes()
                if deadline_urgency(row) not in ("done", "")
            ]
        except Exception:
            rows = []
        order = {"today": 0, "past": 1, "soon": 2, "later": 3}
        rows.sort(key=lambda row: (
            order.get(deadline_urgency(row), 4),
            abs(deadline_days_left(str(row["d_day_at"] or "")) or 0),
        ))
        options = self.deadline_options()
        if options.get("deadline_hide_finished", False):
            rows = [row for row in rows if deadline_urgency(row) != "done"]
        if not rows:
            self._nearest_deadline_id = None
            self.deadline_chip.hide()
            self._set_tray_tooltip("")
            return
        nearest = rows[0]
        self._nearest_deadline_id = int(nearest["id"])
        urgency = deadline_urgency(nearest)
        title = deadline_title(nearest)
        # One chip, but it must not hide that three things are due: the count of
        # the rest rides along instead of a second chip.
        label = f"{deadline_chip_text(nearest)}  {title[:10]}"
        if len(rows) > 1:
            label += f"  +{len(rows) - 1}"
        self.deadline_chip.setText(label)
        self.deadline_chip.setToolTip("\n".join(
            f"{deadline_chip_text(row)}  {deadline_title(row)}" for row in rows[:6]
        ))
        refresh_property(self.deadline_chip, "urgency", urgency)
        self.deadline_chip.setVisible(options.get("deadline_show_top_chip", True))
        urgent = [row for row in rows if deadline_urgency(row) in ("today", "past", "soon")]
        self._set_tray_tooltip(
            f"{deadline_chip_text(nearest)} {title}" + (f" 외 {len(urgent) - 1}건" if len(urgent) > 1 else "")
        )

    def announce_today_deadlines(self) -> bool:
        """Once a day, on first launch, say what is due today.

        The pet dialog is a reminder surface with 완료·미루기 buttons, so a
        D-Day notice uses the tray instead; the target-time alert still goes
        through the pet when the user asked for one.
        """
        if not self.deadline_options().get("deadline_pet_on_the_day", True):
            return False
        today = datetime.now().strftime("%Y%m%d")
        if self.note_store.setting(DEADLINE_ANNOUNCED_SETTING, "") == today:
            return False
        try:
            rows = [
                row for row in self.note_store.deadline_notes()
                if deadline_urgency(row) == "today"
            ]
        except Exception:
            return False
        if not rows:
            return False
        self.note_store.set_setting(DEADLINE_ANNOUNCED_SETTING, today)
        names = " · ".join(deadline_title(row) for row in rows[:3])
        if len(rows) > 3:
            names += f" 외 {len(rows) - 3}건"
        tray_icon = getattr(self, "tray_icon", None)
        if tray_icon is not None:
            tray_icon.showMessage("오늘이 D-Day입니다", names, application_icon(), 8000)
        self._set_status(f"오늘이 D-Day: {names}", "warning")
        return True

    def _set_tray_tooltip(self, text: str) -> None:
        self._tray_detail_text = text
        self._refresh_tray_tooltip()

    def _refresh_tray_tooltip(self) -> None:
        tray_icon = getattr(self, "tray_icon", None)
        if tray_icon is None:
            return
        details = []
        text = str(getattr(self, "_tray_detail_text", "") or "")
        if text:
            details.append(text)
        window_pin = getattr(self, "window_pin", None)
        if window_pin is not None:
            details.append(f"고정된 창 {window_pin.pinned_count}개")
        tray_icon.setToolTip(APP_NAME + ("\n" + "\n".join(details) if details else ""))

    def _is_own_postit_window(self, hwnd: int) -> bool:
        panel = getattr(self, "alert_panel", None)
        if panel is None:
            return False
        windows = list(getattr(panel, "postits", {}).values())
        schedule_postit = getattr(panel, "schedule_postit", None)
        if schedule_postit is not None:
            windows.append(schedule_postit)
        return any(
            window.isVisible() and int(window.winId()) == int(hwnd)
            for window in windows
        )

    def toggle_foreground_window_pin(self) -> None:
        result = self.window_pin.toggle_foreground()
        level = "success" if result.changed else "warning"
        self._set_status(result.message, level)
        tray_icon = getattr(self, "tray_icon", None)
        if tray_icon is not None:
            tray_icon.showMessage("창 고정/해제", result.message, application_icon(), 3500)

    def show_shortcut_overlay(self) -> bool:
        current_app = foreground_application()
        return self.shortcut_overlay.open_overlay(
            self._shortcut_overlay_entries(),
            failure_count=len(self._last_hotkey_failures),
            excluded_app=is_app_excluded(current_app, self.excluded_apps),
            recording=self._recording,
            playback=self._macro_playing,
        )

    def _shortcut_overlay_entries(self) -> list[ShortcutOverlayEntry]:
        entries = list(getattr(self, "_shortcut_overlay_registered_entries", []))
        for hotkey_id, row in sorted(self._action_hotkey_rows.items()):
            if hotkey_id not in self._registered_action_hotkey_ids or not bool(row["active"]):
                continue
            entries.append(ShortcutOverlayEntry(
                GROUP_ACTIONS,
                str(row["name"]),
                str(row["hotkey"]),
                target_kind="action",
                target_id=int(row["id"]),
            ))
        return entries

    def _navigate_from_shortcut_overlay(self, entry: ShortcutOverlayEntry) -> None:
        if not isinstance(entry, ShortcutOverlayEntry):
            return
        if entry.target_kind == "note" and entry.target_id is not None:
            self.open_alert_note(int(entry.target_id))
            return
        if entry.target_kind == "schedule" and entry.target_id is not None:
            self.open_schedule_item(int(entry.target_id))
            return
        self.restore_from_tray()
        if entry.target_kind == "action" and entry.target_id is not None:
            self._switch_workspace(0)
            self._restore_action_selection(int(entry.target_id))
            self.load_selected()
            current = self.table.currentItem()
            if current is not None:
                self.table.scrollToItem(current)
            return
        if entry.target_kind == "settings":
            self.show_settings()

    def _cycle_alert_tab(self) -> None:
        """Move to the next 메모·일정 tab; the shortcut workspace has none."""
        if self.main_pages.currentIndex() != 1:
            return
        tabs = self.alert_panel.tabs
        if tabs.count():
            tabs.setCurrentIndex((tabs.currentIndex() + 1) % tabs.count())

    def _toggle_workspace(self) -> None:
        self._switch_workspace(1 - self.main_pages.currentIndex())

    def open_alert_note(self, note_id: int) -> None:
        self.alert_mode_button.setChecked(True)
        self._switch_workspace(1)
        self.restore_from_tray()
        self.alert_panel.show_note(note_id)

    def open_schedule_item(self, item_id: int) -> None:
        self.alert_mode_button.setChecked(True)
        self._switch_workspace(1)
        self.restore_from_tray()
        self.alert_panel.show_schedule(item_id)

    def open_today_schedule(self) -> None:
        self.alert_mode_button.setChecked(True)
        self._switch_workspace(1)
        self.restore_from_tray()
        self.alert_panel.show_today()

    def show_quick_memo(self) -> None:
        if self._quick_memo_dialog is None:
            self._quick_memo_dialog = QuickMemoDialog(self.note_store, self)
            self._quick_memo_dialog.note_saved.connect(self._quick_note_saved)
        self._quick_memo_dialog.prepare()
        self._quick_memo_dialog.show()
        self._quick_memo_dialog.raise_()
        self._quick_memo_dialog.activateWindow()

    def show_new_memo_editor(self) -> None:
        """Create a memo and open only its standalone editor window."""
        note_id = self.note_store.create_note("새 메모", "")
        self.alert_panel.refresh()
        self.alert_panel.calendar.refresh()
        self.alert_panel.open_standalone_note(note_id)

    def show_quick_schedule(self) -> None:
        """어느 프로그램에 있든 한 줄로 일정을 넣는 창."""
        if self._quick_schedule_dialog is None:
            self._quick_schedule_dialog = QuickScheduleDialog(
                self.note_store, self, self.quick_schedule_hotkey
            )
            self._quick_schedule_dialog.schedule_saved.connect(self._quick_schedule_saved)
            self._quick_schedule_dialog.note_saved.connect(self._quick_note_saved)
            self._quick_schedule_dialog.detail_requested.connect(self.open_schedule_item)
        self._quick_schedule_dialog.prepare(self.quick_schedule_hotkey)
        self._quick_schedule_dialog.show()
        self._quick_schedule_dialog.raise_()
        self._quick_schedule_dialog.activateWindow()

    def toggle_schedule_postit(self) -> None:
        self.alert_panel.toggle_schedule_postit()

    def _quick_schedule_saved(self, _item_id: int) -> None:
        self.alert_panel.refresh()
        self.alert_panel.calendar.refresh()

    def _quick_note_saved(self, note_id: int) -> None:
        self.alert_panel.current_id = note_id
        self.alert_panel.refresh()
        self.register_hotkeys(False)

    def show_memo_search(self) -> None:
        if self._memo_search_dialog is None:
            self._memo_search_dialog = MemoSearchDialog(self.note_store, self)
            self._memo_search_dialog.note_requested.connect(self.open_alert_note)
            self._memo_search_dialog.schedule_requested.connect(self.open_schedule_item)
        self._memo_search_dialog.prepare()
        self._memo_search_dialog.show()
        self._memo_search_dialog.raise_()
        self._memo_search_dialog.activateWindow()

    def _build_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(self.windowIcon(), self)
        self._refresh_tray_tooltip()
        tray_menu = QMenu(self)
        open_action = tray_menu.addAction("메인 창 열기")
        open_action.triggered.connect(self.restore_from_tray)
        schedule_postit_action = tray_menu.addAction("일정 포스트잇")
        schedule_postit_action.triggered.connect(self.toggle_schedule_postit)
        settings_action = tray_menu.addAction("설정")
        settings_action.triggered.connect(self.show_settings)
        restore_hidden_action = tray_menu.addAction("숨긴 창 모두 복원")
        restore_hidden_action.triggered.connect(self.restore_all_hidden_windows)
        tray_menu.addSeparator()
        exit_action = tray_menu.addAction("종료")
        exit_action.triggered.connect(self.exit_application)
        self.tray_icon.setContextMenu(tray_menu)

    def hide_to_tray(self) -> None:
        self._cancel_resize_drag()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QMessageBox.warning(self, APP_NAME, "시스템 트레이를 사용할 수 없어 창을 숨길 수 없습니다.")
            return
        if self.tray_icon.icon().isNull():
            self.tray_icon.setIcon(self.windowIcon())
        if self.tray_icon.icon().isNull():
            QMessageBox.warning(self, APP_NAME, "트레이 아이콘을 불러오지 못해 창을 숨길 수 없습니다.")
            return
        self.tray_icon.show()
        # Let Windows register the icon before the main window disappears.
        QApplication.processEvents()
        self.hide()

    def restore_from_tray(self) -> None:
        self._cancel_resize_drag()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toggle_maximized(self) -> None:
        self._cancel_resize_drag()
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        QTimer.singleShot(0, self._cancel_resize_drag)

    def show_initial_state(self) -> None:
        show_guide = self.store.setting(SHOW_START_GUIDE_SETTING, "true").lower() == "true"
        QTimer.singleShot(200, self._offer_restore_hidden_windows)
        if self.startup_mode == "tray" and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()
            self.hide()
            if show_guide:
                QTimer.singleShot(0, self.show_start_guide)
            return
        self.show()
        if show_guide:
            QTimer.singleShot(0, self.show_start_guide)

    def restore_all_hidden_windows(self) -> None:
        restored, failed = self.runner.restore_all_hidden_windows()
        if failed:
            self._set_status(
                f"숨긴 창 {restored}개 복원, {failed}개는 창 종류·폴더 경로 확인에 실패했습니다.",
                "warning",
            )
        else:
            self._set_status(f"숨긴 창 {restored}개를 복원했습니다.", "success")

    def _offer_restore_hidden_windows(self) -> None:
        if self._hidden_windows_startup_checked:
            return
        self._hidden_windows_startup_checked = True
        count = self.runner.alive_hidden_window_count()
        if count and QMessageBox.question(
            self,
            "숨긴 창 복원",
            f"이전 실행에서 숨긴 탐색기 창 {count}개가 남아 있습니다. 지금 복원할까요?",
        ) == QMessageBox.StandardButton.Yes:
            self.restore_all_hidden_windows()

    def _restore_hidden_windows_on_exit(self) -> tuple[int, int]:
        if self._hidden_windows_exit_restored:
            return (0, 0)
        self._hidden_windows_exit_restored = True
        return self.runner.restore_all_hidden_windows()

    def show_start_guide(self) -> None:
        memo_auto_save = self.note_store.setting(MEMO_AUTO_SAVE_SETTING, "true").lower() == "true"
        memo_description = (
            "입력한 내용이 자동 저장됩니다."
            if memo_auto_save
            else "Ctrl+S 또는 지금 저장 버튼으로 저장합니다."
        )
        dialog = StartJourneyDialog(
            [
                (
                    "⌨ 단축키 만들기", "문구, 사이트, 프로그램 또는 반복작업을 단축키로 실행합니다.",
                    "단축키 만들기", self._start_shortcut_journey,
                ),
                ("📝 빠른 메모", memo_description, "메모 쓰기", self._start_memo_journey),
                (
                    "🗓 일정 추가", "간단한 알림이나 D-Day 일정을 등록합니다.",
                    "일정 추가하기", self._start_schedule_journey,
                ),
            ],
            self,
        )
        dialog.exec()

    def _start_shortcut_journey(self) -> None:
        self.restore_from_tray()
        self._switch_workspace(0)
        self.new_action()

    def _start_memo_journey(self) -> None:
        self.restore_from_tray()
        self._switch_workspace(1)
        self.alert_panel.tabs.setCurrentIndex(0)
        self.alert_panel.create_note()

    def _start_schedule_journey(self) -> None:
        self.restore_from_tray()
        self._switch_workspace(1)
        self.alert_panel.tabs.setCurrentIndex(1)
        self.alert_panel.calendar._new_schedule()

    def show_trash(self) -> None:
        items: list[dict] = []
        for row in self.store.trashed_actions():
            action_id = int(row["id"])
            items.append({
                "kind": "단축키 작업", "id": action_id, "title": str(row["name"]),
                "deleted_at": str(row["deleted_at"]),
                "restore": lambda value=action_id: self.store.restore_action(value),
            })
        for row in self.note_store.trashed_notes():
            note_id = int(row["id"])
            items.append({
                "kind": "메모", "id": note_id, "title": str(row["title"]),
                "deleted_at": str(row["deleted_at"]),
                "restore": lambda value=note_id: self.note_store.restore_note(value),
            })
        for row in self.note_store.schedules.trashed_items():
            item_id = int(row["id"])
            items.append({
                "kind": "일정", "id": item_id, "title": str(row["title"]),
                "deleted_at": str(row["deleted_at"]),
                "restore": lambda value=item_id: self.note_store.schedules.restore_item(value),
            })
        dialog = TrashDialog(sorted(items, key=lambda item: item["deleted_at"], reverse=True), self)
        dialog.exec()
        self.refresh()
        self.alert_panel.refresh()
        self.alert_panel.calendar.refresh()
        self.register_hotkeys(False)

    def exit_application(self) -> None:
        if self.close():
            QApplication.instance().quit()

    def _build_table_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("tablePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        title_row = QHBoxLayout()
        title = QLabel("단축키 작업")
        title.setObjectName("pageTitle")
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title_block.addWidget(title)
        self.action_count_label = QLabel()
        self.action_count_label.setObjectName("workspaceSubtitle")
        apply_numeric_font(self.action_count_label)
        title_block.addWidget(self.action_count_label)
        title_row.addLayout(title_block)
        title_row.addStretch()
        # 늘 떠 있던 단추 줄과 등록 상태 줄을 걷었다.  두 줄이 비는 만큼 아래
        # 목록이 길어진다.  지우기만 제목 줄로 올리고, 나머지는 줄에서 오른쪽
        # 단추로 부른다.
        self._button(title_row, "삭제", self.delete_action)
        self.delete_action_button = title_row.itemAt(title_row.count() - 1).widget()
        self.delete_action_button.setObjectName("dangerButton")
        self._button(title_row, "＋ 새 작업", self.new_action)
        self.new_action_button = title_row.itemAt(title_row.count() - 1).widget()
        self.new_action_button.setObjectName("primaryButton")
        layout.addLayout(title_row)
        self._build_row_menu()
        filters = QHBoxLayout()
        self.active_filter = QComboBox()
        self.active_filter.addItem("전체 상태", "all")
        self.active_filter.addItem("활성", "active")
        self.active_filter.addItem("비활성", "inactive")
        self.active_filter.setMaximumWidth(110)
        self.active_filter.setAccessibleName("활성 상태 필터")
        self.type_filter = QComboBox()
        self.type_filter.addItem("모든 작업", "all")
        for action_type, label in ACTION_LABELS.items():
            self.type_filter.addItem(label, action_type)
        self.type_filter.setMaximumWidth(145)
        self.type_filter.setAccessibleName("작업 유형 필터")
        filters.addWidget(self.active_filter)
        filters.addWidget(self.type_filter)
        self.action_search = QLineEdit()
        self.action_search.setPlaceholderText("이름·단축키·작업 검색")
        self.action_search.setClearButtonEnabled(True)
        self.action_search.setMaximumWidth(230)
        self.action_search.setAccessibleName("작업 검색")
        self.action_search.textChanged.connect(self._filter_actions)
        self.active_filter.currentIndexChanged.connect(lambda: self._filter_actions(self.action_search.text()))
        self.type_filter.currentIndexChanged.connect(lambda: self._filter_actions(self.action_search.text()))
        filters.addWidget(self.action_search, 1)
        layout.addLayout(filters)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "ID", "활성", "이름", "단축키", "작업", "상태"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setAccessibleName("단축키 작업 목록")
        self.table_header = SelectAllHeader(self.table)
        self.table.setHorizontalHeader(self.table_header)
        for column in range(0, 3):
            self.table_header.setSectionResizeMode(column, SelectAllHeader.ResizeMode.Fixed)
        for column in range(3, 7):
            self.table_header.setSectionResizeMode(column, SelectAllHeader.ResizeMode.Interactive)
        self.table_header.setMinimumSectionSize(38)
        # ID 는 프로그램이 쓰는 번호다.  자리만 차지하므로 감추되, 줄을 찾는
        # 열쇠로는 그대로 쓴다.  머리글을 새로 끼우면 감춘 상태가 풀리므로
        # 반드시 그다음에 감춘다.
        self.table.setColumnHidden(ID_COLUMN, True)
        self.table.setItemDelegateForColumn(6, RegistrationDotDelegate(self.table))
        self._restore_table_column_widths()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        # Make the sortable headers behave like a spreadsheet: they can be
        # clicked and always show which column/direction is currently active.
        self.table_header.setSectionsClickable(True)
        self.table_header.setSortIndicatorShown(True)
        self.table_header.setSortIndicator(1, Qt.SortOrder.AscendingOrder)
        self.table.itemSelectionChanged.connect(self.load_selected)
        self.table.itemChanged.connect(self._sync_select_all_state)
        self.table_header.check_state_changed.connect(self._set_all_checked)
        self.table_header.sectionResized.connect(self._on_table_column_resized)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)
        layout.addWidget(self.table)
        self.empty_search_label = QLabel("검색 결과가 없습니다. 상태·작업 필터나 검색어를 지워 보세요.")
        self.empty_search_label.setObjectName("emptySearch")
        self.empty_search_label.setWordWrap(True)
        self.empty_search_label.hide()
        layout.addWidget(self.empty_search_label)
        return panel

    def _build_form_panel(self) -> QWidget:
        panel = QScrollArea()
        panel.setObjectName("formScroll")
        panel.setWidgetResizable(True)
        panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("formPanel")
        self.form_content = content
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(5)
        title_row = QHBoxLayout()
        title = QLabel("작업 편집")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        # 등록에 실패한 것이 있을 때만 뜨는 한 줄.  제목 옆에 붙으므로 자리를
        # 새로 차지하지 않는다.  ‘실패 상세’를 누르면 목록이 뜬다.
        self.registration_notice = QLabel()
        self.registration_notice.setObjectName("registrationNotice")
        self.registration_notice.setTextFormat(Qt.TextFormat.RichText)
        self.registration_notice.setOpenExternalLinks(False)
        self.registration_notice.setAccessibleName("단축키 등록 실패 알림")
        self.registration_notice.linkActivated.connect(
            lambda _link: self.show_registration_failures()
        )
        self.registration_notice.hide()
        title_row.addWidget(self.registration_notice, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(title_row)
        self.status = QLabel()
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        form_card = QFrame()
        self.form_card = form_card
        form_card.setObjectName("editorCard")
        form = QGridLayout(form_card)
        form.setContentsMargins(12, 5, 12, 5)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(3)
        self.name_edit = QLineEdit()
        self.hotkey_edit = HotkeyBuilder()
        self.active_check = QCheckBox("활성화")
        self.type_combo = QComboBox()
        self.name_edit.setObjectName("compactEditorInput")
        self.type_combo.setObjectName("compactEditorInput")
        self.hotkey_edit.first_modifier.setObjectName("compactEditorInput")
        self.hotkey_edit.second_modifier.setObjectName("compactEditorInput")
        self.hotkey_edit.third_modifier.setObjectName("compactEditorInput")
        self.hotkey_edit.key_edit.setObjectName("compactEditorInput")
        for value, label in ACTION_LABELS.items():
            self.type_combo.addItem(label, value)
        self.type_combo.currentIndexChanged.connect(self._sync_stack)
        self._wheel_locked_combos = (
            self.type_combo,
            self.hotkey_edit.first_modifier,
            self.hotkey_edit.second_modifier,
            self.hotkey_edit.third_modifier,
        )
        self.form_grid = form
        self.name_field_label = QLabel("이름")
        self.state_field_label = QLabel("상태")
        self.type_field_label = QLabel("작업 유형")
        self.hotkey_field_label = QLabel("단축키")
        form.addWidget(self.name_field_label, 0, 0)
        form.addWidget(self.name_edit, 0, 1)
        form.addWidget(self.state_field_label, 0, 2)
        form.addWidget(self.active_check, 0, 3)
        form.addWidget(self.type_field_label, 0, 4)
        form.addWidget(self.type_combo, 0, 5)
        form.addWidget(self.hotkey_field_label, 1, 0)
        form.addWidget(self.hotkey_edit, 1, 1, 1, 5)
        self.hotkey_feedback = QLabel("원하는 조합을 한 번에 누르세요.")
        self.hotkey_feedback.setObjectName("secondaryText")
        self.hotkey_feedback.setWordWrap(True)
        form.addWidget(self.hotkey_feedback, 2, 1, 1, 5)
        self.hotkey_edit.changed.connect(self._update_hotkey_validation)
        form.setColumnStretch(1, 3)
        form.setColumnStretch(5, 1)
        layout.addWidget(form_card)
        self.stack = QStackedWidget()
        self._build_action_pages()
        layout.addWidget(self.stack)
        bottom = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.form_bottom_layout = bottom
        primary_actions = QHBoxLayout()
        self.form_save_button = self._button(primary_actions, "저장", self.save_action)
        self.form_save_button.setObjectName("primaryButton")
        self.form_save_button.setAccessibleDescription("현재 편집 내용을 저장하고 단축키 등록을 갱신합니다")
        self.form_excluded_apps_button = self._button(
            primary_actions, "제외 프로그램 선택", self.choose_excluded_apps
        )
        primary_actions.addStretch()
        bottom.addLayout(primary_actions)
        utility_actions = QHBoxLayout()
        self.utility_buttons = []
        for text, callback in (
            ("Excel 내보내기", self.export_excel),
            ("Excel 가져오기", self.import_excel),
        ):
            button = self._button(utility_actions, text, callback)
            button.setObjectName("compactUtilityButton")
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self.utility_buttons.append(button)
        utility_actions.addStretch()
        bottom.addLayout(utility_actions)
        layout.addLayout(bottom)
        panel.setWidget(content)
        return panel

    def _build_action_pages(self) -> None:
        self.text_edit = QTextEdit()
        self.text_enter_check = QCheckBox("입력 후 Enter")
        self.text_enter_check.setChecked(False)
        self.stack.addWidget(_page([QLabel("입력할 문구"), self.text_edit, self.text_enter_check]))
        self.url_edit = QLineEdit()
        self.stack.addWidget(_form_page("URL", self.url_edit))
        self.path_edit = QLineEdit()
        self.path_restore_check = QCheckBox("이미 열려 있고 최소화된 경우 창 복원")
        self.path_restore_check.setChecked(False)
        self.path_restore_check.setToolTip(
            "같은 프로그램 또는 탐색기 폴더 창이 최소화되어 있으면 새로 열지 않고 복원합니다."
        )
        self.stack.addWidget(self._path_page())
        macro_page = QWidget()
        macro_root = QVBoxLayout(macro_page)
        macro_root.setContentsMargins(0, 0, 0, 0)
        macro_root.setSpacing(8)
        self.advanced_json_toggle = QCheckBox("고급 설정: 매크로 JSON 직접 편집")
        self.advanced_json_toggle.setChecked(False)
        macro_root.addWidget(self.advanced_json_toggle)
        macro_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.macro_layout = macro_layout
        macro_layout.setContentsMargins(0, 0, 0, 0)
        macro_layout.setSpacing(10)
        macro_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        json_panel = QFrame()
        self.json_panel = json_panel
        json_panel.setObjectName("editorCard")
        json_layout = QVBoxLayout(json_panel)
        json_layout.setContentsMargins(12, 10, 12, 10)
        json_layout.setSpacing(7)
        json_title = QLabel("매크로 JSON 단계")
        json_title.setObjectName("sectionTitle")
        json_layout.addWidget(json_title)
        self.macro_edit = QTextEdit()
        self.macro_edit.setObjectName("macroEditor")
        self.macro_edit.setPlainText(_default_macro_json())
        self.macro_edit.setMinimumHeight(245)
        self.macro_edit.textChanged.connect(self._update_macro_summary)
        self.macro_edit.textChanged.connect(self._queue_macro_history_commit)
        json_layout.addWidget(self.macro_edit)
        macro_json_buttons = QHBoxLayout()
        self._button(macro_json_buttons, "반복작업 JSON 내보내기", self.export_macro_json)
        self._button(macro_json_buttons, "반복작업 JSON 가져오기", self.import_macro_json)
        json_layout.addLayout(macro_json_buttons)
        json_panel.setMinimumHeight(400)
        macro_layout.addWidget(json_panel, 3)
        self.advanced_json_toggle.toggled.connect(json_panel.setVisible)
        json_panel.setVisible(self.advanced_json_toggle.isChecked())

        settings_panel = QFrame()
        self.settings_panel = settings_panel
        settings_panel.setObjectName("macroSettingsPanel")
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(8)
        settings_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        recording_section = QGroupBox("녹화 제어")
        self.recording_section = recording_section
        recording_section.setObjectName("macroSectionCard")
        recording_section_layout = QVBoxLayout(recording_section)
        recording_section_layout.setContentsMargins(10, 10, 10, 8)
        recording_section_layout.setSpacing(5)
        self.recording_deck = QFrame()
        self.recording_deck.setObjectName("recordingDeck")
        self.recording_deck.setProperty("recording", False)
        recording_layout = QHBoxLayout(self.recording_deck)
        recording_layout.setContentsMargins(10, 4, 10, 4)
        recording_layout.setSpacing(7)
        self.record_start_button = self._button(recording_layout, "녹화 시작", self.start_recording)
        self.record_start_button.setObjectName("recordButton")
        self.record_start_button.setAccessibleDescription("외부 프로그램 조작 기록을 시작합니다")
        self.record_stop_button = self._button(recording_layout, "녹화 종료", self.stop_recording)
        self.record_stop_button.setObjectName("stopButton")
        self.record_stop_button.setAccessibleDescription("현재 녹화를 종료하고 기록된 동작을 가져옵니다")
        self.record_stop_button.setEnabled(False)
        self.recording_badge = QLabel("녹화 대기")
        self.recording_badge.setObjectName("recordingBadge")
        self.recording_badge.setProperty("recording", False)
        recording_layout.addWidget(self.recording_badge)
        recording_layout.addStretch()
        self.macro_excluded_apps_button = self._button(
            recording_layout, "제외 프로그램 선택", self.choose_excluded_apps
        )
        self.macro_save_button = self._button(recording_layout, "저장", self.save_action)
        self.macro_save_button.setObjectName("primaryButton")
        self.macro_save_button.setAccessibleDescription("현재 반복작업과 녹화 설정을 저장합니다")
        recording_section_layout.addWidget(self.recording_deck)
        macro_test_button = self._button(
            recording_section_layout, "▶ 저장 전 반복작업 테스트", self.test_macro_before_save
        )
        macro_test_button.setObjectName("testButton")
        macro_test_button.setAccessibleDescription("저장하기 전에 현재 속도와 반복 횟수로 실행합니다")
        hotkey_bar = QFrame()
        self.macro_hotkey_bar = hotkey_bar
        hotkey_bar.setObjectName("hotkeyBar")
        self.stop_hotkey_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.stop_hotkey_layout.setContentsMargins(8, 5, 8, 5)
        self.stop_hotkey_layout.setSpacing(7)
        hotkey_bar.setLayout(self.stop_hotkey_layout)
        hotkey_controls = QWidget()
        self.hotkey_controls_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.hotkey_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.hotkey_controls_layout.setSpacing(7)
        hotkey_controls.setLayout(self.hotkey_controls_layout)
        record_hotkey_controls = QWidget()
        record_hotkey_layout = QHBoxLayout(record_hotkey_controls)
        record_hotkey_layout.setContentsMargins(0, 0, 0, 0)
        record_hotkey_layout.setSpacing(7)
        playback_hotkey_controls = QWidget()
        playback_hotkey_layout = QHBoxLayout(playback_hotkey_controls)
        playback_hotkey_layout.setContentsMargins(0, 0, 0, 0)
        playback_hotkey_layout.setSpacing(7)
        self.record_stop_hotkey_label = QLabel()
        self.record_stop_hotkey_label.setObjectName("hotkeyChip")
        self.playback_stop_hotkey_label = QLabel()
        self.playback_stop_hotkey_label.setObjectName("hotkeyChip")
        apply_numeric_font(self.record_stop_hotkey_label)
        apply_numeric_font(self.playback_stop_hotkey_label)
        self._update_stop_hotkey_labels()
        record_hotkey_layout.addWidget(self.record_stop_hotkey_label)
        self.edit_record_stop_hotkey_button = self._button(
            record_hotkey_layout, "단축키 수정", self.edit_record_stop_hotkey
        )
        playback_hotkey_layout.addWidget(self.playback_stop_hotkey_label)
        self.edit_playback_stop_hotkey_button = self._button(
            playback_hotkey_layout, "단축키 수정", self.edit_playback_stop_hotkey
        )
        self.hotkey_controls_layout.addWidget(record_hotkey_controls)
        self.hotkey_controls_layout.addWidget(playback_hotkey_controls)
        self.hotkey_controls_layout.addStretch()
        self.stop_hotkey_layout.addWidget(hotkey_controls, 1)
        self.repeat_controls = QFrame()
        self.repeat_controls.setObjectName("repeatControls")
        repeat_layout = QHBoxLayout(self.repeat_controls)
        repeat_layout.setContentsMargins(8, 0, 2, 0)
        repeat_layout.setSpacing(6)
        repeat_label = QLabel("반복 횟수")
        repeat_label.setObjectName("repeatLabel")
        repeat_layout.addWidget(repeat_label)
        self.repeat_count_spin = QSpinBox()
        self.repeat_count_spin.setObjectName("repeatCountSpin")
        self.repeat_count_spin.setRange(MIN_REPEAT_COUNT, MAX_REPEAT_COUNT)
        self.repeat_count_spin.setValue(1)
        self.repeat_count_spin.setSuffix(" 회")
        self.repeat_count_spin.setAccessibleName("반복 횟수")
        self.repeat_count_spin.setAccessibleDescription("전체 반복작업을 실행할 횟수입니다")
        apply_numeric_font(self.repeat_count_spin)
        repeat_layout.addWidget(self.repeat_count_spin)
        self.stop_hotkey_layout.addWidget(self.repeat_controls, 0, Qt.AlignmentFlag.AlignRight)
        recording_section_layout.addWidget(hotkey_bar)
        settings_layout.addWidget(recording_section)

        self.macro_advanced_options_toggle = QCheckBox("고급 옵션: 종료 단축키·시간·반복 설정")
        self.macro_advanced_options_toggle.setChecked(False)
        self.macro_advanced_options_toggle.setAccessibleName("반복작업 고급 옵션 펼치기")
        settings_layout.addWidget(self.macro_advanced_options_toggle)

        timing_section = QGroupBox("시간 설정")
        self.timing_section = timing_section
        timing_section.setObjectName("macroSectionCard")
        timing_section_layout = QVBoxLayout(timing_section)
        timing_section_layout.setContentsMargins(10, 10, 10, 8)
        timing_section_layout.setSpacing(5)
        self._update_stop_hotkey_labels()
        self.macro_summary_label = QLabel()
        self.macro_summary_label.setObjectName("macroSummary")
        self.macro_summary_label.setWordWrap(True)
        self.macro_summary_label.setMinimumWidth(0)
        self.macro_summary_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        timing_section_layout.addWidget(self.macro_summary_label)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(50, 1000)
        self.speed_slider.setSingleStep(10)
        self.speed_slider.setValue(100)
        self.speed_reset_button = QPushButton()
        polish_button(self.speed_reset_button)
        self.speed_reset_button.setObjectName("speedResetButton")
        self.speed_reset_button.setToolTip("클릭하면 기본 속도 1.0배로 복원합니다.")
        self.speed_reset_button.setAccessibleName("기본 속도로 복원")
        self.speed_reset_button.clicked.connect(lambda: self.speed_slider.setValue(100))
        apply_numeric_font(self.speed_reset_button)
        self.speed_label = self.speed_reset_button
        self.speed_slider.valueChanged.connect(self._sync_timing_controls)
        self.speed_slider.valueChanged.connect(self._queue_macro_history_commit)
        self.repeat_count_spin.valueChanged.connect(self._sync_timing_controls)
        self.repeat_count_spin.valueChanged.connect(self._queue_macro_history_commit)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(self.speed_reset_button)
        timing_section_layout.addLayout(speed_row)
        timing_actions = QHBoxLayout()
        edit_delays_button = self._button(timing_actions, "단계별 시간 편집", self.edit_step_delays)
        edit_delays_button.setToolTip("JSON의 wait 단계를 표 형태로 편집합니다.")
        self.restore_macro_button = self._button(
            timing_actions, "초기화", self.restore_original_macro
        )
        self.restore_macro_button.setToolTip("현재 반복작업을 불러오거나 마지막으로 저장한 상태로 초기화합니다.")
        self.restore_macro_button.setEnabled(False)
        self.macro_undo_button = self._button(timing_actions, "↶", self.undo_macro_edit)
        self.macro_undo_button.setToolTip("되돌리기")
        self.macro_undo_button.setAccessibleName("되돌리기")
        self.macro_undo_button.setAccessibleDescription("반복작업 편집을 한 단계 이전 상태로 되돌립니다")
        self.macro_undo_button.setMinimumWidth(38)
        self.macro_undo_button.setMaximumWidth(44)
        self.macro_undo_button.setEnabled(False)
        self.macro_redo_button = self._button(timing_actions, "↷", self.redo_macro_edit)
        self.macro_redo_button.setToolTip("다시 실행")
        self.macro_redo_button.setAccessibleName("다시 실행")
        self.macro_redo_button.setAccessibleDescription("되돌린 반복작업 편집을 한 단계 다시 실행합니다")
        self.macro_redo_button.setMinimumWidth(38)
        self.macro_redo_button.setMaximumWidth(44)
        self.macro_redo_button.setEnabled(False)
        timing_actions.addStretch()
        timing_section_layout.addLayout(timing_actions)
        settings_layout.addWidget(timing_section)
        self.macro_advanced_options_toggle.toggled.connect(self.macro_hotkey_bar.setVisible)
        self.macro_advanced_options_toggle.toggled.connect(timing_section.setVisible)
        self.macro_hotkey_bar.hide()
        timing_section.hide()

        help_section = QGroupBox("도움말")
        self.help_section = help_section
        help_section.setObjectName("macroSectionCard")
        help_section_layout = QVBoxLayout(help_section)
        help_section_layout.setContentsMargins(10, 8, 10, 8)
        help_section_layout.setSpacing(4)
        self.recording_help_toggle = self._button(
            help_section_layout, "▸ 도움말 펼치기", self.toggle_recording_help
        )
        self.recording_help_toggle.setObjectName("helpDisclosureButton")
        self.recording_help_toggle.setCheckable(True)
        self.recording_help_panel = QFrame()
        self.recording_help_panel.setObjectName("helpDisclosurePanel")
        help_layout = QVBoxLayout(self.recording_help_panel)
        help_layout.setContentsMargins(10, 8, 10, 8)
        self.recording_help_label = QLabel()
        self.recording_help_label.setWordWrap(True)
        help_layout.addWidget(self.recording_help_label)
        self.recording_help_panel.setVisible(False)
        help_section_layout.addWidget(self.recording_help_panel)
        settings_layout.addWidget(help_section)
        self._update_stop_hotkey_labels()
        settings_panel.setMinimumHeight(0)
        self._sync_timing_controls()
        macro_layout.addWidget(settings_panel, 2)
        macro_root.addLayout(macro_layout)
        self.stack.addWidget(macro_page)
        self.stack.addWidget(self._layout_page())
        self._sync_stack()
        self._sync_excluded_apps_buttons()

    def _path_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow("경로", self.path_edit)
        layout.addLayout(form)
        layout.addWidget(self.path_restore_check)
        row = QHBoxLayout()
        self._button(row, "파일 선택", self.pick_file)
        self._button(row, "폴더 선택", self.pick_folder)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        return page

    def _layout_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        capture_row = QHBoxLayout()
        self.layout_capture_button = self._button(
            capture_row, "＋ 지금 열린 창 불러오기", self.capture_layout_windows
        )
        self.layout_capture_button.setAccessibleDescription(
            "현재 열린 파일 탐색기 창의 폴더와 화면 위치를 목록으로 불러옵니다"
        )
        self.layout_status_label = QLabel("탐색기 창을 불러온 뒤 저장할 창을 선택하세요.")
        self.layout_status_label.setObjectName("secondaryText")
        capture_row.addWidget(self.layout_status_label, 1)
        root.addLayout(capture_row)

        self.layout_table = QTableWidget(0, 6)
        self.layout_table.setObjectName("layoutWindowTable")
        self.layout_table.setHorizontalHeaderLabels(
            ["사용", "폴더", "모니터", "위치·크기", "열기 방식", "순서·삭제"]
        )
        self.layout_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.layout_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.layout_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.layout_table.verticalHeader().setVisible(False)
        self.layout_table.setMinimumHeight(180)
        header = self.layout_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.layout_table, 1)
        return page

    def capture_layout_windows(self) -> None:
        try:
            windows = [item for item in collect_open_windows() if item.get("explorer_path")]
        except Exception as exc:
            self.layout_status_label.setText(f"창을 불러오지 못했습니다: {exc}")
            return
        rows = [self._layout_payload_from_window(item) for item in windows]
        self._set_layout_rows(rows)
        if rows:
            self.layout_status_label.setText(f"탐색기 창 {len(rows)}개를 불러왔습니다.")
        else:
            self.layout_status_label.setText("현재 열린 파일 탐색기 창이 없습니다.")

    @staticmethod
    def _layout_payload_from_window(window: dict) -> dict:
        payload = {
            "kind": "explorer",
            "path": str(window.get("explorer_path", "") or ""),
            "monitor": int(window.get("monitor", 0) or 0),
            "rect": list(window.get("rect", [0, 0, 1, 1])),
            "state": str(window.get("state", "normal") or "normal"),
            "always_new": False,
        }
        if "rect_basis" in window:
            payload["rect_basis"] = str(window.get("rect_basis", "window") or "window")
        if window.get("monitor_device"):
            payload["monitor_device"] = str(window["monitor_device"])
        if "work_area" in window:
            payload["work_area"] = list(window.get("work_area") or [])
        if "dpi" in window:
            payload["dpi"] = int(window.get("dpi", 96) or 96)
        return payload

    def _set_layout_rows(self, windows) -> None:
        self.layout_table.setRowCount(0)
        for value in windows if isinstance(windows, list) else []:
            if not isinstance(value, dict):
                continue
            row_value = dict(value)
            selected = bool(row_value.pop("_selected", True))
            row = self.layout_table.rowCount()
            self.layout_table.insertRow(row)

            use_item = QTableWidgetItem()
            use_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            use_item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
            use_item.setData(Qt.ItemDataRole.UserRole, row_value)
            self.layout_table.setItem(row, 0, use_item)

            path = str(row_value.get("path", "") or "")
            folder_name = Path(path).name or path
            folder_item = QTableWidgetItem(folder_name)
            folder_item.setToolTip(path)
            self.layout_table.setItem(row, 1, folder_item)
            self.layout_table.setItem(
                row, 2, QTableWidgetItem(f"모니터 {int(row_value.get('monitor', 0) or 0)}")
            )
            rect = list(row_value.get("rect", [0, 0, 1, 1]))
            while len(rect) < 4:
                rect.append(0)
            self.layout_table.setItem(
                row, 3, QTableWidgetItem(f"{rect[0]}, {rect[1]} · {rect[2]}×{rect[3]}")
            )

            always_new = QCheckBox("항상 새 창으로 열기")
            always_new.setChecked(bool(row_value.get("always_new", False)))
            always_new.setAccessibleName(f"{folder_name} 항상 새 창으로 열기")
            self.layout_table.setCellWidget(row, 4, always_new)

            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(2)
            up = QPushButton("↑")
            down = QPushButton("↓")
            remove = QPushButton("삭제")
            for button in (up, down, remove):
                polish_button(button)
                actions_layout.addWidget(button)
            up.setAccessibleName(f"{folder_name} 위로 이동")
            down.setAccessibleName(f"{folder_name} 아래로 이동")
            remove.setAccessibleName(f"{folder_name} 행 삭제")
            up.clicked.connect(lambda _checked=False, button=up: self._move_layout_row(button, -1))
            down.clicked.connect(lambda _checked=False, button=down: self._move_layout_row(button, 1))
            remove.clicked.connect(lambda _checked=False, button=remove: self._delete_layout_row(button))
            self.layout_table.setCellWidget(row, 5, actions)
            self.layout_table.setRowHeight(row, 32)

    def _layout_row_states(self) -> list[dict]:
        result = []
        for row in range(self.layout_table.rowCount()):
            use_item = self.layout_table.item(row, 0)
            value = dict(use_item.data(Qt.ItemDataRole.UserRole) or {})
            always_new = self.layout_table.cellWidget(row, 4)
            value["always_new"] = bool(always_new and always_new.isChecked())
            value["_selected"] = use_item.checkState() == Qt.CheckState.Checked
            result.append(value)
        return result

    def _layout_windows(self, selected_only: bool = True) -> list[dict]:
        result = []
        for value in self._layout_row_states():
            selected = bool(value.pop("_selected", False))
            if selected or not selected_only:
                result.append(value)
        return result

    def _layout_row_for_button(self, button: QPushButton) -> int:
        for row in range(self.layout_table.rowCount()):
            host = self.layout_table.cellWidget(row, 5)
            if host is not None and button in host.findChildren(QPushButton):
                return row
        return -1

    def _move_layout_row(self, button: QPushButton, offset: int) -> None:
        row = self._layout_row_for_button(button)
        target = row + offset
        if row < 0 or target < 0 or target >= self.layout_table.rowCount():
            return
        rows = self._layout_row_states()
        rows[row], rows[target] = rows[target], rows[row]
        self._set_layout_rows(rows)
        self.layout_table.selectRow(target)

    def _delete_layout_row(self, button: QPushButton) -> None:
        row = self._layout_row_for_button(button)
        if row >= 0:
            self.layout_table.removeRow(row)

    def _button(self, layout, text: str, callback, *position) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(callback)
        polish_button(button)
        layout.addWidget(button, *position)
        return button

    def _sync_stack(self) -> None:
        self.stack.setCurrentIndex(self.type_combo.currentIndex())
        action_type = self.type_combo.currentData()
        is_macro = action_type == "macro"
        if hasattr(self, "macro_save_button"):
            self.macro_save_button.setVisible(is_macro)
        if hasattr(self, "form_save_button"):
            self.form_save_button.setVisible(not is_macro)
        if hasattr(self, "form_excluded_apps_button"):
            self.form_excluded_apps_button.setVisible(action_type in {"text", "url", "path"})

    def toggle_recording_help(self, expanded: bool) -> None:
        self.recording_help_panel.setVisible(expanded)
        self.recording_help_toggle.setText("▾ 도움말 접기" if expanded else "▸ 도움말 펼치기")

    def choose_excluded_apps(self) -> None:
        dialog = ExcludedAppsDialog(self.excluded_apps, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.excluded_apps = dialog.selected_apps()
        self._sync_excluded_apps_buttons()
        self._set_status(
            f"제외 프로그램 {len(self.excluded_apps)}개를 선택했습니다. 저장해야 작업에 적용됩니다.",
            "info",
        )

    def _sync_excluded_apps_buttons(self) -> None:
        count = len(self.excluded_apps)
        text = f"제외 프로그램 선택 ({count})" if count else "제외 프로그램 선택"
        for name in ("form_excluded_apps_button", "macro_excluded_apps_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setText(text)

    def show_help(self) -> None:
        """설명서는 지금 쓰는 실제 단축키를 그대로 보여 준다."""
        UserManualDialog(
            self,
            hotkeys={
                "main_open": self.main_open_hotkey,
                "tray_hide": self.tray_hide_hotkey,
                "exit_key": self.exit_hotkey,
                "quick_memo": self.quick_memo_hotkey,
                "new_memo": self.new_memo_hotkey,
                "today_view": self.today_view_hotkey,
                "memo_search": self.memo_search_hotkey,
                "quick_schedule": self.quick_schedule_hotkey,
                "record_stop": self._record_stop_hotkey_from_store(),
                "playback_stop": self._playback_stop_hotkey_from_store(),
            },
        ).exec()

    def show_settings(self) -> None:
        existing = getattr(self, "_settings_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        schedule_postit_preferences = SchedulePostitPreferences.load(self.note_store)
        dialog = SettingsDialog(
            hotkeys={
                EXIT_HOTKEY_SETTING: self.exit_hotkey,
                MAIN_OPEN_HOTKEY_SETTING: self.main_open_hotkey,
                TRAY_HIDE_HOTKEY_SETTING: self.tray_hide_hotkey,
                RECORD_STOP_HOTKEY_SETTING: self.record_stop_hotkey,
                PLAYBACK_STOP_HOTKEY_SETTING: self.playback_stop_hotkey,
                QUICK_MEMO_HOTKEY_SETTING: self.quick_memo_hotkey,
                NEW_MEMO_HOTKEY_SETTING: self.new_memo_hotkey,
                TODAY_VIEW_HOTKEY_SETTING: self.today_view_hotkey,
                MEMO_SEARCH_HOTKEY_SETTING: self.memo_search_hotkey,
                QUICK_SCHEDULE_HOTKEY_SETTING: self.quick_schedule_hotkey,
                WINDOW_PIN_HOTKEY_SETTING: self.window_pin_hotkey,
                SHORTCUT_OVERLAY_HOTKEY_SETTING: self.shortcut_overlay_hotkey,
            },
            startup_mode=self.startup_mode,
            data_dir=self.store.data_dir,
            backup_dir=self.store.backup_dir,
            action_hotkeys=self._content_hotkeys(),
            on_full_backup=self.export_backup,
            on_full_restore=self.import_backup,
            pet_alert_enabled=self.pet_controller.alert_enabled,
            pet_persistent_enabled=self.pet_controller.persistent_enabled,
            memo_auto_save_enabled=(
                self.note_store.setting(MEMO_AUTO_SAVE_SETTING, "true").lower() == "true"
            ),
            show_start_guide_on_launch=(
                self.store.setting(SHOW_START_GUIDE_SETTING, "true").lower() == "true"
            ),
            explorer_double_click_enabled=(
                self.store.setting(EXPLORER_DBLCLICK_SETTING, "true").lower() == "true"
            ),
            explorer_middle_click_enabled=(
                self.store.setting(EXPLORER_MIDDLE_CLICK_SETTING, "true").lower()
                == "true"
            ),
            deadline_options=self.deadline_options(),
            schedule_postit_options=schedule_postit_preferences.__dict__,
            parent=self,
        )
        # 설정창을 띄운 채로 빠른 메모나 검색 창도 쓸 수 있어야 한다.  exec()
        # 는 프로그램 전체를 막아 두므로 쓰지 않고, 저장을 누른 다음에 할 일을
        # 신호로 이어 둔다.
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.accepted.connect(lambda: self._apply_settings(dialog))
        dialog.finished.connect(self._forget_settings_dialog)
        self._settings_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _forget_settings_dialog(self, *_args) -> None:
        """창을 닫으면 붙잡고 있던 자리를 놓는다.

        deleteLater 는 신호가 모두 지나간 뒤에 지우므로, 이어서 도는
        _apply_settings 는 창을 그대로 읽을 수 있다.
        """
        dialog = getattr(self, "_settings_dialog", None)
        self._settings_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _apply_settings(self, dialog) -> None:
        values = dialog.values()
        new_data_dir = Path(values["data_dir"])
        data_changed = not same_path(new_data_dir, self.store.data_dir)
        self.exit_hotkey = values.get(EXIT_HOTKEY_SETTING, self.exit_hotkey)
        values[EXIT_HOTKEY_SETTING] = self.exit_hotkey
        self.main_open_hotkey = values[MAIN_OPEN_HOTKEY_SETTING]
        self.tray_hide_hotkey = values[TRAY_HIDE_HOTKEY_SETTING]
        self.record_stop_hotkey = values[RECORD_STOP_HOTKEY_SETTING]
        self.playback_stop_hotkey = values[PLAYBACK_STOP_HOTKEY_SETTING]
        self.quick_memo_hotkey = values.get(QUICK_MEMO_HOTKEY_SETTING, self.quick_memo_hotkey)
        self.new_memo_hotkey = values.get(NEW_MEMO_HOTKEY_SETTING, self.new_memo_hotkey)
        self.today_view_hotkey = values.get(TODAY_VIEW_HOTKEY_SETTING, self.today_view_hotkey)
        self.memo_search_hotkey = values.get(MEMO_SEARCH_HOTKEY_SETTING, self.memo_search_hotkey)
        self.quick_schedule_hotkey = values.get(
            QUICK_SCHEDULE_HOTKEY_SETTING, self.quick_schedule_hotkey
        )
        self.window_pin_hotkey = values.get(
            WINDOW_PIN_HOTKEY_SETTING, self.window_pin_hotkey
        )
        self.shortcut_overlay_hotkey = values.get(
            SHORTCUT_OVERLAY_HOTKEY_SETTING, self.shortcut_overlay_hotkey
        )
        values[QUICK_MEMO_HOTKEY_SETTING] = self.quick_memo_hotkey
        values[NEW_MEMO_HOTKEY_SETTING] = self.new_memo_hotkey
        values[TODAY_VIEW_HOTKEY_SETTING] = self.today_view_hotkey
        values[MEMO_SEARCH_HOTKEY_SETTING] = self.memo_search_hotkey
        values[QUICK_SCHEDULE_HOTKEY_SETTING] = self.quick_schedule_hotkey
        values[WINDOW_PIN_HOTKEY_SETTING] = self.window_pin_hotkey
        values[SHORTCUT_OVERLAY_HOTKEY_SETTING] = self.shortcut_overlay_hotkey
        self.startup_mode = values["startup_mode"]
        for key in (
            EXIT_HOTKEY_SETTING,
            MAIN_OPEN_HOTKEY_SETTING,
            TRAY_HIDE_HOTKEY_SETTING,
            RECORD_STOP_HOTKEY_SETTING,
            PLAYBACK_STOP_HOTKEY_SETTING,
            QUICK_MEMO_HOTKEY_SETTING,
            NEW_MEMO_HOTKEY_SETTING,
            TODAY_VIEW_HOTKEY_SETTING,
            MEMO_SEARCH_HOTKEY_SETTING,
            QUICK_SCHEDULE_HOTKEY_SETTING,
            WINDOW_PIN_HOTKEY_SETTING,
            SHORTCUT_OVERLAY_HOTKEY_SETTING,
        ):
            self.store.set_setting(key, values[key])
        self.store.set_setting(STARTUP_MODE_SETTING, self.startup_mode)
        self.store.set_setting(
            SHOW_START_GUIDE_SETTING,
            "true" if values.get("show_start_guide_on_launch", True) else "false",
        )
        self._set_explorer_double_click_enabled(
            bool(values.get("explorer_double_click_enabled", True))
        )
        self._set_explorer_middle_click_enabled(
            bool(values.get("explorer_middle_click_enabled", True))
        )
        for key, default in DEADLINE_SETTING_DEFAULTS.items():
            self.note_store.set_setting(
                key, "true" if values.get(key, default) else "false"
            )
        schedule_postit_preferences = values.get("schedule_postit_preferences")
        if not isinstance(schedule_postit_preferences, SchedulePostitPreferences):
            schedule_postit_preferences = SchedulePostitPreferences.load(self.note_store)
        schedule_postit_preferences.save(self.note_store)
        self.schedule_postit_hotkey = schedule_postit_preferences.hotkey
        self.alert_panel.apply_schedule_postit_preferences(schedule_postit_preferences)
        # Counting and dimming are display conventions: redraw everything at once.
        self.apply_deadline_counting()
        self.alert_panel.refresh()
        memo_auto_save = bool(values.get("memo_auto_save_enabled", True))
        self.note_store.set_setting(MEMO_AUTO_SAVE_SETTING, "true" if memo_auto_save else "false")
        self.alert_panel.set_auto_save_enabled(memo_auto_save)
        self.pet_controller.set_preferences(
            values.get("toma_pet_alert_enabled", self.pet_controller.alert_enabled),
            values.get("toma_pet_persistent_enabled", self.pet_controller.persistent_enabled),
            reset_position=values.get("reset_toma_pet_position", False),
        )
        try:
            preserved_databases: list[Path] = []
            if data_changed:
                merge_storage_files(self.store.data_dir, new_data_dir)
                preserved_databases = copy_databases_preserving_existing(
                    new_data_dir,
                    {
                        "hotkeys.db": self.store.backup_database,
                        "alert_notes.db": self.note_store.backup_database,
                    },
                    finalize=lambda: save_storage_paths(new_data_dir),
                )
            else:
                save_storage_paths(new_data_dir)
            self.store.backup_dir = new_data_dir
        except OSError as exc:
            QMessageBox.warning(self, "저장 위치 변경 실패", str(exc))
            return
        self.runner.set_stop_hotkey(self.playback_stop_hotkey)
        self._update_stop_hotkey_labels()
        if data_changed:
            preserved_message = ""
            if preserved_databases:
                preserved_names = ", ".join(path.name for path in preserved_databases)
                preserved_message = f"\n기존 DB 보존: {preserved_names}\n"
            QMessageBox.information(
                self,
                "데이터 폴더 변경 완료",
                f"현재 데이터를 새 폴더로 복사했습니다.\n{new_data_dir}\n\n"
                f"{preserved_message}"
                "프로그램을 종료합니다. 다시 실행하면 새 위치가 적용됩니다.",
            )
            QApplication.instance().quit()
            return
        if self.register_hotkeys(show_message=True, success_message="설정이 저장되었습니다."):
            self._set_status("설정을 저장하고 전역 단축키를 갱신했습니다.", "success")

    def _configure_explorer_double_click_from_store(self) -> None:
        self._explorer_double_click_enabled = (
            self.store.setting(EXPLORER_DBLCLICK_SETTING, "true").strip().casefold()
            == "true"
        )
        self._explorer_middle_click_enabled = (
            self.store.setting(EXPLORER_MIDDLE_CLICK_SETTING, "true").strip().casefold()
            == "true"
        )
        self._sync_explorer_mouse_hook()

    def _set_explorer_double_click_enabled(
        self, enabled: bool, *, persist: bool = True
    ) -> None:
        self._explorer_double_click_enabled = bool(enabled)
        self._sync_explorer_mouse_hook()
        if persist:
            self.store.set_setting(
                EXPLORER_DBLCLICK_SETTING, "true" if enabled else "false"
            )

    def _set_explorer_middle_click_enabled(
        self, enabled: bool, *, persist: bool = True
    ) -> None:
        self._explorer_middle_click_enabled = bool(enabled)
        self._sync_explorer_mouse_hook()
        if persist:
            self.store.set_setting(
                EXPLORER_MIDDLE_CLICK_SETTING, "true" if enabled else "false"
            )

    def _sync_explorer_mouse_hook(self) -> None:
        navigator = getattr(self, "_explorer_double_click_navigator", None)
        double_enabled = bool(getattr(self, "_explorer_double_click_enabled", False))
        middle_enabled = bool(getattr(self, "_explorer_middle_click_enabled", False))
        if (double_enabled or middle_enabled) and navigator is None:
            navigator = ExplorerDoubleClickNavigator(
                recording_provider=lambda: self._recording,
                double_click_enabled=double_enabled,
                middle_click_enabled=middle_enabled,
            )
            navigator.start()
            self._explorer_double_click_navigator = navigator
        elif not (double_enabled or middle_enabled) and navigator is not None:
            navigator.stop()
            self._explorer_double_click_navigator = None
        elif navigator is not None:
            navigator.configure_features(
                double_click_enabled=double_enabled,
                middle_click_enabled=middle_enabled,
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "alert_panel"):
            self.alert_panel.update_responsive_layout(self.width())
        QTimer.singleShot(0, self._update_responsive_layout)

    def _splitter_setting_key(self, orientation: str) -> str:
        return f"main_splitter_{orientation}_sizes"

    def _splitter_ratio_setting_key(self, orientation: str) -> str:
        return f"main_splitter_{orientation}_ratio"

    def _restore_window_geometry(self) -> None:
        encoded = self.store.setting("main_window_geometry", "")
        if not encoded:
            return
        geometry = QByteArray.fromBase64(QByteArray(encoded.encode("ascii")))
        if self.restoreGeometry(geometry):
            self._keep_window_on_screen()

    def _save_window_geometry(self) -> None:
        encoded = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.store.set_setting("main_window_geometry", encoded)

    def _restore_table_column_widths(self) -> None:
        self._apply_table_column_ratios()

    def _set_table_column_widths(self, widths: list[int]) -> None:
        self._restoring_column_widths = True
        try:
            for column, width in enumerate(widths):
                self.table.setColumnWidth(column, int(width))
        finally:
            self._restoring_column_widths = False

    def _save_table_column_widths(self, *_args) -> None:
        if self._restoring_column_widths or not hasattr(self, "table"):
            return
        widths = [self.table.columnWidth(column) for column in range(self.table.columnCount())]
        self.store.set_setting(TABLE_COLUMN_WIDTHS_SETTING, json.dumps(widths))

    def _migrated_column_ratios(self, ratios: list[float]) -> list[float]:
        """Replace untouched legacy ratios with the wider name column, once."""
        if self.store.setting(TABLE_COLUMN_RATIOS_VERSION_SETTING, "") == TABLE_COLUMN_RATIOS_VERSION:
            return ratios
        self.store.set_setting(TABLE_COLUMN_RATIOS_VERSION_SETTING, TABLE_COLUMN_RATIOS_VERSION)
        untouched = False
        for widths in (LEGACY_FLEXIBLE_COLUMN_WIDTHS, PREVIOUS_FLEXIBLE_COLUMN_WIDTHS):
            total = sum(widths)
            expected = [width / total for width in widths]
            if all(abs(value - want) <= 0.015 for value, want in zip(ratios, expected)):
                untouched = True
                break
        if not untouched:
            return ratios
        default_total = sum(DEFAULT_COLUMN_WIDTHS[3:7])
        migrated = [width / default_total for width in DEFAULT_COLUMN_WIDTHS[3:7]]
        self.store.set_setting(TABLE_COLUMN_RATIOS_SETTING, json.dumps(migrated))
        return migrated

    def _table_column_ratios(self) -> list[float]:
        raw_value = self.store.setting(TABLE_COLUMN_RATIOS_SETTING, "")
        try:
            values = json.loads(raw_value)
            ratios = [float(value) for value in values]
        except (TypeError, ValueError, json.JSONDecodeError):
            ratios = []
        if len(ratios) == 4 and all(value > 0 for value in ratios):
            total = sum(ratios)
            normalized = [value / total for value in ratios]
            return self._migrated_column_ratios(normalized)
        if len(ratios) == 3 and all(value > 0 for value in ratios):
            total = sum(ratios)
            migrated = [(value / total) * 0.82 for value in ratios] + [0.18]
            self.store.set_setting(TABLE_COLUMN_RATIOS_SETTING, json.dumps(migrated))
            return migrated

        legacy = self.store.setting(TABLE_COLUMN_WIDTHS_SETTING, "")
        try:
            widths = json.loads(legacy)
            flexible = [max(1, int(value)) for value in widths[3:7]]
            if len(flexible) == 3:
                flexible.append(DEFAULT_COLUMN_WIDTHS[6])
        except (TypeError, ValueError, json.JSONDecodeError):
            flexible = DEFAULT_COLUMN_WIDTHS[3:7]
        if len(flexible) != 4:
            flexible = DEFAULT_COLUMN_WIDTHS[3:7]
        total = sum(flexible)
        ratios = [value / total for value in flexible]
        self.store.set_setting(TABLE_COLUMN_RATIOS_SETTING, json.dumps(ratios))
        return ratios

    def _apply_table_column_ratios(self) -> None:
        if not hasattr(self, "table"):
            return
        viewport_width = self.table.viewport().width()
        if viewport_width < 240:
            return
        fixed = [
            round(DEFAULT_COLUMN_WIDTHS[index] * self._ui_scale)
            for index in range(3)
        ]
        remaining = max(152, viewport_width - sum(fixed) - 2)
        ratios = self._table_column_ratios()
        flexible = [max(38, round(remaining * ratio)) for ratio in ratios[:-1]]
        flexible.append(max(38, remaining - sum(flexible)))
        self._set_table_column_widths([*fixed, *flexible])

    def _on_table_column_resized(self, logical_index: int, _old_size: int, _new_size: int) -> None:
        if self._restoring_column_widths or logical_index < 3:
            return
        flexible = [self.table.columnWidth(column) for column in range(3, 7)]
        total = sum(flexible)
        if total <= 0:
            return
        ratios = [width / total for width in flexible]
        self.store.set_setting(TABLE_COLUMN_RATIOS_SETTING, json.dumps(ratios))
        self._save_table_column_widths()
        QTimer.singleShot(0, self._apply_table_column_ratios)

    def _keep_window_on_screen(self) -> None:
        frame = self.frameGeometry()
        screens = QGuiApplication.screens()
        if any(screen.availableGeometry().contains(frame.center()) for screen in screens):
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(max(self.minimumWidth(), frame.width()), available.width())
        height = min(max(self.minimumHeight(), frame.height()), available.height())
        max_x = available.right() - width + 1
        max_y = available.bottom() - height + 1
        self.setGeometry(
            min(max(frame.x(), available.x()), max_x),
            min(max(frame.y(), available.y()), max_y),
            width,
            height,
        )

    def _saved_splitter_ratio(self, orientation: str, fallback: float) -> float:
        raw_value = self.store.setting(self._splitter_ratio_setting_key(orientation), "")
        try:
            ratio = float(raw_value)
        except (TypeError, ValueError):
            ratio = 0
        if 0.1 <= ratio <= 0.9:
            return ratio
        legacy = parse_splitter_sizes(
            self.store.setting(self._splitter_setting_key(orientation), ""),
            [],
        )
        if len(legacy) == 2 and sum(legacy) > 0:
            ratio = legacy[0] / sum(legacy)
            self.store.set_setting(self._splitter_ratio_setting_key(orientation), f"{ratio:.6f}")
            return ratio
        return fallback

    def _save_splitter_sizes(self) -> None:
        if not hasattr(self, "splitter") or self._restoring_splitter_ratio:
            return
        orientation = "vertical" if self.splitter.orientation() == Qt.Orientation.Vertical else "horizontal"
        sizes = self.splitter.sizes()
        total = sum(sizes)
        if total > 0:
            self.store.set_setting(
                self._splitter_ratio_setting_key(orientation),
                f"{sizes[0] / total:.6f}",
            )

    def _vertical_table_minimum(self) -> int:
        """Height the stacked list needs to show VERTICAL_MIN_TABLE_ROWS rows."""
        if not hasattr(self, "table"):
            return 225
        row_height = max(24, self.table.verticalHeader().defaultSectionSize())
        header = max(24, self.table.horizontalHeader().height())
        chrome = max(0, self.table.y()) + 16
        return chrome + header + row_height * VERTICAL_MIN_TABLE_ROWS

    def _apply_splitter_ratio(self) -> None:
        if not hasattr(self, "splitter"):
            return
        vertical = self.splitter.orientation() == Qt.Orientation.Vertical
        orientation = "vertical" if vertical else "horizontal"
        total = (
            self.splitter.height() if vertical else self.splitter.width()
        ) - self.splitter.handleWidth()
        if total <= 0:
            return
        ratio = self._saved_splitter_ratio(orientation, 0.5)
        if vertical:
            # A stacked list that only shows one row is useless, so the saved
            # ratio yields to "keep VERTICAL_MIN_TABLE_ROWS rows visible".
            first_min, second_min = self._vertical_table_minimum(), 200
            ceiling = VERTICAL_TABLE_MAX_SHARE
        else:
            first_min, second_min = 480, 500
            ceiling = 0.5
        minimum_ratio = min(ceiling, first_min / total)
        maximum_ratio = max(minimum_ratio, 1 - second_min / total)
        effective = max(minimum_ratio, min(ratio, maximum_ratio))
        first = round(total * effective)
        self._restoring_splitter_ratio = True
        try:
            self.splitter.setSizes([first, max(1, total - first)])
        finally:
            self._restoring_splitter_ratio = False

    def _on_splitter_moved(self, *_args) -> None:
        self._save_splitter_sizes()
        self._update_responsive_layout()

    def _update_responsive_layout(self) -> None:
        if not hasattr(self, "macro_layout"):
            return
        narrow = self.width() < 1050
        self.workspace_switch_hint.setVisible(self._hints_fit())
        self._update_workspace_subnav_visibility()
        desired = Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal
        if self.splitter.orientation() != desired:
            self._save_splitter_sizes()
            self.splitter.setOrientation(desired)
            if narrow:
                self.table_panel.setMinimumWidth(0)
                self.table_panel.setMinimumHeight(225)
            else:
                self.table_panel.setMinimumHeight(0)
                self.table_panel.setMinimumWidth(520)
        self._apply_splitter_ratio()
        form_width = self.form_panel.viewport().width()
        compact = narrow or form_width < 650
        self._update_form_header_layout(compact)
        self.form_bottom_layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if form_width < 620
            else QBoxLayout.Direction.LeftToRight
        )
        direction = QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        if self.macro_layout.direction() != direction:
            self.macro_layout.setDirection(direction)
        if hasattr(self, "stop_hotkey_layout"):
            compact_hotkeys = form_width < 900
            hotkey_direction = (
                QBoxLayout.Direction.TopToBottom
                if compact_hotkeys
                else QBoxLayout.Direction.LeftToRight
            )
            self.stop_hotkey_layout.setDirection(hotkey_direction)
            self.hotkey_controls_layout.setDirection(hotkey_direction)
            self.stop_hotkey_layout.setAlignment(
                self.repeat_controls, Qt.AlignmentFlag.AlignRight
            )
            for layout in (
                self.hotkey_controls_layout,
                self.stop_hotkey_layout,
                self.recording_section.layout(),
                self.settings_panel.layout(),
                self.macro_layout,
            ):
                layout.invalidate()
                layout.activate()
        # At smaller widths the form scrolls instead of clipping its cards.
        self.json_panel.setMinimumHeight(320)
        self.settings_panel.setMinimumHeight(0)
        self._apply_table_column_ratios()

    def _update_form_header_layout(self, compact: bool) -> None:
        if getattr(self, "_form_header_compact", None) is compact:
            return
        self._form_header_compact = compact
        widgets = (
            self.name_field_label,
            self.name_edit,
            self.state_field_label,
            self.active_check,
            self.type_field_label,
            self.type_combo,
            self.hotkey_field_label,
            self.hotkey_edit,
            self.hotkey_feedback,
        )
        for widget in widgets:
            self.form_grid.removeWidget(widget)
        for column in range(6):
            self.form_grid.setColumnStretch(column, 0)
        if compact:
            self.form_grid.addWidget(self.name_field_label, 0, 0)
            self.form_grid.addWidget(self.name_edit, 0, 1, 1, 3)
            self.form_grid.addWidget(self.state_field_label, 1, 0)
            self.form_grid.addWidget(self.active_check, 1, 1)
            self.form_grid.addWidget(self.type_field_label, 1, 2)
            self.form_grid.addWidget(self.type_combo, 1, 3)
            self.form_grid.addWidget(self.hotkey_field_label, 2, 0)
            self.form_grid.addWidget(self.hotkey_edit, 2, 1, 1, 3)
            # The hint moves to its own row; sharing (2, 1) draws it over the combos.
            self.form_grid.addWidget(self.hotkey_feedback, 3, 1, 1, 3)
            self.form_grid.setColumnStretch(1, 2)
            self.form_grid.setColumnStretch(3, 2)
        else:
            self.form_grid.addWidget(self.name_field_label, 0, 0)
            self.form_grid.addWidget(self.name_edit, 0, 1)
            self.form_grid.addWidget(self.state_field_label, 0, 2)
            self.form_grid.addWidget(self.active_check, 0, 3)
            self.form_grid.addWidget(self.type_field_label, 0, 4)
            self.form_grid.addWidget(self.type_combo, 0, 5)
            self.form_grid.addWidget(self.hotkey_field_label, 1, 0)
            self.form_grid.addWidget(self.hotkey_edit, 1, 1, 1, 5)
            self.form_grid.addWidget(self.hotkey_feedback, 2, 1, 1, 5)
            self.form_grid.setColumnStretch(1, 3)
            self.form_grid.setColumnStretch(5, 1)

    def _set_status(self, message: str, level: str = "info") -> None:
        apply_status(self.status, message, level)
        # An empty banner should not reserve a row above the input fields.
        self.status.setVisible(bool(message))

    def eventFilter(self, _watched, event) -> bool:
        if _watched is self and event.type() in (QEvent.Type.WindowStateChange, QEvent.Type.Hide):
            self._cancel_resize_drag()
        if _watched is self or (isinstance(_watched, QWidget) and self.isAncestorOf(_watched)):
            if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                global_position = getattr(event, "globalPosition", None)
                if global_position is not None:
                    point = global_position().toPoint()
                    if event.type() == QEvent.Type.MouseMove and self._resize_drag is not None:
                        if not event.buttons() & Qt.MouseButton.LeftButton:
                            self._cancel_resize_drag()
                            return False
                        self._resize_from_drag(point)
                        event.accept()
                        return True
                    if event.type() == QEvent.Type.MouseButtonRelease and self._resize_drag is not None:
                        self._cancel_resize_drag()
                        event.accept()
                        return True
                    edges = self._resize_edges_at(point)
                    if event.type() == QEvent.Type.MouseMove:
                        self._set_resize_cursor(edges)
                    elif (edges != Qt.Edge(0)
                          and event.button() == Qt.MouseButton.LeftButton
                          and not self.isMaximized()):
                        self._resize_drag = (edges, point, self.geometry())
                        # Keep receiving move events even after the pointer crosses
                        # the old frameless-window boundary during an outward drag.
                        self.grabMouse()
                        event.accept()
                        return True
        if (event.type() == QEvent.Type.Wheel
                and _watched in getattr(self, "_wheel_locked_controls", ())
                and not event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            event.accept()
            return True
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self._set_ui_scale(self._ui_scale + (0.1 if delta > 0 else -0.1))
                event.accept()
                return True
        if event.type() == QEvent.Type.KeyPress and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_0:
                self._set_ui_scale(1.0)
                event.accept()
                return True
        return super().eventFilter(_watched, event)

    def _set_ui_scale(self, scale: float) -> None:
        scale = max(0.8, min(1.5, round(scale, 1)))
        if scale == self._ui_scale:
            return
        self._ui_scale = scale
        self._apply_ui_scale()
        self._set_status(f"UI 크기: {round(scale * 100)}%  (Ctrl+마우스휠로 조절, Ctrl+0으로 초기화)")

    def _apply_ui_scale(self) -> None:
        self.setStyleSheet(theme_scaled_stylesheet(self._ui_scale))
        if hasattr(self, "alert_panel"):
            self.alert_panel.apply_ui_scale(self._ui_scale)
        if hasattr(self, "table"):
            self.table.verticalHeader().setDefaultSectionSize(round(42 * self._ui_scale))
            self._apply_table_column_ratios()
            for switch in self.table.findChildren(ToggleSwitch):
                switch.set_scale(self._ui_scale)
        QTimer.singleShot(0, self._update_responsive_layout)

    def _sync_timing_controls(self) -> None:
        speed = self.speed_slider.value() / 100
        if speed == 1:
            text = "기본 속도 (1.0배)"
        elif speed > 1:
            text = f"현재 {speed:.1f}배 빠르게 재생"
        else:
            text = f"현재 {speed:.1f}배 느리게 재생"
        self.speed_reset_button.setText(text)
        self._update_macro_summary()
        if not self._updating_macro_document:
            self._sync_timing_json()

    def _update_macro_summary(self) -> None:
        if not hasattr(self, "macro_summary_label"):
            return
        try:
            payload = json.loads(self.macro_edit.toPlainText() or "{}")
            steps = payload.get("steps", []) if isinstance(payload, dict) else []
            if not isinstance(steps, list):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            self.macro_summary_label.setText("매크로 JSON 형식을 확인해 주세요.")
            refresh_property(self.macro_summary_label, "valid", False)
            return
        wait_count = sum(1 for step in steps if isinstance(step, dict) and step.get("type") == "wait")
        timing_text = f"{self.speed_slider.value() / 100:.1f}배 재생"
        repeat_text = f"{self.repeat_count_spin.value()}회 반복"
        self.macro_summary_label.setText(
            f"동작 {len(steps)}개 · 대기 {wait_count}개 · {timing_text} · {repeat_text}"
        )
        refresh_property(self.macro_summary_label, "valid", True)

    def _timing_options(self) -> dict:
        return {
            "timing_mode": "scaled",
            "playback_speed": round(self.speed_slider.value() / 100, 2),
            "repeat_count": self.repeat_count_spin.value(),
        }

    def _sync_timing_json(self) -> None:
        """Reflect timing controls in the visible macro JSON immediately."""
        try:
            payload = json.loads(self.macro_edit.toPlainText() or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        payload.update(self._timing_options())
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        if rendered != self.macro_edit.toPlainText():
            scroll_value = self.macro_edit.verticalScrollBar().value()
            self.macro_edit.setPlainText(rendered)
            self.macro_edit.verticalScrollBar().setValue(scroll_value)

    def _set_macro_steps_json(self, steps: list[dict]) -> None:
        payload = {"steps": steps}
        payload.update(self._timing_options())
        self.macro_edit.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

    def edit_step_delays(self) -> None:
        try:
            payload = json.loads(self.macro_edit.toPlainText() or "{}")
            steps = payload.get("steps", [])
            if not isinstance(steps, list):
                raise ValueError("steps 배열을 확인해 주세요.")
        except Exception as exc:
            QMessageBox.warning(self, "시간 편집", str(exc))
            return
        dialog = TimingEditorDialog(steps, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._commit_macro_history_state()
            payload["steps"] = dialog.steps()
            payload.update(self._timing_options())
            self._updating_macro_document = True
            try:
                self.macro_edit.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
            finally:
                self._updating_macro_document = False
            self._commit_macro_history_state()
            self._set_status("단계별 대기 시간을 반영했습니다. 저장 전 테스트로 동작을 확인하세요.", "info")

    def _macro_edit_state(self) -> dict:
        return {
            "document": self.macro_edit.toPlainText(),
            "speed": self.speed_slider.value(),
            "repeat_count": self.repeat_count_spin.value(),
        }

    def _queue_macro_history_commit(self, _value=None) -> None:
        if self._updating_macro_document or self._macro_history_current is None:
            return
        self._macro_history_timer.start()

    def _commit_macro_history_state(self) -> None:
        self._macro_history_timer.stop()
        if self._updating_macro_document:
            return
        state = self._macro_edit_state()
        if self._macro_history_current is None:
            self._macro_history_current = state
            self._update_macro_history_buttons()
            return
        if state == self._macro_history_current:
            self._update_macro_history_buttons()
            return
        self._macro_undo_stack.append(self._macro_history_current)
        if len(self._macro_undo_stack) > MACRO_HISTORY_LIMIT:
            del self._macro_undo_stack[:-MACRO_HISTORY_LIMIT]
        self._macro_history_current = state
        self._macro_redo_stack.clear()
        self._update_macro_history_buttons()

    def _reset_macro_history(self) -> None:
        self._macro_history_timer.stop()
        self._macro_undo_stack.clear()
        self._macro_redo_stack.clear()
        self._macro_history_current = self._macro_edit_state()
        self._update_macro_history_buttons()

    def _apply_macro_edit_state(self, state: dict) -> None:
        self._macro_history_timer.stop()
        self._updating_macro_document = True
        try:
            self.speed_slider.setValue(int(state["speed"]))
            self.repeat_count_spin.setValue(int(state.get("repeat_count", 1)))
            self.macro_edit.setPlainText(str(state["document"]))
            self._sync_timing_controls()
        finally:
            self._updating_macro_document = False

    def _update_macro_history_buttons(self) -> None:
        if not hasattr(self, "macro_undo_button"):
            return
        enabled = not self._recording
        self.macro_undo_button.setEnabled(enabled and bool(self._macro_undo_stack))
        self.macro_redo_button.setEnabled(enabled and bool(self._macro_redo_stack))

    def undo_macro_edit(self) -> None:
        self._commit_macro_history_state()
        if not self._macro_undo_stack:
            return
        current = self._macro_history_current or self._macro_edit_state()
        self._macro_redo_stack.append(current)
        if len(self._macro_redo_stack) > MACRO_HISTORY_LIMIT:
            del self._macro_redo_stack[:-MACRO_HISTORY_LIMIT]
        state = self._macro_undo_stack.pop()
        self._apply_macro_edit_state(state)
        self._macro_history_current = state
        self._update_macro_history_buttons()
        self._set_status("반복작업 편집을 한 단계 되돌렸습니다.", "info")

    def redo_macro_edit(self) -> None:
        self._commit_macro_history_state()
        if not self._macro_redo_stack:
            return
        current = self._macro_history_current or self._macro_edit_state()
        self._macro_undo_stack.append(current)
        if len(self._macro_undo_stack) > MACRO_HISTORY_LIMIT:
            del self._macro_undo_stack[:-MACRO_HISTORY_LIMIT]
        state = self._macro_redo_stack.pop()
        self._apply_macro_edit_state(state)
        self._macro_history_current = state
        self._update_macro_history_buttons()
        self._set_status("되돌린 반복작업 편집을 한 단계 다시 실행했습니다.", "info")

    def _capture_original_macro_state(self) -> None:
        self._original_macro_state = self._macro_edit_state()
        self._update_restore_macro_button()

    def _update_restore_macro_button(self) -> None:
        if hasattr(self, "restore_macro_button"):
            self.restore_macro_button.setEnabled(
                self.current_id is not None and self._original_macro_state is not None
            )

    def restore_original_macro(self) -> None:
        if self.current_id is None or self._original_macro_state is None:
            return
        self._commit_macro_history_state()
        state = self._original_macro_state
        self._apply_macro_edit_state(state)
        self._commit_macro_history_state()
        self._set_status("반복작업을 불러오거나 마지막으로 저장한 상태로 초기화했습니다.", "info")

    def test_macro_before_save(self) -> None:
        self.alert_service.pause()
        try:
            payload = self._payload("macro")
            result = self.runner.run(_dict_row({
                "name": self.name_edit.text().strip() or "반복작업 테스트",
                "hotkey": "Ctrl+Alt+Space", "action_type": "macro", "payload": payload, "active": True,
            }))
            self._set_status(
                f"저장 전 반복작업 테스트 완료: {result}. 이상이 없으면 저장하세요.",
                "success",
            )
        except Exception as exc:
            self._set_status(f"반복작업 테스트 실패: {exc}. 설정을 확인한 뒤 다시 테스트하세요.", "error")
            QMessageBox.warning(self, "반복작업 테스트 실패", str(exc))
        finally:
            self.alert_service.resume()

    def start_recording(self) -> None:
        if self._recording:
            return
        if not self._show_recording_guide():
            return
        self.alert_service.pause()
        try:
            # While recording, only the recording-stop shortcut is global.
            # This lets it reuse a shortcut that normally belongs to this app.
            self.hotkeys.unregister_all()
            self.hotkeys.register(EXIT_HOTKEY_ID, self.exit_hotkey, self.exit_application)
            self.hotkeys.register(RECORD_STOP_HOTKEY_ID, self.record_stop_hotkey, self.stop_recording)
            self.recorder.start()
        except Exception as exc:
            self.hotkeys.unregister(RECORD_STOP_HOTKEY_ID)
            self.register_hotkeys(show_message=False)
            self.alert_service.resume()
            QMessageBox.warning(self, "녹화 시작 실패", str(exc))
            return
        # Clear only after recording has successfully started. Cancelled or
        # failed starts keep the user's existing macro intact.
        self._commit_macro_history_state()
        self._updating_macro_document = True
        try:
            self._set_macro_steps_json([])
        finally:
            self._updating_macro_document = False
        self._recording = True
        self._set_recording_controls()
        self._set_status(f"녹화 중입니다. {self.record_stop_hotkey} 또는 녹화 종료 버튼을 누르세요.", "warning")
        self.showMinimized()

    def _show_recording_guide(self) -> bool:
        guide = QMessageBox(self)
        guide.setIcon(QMessageBox.Icon.Information)
        guide.setWindowTitle("반복작업 녹화 안내")
        guide.setText("확인을 누른 시점부터 녹화를 시작합니다.")
        guide.setInformativeText(self._recording_guide_text())
        start = guide.addButton("녹화 시작", QMessageBox.ButtonRole.AcceptRole)
        guide.addButton(QMessageBox.StandardButton.Cancel)
        guide.exec()
        return guide.clickedButton() is start

    def _recording_guide_text(self) -> str:
        hotkey = html.escape(self.record_stop_hotkey)
        emphasis = "color:#dc2626; font-weight:700;"
        return (
            "1. 앱이 최소화되면 외부 프로그램에서 클릭·드래그·마우스 휠·키보드 입력 작업을 수행하세요.\n"
            f"2. 종료는 <span style='{emphasis}'>{hotkey}</span> 또는 앱의 "
            f"<span style='{emphasis}'>녹화 종료</span> 버튼을 사용하세요."
        )

    def stop_recording(self) -> None:
        if not self._recording:
            return
        self._recording = False
        self.hotkeys.unregister(RECORD_STOP_HOTKEY_ID)
        steps = self.recorder.stop()
        # Restore the app's normal shortcuts as soon as recording is over.
        self.register_hotkeys(show_message=False)
        self.alert_service.resume()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._set_recording_controls()
        if not steps:
            self._commit_macro_history_state()
            self._set_status("녹화된 동작이 없습니다. 입력 동작을 수행한 뒤 다시 종료하세요.", "warning")
            return
        self._updating_macro_document = True
        try:
            self._set_macro_steps_json(steps)
        finally:
            self._updating_macro_document = False
        self._commit_macro_history_state()
        self._set_status("녹화 결과를 반복작업에 반영했습니다. 저장 버튼을 눌러 완료하세요.", "success")

    def _set_recording_controls(self) -> None:
        self.record_start_button.setEnabled(not self._recording)
        self.record_stop_button.setEnabled(self._recording)
        self.edit_record_stop_hotkey_button.setEnabled(not self._recording)
        self.edit_playback_stop_hotkey_button.setEnabled(not self._recording)
        badge_text = f"녹화 중 · {self.record_stop_hotkey}로 종료" if self._recording else "녹화 대기"
        self.recording_badge.setText(badge_text)
        refresh_property(self.recording_badge, "recording", self._recording)
        refresh_property(self.recording_deck, "recording", self._recording)
        self._update_macro_history_buttons()

    def _record_stop_hotkey_from_store(self) -> str:
        return self._hotkey_from_store(RECORD_STOP_HOTKEY_SETTING, RECORD_STOP_HOTKEY)

    def _playback_stop_hotkey_from_store(self) -> str:
        return self._hotkey_from_store(PLAYBACK_STOP_HOTKEY_SETTING, PLAYBACK_STOP_HOTKEY)

    def _hotkey_from_store(self, key: str, fallback: str) -> str:
        value = self.store.setting(key, fallback)
        try:
            return parse_hotkey(value).text
        except Exception:
            return fallback

    def _update_stop_hotkey_labels(self) -> None:
        if hasattr(self, "record_stop_hotkey_label"):
            self.record_stop_hotkey_label.setText(f"녹화 종료  {self.record_stop_hotkey}")
            self.playback_stop_hotkey_label.setText(f"실행 중지  {self.playback_stop_hotkey}")
        if hasattr(self, "recording_help_label"):
            self.recording_help_label.setText(
                "• 녹화 시작 후 외부 프로그램에서 클릭·드래그·마우스 휠·키보드 입력을 수행하세요.\n"
                f"• 반복작업 실행 중 {self.playback_stop_hotkey}를 누르면 즉시 멈춥니다."
            )

    def edit_record_stop_hotkey(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("녹화 종료 단축키 수정")
        dialog.setMinimumWidth(430)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("녹화를 종료할 단축키를 지정하세요. 앱의 일반 단축키는 녹화 중 잠시 해제되므로 같은 조합도 사용할 수 있습니다."))
        builder = HotkeyBuilder()
        builder.setText(self.record_stop_hotkey)
        layout.addWidget(builder)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            hotkey = parse_hotkey(builder.text()).text
            self._validate_stop_hotkey(hotkey, "record")
        except Exception as exc:
            QMessageBox.warning(self, "종료 단축키 수정", str(exc))
            return
        self.record_stop_hotkey = hotkey
        self.store.set_setting(RECORD_STOP_HOTKEY_SETTING, hotkey)
        self._update_stop_hotkey_labels()
        self._set_status(f"녹화 종료 단축키를 {hotkey}로 변경했습니다.", "success")

    def edit_playback_stop_hotkey(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("실행 중지 단축키 수정")
        dialog.setMinimumWidth(430)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("반복작업 실행을 즉시 중단할 단축키를 지정하세요. 변경값은 다음 실행부터 적용됩니다."))
        builder = HotkeyBuilder()
        builder.setText(self.playback_stop_hotkey)
        layout.addWidget(builder)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            hotkey = parse_hotkey(builder.text()).text
            self._validate_stop_hotkey(hotkey, "playback")
        except Exception as exc:
            QMessageBox.warning(self, "실행 중지 단축키 수정", str(exc))
            return
        self.playback_stop_hotkey = hotkey
        self.store.set_setting(PLAYBACK_STOP_HOTKEY_SETTING, hotkey)
        self.runner.set_stop_hotkey(hotkey)
        self._update_stop_hotkey_labels()
        self.register_hotkeys(False)
        self._set_status(f"실행 중지 단축키를 {hotkey}로 변경했습니다.", "success")

    def _validate_stop_hotkey(self, hotkey: str, setting: str) -> None:
        reserved = {
            self.exit_hotkey: "프로그램 종료",
            self.main_open_hotkey: "메인창 열기",
            self.tray_hide_hotkey: "트레이로 숨기기",
            self.record_stop_hotkey: "녹화 종료",
            self.playback_stop_hotkey: "실행 긴급 중지",
            self.quick_memo_hotkey: "빠른 메모",
            self.new_memo_hotkey: "새 메모",
            self.today_view_hotkey: "오늘 일정 열기",
            self.memo_search_hotkey: "메모·일정 검색",
            self.quick_schedule_hotkey: "빠른 일정",
            self.window_pin_hotkey: "창 고정/해제",
            self.shortcut_overlay_hotkey: "단축키 안내",
            self.schedule_postit_hotkey: "일정 포스트잇",
        }
        reserved.pop("", None)
        current = self.record_stop_hotkey if setting == "record" else self.playback_stop_hotkey
        reserved.pop(current, None)
        if hotkey in reserved:
            raise ValueError(f"{reserved[hotkey]} 단축키와 겹칠 수 없습니다.")
        for row in self.store.actions():
            if row["hotkey"] == hotkey:
                raise ValueError(f"작업 '{row['name']}'에서 이미 사용하는 단축키입니다.")
        if hotkey in self._content_hotkeys():
            raise ValueError("메모 또는 일정에서 이미 사용하는 단축키입니다.")

    def _is_own_window_click(self, x: int, y: int) -> bool:
        try:
            # Qt child controls and the main window share the same root window.
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
            user32 = ctypes.windll.user32
            user32.WindowFromPoint.argtypes = [POINT]
            user32.WindowFromPoint.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            target = user32.WindowFromPoint(POINT(x, y))
            return bool(target and user32.GetAncestor(target, 2) == user32.GetAncestor(int(self.winId()), 2))
        except Exception:
            return False

    def refresh(self) -> None:
        rows = self.store.actions()
        sort_column = self.table_header.sortIndicatorSection()
        sort_order = self.table_header.sortIndicatorOrder()
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            checked = QTableWidgetItem()
            checked.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            checked.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, checked)
            status, detail = self._registration_status_for_row(row)
            values = [row["id"], int(row["active"]), row["name"], row["hotkey"],
                      ACTION_LABELS.get(row["action_type"], row["action_type"]), status]
            for c, value in enumerate(values, start=1):
                if c == 2:
                    item = ActiveStateItem(bool(row["active"]))
                elif c == 6:
                    item = RegistrationStateItem(status, detail)
                else:
                    item = QTableWidgetItem()
                if c == 1:
                    item.setData(Qt.ItemDataRole.DisplayRole, int(row["id"]))
                    item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                elif c not in (2, 6):
                    item.setText(str(value))
                if c == 5:
                    item.setData(Qt.ItemDataRole.UserRole, row["action_type"])
                if c == 6:
                    item.setForeground(QColor(_registration_status_color(status)))
                if c == 3:
                    item.setToolTip(str(value))
                polish_action_item(item, c)
                self.table.setItem(r, c, item)
            switch_host = QWidget()
            switch_layout = QHBoxLayout(switch_host)
            switch_layout.setContentsMargins(0, 0, 0, 0)
            switch_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            switch = ToggleSwitch()
            switch.set_scale(self._ui_scale)
            switch_host.setMinimumWidth(switch.width() + 12)
            switch_host.setMinimumHeight(max(40, switch.height() + 8))
            switch.setChecked(bool(row["active"]))
            switch.setAccessibleName(f"{row['name']} 활성화")
            switch.setAccessibleDescription("켜면 전역 단축키가 등록되고 끄면 실행되지 않습니다")
            switch.toggled.connect(lambda checked, action_id=int(row["id"]):
                                   self._toggle_action_active(action_id, checked))
            switch_layout.addWidget(switch)
            self.table.setCellWidget(r, 2, switch_host)
        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        self.table.sortItems(sort_column if sort_column > 0 else 1, sort_order)
        self.table_header.set_check_state(Qt.CheckState.Unchecked)
        self._update_action_summary(rows)
        self._filter_actions(self.action_search.text())
        self._update_selection_actions()

    def _update_action_summary(self, rows: list[dict]) -> None:
        self._action_total_count = len(rows)
        self._action_active_count = sum(bool(row["active"]) for row in rows)
        self._refresh_action_count_label()

    def _refresh_action_count_label(self) -> None:
        parts = [
            f"전체 {getattr(self, '_action_total_count', 0)}개",
            f"활성 {getattr(self, '_action_active_count', 0)}개",
        ]
        registered = getattr(self, "_registered_hotkey_count", None)
        if registered is not None:
            parts.append(f"등록 {registered}개")
        self.action_count_label.setText(" · ".join(parts))

    def _filter_actions(self, query: str) -> None:
        normalized = query.strip().casefold()
        active_filter = self.active_filter.currentData()
        type_filter = self.type_filter.currentData()
        visible_count = 0
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            values = []
            for column in (3, 4, 5):  # 감춘 ID 로 걸리면 왜 걸렸는지 알 수 없다
                item = self.table.item(row, column)
                if item is not None:
                    values.append(item.text())
            active_item = self.table.item(row, 2)
            type_item = self.table.item(row, 5)
            is_active = bool(active_item and int(active_item.data(Qt.ItemDataRole.UserRole)))
            action_type = type_item.data(Qt.ItemDataRole.UserRole) if type_item else None
            query_matches = not normalized or normalized in " ".join(values).casefold()
            active_matches = (
                active_filter == "all"
                or (active_filter == "active" and is_active)
                or (active_filter == "inactive" and not is_active)
            )
            type_matches = type_filter == "all" or action_type == type_filter
            hidden = not (query_matches and active_matches and type_matches)
            self.table.setRowHidden(row, hidden)
            if hidden:
                self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
            else:
                visible_count += 1
        self.table.blockSignals(False)
        has_empty_result = self.table.rowCount() > 0 and visible_count == 0
        self.empty_search_label.setVisible(has_empty_result)
        self.table.setVisible(not has_empty_result)
        self._sync_select_all_state()

    def _toggle_action_active(self, action_id: int, active: bool) -> None:
        self.store.set_actions_active([action_id], active)
        self.register_hotkeys(False)
        state = "ON" if active else "OFF"
        self._set_status(f"작업 ID {action_id}를 {state}으로 변경했습니다.", "success")
        if self.table_header.sortIndicatorSection() == 2:
            self.refresh()

    def _selected_action_ids(self) -> list[int]:
        action_ids = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                action_ids.append(int(self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)))
        return action_ids

    def _set_all_checked(self, checked) -> None:
        if not isinstance(checked, bool):
            checked = Qt.CheckState(checked) != Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                self.table.item(row, 0).setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
        self.table.blockSignals(False)
        self._sync_select_all_state()

    def _sync_select_all_state(self, _item=None) -> None:
        visible_rows = [row for row in range(self.table.rowCount()) if not self.table.isRowHidden(row)]
        total = len(visible_rows)
        selected = sum(
            self.table.item(row, 0).checkState() == Qt.CheckState.Checked
            for row in visible_rows
        )
        if selected == 0:
            state = Qt.CheckState.Unchecked
        elif selected == total:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        self.table_header.set_check_state(state)
        self._update_selection_actions()

    def _build_row_menu(self) -> None:
        """목록 줄에서 오른쪽 단추로 부르는 메뉴.

        늘 떠 있던 단추 줄을 걷어 목록에 자리를 내주되, 하던 일은 그대로
        둔다.  대상은 예전 단추와 같이 ‘체크한 줄’이다.
        """
        self.row_menu = QMenu(self)
        self.activate_selected_action = self.row_menu.addAction(
            "활성", lambda: self.set_selected_active(True)
        )
        self.deactivate_selected_action = self.row_menu.addAction(
            "비활성", lambda: self.set_selected_active(False)
        )
        self.test_action_action = self.row_menu.addAction(
            "실행 테스트", self.test_selected_action
        )
        self.row_menu.addSeparator()
        self.delete_action_menu_item = self.row_menu.addAction("삭제", self.delete_action)
        self.row_menu.addSeparator()
        self.retry_registration_action = self.row_menu.addAction(
            "단축키 다시 등록", lambda: self.register_hotkeys(True)
        )
        self.registration_details_action = self.row_menu.addAction(
            "실패 상세", self.show_registration_failures
        )

    def _show_row_menu(self, point) -> None:
        row = self.table.rowAt(point.y())
        if row < 0:
            return
        self._update_selection_actions()
        self.row_menu.exec(self.table.viewport().mapToGlobal(point))

    def _update_selection_actions(self) -> None:
        checked_count = len(self._selected_action_ids())
        has_current = self.current_id is not None
        self.delete_action_button.setEnabled(checked_count > 0 or has_current)
        self.delete_action_button.setText(f"삭제 ({checked_count})" if checked_count else "삭제")
        if not hasattr(self, "row_menu"):
            return
        self.activate_selected_action.setEnabled(checked_count > 0)
        self.deactivate_selected_action.setEnabled(checked_count > 0)
        self.test_action_action.setEnabled(checked_count == 1)
        self.delete_action_menu_item.setEnabled(checked_count > 0 or has_current)
        self.registration_details_action.setEnabled(bool(self._last_hotkey_failures))

    def test_selected_action(self) -> None:
        selected_ids = self._selected_action_ids()
        if len(selected_ids) != 1:
            QMessageBox.information(self, "실행 테스트", "실행할 작업 하나만 체크해 주세요.")
            return
        row = self.store.action(selected_ids[0])
        if row is None:
            return
        is_macro = str(row["action_type"]) == "macro"
        if is_macro:
            self.alert_service.pause()
        try:
            result = self.runner.run(row)
        except Exception as exc:
            self._set_status(f"실행 테스트 실패: {exc}", "error")
            QMessageBox.warning(self, "실행 테스트 실패", str(exc))
            return
        finally:
            if is_macro:
                self.alert_service.resume()
        self._set_status(f"{row['name']} 실행 테스트 완료: {result}", "success")

    def new_action(self) -> None:
        if not self._confirm_action_form_transition():
            return
        self._macro_history_timer.stop()
        self.current_id = None
        self._original_macro_state = None
        self.excluded_apps = []
        self.name_edit.setText("새 작업")
        self.hotkey_edit.setText("Ctrl+Alt+Space")
        self.active_check.setChecked(True)
        self.type_combo.setCurrentIndex(0)
        self.text_edit.setPlainText("")
        self.text_enter_check.setChecked(False)
        self.url_edit.setText("")
        self.path_edit.setText("")
        self.path_restore_check.setChecked(False)
        self._set_layout_rows([])
        self._updating_macro_document = True
        try:
            self.macro_edit.setPlainText(_default_macro_json())
            self.speed_slider.setValue(100)
            self.repeat_count_spin.setValue(1)
            self._sync_timing_controls()
        finally:
            self._updating_macro_document = False
        self._update_selection_actions()
        self._update_restore_macro_button()
        self._reset_macro_history()
        self._sync_excluded_apps_buttons()
        self.name_edit.setFocus()
        self._set_action_form_baseline()

    def load_selected(self) -> None:
        if self._restoring_action_selection:
            return
        row_index = self.table.currentRow()
        if row_index < 0:
            return
        item = self.table.item(row_index, 1)
        if item is None:
            return
        raw_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            action_id = int(raw_id if raw_id is not None else item.text())
        except (TypeError, ValueError):
            return
        row = self.store.action(action_id)
        if row is None:
            return
        if action_id == self.current_id:
            return
        previous_id = self.current_id
        if not self._confirm_action_form_transition():
            self._restore_action_selection(previous_id)
            return
        self.current_id = action_id
        self._original_macro_state = None
        payload = json.loads(row["payload"] or "{}")
        self.excluded_apps = normalize_app_list(payload.get("excluded_apps", []))
        self._sync_excluded_apps_buttons()
        self.name_edit.setText(row["name"])
        self.hotkey_edit.setText(row["hotkey"])
        self.active_check.setChecked(bool(row["active"]))
        self.type_combo.setCurrentIndex(max(0, list(ACTION_LABELS).index(row["action_type"])))
        self.path_restore_check.setChecked(False)
        self._load_payload(row["action_type"], payload)
        if row["action_type"] == "macro":
            self._capture_original_macro_state()
        else:
            self._update_restore_macro_button()
        self._reset_macro_history()
        self._update_selection_actions()
        self._set_action_form_baseline()

    def _load_payload(self, action_type: str, payload: dict) -> None:
        if action_type == "text":
            self.text_edit.setPlainText(payload.get("text", ""))
            self.text_enter_check.setChecked(bool(payload.get("press_enter", True)))
        elif action_type == "url":
            self.url_edit.setText(payload.get("url", ""))
        elif action_type == "path":
            self.path_edit.setText(payload.get("path", ""))
            self.path_restore_check.setChecked(bool(payload.get("restore_if_minimized", False)))
        elif action_type == "macro":
            self._updating_macro_document = True
            try:
                try:
                    speed = editor_playback_speed(payload)
                    repeat_count = validate_repeat_count(payload.get("repeat_count", 1))
                    self.speed_slider.setValue(round(speed * 100))
                    self.repeat_count_spin.setValue(repeat_count)
                except ValueError:
                    self.speed_slider.setValue(100)
                    self.repeat_count_spin.setValue(1)
                self._set_macro_steps_json(payload.get("steps", []))
            finally:
                self._updating_macro_document = False
            self._sync_timing_controls()
        elif action_type == "layout":
            self._set_layout_rows(payload.get("windows", []))
            self.layout_status_label.setText(
                f"저장된 탐색기 창 {self.layout_table.rowCount()}개를 불러왔습니다."
            )

    def save_action(self) -> bool:
        self._commit_macro_history_state()
        try:
            data = self._form_data()
            self._validate_unique_hotkey(data["hotkey"], data.get("id"))
            action_id = self.store.save_action(data)
        except Exception as exc:
            self._set_status(f"저장 실패: {exc}. 입력 내용을 확인하세요.", "error")
            QMessageBox.warning(self, "저장 실패", str(exc))
            return False
        self.current_id = action_id
        if data["action_type"] == "macro":
            self._capture_original_macro_state()
        else:
            self._original_macro_state = None
            self._update_restore_macro_button()
        self._reset_macro_history()
        self.refresh()
        registered = self.register_hotkeys(show_message=False)
        self._set_action_form_baseline()
        if registered:
            self._set_status("저장되었습니다. 단축키 등록도 최신 상태로 갱신했습니다.", "success")
        else:
            self._set_status(
                "작업은 저장됐지만 일부 단축키를 등록하지 못했습니다. "
                "중복된 단축키를 확인해 주세요.",
                "warning",
            )
        return True

    def _form_data(self) -> dict:
        hotkey = parse_hotkey(self.hotkey_edit.text()).text
        action_type = self.type_combo.currentData()
        payload = self._payload(action_type)
        self._validate_action_payload(action_type, payload)
        return {
            "id": self.current_id,
            "name": self.name_edit.text().strip() or "작업",
            "hotkey": hotkey,
            "action_type": action_type,
            "active": self.active_check.isChecked(),
            "payload": payload,
        }

    def _validate_action_payload(self, action_type: str, payload: dict) -> None:
        if action_type == "text" and not str(payload.get("text", "")).strip():
            self.text_edit.setFocus()
            raise ValueError("입력할 문구를 적어 주세요.")
        if action_type == "url":
            raw_url = str(payload.get("url", "")).strip()
            if not raw_url:
                self.url_edit.setFocus()
                raise ValueError("URL을 입력해 주세요.")
            normalized = raw_url if "://" in raw_url else f"https://{raw_url}"
            parsed = urlparse(normalized)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                self.url_edit.setFocus()
                raise ValueError("올바른 웹 주소를 입력해 주세요.")
            payload["url"] = normalized
            self.url_edit.setText(normalized)
        if action_type == "path":
            target = str(payload.get("path", "")).strip()
            if not target or not Path(target).exists():
                self.path_edit.setFocus()
                raise ValueError("존재하는 파일 또는 폴더를 선택해 주세요.")
        if action_type == "macro" and not payload.get("steps"):
            self.macro_edit.setFocus()
            raise ValueError("반복작업에 하나 이상의 단계를 추가해 주세요.")
        if action_type == "layout" and not payload.get("windows"):
            self.layout_capture_button.setFocus()
            raise ValueError("저장할 탐색기 창을 하나 이상 선택해 주세요.")

    def _action_form_state(self) -> dict:
        """Return a lossless editor snapshot without validating unfinished input."""
        return {
            "id": self.current_id,
            "name": self.name_edit.text(),
            "hotkey": self.hotkey_edit.text(),
            "active": self.active_check.isChecked(),
            "type": self.type_combo.currentData(),
            "text": self.text_edit.toPlainText(),
            "press_enter": self.text_enter_check.isChecked(),
            "url": self.url_edit.text(),
            "path": self.path_edit.text(),
            "restore": self.path_restore_check.isChecked(),
            "macro": self.macro_edit.toPlainText(),
            "speed": self.speed_slider.value(),
            "repeat": self.repeat_count_spin.value(),
            "layout_windows": self._layout_row_states(),
            "excluded_apps": persisted_app_list(self.excluded_apps),
        }

    def _set_action_form_baseline(self) -> None:
        self._action_form_baseline = self._action_form_state()

    def _action_form_is_dirty(self) -> bool:
        if self._action_form_baseline is None:
            return False
        current = self._action_form_state()
        baseline = dict(self._action_form_baseline)
        # A newly opened form may change type while the user explores the choices.
        # Type alone is not substantive input and must not trigger a leave warning.
        if baseline.get("id") is None:
            current.pop("type", None)
            baseline.pop("type", None)
        return current != baseline

    def _confirm_action_form_transition(self) -> bool:
        if not self._action_form_is_dirty():
            return True
        answer = QMessageBox.question(
            self,
            "편집 내용 저장",
            "아직 저장하지 않은 변경 내용이 있습니다.",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_action()
        return answer == QMessageBox.StandardButton.Discard

    def _restore_action_selection(self, action_id: int | None) -> None:
        self._restoring_action_selection = True
        try:
            self.table.clearSelection()
            if action_id is None:
                self.table.setCurrentCell(-1, -1)
                return
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 1)
                if item is not None and int(item.data(Qt.ItemDataRole.UserRole)) == action_id:
                    self.table.selectRow(row)
                    break
        finally:
            self._restoring_action_selection = False

    def _payload(self, action_type: str) -> dict:
        if action_type == "text":
            payload = {"text": self.text_edit.toPlainText(), "press_enter": self.text_enter_check.isChecked()}
        elif action_type == "url":
            payload = {"url": self.url_edit.text().strip()}
        elif action_type == "path":
            payload = {
                "path": self.path_edit.text().strip(),
                "restore_if_minimized": self.path_restore_check.isChecked(),
            }
        elif action_type == "macro":
            payload = self._macro_document()
            payload.update(self._timing_options())
        elif action_type == "layout":
            return {"windows": self._layout_windows(selected_only=True)}
        else:
            payload = {}
        payload["excluded_apps"] = persisted_app_list(self.excluded_apps)
        return payload

    def _macro_document(self) -> dict:
        payload = json.loads(self.macro_edit.toPlainText() or "{}")
        if not isinstance(payload, dict) or not isinstance(payload.get("steps"), list):
            raise ValueError("반복작업 JSON에는 steps 배열이 필요합니다.")
        speed = validate_playback_speed(
            payload.get("playback_speed", self._timing_options()["playback_speed"])
        )
        repeat_count = validate_repeat_count(
            payload.get("repeat_count", self._timing_options()["repeat_count"])
        )
        return {
            "steps": payload["steps"],
            "timing_mode": "scaled",
            "playback_speed": speed,
            "repeat_count": repeat_count,
        }

    def export_macro_json(self) -> None:
        try:
            payload = self._macro_document()
        except Exception as exc:
            QMessageBox.warning(self, "반복작업 JSON 내보내기", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, "반복작업 JSON 내보내기", str(Path.cwd() / "repeat_task.json"), "JSON (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._set_status("반복작업 JSON을 내보냈습니다.", "success")

    def import_macro_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "반복작업 JSON 가져오기", str(Path.cwd()), "JSON (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict) or not isinstance(payload.get("steps"), list):
                raise ValueError("steps 배열이 있는 반복작업 JSON만 가져올 수 있습니다.")
            validate_timing_mode(payload.get("timing_mode", "recorded"))
            speed = editor_playback_speed(payload)
            repeat_count = validate_repeat_count(payload.get("repeat_count", 1))
            imported = {
                "steps": payload["steps"],
                "timing_mode": "scaled",
                "playback_speed": speed,
                "repeat_count": repeat_count,
            }
        except Exception as exc:
            QMessageBox.warning(self, "반복작업 JSON 가져오기", str(exc))
            return
        self._commit_macro_history_state()
        self._updating_macro_document = True
        try:
            self.speed_slider.setValue(round(speed * 100))
            self.repeat_count_spin.setValue(repeat_count)
            self.macro_edit.setPlainText(json.dumps(imported, ensure_ascii=False, indent=2))
        finally:
            self._updating_macro_document = False
        self._sync_timing_controls()
        self._commit_macro_history_state()
        self._set_status("반복작업 JSON을 편집기에 가져왔습니다. 저장해야 실제 작업에 적용됩니다.", "warning")

    def _validate_unique_hotkey(self, hotkey: str, current_id: int | None) -> None:
        reserved = {
            self.exit_hotkey,
            self.main_open_hotkey,
            self.tray_hide_hotkey,
            self.record_stop_hotkey,
            self.playback_stop_hotkey,
            self.quick_memo_hotkey,
            self.new_memo_hotkey,
            self.today_view_hotkey,
            self.memo_search_hotkey,
            self.quick_schedule_hotkey,
            self.window_pin_hotkey,
            self.shortcut_overlay_hotkey,
            self.schedule_postit_hotkey,
        }
        reserved.discard("")
        if hotkey in reserved:
            raise ValueError("프로그램 제어 단축키와 겹칠 수 없습니다.")
        for row in self.store.actions():
            if row["hotkey"] == hotkey and int(row["id"]) != int(current_id or 0):
                raise ValueError("이미 사용 중인 단축키입니다.")
        if any(str(row["hotkey"] or "") == hotkey for row in self.note_store.notes()):
            raise ValueError("메모에 이미 사용 중인 단축키입니다.")
        if any(str(row["hotkey"] or "") == hotkey for row in self.note_store.schedules.hotkey_items()):
            raise ValueError("일정에 이미 사용 중인 단축키입니다.")

    def _update_hotkey_validation(self, _value: str = "") -> None:
        if not hasattr(self, "hotkey_feedback"):
            return
        try:
            parsed = parse_hotkey(self.hotkey_edit.text()).text
            self._validate_unique_hotkey(parsed, self.current_id)
        except Exception as exc:
            apply_status(self.hotkey_feedback, str(exc), "error")
            return
        apply_status(self.hotkey_feedback, f"사용 가능한 단축키입니다: {parsed}", "success")

    def _content_hotkeys(self) -> set[str]:
        values = {str(row["hotkey"]) for row in self.store.actions() if row["hotkey"]}
        values.update(str(row["hotkey"]) for row in self.note_store.notes() if row["hotkey"])
        values.update(str(row["hotkey"]) for row in self.note_store.schedules.hotkey_items() if row["hotkey"])
        return values

    def _validate_content_hotkey(
        self, hotkey: str, *, note_id: int | None = None, schedule_id: int | None = None
    ) -> None:
        controls = {
            self.exit_hotkey, self.main_open_hotkey, self.tray_hide_hotkey,
            self.record_stop_hotkey, self.playback_stop_hotkey, self.quick_memo_hotkey,
            self.new_memo_hotkey,
            self.today_view_hotkey, self.memo_search_hotkey,
            self.quick_schedule_hotkey,
            self.window_pin_hotkey,
            self.shortcut_overlay_hotkey,
            self.schedule_postit_hotkey,
        }
        controls.discard("")
        if hotkey in controls:
            raise ValueError("프로그램 제어 단축키와 겹칠 수 없습니다.")
        if any(row["hotkey"] == hotkey for row in self.store.actions()):
            raise ValueError("저장된 단축키 작업에서 이미 사용하는 단축키입니다.")
        for row in self.note_store.notes():
            if row["hotkey"] == hotkey and int(row["id"]) != int(note_id or 0):
                raise ValueError(f"메모 '{row['title']}'에서 이미 사용하는 단축키입니다.")
        for row in self.note_store.schedules.hotkey_items():
            if row["hotkey"] == hotkey and int(row["id"]) != int(schedule_id or 0):
                raise ValueError(f"일정 '{row['title']}'에서 이미 사용하는 단축키입니다.")

    def delete_action(self) -> None:
        selected_ids = self._selected_action_ids()
        if selected_ids:
            count = len(selected_ids)
            prompt = f"선택한 {count}개 작업을 삭제할까요?"
        elif self.current_id is not None:
            selected_ids = [self.current_id]
            prompt = "선택한 작업을 삭제할까요?"
        else:
            QMessageBox.information(self, "삭제", "삭제할 작업을 체크하거나 선택해 주세요.")
            return
        if QMessageBox.question(self, "삭제", prompt) != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_actions(selected_ids)
        self.current_id = None
        self.refresh()
        self.register_hotkeys(False)

    def set_selected_active(self, active: bool) -> None:
        selected_ids = self._selected_action_ids()
        if not selected_ids:
            QMessageBox.information(self, "상태 변경", "상태를 변경할 작업을 체크해 주세요.")
            return
        self.store.set_actions_active(selected_ids, active)
        self.refresh()
        self.register_hotkeys(False)
        state = "활성" if active else "비활성"
        self._set_status(f"{len(selected_ids)}개 작업을 {state} 처리했습니다.", "success")

    def test_action(self) -> None:
        try:
            data = self._form_data()
            row = _dict_row(data)
            result = self.runner.run(row)
            self._set_status(f"실행 테스트 완료: {result}", "success")
        except Exception as exc:
            self._set_status(f"실행 테스트 실패: {exc}. 작업 설정을 확인하세요.", "error")
            QMessageBox.warning(self, "실행 실패", str(exc))

    def _content_hotkey_signature(self) -> tuple:
        notes = tuple(sorted(
            (int(row["id"]), str(row["hotkey"] or ""), str(row["hotkey_action"] or ""))
            for row in self.note_store.notes()
            if row["hotkey"]
        ))
        schedules = tuple(sorted(
            (int(row["id"]), str(row["hotkey"] or ""), str(row["hotkey_action"] or ""))
            for row in self.note_store.schedules.hotkey_items()
        ))
        return notes, schedules

    def _on_content_shortcuts_changed(self) -> None:
        signature = self._content_hotkey_signature()
        if signature == self._last_content_hotkey_signature:
            return
        self.register_hotkeys(False)

    def _registration_status_for_row(self, row) -> tuple[str, str]:
        if not bool(row["active"]):
            return "비활성", "작업이 꺼져 있어 전역 단축키를 등록하지 않았습니다."
        return self._action_registration_status.get(
            int(row["id"]), ("확인 중", "단축키 등록 결과를 확인하고 있습니다."),
        )

    def _refresh_registration_status_cells(self) -> None:
        if not hasattr(self, "table") or self.table.columnCount() < 7:
            return
        for table_row in range(self.table.rowCount()):
            id_item = self.table.item(table_row, 1)
            status_item = self.table.item(table_row, 6)
            if id_item is None or status_item is None:
                continue
            action = self.store.action(int(id_item.data(Qt.ItemDataRole.UserRole)))
            if action is None:
                continue
            status, detail = self._registration_status_for_row(action)
            if isinstance(status_item, RegistrationStateItem):
                status_item.set_status(status, detail)
            else:
                status_item.setText(status)
                status_item.setToolTip(detail)
            status_item.setForeground(QColor(_registration_status_color(status)))

    def _update_registration_summary(self, registered: int, failures: list[str]) -> None:
        self._last_hotkey_failures = list(failures)
        if not hasattr(self, "registration_notice"):
            return
        if failures:
            self.registration_notice.setText(
                f"실패 {len(failures)}개 · "
                f"<a href='#failures' style='{REGISTRATION_LINK_STYLE}'>‘실패 상세’</a>"
                "에서 확인하세요"
            )
            self.registration_notice.setToolTip("\n".join(failures[:20]))
        else:
            self.registration_notice.clear()
            self.registration_notice.setToolTip("")
        # 잘 됐을 때는 아무 말도 하지 않는다.  등록 개수는 목록 부제에 있다.
        self.registration_notice.setVisible(bool(failures))
        self._registered_hotkey_count = registered
        self._refresh_action_count_label()
        self._update_selection_actions()

    def show_registration_failures(self) -> None:
        if not self._last_hotkey_failures:
            QMessageBox.information(self, "단축키 등록", "현재 등록에 실패한 단축키가 없습니다.")
            return
        lines = self._last_hotkey_failures[:20]
        if len(self._last_hotkey_failures) > 20:
            lines.append(f"외 {len(self._last_hotkey_failures) - 20}개")
        QMessageBox.warning(self, "단축키 등록 실패", "\n".join(lines))

    def register_hotkeys(self, show_message: bool, success_message: str | None = None) -> bool:
        self.hotkeys.unregister_all()
        self._shortcut_overlay_registered_entries: list[ShortcutOverlayEntry] = []
        self._registered_action_hotkey_ids.clear()
        self._action_hotkey_rows.clear()
        self._foreground_app_signature = None
        failed = []
        self._action_registration_status = {
            int(row["id"]): (
                ("확인 중", "단축키 등록 결과를 확인하고 있습니다.")
                if bool(row["active"])
                else ("비활성", "작업이 꺼져 있어 전역 단축키를 등록하지 않았습니다.")
            )
            for row in self.store.actions()
        }
        control_hotkeys = (
            (EXIT_HOTKEY_ID, self.exit_hotkey, self.exit_application, "프로그램 종료"),
            (MAIN_OPEN_HOTKEY_ID, self.main_open_hotkey, self.restore_from_tray, "메인창 열기"),
            (TRAY_HIDE_HOTKEY_ID, self.tray_hide_hotkey, self.hide_to_tray, "트레이로 숨기기"),
            (HOTKEY_ID_STOP, self.playback_stop_hotkey, self.runner.stop, "긴급 중지"),
            (QUICK_MEMO_HOTKEY_ID, self.quick_memo_hotkey, self.show_quick_memo, "빠른 메모"),
            (NEW_MEMO_HOTKEY_ID, self.new_memo_hotkey, self.show_new_memo_editor, "새 메모"),
            (TODAY_VIEW_HOTKEY_ID, self.today_view_hotkey, self.open_today_schedule, "오늘 일정"),
            (MEMO_SEARCH_HOTKEY_ID, self.memo_search_hotkey, self.show_memo_search, "메모·일정 검색"),
            (QUICK_SCHEDULE_HOTKEY_ID, self.quick_schedule_hotkey, self.show_quick_schedule, "빠른 일정"),
            (WINDOW_PIN_HOTKEY_ID, self.window_pin_hotkey, self.toggle_foreground_window_pin, "창 고정/해제"),
            (SHORTCUT_OVERLAY_HOTKEY_ID, self.shortcut_overlay_hotkey, self.show_shortcut_overlay, "단축키 안내"),
            (SCHEDULE_POSTIT_HOTKEY_ID, self.schedule_postit_hotkey, self.toggle_schedule_postit, "일정 포스트잇"),
        )
        control_registered = 0
        for hotkey_id, hotkey, callback, label in control_hotkeys:
            if not hotkey:
                continue
            try:
                self.hotkeys.register(hotkey_id, hotkey, callback)
                control_registered += 1
                self._shortcut_overlay_registered_entries.append(ShortcutOverlayEntry(
                    GROUP_COMMON, label, hotkey, target_kind="settings",
                ))
            except HotkeyError as exc:
                failed.append(f"{label} ({exc})")
        for index, row in enumerate(self.store.active_actions(), start=HOTKEY_ID_START):
            if row["hotkey"] in {
                self.exit_hotkey,
                self.main_open_hotkey,
                self.tray_hide_hotkey,
                self.record_stop_hotkey,
                self.playback_stop_hotkey,
                self.quick_memo_hotkey,
                self.new_memo_hotkey,
                self.today_view_hotkey,
                self.memo_search_hotkey,
                self.quick_schedule_hotkey,
                self.window_pin_hotkey,
                self.shortcut_overlay_hotkey,
                self.schedule_postit_hotkey,
            }:
                failed.append(f"{row['name']} (프로그램 제어 단축키와 충돌)")
                self._action_registration_status[int(row["id"])] = (
                    "등록 실패", "프로그램 제어 단축키와 충돌합니다.",
                )
                continue
            self._action_hotkey_rows[index] = row

        self._sync_action_hotkeys(foreground_application(), failed)
        content_registered = 0
        content_id = 20_000
        for row in self.note_store.notes():
            if not row["hotkey"]:
                continue
            try:
                self.hotkeys.register(content_id, row["hotkey"], lambda r=row: self._run_note_hotkey(r))
                content_registered += 1
                self._shortcut_overlay_registered_entries.append(ShortcutOverlayEntry(
                    GROUP_CONTENT, str(row["title"]), str(row["hotkey"]),
                    target_kind="note", target_id=int(row["id"]),
                ))
            except HotkeyError as exc:
                failed.append(f"메모 '{row['title']}' ({exc})")
            content_id += 1
        for row in self.note_store.schedules.hotkey_items():
            try:
                self.hotkeys.register(content_id, row["hotkey"], lambda r=row: self._run_schedule_hotkey(r))
                content_registered += 1
                self._shortcut_overlay_registered_entries.append(ShortcutOverlayEntry(
                    GROUP_CONTENT, str(row["title"]), str(row["hotkey"]),
                    target_kind="schedule", target_id=int(row["id"]),
                ))
            except HotkeyError as exc:
                failed.append(f"일정 '{row['title']}' ({exc})")
            content_id += 1
        registered = control_registered + len(self._registered_action_hotkey_ids) + content_registered
        self._last_content_hotkey_signature = self._content_hotkey_signature()
        self._update_registration_summary(registered, failed)
        self._refresh_registration_status_cells()
        if failed:
            # 같은 말을 두 번 하지 않는다.  실패는 ‘작업 편집’ 제목 옆 알림 줄이
            # 맡으므로 노란 띠까지 띄우면 자리만 먹는다.
            message = f"등록 완료 {registered}개 / 실패 {len(failed)}개 · ‘실패 상세’에서 확인하세요"
            self._set_status("", "warning")
        else:
            message = f"단축키 등록 완료: {registered}개"
            self._set_status(message, "success")
        if show_message:
            dialog = QMessageBox.warning if failed else QMessageBox.information
            dialog(self, "단축키 등록", success_message if success_message and not failed else message)
        return not failed

    def _run_note_hotkey(self, row) -> None:
        note_id = int(row["id"])
        if row["hotkey_action"] == "postit":
            self.alert_panel.toggle_note_postit(note_id)
            return
        self.alert_panel.open_standalone_note(note_id)

    def _run_schedule_hotkey(self, row) -> None:
        if row["hotkey_action"] == "postit" and row["note_id"]:
            self.alert_panel.toggle_note_postit(int(row["note_id"]))
            return
        self.open_schedule_item(int(row["id"]))

    def _sync_action_hotkeys_for_foreground(self) -> None:
        """Release excluded action shortcuts so the foreground app receives them."""
        if self._recording:
            return
        current_app = foreground_application()
        signature = self._app_signature(current_app)
        if signature == self._foreground_app_signature:
            return
        self._foreground_app_signature = signature
        self._sync_action_hotkeys(current_app)

    def _sync_action_hotkeys(self, current_app: dict | None, failures: list[str] | None = None) -> None:
        desired_ids = {
            hotkey_id
            for hotkey_id, row in self._action_hotkey_rows.items()
            if not is_app_excluded(current_app, self._excluded_apps_from_row(row))
        }
        for hotkey_id, row in self._action_hotkey_rows.items():
            action_id = int(row["id"])
            if hotkey_id not in desired_ids:
                self._action_registration_status[action_id] = (
                    "제외 중", "현재 전경 프로그램에서는 이 단축키를 해제했습니다.",
                )
            elif hotkey_id in self._registered_action_hotkey_ids:
                self._action_registration_status[action_id] = (
                    "등록됨", "Windows 전역 단축키가 정상 등록되었습니다.",
                )
        for hotkey_id in self._registered_action_hotkey_ids - desired_ids:
            self.hotkeys.unregister(hotkey_id)
            self._registered_action_hotkey_ids.discard(hotkey_id)
        for hotkey_id in desired_ids - self._registered_action_hotkey_ids:
            row = self._action_hotkey_rows[hotkey_id]
            try:
                self.hotkeys.register(hotkey_id, row["hotkey"], lambda r=row: self.run_saved_action(r))
                self._registered_action_hotkey_ids.add(hotkey_id)
                self._action_registration_status[int(row["id"])] = (
                    "등록됨", "Windows 전역 단축키가 정상 등록되었습니다.",
                )
            except HotkeyError as exc:
                self._action_registration_status[int(row["id"])] = ("등록 실패", str(exc))
                if failures is not None:
                    failures.append(f"{row['name']} ({exc})")
        self._refresh_registration_status_cells()

    @staticmethod
    def _excluded_apps_from_row(row) -> list[dict]:
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return []
        return payload.get("excluded_apps", []) if isinstance(payload, dict) else []

    @staticmethod
    def _app_signature(app: dict | None) -> tuple[str, str]:
        if not app:
            return "", ""
        return (
            str(app.get("path") or "").casefold(),
            str(app.get("name") or "").casefold(),
        )

    def run_saved_action(self, row) -> None:
        payload = {"excluded_apps": self._excluded_apps_from_row(row)}
        current_app = foreground_application()
        if is_app_excluded(current_app, payload.get("excluded_apps", [])):
            app_name = current_app.get("name") or "현재 프로그램"
            self._set_status(f"{app_name} 프로그램에서는 이 단축키가 제외됩니다.", "info")
            return
        is_macro = str(row["action_type"]) == "macro"
        if is_macro:
            self.alert_service.pause()
        try:
            try:
                result = self.runner.run(row)
            except Exception as exc:
                result = f"실패: {exc}"
        finally:
            if is_macro:
                self.alert_service.resume()
        self.store.add_history(row, result)
        level = "error" if str(result).startswith("실패") else "success"
        self._set_status(f"{row['name']}: {result}", level)

    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "파일 선택")
        if path:
            self.path_edit.setText(path)

    def pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if path:
            self.path_edit.setText(path)

    def export_backup(self) -> None:
        self.store.backup_dir.mkdir(parents=True, exist_ok=True)
        path = self.store.backup_dir / f"backup_{now_key()}.json"
        self._export_bundle(path)
        self._rotate_backups()
        QMessageBox.information(self, "전체 백업 완료", str(path))

    def _export_bundle(self, path: Path) -> Path:
        export_database_bundle(
            {
                "hotkeys": (self.store.conn, HOTKEY_TABLES),
                "alert_notes": (
                    self.note_store.conn,
                    ("notes", "note_attachments", "reminder_series", "reminders", "reminder_history", "settings", "schedule_items", "schedule_notifications",
                     "schedule_notification_log", "schedule_occurrence_exceptions"),
                ),
            },
            path,
        )
        return path

    def _create_automatic_backup(self) -> None:
        try:
            self.store.backup_dir.mkdir(parents=True, exist_ok=True)
            path = self.store.backup_dir / f"auto_backup_{datetime.now():%Y%m%d}.json"
            if not path.exists():
                self._export_bundle(path)
            self._rotate_backups()
        except OSError as exc:
            self._set_status(f"자동 백업 실패: {exc}", "warning")

    def _rotate_backups(self, keep: int = 7) -> None:
        candidates = {
            path
            for pattern in ("backup_*.json", "auto_backup_*.json", "before_restore_*.json")
            for path in self.store.backup_dir.glob(pattern)
        }
        backups = sorted(
            candidates,
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in backups[max(1, keep):]:
            path.unlink(missing_ok=True)

    def import_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "전체 복원", str(self.store.backup_dir), "JSON (*.json)"
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            databases = payload.get("databases", {})
            hotkeys = databases.get("hotkeys", {})
            notes = databases.get("alert_notes", {})
            preview = (
                f"단축키 작업 {len(hotkeys.get('hotkey_actions', []))}개, "
                f"메모 {len(notes.get('notes', []))}개, "
                f"일정 {len(notes.get('schedule_items', []))}개"
            )
        except (OSError, ValueError, TypeError):
            preview = "백업 내용 개수를 미리 확인할 수 없습니다."
        if QMessageBox.question(
            self,
            "전체 복원",
            f"복원 대상: {preview}\n\n"
            "현재 단축키 작업·메모·일정·알림·설정을 교체합니다.\n"
            "복원 직전 현재 상태는 안전 백업으로 자동 저장됩니다. 복원할까요?",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            safety_path = self.store.backup_dir / f"before_restore_{now_key()}.json"
            self._export_bundle(safety_path)
            import_database_bundle(
                {
                    "hotkeys": (self.store.conn, HOTKEY_COLUMNS),
                    "alert_notes": (
                        self.note_store.conn,
                        {"notes": list(NOTE_COLUMNS), "note_attachments": list(ATTACHMENT_COLUMNS),
                         "reminder_series": list(SERIES_COLUMNS),
                         "reminders": list(REMINDER_COLUMNS), "reminder_history": list(HISTORY_COLUMNS),
                         "settings": list(SETTING_COLUMNS), "schedule_items": list(ITEM_COLUMNS),
                         "schedule_notifications": list(NOTIFICATION_COLUMNS),
                         "schedule_notification_log": list(NOTIFICATION_LOG_COLUMNS),
                         "schedule_occurrence_exceptions": list(EXCEPTION_COLUMNS)},
                    ),
                },
                Path(path),
                legacy_name="hotkeys",
            )
        except Exception as exc:
            QMessageBox.warning(self, "전체 복원 실패", str(exc))
            return
        QMessageBox.information(
            self,
            "전체 복원 완료",
            "전체 데이터를 복원했습니다. 변경된 설정을 적용하기 위해 프로그램을 종료합니다.",
        )
        QApplication.instance().quit()

    def export_excel(self) -> None:
        default = self.store.data_dir / f"hotkey_actions_{now_key()}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Excel 내보내기", str(default), "Excel (*.xlsx)")
        if not path:
            return
        output = export_actions_xlsx(self.store.actions(), Path(path))
        QMessageBox.information(self, "Excel 내보내기 완료", str(output))

    def import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Excel 가져오기", str(self.store.data_dir), "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            actions = import_actions_xlsx(Path(path))
            current_count = len(self.store.actions())
            trash_count = len(self.store.trashed_actions())
            backup_path = self.store.data_dir / f"backup_{now_key()}.json"
            if QMessageBox.question(
                self,
                "Excel 가져오기 확인",
                f"가져올 작업: {len(actions)}개\n"
                f"교체될 현재 작업: {current_count}개\n"
                f"영구 삭제될 휴지통 작업: {trash_count}개\n\n"
                f"교체 전 백업: {backup_path}\n\n계속할까요?",
            ) != QMessageBox.StandardButton.Yes:
                return
            self.store.export_json(backup_path)
            self.store.replace_actions(actions)
        except ExcelImportError as exc:
            QMessageBox.warning(self, "Excel 가져오기 실패", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "Excel 가져오기 실패", str(exc))
            return
        self.current_id = None
        self.refresh()
        self.register_hotkeys(False)
        QMessageBox.information(self, "Excel 가져오기 완료", f"{len(actions)}개 작업을 가져왔습니다.\n백업: {backup_path}")

    def nativeEvent(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        hotkeys = getattr(self, "hotkeys", None)
        if hotkeys is not None and hotkeys.handle_native_event(message):
            return True, 0
        return False, 0

    def closeEvent(self, event) -> None:
        if not self._confirm_action_form_transition():
            event.ignore()
            return
        self._restore_hidden_windows_on_exit()
        self._cancel_resize_drag()
        self._foreground_hotkey_timer.stop()
        if hasattr(self, "alert_service"):
            self.alert_service.stop()
        if hasattr(self, "pet_controller"):
            self.pet_controller.stop()
        if hasattr(self, "alert_panel"):
            self.alert_panel.shutdown()
        self._save_window_geometry()
        self._save_splitter_sizes()
        if self._recording:
            self.recorder.stop()
        self._set_explorer_double_click_enabled(False, persist=False)
        self._set_explorer_middle_click_enabled(False, persist=False)
        self.window_pin.shutdown()
        QApplication.instance().removeEventFilter(self)
        self.hotkeys.unregister_all()
        # 갈고리를 건 채로 나가면 다음에 켤 때까지 키가 새어 나간다.
        shutdown_hotkeys = getattr(self.hotkeys, "shutdown", None)
        if shutdown_hotkeys is not None:
            shutdown_hotkeys()
        tray_icon = getattr(self, "tray_icon", None)
        if tray_icon is not None:
            tray_icon.hide()
        if not getattr(self, "_note_store_closed", False):
            self.note_store.close()
            self._note_store_closed = True
        super().closeEvent(event)

    def _resize_hit_test(self, lparam: int) -> int | None:
        if self.isMaximized():
            return None
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        edges = self._resize_edges_at(QPointF(x, y).toPoint())
        hit_tests = {
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge: 13,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge: 14,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: 16,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge: 17,
            Qt.Edge.LeftEdge: 10,
            Qt.Edge.RightEdge: 11,
            Qt.Edge.TopEdge: 12,
            Qt.Edge.BottomEdge: 15,
        }
        return hit_tests.get(edges)

    def _cancel_resize_drag(self) -> None:
        self._resize_drag = None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.unsetCursor()

    def _resize_edges_at(self, global_point) -> Qt.Edge:
        if self.isMaximized():
            return Qt.Edge(0)
        point = self.mapFromGlobal(global_point)
        border = max(8, round(10 * self._ui_scale))
        corner = max(16, round(18 * self._ui_scale))
        near_left, near_right = point.x() < corner, point.x() >= self.width() - corner
        near_top, near_bottom = point.y() < corner, point.y() >= self.height() - corner
        if near_top and near_left:
            return Qt.Edge.TopEdge | Qt.Edge.LeftEdge
        if near_top and near_right:
            return Qt.Edge.TopEdge | Qt.Edge.RightEdge
        if near_bottom and near_left:
            return Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        if near_bottom and near_right:
            return Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        left, right = point.x() < border, point.x() >= self.width() - border
        top, bottom = point.y() < border, point.y() >= self.height() - border
        edges = Qt.Edge(0)
        if left:
            return Qt.Edge.LeftEdge
        if right:
            return Qt.Edge.RightEdge
        if top:
            return Qt.Edge.TopEdge
        if bottom:
            return Qt.Edge.BottomEdge
        return edges

    def _set_resize_cursor(self, edges: Qt.Edge) -> None:
        cursors = {
            Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeBDiagCursor,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeBDiagCursor,
        }
        cursor = cursors.get(edges)
        if cursor is None:
            self.unsetCursor()
        else:
            self.setCursor(cursor)

    def _resize_from_drag(self, global_point) -> None:
        """Resize reliably even when the frameless window has no native frame."""
        edges, start_point, start_geometry = self._resize_drag
        dx = global_point.x() - start_point.x()
        dy = global_point.y() - start_point.y()
        geometry = QRect(start_geometry)
        min_width = self.minimumWidth()
        min_height = self.minimumHeight()
        if edges & Qt.Edge.LeftEdge:
            geometry.setLeft(min(start_geometry.right() - min_width + 1, start_geometry.left() + dx))
        if edges & Qt.Edge.RightEdge:
            geometry.setRight(max(start_geometry.left() + min_width - 1, start_geometry.right() + dx))
        if edges & Qt.Edge.TopEdge:
            geometry.setTop(min(start_geometry.bottom() - min_height + 1, start_geometry.top() + dy))
        if edges & Qt.Edge.BottomEdge:
            geometry.setBottom(max(start_geometry.top() + min_height - 1, start_geometry.bottom() + dy))
        self.setGeometry(geometry)


def _page(widgets: list[QWidget]) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    for widget in widgets:
        layout.addWidget(widget)
    return page


def _form_page(label: str, widget: QWidget) -> QWidget:
    page = QWidget()
    layout = QFormLayout(page)
    layout.addRow(label, widget)
    return page


def _default_macro_json() -> str:
    payload = {
        "steps": [
            {"type": "click", "x": 500, "y": 300},
            {"type": "wait", "seconds": 0.3},
            {"type": "text", "text": "입력할 문구", "press_enter": False},
        ],
        "timing_mode": "scaled",
        "playback_speed": 1.0,
        "repeat_count": 1,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _dict_row(data: dict) -> dict:
    return {
        "id": data.get("id") or 0,
        "name": data["name"],
        "hotkey": data["hotkey"],
        "action_type": data["action_type"],
        "payload": json.dumps(data["payload"], ensure_ascii=False),
        "active": int(data["active"]),
    }


REGISTRATION_LINK_STYLE = "color:#157347; font-weight:700; text-decoration:none;"


def _registration_status_color(status: str) -> str:
    return {
        "등록됨": "#176448",
        "등록 실패": "#B42318",
        "제외 중": "#815B10",
        "비활성": "#64748B",
        "확인 중": "#64748B",
    }.get(status, "#64748B")

