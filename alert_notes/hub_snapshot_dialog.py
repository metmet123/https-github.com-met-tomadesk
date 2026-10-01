"""Local chooser for the schedules included in a future Hub read-only view."""
from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHeaderView, QLabel, QMessageBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .hub_snapshot import HubSnapshotStore


class HubSnapshotVisibilityDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.repo = HubSnapshotStore(store)
        self.choices = self.repo.list_schedule_choices()
        self.setWindowTitle("조회 공개 일정 선택")
        self.resize(780, 480)
        layout = QVBoxLayout(self)
        notice = QLabel(
            "체크한 일정의 제목·시각·상태만 향후 읽기 전용 조회에 포함됩니다. "
            "메모·상세 설명·첨부는 포함되지 않습니다. 현재는 외부로 전송하지 않습니다."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.table = QTableWidget(len(self.choices), 5)
        self.table.setHorizontalHeaderLabels(["공개", "제목", "종류", "시작", "상태"])
        self.table.setAccessibleName("Hub 조회 공개 일정 목록")
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 60), (2, 85), (3, 140), (4, 85)):
            self.table.setColumnWidth(column, width)
        for index, choice in enumerate(self.choices):
            flag = QTableWidgetItem()
            flag.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            flag.setCheckState(Qt.CheckState.Checked if choice["visible"] else Qt.CheckState.Unchecked)
            self.table.setItem(index, 0, flag)
            values = (
                choice["title"],
                "할 일" if choice["kind"] == "task" else "일정",
                _display_start(choice["start_at"], all_day=choice["all_day"]),
                "완료" if choice["status"] == "completed" else "미완료",
            )
            for column, value in enumerate(values, 1):
                cell = QTableWidgetItem(value)
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(index, column, cell)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.save_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save_selection(self):
        changes = {
            choice["id"]: self.table.item(index, 0).checkState() == Qt.CheckState.Checked
            for index, choice in enumerate(self.choices)
            if (self.table.item(index, 0).checkState() == Qt.CheckState.Checked) != choice["visible"]
        }
        try:
            self.repo.set_visible_many(changes)
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "조회 공개 설정", str(exc))
            return
        self.accept()


def _display_start(value: str, *, all_day: bool = False) -> str:
    text = str(value)
    if len(text) != 12 or not text.isdigit():
        return text
    day = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return f"{day} · 종일" if all_day else f"{day} {text[8:10]}:{text[10:]}"
