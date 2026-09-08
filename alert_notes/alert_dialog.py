from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .sqlite_store import DATETIME_FMT
from .rich_text import plain_text_from_content


class ReminderAlertDialog(QDialog):
    completed = pyqtSignal(int)
    snoozed = pyqtSignal(int, int)
    skipped = pyqtSignal(int)
    note_open_requested = pyqtSignal(int)

    def __init__(self, reminder, parent=None):
        super().__init__(parent)
        self.reminder_id = int(reminder["id"])
        self.note_id = int(reminder["note_id"])
        self.setWindowTitle("알림 메모")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        title = QLabel(str(reminder["note_title"]))
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        content = QLabel(plain_text_from_content(str(reminder["note_content"] or reminder["memo"])))
        content.setWordWrap(True)
        content.setMinimumHeight(80)
        layout.addWidget(content)
        buttons = QHBoxLayout()
        done = QPushButton("확인")
        done.setObjectName("primaryButton")
        done.clicked.connect(lambda: self._complete())
        snooze = QPushButton("10분 뒤 다시 알림")
        snooze.clicked.connect(lambda: self._snooze())
        open_note = QPushButton("메모 열기")
        open_note.clicked.connect(lambda: self.note_open_requested.emit(self.note_id))
        skip = QPushButton("건너뛰기")
        skip.clicked.connect(self._skip)
        buttons.addWidget(done)
        buttons.addWidget(snooze)
        buttons.addWidget(skip)
        buttons.addWidget(open_note)
        layout.addLayout(buttons)

    def _complete(self) -> None:
        self.completed.emit(self.reminder_id)
        self.accept()

    def _snooze(self) -> None:
        self.snoozed.emit(self.reminder_id, 10)
        self.accept()

    def _skip(self) -> None:
        self.skipped.emit(self.reminder_id)
        self.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)


class ScheduleAlertDialog(QDialog):
    completed = pyqtSignal(int, str)
    snoozed = pyqtSignal(int, str, int)
    note_open_requested = pyqtSignal(int)
    schedule_open_requested = pyqtSignal(int)

    def __init__(self, reminder, parent=None):
        super().__init__(parent)
        self.notification_id = int(reminder["notification_id"])
        self.occurrence_at = str(reminder["occurrence_at"])
        self.item_id = int(reminder["item_id"])
        self.note_id = reminder.get("note_id")
        self.setWindowTitle("일정 알림")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        title = QLabel(str(reminder["title"]))
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        when = datetime.strptime(str(reminder["start_at"]), DATETIME_FMT).strftime("%Y-%m-%d %H:%M")
        schedule = QLabel(f"{when} · {'할 일' if reminder['item_type'] == 'task' else '일정'}")
        schedule.setObjectName("mutedLabel")
        layout.addWidget(schedule)
        content = QLabel(str(reminder["details"] or "등록한 일정 시간이 되었습니다."))
        content.setWordWrap(True)
        content.setMinimumHeight(70)
        layout.addWidget(content)
        buttons = QHBoxLayout()
        done = QPushButton("확인")
        done.setObjectName("primaryButton")
        done.clicked.connect(self._complete)
        buttons.addWidget(done)
        for minutes, label in ((10, "10분"), (30, "30분"), (60, "1시간")):
            button = QPushButton(f"{label} 미루기")
            button.clicked.connect(lambda _checked=False, value=minutes: self._snooze(value))
            buttons.addWidget(button)
        open_button = QPushButton("열기")
        open_button.clicked.connect(self._open)
        buttons.addWidget(open_button)
        layout.addLayout(buttons)

    def _complete(self) -> None:
        self.completed.emit(self.notification_id, self.occurrence_at)
        self.accept()

    def _snooze(self, minutes: int) -> None:
        self.snoozed.emit(self.notification_id, self.occurrence_at, minutes)
        self.accept()

    def _open(self) -> None:
        if self.note_id:
            self.note_open_requested.emit(int(self.note_id))
        else:
            self.schedule_open_requested.emit(self.item_id)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)
