"""이미 있는 메모를 고르는 창.

본문에 메모 링크를 넣을 때 쓴다.  페이지 추가와 달리 새 메모를 만들지 않고,
이미 있는 메모를 가리키기만 한다.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QVBoxLayout,
)

from .rich_text import display_plain_text_from_content


class NoteLinkDialog(QDialog):
    ID_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, store, exclude_id=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.exclude_id = int(exclude_id) if exclude_id is not None else None
        self.setWindowTitle("메모 링크")
        self.setMinimumSize(420, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        hint = QLabel("링크할 메모를 고르세요.  누르면 그 메모가 열립니다.")
        hint.setObjectName("mutedLabel")
        layout.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("메모 제목과 내용 검색")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("링크 넣기")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.reload()

    def reload(self, *_args) -> None:
        self.list.clear()
        for row in self.store.notes(self.search.text()):
            note_id = int(row["id"])
            if note_id == self.exclude_id:
                # 자기 자신으로 가는 링크는 쓸모가 없다.
                continue
            title = str(row["title"] or "제목 없음")
            preview = display_plain_text_from_content(str(row["content"])).replace("\n", " ").strip()
            item = QListWidgetItem(title if not preview else f"{title}    {preview[:40]}")
            item.setData(self.ID_ROLE, note_id)
            item.setToolTip(title)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def chosen_id(self) -> int | None:
        item = self.list.currentItem()
        return None if item is None else int(item.data(self.ID_ROLE))

    def chosen_title(self) -> str:
        note_id = self.chosen_id()
        if note_id is None:
            return ""
        row = self.store.note(note_id)
        return str(row["title"]) if row is not None else ""
