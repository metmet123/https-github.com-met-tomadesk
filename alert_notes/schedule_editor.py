from __future__ import annotations

from datetime import datetime, timedelta
from .schedule_reminders import parse_reminder_value, reminder_input_value

from PyQt6.QtCore import QDateTime, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)

from hotkey_builder import HotkeyBuilder
from hotkey_parser import parse_hotkey
from ui_polish import apply_numeric_font, polish_button
from .datetime_input import CompactDateEdit, CompactTimeEdit
# S3: the interval is meaningless without its unit — "2주마다", not "2 간격".
REPEAT_UNITS = {
    "daily": "일마다", "weekly": "주마다", "monthly": "개월마다", "yearly": "년마다",
}

from .schedule_recurrence import DATETIME_FMT, normalize_rule
from .schedule_day_context import same_day_context


class ScheduleEditor(QWidget):
    saved = pyqtSignal(int)
    deleted = pyqtSignal(int)
    close_requested = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.item_id: int | None = None
        self.occurrence_at: str | None = None
        self.hotkey_validator = None
        self._loading = False
        self._dirty = False
        self._build_ui()
        self.new_item()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)
        header = QHBoxLayout()
        self.heading = QLabel("일정 편집")
        self.heading.setObjectName("sectionTitle")
        header.addWidget(self.heading)
        header.addStretch()
        self.close_button = QPushButton("닫기")
        self.close_button.setAccessibleName("일정 편집기 닫기")
        self.save_button = QPushButton("저장")
        self.save_button.setObjectName("primaryButton")
        for button in (self.close_button, self.save_button):
            button.setMinimumHeight(40)
            polish_button(button)
            header.addWidget(button)
        root.addLayout(header)
        self.mirror_notice = QLabel("메모 알림에서 만들어진 일정입니다. 메모의 알림 설정에서 변경해 주세요.")
        self.mirror_notice.setObjectName("scheduleMirrorNotice")
        self.mirror_notice.setWordWrap(True)
        self.mirror_notice.hide()
        root.addWidget(self.mirror_notice)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("일정 또는 할 일 제목")
        self.details_edit = QTextEdit()
        self.details_edit.setPlaceholderText("메모와 준비 사항")
        self.details_edit.setMaximumHeight(92)
        self.type_combo = QComboBox()
        self.type_combo.addItem("일정", "event")
        self.type_combo.addItem("할 일", "task")
        self.start_edit = _datetime_edit()
        self.end_edit = _datetime_edit()
        self.all_day_check = QCheckBox("종일")
        self.end_none_check = QCheckBox("종료 없음")
        # CAL4: moving the start drags the end along instead of refusing to save.
        self._span_minutes = 60
        self._syncing_range = False
        self.start_edit.changed.connect(self._start_moved)
        self.end_edit.changed.connect(self._end_moved)
        self.all_day_check.toggled.connect(self._all_day_toggled)
        self.end_none_check.toggled.connect(self._end_none_toggled)
        self.completed_check = QCheckBox("완료")
        self.count_as_dday_check = QCheckBox("D-Day로 세기")
        self.count_as_dday_check.setAccessibleName("할 일을 D-Day로 세기")
        self.count_as_dday_check.setToolTip("캘린더와 D-Day 보기에 이 할 일의 마감을 표시합니다.")
        self.category_combo = QComboBox()
        for label, key in (("업무", "sky"), ("개인", "mint"), ("중요", "peach"), ("학습", "vanilla"), ("기타", "lavender")):
            self.category_combo.addItem(label, key)
        self.priority_combo = QComboBox()
        for label, value in (("없음", 0), ("낮음", 1), ("보통", 2), ("높음", 3)):
            self.priority_combo.addItem(label, value)
        self.note_combo = QComboBox()
        form = QFormLayout()
        self.form = form
        form.setSpacing(8)
        form.addRow("제목", self.title_edit)
        form.addRow("종류", self.type_combo)
        form.addRow("시작", self.start_edit)
        form.addRow("종료", self.end_edit)
        form.setRowVisible(self.type_combo, False)
        flags = QHBoxLayout()
        flags.addWidget(self.all_day_check)
        flags.addWidget(self.end_none_check)
        flags.addWidget(self.completed_check)
        flags.addWidget(self.count_as_dday_check)
        flags.addStretch()
        form.addRow("상태", flags)
        form.addRow("분류", self.category_combo)
        root.addLayout(form)
        details_label = QLabel("메모 내용")
        details_label.setObjectName("mutedLabel")
        root.addWidget(details_label)
        root.addWidget(self.details_edit)

        self.day_context_card = QFrame()
        self.day_context_card.setObjectName("scheduleSubCard")
        day_context_layout = QVBoxLayout(self.day_context_card)
        day_context_layout.setContentsMargins(10, 8, 10, 8)
        day_context_layout.setSpacing(4)
        day_context_heading = QLabel("같은 날 다른 일정")
        day_context_heading.setObjectName("mutedLabel")
        day_context_layout.addWidget(day_context_heading)
        self.day_context_list = QListWidget()
        self.day_context_list.setObjectName("scheduleDayContextList")
        self.day_context_list.setAccessibleName("같은 날 다른 일정과 겹침")
        self.day_context_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.day_context_list.setMaximumHeight(92)
        day_context_layout.addWidget(self.day_context_list)
        root.addWidget(self.day_context_card)
        self.start_edit.changed.connect(self._refresh_day_context)
        self.end_edit.changed.connect(self._refresh_day_context)

        self.additional_button = QPushButton("추가 설정  ▾")
        self.additional_button.setObjectName("helpDisclosureButton")
        self.additional_button.setCheckable(True)
        self.additional_button.setAccessibleName("추가 설정 펼치기")
        root.addWidget(self.additional_button)
        self.additional_card = QFrame()
        self.additional_card.setObjectName("scheduleAdditionalCard")
        additional_layout = QVBoxLayout(self.additional_card)
        additional_layout.setContentsMargins(10, 10, 10, 10)
        additional_layout.setSpacing(10)
        additional_form = QFormLayout()
        additional_form.addRow("우선순위", self.priority_combo)
        additional_form.addRow("연결 메모", self.note_combo)
        additional_layout.addLayout(additional_form)

        repeat_card = QFrame()
        repeat_card.setObjectName("scheduleSubCard")
        self.repeat_layout = repeat_layout = QFormLayout(repeat_card)
        self.repeat_combo = QComboBox()
        for label, key in (("반복 안 함", "none"), ("매일", "daily"), ("매주", "weekly"), ("매월", "monthly"), ("매년", "yearly")):
            self.repeat_combo.addItem(label, key)
        self.repeat_interval = QSpinBox()
        self.repeat_interval.setRange(1, 365)
        # S3: "1 간격" said nothing; the unit follows the repeat kind.
        self.repeat_interval.setSuffix(REPEAT_UNITS["daily"])
        apply_numeric_font(self.repeat_interval)
        self.weekdays_edit = QLineEdit()
        self.weekdays_edit.setPlaceholderText("주간 반복 요일: 월,수,금")
        self.repeat_end_combo = QComboBox()
        self.repeat_end_combo.addItem("종료 없음", "none")
        self.repeat_end_combo.addItem("날짜까지", "date")
        self.repeat_end_combo.addItem("횟수", "count")
        self.repeat_until_edit = _datetime_edit()
        self.repeat_count_spin = QSpinBox()
        self.repeat_count_spin.setRange(1, 9999)
        self.repeat_count_spin.setSuffix("회")
        apply_numeric_font(self.repeat_count_spin)
        self.reminders_edit = QLineEdit()
        self.reminders_edit.setPlaceholderText("예: 10, 5분 후 (숫자는 분 전, 최대 5개)")
        repeat_layout.addRow("반복", self.repeat_combo)
        repeat_layout.addRow("반복 간격", self.repeat_interval)
        repeat_layout.addRow("반복 요일", self.weekdays_edit)
        repeat_layout.addRow("반복 종료", self.repeat_end_combo)
        repeat_layout.addRow("종료 날짜", self.repeat_until_edit)
        repeat_layout.addRow("반복 횟수", self.repeat_count_spin)
        repeat_layout.addRow("미리 알림", self.reminders_edit)
        self.repeat_combo.currentIndexChanged.connect(self._sync_repeat_controls)
        self.repeat_end_combo.currentIndexChanged.connect(self._sync_repeat_controls)
        additional_layout.addWidget(repeat_card)

        self.occurrence_only_check = QCheckBox("이번 일정의 시간만 변경")
        self.skip_occurrence_button = QPushButton("이번 일정 건너뛰기")
        self.skip_occurrence_button.setObjectName("dangerButton")
        self.skip_occurrence_button.setMinimumHeight(40)
        polish_button(self.skip_occurrence_button)
        self.skip_occurrence_button.clicked.connect(self._skip_occurrence)
        occurrence_row = QHBoxLayout()
        occurrence_row.addWidget(self.occurrence_only_check)
        occurrence_row.addStretch()
        occurrence_row.addWidget(self.skip_occurrence_button)
        additional_layout.addLayout(occurrence_row)

        hotkey_card = QFrame()
        hotkey_card.setObjectName("memoSectionCard")
        hotkey_layout = QFormLayout(hotkey_card)
        self.hotkey_enabled = QCheckBox("메모별 단축키 사용")
        self.hotkey_edit = HotkeyBuilder()
        self.hotkey_action_combo = QComboBox()
        self.hotkey_action_combo.addItem("메모·일정 열기", "open")
        self.hotkey_action_combo.addItem("포스트잇 표시·숨김", "postit")
        hotkey_layout.addRow("", self.hotkey_enabled)
        hotkey_layout.addRow("전역 단축키", self.hotkey_edit)
        hotkey_layout.addRow("실행 동작", self.hotkey_action_combo)
        self.hotkey_enabled.toggled.connect(self.hotkey_edit.setEnabled)
        self.hotkey_enabled.toggled.connect(self.hotkey_action_combo.setEnabled)
        additional_layout.addWidget(hotkey_card)

        buttons = QHBoxLayout()
        self.new_button = QPushButton("새 일정")
        self.delete_button = QPushButton("삭제")
        self.delete_button.setObjectName("dangerButton")
        for button in (self.new_button, self.delete_button):
            button.setMinimumHeight(40)
            polish_button(button)
            buttons.addWidget(button)
        buttons.addStretch()
        additional_layout.addLayout(buttons)
        root.addWidget(self.additional_card)
        root.addStretch()
        self.additional_card.hide()
        self.new_button.clicked.connect(
            lambda: self.new_item(item_type=getattr(self, "_editor_kind", "event"))
        )
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)
        self.close_button.clicked.connect(self.request_close)
        self.additional_button.toggled.connect(self._toggle_additional)
        self._connect_dirty_tracking()

    def new_item(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        item_type: str = "event",
    ) -> None:
        self._loading = True
        self._set_mirror_read_only(False)
        self.item_id = None
        self.occurrence_at = None
        self._refresh_notes()
        start = (start or datetime.now() + timedelta(minutes=30)).replace(second=0, microsecond=0)
        end = end or start + timedelta(hours=1)
        self.title_edit.clear()
        self.details_edit.clear()
        self.type_combo.setCurrentIndex(0)
        self._set_editor_kind(item_type)
        self.start_edit.setDateTime(QDateTime(start))
        self.end_edit.setDateTime(QDateTime(end))
        self.all_day_check.setChecked(False)
        self.end_none_check.setChecked(False)
        self.completed_check.setChecked(False)
        self.count_as_dday_check.setChecked(False)
        self.category_combo.setCurrentIndex(0)
        self.priority_combo.setCurrentIndex(0)
        self.repeat_combo.setCurrentIndex(0)
        self.repeat_interval.setValue(1)
        self.weekdays_edit.clear()
        self.repeat_end_combo.setCurrentIndex(0)
        self.repeat_until_edit.setDateTime(QDateTime(start + timedelta(days=30)))
        self.repeat_count_spin.setValue(10)
        self.reminders_edit.clear()
        self.hotkey_enabled.setChecked(False)
        self.hotkey_edit.setText("Ctrl+Alt+1")
        self.hotkey_edit.setEnabled(False)
        self.hotkey_action_combo.setEnabled(False)
        self.hotkey_action_combo.setCurrentIndex(0)
        self.delete_button.setEnabled(False)
        self.occurrence_only_check.setVisible(False)
        self.skip_occurrence_button.setVisible(False)
        self._sync_repeat_controls()
        self.additional_button.setChecked(False)
        self._loading = False
        self._dirty = False
        self._refresh_day_context()
        self.title_edit.setFocus()

    def load_item(self, item_id: int, occurrence_at: str | None = None) -> None:
        item = self.store.schedules.item(item_id)
        if item is None:
            return
        item_type = str(item["item_type"] or "")
        if item_type not in {"event", "task"}:
            QMessageBox.warning(
                self,
                "일정 종류 확인",
                "저장된 종류가 일정과 할 일 중 하나로 확인되지 않아 "
                "자동 변환하지 않았습니다.",
            )
            return
        self._loading = True
        self.item_id = int(item["id"])
        self.occurrence_at = occurrence_at
        self._set_editor_kind(item_type)
        self._refresh_notes()
        self.title_edit.setText(str(item["title"]))
        self.details_edit.setPlainText(str(item["details"]))
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(item["item_type"])))
        self.start_edit.setDateTime(QDateTime(datetime.strptime(item["start_at"], DATETIME_FMT)))
        saved_start = datetime.strptime(item["start_at"], DATETIME_FMT)
        saved_end = datetime.strptime(item["end_at"], DATETIME_FMT)
        self.end_edit.setDateTime(QDateTime(
            saved_start + timedelta(hours=1) if item["time_mode"] == "point" else saved_end
        ))
        self.all_day_check.setChecked(bool(item["all_day"]))
        self.end_none_check.setChecked(item["time_mode"] == "point")
        self.completed_check.setChecked(item["status"] == "completed")
        self.count_as_dday_check.setChecked(bool(item["count_as_dday"]))
        self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(item["category"])))
        self.priority_combo.setCurrentIndex(max(0, self.priority_combo.findData(item["priority"])))
        self.note_combo.setCurrentIndex(max(0, self.note_combo.findData(item["note_id"])))
        rule = normalize_rule(item["recurrence_rule"])
        self.repeat_combo.setCurrentIndex(max(0, self.repeat_combo.findData(rule["frequency"])))
        self.repeat_interval.setValue(rule["interval"])
        self.weekdays_edit.setText(",".join("월화수목금토일"[day] for day in rule["weekdays"]))
        end_mode = "count" if rule["count"] else "date" if rule["until"] else "none"
        self.repeat_end_combo.setCurrentIndex(max(0, self.repeat_end_combo.findData(end_mode)))
        if rule["until"]:
            self.repeat_until_edit.setDateTime(QDateTime(datetime.strptime(rule["until"], DATETIME_FMT)))
        self.repeat_count_spin.setValue(rule["count"] or 10)
        self.reminders_edit.setText(", ".join(map(reminder_input_value, self.store.schedules.notifications(self.item_id))))
        self.hotkey_enabled.setChecked(bool(item["hotkey"]))
        self.hotkey_edit.setText(str(item["hotkey"] or "Ctrl+Alt+1"))
        self.hotkey_action_combo.setCurrentIndex(max(0, self.hotkey_action_combo.findData(item["hotkey_action"])))
        is_mirror = item["source_reminder_id"] is not None
        self._set_mirror_read_only(is_mirror)
        self.delete_button.setEnabled(not is_mirror)
        recurring_occurrence = rule["frequency"] != "none" and bool(occurrence_at)
        self.occurrence_only_check.setVisible(recurring_occurrence)
        self.skip_occurrence_button.setVisible(recurring_occurrence)
        self.occurrence_only_check.setChecked(False)
        if recurring_occurrence:
            master_start = datetime.strptime(item["start_at"], DATETIME_FMT)
            master_end = datetime.strptime(item["end_at"], DATETIME_FMT)
            occurrence_start = datetime.strptime(occurrence_at, DATETIME_FMT)
            self.start_edit.setDateTime(QDateTime(occurrence_start))
            self.end_edit.setDateTime(QDateTime(occurrence_start + (master_end - master_start)))
        self.additional_button.setChecked(recurring_occurrence)
        self._loading = False
        self._dirty = False
        self._refresh_day_context()

    def _set_mirror_read_only(self, read_only: bool) -> None:
        self.mirror_notice.setVisible(read_only)
        controls = (
            self.title_edit, self.details_edit, self.type_combo, self.start_edit, self.end_edit,
            self.all_day_check, self.end_none_check, self.completed_check, self.count_as_dday_check,
            self.category_combo, self.priority_combo,
            self.note_combo, self.repeat_combo, self.repeat_interval, self.weekdays_edit,
            self.repeat_end_combo, self.repeat_until_edit, self.repeat_count_spin,
            self.reminders_edit, self.hotkey_enabled, self.hotkey_edit, self.hotkey_action_combo,
            self.occurrence_only_check, self.skip_occurrence_button, self.save_button,
        )
        for control in controls:
            control.setEnabled(not read_only)

    def _range_values(self) -> tuple[str, str]:
        start = self.start_edit.dateTime().toPyDateTime()
        end = self.end_edit.dateTime().toPyDateTime()
        if self.end_none_check.isChecked() and self._editor_kind == "event":
            end = start + timedelta(minutes=1)
        if self.all_day_check.isChecked():
            start = start.replace(hour=0, minute=0)
            end = max(end, start).replace(hour=23, minute=59)
        if end <= start:
            end = start + timedelta(hours=1)
        return start.strftime(DATETIME_FMT), end.strftime(DATETIME_FMT)

    def _start_moved(self) -> None:
        if self._syncing_range:
            return
        start = self.start_edit.dateTime()
        self._syncing_range = True
        try:
            self.end_edit.setDateTime(start.addSecs(self._span_minutes * 60))
        finally:
            self._syncing_range = False

    def _end_moved(self) -> None:
        if self._syncing_range:
            return
        start = self.start_edit.dateTime()
        end = self.end_edit.dateTime()
        if end <= start:
            # Keep the pair valid rather than failing later at save time.
            self._syncing_range = True
            try:
                self.end_edit.setDateTime(start.addSecs(60 * 60))
            finally:
                self._syncing_range = False
            self._span_minutes = 60
            return
        self._span_minutes = max(1, start.secsTo(end) // 60)

    def _all_day_toggled(self, checked: bool) -> None:
        """A whole-day item has no clock, so hide the time boxes."""
        if checked:
            self.end_none_check.setChecked(False)
        self.start_edit.set_time_visible(not checked)
        self.end_edit.set_time_visible(not checked)

    def _end_none_toggled(self, _checked: bool) -> None:
        if self.end_none_check.isChecked():
            self.all_day_check.setChecked(False)
        self.form.setRowVisible(
            self.end_edit, self._editor_kind == "event" and not self.end_none_check.isChecked()
        )

    def values(self) -> dict:
        hotkey = self.hotkey_edit.text().strip() if self.hotkey_enabled.isChecked() else ""
        if hotkey:
            hotkey = parse_hotkey(hotkey).text
        reminders = []
        for value in self.reminders_edit.text().replace(" ", "").split(","):
            if value:
                reminders.append(parse_reminder_value(value))
        return {
            "id": self.item_id, "title": self.title_edit.text(), "details": self.details_edit.toPlainText(),
            "item_type": self._editor_kind,
            "start_at": self._range_values()[0], "end_at": self._range_values()[1],
            "time_mode": "point" if self.end_none_check.isChecked() and self._editor_kind == "event" else "range",
            "all_day": self.all_day_check.isChecked(), "category": self.category_combo.currentData(),
            "priority": self.priority_combo.currentData(),
            "note_id": self.note_combo.currentData(),
            "status": "completed" if self.completed_check.isChecked() else "pending",
            "count_as_dday": self.count_as_dday_check.isChecked(),
            "recurrence_rule": self._recurrence_values(),
            "reminders": reminders, "hotkey": hotkey, "hotkey_action": self.hotkey_action_combo.currentData(),
        }

    def _save(self) -> bool:
        try:
            values = self.values()
            if values["hotkey"] and self.hotkey_validator is not None:
                self.hotkey_validator(values["hotkey"], schedule_id=self.item_id)
            if self.item_id and self.occurrence_at and self.occurrence_only_check.isChecked():
                self.store.schedules.move_occurrence(
                    self.item_id, self.occurrence_at, values["start_at"], values["end_at"]
                )
                item_id = self.item_id
            else:
                item_id = self.store.schedules.save_item(values)
        except Exception as exc:
            QMessageBox.warning(self, "일정 저장", str(exc))
            return False
        self.item_id = item_id
        self._set_editor_kind(self._editor_kind)
        self.delete_button.setEnabled(True)
        self._dirty = False
        self.saved.emit(item_id)
        return True

    def _delete(self) -> None:
        if self.item_id is None:
            return
        if QMessageBox.question(self, "일정 삭제", "선택한 일정을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        item_id = self.item_id
        self.store.schedules.delete_item(item_id)
        self.new_item(item_type=self._editor_kind)
        self.deleted.emit(item_id)

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def request_close(self) -> bool:
        if self._dirty:
            choice = QMessageBox.question(
                self,
                "변경 사항 저장",
                "편집 중인 변경 사항을 저장할까요?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return False
            if choice == QMessageBox.StandardButton.Save and not self._save():
                return False
        self._dirty = False
        self.close_requested.emit()
        return True

    def _toggle_additional(self, checked: bool) -> None:
        self.additional_card.setVisible(checked)
        self.additional_button.setText("추가 설정  ▴" if checked else "추가 설정  ▾")
        self.additional_button.setAccessibleName("추가 설정 접기" if checked else "추가 설정 펼치기")

    def _connect_dirty_tracking(self) -> None:
        for widget in self.findChildren(QLineEdit):
            widget.textChanged.connect(self._mark_dirty)
        for widget in self.findChildren(QTextEdit):
            widget.textChanged.connect(self._mark_dirty)
        for widget in self.findChildren(QComboBox):
            widget.currentIndexChanged.connect(self._mark_dirty)
        for widget in self.findChildren(QCheckBox):
            widget.toggled.connect(self._mark_dirty)
        for widget in self.findChildren(QSpinBox):
            widget.valueChanged.connect(self._mark_dirty)
        for widget in self.findChildren(DateTimeField):
            widget.changed.connect(self._mark_dirty)

    def _mark_dirty(self, *_args) -> None:
        if not self._loading:
            self._dirty = True

    def _skip_occurrence(self) -> None:
        if self.item_id is None or not self.occurrence_at:
            return
        self.store.schedules.skip_occurrence(self.item_id, self.occurrence_at)
        item_id = self.item_id
        self.new_item(item_type=self._editor_kind)
        self.saved.emit(item_id)

    def _recurrence_values(self) -> dict:
        end_mode = self.repeat_end_combo.currentData()
        rule = {
            "frequency": self.repeat_combo.currentData(), "interval": self.repeat_interval.value(),
            "weekdays": _parse_weekdays(self.weekdays_edit.text()),
            "until": self.repeat_until_edit.dateTime().toPyDateTime().strftime(DATETIME_FMT) if end_mode == "date" else "",
            "count": self.repeat_count_spin.value() if end_mode == "count" else 0,
        }
        return rule

    def apply_draft(self, values: dict) -> None:
        """팝오버에서 넘어온 초안을 그대로 이어서 편집한다.

        "전체 편집 ↗"을 눌렀을 때 적어 둔 제목·시간·분류가 사라지면 두 입력
        경로가 하나로 이어지지 않는다."""
        item_type = str(values.get("item_type") or "event")
        self.new_item(item_type=item_type if item_type in {"event", "task"} else "event")
        self._loading = True
        try:
            self.title_edit.setText(str(values.get("title", "")))
            self.details_edit.setPlainText(str(values.get("details", "")))
            start = datetime.strptime(str(values["start_at"]), DATETIME_FMT)
            end = datetime.strptime(str(values["end_at"]), DATETIME_FMT)
            self.start_edit.setDateTime(QDateTime(start))
            is_point = values.get("time_mode") == "point"
            visible_end = start + timedelta(hours=1) if is_point else end
            self.end_edit.setDateTime(QDateTime(visible_end))
            self._span_minutes = max(1, int((visible_end - start).total_seconds() // 60))
            self.all_day_check.setChecked(bool(values.get("all_day")))
            self.end_none_check.setChecked(is_point)
            self.category_combo.setCurrentIndex(
                max(0, self.category_combo.findData(values.get("category")))
            )
            rule = normalize_rule(values.get("recurrence_rule"))
            self.repeat_combo.setCurrentIndex(max(0, self.repeat_combo.findData(rule["frequency"])))
            self.repeat_interval.setValue(rule["interval"])
            self.reminders_edit.setText(", ".join(reminder_input_value(value) for value in values.get("reminders", [])))
            self.note_combo.setCurrentIndex(max(0, self.note_combo.findData(values.get("note_id"))))
            self.count_as_dday_check.setChecked(bool(values.get("count_as_dday", False)))
            self._sync_repeat_controls()
        finally:
            self._loading = False
        self._dirty = True
        self.title_edit.setFocus()

    def _set_editor_kind(self, item_type: str) -> None:
        """전체 편집기의 종류를 진입점과 저장값으로만 결정한다."""
        self._editor_kind = "task" if item_type == "task" else "event"
        self.type_combo.setCurrentIndex(
            max(0, self.type_combo.findData(self._editor_kind))
        )
        is_task = self._editor_kind == "task"
        self.heading.setText(
            ("할 일 편집" if self.item_id is not None else "새 할 일")
            if is_task
            else ("일정 편집" if self.item_id is not None else "새 일정")
        )
        self.title_edit.setPlaceholderText("할 일 제목" if is_task else "일정 제목")
        self.form.labelForField(self.start_edit).setText("마감" if is_task else "시작")
        self.end_none_check.setVisible(not is_task)
        self.form.setRowVisible(self.end_edit, not is_task and not self.end_none_check.isChecked())
        self.count_as_dday_check.setVisible(is_task)
        self.new_button.setText("새 할 일" if is_task else "새 일정")

    def _refresh_day_context(self) -> None:
        if not hasattr(self, "day_context_list"):
            return
        try:
            start_key, end_key = self._range_values()
            start = datetime.strptime(start_key, DATETIME_FMT)
            end = datetime.strptime(end_key, DATETIME_FMT)
            items = same_day_context(
                self.store, start, end, current_id=self.item_id
            )
        except Exception:
            items = []
        self.day_context_list.clear()
        if not items:
            placeholder = QListWidgetItem("같은 날의 다른 일정이 없습니다.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            placeholder.setForeground(QColor("#94a3b8"))
            self.day_context_list.addItem(placeholder)
            return
        for context in items:
            entry = QListWidgetItem(context.label)
            entry.setData(Qt.ItemDataRole.UserRole, context.item_id)
            if context.overlaps:
                entry.setBackground(QColor("#fff0f1"))
                entry.setForeground(QColor("#b42318"))
                entry.setToolTip("현재 편집 중인 시간과 겹칩니다.")
            self.day_context_list.addItem(entry)

    def move_to_date(self, day) -> bool:
        """Point an unsaved draft at another day, keeping its times and title.

        Only a draft moves.  A saved item must never change date because the
        user clicked around the calendar looking for something.
        """
        if self.item_id is not None:
            return False
        start = self.start_edit.dateTime()
        end = self.end_edit.dateTime()
        span = start.secsTo(end)
        moved = QDateTime(day, start.time())
        self._syncing_range = True
        try:
            self.start_edit.setDateTime(moved)
            self.end_edit.setDateTime(moved.addSecs(max(0, span)))
        finally:
            self._syncing_range = False
        return True

    def _sync_repeat_controls(self) -> None:
        """Hide what does not apply instead of greying it.

        A greyed row still costs a line; with 반복 안 함 that was five lines of
        dead space above the buttons.  Rows now collapse to nothing.
        """
        kind = self.repeat_combo.currentData()
        recurring = kind != "none"
        weekly = kind == "weekly"
        end_mode = self.repeat_end_combo.currentData()
        self.repeat_interval.setSuffix(REPEAT_UNITS.get(kind, REPEAT_UNITS["daily"]))
        for widget, visible in (
            (self.repeat_interval, recurring),
            (self.weekdays_edit, recurring and weekly),
            (self.repeat_end_combo, recurring),
            (self.repeat_until_edit, recurring and end_mode == "date"),
            (self.repeat_count_spin, recurring and end_mode == "count"),
        ):
            self.repeat_layout.setRowVisible(widget, visible)
            widget.setEnabled(visible)

    def _refresh_notes(self) -> None:
        current = self.note_combo.currentData() if self.note_combo.count() else None
        self.note_combo.clear()
        self.note_combo.addItem("연결하지 않음", None)
        for note in self.store.notes():
            self.note_combo.addItem(str(note["title"]), int(note["id"]))
        self.note_combo.setCurrentIndex(max(0, self.note_combo.findData(current)))


class DateTimeField(QWidget):
    """Date and time in two boxes you can actually type into.

    QDateTimeEdit only accepts digits section by section, so "20260910" did
    nothing.  CompactDateEdit/CompactTimeEdit already power the memo reminder
    and take 20260910 / 0930 / pasted text.
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.date_edit = CompactDateEdit()
        self.time_edit = CompactTimeEdit()
        for widget in (self.date_edit, self.time_edit):
            widget.setMinimumHeight(38)
        self.date_edit.setAccessibleName("날짜")
        self.time_edit.setAccessibleName("시간")
        row.addWidget(self.date_edit, 3)
        row.addWidget(self.time_edit, 2)
        self.date_edit.dateChanged.connect(lambda _v: self.changed.emit())
        self.time_edit.timeChanged.connect(lambda _v: self.changed.emit())

    def dateTime(self) -> QDateTime:
        return QDateTime(self.date_edit.date(), self.time_edit.time())

    def setDateTime(self, value: QDateTime) -> None:
        blocked = [(w, w.blockSignals(True)) for w in (self.date_edit, self.time_edit)]
        try:
            self.date_edit.setDate(value.date())
            self.time_edit.setTime(value.time())
        finally:
            for widget, previous in blocked:
                widget.blockSignals(previous)

    def set_time_visible(self, visible: bool) -> None:
        self.time_edit.setVisible(visible)


def _datetime_edit() -> DateTimeField:
    return DateTimeField()


def _parse_weekdays(value: str) -> list[int]:
    names = {name: index for index, name in enumerate("월화수목금토일")}
    result = set()
    for part in value.replace("요일", "").replace(" ", "").split(","):
        if part in names:
            result.add(names[part])
        elif part.isdigit() and 0 <= int(part) <= 6:
            result.add(int(part))
    return sorted(result)
