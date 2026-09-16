"""HTML-backed, non-rendered identity metadata for memo document blocks.

QTextDocument drops arbitrary block properties and HTML ``id`` attributes.
Keep the IDs in a versioned head meta tag instead of making visible text or
link anchors carry application identity. Runtime IDs live on QTextBlockUserData
so inspecting an old note never marks its document modified.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from uuid import UUID, uuid4

from PyQt6.QtGui import QTextBlockFormat, QTextBlockUserData, QTextCursor, QTextDocument


META_NAME = "tomadesk-block-ids-v1"
PIN_META_NAME = "tomadesk-pinned-blocks-v1"
HEADING_FOLD_META_NAME = "tomadesk-folded-headings-v1"
PIN_PROPERTY = QTextBlockFormat.Property.UserProperty + 44
HEADING_FOLDED_PROPERTY = QTextBlockFormat.Property.UserProperty + 32
_META = re.compile(
    rf'<meta\s+name="{META_NAME}"\s+content="([A-Za-z0-9_-]+)"\s*/?>',
    re.IGNORECASE,
)
_PIN_META = re.compile(
    rf'<meta\s+name="{PIN_META_NAME}"\s+content="([A-Za-z0-9_-]+)"\s*/?>',
    re.IGNORECASE,
)
_HEADING_FOLD_META = re.compile(
    rf'<meta\s+name="{HEADING_FOLD_META_NAME}"\s+content="([A-Za-z0-9_-]+)"\s*/?>',
    re.IGNORECASE,
)
_HEAD = re.compile(r"<head(?:\s[^>]*)?>", re.IGNORECASE)


class BlockIdentityData(QTextBlockUserData):
    def __init__(self, block_id: str):
        super().__init__()
        self.block_id = block_id


def _valid_id(value) -> str | None:
    try:
        resolved = UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
    return str(resolved) if resolved.version == 4 else None


def stored_ids(content: str) -> list[str]:
    """Read only our versioned metadata; malformed/untrusted tags are ignored."""
    match = _META.search(str(content or ""))
    if match is None:
        return []
    try:
        token = match.group(1)
        payload = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        values = json.loads(payload)
        if not isinstance(values, list) or len(values) > 100_000:
            return []
        return [value if _valid_id(value) == value else "" for value in values]
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return []


def block_ids(document: QTextDocument) -> list[str]:
    """Assign missing/duplicate IDs without altering text, formatting or Undo."""
    result, seen = [], set()
    block = document.begin()
    while block.isValid():
        data = block.userData()
        value = _valid_id(getattr(data, "block_id", None))
        if value is None or value in seen:
            value = str(uuid4())
            block.setUserData(BlockIdentityData(value))
        result.append(value)
        seen.add(value)
        block = block.next()
    return result


def load_ids(document: QTextDocument, content: str) -> list[str]:
    """Attach legacy or saved IDs to the already-loaded Qt document."""
    saved = stored_ids(content)
    seen = set()
    block = document.begin()
    index = 0
    while block.isValid():
        value = saved[index] if index < len(saved) else ""
        if not value or value in seen:
            value = str(uuid4())
        block.setUserData(BlockIdentityData(value))
        seen.add(value)
        index += 1
        block = block.next()
    return block_ids(document)


def set_ids_from(document: QTextDocument, position: int, ids: list[str]) -> None:
    """Restore source IDs onto blocks recreated by an in-document move."""
    block = document.findBlock(position)
    for value in ids:
        if not block.isValid() or _valid_id(value) != value:
            raise ValueError("Invalid moved block identity")
        block.setUserData(BlockIdentityData(value))
        block = block.next()


def restore_ids(document: QTextDocument, ids: list[str]) -> bool:
    """Restore the exact ID sequence associated with a Qt Undo position."""
    if document.blockCount() != len(ids) or len(set(ids)) != len(ids):
        return False
    if any(_valid_id(value) != value for value in ids):
        return False
    block = document.begin()
    for value in ids:
        block.setUserData(BlockIdentityData(value))
        block = block.next()
    return True


def with_ids(html: str, ids: list[str]) -> str:
    """Embed IDs in Qt-generated HTML without changing visible content."""
    cleaned = _META.sub("", str(html or ""))
    head = _HEAD.search(cleaned)
    if head is None:
        raise ValueError("Block IDs require a complete HTML document")
    if any(_valid_id(value) != value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Block IDs must be distinct UUIDv4 values")
    token = base64.urlsafe_b64encode(
        json.dumps(ids, separators=(",", ":")).encode("ascii")
    ).decode("ascii").rstrip("=")
    return cleaned[:head.end()] + f'<meta name="{META_NAME}" content="{token}" />' + cleaned[head.end():]


def renew_content_ids(content: str) -> str:
    """Give an independent memo/page clone new block IDs, if it has any."""
    existing = stored_ids(content)
    if not existing:
        return content
    fresh = [str(uuid4()) for _ in existing]
    pin_map = dict(zip(existing, fresh))
    renewed = with_ids(content, fresh)
    renewed = with_pins(renewed, {pin_map[value] for value in stored_pins(content) if value in pin_map})
    return with_heading_folds(
        renewed,
        {pin_map[value] for value in stored_heading_folds(content) if value in pin_map},
    )


def is_pinned(block) -> bool:
    return bool(block.isValid() and block.blockFormat().property(PIN_PROPERTY))


def set_pinned(block, pinned: bool) -> None:
    fmt = block.blockFormat()
    if pinned:
        fmt.setProperty(PIN_PROPERTY, True)
    else:
        fmt.clearProperty(PIN_PROPERTY)
    QTextCursor(block).setBlockFormat(fmt)


def pinned_ids(document: QTextDocument) -> set[str]:
    ids = block_ids(document)
    result = set()
    block = document.begin()
    while block.isValid():
        if is_pinned(block):
            result.add(ids[block.blockNumber()])
        block = block.next()
    return result


def stored_pins(content: str) -> set[str]:
    match = _PIN_META.search(str(content or ""))
    if match is None:
        return set()
    try:
        token = match.group(1)
        values = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        if not isinstance(values, list) or len(values) > 100_000:
            return set()
        return {value for value in values if _valid_id(value) == value}
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return set()


def load_pins(document: QTextDocument, content: str) -> None:
    wanted = stored_pins(content).intersection(block_ids(document))
    if not wanted:
        return
    undo_enabled = document.isUndoRedoEnabled()
    document.setUndoRedoEnabled(False)
    try:
        block = document.begin()
        while block.isValid():
            if block.userData().block_id in wanted:
                set_pinned(block, True)
            block = block.next()
    finally:
        document.setUndoRedoEnabled(undo_enabled)


def with_pins(html: str, pins: set[str]) -> str:
    cleaned = _PIN_META.sub("", str(html or ""))
    if not pins:
        return cleaned
    if any(_valid_id(value) != value for value in pins):
        raise ValueError("Pinned blocks must have UUIDv4 identities")
    head = _HEAD.search(cleaned)
    if head is None:
        raise ValueError("Pinned blocks require a complete HTML document")
    token = base64.urlsafe_b64encode(
        json.dumps(sorted(pins), separators=(",", ":")).encode("ascii")
    ).decode("ascii").rstrip("=")
    return cleaned[:head.end()] + f'<meta name="{PIN_META_NAME}" content="{token}" />' + cleaned[head.end():]


def heading_folded_ids(document: QTextDocument) -> set[str]:
    ids = block_ids(document)
    result = set()
    block = document.begin()
    while block.isValid():
        if bool(block.blockFormat().property(HEADING_FOLDED_PROPERTY)):
            result.add(ids[block.blockNumber()])
        block = block.next()
    return result


def stored_heading_folds(content: str) -> set[str]:
    match = _HEADING_FOLD_META.search(str(content or ""))
    if match is None:
        return set()
    try:
        token = match.group(1)
        values = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        if not isinstance(values, list) or len(values) > 100_000:
            return set()
        return {value for value in values if _valid_id(value) == value}
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return set()


def load_heading_folds(document: QTextDocument, content: str) -> None:
    wanted = stored_heading_folds(content).intersection(block_ids(document))
    block = document.begin()
    while block.isValid():
        fmt = block.blockFormat()
        block_id = getattr(block.userData(), "block_id", "")
        if block_id in wanted:
            fmt.setProperty(HEADING_FOLDED_PROPERTY, True)
        else:
            fmt.clearProperty(HEADING_FOLDED_PROPERTY)
        QTextCursor(block).setBlockFormat(fmt)
        block = block.next()


def with_heading_folds(html: str, folded: set[str]) -> str:
    cleaned = _HEADING_FOLD_META.sub("", str(html or ""))
    if not folded:
        return cleaned
    if any(_valid_id(value) != value for value in folded):
        raise ValueError("Folded headings must have UUIDv4 identities")
    head = _HEAD.search(cleaned)
    if head is None:
        raise ValueError("Folded headings require a complete HTML document")
    token = base64.urlsafe_b64encode(
        json.dumps(sorted(folded), separators=(",", ":")).encode("ascii")
    ).decode("ascii").rstrip("=")
    return (
        cleaned[:head.end()]
        + f'<meta name="{HEADING_FOLD_META_NAME}" content="{token}" />'
        + cleaned[head.end():]
    )


# ------------------------------------------------------------ section breaks --
# A body line marked here ends the heading section above it: folding the
# heading no longer hides it.  Stored like folded headings, as invisible head
# metadata, because arbitrary block properties do not survive toHtml().
SECTION_BREAK_META_NAME = "tomadesk-section-breaks-v1"
SECTION_BREAK_PROPERTY = QTextBlockFormat.Property.UserProperty + 46
_SECTION_BREAK_META = re.compile(
    rf'<meta\s+name="{SECTION_BREAK_META_NAME}"\s+content="([A-Za-z0-9_-]+)"\s*/?>',
    re.IGNORECASE,
)


def is_section_break(block) -> bool:
    return block.isValid() and bool(block.blockFormat().property(SECTION_BREAK_PROPERTY))


def section_break_ids(document: QTextDocument) -> set[str]:
    ids = block_ids(document)
    result = set()
    block = document.begin()
    while block.isValid():
        if is_section_break(block):
            result.add(ids[block.blockNumber()])
        block = block.next()
    return result


def stored_section_breaks(content: str) -> set[str]:
    match = _SECTION_BREAK_META.search(str(content or ""))
    if match is None:
        return set()
    try:
        token = match.group(1)
        values = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        if not isinstance(values, list) or len(values) > 100_000:
            return set()
        return {value for value in values if _valid_id(value) == value}
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return set()


def load_section_breaks(document: QTextDocument, content: str) -> None:
    wanted = stored_section_breaks(content).intersection(block_ids(document))
    undo_enabled = document.isUndoRedoEnabled()
    document.setUndoRedoEnabled(False)
    try:
        block = document.begin()
        while block.isValid():
            block_id = getattr(block.userData(), "block_id", "")
            marked = is_section_break(block)
            if (block_id in wanted) != marked:
                fmt = block.blockFormat()
                if block_id in wanted:
                    fmt.setProperty(SECTION_BREAK_PROPERTY, True)
                else:
                    fmt.clearProperty(SECTION_BREAK_PROPERTY)
                QTextCursor(block).setBlockFormat(fmt)
            block = block.next()
    finally:
        document.setUndoRedoEnabled(undo_enabled)


def with_section_breaks(html: str, breaks: set[str]) -> str:
    cleaned = _SECTION_BREAK_META.sub("", str(html or ""))
    if not breaks:
        return cleaned
    if any(_valid_id(value) != value for value in breaks):
        raise ValueError("Section breaks must have UUIDv4 identities")
    head = _HEAD.search(cleaned)
    if head is None:
        raise ValueError("Section breaks require a complete HTML document")
    token = base64.urlsafe_b64encode(
        json.dumps(sorted(breaks), separators=(",", ":")).encode("ascii")
    ).decode("ascii").rstrip("=")
    return (
        cleaned[:head.end()]
        + f'<meta name="{SECTION_BREAK_META_NAME}" content="{token}" />'
        + cleaned[head.end():]
    )
