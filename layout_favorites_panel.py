"""Compact workspace favorites UI; Explorer remains the file manager."""

import copy
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QSizePolicy, QStyle, QVBoxLayout, QWidget,
)

from layout_workspace import workspace_payload
from ui_polish import polish_button
from ui_theme import scaled_stylesheet


class FavoritesDialog(QDialog):
    def __init__(self, favorites, parent=None):
        super().__init__(parent)
        self.setWindowTitle("즐겨찾기 폴더 관리")
        self.resize(440, 380)
        root = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setAccessibleName("즐겨찾기 폴더 목록")
        root.addWidget(self.list)
        for favorite in favorites:
            self._append(favorite)
        tools = QHBoxLayout()
        for label, callback in (("추가", self.add_folder), ("이름", self.rename), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1)), ("삭제", self.remove)):
            button = QPushButton(label)
            polish_button(button)
            button.clicked.connect(callback)
            tools.addWidget(button)
        root.addLayout(tools)
        hint = QLabel("삭제는 이 목록에서만 제거합니다. 실제 폴더는 유지됩니다.")
        hint.setWordWrap(True)
        hint.setObjectName("secondaryText")
        root.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _append(self, favorite):
        item = QListWidgetItem(favorite.get("name") or Path(favorite["path"]).name or favorite["path"])
        item.setData(Qt.ItemDataRole.UserRole, dict(favorite))
        item.setToolTip(favorite["path"])
        item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.list.addItem(item)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "즐겨찾기에 추가할 폴더")
        if path:
            self._append({"path": path, "name": Path(path).name or path})

    def rename(self):
        item = self.list.currentItem()
        if item is None:
            return
        name, accepted = QInputDialog.getText(self, "즐겨찾기 이름", "이름", text=item.text())
        if accepted and name.strip():
            favorite = dict(item.data(Qt.ItemDataRole.UserRole))
            favorite["name"] = name.strip()
            item.setData(Qt.ItemDataRole.UserRole, favorite)
            item.setText(name.strip())

    def move(self, offset):
        row = self.list.currentRow()
        if 0 <= row + offset < self.list.count():
            item = self.list.takeItem(row)
            self.list.insertItem(row + offset, item)
            self.list.setCurrentRow(row + offset)

    def remove(self):
        if self.list.currentRow() >= 0:
            self.list.takeItem(self.list.currentRow())

    def favorites(self):
        return [dict(self.list.item(row).data(Qt.ItemDataRole.UserRole)) for row in range(self.list.count())]


