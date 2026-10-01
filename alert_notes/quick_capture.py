from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QVBoxLayout,
)

from ui_polish import polish_button
from .datetime_input import DateTimeInput
from .memo_inline_alarm import chip_label, find_phrase, plain_text_with_chips
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
        self.title_edit.setPlaceholderText("제목 · 예: 보고서 보내기 @ 내일 오후 3시")
        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("메모 내용을 입력하세요 · 줄 끝에 @ 시간을 적으면 알림이 걸립니다")
        self.content_edit.setMaximumHeight(150)
        root.addWidget(self.title_edit)
        root.addWidget(self.content_edit)
        # `@ 내일 3시`로 읽은 알림.  저장하면 메모 본문의 알림 칩이 된다.
        self.alarm_preview = QLabel()
        self.alarm_preview.setObjectName("mutedLabel")
        self.alarm_preview.setWordWrap(True)
        self.alarm_preview.hide()
        root.addWidget(self.alarm_preview)
        self.title_edit.textChanged.connect(self._refresh_alarm_preview)
        self.content_edit.textChanged.connect(self._refresh_alarm_preview)
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
        self._refresh_alarm_preview()
        self.title_edit.setFocus()

    def alarm_phrases(self) -> list:
        lines = [self.title_edit.text(), *self.content_edit.toPlainText().splitlines()]
        found = []
        for line in lines:
            phrase = find_phrase(line)
            if phrase is not None and (phrase.spec is not None or phrase.issue):
                found.append(phrase)
        return found

    def _refresh_alarm_preview(self, *_args) -> None:
        phrases = self.alarm_phrases()
        if not phrases:
            self.alarm_preview.hide()
            return
        lines = [
            f"@ 알림: {phrase.issue}" if phrase.issue
            else f"{chip_label(phrase.spec)} 알림을 함께 저장합니다"
            for phrase in phrases
        ]
        self.alarm_preview.setText(chr(10).join(lines))
        self.alarm_preview.show()

    def _save(self) -> None:
        title = self.title_edit.text().strip()
        content = self.content_edit.toPlainText().strip()
        if not title and not content:
            self.title_edit.setFocus()
            return
        raw_title = self.title_edit.text()
        raw_content = self.content_edit.toPlainText()
        title, stored, _chips = plain_text_with_chips(raw_title, raw_content)
        title = title.strip()
        if not title:
            first = next((line for line in raw_content.splitlines() if line.strip()), "")
            phrase = find_phrase(first)
            if phrase is not None and phrase.valid:
                first = (first[:phrase.at_index] + " " + phrase.leftover + " " + first[phrase.end:]).strip()
            title = first[:60]
        note_id = self.store.create_note(title, stored)
        if self.schedule_check.isChecked() and self.datetime_input.datetime() > datetime.now():
            due = self.datetime_input.datetime().strftime(DATETIME_FMT)
            self.store.set_reminder(note_id, due, content or title)
        self.note_saved.emit(note_id)
        self.accept()
