"""본문 안에서 글자를 찾는 줄.

Ctrl+F 로 열린다.  치는 동안 찾은 자리가 모두 노랗게 칠해지고, 지금 자리만
주황이다.  Enter 로 다음, Shift+Enter 로 이전, Esc 로 닫는다.  접힌 토글 안에
있는 자리로 갈 때는 그 토글을 펴 준다.
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QWidget,
)


class MemoFindBar(QWidget):
    """편집기 하나에 붙어 다니는 찾기 줄."""

    BUTTON_WIDTH = 30
    TYPING_DELAY = 120

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.matches: list[tuple[int, int]] = []
        self.index = -1
        self.setObjectName("memoFindBar")
        self.setAccessibleName("본문 찾기")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(6)

        label = QLabel("찾기")
        label.setObjectName("secondaryText")
        row.addWidget(label)

        self.input = QLineEdit()
        self.input.setPlaceholderText("본문에서 찾을 말")
        self.input.setAccessibleName("찾을 말")
        self.input.setClearButtonEnabled(True)
        row.addWidget(self.input, 1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("memoFindCount")
        self.count_label.setAccessibleName("찾은 개수")
        self.count_label.setMinimumWidth(58)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.count_label)

        self.previous_button = self._arrow("▲", "이전 (Shift+Enter)")
        self.next_button = self._arrow("▼", "다음 (Enter)")
        self.close_button = self._arrow("✕", "닫기 (Esc)")
        row.addWidget(self.previous_button)
        row.addWidget(self.next_button)
        row.addWidget(self.close_button)

        self.previous_button.clicked.connect(lambda: self.step(-1))
        self.next_button.clicked.connect(lambda: self.step(1))
        self.close_button.clicked.connect(self.close_bar)

        # 한 글자마다 문서를 뒤지면 긴 메모에서 걸린다.  손을 멈추면 찾는다.
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(self.TYPING_DELAY)
        self._typing.timeout.connect(self.refresh)
        self.input.textChanged.connect(lambda _text: self._typing.start())
        self.input.returnPressed.connect(lambda: self.step(1))

        self.next_shortcut = QShortcut(QKeySequence("F3"), self)
        self.next_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.next_shortcut.activated.connect(lambda: self.step(1))
        self.previous_shortcut = QShortcut(QKeySequence("Shift+F3"), self)
        self.previous_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.previous_shortcut.activated.connect(lambda: self.step(-1))
        self.hide()

    def _arrow(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("findBarButton")
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setFixedWidth(self.BUTTON_WIDTH)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    # ----------------------------------------------------------------- 여닫기 --
    def open_bar(self) -> None:
        """Ctrl+F.  본문에 고른 글이 있으면 그것을 찾을 말로 채운다."""
        picked = self.editor.textCursor().selectedText()
        if picked and " " not in picked:
            self.input.setText(picked)
        self.show()
        self.input.setFocus()
        self.input.selectAll()
        self.refresh()

    def close_bar(self) -> None:
        self.hide()
        self.editor.clear_find_highlights()
        self.editor.setFocus()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_bar()
            return
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self.step(-1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ 찾기 --
    def refresh(self) -> None:
        """지금 친 말로 다시 찾는다.  커서에서 가장 가까운 자리를 고른다."""
        text = self.input.text()
        self.matches = self.editor.find_matches(text)
        if not self.matches:
            self.index = -1
            self.editor.set_find_highlights([], -1)
            self.count_label.setText("없음" if text else "")
            self.count_label.setProperty("empty", bool(text))
            self._restyle()
            return
        caret = self.editor.textCursor().selectionStart()
        self.index = 0
        for position, (start, _end) in enumerate(self.matches):
            if start >= caret:
                self.index = position
                break
        self._apply()

    def step(self, direction: int) -> None:
        """다음·이전 자리로 옮긴다.  끝에 닿으면 처음으로 돌아온다."""
        if not self.matches:
            self.refresh()
            if not self.matches:
                return
        else:
            self.index = (self.index + direction) % len(self.matches)
        self._apply()

    def _apply(self) -> None:
        start, end = self.matches[self.index]
        self.editor.set_find_highlights(self.matches, self.index)
        self.editor.go_to_match(start, end)
        self.count_label.setText(f"{self.index + 1} / {len(self.matches)}")
        self.count_label.setProperty("empty", False)
        self._restyle()

    def _restyle(self) -> None:
        self.count_label.style().unpolish(self.count_label)
        self.count_label.style().polish(self.count_label)
