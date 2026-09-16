from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog, QDialog, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout,
)


CATEGORY_ID_ROLE = Qt.ItemDataRole.UserRole


class CategoryManagerDialog(QDialog):
    changed = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("메모 카테고리 관리")
        self.resize(420, 360)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.model().rowsMoved.connect(self._save_order)
        layout.addWidget(self.list, 1)
        actions = QHBoxLayout()
        for label, slot in (
            ("추가", self._add), ("이름 변경", self._rename), ("색상", self._color),
            ("위로", lambda: self._move(-1)), ("아래로", lambda: self._move(1)),
            ("삭제", self._delete),
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

    def refresh(self, selected_id: int | None = None) -> None:
        self.list.clear()
        for row in self.store.categories():
            item = QListWidgetItem(str(row["name"]))
            item.setData(CATEGORY_ID_ROLE, int(row["id"]))
            item.setForeground(QColor(str(row["color"])))
            self.list.addItem(item)
            if selected_id == int(row["id"]):
                self.list.setCurrentItem(item)

    def _selected_id(self) -> int | None:
        item = self.list.currentItem()
        return None if item is None else int(item.data(CATEGORY_ID_ROLE))

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "카테고리 추가", "이름")
        if ok and name.strip():
            try:
                category_id = self.store.create_category(name)
            except Exception as exc:
                QMessageBox.warning(self, "카테고리", str(exc))
                return
            self.refresh(category_id)
            self.changed.emit()

    def _rename(self) -> None:
        category_id = self._selected_id()
        if category_id is None:
            return
        row = self.store.category(category_id)
        name, ok = QInputDialog.getText(self, "카테고리 이름 변경", "이름", text=str(row["name"]))
        if ok and name.strip():
            try:
                self.store.update_category(category_id, name=name)
            except Exception as exc:
                QMessageBox.warning(self, "카테고리", str(exc))
                return
            self.refresh(category_id)
            self.changed.emit()

    def _color(self) -> None:
        category_id = self._selected_id()
        if category_id is None:
            return
        row = self.store.category(category_id)
        color = QColorDialog.getColor(QColor(str(row["color"])), self, "카테고리 색상")
        if color.isValid():
            self.store.update_category(category_id, color=color.name())
            self.refresh(category_id)
            self.changed.emit()

    def _move(self, offset: int) -> None:
        row = self.list.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)
        self._save_order()

    def _save_order(self, *_args) -> None:
        self.store.reorder_categories([
            int(self.list.item(index).data(CATEGORY_ID_ROLE)) for index in range(self.list.count())
        ])
        self.changed.emit()

    def _delete(self) -> None:
        category_id = self._selected_id()
        if category_id is None:
            return
        row = self.store.category(category_id)
        answer = QMessageBox.question(
            self, "카테고리 삭제",
            f"'{row['name']}' 카테고리를 삭제할까요?\n메모는 삭제되지 않고 미지정으로 바뀝니다.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete_category(category_id)
            self.refresh()
            self.changed.emit()
