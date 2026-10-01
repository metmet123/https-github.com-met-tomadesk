"""Full-document Markdown conversion. Original rich notes are backed up by service."""
from PyQt6.QtGui import QTextDocument
from alert_notes.rich_text import is_rich_text_content
from .codec import decode


def to_markdown(content: str) -> str:
    doc=QTextDocument()
    if is_rich_text_content(content): doc.setHtml(content)
    else: doc.setPlainText(content)
    return doc.toMarkdown(QTextDocument.MarkdownFeature.MarkdownDialectGitHub)


def from_markdown(source: str) -> str:
    if not isinstance(source,str) or len(source.encode('utf-8'))>1_000_000 or source.count('\n')>10000:
        raise ValueError('Markdown 문서는 1MB, 10,000줄까지 지원합니다.')
    doc=QTextDocument()
    doc.setMarkdown(source,QTextDocument.MarkdownFeature.MarkdownDialectGitHub | QTextDocument.MarkdownFeature.MarkdownNoHTML)
    return decode(doc.toHtml())[0]
