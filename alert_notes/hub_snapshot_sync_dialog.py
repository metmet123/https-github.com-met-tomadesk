"""Explicit local/Drive-synced folder choice for read-only Snapshot publishing."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from .hub_snapshot_sync import validate_snapshot_config


class HubSnapshotSyncDialog(QDialog):
    def __init__(self, config: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("조회 Snapshot 게시 설정")
        self.setMinimumWidth(540)
        self.config = None
        root = QVBoxLayout(self)
        explanation = QLabel(
            "'조회 공개 선택'에서 허용한 일정의 제목·시각·상태만 JSON으로 게시합니다. "
            "선택한 폴더가 Google Drive와 동기화된다면 휴대폰에서도 읽을 수 있습니다. "
            "처음에는 꺼져 있으며, 아래 체크를 켠 뒤 저장해야 자동 게시됩니다."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)
        form = QFormLayout()
        self.folder = QLineEdit((config or {}).get("folder", ""))
        self.folder.setAccessibleName("Snapshot 게시 폴더 경로")
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        browse = QPushButton("폴더 선택")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        form.addRow("게시할 폴더", row)
        self.enabled = QCheckBox("이 PC에서 조회 Snapshot 자동 게시 켜기")
        self.enabled.setChecked((config or {}).get("enabled", False))
        form.addRow("", self.enabled)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Snapshot 게시 폴더 선택", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _save(self):
        value = {"version": 1, "enabled": self.enabled.isChecked(),
                 "folder": self.folder.text().strip()}
        try:
            self.config = validate_snapshot_config(value, require_folder=value["enabled"])
        except ValueError as exc:
            QMessageBox.warning(self, "Snapshot 게시 설정", str(exc))
            return
        self.accept()
