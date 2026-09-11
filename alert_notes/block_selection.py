from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QTextCursor


class BlockSelectionManager(QObject):
    """Keep an ordered, non-contiguous set of QTextDocument blocks."""

    changed = pyqtSignal()

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self._anchors: list[QTextCursor] = []
        self._drag_origin: int | None = None
        self._drag_base: list[int] = []

    def clear(self) -> None:
        if not self._anchors:
            return
        self._anchors = []
        self._drag_origin = None
        self._drag_base = []
        self.changed.emit()

    def positions(self) -> list[int]:
        document = self.editor.document()
        found = []
        for anchor in self._anchors:
            block = document.findBlock(anchor.position())
            if block.isValid():
                found.append(block.position())
        return sorted(set(found))

    def blocks(self) -> list:
        document = self.editor.document()
        return [document.findBlock(position) for position in self.positions()]

    def count(self) -> int:
        return len(self.positions())

    def contains(self, block) -> bool:
        return block is not None and block.isValid() and block.position() in set(self.positions())

    def set_positions(self, positions) -> None:
        document = self.editor.document()
        anchors = []
        for position in sorted(set(int(value) for value in positions)):
            block = document.findBlock(position)
            if not block.isValid():
                continue
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            anchors.append(cursor)
        before = self.positions()
        self._anchors = anchors
        if before != self.positions():
            self.changed.emit()

    def _family_positions(self, block) -> list[int]:
        family = self.editor._block_family(block)
        return [value.position() for value in family if value.isValid()]

    def toggle(self, block, include_family: bool = True) -> None:
        if block is None or not block.isValid():
            return
        wanted = self._family_positions(block) if include_family else [block.position()]
        current = set(self.positions())
        if all(position in current for position in wanted):
            current.difference_update(wanted)
        else:
            current.update(wanted)
        self.set_positions(current)

    def select_only(self, block, include_family: bool = True) -> None:
        if block is None or not block.isValid():
            self.clear()
            return
        wanted = self._family_positions(block) if include_family else [block.position()]
        self.set_positions(wanted)

    def begin_drag(self, block, additive: bool = True) -> None:
        if block is None or not block.isValid():
            return
        self._drag_origin = block.position()
        self._drag_base = self.positions() if additive else []
        self.toggle(block)

    def update_drag(self, block) -> None:
        if self._drag_origin is None or block is None or not block.isValid():
            return
        document = self.editor.document()
        start, end = sorted((self._drag_origin, block.position()))
        positions = set(self._drag_base)
        current = document.findBlock(start)
        while current.isValid() and current.position() <= end:
            positions.update(self._family_positions(current))
            current = current.next()
        self.set_positions(positions)

    def finish_drag(self) -> None:
        self._drag_origin = None
        self._drag_base = []

    def contiguous_groups(self) -> list[list]:
        blocks = self.blocks()
        if not blocks:
            return []
        groups, group = [], [blocks[0]]
        for block in blocks[1:]:
            if group[-1].next().isValid() and group[-1].next().position() == block.position():
                group.append(block)
            else:
                groups.append(group)
                group = [block]
        groups.append(group)
        return groups

    def root_blocks(self) -> list:
        """Selected blocks excluding descendants already carried by a toggle."""
        selected = set(self.positions())
        roots = []
        for block in self.blocks():
            parent = self.editor._parent_toggle(block)
            if parent is not None and parent.position() in selected:
                continue
            roots.append(block)
        return roots
