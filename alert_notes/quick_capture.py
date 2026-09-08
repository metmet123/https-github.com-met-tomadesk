from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QVBoxLayout,
)

from ui_polish import polish_button
from .datetime_input import DateTimeInput
from .sqlite_store import DATETIME_FMT


class QuickMemoDialog(QDialog):
    note_saved = pyqtSignal(int)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("빠른 메모")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        heading = QLabel("빠른 메모")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("제목")
        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("메모 내용을 입력하세요")
        self.content_edit.setMaximumHeight(150)
        root.addWidget(self.title_edit)
        root.addWidget(self.content_edit)
        self.schedule_check = QCheckBox("날짜와 시간 지정")
        self.datetime_input = DateTimeInput()
        self.schedule_check.toggled.connect(self.datetime_input.setVisible)
        root.addWidget(self.schedule_check)
        root.addWidget(self.datetime_input)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("취소")
        save = QPushButton("저장")
        save.setObjectName("primaryButton")
        for button in (cancel, save):
            button.setMinimumHeight(40)
            polish_button(button)
            buttons.addWidget(button)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        root.addLayout(buttons)
        self.schedule_check.setChecked(False)
        self.datetime_input.setVisible(False)

    def prepare(self) -> None:
        self.title_edit.clear()
        self.content_edit.clear()
        self.schedule_check.setChecked(False)
        self.datetime_input.set_datetime(datetime.now() + timedelta(minutes=10))
        self.title_edit.setFocus()

    def _save(self) -> None:
        title = self.title_edit.text().strip()
        content = self.content_edit.toPlainText().strip()
        if not title and not content:
            self.title_edit.setFocus()
            return
        note_id = self.store.create_note(title or content.splitlines()[0][:60], content)
        if self.schedule_check.isChecked() and self.datetime_input.datetime() > datetime.now():
            due = self.datetime_input.datetime().strftime(DATETIME_FMT)
            self.store.set_reminder(note_id, due, content or title)
        self.note_saved.emit(note_id)
        self.accept()


class MemoSearchDialog(QDialog):
    note_requested = pyqtSignal(int)
    schedule_requested = pyqtSignal(int)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("메모·일정 검색")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumSize(560, 430)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        heading = QLabel("메모·일정 통합 검색")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("제목, 내용 또는 일정 검색")
        self.search_edit.setClearButtonEnabled(True)
        self.results = QListWidget()
        self.results.setAccessibleName("메모와 일정 검색 결과")
        root.addWidget(self.search_edit)
        root.addWidget(self.results, 1)
        hint = QLabel("↑↓ 이동 · Enter 열기 · Esc 닫기")
        hint.setObjectName("mutedLabel")
        root.addWidget(hint)
        self.search_edit.textChanged.connect(self.refresh)
        self.search_edit.returnPressed.connect(self._open_current)
        self.results.itemDoubleClicked.connect(self._open_item)

    def prepare(self) -> None:
        self.search_edit.clear()
        self.refresh("")
        self.search_edit.setFocus()

    def refresh(self, text: str) -> None:
        self.results.clear()
        for note in self.store.notes(text)[:50]:
            item = QListWidgetItem(f"메모  ·  {note['title']}\n{str(note['content'])[:90]}")
            item.setData(Qt.ItemDataRole.UserRole, ("note", int(note["id"])))
            self.results.addItem(item)
        if text.strip():
            for schedule in self.store.schedules.search(text, 50):
                item = QListWidgetItem(f"일정  ·  {schedule['title']}\n{schedule['start_at']}")
                item.setData(Qt.ItemDataRole.UserRole, ("schedule", int(schedule["id"])))
                self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def _open_current(self) -> None:
        if self.results.currentItem() is not None:
            self._open_item(self.results.currentItem())

    def _open_item(self, item: QListWidgetItem) -> None:
        kind, item_id = item.data(Qt.ItemDataRole.UserRole)
        if kind == "note":
            self.note_requested.emit(item_id)
        else:
            self.schedule_requested.emit(item_id)
        self.accept()
