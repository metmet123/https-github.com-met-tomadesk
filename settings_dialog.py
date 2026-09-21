"""Focused application settings dialog."""

import tempfile
from pathlib import Path
from alert_notes.external_ai_policy import ExternalAIPolicy

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from hotkey_builder import HotkeyBuilder
from hotkey_parser import parse_hotkey
from screen_ocr import WindowsOcrBackend
from ui_polish import polish_button
from storage_config import is_system_temporary_path
from alert_notes.value_input_guard import install_value_input_guard
from alert_notes.schedule_postit_settings import (
    COMPLETE_STRIKE, COMPLETE_TRASH, SchedulePostitPreferences,
    VIEW_DAY, VIEW_DUE, VIEW_PRIORITY, VIEW_WEEK,
)


HOTKEY_FIELDS = (
    ("exit_hotkey", "프로그램 종료"),
    ("main_open_hotkey", "메인창 열기"),
    ("tray_hide_hotkey", "트레이로 숨기기"),
    ("record_stop_hotkey", "녹화 종료"),
    ("playback_stop_hotkey", "실행 긴급 중지"),
    ("quick_memo_hotkey", "빠른 메모"),
    ("new_memo_hotkey", "새 메모"),
    ("today_view_hotkey", "오늘 일정 열기"),
    ("memo_search_hotkey", "메모·일정 검색"),
    ("quick_schedule_hotkey", "빠른 일정"),
    ("window_pin_hotkey", "창 고정/해제"),
    ("shortcut_overlay_hotkey", "단축키 안내"),
    ("file_rename_hotkey", "파일 이름 일괄 변경"),
    ("screen_ocr_hotkey", "화면 글자 따기"),
)
# key, label, help text, default.  Kept here so the dialog and the window agree.
DEADLINE_OPTIONS = (
    (
        "deadline_hide_finished", "카운트를 끝낸 D-Day 숨기기",
        "끄면 끝낸 D-Day도 목록에 취소선으로 남습니다.", False,
    ),
    (
        "deadline_notify_day_before", "하루 전에 미리 알림",
        "목표 시각 하루 전 같은 시각에 한 번 더 알립니다.", True,
    ),
    (
        "deadline_pet_on_the_day", "당일 아침에 한 번 알려주기",
        "그날 처음 프로그램을 켤 때 트레이 알림으로 오늘의 D-Day를 알립니다.", True,
    ),
    (
        "deadline_show_top_chip", "상단 바에 가장 임박한 D-Day 표시",
        "끄면 오늘 요약과 트레이에만 표시합니다.", True,
    ),
    (
        "deadline_count_today_as_one", "목표일을 1일째로 세기",
        "끄면 목표일 당일이 D-DAY, 켜면 D-1입니다. 기념일을 셀 때 켜세요.", False,
    ),
    (
        "calendar_dim_past", "지난 일정 흐리게",
        "지난 일정만 흐려집니다. 지난 D-Day는 마감이 남아 있다는 뜻이라 그대로 둡니다.", True,
    ),
    (
        "schedule_nlp_enabled", "제목에서 날짜·시간 읽기",
        "‘내일 오후 3시 팀 회의’처럼 적으면 시간과 분류를 자동으로 채웁니다. "
        "직접 고친 항목은 건드리지 않고, 끄면 제목을 있는 그대로 둡니다.", True,
    ),
)
HOTKEY_DEFAULTS = {
    "exit_hotkey": "Ctrl+Alt+F9", "main_open_hotkey": "Ctrl+Alt+F10",
    "tray_hide_hotkey": "Ctrl+Alt+F11", "record_stop_hotkey": "Ctrl+Alt+F12",
    "playback_stop_hotkey": "Ctrl+Alt+Esc", "quick_memo_hotkey": "Ctrl+Alt+N",
    "new_memo_hotkey": "Ctrl+Alt+Shift+N",
    "today_view_hotkey": "Ctrl+Alt+C", "memo_search_hotkey": "Ctrl+Alt+M",
    "quick_schedule_hotkey": "Ctrl+Alt+A",
    "window_pin_hotkey": "Ctrl+Alt+T",
    "shortcut_overlay_hotkey": "Ctrl+Alt+H",
    "file_rename_hotkey": "",
    "screen_ocr_hotkey": "Ctrl+Alt+O",
}


