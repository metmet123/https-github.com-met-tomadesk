from __future__ import annotations

import json
import html as html_module
import re

from PyQt6.QtCore import QByteArray, QMimeData
from PyQt6.QtGui import QTextCursor


BLOCK_MIME = "application/x-tomadesk-blocks+json"
NOTES_MIME = "application/x-tomadesk-notes+json"
_PAGE_ANCHOR_RE = re.compile(
    r"<a\b[^>]*\bhref=(['\"])toma-note://(\d+)\1[^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_PAGE_SYNC_ANCHOR_RE = re.compile(
    r"<a\b[^>]*\bhref=(['\"])toma-note://v2/([0-9a-fA-F-]{36})\1[^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_IMAGE_RE = re.compile(r"toma-note-image://(?:attachment/)?(\d+)", re.IGNORECASE)


def set_json(mime: QMimeData, mime_type: str, payload: dict) -> None:
    mime.setData(
        mime_type,
        QByteArray(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
    )


def get_json(mime: QMimeData, mime_type: str) -> dict | None:
    if not mime.hasFormat(mime_type):
        return None
    try:
        value = json.loads(bytes(mime.data(mime_type)).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) and int(value.get("version", 0)) == 1 else None


def selected_block_metadata(cursor: QTextCursor, heading_level) -> list[dict]:
    start, end = cursor.selectionStart(), cursor.selectionEnd()
    document = cursor.document()
    block = document.findBlock(start)
    values = []
    while block.isValid() and block.position() <= end:
        fmt = block.blockFormat()
        values.append({
            "indent": int(fmt.indent()),
            "heading": int(heading_level(block)),
            "user_state": int(block.userState()),
        })
        if block.position() + block.length() > end:
            break
        block = block.next()
    return values


def apply_block_metadata(document, start: int, metadata, set_heading_level) -> None:
    block = document.findBlock(max(0, int(start)))
    for value in metadata or []:
        if not block.isValid():
            break
        cursor = QTextCursor(block)
        fmt = block.blockFormat()
        fmt.setIndent(max(0, int(value.get("indent", 0))))
        cursor.setBlockFormat(fmt)
        set_heading_level(block, int(value.get("heading", 0)))
        block.setUserState(int(value.get("user_state", -1)))
        block = block.next()


def page_ids_from_html(html: str) -> list[int]:
    found = []
    for match in _PAGE_ANCHOR_RE.finditer(str(html or "")):
        text = html_module.unescape(re.sub(r"<[^>]+>", "", match.group(3))).lstrip()
        if text.startswith("📄"):
            found.append(int(match.group(2)))
    return list(dict.fromkeys(found))


def page_sync_ids_from_html(html: str) -> list[str]:
    found = []
    for match in _PAGE_SYNC_ANCHOR_RE.finditer(str(html or "")):
        text = html_module.unescape(re.sub(r"<[^>]+>", "", match.group(3))).lstrip()
        if text.startswith("📄"):
            found.append(match.group(2).lower())
    return list(dict.fromkeys(found))


def attachment_ids_from_html(html: str) -> list[int]:
    return list(dict.fromkeys(int(value) for value in _IMAGE_RE.findall(str(html or ""))))
