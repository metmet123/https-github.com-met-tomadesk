from __future__ import annotations

import re


_BLOCK_V1 = re.compile(r"toma-block://v1/(\d+)/([0-9a-fA-F-]{36})", re.IGNORECASE)
_BLOCK_V2 = re.compile(
    r"toma-block://v2/([0-9a-fA-F-]{36})/([0-9a-fA-F-]{36})", re.IGNORECASE,
)
_NOTE_V1 = re.compile(r"toma-note://(?!v2/)(\d+)", re.IGNORECASE)
_NOTE_V2 = re.compile(r"toma-note://v2/([0-9a-fA-F-]{36})", re.IGNORECASE)
_IMAGE = re.compile(r"toma-note-image://(?:attachment/)?(\d+)", re.IGNORECASE)


def rewrite_internal_links(
    content: str,
    *,
    note_ids: dict[int, int] | None = None,
    note_sync_ids: dict[str, str] | None = None,
    attachment_ids: dict[int, int] | None = None,
    block_ids_by_local: dict[int, dict[str, str]] | None = None,
    block_ids_by_sync: dict[str, dict[str, str]] | None = None,
) -> str:
    """Remap only entities included in a clone/restore graph.

    References outside the supplied maps stay byte-for-byte compatible.  Block
    identities are scoped to their memo, so a cloned target can replace both
    parts of a block URL without touching unrelated links.
    """

    local = {int(key): int(value) for key, value in (note_ids or {}).items()}
    sync = {str(key).lower(): str(value) for key, value in (note_sync_ids or {}).items()}
    attachments = {int(key): int(value) for key, value in (attachment_ids or {}).items()}
    local_blocks = block_ids_by_local or {}
    sync_blocks = {str(key).lower(): value for key, value in (block_ids_by_sync or {}).items()}

    def block_v1(match: re.Match) -> str:
        old_note = int(match.group(1))
        if old_note not in local:
            return match.group(0)
        old_block = match.group(2)
        new_block = local_blocks.get(old_note, {}).get(old_block, old_block)
        return f"toma-block://v1/{local[old_note]}/{new_block}"

    def block_v2(match: re.Match) -> str:
        old_note = match.group(1)
        mapped = sync.get(old_note.lower())
        if mapped is None:
            return match.group(0)
        old_block = match.group(2)
        new_block = sync_blocks.get(old_note.lower(), {}).get(old_block, old_block)
        return f"toma-block://v2/{mapped}/{new_block}"

    rewritten = _BLOCK_V1.sub(block_v1, str(content or ""))
    rewritten = _BLOCK_V2.sub(block_v2, rewritten)
    rewritten = _NOTE_V2.sub(
        lambda match: f"toma-note://v2/{sync[match.group(1).lower()]}"
        if match.group(1).lower() in sync else match.group(0),
        rewritten,
    )
    rewritten = _NOTE_V1.sub(
        lambda match: f"toma-note://{local[int(match.group(1))]}"
        if int(match.group(1)) in local else match.group(0),
        rewritten,
    )
    return _IMAGE.sub(
        lambda match: f"toma-note-image://attachment/{attachments[int(match.group(1))]}"
        if int(match.group(1)) in attachments else match.group(0),
        rewritten,
    )