class SettingsDialog(QDialog):
    def __init__(
        self,
        hotkeys: dict[str, str],
        startup_mode: str,
        data_dir: Path,
        backup_dir: Path | None = None,
        action_hotkeys: set[str] | None = None,
        on_full_backup=None,
        on_full_restore=None,
        pet_alert_enabled: bool = True,
        pet_persistent_enabled: bool = False,
        memo_auto_save_enabled: bool = True,
        show_start_guide_on_launch: bool = True,
        explorer_double_click_enabled: bool = True,
        explorer_middle_click_enabled: bool = True,
        deadline_options: dict | None = None,
        schedule_postit_options: dict | None = None,
        parent=None,
        external_ai_store=None,
    ):
        super().__init__(parent)
        self.external_ai_policy = ExternalAIPolicy(
            external_ai_store if external_ai_store is not None else getattr(parent, "note_store", None)
        )
        self.accepted.connect(self._save_external_ai_policy)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._action_hotkeys = action_hotkeys or set()
        self._original_hotkeys = {
            key: hotkeys.get(key, HOTKEY_DEFAULTS[key]) for key, _label in HOTKEY_FIELDS
        }
        self._accepted_hotkey_values: dict[str, str] | None = None
        postit_options = dict(schedule_postit_options or {})
        self._original_schedule_postit_hotkey = str(postit_options.get("hotkey") or "")
        self._accepted_schedule_postit_hotkey: str | None = None
        self._on_full_backup = on_full_backup
        self._on_full_restore = on_full_restore
        self.data_dir = Path(data_dir)
        # Backups live in the data folder now; the argument is kept so existing
        # callers keep working, but there is no separate path to configure.
        self.backup_dir = self.data_dir
        self.path_labels: dict[str, QLabel] = {}
        self.reset_pet_position_requested = False
        self._ui_scale = max(0.8, min(1.5, float(getattr(parent, "_ui_scale", 1.0))))
        self.setWindowTitle("설정")
        extra_scale = max(0.0, self._ui_scale - 1.0)
        # Wide enough that the key box still shows "Backspace" rather than "ace".
        dialog_width = round(1150 + (460 * extra_scale))
        # 스크롤이 없는 창이므로 모든 칸이 보일 만큼은 열려야 한다.  다만
        # 필요한 높이는 아래에서 sizeHint 로 다시 재므로 여기서는 바닥값만 둔다.
        dialog_height = round(680 + (300 * extra_scale))
        self.setMinimumSize(
            round(1080 + (460 * extra_scale)),
            round(660 + (280 * extra_scale)),
        )
        self.resize(dialog_width, dialog_height)
        shell = QVBoxLayout(self)
        shell.setContentsMargins(18, 16, 18, 14)
        shell.setSpacing(8)

        title = QLabel("프로그램 설정")
        title.setObjectName("pageTitle")
        shell.addWidget(title)
        subtitle = QLabel("전역 단축키, 시작 위치, 데이터 저장 위치를 설정합니다.")
        subtitle.setObjectName("mutedLabel")
        shell.addWidget(subtitle)

        settings_grid = QGridLayout()
        settings_grid.setContentsMargins(0, 4, 0, 0)
        settings_grid.setHorizontalSpacing(10)
        settings_grid.setVerticalSpacing(0)
        settings_grid.setColumnStretch(0, 70)
        settings_grid.setColumnStretch(1, 30)

        self.hotkey_builders: dict[str, HotkeyBuilder] = {}
        self.hotkey_field_widgets: list[QWidget] = []
        hotkey_card, hotkey_layout = _card("단축키")
        self.hotkey_card = hotkey_card
        hotkey_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.hotkey_grid = QGridLayout()
        self.hotkey_grid.setContentsMargins(0, 0, 0, 0)
        self.hotkey_grid.setHorizontalSpacing(14)
        self.hotkey_grid.setVerticalSpacing(6)
        self.hotkey_conflict_labels: dict[str, QLabel] = {}
        self.hotkey_reset_buttons: dict[str, QPushButton] = {}
        for key, label in HOTKEY_FIELDS:
            builder = HotkeyBuilder()
            if key == "file_rename_hotkey":
                builder.setAllowEmpty(True)
            builder.setText(hotkeys.get(key, HOTKEY_DEFAULTS[key]))
            builder.setAccessibleName(label)
            # 열 줄이 세로로 늘어선 칸이라 한 줄이 낮아지는 만큼이 그대로
            # 창 높이로 돌아온다.  낮춘 값은 ui_theme 의 같은 이름 규칙과 짝이다.
            builder.setObjectName("settingsHotkeyBuilder")
            builder.setMinimumHeight(32)
            self.hotkey_builders[key] = builder
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(2)
            heading_row = QHBoxLayout()
            heading_row.setContentsMargins(0, 0, 0, 0)
            heading_row.setSpacing(6)
            heading_row.addWidget(QLabel(label))
            heading_row.addStretch()
            # Getting back to the shipped default used to mean remembering it.
            reset = QPushButton("기본값")
            reset.setObjectName("linkButton")
            reset.setAccessibleName(f"{label} 기본값으로")
            reset.setToolTip(f"기본값 {HOTKEY_DEFAULTS[key]}(으)로 되돌립니다.")
            reset.setCursor(Qt.CursorShape.PointingHandCursor)
            reset.clicked.connect(
                lambda _checked=False, target=key: self._reset_hotkey_to_default(target)
            )
            self.hotkey_reset_buttons[key] = reset
            heading_row.addWidget(reset)
            field_layout.addLayout(heading_row)
            field_layout.addWidget(builder)
            conflict = QLabel("")
            conflict.setObjectName("hotkeyConflictLabel")
            conflict.setWordWrap(True)
            conflict.hide()
            self.hotkey_conflict_labels[key] = conflict
            field_layout.addWidget(conflict)
            builder.changed.connect(self._refresh_hotkey_conflicts)
            self.hotkey_field_widgets.append(field)
        split_index = (len(self.hotkey_field_widgets) + 1) // 2
        for index, field in enumerate(self.hotkey_field_widgets):
            row = index if index < split_index else index - split_index
            column = 0 if index < split_index else 1
            self.hotkey_grid.addWidget(field, row, column)
        self.hotkey_grid.setColumnStretch(0, 1)
        self.hotkey_grid.setColumnStretch(1, 1)
        hotkey_layout.addLayout(self.hotkey_grid)
        _ocr_ready, ocr_message = WindowsOcrBackend().availability()
        self.ocr_status = QLabel(ocr_message)
        self.ocr_status.setWordWrap(True)
        self.ocr_status.setObjectName("mutedLabel")
        hotkey_layout.addWidget(self.ocr_status)
        # 칸이 옆 칸 높이에 맞춰 늘어나면 남는 자리를 머리글이 나눠 가져
        # ‘단축키’ 글자 둘레가 통째로 비었다.  남는 자리는 아래로 보낸다.
        hotkey_layout.addStretch()
        self.main_panel = QWidget()
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)
        main_layout.addWidget(hotkey_card, 1)
        settings_grid.addWidget(self.main_panel, 0, 0)

        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(10)
        startup_card, startup_layout = _card("창 및 트레이")
        self.startup_card = startup_card
        startup_row = QHBoxLayout()
        startup_row.setSpacing(10)
        startup_row.addWidget(QLabel("시작 시"))
        self.startup_combo = QComboBox()
        self.startup_combo.addItem("메인창 열기", "window")
        self.startup_combo.addItem("트레이에서 시작", "tray")
        self.startup_combo.setCurrentIndex(max(0, self.startup_combo.findData(startup_mode)))
        self.startup_combo.setMinimumHeight(36)
        startup_row.addWidget(self.startup_combo, 1)
        startup_layout.addLayout(startup_row)
        self.show_start_guide_check = QCheckBox("프로그램 시작 시 빠른 시작 표시")
        self.show_start_guide_check.setChecked(bool(show_start_guide_on_launch))
        startup_layout.addWidget(self.show_start_guide_check)
        self.explorer_double_click_check = QCheckBox(
            "탐색기 빈 공간 더블클릭 상위 폴더 이동"
        )
        self.explorer_double_click_check.setChecked(bool(explorer_double_click_enabled))
        startup_layout.addWidget(self.explorer_double_click_check)
        self.explorer_middle_click_check = QCheckBox(
            "탐색기 파일 목록 가운데 클릭 상위 폴더 이동"
        )
        self.explorer_middle_click_check.setChecked(bool(explorer_middle_click_enabled))
        startup_layout.addWidget(self.explorer_middle_click_check)
        self.memo_auto_save_check = QCheckBox("메모 자동 저장")
        self.memo_auto_save_check.setChecked(bool(memo_auto_save_enabled))
        startup_layout.addWidget(self.memo_auto_save_check)
        memo_save_help = QLabel(
            "끄면 메모 편집창의 지금 저장 버튼 또는 Ctrl+S로 저장합니다. "
            "저장 전 내용은 7일간 임시 보관됩니다."
        )
        memo_save_help.setObjectName("mutedLabel")
        memo_save_help.setWordWrap(True)
        startup_layout.addWidget(memo_save_help)
        side_layout.addWidget(startup_card)

        # Judgement calls the program should not make on the user's behalf.
        deadline_card, deadline_layout = _card("일정 · D-Day")
        self.deadline_card = deadline_card
        options = dict(deadline_options or {})
        self.deadline_checks: dict[str, QCheckBox] = {}
        deadline_grid = QGridLayout()
        deadline_grid.setContentsMargins(0, 0, 0, 0)
        deadline_grid.setHorizontalSpacing(10)
        deadline_grid.setVerticalSpacing(4)
        # 넓은 왼쪽 칸에 놓이므로 세 줄로 벌린다.  두 줄이면 오른쪽이 비고
        # 칸만 세로로 길어진다.
        self._deadline_columns = 3
        for index, (key, label, help_text, default) in enumerate(DEADLINE_OPTIONS):
            check = QCheckBox(label)
            check.setAccessibleName(label)
            check.setToolTip(help_text)
            check.setChecked(bool(options.get(key, default)))
            deadline_grid.addWidget(
                check, index // self._deadline_columns, index % self._deadline_columns
            )
            self.deadline_checks[key] = check
        for column in range(self._deadline_columns):
            deadline_grid.setColumnStretch(column, 1)
        deadline_layout.addLayout(deadline_grid)
        # 오른쪽 칸만 길어 왼쪽이 200px 남던 것을, 이 칸을 옮겨 맞춘다.
        main_layout.addWidget(deadline_card)

        pet_card, pet_layout = _card("토마펫")
        self.pet_card = pet_card
        self.pet_alert_check = QCheckBox("알림에 토마펫 사용")
        self.pet_alert_check.setAccessibleName("알림에 토마펫 사용")
        self.pet_alert_check.setChecked(bool(pet_alert_enabled))
        pet_layout.addWidget(self.pet_alert_check)
        alert_help = QLabel("알림 내용을 토마펫 말풍선으로 표시합니다.")
        alert_help.setObjectName("mutedLabel")
        pet_layout.addWidget(alert_help)
        self.pet_persistent_check = QCheckBox("토마펫 상시 표시")
        self.pet_persistent_check.setAccessibleName("토마펫 상시 표시")
        self.pet_persistent_check.setChecked(bool(pet_persistent_enabled))
        pet_layout.addWidget(self.pet_persistent_check)
        persistent_help = QLabel("마지막 위치에서 토마펫을 항상 위로 표시합니다.")
        persistent_help.setObjectName("mutedLabel")
        pet_layout.addWidget(persistent_help)
        pet_actions = QHBoxLayout()
        self.pet_position_reset_button = QPushButton("토마펫 위치 초기화")
        self.pet_position_reset_button.setAccessibleName("토마펫 위치 초기화")
        self.pet_position_reset_button.setMinimumHeight(36)
        self.pet_position_reset_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        polish_button(self.pet_position_reset_button)
        self.pet_position_reset_button.clicked.connect(self._request_pet_position_reset)
        pet_actions.addWidget(self.pet_position_reset_button)
        pet_actions.addStretch()
        pet_layout.addLayout(pet_actions)
        # 남는 세로 자리는 칸을 늘리지 않고 칸 아래에 둔다.  속이 빈 카드보다
        # 카드가 끝나고 배경이 보이는 편이 덜 허전하다.
        side_layout.addWidget(pet_card)
        side_layout.addStretch()
        settings_grid.addWidget(side_panel, 0, 1)
        shell.addLayout(settings_grid, 1)

        paths_card, paths_layout = _card("데이터 및 안전")
        self.paths_card = paths_card
        paths_layout.addWidget(self._path_row("data_dir", "데이터 폴더"))
        data_buttons = QHBoxLayout()
        data_buttons.setSpacing(8)
        self.full_backup_button = QPushButton("앱 전체 백업")
        self.full_backup_button.setAccessibleName("앱 전체 백업")
        self.full_backup_button.setMinimumHeight(40)
        polish_button(self.full_backup_button)
        self.full_backup_button.clicked.connect(self._full_backup)
        data_buttons.addWidget(self.full_backup_button)
        self.full_restore_button = QPushButton("앱 전체 복원")
        self.full_restore_button.setAccessibleName("앱 전체 복원")
        self.full_restore_button.setMinimumHeight(40)
        polish_button(self.full_restore_button)
        self.full_restore_button.clicked.connect(self._full_restore)
        data_buttons.addWidget(self.full_restore_button)
        path_note = QLabel(
            "DB와 자동·전체 백업을 모두 데이터 폴더에 저장합니다. "
            "폴더 변경은 프로그램을 다시 시작한 뒤 적용됩니다."
        )
        path_note.setObjectName("mutedLabel")
        path_note.setWordWrap(True)
        data_buttons.addSpacing(8)
        data_buttons.addWidget(path_note, 1)
        paths_layout.addLayout(data_buttons)
        shell.addWidget(paths_card)

        schedule_postit_card, postit_layout = _card("일정 포스트잇")
        self.schedule_postit_card = schedule_postit_card
        self.schedule_postit_checks: dict[str, QCheckBox] = {}
        target_row = QHBoxLayout()
        target_row.setSpacing(12)
        target_row.addWidget(QLabel("표시 대상"))
        for key, label, default in (
            ("show_events", "일정", True),
            ("show_tasks", "할 일", True),
            ("show_memo_deadlines", "메모 D-Day", False),
        ):
            check = QCheckBox(label)
            check.setChecked(bool(postit_options.get(key, default)))
            check.setAccessibleName(f"일정 포스트잇에 {label} 표시")
            self.schedule_postit_checks[key] = check
            target_row.addWidget(check)
        target_row.addStretch()
        postit_layout.addLayout(target_row)

        postit_grid = QGridLayout()
        postit_grid.setHorizontalSpacing(12)
        postit_grid.setVerticalSpacing(8)
        postit_grid.addWidget(QLabel("기본 보기"), 0, 0)
        self.schedule_postit_view_combo = QComboBox()
        for label, value in (
            ("당일", VIEW_DAY), ("이번 주", VIEW_WEEK),
            ("임박순", VIEW_DUE), ("우선도순", VIEW_PRIORITY),
        ):
            self.schedule_postit_view_combo.addItem(label, value)
        current_view = str(postit_options.get("view") or VIEW_DAY)
        self.schedule_postit_view_combo.setCurrentIndex(
            max(0, self.schedule_postit_view_combo.findData(current_view))
        )
        postit_grid.addWidget(self.schedule_postit_view_combo, 0, 1)
        postit_grid.addWidget(QLabel("최대 줄 수"), 1, 0)
        self.schedule_postit_max_rows = QSpinBox()
        self.schedule_postit_max_rows.setRange(3, 15)
        self.schedule_postit_max_rows.setValue(int(postit_options.get("max_rows", 8) or 8))
        self.schedule_postit_max_rows.setSuffix("줄")
        postit_grid.addWidget(self.schedule_postit_max_rows, 1, 1)
        postit_grid.addWidget(QLabel("완료 방식"), 2, 0)
        self.schedule_postit_completion_combo = QComboBox()
        self.schedule_postit_completion_combo.addItem("삭선으로 남기기", COMPLETE_STRIKE)
        self.schedule_postit_completion_combo.addItem("휴지통으로 보내기", COMPLETE_TRASH)
        completion = str(postit_options.get("completion_mode") or COMPLETE_STRIKE)
        self.schedule_postit_completion_combo.setCurrentIndex(
            max(0, self.schedule_postit_completion_combo.findData(completion))
        )
        postit_grid.addWidget(self.schedule_postit_completion_combo, 2, 1)
        postit_grid.addWidget(QLabel("열기 단축키"), 3, 0)
        self.schedule_postit_hotkey_builder = HotkeyBuilder()
        self.schedule_postit_hotkey_builder.setAllowEmpty(True)
        self.schedule_postit_hotkey_builder.setText(self._original_schedule_postit_hotkey)
        self.schedule_postit_hotkey_builder.setAccessibleName("일정 포스트잇 열기 단축키")
        self.schedule_postit_hotkey_builder.key_edit.setPlaceholderText("지정하지 않음")
        self.schedule_postit_hotkey_builder.changed.connect(self._refresh_hotkey_conflicts)
        postit_grid.addWidget(self.schedule_postit_hotkey_builder, 3, 1)
        self.schedule_postit_hotkey_conflict = QLabel("")
        self.schedule_postit_hotkey_conflict.setObjectName("hotkeyConflictLabel")
        self.schedule_postit_hotkey_conflict.setWordWrap(True)
        self.schedule_postit_hotkey_conflict.hide()
        postit_grid.addWidget(self.schedule_postit_hotkey_conflict, 4, 1)
        postit_grid.setColumnStretch(1, 1)
        postit_layout.addLayout(postit_grid)
        postit_help = QLabel(
            "빈 값이면 단축키를 등록하지 않습니다. 지정하면 기존 충돌·위험 조합 검사를 사용합니다."
        )
        postit_help.setObjectName("mutedLabel")
        postit_help.setWordWrap(True)
        postit_layout.addWidget(postit_help)

        # 150%에서도 내부 스크롤 없이 보이도록 기존 카드를 네 범주로 나눈다.
        shell.removeItem(settings_grid)
        shell.removeWidget(paths_card)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("settingsCategoryTabs")
        self.hotkey_page = _settings_page(hotkey_card)
        self.schedule_page = _settings_page(schedule_postit_card, deadline_card)
        self.program_page = _settings_page(startup_card, pet_card)
        self.data_page = _settings_page(paths_card)
        self.settings_tabs.addTab(self.hotkey_page, "단축키")
        self.settings_tabs.addTab(self.schedule_page, "일정·D-Day")
        self.settings_tabs.addTab(self.program_page, "프로그램")
        self.settings_tabs.addTab(self.data_page, "데이터")
        ai_card, ai_layout = _card("외부 AI 연결")
        self.external_ai_combo = QComboBox()
        self.external_ai_combo.setAccessibleName("외부 AI 연결 허용 여부")
        self.external_ai_combo.addItem("차단 — 로컬 기능만 사용", False)
        self.external_ai_combo.addItem("허용 — 연결 기능 추가 후 사용 가능", True)
        self.external_ai_combo.setCurrentIndex(1 if self.external_ai_policy.allowed else 0)
        ai_layout.addWidget(self.external_ai_combo)
        ai_help = QLabel(
            "기본값은 차단입니다. 메모 정리·날짜 계산·저장·PC 알림은 외부 AI 없이 사용할 수 있습니다.\n\n"
            "현재 버전은 실제 AI 연결 기능을 제공하지 않습니다. 허용을 선택해도 메모를 전송하지 않습니다.\n\n"
            "향후 AI 연결을 추가하면 사용자가 AI 정리를 요청한 메모만 전송하도록 적용할 설정입니다. "
            "캘린더 동기화 등 다른 서비스의 연결 설정과는 별개입니다."
        )
        ai_help.setWordWrap(True)
        ai_layout.addWidget(ai_help)
        self.external_ai_page = _settings_page(ai_card)
        self.settings_tabs.addTab(self.external_ai_page, "외부 AI")
        shell.addWidget(self.settings_tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setText("저장")
        save_button.setObjectName("primaryButton")
        polish_button(save_button)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText("취소")
        for button in buttons.buttons():
            button.setMinimumHeight(36)
            polish_button(button)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        shell.addWidget(buttons)
        self.dialog_buttons = buttons
        self._hotkey_columns = 2
        self._value_input_guard = install_value_input_guard(self)
        # Open at least as tall as the content, but never taller than the screen.
        screen = self.screen() or QGuiApplication.primaryScreen()
        ceiling = screen.availableGeometry().height() - 60 if screen is not None else dialog_height
        self.resize(dialog_width, min(max(dialog_height, self.sizeHint().height()), max(dialog_height, ceiling)))
        self._refresh_hotkey_conflicts()

    def _save_external_ai_policy(self) -> None:
        self.external_ai_policy.save(bool(self.external_ai_combo.currentData()))

    def values(self) -> dict:
        values = dict(self._accepted_hotkey_values or {
            key: (_optional_hotkey_text(builder) if key == "file_rename_hotkey" else parse_hotkey(builder.text()).text)
            for key, builder in self.hotkey_builders.items()
        })
        values["startup_mode"] = str(self.startup_combo.currentData())
        values["external_ai_allowed"] = bool(self.external_ai_combo.currentData())
        values["data_dir"] = self.data_dir
        values["toma_pet_alert_enabled"] = self.pet_alert_check.isChecked()
        values["toma_pet_persistent_enabled"] = self.pet_persistent_check.isChecked()
        values["memo_auto_save_enabled"] = self.memo_auto_save_check.isChecked()
        values["explorer_double_click_enabled"] = (
            self.explorer_double_click_check.isChecked()
        )
        values["explorer_middle_click_enabled"] = (
            self.explorer_middle_click_check.isChecked()
        )
        for key, check in self.deadline_checks.items():
            values[key] = check.isChecked()
        values["schedule_postit_preferences"] = SchedulePostitPreferences(
            view=str(self.schedule_postit_view_combo.currentData()),
            max_rows=self.schedule_postit_max_rows.value(),
            show_events=self.schedule_postit_checks["show_events"].isChecked(),
            show_tasks=self.schedule_postit_checks["show_tasks"].isChecked(),
            show_memo_deadlines=self.schedule_postit_checks["show_memo_deadlines"].isChecked(),
            completion_mode=str(self.schedule_postit_completion_combo.currentData()),
            hotkey=(
                self._accepted_schedule_postit_hotkey
                if self._accepted_schedule_postit_hotkey is not None
                else _optional_hotkey_text(self.schedule_postit_hotkey_builder)
            ),
        ).normalized()
        values["show_start_guide_on_launch"] = self.show_start_guide_check.isChecked()
        values["reset_toma_pet_position"] = self.reset_pet_position_requested
        return values

    def _request_pet_position_reset(self) -> None:
        self.reset_pet_position_requested = True
        self.pet_position_reset_button.setText("저장 시 위치 초기화")

    def _full_backup(self) -> None:
        if self._on_full_backup is not None:
            self._on_full_backup()

    def _full_restore(self) -> None:
        if self._on_full_restore is not None:
            self._on_full_restore()

    def _path_row(self, key: str, label: str) -> QFrame:
        row = QFrame()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        heading = QLabel(label)
        heading.setObjectName("settingsPathTitle")
        layout.addWidget(heading)
        path_label = QLabel(str(getattr(self, key)))
        path_label.setObjectName("settingsPath")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(False)
        path_label.setToolTip(str(getattr(self, key)))
        path_label.setMinimumWidth(160)
        path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.path_labels[key] = path_label
        layout.addWidget(path_label, 1)
        select_button = QPushButton("폴더 선택")
        select_button.setAccessibleName(f"{label} 선택")
        select_button.setMinimumHeight(36)
        polish_button(select_button)
        select_button.clicked.connect(lambda: self._select_folder(key, label))
        layout.addWidget(select_button)
        open_button = QPushButton("폴더 열기")
        open_button.setAccessibleName(f"{label} 열기")
        open_button.setMinimumHeight(36)
        polish_button(open_button)
        open_button.clicked.connect(lambda: _open_folder(getattr(self, key), row))
        layout.addWidget(open_button)
        return row

    def _select_folder(self, key: str, label: str) -> None:
        current = Path(getattr(self, key))
        selected = QFileDialog.getExistingDirectory(self, f"{label} 선택", str(current))
        if not selected:
            return
        path = Path(selected)
        if (
            key == "data_dir"
            and is_system_temporary_path(path)
            and not is_system_temporary_path(self.data_dir)
        ):
            QMessageBox.warning(
                self,
                "저장 위치 선택 불가",
                "Windows 임시 폴더는 시스템이나 정리 도구가 삭제할 수 있어 "
                "데이터 저장 위치로 사용할 수 없습니다.\n\n"
                f"선택한 경로: {path}",
            )
            return
        setattr(self, key, path)
        self.path_labels[key].setText(str(path))
        self.path_labels[key].setToolTip(str(path))

    def _reset_hotkey_to_default(self, key: str) -> None:
        self.hotkey_builders[key].setText(HOTKEY_DEFAULTS[key])
        self._refresh_hotkey_conflicts()

    def _refresh_hotkey_conflicts(self, *_args) -> None:
        """Show duplicates while they are being made, not only on save."""
        if not getattr(self, "hotkey_conflict_labels", None):
            return
        labels = dict(HOTKEY_FIELDS)
        texts: dict[str, str] = {}
        for key, _label in HOTKEY_FIELDS:
            try:
                texts[key] = parse_hotkey(self.hotkey_builders[key].text()).text
            except Exception:
                texts[key] = ""
        for key, _label in HOTKEY_FIELDS:
            message = ""
            value = texts[key]
            if value:
                others = [
                    labels[other] for other, text in texts.items()
                    if other != key and text and text == value
                ]
                if others:
                    message = f"{'·'.join(others)}와(과) 같은 조합입니다."
                elif value in self._action_hotkeys:
                    message = "저장된 작업 단축키와 같은 조합입니다."
            conflict = self.hotkey_conflict_labels[key]
            conflict.setText(message)
            conflict.setVisible(bool(message))
        try:
            postit_hotkey = _optional_hotkey_text(self.schedule_postit_hotkey_builder)
            message = ""
            if postit_hotkey:
                duplicates = [labels[key] for key, value in texts.items() if value == postit_hotkey]
                if duplicates:
                    message = f"{'·'.join(duplicates)}와(과) 같은 조합입니다."
                elif postit_hotkey in self._action_hotkeys:
                    message = "저장된 작업·메모·일정 단축키와 같은 조합입니다."
        except Exception as exc:
            message = str(exc)
        self.schedule_postit_hotkey_conflict.setText(message)
        self.schedule_postit_hotkey_conflict.setVisible(bool(message))

    def _validate_and_accept(self) -> None:
        labels = dict(HOTKEY_FIELDS)
        seen: dict[str, str] = {}
        accepted: dict[str, str] = {}
        rejected: list[str] = []
        for key, _label in HOTKEY_FIELDS:
            try:
                hotkey = (_optional_hotkey_text(self.hotkey_builders[key]) if key == "file_rename_hotkey"
                          else parse_hotkey(self.hotkey_builders[key].text()).text)
            except Exception as exc:
                rejected.append(f"{labels[key]}: {exc}")
                hotkey = parse_hotkey(self._original_hotkeys[key]).text if self._original_hotkeys[key] else ""
            if hotkey and (hotkey in seen or hotkey in self._action_hotkeys):
                reason = (
                    f"{labels[seen[hotkey]]}와 중복"
                    if hotkey in seen else "저장된 작업 단축키와 중복"
                )
                rejected.append(f"{labels[key]}: {reason}")
                hotkey = parse_hotkey(self._original_hotkeys[key]).text if self._original_hotkeys[key] else ""
            if hotkey and (hotkey in seen or hotkey in self._action_hotkeys):
                QMessageBox.warning(
                    self, "단축키 중복",
                    "기존 단축키 설정에도 중복이 있어 저장할 수 없습니다. 단축키를 먼저 정리해 주세요.",
                )
                return
            accepted[key] = hotkey
            if hotkey:
                seen[hotkey] = key
        self._accepted_hotkey_values = accepted
        try:
            schedule_postit_hotkey = _optional_hotkey_text(
                self.schedule_postit_hotkey_builder
            )
        except Exception as exc:
            rejected.append(f"일정 포스트잇: {exc}")
            schedule_postit_hotkey = self._original_schedule_postit_hotkey
        if schedule_postit_hotkey and (
            schedule_postit_hotkey in seen or schedule_postit_hotkey in self._action_hotkeys
        ):
            rejected.append("일정 포스트잇: 다른 단축키와 중복")
            schedule_postit_hotkey = self._original_schedule_postit_hotkey
        if schedule_postit_hotkey and (
            schedule_postit_hotkey in seen or schedule_postit_hotkey in self._action_hotkeys
        ):
            QMessageBox.warning(
                self, "단축키 중복",
                "기존 일정 포스트잇 단축키도 다른 단축키와 겹쳐 "
                "저장할 수 없습니다. 단축키를 먼저 정리해 주세요.",
            )
            self._accepted_hotkey_values = None
            return
        self._accepted_schedule_postit_hotkey = schedule_postit_hotkey
        values = self.values()
        try:
            _ensure_writable_directory(values["data_dir"])
        except OSError as exc:
            QMessageBox.warning(self, "폴더 확인", f"선택한 폴더에 저장할 수 없습니다.\n{exc}")
            self._accepted_hotkey_values = None
            return
        if rejected:
            QMessageBox.information(
                self,
                "단축키 설정 유지",
                "다음 단축키 변경은 적용하지 않고 기존 값을 유지합니다. 다른 설정은 저장합니다.\n\n"
                + "\n".join(rejected),
            )
        self.accept()


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("settingsDialogCard")
    card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 14)
    layout.setSpacing(8)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    layout.addWidget(heading)
    return card, layout


def _settings_page(*cards: QWidget) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(4, 10, 4, 4)
    layout.setSpacing(10)
    for card in cards:
        layout.addWidget(card)
    layout.addStretch()
    return page


def _optional_hotkey_text(builder: HotkeyBuilder) -> str:
    raw = builder.text().strip()
    return parse_hotkey(raw).text if raw else ""


def _open_folder(path: Path, parent) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        QMessageBox.warning(parent, "폴더 열기", str(exc))
        return
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        QMessageBox.warning(parent, "폴더 열기", f"폴더를 열 수 없습니다.\n{path}")


def _ensure_writable_directory(path: Path) -> None:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".toma-write-", dir=directory, delete=True):
        pass
