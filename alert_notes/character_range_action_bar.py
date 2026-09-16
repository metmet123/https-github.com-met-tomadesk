from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton


class CharacterRangeActionBar(QFrame):
    """Compact actions in reserved space below the editor viewport."""

    HEIGHT = 38

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setObjectName("characterRangeActionBar")
        self.setAccessibleName("글자 구간 선택 도구")
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(
            "QFrame#characterRangeActionBar{background:#f8fafc;border-top:1px solid #cbd5e1;}"
            "QToolButton{color:#172033;border:1px solid transparent;border-radius:5px;"
            "padding:3px 7px;min-height:25px;}"
            "QToolButton:hover{background:#e2e8f0;border-color:#cbd5e1;}"
            "QLabel{color:#334155;font-weight:600;}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(4)
        self.count_label = QLabel(self)
        self.count_label.setAccessibleName("선택한 글자 구간 수")
        self.count_label.setToolTip(
            "Ctrl+드래그로 구간 추가 · 키보드로 글자 선택 후 Ctrl+Shift+M · Esc 해제"
        )
        row.addWidget(self.count_label)
        row.addStretch(1)
        for text, label, callback in (
            ("연동 해제", "선택 글자의 링크 기능 해제", editor.unlink_selected_character_ranges),
            ("×", "글자 구간 선택 해제 (Esc)", editor.character_selection.clear),
        ):
            button = QToolButton(self)
            button.setText(text)
            button.setAccessibleName(label)
            button.setToolTip(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.hide()

    def sync(self) -> None:
        count = self.editor.character_selection.count()
        if not count:
            self.hide()
            self.editor._sync_selection_bar_height()
            return
        self.editor._sync_selection_bar_height()
        frame = self.editor.frameWidth()
        width = max(0, self.editor.width() - frame * 2)
        self.setGeometry(frame, self.editor.height() - frame - self.HEIGHT, width, self.HEIGHT)
        self.count_label.setText(f"{count}개" if width < 290 else f"{count}개 글자 구간 선택")
        self.show()
        self.raise_()
