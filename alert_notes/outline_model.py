"""Document-order outline derived from memo blocks, without a database index."""

from __future__ import annotations

from dataclasses import dataclass

from .block_identity import block_ids, is_pinned


@dataclass(frozen=True)
class OutlineEntry:
    block_id: str
    kind: str
    label: str
    level: int
    position: int
    pinned: bool


def outline_entries(editor) -> list[OutlineEntry]:
    ids = block_ids(editor.document())
    entries = []
    block = editor.document().begin()
    while block.isValid():
        text = block.text().strip()
        level = editor.heading_level(block)
        page_id = editor.page_id_of_block(block)
        pinned = is_pinned(block)
        if level and page_id is None:
            kind = "heading"
            label = text.removeprefix("▶ ").strip()
        elif page_id is not None:
            kind = "page"
            label = text.removeprefix("📄 ").strip()
        elif editor._is_toggle_block(block):
            kind = "toggle"
            label = text.removeprefix("▾ ").removeprefix("▸ ").strip()
        elif pinned:
            kind = "pinned"
            label = text
        else:
            block = block.next()
            continue
        entries.append(OutlineEntry(
            ids[block.blockNumber()], kind, label or "제목 없음", level,
            block.position(), pinned,
        ))
        block = block.next()
    return entries


def resolve_block(editor, block_id: str):
    ids = block_ids(editor.document())
    try:
        return editor.document().findBlockByNumber(ids.index(str(block_id)))
    except ValueError:
        return None
