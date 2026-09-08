from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ui_polish import polish_button
from .datetime_input import DateTimeInput
from .sqlite_store import DATETIME_FMT
from .rich_text import plain_text_from_content


class CalendarQuickEditor(QWidget):
    note_saved = pyqtSignal(int)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.selected_slot: datetime | None = None
        self.selected_note_id: int | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(QLabel("빠른 알림 설정"))
        self.slot_label = QLabel("캘린더에서 시간을 선택하세요.")
        self.slot_label.setObjectName("reminderSummary")
        layout.addWidget(self.slot_label)
        layout.addWidget(QLabel("메모 제목"))
        self.title_edit = QLineEdit()
        self.title_edit.setAccessibleName("빠른 알림 메모 제목")
        self.title_edit.setMinimumHeight(40)
        layout.addWidget(self.title_edit)
        layout.addWidget(QLabel("메모 내용"))
        self.content_edit = QLineEdit()
        self.content_edit.setAccessibleName("빠른 알림 메모 내용")
        self.content_edit.setMinimumHeight(40)
        layout.addWidget(self.content_edit)
        self.datetime_input = DateTimeInput()
        layout.addWidget(self.datetime_input)
        self.save_button = QPushButton("알림 설정")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setMinimumHeight(44)
        polish_button(self.save_button)
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        layout.addStretch()
        self.datetime_input.changed.connect(self._update_state)
        self.datetime_input.commit_requested.connect(self.save)
        self._save_shortcuts = [QShortcut(QKeySequence(key), self) for key in ("Ctrl+Return", "Ctrl+Enter")]
        for shortcut in self._save_shortcuts:
            shortcut.activated.connect(self.save)
        self._update_state()

    def select_slot(self, value: datetime) -> None:
        self.selected_slot = value
        self.selected_note_id = None
        self.save_button.setText("알림 설정")
        self.datetime_input.set_datetime(value)
        self.slot_label.setText(value.strftime("%Y년 %m월 %d일 %H:%M"))

    def load_note(self, note_id: int) -> None:
        note = self.store.note(note_id)
        if note is None:
            return
        due = datetime.strptime(str(note["reminder_due_at"]), DATETIME_FMT)
        self.selected_note_id = int(note_id)
        self.selected_slot = due
        self.title_edit.setText(str(note["title"]))
        self.content_edit.setText(plain_text_from_content(str(note["content"])))
        self.datetime_input.set_datetime(due)
        self.slot_label.setText(due.strftime("%Y년 %m월 %d일 %H:%M"))
        self.save_button.setText("알림 변경")

    def _update_state(self, *_args) -> None:
        valid = self.selected_slot is not None and self.datetime_input.is_valid()
        self.save_button.setEnabled(valid and self.datetime_input.datetime() > datetime.now())

    def save(self) -> None:
        if not self.save_button.isEnabled():
            return
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.information(self, "알림 설정", "메모 제목을 입력해 주세요.")
            self.title_edit.setFocus()
            return
        due_at = self.datetime_input.datetime().strftime(DATETIME_FMT)
        content = self.content_edit.text()
        if self.selected_note_id is None:
            note_id = self.store.create_note_with_reminder(title, content, due_at)
        else:
            note_id = self.selected_note_id
            self.store.update_note(note_id, title=title, content=content)
            self.store.set_reminder(note_id, due_at, content.strip() or title)
        self.note_saved.emit(note_id)
        self.title_edit.clear()
        self.content_edit.clear()
        self.selected_note_id = None
        self.save_button.setText("알림 설정")
