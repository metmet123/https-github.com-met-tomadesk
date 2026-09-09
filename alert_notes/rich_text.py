from html import escape
import re

from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QTextEdit


def is_rich_text_content(content: str) -> bool:
    text = str(content or "").lstrip().lower()
    return text.startswith("<!doctype html") or text.startswith("<html")


def load_editor_content(editor: QTextEdit, content: str) -> None:
    if is_rich_text_content(content):
        editor.setHtml(content)
    else:
        editor.setPlainText(content)


def editor_content(editor: QTextEdit) -> str:
    return editor.toHtml() if editor.toPlainText().strip() else ""


def plain_text_from_content(content: str) -> str:
    if not is_rich_text_content(content):
        return str(content or "")
    document = QTextDocument()
    document.setHtml(content)
    return document.toPlainText().replace("\ufffc", "[이미지]")


def html_from_plain_text(content: str) -> str:
    return escape(str(content or "")).replace("\n", "<br>")


def sanitize_rich_html(content: str, remove_external_images: bool = False) -> str:
    """Keep common memo formatting while removing active or embedded web content."""
    html = str(content or "")
    html = re.sub(
        r"<\s*(script|style|iframe|object|embed|form)\b[^>]*>.*?<\s*/\s*\1\s*>",
        "", html, flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(r"\s+on[a-z]+\s*=\s*(['\"]).*?\1", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"(?:javascript|vbscript)\s*:", "", html, flags=re.IGNORECASE)
    if remove_external_images:
        html = re.sub(
            r"<\s*img\b[^>]*\bsrc\s*=\s*(?:(['\"])(?:https?:)?//.*?\1|(?:https?:)?//[^\s>]+)[^>]*>",
            "", html, flags=re.IGNORECASE | re.DOTALL,
        )
    return html
