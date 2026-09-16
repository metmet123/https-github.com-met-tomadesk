"""Non-overlay memo outline with native keyboard tree navigation."""

from __future__ import annotations

from html import escape

from PyQt6.QtCore import QMimeData, QTimer, Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .block_link import block_url
from .outline_model import outline_entries, resolve_block


class OutlinePanel(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setObjectName("memoOutlinePanel")
        self.setAccessibleName("메모 목차")
        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.title = QLabel("목차")
        header.addWidget(self.title, 1)
        self.copy_button = QPushButton("링크 복사")
        self.copy_button.setAccessibleName("선택한 블록 링크 복사")
        self.copy_button.clicked.connect(self.copy_selected_link)
        header.addWidget(self.copy_button)
        layout.addLayout(header)
        self.tree = QTreeWidget(self)
        self.tree.setObjectName("memoOutlineTree")
        self.tree.setAccessibleName("제목·페이지·토글 목차")
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.itemClicked.connect(self._open_item)
        self.tree.itemActivated.connect(self._open_item)
        self.tree.currentItemChanged.connect(self._sync_copy_button)
        layout.addWidget(self.tree, 1)
        self._items: dict[str, QTreeWidgetItem] = {}
        self._entries = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)

    def queue_refresh(self) -> None:
        if self.isVisible():
            self._timer.start()

    def refresh(self) -> None:
        self._timer.stop()
        entries = outline_entries(self.editor)
        self._entries = entries
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self._items.clear()
            heading_stack: list[tuple[int, QTreeWidgetItem]] = []
            for entry in entries:
                if entry.kind == "heading":
                    while heading_stack and heading_stack[-1][0] >= entry.level:
                        heading_stack.pop()
                    parent = heading_stack[-1][1] if heading_stack else None
                else:
                    parent = heading_stack[-1][1] if heading_stack else None
                prefix = {
                    "heading": f"제목 {entry.level}", "page": "페이지",
                    "toggle": "토글", "pinned": "고정",
                }[entry.kind]
                if entry.pinned and entry.kind != "pinned":
                    prefix = f"고정 · {prefix}"
                item = QTreeWidgetItem([f"{prefix} · {entry.label}"])
                item.setData(0, Qt.ItemDataRole.UserRole, entry.block_id)
                item.setToolTip(0, entry.label)
                if parent is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                self._items[entry.block_id] = item
                if entry.kind == "heading":
                    heading_stack.append((entry.level, item))
            self.tree.expandAll()
            self.title.setText(f"목차 · {len(entries)}")
        finally:
            self.tree.blockSignals(False)
        self.sync_current()
        self._sync_copy_button()

    def _sync_copy_button(self, *_args) -> None:
        self.copy_button.setEnabled(
            self.editor.note_id is not None and self.tree.currentItem() is not None
        )

    def copy_selected_link(self) -> bool:
        item = self.tree.currentItem()
        if item is None or self.editor.note_id is None:
            return False
        identity = item.data(0, Qt.ItemDataRole.UserRole)
        if resolve_block(self.editor, identity) is None:
            self.queue_refresh()
            return False
        ensure_target = getattr(self, "ensure_link_target", None)
        if ensure_target is not None and not ensure_target(identity):
            return False
        note = self.editor.store.note(self.editor.note_id) if self.editor.store is not None else None
        memo_ref = str(note["sync_id"]) if note is not None and str(note["sync_id"] or "") else self.editor.note_id
        url = block_url(memo_ref, identity)
        mime = QMimeData()
        mime.setText(url)
        mime.setHtml(f'<a href="{url}">🔗 {escape(item.text(0))}</a>')
        QApplication.clipboard().setMimeData(mime)
        return True

    def sync_current(self) -> None:
        if not self.isVisible() or not self._items:
            return
        position = self.editor.textCursor().position()
        active = None
        for entry in self._entries:
            if entry.position > position:
                break
            active = self._items.get(entry.block_id)
        if active is not None and self.tree.currentItem() is not active:
            self.tree.setCurrentItem(active)

    def _open_item(self, item: QTreeWidgetItem, _column: int) -> None:
        block = resolve_block(self.editor, item.data(0, Qt.ItemDataRole.UserRole))
        if block is None or not block.isValid():
            self.queue_refresh()
            return
        self.editor.setTextCursor(QTextCursor(block))
        self.editor.ensureCursorVisible()
        self.editor.setFocus()
