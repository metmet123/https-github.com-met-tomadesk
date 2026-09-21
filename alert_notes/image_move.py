"""Move one embedded image inside a QTextDocument without cloning attachments."""

from PyQt6.QtGui import QTextCursor, QTextDocumentFragment

from .block_identity import block_ids, is_pinned, set_ids_from, set_pinned


def move_image(document, source_at: int, target_at: int, *, separate: bool = False,
               after: bool = False) -> int | None:
    """Move the original image run in one undo step; return its new position."""
    if not 0 <= source_at < document.characterCount() - 1:
        return None
    if not 0 <= target_at < document.characterCount():
        return None
    source = QTextCursor(document)
    source.setPosition(source_at)
    source.setPosition(source_at + 1, QTextCursor.MoveMode.KeepAnchor)
    if not source.charFormat().isImageFormat():
        return None
    if source_at <= target_at <= source_at + 1:
        return None
    destination = QTextCursor(document)
    destination.setPosition(target_at)
    if not destination.block().isVisible():
        return None
    source_block = document.findBlock(source_at)
    image_only = source_block.length() == 2
    source_id = block_ids(document)[source_block.blockNumber()] if image_only else None
    source_pinned = is_pinned(source_block) if image_only else False
    fragment = QTextDocumentFragment(source)
    source.beginEditBlock()
    try:
        source.removeSelectedText()
        if separate and destination.currentTable() is None:
            if after:
                destination.insertBlock()
                destination.insertFragment(fragment)
            else:
                destination.insertFragment(fragment)
                marker = QTextCursor(document)
                marker.setPosition(destination.position() - 1)
                destination.insertBlock()
        else:
            destination.insertFragment(fragment)
        if not (separate and not after and destination.currentTable() is None):
            marker = QTextCursor(document)
            marker.setPosition(destination.position() - 1)
        if image_only:
            empty = document.findBlock(source.position())
            if empty.isValid() and empty.text() == "" and QTextCursor(empty).currentTable() is None:
                cleaner = QTextCursor(empty)
                cleaner.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                if empty.next().isValid() and QTextCursor(empty.next()).currentTable() is None:
                    cleaner.deleteChar()
                elif empty.previous().isValid() and QTextCursor(empty.previous()).currentTable() is None:
                    cleaner.deletePreviousChar()
        moved_at = marker.position()
        if source_id is not None and source_id not in block_ids(document):
            moved_block = document.findBlock(moved_at)
            if moved_block.isValid() and moved_block.length() == 2:
                set_ids_from(document, moved_at, [source_id])
                if source_pinned:
                    set_pinned(moved_block, True)
        return moved_at
    finally:
        source.endEditBlock()