class WorkspaceSettings(QWidget):
    """Optional settings attached below the existing layout table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.options = {}
        self.entries = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        row = QHBoxLayout()
        self.enabled = QCheckBox("즐겨찾기 패널 사용")
        row.addWidget(self.enabled)
        row.addStretch()
        self.manage = QPushButton("폴더 관리…")
        polish_button(self.manage)
        self.manage.clicked.connect(self.edit_favorites)
        row.addWidget(self.manage)
        root.addLayout(row)
        self.details = QWidget()
        form = QFormLayout(self.details)
        form.setContentsMargins(0, 0, 0, 0)
        self.target = QComboBox()
        self.target.setMinimumWidth(0)
        self.target.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.setAccessibleName("기본 폴더 열기 대상")
        self.restore = QComboBox()
        self.restore.addItem("사용 중 폴더 유지", "keep")
        self.restore.addItem("저장된 초기 폴더로 복원", "initial")
        form.addRow("기본 대상", self.target)
        form.addRow("다시 불러올 때", self.restore)
        root.addWidget(self.details)
        self.enabled.toggled.connect(self._sync_enabled)
        self._sync_enabled(False)

    def _sync_enabled(self, enabled):
        self.details.setVisible(enabled)
        self.manage.setEnabled(enabled)

    def set_entries(self, entries):
        target = self.target.currentData() or self.options.get("target_slot")
        self.entries = copy.deepcopy(entries)
        normalized = workspace_payload({"windows": entries, "workspace": dict(self.options, target_slot=target)})
        self.target.blockSignals(True)
        self.target.clear()
        for index, entry in enumerate(normalized["windows"]):
            self.target.addItem(f"{index + 1} · {Path(entry['path']).name or entry['path']}", entry["slot_id"])
        self.target.setCurrentIndex(self.target.findData(normalized["workspace"]["target_slot"]))
        self.target.blockSignals(False)

    def load(self, options, entries):
        self.options = copy.deepcopy(options) if isinstance(options, dict) else {}
        self.target.clear()
        self.set_entries(entries)
        self.enabled.setChecked(bool(self.options.get("enabled")))
        self.restore.setCurrentIndex(max(0, self.restore.findData(self.options.get("restore_folders", "keep"))))

    def value(self):
        options = copy.deepcopy(self.options)
        options.update(enabled=self.enabled.isChecked(), target_slot=self.target.currentData() or "", restore_folders=self.restore.currentData(), favorites=options.get("favorites", []))
        return options

    def edit_favorites(self):
        dialog = FavoritesDialog(self.options.get("favorites", []), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.options["favorites"] = dialog.favorites()


class FavoritesPanel(QWidget):
    folder_requested = pyqtSignal(str, str)
    manage_requested = pyqtSignal()
    save_geometry_requested = pyqtSignal()

    def __init__(self):
        # Independent top-level window: showing an Explorer must not minimize it.
        super().__init__(None, Qt.WindowType.Window)
        self.setObjectName("layoutFavoritesPanel")
        self.setWindowTitle("즐겨찾기 · 토마데스크")
        self.resize(280, 650)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        toolbar = QHBoxLayout()
        self.target = QComboBox()
        self.target.setMinimumWidth(0)
        self.target.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.setAccessibleName("폴더를 열 대상 탐색기")
        toolbar.addWidget(self.target, 1)
        self.manage = QPushButton("…")
        self.manage.setObjectName("layoutFavoritesMenu")
        self.manage.setAccessibleName("즐겨찾기와 배치 관리")
        polish_button(self.manage, "즐겨찾기와 배치 관리")
        menu = QMenu(self)
        menu.addAction("즐겨찾기 폴더 관리…", self.manage_requested.emit)
        menu.addAction("현재 배치 위치·크기 저장", self.save_geometry_requested.emit)
        self.manage.setMenu(menu)
        toolbar.addWidget(self.manage)
        root.addLayout(toolbar)
        self.list = QListWidget()
        self.list.setObjectName("layoutFavoritesList")
        self.list.setAccessibleName("배치별 즐겨찾기 폴더")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemClicked.connect(self._request)
        self.list.itemActivated.connect(self._request)
        root.addWidget(self.list, 1)
        self.message = QLabel("폴더를 선택하면 대상 탐색기에서 엽니다.")
        self.message.setObjectName("secondaryText")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        self.footer.setObjectName("secondaryText")
        root.addWidget(self.footer)
        self.apply_scale(1.0)

    def apply_scale(self, scale):
        self.setStyleSheet(scaled_stylesheet(scale))
        self.setMinimumSize(round(240 * scale), round(230 * scale))
        self.manage.setFixedWidth(round(36 * scale))
        self.list.setSpacing(round(4 * scale))

    def configure(self, name, payload):
        old = self.target.currentData()
        self.target.clear()
        for index, entry in enumerate(payload["windows"]):
            self.target.addItem(f"{index + 1} · {Path(entry['path']).name or entry['path']}", entry["slot_id"])
        target = old if self.target.findData(old) >= 0 else payload["workspace"]["target_slot"]
        self.target.setCurrentIndex(self.target.findData(target))
        self.list.clear()
        for favorite in payload["workspace"]["favorites"]:
            item = QListWidgetItem(favorite["name"])
            item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
            item.setToolTip(favorite["path"])
            item.setData(Qt.ItemDataRole.UserRole, favorite["path"])
            self.list.addItem(item)
        self.footer.setText("배치: " + name)
        self.setWindowTitle(f"즐겨찾기 · {name}")
        if not self.list.count():
            self.message.setText("… → 즐겨찾기 폴더 관리에서 폴더를 추가하세요.")

    def _request(self, item):
        if self.list.isEnabled() and self.target.currentData():
            self.folder_requested.emit(self.target.currentData(), item.data(Qt.ItemDataRole.UserRole))

    def set_busy(self, busy):
        self.list.setEnabled(not busy)
        self.target.setEnabled(not busy)
        self.manage.setEnabled(not busy)
        if busy:
            self.message.setText("탐색기 폴더를 이동하고 있습니다…")

    def closeEvent(self, event):
        self.hide()
        event.ignore()
