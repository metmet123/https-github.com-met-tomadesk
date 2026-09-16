from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)


VERSION_ID_ROLE = Qt.ItemDataRole.UserRole
IMPORTANT_ROLE = Qt.ItemDataRole.UserRole + 1

VERSION_KIND_LABELS = {
    "session_start": "편집 시작 전",
    "auto": "편집 후",
    "manual": "직접 저장",
    "before_restore": "복원 직전",
}


def local_version_datetime(value: str) -> datetime:
    """Read stored UTC ISO milliseconds and return the current local time."""
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def version_day_label(value: datetime, now: datetime | None = None) -> str:
    current = (now or datetime.now().astimezone()).date()
    if value.date() == current:
        return "오늘"
    if value.date() == current - timedelta(days=1):
        return "어제"
    return value.strftime("%Y-%m-%d")


def version_kind_label(kind: str) -> str:
    return VERSION_KIND_LABELS.get(str(kind), str(kind) or "기타")


class VersionHistoryDialog(QDialog):
    restored = pyqtSignal()

    def __init__(self, service, note_id: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.note_id = int(note_id)
        self.setWindowTitle("메모 버전 기록")
        self.resize(760, 500)
        layout = QVBoxLayout(self)
        split = QSplitter()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._preview)
        split.addWidget(self.list)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        split.addWidget(self.preview)
        split.setSizes([250, 500])
        layout.addWidget(split, 1)
        actions = QHBoxLayout()
        self.important = QCheckBox("중요 버전")
        self.important.toggled.connect(self._set_important)
        actions.addWidget(self.important)
        actions.addStretch(1)
        create = QPushButton("현재 상태 저장")
        create.setFixedHeight(28)
        create.clicked.connect(self._create)
        actions.addWidget(create)
        restore = QPushButton("선택 버전 복원")
        restore.setFixedHeight(28)
        restore.clicked.connect(self._restore)
        actions.addWidget(restore)
        close = QPushButton("닫기")
        close.setFixedHeight(28)
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        self.list.clear()
        previous_day = None
        for row in self.service.versions(self.note_id):
            created = local_version_datetime(str(row["created_at_utc"]))
            day = version_day_label(created)
            if day != previous_day:
                header = QListWidgetItem(day)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setForeground(QColor("#64748b"))
                self.list.addItem(header)
                previous_day = day
            mark = "★ " if row["important"] else ""
            label = f"{mark}{created:%H:%M} · {version_kind_label(str(row['kind']))}"
            item = QListWidgetItem(label)
            item.setData(VERSION_ID_ROLE, int(row["id"]))
            item.setData(IMPORTANT_ROLE, bool(row["important"]))
            item.setToolTip(f"{created:%Y-%m-%d %H:%M:%S} · {version_kind_label(str(row['kind']))}")
            self.list.addItem(item)
        for index in range(self.list.count()):
            if self.list.item(index).data(VERSION_ID_ROLE) is not None:
                self.list.setCurrentRow(index)
                break

    def _selected(self):
        item = self.list.currentItem()
        value = None if item is None else item.data(VERSION_ID_ROLE)
        return None if value is None else int(value)

    def _preview(self, item, _previous=None):
        if item is None:
            self.preview.clear()
            return
        blocked = self.important.blockSignals(True)
        version_value = item.data(VERSION_ID_ROLE)
        if version_value is None:
            self.preview.clear()
            self.important.setChecked(False)
            self.important.setEnabled(False)
            self.important.blockSignals(blocked)
            return
        self.important.setEnabled(True)
        self.important.setChecked(bool(item.data(IMPORTANT_ROLE)))
        self.important.blockSignals(blocked)
        version_id = int(version_value)
        try:
            payload = self.service.version_payload(version_id)
            note = payload.get("note") or {}
            diff = self.service.version_diff(version_id)
        except ValueError as exc:
            self.preview.setPlainText(str(exc))
            QMessageBox.warning(self, "버전을 읽을 수 없음", str(exc))
            return
        self.preview.setPlainText(
            f"제목: {note.get('title', '')}\n\n{diff or '현재 상태와 본문 차이가 없습니다.'}"
        )
        self._color_diff_lines()

    def _color_diff_lines(self) -> None:
        block = self.preview.document().begin()
        while block.isValid():
            text = block.text()
            foreground = None
            background = None
            if text.startswith("+++") or text.startswith("---") or text.startswith("@@"):
                foreground, background = QColor("#1d4ed8"), QColor("#eff6ff")
            elif text.startswith("+"):
                foreground, background = QColor("#047857"), QColor("#ecfdf5")
            elif text.startswith("-"):
                foreground, background = QColor("#be123c"), QColor("#fff1f2")
            if foreground is not None:
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setForeground(foreground)
                fmt.setBackground(background)
                cursor.mergeCharFormat(fmt)
            block = block.next()

    def _create(self):
        try:
            self.service.create_version(self.note_id, kind="manual", important=True, force=True)
        except ValueError as exc:
            QMessageBox.warning(self, "버전을 저장할 수 없음", str(exc))
            return
        self.refresh()

    def _set_important(self, checked):
        version_id = self._selected()
        if version_id is not None:
            try:
                self.service.set_version_important(version_id, bool(checked))
            except ValueError as exc:
                QMessageBox.warning(self, "중요 표시를 저장할 수 없음", str(exc))
                return
            self.refresh()

    def _restore(self):
        version_id = self._selected()
        if version_id is None:
            return
        try:
            impacts = self.service.restore_impacts(version_id)
        except ValueError as exc:
            QMessageBox.warning(self, "버전을 복원할 수 없음", str(exc))
            return
        text = "선택한 버전을 복원할까요? 복원 직전 상태도 중요 버전으로 저장됩니다."
        if impacts:
            text += "\n\n" + "\n".join(impacts)
        if QMessageBox.question(self, "버전 복원", text) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.restore_version(version_id)
        except ValueError as exc:
            QMessageBox.warning(self, "버전을 복원할 수 없음", str(exc))
            return
        self.restored.emit()
        self.refresh()
