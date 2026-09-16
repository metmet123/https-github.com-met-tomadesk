from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout,
)


TEMPLATE_ID_ROLE = Qt.ItemDataRole.UserRole


class TemplateManagerDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("블록 템플릿 관리")
        self.resize(440, 360)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.model().rowsMoved.connect(self._save_order)
        layout.addWidget(self.list, 1)
        actions = QHBoxLayout()
        for label, slot in (
            ("이름·호출어", self._edit), ("위로", lambda: self._move(-1)),
            ("아래로", lambda: self._move(1)), ("삭제", self._delete),
        ):
            button = QPushButton(label)
            button.setFixedHeight(28)
            button.clicked.connect(slot)
            actions.addWidget(button)
        layout.addLayout(actions)
        close = QPushButton("닫기")
        close.setFixedHeight(28)
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self.refresh()

    def refresh(self, selected_id=None):
        self.list.clear()
        for row in self.service.templates():
            item = QListWidgetItem(f"{row['name']}   /{row['trigger']}")
            item.setData(TEMPLATE_ID_ROLE, int(row["id"]))
            item.setData(Qt.ItemDataRole.UserRole + 1, dict(row))
            self.list.addItem(item)
            if selected_id == int(row["id"]):
                self.list.setCurrentItem(item)

    def _id(self):
        item = self.list.currentItem()
        return None if item is None else int(item.data(TEMPLATE_ID_ROLE))

    def _edit(self):
        item = self.list.currentItem()
        if item is None:
            return
        row = item.data(Qt.ItemDataRole.UserRole + 1)
        name, ok = QInputDialog.getText(self, "템플릿 이름", "이름", text=str(row["name"]))
        if not ok:
            return
        trigger, ok = QInputDialog.getText(self, "템플릿 호출어", "호출어 (/ 제외)", text=str(row["trigger"]))
        if not ok:
            return
        try:
            self.service.update_template(self._id(), name=name, trigger=trigger)
        except Exception as exc:
            QMessageBox.warning(self, "템플릿", str(exc))
            return
        self.refresh(self._id())

    def _move(self, offset):
        row, target = self.list.currentRow(), self.list.currentRow() + int(offset)
        if row < 0 or target < 0 or target >= self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)
        self._save_order()

    def _save_order(self, *_args):
        try:
            self.service.reorder_templates([
                int(self.list.item(index).data(TEMPLATE_ID_ROLE)) for index in range(self.list.count())
            ])
        except ValueError as exc:
            QMessageBox.warning(self, "템플릿 순서를 저장할 수 없음", str(exc))
            self.refresh()

    def _delete(self):
        template_id = self._id()
        if template_id is None:
            return
        if QMessageBox.question(self, "템플릿 삭제", "선택한 템플릿을 삭제할까요?") == QMessageBox.StandardButton.Yes:
            try:
                self.service.delete_template(template_id)
            except ValueError as exc:
                QMessageBox.warning(self, "템플릿을 삭제할 수 없음", str(exc))
                return
            self.refresh()
