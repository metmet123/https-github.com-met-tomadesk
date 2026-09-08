"""Dialog for selecting applications that suppress one saved hotkey action."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from foreground_app import normalize_app, normalize_app_list, visible_applications


class ExcludedAppsDialog(QDialog):
    def __init__(self, selected_apps: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("제외할 프로그램 선택")
        self.resize(720, 520)
        self.setMinimumSize(580, 400)
        self._selected = normalize_app_list(selected_apps)
        layout = QVBoxLayout(self)
        description = QLabel(
            "체크한 프로그램이 화면에 활성화되어 있을 때 이 작업의 단축키를 실행하지 않습니다."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        layout.addWidget(self.list_widget, 1)
        actions = QHBoxLayout()
        refresh = QPushButton("실행 중 목록 새로고침")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        add_exe = QPushButton("EXE 파일 추가")
        add_exe.clicked.connect(self.add_executable)
        actions.addWidget(add_exe)
        actions.addStretch()
        layout.addLayout(actions)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        checked = self.selected_apps() if self.list_widget.count() else self._selected
        merged = normalize_app_list([*visible_applications(), *checked])
        checked_keys = {_identity(app) for app in checked}
        self.list_widget.clear()
        for app in merged:
            item = QListWidgetItem(_display_text(app))
            item.setData(Qt.ItemDataRole.UserRole, app)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if _identity(app) in checked_keys else Qt.CheckState.Unchecked
            )
            item.setToolTip(app.get("path", ""))
            self.list_widget.addItem(item)

    def add_executable(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "제외할 프로그램 실행 파일", str(Path.home()), "실행 파일 (*.exe)"
        )
        if not path:
            return
        app = normalize_app({"name": Path(path).name, "path": path, "title": ""})
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if _identity(item.data(Qt.ItemDataRole.UserRole)) == _identity(app):
                item.setCheckState(Qt.CheckState.Checked)
                self.list_widget.scrollToItem(item)
                return
        item = QListWidgetItem(_display_text(app))
        item.setData(Qt.ItemDataRole.UserRole, app)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        item.setToolTip(app["path"])
        self.list_widget.addItem(item)
        self.list_widget.scrollToItem(item)

    def selected_apps(self) -> list[dict]:
        selected = []
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return normalize_app_list(selected)


def _identity(app: dict) -> tuple[str, str]:
    normalized = normalize_app(app)
    if normalized["path"]:
        return "path", normalized["path"].casefold()
    return "name", normalized["name"].casefold()


def _display_text(app: dict) -> str:
    title = app.get("title", "")
    heading = f"{title} — {app['name']}" if title else app["name"]
    return f"{heading}\n{app.get('path', '')}".rstrip()
