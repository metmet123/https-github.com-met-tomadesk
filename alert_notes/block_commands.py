from __future__ import annotations

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication


class BlockCommandDispatcher:
    """One execution path for keyboard, toolbar, gutter and context-menu actions."""

    def __init__(self, editor):
        self.editor = editor

    def blocks(self) -> list:
        selected = self.editor.block_selection.blocks()
        return selected or list(self.editor._selected_blocks())

    def groups(self) -> list[list]:
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

    def execute(self, command: str, **kwargs) -> bool:
        handler = getattr(self, f"command_{command}", None)
        if not callable(handler):
            return False
        changed = bool(handler(**kwargs))
        if changed:
            self.editor._structure_dirty = True
            self.editor._refresh_structure()
            self.editor._refresh_checklist_display()
            self.editor.block_action_bar.sync()
        return changed

    def command_copy(self) -> bool:
        mime = self.editor.mime_for_blocks(self.blocks())
        if mime is None:
            return False
        QApplication.clipboard().setMimeData(mime)
        return True

    def command_duplicate(self) -> bool:
        mime = self.editor.mime_for_blocks(self.blocks())
        if mime is None:
            return False
        blocks = self.blocks()
        transaction = QTextCursor(self.editor.document())
        transaction.beginEditBlock()
        try:
            cursor = QTextCursor(blocks[-1])
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertBlock()
            self.editor.setTextCursor(cursor)
            self.editor.insertFromMimeData(mime)
        finally:
            transaction.endEditBlock()
        return True

    def _shift_indent(self, amount: int) -> bool:
        blocks = self.blocks()
        if not blocks:
            return False
        transaction = QTextCursor(self.editor.document())
        transaction.beginEditBlock()
        try:
            for block in blocks:
                cursor = QTextCursor(block)
                fmt = block.blockFormat()
                fmt.setIndent(max(0, min(8, int(fmt.indent()) + amount)))
                cursor.setBlockFormat(fmt)
        finally:
            transaction.endEditBlock()
        return True

    def command_indent(self) -> bool:
        return self._shift_indent(1)

    def command_outdent(self) -> bool:
        return self._shift_indent(-1)

    def command_move_up(self) -> bool:
        groups = self.groups()
        if not groups:
            return False
        changed = False
        transaction = QTextCursor(self.editor.document())
        transaction.beginEditBlock()
        try:
            for group in groups:
                first = group[0]
                previous = first.previous()
                if not previous.isValid() or previous.position() in {block.position() for block in self.blocks()}:
                    continue
                changed = self.editor.move_line(
                    previous.position(), group[-1].position(), False,
                ) or changed
        finally:
            transaction.endEditBlock()
        return changed

    def command_move_down(self) -> bool:
        groups = self.groups()
        if not groups:
            return False
        changed = False
        transaction = QTextCursor(self.editor.document())
        transaction.beginEditBlock()
        try:
            for group in reversed(groups):
                last = group[-1]
                following = last.next()
                if not following.isValid() or following.position() in {block.position() for block in self.blocks()}:
                    continue
                target_family = self.editor._block_family(following)
                for block in reversed(group):
                    changed = self.editor.move_line(
                        block.position(), target_family[-1].position(), False,
                    ) or changed
        finally:
            transaction.endEditBlock()
        return changed

    def command_move_to(self, source_at: int, target_at: int, inside: bool = False) -> bool:
        return self.editor.move_line(source_at, target_at, inside)

    def command_delete(self) -> bool:
        groups = self.groups()
        if not groups:
            return False
        transaction = QTextCursor(self.editor.document())
        transaction.beginEditBlock()
        try:
            for group in reversed(groups):
                self.editor._remove_with_separator(transaction, group)
        finally:
            transaction.endEditBlock()
        self.editor.block_selection.clear()
        self.editor.sync_page_titles()
        return True

    def command_group_toggle(self) -> bool:
        groups = self.groups()
        if not groups:
            return False
        transaction = QTextCursor(self.editor.document())
        transaction.beginEditBlock()
        try:
            for group in groups:
                first = group[0]
                marker = QTextCursor(first)
                marker.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                marker.insertText("▾ ")
                base = int(first.blockFormat().indent())
                for block in group[1:]:
                    cursor = QTextCursor(block)
                    fmt = block.blockFormat()
                    fmt.setIndent(max(base + 1, int(fmt.indent())))
                    cursor.setBlockFormat(fmt)
        finally:
            transaction.endEditBlock()
        return True

    def _convert(self, kind: str) -> bool:
        blocks = self.blocks()
        if not blocks:
            return False
        original = self.editor.textCursor()
        transaction = QTextCursor(self.editor.document())
        transaction.beginEditBlock()
        try:
            for block in blocks:
                cursor = QTextCursor(block)
                self.editor.setTextCursor(cursor)
                getattr(self.editor, kind)()
        finally:
            transaction.endEditBlock()
            self.editor.setTextCursor(original)
        return True

    def command_toggle(self) -> bool:
        return self._convert("make_toggle")

    def command_checklist(self) -> bool:
        return self._convert("toggle_checklist")

    def command_bullet(self) -> bool:
        return self._convert("toggle_bullet_list")

    def command_callout(self) -> bool:
        return self._convert("make_callout")

    def command_quote(self) -> bool:
        return self._convert("make_quote")

    def command_code(self) -> bool:
        return self._convert("make_code_block")

    def command_body(self) -> bool:
        blocks = self.blocks()
        if not blocks:
            return False
        original = self.editor.textCursor()
        transaction = QTextCursor(self.editor.document())
        transaction.beginEditBlock()
        try:
            for block in blocks:
                self.editor.setTextCursor(QTextCursor(block))
                self.editor.apply_body_style()
        finally:
            transaction.endEditBlock()
            self.editor.setTextCursor(original)
        return True

    def _heading(self, level: int) -> bool:
        blocks = self.blocks()
        if not blocks:
            return False
        original = self.editor.textCursor()
        transaction = QTextCursor(self.editor.document())
        transaction.beginEditBlock()
        try:
            for block in blocks:
                self.editor.setTextCursor(QTextCursor(block))
                self.editor.apply_heading(level)
        finally:
            transaction.endEditBlock()
            self.editor.setTextCursor(original)
        return True

    def command_heading1(self) -> bool:
        return self._heading(1)

    def command_heading2(self) -> bool:
        return self._heading(2)

    def command_heading3(self) -> bool:
        return self._heading(3)

    def command_heading4(self) -> bool:
        return self._heading(4)

    def command_unlink_features(self) -> bool:
        cursor = self.editor.textCursor()
        exact = None
        if not self.editor.block_selection.count() and cursor.hasSelection():
            exact = (cursor.selectionStart(), cursor.selectionEnd())
        return self.editor.remove_linked_features(self.blocks(), exact_range=exact)

    def command_unlink_links(self) -> bool:
        cursor = self.editor.textCursor()
        exact = None
        if not self.editor.block_selection.count() and cursor.hasSelection():
            exact = (cursor.selectionStart(), cursor.selectionEnd())
        return self.editor.remove_linked_features(self.blocks(), links_only=True, exact_range=exact)
