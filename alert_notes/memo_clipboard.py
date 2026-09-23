from __future__ import annotations

import json
import html as html_module
import re

from PyQt6.QtCore import QByteArray, QMimeData, QUrl
from PyQt6.QtGui import QTextCursor, QTextDocument


BLOCK_MIME = "application/x-tomadesk-blocks+json"
NOTES_MIME = "application/x-tomadesk-notes+json"


def single_web_url(source: QMimeData) -> str | None:
    """Return the URL represented by a lone external web link on the clipboard."""
    if source.hasFormat(BLOCK_MIME) or source.hasFormat(NOTES_MIME):
        return None
    plain = source.text().strip() if source.hasText() else ""
    if plain and not any(char.isspace() for char in plain):
        url = QUrl(plain)
        if url.scheme().casefold() in {"http", "https"} and url.host():
            return url.toString()
    urls = source.urls() if source.hasUrls() else []
    if len(urls) == 1 and urls[0].scheme().casefold() in {"http", "https"} and urls[0].host():
        return urls[0].toString()
    if not source.hasHtml() or not plain or "\n" in plain:
        return None
    document = QTextDocument()
    document.setHtml(source.html())
    if document.toPlainText().strip() != plain or "\ufffc" in plain:
        return None
    hrefs = set()
    block = document.begin()
    while block.isValid():
        fragment = block.begin()
        while not fragment.atEnd():
            item = fragment.fragment()
            if item.isValid() and item.text().strip():
                href = item.charFormat().anchorHref()
                if not href:
                    return None
                hrefs.add(href)
            fragment += 1
        block = block.next()
    if len(hrefs) != 1:
        return None
    url = QUrl(next(iter(hrefs)))
    return url.toString() if url.scheme().casefold() in {"http", "https"} and url.host() else None
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
