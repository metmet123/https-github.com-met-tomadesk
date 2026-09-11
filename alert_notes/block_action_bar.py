from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton


class BlockActionBar(QFrame):
    """Small floating toolbar for the current custom block selection."""

    def __init__(self, editor, dispatcher):
        super().__init__(editor.viewport())
        self.editor = editor
        self.dispatcher = dispatcher
        self.setObjectName("blockActionBar")
        self.setAccessibleName("선택 블록 도구")
        self.setStyleSheet(
            "QFrame#blockActionBar{background:#172033;border:1px solid #334155;"
            "border-radius:7px;} QToolButton{color:white;border:0;padding:3px 6px;}"
            "QToolButton:hover{background:#334155;border-radius:4px;} QLabel{color:white;}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 4, 5, 4)
        layout.setSpacing(2)
        self.count_label = QLabel()
        layout.addWidget(self.count_label)
        for text, tip, command in (
            ("↑", "선택 블록 위로 (Alt+↑)", "move_up"),
            ("↓", "선택 블록 아래로 (Alt+↓)", "move_down"),
            ("−", "내어쓰기", "outdent"),
            ("+", "들여쓰기", "indent"),
            ("복사", "선택 블록 복사", "copy"),
            ("해제", "연동 기능 삭제", "unlink_features"),
            ("삭제", "선택 블록 삭제", "delete"),
        ):
            button = QToolButton(self)
            button.setText(text)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(lambda _checked=False, name=command: dispatcher.execute(name))
            layout.addWidget(button)
        self.hide()

    def sync(self) -> None:
        blocks = self.editor.block_selection.blocks()
        if not blocks:
            self.hide()
            return
        self.count_label.setText(f"{len(blocks)}개 선택")
        self.adjustSize()
        rect = self.editor.cursorRect(self.editor.block_cursor(blocks[0]))
        x = max(4, min(rect.left(), self.editor.viewport().width() - self.width() - 4))
        above = rect.top() - self.height() - 5
        y = above if above >= 4 else min(
            self.editor.viewport().height() - self.height() - 4,
            self.editor.cursorRect(self.editor.block_cursor(blocks[-1])).bottom() + 5,
        )
        self.move(x, max(4, y))
        self.show()
        self.raise_()

    def mousePressEvent(self, event) -> None:
        # Do not let clicks on the overlay move the QTextEdit caret.
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
        super().mousePressEvent(event)
