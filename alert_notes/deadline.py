from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout,
)

from .sqlite_store import DATETIME_FMT


def parse_deadline(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), DATETIME_FMT)
    except ValueError:
        return None


# 마감 관리는 목표일을 0일째로(당일 = D-DAY), 기념일 계산은 1일째로 셉니다.  어느
# 쪽이 맞는지는 쓰는 사람에 달렸으므로 설정에서 고르고, 앱 전체가 같은 셈법을 씁니다.
_COUNT_TODAY_AS_ONE = False


def set_count_today_as_one(value: bool) -> None:
    global _COUNT_TODAY_AS_ONE
    _COUNT_TODAY_AS_ONE = bool(value)


def count_today_as_one() -> bool:
    return _COUNT_TODAY_AS_ONE


def countdown_text(value: str, now: datetime | None = None) -> str:
    target = parse_deadline(value)
    if target is None:
        return ""
    current = now or datetime.now()
    days = (target.date() - current.date()).days
    if _COUNT_TODAY_AS_ONE and days >= 0:
        # 오늘이 1일째이므로 남은 날짜에 오늘을 더한다. 지난 날은 그대로 D+.
        return f"D-{days + 1}"
    if days > 0:
        return f"D-{days}"
    if days < 0:
        return f"D+{abs(days)}"
    if target > current:
        minutes = max(1, int((target - current).total_seconds() // 60))
        if minutes < 60:
            return f"{minutes}분"
        hours, remainder = divmod(minutes, 60)
        return f"{hours}시간" + (f" {remainder}분" if remainder else "")
    return "D-DAY"


def deadline_badge_text(note, now: datetime | None = None) -> str:
    countdown = countdown_text(str(note["d_day_at"] or ""), now)
    if not countdown:
        return ""
    label = str(note["d_day_label"] or "").strip()
    return f"{countdown} : {label}" if label and label != "D-Day" else countdown


# How urgent the countdown looks. The same four steps are reused by the summary
# panel, the memo list, the top bar chip and the tray tooltip so one D-Day never
# looks different depending on where you read it.
DEADLINE_URGENCY_STEPS = ("done", "today", "soon", "later", "past")
SOON_WITHIN_DAYS = 7


def is_deadline_done(note) -> bool:
    try:
        return bool(str(note["d_day_done_at"] or "").strip())
    except (IndexError, KeyError):
        return False


def deadline_days_left(value: str, now: datetime | None = None) -> int | None:
    target = parse_deadline(value)
    if target is None:
        return None
    return (target.date() - (now or datetime.now()).date()).days


def deadline_urgency(note, now: datetime | None = None) -> str:
    """One of DEADLINE_URGENCY_STEPS, or "" when the note has no D-Day."""
    days = deadline_days_left(str(note["d_day_at"] or ""), now)
    if days is None:
        return ""
    if is_deadline_done(note):
        return "done"
    if days < 0:
        return "past"
    if days == 0:
        return "today"
    return "soon" if days <= SOON_WITHIN_DAYS else "later"


def deadline_chip_text(note, now: datetime | None = None) -> str:
    """Short countdown for narrow places: D-3 / D-DAY / D+2."""
    return countdown_text(str(note["d_day_at"] or ""), now)


def deadline_title(note) -> str:
    label = str(note["d_day_label"] or "").strip()
    if label and label != "D-Day":
        return label
    return str(note["title"] or "").strip() or "제목 없음"


def reminder_display_text(value: str, now: datetime | None = None) -> str:
    """Format a stored reminder using the user's local calendar date."""
    try:
        due = datetime.strptime(str(value or ""), DATETIME_FMT)
    except ValueError:
        return ""
    current = now or datetime.now()
    time_text = due.strftime("%H:%M")
    if due.date() == current.date():
        return f"{time_text} 🔔"
    return f"{due.month}/{due.day} {time_text} 🔔"


class DeadlineDialog(QDialog):
    def __init__(self, note, parent=None):
        super().__init__(parent)
        self.setWindowTitle("D-Day 설정")
        self.setModal(True)
        self.setMinimumWidth(390)
        self._had_deadline = bool(note and note["d_day_at"])
        root = QVBoxLayout(self)
        title = QLabel("D-Day와 알림")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "메모 목록과 오늘 요약에 D-3 처럼 남은 날짜가 계속 표시됩니다. "
            "목표일이 지나도 사라지지 않고 D+1 로 이어집니다."
        )
        description.setWordWrap(True)
        description.setObjectName("mutedLabel")
        root.addWidget(title)
        root.addWidget(description)
        form = QFormLayout()
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("예: 보고서 제출")
        self.datetime_edit = QDateTimeEdit()
        self.datetime_edit.setCalendarPopup(True)
        self.datetime_edit.setDisplayFormat("yyyy-MM-dd  HH:mm")
        self.datetime_edit.setMinimumDateTime(QDateTime.currentDateTime().addYears(-20))
        self.datetime_edit.setMaximumDateTime(QDateTime.currentDateTime().addYears(50))
        self.alert_check = QCheckBox("목표 시각에 알림도 받기")
        self.alert_check.setToolTip("켜면 알림내역의 예정 알림에도 함께 등록됩니다.")
        self.alert_note = QLabel("알림내역에도 함께 등록됩니다.")
        self.alert_note.setObjectName("mutedLabel")
        self.done_check = QCheckBox("카운트 끝내기")
        self.done_check.setToolTip("D-Day는 목록에 남고 남은 날짜 세기만 멈춥니다.")
        form.addRow("이름", self.label_edit)
        form.addRow("목표 시각", self.datetime_edit)
        form.addRow("", self.alert_check)
        form.addRow("", self.alert_note)
        form.addRow("", self.done_check)
        root.addLayout(form)
        target = parse_deadline(str(note["d_day_at"] or "")) if note is not None else None
        self.datetime_edit.setDateTime(QDateTime(target or (datetime.now() + timedelta(days=1))))
        self.label_edit.setText(str(note["d_day_label"] or "") if note is not None else "")
        self.alert_check.setChecked(bool(note["d_day_alert"]) if note is not None else True)
        self.done_check.setChecked(is_deadline_done(note) if note is not None else False)
        self.done_check.setVisible(self._had_deadline)
        self.alert_note.setVisible(self.alert_check.isChecked())
        self.alert_check.toggled.connect(self.alert_note.setVisible)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if self._had_deadline:
            self.clear_button = QPushButton("D-Day 해제")
            self.clear_button.setObjectName("dangerButton")
            self.clear_button.clicked.connect(self._clear)
            buttons.addButton(self.clear_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        else:
            self.clear_button = None
        root.addWidget(buttons)
        self._clear_requested = False

    def _clear(self) -> None:
        self._clear_requested = True
        self.accept()

    @property
    def clear_requested(self) -> bool:
        return self._clear_requested

    def values(self) -> dict:
        return {
            "due_at": self.datetime_edit.dateTime().toPyDateTime().strftime(DATETIME_FMT),
            "label": self.label_edit.text().strip() or "D-Day",
            "alert": self.alert_check.isChecked(),
            "done": self.done_check.isChecked(),
        }
