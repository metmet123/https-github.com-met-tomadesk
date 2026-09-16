from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QTextCursor


class CharacterRangeSelection(QObject):
    """Transient, document-tracking noncontiguous character selections."""

    changed = pyqtSignal()

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self._cursors: list[QTextCursor] = []

    def ranges(self) -> list[tuple[int, int]]:
        return [(cursor.selectionStart(), cursor.selectionEnd())
                for cursor in self._cursors if cursor.hasSelection()]

    def count(self) -> int:
        return len(self.ranges())

    def contains(self, position: int) -> bool:
        return any(start <= position <= end for start, end in self.ranges())

    def clear(self) -> None:
        if self._cursors:
            self._cursors.clear()
            self.changed.emit()

    def add_cursor(self, cursor: QTextCursor) -> bool:
        if not cursor.hasSelection() or cursor.document() != self.editor.document():
            return False
        intervals = sorted([*self.ranges(), (cursor.selectionStart(), cursor.selectionEnd())])
        merged: list[list[int]] = []
        for start, end in intervals:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(end, merged[-1][1])
            else:
                merged.append([start, end])
        self._cursors = []
        for start, end in merged:
            selected = QTextCursor(self.editor.document())
            selected.setPosition(start)
            selected.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            self._cursors.append(selected)
        self.changed.emit()
        return True
