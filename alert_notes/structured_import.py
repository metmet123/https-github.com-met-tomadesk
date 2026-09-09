from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from PyQt6.QtCore import QMimeData
from PyQt6.QtGui import QTextDocument

from .rich_text import sanitize_rich_html


SUPPORTED_IMPORT_SUFFIXES = {".md", ".markdown", ".html", ".htm", ".txt"}
MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024
MAX_IMPORT_FILES = 50
STRATEGY_PRESERVE = "preserve"
STRATEGY_TOP_TWO_TOGGLES = "top_two_toggles"
STRATEGY_ALL_TOGGLES = "all_toggles"
CLIPBOARD_STRATEGY_KEY = "memo_import_clipboard_strategy_v1"
FILE_STRATEGY_KEY = "memo_import_file_strategy_v1"
DETAIL_START_MARKER = "⟦TOMA_DETAILS_START⟧"
DETAIL_END_MARKER = "⟦TOMA_DETAILS_END⟧"
STRATEGIES = {
    STRATEGY_PRESERVE: "제목 구조 유지",
    STRATEGY_TOP_TWO_TOGGLES: "큰 제목 2단계를 토글로",
    STRATEGY_ALL_TOGGLES: "모든 제목을 토글로",
}


@dataclass(frozen=True)
class ImportDocument:
    title: str
    html: str
    source_kind: str
    source_name: str = "클립보드"


def import_strategy(store, source_kind: str) -> str:
    key = CLIPBOARD_STRATEGY_KEY if source_kind == "clipboard" else FILE_STRATEGY_KEY
    fallback = STRATEGY_TOP_TWO_TOGGLES if source_kind == "clipboard" else STRATEGY_PRESERVE
    value = store.setting(key, fallback) if store is not None else fallback
    return value if value in STRATEGIES else fallback


def save_import_strategies(store, clipboard: str, files: str) -> None:
    if store is None:
        return
    store.set_setting(
        CLIPBOARD_STRATEGY_KEY,
        clipboard if clipboard in STRATEGIES else STRATEGY_TOP_TWO_TOGGLES,
    )
    store.set_setting(
        FILE_STRATEGY_KEY,
        files if files in STRATEGIES else STRATEGY_PRESERVE,
    )


def load_import_file(path: Path) -> ImportDocument:
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix not in SUPPORTED_IMPORT_SUFFIXES:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {source.suffix or '확장자 없음'}")
    size = source.stat().st_size
    if size > MAX_IMPORT_FILE_BYTES:
        raise ValueError(f"파일 크기가 10MB를 초과합니다: {source.name}")
    raw = source.read_bytes()
    text = _decode(raw, allow_cp949=suffix == ".txt")
    if suffix in {".md", ".markdown"}:
        return ImportDocument(
            title=_markdown_title(text) or source.stem,
            html=_markdown_html(text), source_kind="file", source_name=source.name,
        )
    if suffix in {".html", ".htm"}:
        cleaned = _details_to_markers(sanitize_rich_html(text, remove_external_images=True))
        return ImportDocument(
            title=_html_title(cleaned) or source.stem,
            html=cleaned, source_kind="file", source_name=source.name,
        )
    document = QTextDocument()
    document.setPlainText(text)
    return ImportDocument(
        title=_plain_title(text) or source.stem,
        html=document.toHtml(), source_kind="file", source_name=source.name,
    )


def load_clipboard(mime: QMimeData) -> ImportDocument:
    if mime.hasHtml():
        html = _details_to_markers(sanitize_rich_html(mime.html(), remove_external_images=True))
        return ImportDocument(_html_title(html) or "가져온 메모", html, "clipboard")
    if mime.hasFormat("text/markdown"):
        raw = bytes(mime.data("text/markdown"))
        text = _decode(raw, allow_cp949=False)
        return ImportDocument(
            _markdown_title(text) or "가져온 메모", _markdown_html(text), "clipboard",
        )
    text = mime.text() if mime.hasText() else ""
    if not text:
        raise ValueError("클립보드에 가져올 텍스트가 없습니다.")
    # GPT/Claude에서 '텍스트만 복사'한 Markdown도 명시적인 표식이 있으면 구조로 읽는다.
    if re.search(r"(?m)^(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|```)", text):
        return ImportDocument(
            _markdown_title(text) or "가져온 메모", _markdown_html(text), "clipboard",
        )
    document = QTextDocument()
    document.setPlainText(text)
    return ImportDocument(_plain_title(text) or "가져온 메모", document.toHtml(), "clipboard")


def heading_levels_for_strategy(html: str, strategy: str) -> set[int]:
    document = QTextDocument()
    document.setHtml(html)
    levels = sorted({
        int(block.blockFormat().headingLevel())
        for block in _blocks(document)
        if int(block.blockFormat().headingLevel()) > 0
    })
    if strategy == STRATEGY_ALL_TOGGLES:
        return set(levels)
    if strategy == STRATEGY_TOP_TWO_TOGGLES:
        return set(levels[:2])
    return set()


def unique_title(store, wanted: str) -> str:
    base = str(wanted or "").strip() or "가져온 메모"
    existing = {
        str(row[0]).strip().casefold()
        for row in store.conn.execute("SELECT title FROM notes")
    }
    if base.casefold() not in existing:
        return base
    index = 2
    while f"{base} ({index})".casefold() in existing:
        index += 1
    return f"{base} ({index})"


def _blocks(document: QTextDocument):
    block = document.begin()
    while block.isValid():
        yield block
        block = block.next()


def _decode(raw: bytes, allow_cp949: bool) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    if allow_cp949:
        try:
            return raw.decode("cp949")
        except UnicodeDecodeError:
            pass
    raise ValueError("텍스트 인코딩을 읽을 수 없습니다. UTF-8 파일인지 확인해 주세요.")


def _markdown_html(text: str) -> str:
    document = QTextDocument()
    document.setMarkdown(text)
    return sanitize_rich_html(document.toHtml(), remove_external_images=True)


def _details_to_markers(html: str) -> str:
    """Turn common HTML details/summary blocks into explicit native-toggle markers."""
    pattern = re.compile(r"<details\b[^>]*>(.*?)</details\s*>", re.IGNORECASE | re.DOTALL)
    summary_pattern = re.compile(r"<summary\b[^>]*>(.*?)</summary\s*>", re.IGNORECASE | re.DOTALL)

    def replace(match) -> str:
        body = match.group(1)
        summary = summary_pattern.search(body)
        title = summary.group(1) if summary else "세부 내용"
        remainder = summary_pattern.sub("", body, count=1)
        return f"<p>{DETAIL_START_MARKER}{title}</p>{remainder}<p>{DETAIL_END_MARKER}</p>"

    result = html
    for _ in range(16):
        changed = pattern.sub(replace, result)
        if changed == result:
            break
        result = changed
    return result


def _markdown_title(text: str) -> str:
    match = re.search(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", text)
    return re.sub(r"[*_`\[\]]", "", match.group(1)).strip() if match else ""


def _html_title(html: str) -> str:
    for pattern in (
        r"<title\b[^>]*>(.*?)</title>",
        r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>",
    ):
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            document = QTextDocument()
            document.setHtml(match.group(1))
            value = document.toPlainText().strip()
            if value:
                return value[:120]
    return ""


def _plain_title(text: str) -> str:
    return next((line.strip()[:120] for line in text.splitlines() if line.strip()), "")
