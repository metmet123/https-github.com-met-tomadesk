from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QToolButton


class BlockActionBar(QFrame):
    """Selection commands in reserved editor space, never over document text."""

    HEIGHT = 38

    def __init__(self, editor, dispatcher):
        super().__init__(editor)
        self.editor = editor
        self.dispatcher = dispatcher
        self.setObjectName("blockActionBar")
        self.setAccessibleName("선택 블록 도구")
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(
            "QFrame#blockActionBar{background:#f8fafc;border-top:1px solid #cbd5e1;}"
            "QToolButton{color:#172033;border:1px solid transparent;border-radius:5px;"
            "padding:3px 7px;min-height:25px;}"
            "QToolButton:hover{background:#e2e8f0;border-color:#cbd5e1;}"
            "QLabel{color:#334155;font-weight:600;}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(4)
        self.count_label = QLabel()
        self.count_label.setAccessibleName("선택한 블록 수")
        layout.addWidget(self.count_label)
        layout.addStretch(1)
        for text, tip, command in (
            ("↑", "선택 블록 위로 (Alt+↑)", "move_up"),
            ("↓", "선택 블록 아래로 (Alt+↓)", "move_down"),
        ):
            button = QToolButton(self)
            button.setText(text)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(lambda _checked=False, name=command: dispatcher.execute(name))
            layout.addWidget(button)
        self.copy_button = QToolButton(self)
        self.copy_button.setText("복사")
        self.copy_button.setAccessibleName("선택 블록 복사")
        self.copy_button.clicked.connect(lambda: dispatcher.execute("copy"))
        layout.addWidget(self.copy_button)
        self.more_button = QToolButton(self)
        self.more_button.setText("작업 ▾")
        self.more_button.setAccessibleName("선택 블록 작업 더보기")
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.more_button)
        self.more_menu.aboutToShow.connect(self._refresh_menu)
        self.more_button.setMenu(self.more_menu)
        layout.addWidget(self.more_button)
        clear_button = QToolButton(self)
        clear_button.setText("×")
        clear_button.setAccessibleName("블록 선택 해제")
        clear_button.setToolTip("블록 선택 해제 (Esc)")
        clear_button.clicked.connect(editor.block_selection.clear)
        layout.addWidget(clear_button)
        self.hide()

    def _refresh_menu(self) -> None:
        self.more_menu.clear()
        self.editor._populate_block_context_menu(self.more_menu)

    def place(self) -> None:
        frame = self.editor.frameWidth()
        width = max(0, self.editor.width() - frame * 2)
        self.setGeometry(frame, self.editor.height() - frame - self.HEIGHT, width, self.HEIGHT)
        count = self.editor.block_selection.count()
        self.count_label.setText(f"{count}개" if width < 330 else f"{count}개 블록 선택")
        self.count_label.setToolTip(f"{count}개 블록 선택")
        self.more_button.setText("작업" if width < 330 else "작업 ▾")
        self.copy_button.setVisible(width >= 390)

    def sync(self) -> None:
        count = self.editor.block_selection.count()
        if count == 0:
            self.hide()
            self.editor._sync_selection_bar_height()
            return
        # Qt frame/viewport metrics vary slightly by style and scale.  Keep a
        # small clearance so no selectable text sits under the command row.
        self.editor._sync_selection_bar_height()
        self.place()
        self.show()
        self.raise_()
