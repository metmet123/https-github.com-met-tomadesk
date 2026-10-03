"""Explicit local-folder and paired Telegram ID setup; no credentials here."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from .hub_folder_sync import validate_config


class HubFolderDialog(QDialog):
    def __init__(self, config: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Telegram 수신 폴더 설정")
        self.setMinimumWidth(540)
        self.config = None
        root = QVBoxLayout(self)
        explanation = QLabel(
            "이 PC에 이미 내려받은 Drive 수신 파일만 읽습니다. "
            "Google·Telegram 계정에는 로그인하지 않으며, 설정 전에는 자동 수집하지 않습니다."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)
        form = QFormLayout()
        self.folder = QLineEdit((config or {}).get("folder", ""))
        self.folder.setAccessibleName("Telegram 수신 폴더 경로")
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        browse = QPushButton("폴더 선택")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        form.addRow("로컬 수신 폴더", folder_row)
        self.bot_id = QLineEdit(str((config or {}).get("bot_id", "")))
        self.user_id = QLineEdit(str((config or {}).get("user_id", "")))
        self.chat_id = QLineEdit(str((config or {}).get("chat_id", "")))
        for field, label in ((self.bot_id, "봇 ID"), (self.user_id, "허용 사용자 ID"),
                             (self.chat_id, "허용 개인 채팅 ID")):
            field.setPlaceholderText("양의 숫자 ID")
            field.setAccessibleName(label)
            form.addRow(label, field)
        self.enabled = QCheckBox("이 PC에서 자동 수집 켜기")
        self.enabled.setChecked((config or {}).get("enabled", True))
        form.addRow("", self.enabled)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Telegram 수신 폴더 선택", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _save(self):
        try:
            ids = (self.bot_id.text().strip(), self.user_id.text().strip(), self.chat_id.text().strip())
            if not all(value.isascii() and value.isdecimal() for value in ids):
                raise ValueError("봇·사용자·개인 채팅의 숫자 ID를 모두 입력해 주세요.")
            value = {
                "version": 1,
                "enabled": self.enabled.isChecked(),
                "folder": self.folder.text().strip(),
                "bot_id": int(ids[0]),
                "user_id": int(ids[1]),
                "chat_id": int(ids[2]),
            }
            self.config = validate_config(value, require_folder=value["enabled"])
        except (ValueError, OverflowError) as exc:
            QMessageBox.warning(self, "수신 폴더 설정", str(exc))
            return
        self.accept()
