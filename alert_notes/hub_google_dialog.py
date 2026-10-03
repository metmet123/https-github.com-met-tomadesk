"""Drive receiver settings; OAuth grant happens through a separate button."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from .hub_google_sync import validate_drive_config


class HubGoogleDialog(QDialog):
    def __init__(self, config: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Google Drive 수신 설정")
        self.setMinimumWidth(580)
        self.config = None
        root = QVBoxLayout(self)
        explanation = QLabel(
            "선택한 Drive 폴더의 Telegram 수신 파일만 내려받습니다. "
            "Google 승인에는 Drive 전체 읽기 권한이 필요하지만, TomaDesk는 지정 폴더만 조회합니다. "
            "처음 연결은 아래 설정을 저장한 뒤 별도 'Google 연결' 버튼으로 시작합니다."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)
        form = QFormLayout()
        self.folder_id = QLineEdit((config or {}).get("folder_id", ""))
        self.folder_id.setAccessibleName("Google Drive 수신 폴더 ID")
        form.addRow("Drive 폴더 ID", self.folder_id)
        self.client_file = QLineEdit((config or {}).get("oauth_client_file", ""))
        self.client_file.setAccessibleName("Google OAuth 데스크톱 클라이언트 JSON")
        client_row = QHBoxLayout()
        client_row.addWidget(self.client_file, 1)
        browse = QPushButton("JSON 선택")
        browse.clicked.connect(self._browse)
        client_row.addWidget(browse)
        form.addRow("OAuth 클라이언트 JSON", client_row)
        self.enabled = QCheckBox("이 PC에서 Drive 자동 다운로드 켜기")
        self.enabled.setChecked((config or {}).get("enabled", False))
        form.addRow("", self.enabled)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Google OAuth 데스크톱 클라이언트 JSON 선택", self.client_file.text(), "JSON (*.json)"
        )
        if path:
            self.client_file.setText(path)

    def _save(self):
        value = {
            "version": 1, "enabled": self.enabled.isChecked(),
            "folder_id": self.folder_id.text().strip(),
            "oauth_client_file": self.client_file.text().strip(),
        }
        try:
            self.config = validate_drive_config(value, require_client=value["enabled"])
        except ValueError as exc:
            QMessageBox.warning(self, "Drive 수신 설정", str(exc))
            return
        self.accept()
