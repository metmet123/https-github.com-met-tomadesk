from __future__ import annotations

import base64
import re
import weakref
from pathlib import Path

from PyQt6.QtCore import (
    QByteArray, QBuffer, QEvent, QIODevice, QLineF, QMimeData, QPoint, QPointF, QRectF,
    QTimer, Qt, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QDesktopServices, QFont, QFontMetricsF, QImage, QImageReader, QKeyEvent,
    QMouseEvent, QPainter, QPen, QTextCharFormat, QTextCursor, QTextDocument,
    QTextBlockFormat, QTextFrameFormat, QTextImageFormat, QTextLength,
    QTextListFormat, QTextTableCellFormat, QTextTableFormat,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QListWidget, QListWidgetItem, QMessageBox, QTextEdit,
)

from .insert_menu import (
    install_insert_shortcuts, item_label, item_tooltip, matching_items,
)
from .insert_preferences import get_insert_preferences
from .note_link_dialog import NoteLinkDialog
from .line_gutter import LineGutter
from .rich_text import editor_content, load_editor_content, sanitize_rich_html


IMAGE_URL_PREFIX = "toma-note-image://"
# 메모 안에 사는 메모.  본문에는 한 줄로 보이고, 누르면 그 메모가 열린다.
PAGE_URL_PREFIX = "toma-note://"
PAGE_MARK = "📄 "
# 아직 이름을 치지 않은 페이지.  본문 줄에 친 글이 곧 제목이 된다.
DEFAULT_PAGE_TITLE = "제목 없음"
# 이미 있는 메모를 가리키기만 하는 링크.  페이지와 달리 이 줄을 지워도 그
# 메모는 그대로 남는다.  그래서 표시 글자를 달리 둔다.
LINK_MARK = "🔗 "
_PAGE_ID_RE = re.compile(r"toma-note://(\d+)", re.IGNORECASE)
MAX_IMAGE_EDGE = 1920
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_ORIGINAL_WIDTH = QTextCharFormat.Property.UserProperty + 21
IMAGE_ORIGINAL_HEIGHT = QTextCharFormat.Property.UserProperty + 22
# 사용자가 직접 끌어 정한 폭.  창 크기에 맞춰 다시 맞출 때도 이 값을 지킨다.
IMAGE_USER_WIDTH = QTextCharFormat.Property.UserProperty + 23
# 모서리를 잡는 자리.
IMAGE_GRIP = 14.0
IMAGE_MIN_WIDTH = 60.0
UNCHECKED_PREFIX = "☐ "
CHECKED_PREFIX = "☑ "
# 노션식 토글.  펼침/접힘을 글자 하나로 들고 다니므로 저장한 HTML에도 그대로
# 남고, 다시 열었을 때 접힌 상태가 살아난다.
TOGGLE_OPEN_PREFIX = "▾ "
TOGGLE_CLOSED_PREFIX = "▸ "
TOGGLE_PREFIXES = (TOGGLE_OPEN_PREFIX, TOGGLE_CLOSED_PREFIX)
# 펼쳐 두었는데 안이 빈 토글에만 그린다.  문서에 넣는 글자가 아니라 화면에만
# 그리므로 저장한 메모에는 이 문장이 남지 않는다.
EMPTY_TOGGLE_HINT = "빈 토글입니다. 클릭하거나 블록을 내부로 드래그하세요."
# 강조 상자.  긴 메모에서 눈이 쉬어 가는 자리다.  토글·체크리스트와 같이 줄 앞
# 글자로 표시를 들고 다니므로 저장한 HTML 에도 그대로 남는다.
CALLOUT_PREFIX = "💡 "
CALLOUT_BACKGROUND = "#fff8e1"
# 인용문.  표시는 감추고 왼쪽에 세로줄을 그린다.  글자는 기울이고 흐리게.
QUOTE_PREFIX = "❝ "
QUOTE_COLOR = "#475569"
QUOTE_BAR_COLOR = "#94a3b8"
QUOTE_MARGIN = 16
# 코드 줄.  회색 바탕에 고정폭 글씨.  띄어쓰기가 그대로 남는다.
CODE_PREFIX = "⌗ "
CODE_BACKGROUND = "#f1f5f9"
CODE_FONT_FAMILY = "Consolas"
# 표.  머리줄 한 줄에 세 칸으로 시작한다.
TABLE_ROWS = 3
TABLE_COLUMNS = 3
TABLE_BORDER_COLOR = "#cbd5e1"
TABLE_HEADER_BACKGROUND = "#f1f5f9"
# 구분선.  글자는 화면에서 감추고 그 자리에 가로줄을 그린다.
DIVIDER_TEXT = "───"
DIVIDER_COLOR = "#cbd5e1"
_IMAGE_ID_RE = re.compile(r"toma-note-image://(?:attachment/)?(\d+)", re.IGNORECASE)
_LINK_RE = re.compile(r"(?P<url>(?:https?://|www\.)[^\s<>]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})$")
HEADING_LEVEL_PROPERTY = QTextBlockFormat.Property.UserProperty + 31
HEADING_STYLES = {
    1: (22.0, 0.7, 12.0, 6.0),
    2: (18.0, 0.5, 10.0, 5.0),
    3: (15.0, 0.3, 8.0, 4.0),
    4: (13.0, 0.1, 6.0, 3.0),
}


def attachment_ids_from_content(content: str) -> set[int]:
    return {int(value) for value in _IMAGE_ID_RE.findall(str(content or ""))}


class RichMemoTextEdit(QTextEdit):
    """Shared rich memo editor used by full editors and desktop post-its."""

    # `/` 메뉴 한 줄의 높이.
    INSERT_ROW_HEIGHT = 26

    save_error = pyqtSignal(str)
    page_created = pyqtSignal(int)
    page_open_requested = pyqtSignal(int)
    page_renamed = pyqtSignal(int)
    page_removed = pyqtSignal(int)

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.insert_preferences = get_insert_preferences(store)
        self.note_id: int | None = None
        self._refitting_images = False
        # 마우스가 올라와 있는 토글·체크리스트 표시의 위치.  손가락 커서와 옅은
        # 사각형을 어디에 그릴지 이 값 하나로 정한다.
        self._hover_marker: int | None = None
        self._syncing_toggle_children = False
        self._claimed_press = False
        # 본문에 지금 들어 있는 페이지들.  줄이 사라지면 그 페이지도 휴지통으로
        # 보내야 하므로, 직전에 무엇이 있었는지 들고 있어야 한다.
        self._known_pages: set[int] = set()
        # `/` 를 쳤을 때 뜨는 삽입 메뉴.  쓸 때 만든다.
        self._insert_popup = None
        # 끌고 있는 줄과 놓을 자리.
        self._drag_source: int | None = None
        self._drop_at = None
        # 크기를 끌고 있는 그림.
        self._image_resize = None
        # 구조(토글·줄 수)가 바뀌었을 때만 문서를 다시 계산한다.
        self._watched_document = None
        self._structure_dirty = True
        self._block_count = 0
        # 본문 찾기로 표시해 둔 자리.  칠할 때 체크리스트 표시와 함께 얹는다.
        self._find_ranges: list[tuple[int, int]] = []
        self._find_current = -1
        self.setAcceptRichText(True)
        self.setAccessibleName("메모 본문")
        self.setTabChangesFocus(False)
        self._configure_document(self.document())
        self._watch_document(self.document())
        self.document().setModified(False)
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.timeout.connect(self.refit_images)
        self.textChanged.connect(self._refresh_checklist_display)
        self.textChanged.connect(self._refresh_structure)
        # 스크롤하면 보이는 줄이 달라진다.  그때 다시 칠한다.
        self.verticalScrollBar().valueChanged.connect(self._refresh_checklist_display)
        self._page_sync_timer = QTimer(self)
        self._page_sync_timer.setSingleShot(True)
        self._page_sync_timer.setInterval(350)
        self._page_sync_timer.timeout.connect(self.sync_page_titles)
        self.textChanged.connect(self._queue_page_sync)
        self.cursorPositionChanged.connect(self._refresh_insert_popup)
        self.textChanged.connect(lambda: self.gutter.update() if hasattr(self, "gutter") else None)
        self.viewport().setMouseTracking(True)
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        # 줄 손잡이 칸.  본문 오른쪽 끝에 둔다.
        self.gutter = LineGutter(self)
        self.setViewportMargins(0, 0, LineGutter.WIDTH, 0)
        self._place_gutter()
        # 넣을 수 있는 것들의 단축키.  목록 한곳에 적힌 것을 그대로 건다.
        self.insert_shortcuts = install_insert_shortcuts(self)

    def set_note_context(self, note_id: int | None) -> None:
        resolved = int(note_id) if note_id is not None else None
        if self.note_id == resolved:
            return
        previous = self.note_id
        views = getattr(self.store, "_rich_document_views", None) if self.store is not None else None
        if previous is not None and views is not None and previous in views:
            views[previous].discard(self)
        self.note_id = resolved
        new_document = False
        if self.store is None or resolved is None:
            document = QTextDocument()
            new_document = True
        else:
            registry = getattr(self.store, "_rich_document_registry", None)
            if registry is None:
                registry = {}
                setattr(self.store, "_rich_document_registry", registry)
            document = registry.get(resolved)
            if document is None:
                document = QTextDocument()
                registry[resolved] = document
                new_document = True
            if views is None:
                views = {}
                setattr(self.store, "_rich_document_views", views)
            views.setdefault(resolved, weakref.WeakSet()).add(self)
        self._configure_document(document)
        self.setDocument(document)
        self._watch_document(document)
        if new_document:
            document.setModified(False)
        self._refit_timer.start(0)
        self._refresh_checklist_display()
        self._reset_typing_format()
        # 문서가 바뀌었다.  "직전에 있던 페이지" 기준을 새 문서로 다시 잡지
        # 않으면, 앞 메모의 페이지가 사라진 줄 알고 휴지통으로 보낸다.
        self._refresh_known_pages()

    def _watch_document(self, document) -> None:
        """이 문서에서 무엇이 바뀌는지 지켜본다.

        글자 한 자를 칠 때마다 문서 전체를 훑지 않으려면, 구조가 바뀐 편집인지
        아닌지를 알아야 한다.  그 판단에 쓸 신호를 여기서 잇는다.
        """
        if self._watched_document is document:
            self._block_count = document.blockCount()
            return
        if self._watched_document is not None:
            try:
                self._watched_document.contentsChange.disconnect(self._note_contents_change)
            except (RuntimeError, TypeError):
                # 앞 문서가 이미 지워졌으면 끊을 것도 없다.
                pass
        self._watched_document = document
        document.contentsChange.connect(self._note_contents_change)
        self._block_count = document.blockCount()
        self._structure_dirty = True

    def _note_contents_change(self, position: int, removed: int, added: int) -> None:
        """바뀐 자리가 구조를 건드렸는지만 표시해 둔다.

        한 줄 안에서 글자만 친 것이면 토글 접기도, 빈 토글 줄도 달라질 수 없다.
        줄이 나뉘거나 합쳐졌거나 토글 줄을 건드렸을 때만 다시 계산한다.
        """
        if self._structure_dirty:
            return
        document = self.document()
        first = document.findBlock(max(0, position))
        last = document.findBlock(max(0, position + max(added, removed)))
        if not first.isValid() or first.blockNumber() != last.blockNumber():
            self._structure_dirty = True
            return
        if self._is_toggle_block(first):
            self._structure_dirty = True

    def _refresh_structure(self) -> None:
        """줄 수가 달라졌거나 토글이 건드려졌을 때만 문서 전체를 다시 본다."""
        document = self.document()
        if document.blockCount() != self._block_count:
            self._structure_dirty = True
        if not self._structure_dirty:
            return
        self._structure_dirty = False
        self._refresh_toggle_visibility()
        self._ensure_toggle_children()
        self._block_count = document.blockCount()

    def _reset_typing_format(self) -> None:
        """앞 문서에서 쓰던 입력 서식을 새 문서로 끌고 오지 않는다.

        페이지 줄 끝에 커서를 둔 채 그 페이지를 열면, 위젯이 들고 있던 줄의
        서식(밑줄·링크색)이 그대로 남아 새 메모의 첫 글자가 링크처럼 보였다.
        커서가 실제로 링크 안에 있을 때만 그 서식을 잇고, 아니면 맨 서식으로
        되돌린다.
        """
        cursor = self.textCursor()
        inside_link = cursor.position() > cursor.block().position() and (
            cursor.charFormat().isAnchor()
        )
        if not inside_link:
            self.setCurrentCharFormat(QTextCharFormat())

    def bind_current_document(self, note_id: int) -> None:
        """Attach an unsaved draft document to its newly-created database note."""
        resolved = int(note_id)
        if self.store is not None:
            registry = getattr(self.store, "_rich_document_registry", None)
            if registry is None:
                registry = {}
                setattr(self.store, "_rich_document_registry", registry)
            registry[resolved] = self.document()
            views = getattr(self.store, "_rich_document_views", None)
            if views is None:
                views = {}
                setattr(self.store, "_rich_document_views", views)
            views.setdefault(resolved, weakref.WeakSet()).add(self)
        self.note_id = resolved

    def set_content(self, content: str) -> None:
        source = self.document().property("tomaSourceContent")
        if self.document().isModified():
            return
        if source is not None and str(source) == str(content or ""):
            return
        self._register_content_images(content)
        load_editor_content(self, content)
        # 접어 둔 토글은 ▸ 글자에 상태가 남아 있다.  그대로 다시 접는다.
        self._refresh_toggle_visibility()
        # 이 기능이 생기기 전에 만든 빈 토글에도 안내가 들어갈 자리를 만들어 준다.
        self._ensure_toggle_children()
        # 페이지 줄에 옛 제목이 남아 있으면 지금 제목으로 맞춘다.
        self._refresh_page_links()
        self._refresh_note_links()
        self._refresh_known_pages()
        self._reset_typing_format()
        self.document().setProperty("tomaSourceContent", str(content or ""))
        self.document().setModified(False)
        self._refit_timer.start(0)

    def content(self) -> str:
        return editor_content(self)

    def mark_document_saved(self, content: str | None = None) -> None:
        resolved = self.content() if content is None else str(content)
        self.document().setProperty("tomaSourceContent", resolved)
        self.document().setModified(False)

    @staticmethod
    def _configure_document(document: QTextDocument) -> None:
        # Malgun Gothic is a stable document fallback for Korean glyphs. The
        # stylesheet still gives Latin glyphs Segoe UI Variable priority.
        font = QFont("Malgun Gothic")
        font.setPointSizeF(10.5)
        document.setDefaultFont(font)
        document.setDefaultStyleSheet(
            "body, p, li { font-family:'Segoe UI Variable','Malgun Gothic'; "
            "font-size:14px; line-height:140%; }"
        )

    def toggle_character_style(self, style: str) -> None:
        current = self.currentCharFormat()
        fmt = QTextCharFormat()
        if style == "bold":
            active = current.fontWeight() >= QFont.Weight.Bold
            fmt.setFontWeight(QFont.Weight.Normal if active else QFont.Weight.Bold)
        elif style == "italic":
            fmt.setFontItalic(not current.fontItalic())
        elif style == "underline":
            fmt.setFontUnderline(not current.fontUnderline())
        elif style == "strike":
            fmt.setFontStrikeOut(not current.fontStrikeOut())
        else:
            return
        cursor = self.textCursor()
        cursor.mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)
        self.setFocus()

    def toggle_bullet_list(self) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        current = cursor.currentList()
        if current is not None and current.format().style() == QTextListFormat.Style.ListDisc:
            block_format = cursor.blockFormat()
            block_format.setIndent(0)
            block_format.setObjectIndex(-1)
            cursor.setBlockFormat(block_format)
        else:
            list_format = QTextListFormat()
            list_format.setStyle(QTextListFormat.Style.ListDisc)
            list_format.setIndent(max(1, cursor.blockFormat().indent() + 1))
            cursor.createList(list_format)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.setFocus()

    def current_block_is_bullet_list(self) -> bool:
        current = self.textCursor().currentList()
        return bool(current is not None and current.format().style() == QTextListFormat.Style.ListDisc)

    def toggle_checklist(self) -> None:
        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        first = self.document().findBlock(start)
        last = self.document().findBlock(max(start, end - 1))
        blocks = []
        block = first
        while block.isValid():
            blocks.append(block)
            if block == last:
                break
            block = block.next()
        make_checklist = not blocks or not all(self._is_checklist_block(item) for item in blocks)
        edit = QTextCursor(self.document())
        edit.beginEditBlock()
        try:
            for item in reversed(blocks):
                block_cursor = QTextCursor(item)
                block_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                if make_checklist:
                    if not self._is_checklist_block(item):
                        block_cursor.insertText(UNCHECKED_PREFIX)
                else:
                    self._remove_checklist_prefix(block_cursor.block())
        finally:
            edit.endEditBlock()
        self.setFocus()

    @staticmethod
    def _is_checklist_block(block) -> bool:
        return block.text().startswith((UNCHECKED_PREFIX, CHECKED_PREFIX))

    def current_block_is_checklist(self) -> bool:
        return self._is_checklist_block(self.textCursor().block())

    def _remove_checklist_prefix(self, block) -> None:
        if not self._is_checklist_block(block):
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 2)
        cursor.removeSelectedText()

    def _toggle_check_state(self, block) -> None:
        if not self._is_checklist_block(block):
            return
        completed = block.text().startswith(UNCHECKED_PREFIX)
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText("☑" if completed else "☐")
        self._refresh_checklist_display()

    def _refresh_checklist_display(self) -> None:
        selections = []
        for block in self._visible_blocks():
            text = block.text()
            if text == DIVIDER_TEXT:
                # 글자는 감추고 paintEvent 가 그 자리에 선을 그린다.
                hidden = QTextEdit.ExtraSelection()
                hidden.cursor = QTextCursor(block)
                hidden.cursor.setPosition(block.position())
                hidden.cursor.setPosition(
                    block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor,
                )
                hidden.format.setForeground(QColor(0, 0, 0, 0))
                selections.append(hidden)
            if text.startswith((QUOTE_PREFIX, CODE_PREFIX)):
                # 표시 글자는 감춘다.  자리는 여백과 바탕이 대신한다.
                mark = QTextEdit.ExtraSelection()
                mark.cursor = QTextCursor(block)
                mark.cursor.setPosition(block.position())
                mark.cursor.setPosition(
                    block.position() + len(QUOTE_PREFIX), QTextCursor.MoveMode.KeepAnchor,
                )
                mark.format.setForeground(QColor(0, 0, 0, 0))
                selections.append(mark)
            if text.startswith((UNCHECKED_PREFIX, CHECKED_PREFIX)):
                prefix = QTextEdit.ExtraSelection()
                prefix.cursor = QTextCursor(block)
                prefix.cursor.setPosition(block.position())
                prefix.cursor.setPosition(block.position() + 2, QTextCursor.MoveMode.KeepAnchor)
                prefix.format.setForeground(QColor(0, 0, 0, 0))
                selections.append(prefix)
                if text.startswith(CHECKED_PREFIX) and block.length() > 3:
                    completed = QTextEdit.ExtraSelection()
                    completed.cursor = QTextCursor(block)
                    completed.cursor.setPosition(block.position() + 2)
                    completed.cursor.setPosition(
                        block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor,
                    )
                    completed.format.setFontStrikeOut(True)
                    completed.format.setForeground(QColor(71, 85, 105, 145))
                    selections.append(completed)
        selections.extend(self._find_selections())
        self.setExtraSelections(selections)
        self.viewport().update()

    # ------------------------------------------------------------ 본문 찾기 --
    FIND_BACKGROUND = "#fde68a"
    FIND_CURRENT_BACKGROUND = "#fb923c"

    def find_matches(self, text: str, case_sensitive: bool = False) -> list:
        """본문에서 그 글이 있는 자리를 모두 찾는다.  접힌 토글 안도 센다."""
        if not text:
            return []
        flags = (
            QTextDocument.FindFlag.FindCaseSensitively
            if case_sensitive else QTextDocument.FindFlag(0)
        )
        document = self.document()
        found = []
        cursor = QTextCursor(document)
        while True:
            cursor = document.find(text, cursor, flags)
            if cursor.isNull():
                break
            found.append((cursor.selectionStart(), cursor.selectionEnd()))
        return found

    def set_find_highlights(self, ranges, current: int = -1) -> None:
        """찾은 자리를 노랗게, 지금 자리를 주황으로 칠한다."""
        self._find_ranges = [(int(a), int(b)) for a, b in ranges]
        self._find_current = int(current)
        self._refresh_checklist_display()

    def clear_find_highlights(self) -> None:
        if not self._find_ranges and self._find_current < 0:
            return
        self._find_ranges = []
        self._find_current = -1
        self._refresh_checklist_display()

    def _find_selections(self):
        """찾은 자리 중 화면에 걸친 것만 칠한다."""
        if not self._find_ranges:
            return []
        blocks = list(self._visible_blocks())
        if not blocks:
            return []
        top = blocks[0].position()
        bottom = blocks[-1].position() + blocks[-1].length()
        out = []
        for index, (start, end) in enumerate(self._find_ranges):
            if end < top or start > bottom:
                continue
            mark = QTextEdit.ExtraSelection()
            mark.cursor = QTextCursor(self.document())
            mark.cursor.setPosition(start)
            mark.cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            colour = (
                self.FIND_CURRENT_BACKGROUND if index == self._find_current
                else self.FIND_BACKGROUND
            )
            mark.format.setBackground(QColor(colour))
            out.append(mark)
        return out

    def reveal_position(self, position: int) -> bool:
        """접힌 토글 안에 있는 자리면 그 토글을 펴서 보이게 한다."""
        document = self.document()
        block = document.findBlock(max(0, min(int(position), document.characterCount() - 1)))
        if not block.isValid() or block.isVisible():
            return False
        opened = False
        for _ in range(64):
            if block.isVisible():
                break
            depth = self._block_indent(block)
            probe = block.previous()
            while probe.isValid():
                if self._is_toggle_block(probe) and self._block_indent(probe) < depth:
                    if not self._toggle_is_open(probe):
                        self.fold_toggle(probe)
                        opened = True
                    break
                depth = min(depth, self._block_indent(probe))
                probe = probe.previous()
            if not probe.isValid():
                break
            self._refresh_toggle_visibility()
            block = document.findBlock(block.position())
        return opened

    def go_to_match(self, start: int, end: int) -> None:
        """찾은 자리로 커서를 옮기고 화면에 들어오게 한다."""
        self.reveal_position(start)
        cursor = QTextCursor(self.document())
        cursor.setPosition(int(start))
        cursor.setPosition(int(end), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    # --------------------------------------------------------------- 토글 --
    @staticmethod
    def _is_toggle_block(block) -> bool:
        return block.isValid() and block.text().startswith(TOGGLE_PREFIXES)

    @staticmethod
    def _toggle_is_open(block) -> bool:
        return block.text().startswith(TOGGLE_OPEN_PREFIX)

    @staticmethod
    def _block_indent(block) -> int:
        return block.blockFormat().indent() if block.isValid() else 0

    def current_block_is_toggle(self) -> bool:
        return self._is_toggle_block(self.textCursor().block())

    def _toggle_children(self, block):
        """토글보다 한 칸이라도 더 들여쓴 다음 줄들이 그 토글의 내용이다."""
        depth = self._block_indent(block)
        child = block.next()
        while child.isValid() and self._block_indent(child) > depth:
            yield child
            child = child.next()

    def _lone_empty_child(self, block):
        """빈 토글의 안내가 들어앉을 자리.  자식이 빈 줄 하나뿐일 때만 있다."""
        children = list(self._toggle_children(block))
        if len(children) == 1 and not children[0].text().strip():
            return children[0]
        return None

    def _empty_toggle_blocks(self, blocks=None):
        """펼쳐져 있는데 안이 빈 토글과 그 빈 줄을 짝지어 돌려준다."""
        for block in (self._iter_blocks() if blocks is None else blocks):
            if block.isVisible() and self._is_toggle_block(block) and self._toggle_is_open(block):
                child = self._lone_empty_child(block)
                if child is not None and child.isVisible():
                    yield block, child

    def _ensure_toggle_children(self) -> None:
        """펼친 토글에는 늘 안쪽 줄이 하나 있게 한다.

        노션과 같은 자리다.  Enter 를 누르면 이 줄로 들어가고, 비어 있는 동안은
        그 자리에 안내를 그린다.  줄이 없으면 안내를 그릴 높이도 없다.
        """
        if self._syncing_toggle_children:
            return
        document = self.document()
        positions = []
        block = document.begin()
        while block.isValid():
            if self._is_toggle_block(block) and self._toggle_is_open(block):
                if next(self._toggle_children(block), None) is None:
                    positions.append(block.position())
            block = block.next()
        if not positions:
            return
        caret = self.textCursor().position()
        self._syncing_toggle_children = True
        try:
            # 뒤에서부터 넣어야 앞서 구한 위치가 밀리지 않는다.
            for position in reversed(positions):
                target = document.findBlock(position)
                if not target.isValid():
                    continue
                depth = self._block_indent(target) + 1
                insert_at = target.position() + target.length() - 1
                cursor = QTextCursor(target)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                self._open_clean_block(cursor, depth)
                if caret > insert_at:
                    caret += 1
        finally:
            self._syncing_toggle_children = False
        # 넣은 줄로 커서가 끌려가면 제목을 이어서 칠 수 없다.  있던 자리로 돌린다.
        restored = QTextCursor(document)
        restored.setPosition(max(0, min(caret, document.characterCount() - 1)))
        self.setTextCursor(restored)

    def make_toggle(self) -> None:
        """지금 줄을 토글로 만든다.  토글이면 되돌린다."""
        block = self.textCursor().block()
        if self._is_toggle_block(block):
            self._remove_toggle_prefix(block)
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.insertText(TOGGLE_OPEN_PREFIX)
        self.setFocus()

    # 줄 앞에서 이렇게 치면 그 기능이 된다.
    # (친 글, 뒤에 스페이스가 있어야 하는가, 편집기 메서드)
    # ">" 는 예전부터 따로 다루고 있어 여기 넣지 않았다.
    LEGACY_TYPING_RULES = (
        ("-", True, "toggle_bullet_list"),
        ("*", True, "toggle_bullet_list"),
        ("[]", True, "toggle_checklist"),
        ("[ ]", True, "toggle_checklist"),
        ("!", True, "make_callout"),
        ('"', True, "make_quote"),
        ("|", True, "make_quote"),
        ("---", False, "insert_divider"),
        ("```", False, "make_code_block"),
        ("[[", False, "insert_note_link"),
    )

    def _run_typing_rule(self, event, block, offset: int) -> bool:
        """줄 앞에 친 글이 규칙에 맞으면 친 글을 지우고 그 기능을 부른다.

        스페이스로 끝나는 규칙과 마지막 글자로 바로 끝나는 규칙 두 가지다.
        `---` 은 세 번째 `-` 를 치는 순간, `[[` 는 두 번째 `[` 를 치는 순간이다.
        """
        if self._is_toggle_block(block) or self._is_checklist_block(block):
            return False
        typed = block.text()[:offset]
        rules = self.insert_preferences.typing_rules()
        for pattern, needs_space, method in rules:
            handler = getattr(self, method, None)
            if not callable(handler):
                continue
            if needs_space:
                if event.key() != Qt.Key.Key_Space or typed != pattern:
                    continue
                eaten = len(pattern)
            else:
                if event.text() != pattern[-1] or typed != pattern[:-1]:
                    continue
                eaten = len(pattern) - 1
            wipe = QTextCursor(block)
            wipe.beginEditBlock()
            try:
                if eaten:
                    wipe.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    wipe.movePosition(
                        QTextCursor.MoveOperation.NextCharacter,
                        QTextCursor.MoveMode.KeepAnchor, eaten,
                    )
                    wipe.removeSelectedText()
                    self.setTextCursor(wipe)
                handler()
            finally:
                wipe.endEditBlock()
            return True
        return False

    def _selected_blocks(self):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = max(start, cursor.selectionEnd() - (1 if cursor.hasSelection() else 0))
        block = self.document().findBlock(start)
        last = self.document().findBlock(end)
        while block.isValid():
            yield block
            if block == last:
                break
            block = block.next()

    def apply_heading(self, level: int) -> None:
        """Apply one persisted line-level title style to every selected block."""
        if level not in HEADING_STYLES:
            return
        point_size, spacing, top, bottom = HEADING_STYLES[level]
        original = self.textCursor()
        transaction = QTextCursor(original)
        transaction.beginEditBlock()
        try:
            for block in list(self._selected_blocks()):
                block_cursor = QTextCursor(block)
                block_format = block.blockFormat()
                block_format.setTopMargin(top)
                block_format.setBottomMargin(bottom)
                block_format.setProperty(HEADING_LEVEL_PROPERTY, level)
                block_cursor.setBlockFormat(block_format)
                block_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                          QTextCursor.MoveMode.KeepAnchor)
                char_format = QTextCharFormat()
                char_format.setFontWeight(QFont.Weight.Bold)
                char_format.setFontPointSize(point_size)
                char_format.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
                char_format.setFontLetterSpacing(spacing)
                block_cursor.setCharFormat(char_format)
        finally:
            transaction.endEditBlock()
        self.setTextCursor(original)
        self.setFocus()

    def apply_heading1(self) -> None:
        self.apply_heading(1)

    def apply_heading2(self) -> None:
        self.apply_heading(2)

    def apply_heading3(self) -> None:
        self.apply_heading(3)

    def apply_heading4(self) -> None:
        self.apply_heading(4)

    def apply_body_style(self) -> None:
        original = self.textCursor()
        transaction = QTextCursor(original)
        transaction.beginEditBlock()
        try:
            for block in list(self._selected_blocks()):
                block_cursor = QTextCursor(block)
                block_format = block.blockFormat()
                block_format.setTopMargin(0)
                block_format.setBottomMargin(0)
                block_format.clearProperty(HEADING_LEVEL_PROPERTY)
                block_cursor.setBlockFormat(block_format)
                block_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                          QTextCursor.MoveMode.KeepAnchor)
                block_cursor.setCharFormat(QTextCharFormat())
        finally:
            transaction.endEditBlock()
        self.setTextCursor(original)
        self.setCurrentCharFormat(QTextCharFormat())
        self.setFocus()

    @staticmethod
    def heading_level(block) -> int:
        try:
            return int(block.blockFormat().property(HEADING_LEVEL_PROPERTY) or 0)
        except (TypeError, ValueError):
            return 0

    def _convert_to_toggle(self, block) -> None:
        """줄 맨 앞의 '>' 한 글자를 토글 표시로 바꾼다."""
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1
        )
        cursor.insertText(TOGGLE_OPEN_PREFIX)

    def _remove_toggle_prefix(self, block) -> None:
        if not self._is_toggle_block(block):
            return
        # 접힌 채로 표시만 지우면 내용이 영영 숨는다.  먼저 펼친다.
        if not self._toggle_is_open(block):
            self._set_toggle_open(block, True)
        # 토글을 되돌리는 자리에 빈 줄만 남기고 갈 이유가 없다.  같이 걷어낸다.
        self._syncing_toggle_children = True
        try:
            empty = self._lone_empty_child(block)
            if empty is not None:
                sweep = QTextCursor(block)
                sweep.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                sweep.setPosition(
                    empty.position() + empty.length() - 1, QTextCursor.MoveMode.KeepAnchor,
                )
                sweep.removeSelectedText()
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(
                QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 2
            )
            cursor.removeSelectedText()
        finally:
            self._syncing_toggle_children = False

    def _set_toggle_open(self, block, open_state: bool) -> None:
        if not self._is_toggle_block(block) or self._toggle_is_open(block) == open_state:
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(TOGGLE_OPEN_PREFIX[0] if open_state else TOGGLE_CLOSED_PREFIX[0])
        self._refresh_toggle_visibility()

    def fold_toggle(self, block) -> None:
        """▸ ↔ ▾.  접으면 안쪽 줄이 사라지고, 펼치면 돌아온다."""
        if not self._is_toggle_block(block):
            return
        folding = self._toggle_is_open(block)
        if folding:
            # 접는 자리에 커서가 있으면 숨은 줄에 갇힌다.  토글 줄로 데려온다.
            cursor = self.textCursor()
            for child in self._toggle_children(block):
                if child.contains(cursor.position()):
                    moved = QTextCursor(block)
                    moved.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                    self.setTextCursor(moved)
                    break
        self._set_toggle_open(block, not folding)

    def _refresh_toggle_visibility(self) -> None:
        """접힌 토글 아래를 숨긴다.  문서 전체를 한 번에 다시 계산한다."""
        document = self.document()
        hidden_depth = None
        changed = False
        block = document.begin()
        while block.isValid():
            indent = self._block_indent(block)
            if hidden_depth is not None and indent <= hidden_depth:
                hidden_depth = None
            visible = hidden_depth is None
            if block.isVisible() != visible:
                block.setVisible(visible)
                changed = True
            if visible and self._is_toggle_block(block) and not self._toggle_is_open(block):
                hidden_depth = indent
            block = block.next()
        if changed:
            document.markContentsDirty(0, max(1, document.characterCount()))
            self.viewport().update()

    def _shift_indent(self, block, amount: int) -> None:
        """Tab 으로 안으로, Shift+Tab 으로 밖으로.  들여쓰기가 곧 토글의 내용이다."""
        cursor = QTextCursor(block)
        fmt = block.blockFormat()
        fmt.setIndent(max(0, fmt.indent() + amount))
        cursor.setBlockFormat(fmt)
        self._refresh_toggle_visibility()

    # ------------------------------------------------------ 그림 크기 --
    def _image_fragments(self):
        """본문에 있는 그림과 그 자리."""
        for block in self._iter_blocks():
            if not block.isVisible():
                continue
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                iterator += 1
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    yield fragment

    def image_rect(self, fragment) -> QRectF:
        image = fragment.charFormat().toImageFormat()
        spot = QTextCursor(self.document())
        spot.setPosition(fragment.position())
        line = self.cursorRect(spot)
        return QRectF(line.left(), line.top(), image.width(), image.height())

    def image_grip_at(self, point):
        """오른쪽 아래 모서리를 잡았는지."""
        for fragment in self._image_fragments():
            rect = self.image_rect(fragment)
            grip = QRectF(
                rect.right() - IMAGE_GRIP, rect.bottom() - IMAGE_GRIP,
                IMAGE_GRIP * 1.5, IMAGE_GRIP * 1.5,
            )
            if grip.contains(QPointF(point)):
                return fragment
        return None

    def begin_image_resize(self, fragment) -> None:
        image = fragment.charFormat().toImageFormat()
        self._image_resize = {
            "at": fragment.position(),
            "width": float(image.width()),
            "height": float(image.height()),
        }

    def resize_image_to(self, width: float) -> bool:
        """끌어 놓은 폭으로 그림을 맞춘다.  가로세로 비율은 지킨다."""
        state = self._image_resize
        if state is None:
            return False
        ratio = state["height"] / max(1.0, state["width"])
        wanted = max(IMAGE_MIN_WIDTH, min(float(width), self._available_image_width()))
        cursor = QTextCursor(self.document())
        cursor.setPosition(state["at"])
        cursor.setPosition(state["at"] + 1, QTextCursor.MoveMode.KeepAnchor)
        image = cursor.charFormat().toImageFormat()
        if not image.isImageFormat():
            return False
        image.setWidth(wanted)
        image.setHeight(wanted * ratio)
        # 창을 줄였다 늘여도 직접 정한 크기를 지키도록 적어 둔다.
        image.setProperty(IMAGE_USER_WIDTH, wanted)
        cursor.setCharFormat(image)
        return True

    def finish_image_resize(self) -> None:
        self._image_resize = None
        self.viewport().unsetCursor()
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    # --------------------------------------------------- 줄 끌어 옮기기 --
    @staticmethod
    def block_cursor(block) -> QTextCursor:
        return QTextCursor(block)

    def block_at_gutter(self, y: int):
        """손잡이 칸의 세로 자리에 걸리는 줄."""
        for block in self._iter_blocks():
            if not block.isVisible():
                continue
            line = self.cursorRect(QTextCursor(block))
            if line.top() <= y <= line.bottom():
                return block
        return None

    def _block_family(self, block) -> list:
        """그 줄과, 토글이라면 그 안에 든 줄까지."""
        family = [block]
        if self._is_toggle_block(block):
            family.extend(self._toggle_children(block))
        return family

    def begin_line_drag(self, block) -> None:
        self._drag_source = block.position()
        self._drop_at = None
        self.viewport().update()

    def cancel_line_drag(self) -> None:
        if self._drag_source is None and self._drop_at is None:
            return
        self._drag_source = None
        self._drop_at = None
        self.viewport().update()

    def _drop_spot(self, point):
        """놓을 자리.  줄 한가운데면 그 안으로, 위아래면 그 사이로."""
        block = self.block_at_gutter(point.y())
        if block is None:
            last = self.document().lastBlock()
            return (last.position(), False) if last.isValid() else None
        line = self.cursorRect(QTextCursor(block))
        middle = line.height() / 3
        inside = (
            self._is_toggle_block(block) or self.page_id_of_block(block) is not None
        ) and line.top() + middle <= point.y() <= line.bottom() - middle
        return block.position(), inside

    def update_line_drag(self, point) -> None:
        if self._drag_source is None:
            return
        self._drop_at = self._drop_spot(point)
        self.viewport().update()

    def finish_line_drag(self, point) -> bool:
        source_at, self._drag_source = self._drag_source, None
        spot, self._drop_at = self._drop_spot(point), None
        self.viewport().update()
        if source_at is None or spot is None:
            return False
        target_at, inside = spot
        return self.move_line(source_at, target_at, inside)

    def move_line(self, source_at: int, target_at: int, inside: bool = False) -> bool:
        """줄 하나(토글이면 그 안까지)를 다른 자리로 옮긴다."""
        document = self.document()
        source = document.findBlock(source_at)
        target = document.findBlock(target_at)
        if not source.isValid() or not target.isValid():
            return False
        family = self._block_family(source)
        span = range(family[0].position(), family[-1].position() + family[-1].length())
        if target.position() in span:
            # 자기 자신이나 자기 안으로는 옮기지 않는다.
            return False
        page_id = self.page_id_of_block(target) if inside else None
        if page_id is not None:
            return self._move_line_into_page(family, page_id)
        depth = self._block_indent(target) + (1 if inside else 0)
        shift = depth - self._block_indent(source)
        cut = QTextCursor(document)
        cut.beginEditBlock()
        try:
            cut.setPosition(family[0].position())
            cut.setPosition(
                family[-1].position() + family[-1].length() - 1,
                QTextCursor.MoveMode.KeepAnchor,
            )
            fragment = cut.selection().toHtml()
            indents = [self._block_indent(item) + shift for item in family]
            self._remove_with_separator(cut, family)
            # 지운 뒤라 `family` 의 자리 값은 믿을 수 없다.  지우기 전에 잰
            # 범위로 셈한다.
            removed = span.stop - span.start
            landing = document.findBlock(
                target_at if target_at < span.start else target_at - removed
            )
            landing_at = landing.position()
            place = QTextCursor(landing)
            place.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            place.insertBlock()
            start = place.position()
            place.insertHtml(fragment)
            self._reindent_range(start, indents)
            if inside:
                # 토글 안내가 떠 있던 빈 줄은 이제 쓸모가 없다.  같이 걷어낸다.
                # 옮기면서 자리가 밀렸으므로 지금 자리로 다시 찾는다.
                self._drop_empty_placeholder(document.findBlock(landing_at))
        finally:
            cut.endEditBlock()
        self._refresh_toggle_visibility()
        return True

    def _drop_empty_placeholder(self, toggle) -> None:
        if not self._is_toggle_block(toggle):
            return
        children = list(self._toggle_children(toggle))
        if len(children) < 2:
            return
        for child in children:
            if child.text().strip():
                continue
            # 문서 맨 끝 줄은 뒤에 지울 구분자가 없다.  앞의 것을 지워야 한다.
            self._remove_with_separator(QTextCursor(self.document()), [child])
            return

    @staticmethod
    def _remove_with_separator(cursor, family) -> None:
        """옮긴 자리에 빈 줄이 남지 않도록 줄 구분자까지 함께 지운다."""
        document = cursor.document()
        start = family[0].position()
        end = family[-1].position() + family[-1].length() - 1
        if end < document.characterCount() - 1:
            end += 1
        elif start:
            start -= 1
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()

    def _reindent_range(self, start: int, indents) -> None:
        document = self.document()
        block = document.findBlock(start)
        for depth in indents:
            if not block.isValid():
                break
            cursor = QTextCursor(block)
            fmt = block.blockFormat()
            fmt.setIndent(max(0, depth))
            cursor.setBlockFormat(fmt)
            block = block.next()

    def _move_line_into_page(self, family, page_id: int) -> bool:
        """줄을 그 페이지 메모의 본문 끝으로 보낸다."""
        if self.store is None:
            return False
        row = self.store.note(page_id)
        if row is None:
            return False
        cut = QTextCursor(self.document())
        cut.setPosition(family[0].position())
        cut.setPosition(
            family[-1].position() + family[-1].length() - 1,
            QTextCursor.MoveMode.KeepAnchor,
        )
        moved = cut.selection().toHtml()
        carrier = QTextDocument()
        carrier.setHtml(str(row["content"] or ""))
        landing = QTextCursor(carrier)
        landing.movePosition(QTextCursor.MoveOperation.End)
        if carrier.characterCount() > 1:
            landing.insertBlock()
        landing.insertHtml(moved)
        self.store.update_note(page_id, content=carrier.toHtml())
        cut.beginEditBlock()
        try:
            self._remove_with_separator(cut, family)
        finally:
            cut.endEditBlock()
        self.page_renamed.emit(page_id)
        return True

    def _paint_drop_marker(self, painter: QPainter) -> None:
        if self._drop_at is None:
            return
        position, inside = self._drop_at
        block = self.document().findBlock(position)
        if not block.isValid():
            return
        line = self.cursorRect(QTextCursor(block))
        painter.save()
        colour = QColor(59, 84, 232)
        if inside:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(59, 84, 232, 34))
            painter.drawRoundedRect(
                QRectF(2, line.top(), self.viewport().width() - 4, line.height()),
                5.0, 5.0,
            )
        else:
            painter.setPen(QPen(colour, 2.0))
            painter.drawLine(QLineF(
                4.0, float(line.bottom()), float(self.viewport().width() - 4), float(line.bottom()),
            ))
        painter.restore()

    # ------------------------------------------------------- / 삽입 메뉴 --
    def _slash_query(self) -> tuple[int, str] | None:
        """커서 앞의 `/…` 를 찾는다.  없으면 None.

        낱말 한가운데의 `/`(주소나 날짜)는 메뉴를 열지 않는다.
        """
        cursor = self.textCursor()
        if cursor.hasSelection():
            return None
        block = cursor.block()
        offset = cursor.position() - block.position()
        text = block.text()[:offset]
        mark = text.rfind("/")
        if mark < 0:
            return None
        if mark and not text[mark - 1].isspace():
            return None
        query = text[mark + 1:]
        if any(character.isspace() for character in query):
            return None
        return block.position() + mark, query

    def _refresh_insert_popup(self) -> None:
        found = self._slash_query()
        if found is None:
            self.close_insert_popup()
            return
        _start, query = found
        matches = list(matching_items(self, query))
        if not matches:
            self.close_insert_popup()
            return
        popup = self._ensure_insert_popup()
        popup.clear()
        for item, handler in matches:
            entry = QListWidgetItem(item_label(item))
            entry.setToolTip(item_tooltip(item))
            entry.setData(Qt.ItemDataRole.UserRole, item[2])
            popup.addItem(entry)
        popup.setCurrentRow(0)
        # 스크롤을 내리지 않아도 다 보이게 항목 수만큼 편다.  줄 높이는 글꼴에
        # 따라 달라지므로 짐작하지 않고 위젯에 물어본다.
        row = max(popup.sizeHintForRow(0), self.INSERT_ROW_HEIGHT)
        popup.resize(240, row * popup.count() + popup.frameWidth() * 2 + 2)
        corner = self.viewport().mapToGlobal(self.cursorRect().bottomLeft())
        popup.move(corner.x(), corner.y() + 4)
        popup.show()

    def _ensure_insert_popup(self):
        if self._insert_popup is None:
            popup = QListWidget(self)
            popup.setObjectName("insertCommandPopup")
            popup.setWindowFlags(Qt.WindowType.Popup)
            popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            popup.itemClicked.connect(lambda item: self._run_insert_item(item))
            # 뜬 메뉴는 창 하나라서 키를 먼저 가져간다.  Enter·Esc·글자를 우리가
            # 받아 처리하지 않으면 편집기까지 오지 않는다.
            popup.installEventFilter(self)
            self._insert_popup = popup
        return self._insert_popup

    def insert_popup_visible(self) -> bool:
        return self._insert_popup is not None and self._insert_popup.isVisible()

    def close_insert_popup(self) -> bool:
        """메뉴를 닫는다.  열려 있었으면 True.  친 `/` 는 글자로 남는다."""
        if not self.insert_popup_visible():
            return False
        self._insert_popup.hide()
        return True

    def insert_popup_items(self) -> list[str]:
        if not self.insert_popup_visible():
            return []
        return [
            self._insert_popup.item(row).text()
            for row in range(self._insert_popup.count())
        ]

    def eventFilter(self, watched, event):
        if (
            self._insert_popup is not None
            and watched is self._insert_popup
            and event.type() == QEvent.Type.KeyPress
        ):
            key = event.key()
            if key in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
                self._move_insert_selection(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab}:
                self.run_selected_insert()
                return True
            if key == Qt.Key.Key_Escape:
                self.close_insert_popup()
                return True
            # 나머지 글자는 편집기로 넘겨, 치는 대로 목록이 좁혀지게 한다.
            self.keyPressEvent(event)
            return True
        return super().eventFilter(watched, event)

    def _move_insert_selection(self, step: int) -> None:
        popup = self._insert_popup
        if popup is None or not popup.count():
            return
        popup.setCurrentRow((popup.currentRow() + step) % popup.count())

    def run_selected_insert(self) -> bool:
        """메뉴에서 고른 것을 넣는다.  친 `/…` 는 지운다."""
        if not self.insert_popup_visible():
            return False
        return self._run_insert_item(self._insert_popup.currentItem())

    def _run_insert_item(self, entry) -> bool:
        if entry is None:
            return False
        method = str(entry.data(Qt.ItemDataRole.UserRole) or "")
        found = self._slash_query()
        self.close_insert_popup()
        if found is not None:
            start, query = found
            cursor = self.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(
                start + len(query) + 1, QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()
            self.setTextCursor(cursor)
        handler = getattr(self, method, None)
        if callable(handler):
            handler()
        return True

    # --------------------------------------------------- 강조 상자·구분선 --
    @staticmethod
    def is_callout_block(block) -> bool:
        return block.isValid() and block.text().startswith(CALLOUT_PREFIX)

    def current_block_is_callout(self) -> bool:
        return self.is_callout_block(self.textCursor().block())

    def make_callout(self) -> None:
        """지금 줄을 강조 상자로 만든다.  이미 상자면 되돌린다."""
        block = self.textCursor().block()
        cursor = QTextCursor(block)
        cursor.beginEditBlock()
        try:
            fmt = block.blockFormat()
            if self.is_callout_block(block):
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(
                    QTextCursor.MoveOperation.NextCharacter,
                    QTextCursor.MoveMode.KeepAnchor, len(CALLOUT_PREFIX),
                )
                cursor.removeSelectedText()
                fmt.clearBackground()
                fmt.setLeftMargin(0)
                fmt.setTopMargin(0)
                fmt.setBottomMargin(0)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.insertText(CALLOUT_PREFIX)
                fmt.setBackground(QColor(CALLOUT_BACKGROUND))
                fmt.setLeftMargin(10)
                fmt.setTopMargin(5)
                fmt.setBottomMargin(5)
            cursor.setBlockFormat(fmt)
        finally:
            cursor.endEditBlock()
        self.setFocus()

    # ------------------------------------------------------ 인용문 · 코드 --
    @staticmethod
    def is_quote_block(block) -> bool:
        return block.isValid() and block.text().startswith(QUOTE_PREFIX)

    @staticmethod
    def is_code_block(block) -> bool:
        return block.isValid() and block.text().startswith(CODE_PREFIX)

    def current_block_is_quote(self) -> bool:
        return self.is_quote_block(self.textCursor().block())

    def current_block_is_code(self) -> bool:
        return self.is_code_block(self.textCursor().block())

    def _restyle_block(self, block, char_format) -> None:
        """줄 전체의 글자 서식을 바꾼다.  표시 글자까지 함께 바꾼다."""
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.setCharFormat(char_format)

    def _drop_line_prefix(self, block, prefix: str) -> None:
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor, len(prefix),
        )
        cursor.removeSelectedText()

    def make_quote(self) -> None:
        """지금 줄을 인용문으로 만든다.  이미 인용문이면 되돌린다."""
        block = self.textCursor().block()
        cursor = QTextCursor(block)
        cursor.beginEditBlock()
        try:
            fmt = block.blockFormat()
            if self.is_quote_block(block):
                self._drop_line_prefix(block, QUOTE_PREFIX)
                fmt.setLeftMargin(0)
                self._restyle_block(self.textCursor().block(), QTextCharFormat())
            else:
                if self.is_code_block(block):
                    self._drop_line_prefix(block, CODE_PREFIX)
                    fmt.clearBackground()
                    fmt.setTopMargin(0)
                    fmt.setBottomMargin(0)
                start = QTextCursor(self.textCursor().block())
                start.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                start.insertText(QUOTE_PREFIX)
                fmt.setLeftMargin(QUOTE_MARGIN)
                quoted = QTextCharFormat()
                quoted.setFontItalic(True)
                quoted.setForeground(QColor(QUOTE_COLOR))
                self._restyle_block(self.textCursor().block(), quoted)
            cursor = QTextCursor(self.textCursor().block())
            cursor.setBlockFormat(fmt)
        finally:
            cursor.endEditBlock()
        self.setFocus()

    def make_code_block(self) -> None:
        """지금 줄을 코드 줄로 만든다.  이미 코드 줄이면 되돌린다."""
        block = self.textCursor().block()
        cursor = QTextCursor(block)
        cursor.beginEditBlock()
        try:
            fmt = block.blockFormat()
            if self.is_code_block(block):
                self._drop_line_prefix(block, CODE_PREFIX)
                fmt.clearBackground()
                fmt.setLeftMargin(0)
                fmt.setTopMargin(0)
                fmt.setBottomMargin(0)
                self._restyle_block(self.textCursor().block(), QTextCharFormat())
            else:
                if self.is_quote_block(block):
                    self._drop_line_prefix(block, QUOTE_PREFIX)
                start = QTextCursor(self.textCursor().block())
                start.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                start.insertText(CODE_PREFIX)
                fmt.setBackground(QColor(CODE_BACKGROUND))
                fmt.setLeftMargin(10)
                # 여러 줄을 이어 쓸 때 사이가 벌어지면 한 덩어리로 안 보인다.
                fmt.setTopMargin(0)
                fmt.setBottomMargin(0)
                self._restyle_block(self.textCursor().block(), self.code_char_format())
            cursor = QTextCursor(self.textCursor().block())
            cursor.setBlockFormat(fmt)
        finally:
            cursor.endEditBlock()
        self.setFocus()

    @staticmethod
    def code_char_format() -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFontFamilies([CODE_FONT_FAMILY, "D2Coding", "Courier New", "monospace"])
        fmt.setForeground(QColor("#0f172a"))
        return fmt

    def _paint_quote_bars(self, painter: QPainter, viewport_rect) -> None:
        """인용문 왼쪽에 세로줄을 긋는다.  문서에는 넣지 않는다."""
        painter.save()
        painter.setPen(QPen(QColor(QUOTE_BAR_COLOR), 3.0))
        for block in self._visible_blocks():
            if not block.isVisible() or not self.is_quote_block(block):
                continue
            line = self.cursorRect(QTextCursor(block))
            if line.bottom() < viewport_rect.top() or line.top() > viewport_rect.bottom():
                continue
            left = line.left() - QUOTE_MARGIN + 4
            painter.drawLine(QLineF(left, line.top() + 1.0, left, line.bottom() - 1.0))
        painter.restore()

    # ------------------------------------------------------------------ 표 --
    def insert_table(self, rows: int = TABLE_ROWS, columns: int = TABLE_COLUMNS) -> None:
        """커서 자리에 표를 넣는다.  첫 줄은 머리줄이다."""
        cursor = self.textCursor()
        cursor.beginEditBlock()
        try:
            fmt = QTextTableFormat()
            fmt.setBorder(1)
            fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
            fmt.setBorderBrush(QColor(TABLE_BORDER_COLOR))
            fmt.setBorderCollapse(True)
            fmt.setCellPadding(4)
            fmt.setCellSpacing(0)
            fmt.setHeaderRowCount(1)
            fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
            table = cursor.insertTable(max(1, int(rows)), max(1, int(columns)), fmt)
            header = QTextCharFormat()
            header.setFontWeight(QFont.Weight.Bold)
            for column in range(table.columns()):
                cell = table.cellAt(0, column)
                # 빈 칸에는 글자 서식이 붙지 않는다.  줄의 기본 서식으로 걸어야
                # 나중에 치는 글자가 굵게 나온다.
                cell.firstCursorPosition().setBlockCharFormat(header)
                # 칸 바탕은 QTextTableCellFormat 으로만 붙는다.  보통
                # QTextCharFormat 으로 넣으면 조용히 사라진다.  그리고 칸 안쪽
                # 글자 서식을 나중에 건드리면 이 바탕까지 함께 지워지므로,
                # 칸 서식은 반드시 맨 마지막에 건다.
                cell_format = cell.format().toTableCellFormat()
                cell_format.setBackground(QColor(TABLE_HEADER_BACKGROUND))
                cell.setFormat(cell_format)
            first = table.cellAt(0, 0).firstCursorPosition()
            self.setTextCursor(first)
        finally:
            cursor.endEditBlock()
        self.setFocus()

    def current_table(self):
        return self.textCursor().currentTable()

    def current_block_is_table(self) -> bool:
        return self.current_table() is not None

    def _cell_of(self, table, cursor):
        return table.cellAt(cursor)

    def step_table_cell(self, forward: bool = True) -> bool:
        """Tab 으로 다음 칸.  마지막 칸에서 Tab 이면 줄을 하나 늘린다."""
        table = self.current_table()
        if table is None:
            return False
        cursor = self.textCursor()
        cell = table.cellAt(cursor)
        if not cell.isValid():
            return False
        row, column = cell.row(), cell.column()
        if forward:
            column += 1
            if column >= table.columns():
                column = 0
                row += 1
            if row >= table.rows():
                table.appendRows(1)
        else:
            column -= 1
            if column < 0:
                column = table.columns() - 1
                row -= 1
            if row < 0:
                return True
        target = table.cellAt(row, column)
        if not target.isValid():
            return True
        self.setTextCursor(target.firstCursorPosition())
        return True

    def add_table_row(self) -> bool:
        table = self.current_table()
        if table is None:
            return False
        cell = table.cellAt(self.textCursor())
        table.insertRows(cell.row() + 1 if cell.isValid() else table.rows(), 1)
        return True

    def add_table_column(self) -> bool:
        table = self.current_table()
        if table is None:
            return False
        cell = table.cellAt(self.textCursor())
        table.insertColumns(cell.column() + 1 if cell.isValid() else table.columns(), 1)
        return True

    @staticmethod
    def is_divider_block(block) -> bool:
        return block.isValid() and block.text() == DIVIDER_TEXT

    def insert_divider(self) -> None:
        """가로줄 한 줄.  글자는 감추고 그 자리에 선을 그린다."""
        cursor = self.textCursor()
        cursor.beginEditBlock()
        try:
            if cursor.block().text().strip():
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                self._open_clean_block(cursor)
            else:
                cursor.setBlockFormat(QTextBlockFormat())
                cursor.setCharFormat(QTextCharFormat())
            cursor.insertText(DIVIDER_TEXT)
            self._open_clean_block(cursor)
        finally:
            cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.setCurrentCharFormat(QTextCharFormat())
        self.setFocus()

    def _divider_line(self, block) -> QLineF:
        rect = self.cursorRect(QTextCursor(block))
        middle = rect.top() + max(rect.height(), self.fontMetrics().height()) / 2
        return QLineF(8.0, middle, float(self.viewport().width() - 8), middle)

    # ----------------------------------------------------- 전부 접기·펼치기 --
    def toggle_all_folds(self) -> bool:
        """모든 토글을 한 번에 접거나 편다.  하나라도 펼쳐져 있으면 접는다."""
        blocks = [
            block for block in self._iter_blocks() if self._is_toggle_block(block)
        ]
        if not blocks:
            return False
        opening = not any(self._toggle_is_open(block) for block in blocks)
        for block in blocks:
            if self._toggle_is_open(block) != opening:
                self._set_toggle_open(block, opening)
        self._refresh_toggle_visibility()
        return opening

    def _iter_blocks(self):
        block = self.document().begin()
        while block.isValid():
            yield block
            block = block.next()

    # 화면 밖 줄은 그려지지도, 칠해지지도 않는다.  긴 메모에서 문서 전체를
    # 훑는 대신 보이는 자리 앞뒤로 이만큼만 본다.
    VISIBLE_MARGIN = 40

    def _visible_blocks(self):
        """지금 화면에 보이는 줄과 그 앞뒤 여유분.

        3000줄짜리 메모에서도 백 줄 남짓만 돈다.  아직 자리를 못 잡은 위젯
        (검사나 화면 밖)에서는 문서 전체를 돌려주어 예전과 같이 움직인다.
        """
        document = self.document()
        height = self.viewport().height()
        if height <= 0 or not self.isVisible():
            yield from self._iter_blocks()
            return
        first = self.cursorForPosition(QPoint(0, 0)).block()
        last = self.cursorForPosition(QPoint(0, height)).block()
        if not first.isValid() or not last.isValid():
            yield from self._iter_blocks()
            return
        start = max(0, first.blockNumber() - self.VISIBLE_MARGIN)
        stop = min(document.blockCount() - 1, last.blockNumber() + self.VISIBLE_MARGIN)
        block = document.findBlockByNumber(start)
        while block.isValid():
            yield block
            if block.blockNumber() >= stop:
                return
            block = block.next()

    # ------------------------------------------------------------- 페이지 --
    @staticmethod
    def page_id_at(anchor: str) -> int | None:
        match = _PAGE_ID_RE.fullmatch(str(anchor or "").strip())
        return int(match.group(1)) if match is not None else None

    def insert_note_link(self) -> bool:
        """이미 있는 메모를 가리키는 링크를 넣는다.  새 메모를 만들지 않는다."""
        if self.store is None:
            return False
        dialog = NoteLinkDialog(self.store, self.note_id, self)
        if dialog.exec() != NoteLinkDialog.DialogCode.Accepted:
            return False
        note_id, title = dialog.chosen_id(), dialog.chosen_title()
        if note_id is None:
            return False
        cursor = self.textCursor()
        self._write_link_run(cursor, note_id, title or DEFAULT_PAGE_TITLE)
        self.setTextCursor(cursor)
        self.setCurrentCharFormat(QTextCharFormat())
        self.setFocus()
        return True

    def _write_link_run(self, cursor, note_id: int, title: str) -> None:
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(f"{PAGE_URL_PREFIX}{int(note_id)}")
        fmt.setForeground(QColor("#2438b8"))
        fmt.setFontUnderline(True)
        cursor.insertText(f"{LINK_MARK}{title}", fmt)
        # 링크 뒤에 이어 치는 글까지 링크가 되지 않게 맨 서식으로 끊는다.
        cursor.insertText(" ", QTextCharFormat())

    def _refresh_note_links(self) -> None:
        """링크 글자를 그 메모의 지금 제목으로 맞춘다.

        가리키기만 하므로 메모가 사라졌으면 "지운 메모" 로 적는다.  페이지와
        달리 이 줄을 지워도 메모는 손대지 않는다.
        """
        if self.store is None:
            return
        blocked = self.blockSignals(True)
        try:
            for block in self._iter_blocks():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    iterator += 1
                    if not fragment.isValid():
                        continue
                    text = fragment.text()
                    if not text.startswith(LINK_MARK):
                        continue
                    note_id = self.page_id_at(fragment.charFormat().anchorHref())
                    if note_id is None:
                        continue
                    row = self.store.note(note_id)
                    title = str(row["title"]) if row is not None else "지운 메모"
                    wanted = f"{LINK_MARK}{title}"
                    if text == wanted:
                        continue
                    cursor = QTextCursor(self.document())
                    cursor.setPosition(fragment.position())
                    cursor.setPosition(
                        fragment.position() + fragment.length(),
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                    cursor.removeSelectedText()
                    cursor.insertText(wanted, fragment.charFormat())
                    break
        finally:
            self.blockSignals(blocked)

    def insert_page_link(self) -> bool:
        """메모 안에 하위 메모를 만들고, 그 자리에 여는 줄을 남긴다.

        줄에는 📄 표시만 넣고 커서를 그 뒤에 둔다.  이어서 치는 글이 곧 그
        페이지의 제목이 된다.
        """
        if self.store is None or self.note_id is None:
            QMessageBox.information(
                self, "페이지 추가", "메모를 먼저 저장한 뒤 페이지를 넣어 주세요.",
            )
            return False
        # 본문 안에만 사는 페이지다.  메모 목록에는 내놓지 않는다.
        page_id = self.store.create_child_note(
            self.note_id, DEFAULT_PAGE_TITLE, embedded=True,
        )
        cursor = self.textCursor()
        if cursor.block().text().strip():
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            self._open_clean_block(cursor)
        else:
            cursor.setBlockFormat(QTextBlockFormat())
        self._write_page_link(cursor, page_id, "")
        self.setTextCursor(cursor)
        self._refresh_known_pages()
        self.page_created.emit(page_id)
        self.setFocus()
        return True

    @staticmethod
    def _open_clean_block(cursor, indent: int = 0) -> None:
        """다음 줄을 맨 서식으로 연다.

        그러지 않으면 강조 상자의 노란 배경과 여백이 뒤따르는 줄, 구분선,
        페이지 줄, 그림까지 물들인다.
        """
        cursor.insertBlock()
        fmt = QTextBlockFormat()
        fmt.setIndent(max(0, indent))
        cursor.setBlockFormat(fmt)
        cursor.setCharFormat(QTextCharFormat())

    def _finish_page_line(self, block) -> None:
        """페이지 줄에서 Enter.  제목을 갈무리하고 아래에 맨 줄을 편다."""
        self.sync_page_titles()
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self._open_clean_block(cursor)
        self.setTextCursor(cursor)
        self.setCurrentCharFormat(QTextCharFormat())

    def current_page_titles(self) -> dict[int, str]:
        """본문에 지금 있는 페이지 줄과 거기 적힌 이름."""
        found: dict[int, str] = {}
        block = self.document().begin()
        while block.isValid():
            page_id = self.page_id_of_block(block)
            if page_id is not None:
                found[page_id] = block.text()[len(PAGE_MARK):].strip()
            block = block.next()
        return found

    def _refresh_known_pages(self) -> None:
        self._page_sync_timer.stop()
        self._known_pages = set(self.current_page_titles())

    def _queue_page_sync(self) -> None:
        if self.store is not None and self.note_id is not None:
            self._page_sync_timer.start()

    def sync_page_titles(self) -> None:
        """본문 줄을 참으로 삼아 페이지 제목과 살아 있음 여부를 맞춘다.

        줄에 친 글이 그 페이지의 제목이 되고, 줄을 지우면 페이지도 휴지통으로
        간다.  되돌리기로 줄이 살아나면 페이지도 휴지통에서 꺼낸다.
        """
        if self.store is None or self.note_id is None:
            return
        current = self.current_page_titles()
        for page_id in self._known_pages - set(current):
            if self.store.note(page_id) is not None:
                self.store.delete_note(page_id)
                self.page_removed.emit(page_id)
        for page_id, typed in current.items():
            row = self.store.note(page_id)
            if row is None:
                self.store.restore_note(page_id)
                row = self.store.note(page_id)
                if row is None:
                    continue
            title = typed or DEFAULT_PAGE_TITLE
            if str(row["title"]) != title:
                self.store.update_note(page_id, title=title)
                self.page_renamed.emit(page_id)
        self._known_pages = set(current)

    def _write_page_link(self, cursor, page_id: int, title: str) -> None:
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(f"{PAGE_URL_PREFIX}{int(page_id)}")
        fmt.setForeground(QColor("#2438b8"))
        fmt.setFontUnderline(True)
        cursor.insertText(f"{PAGE_MARK}{title}", fmt)

    def page_id_of_block(self, block) -> int | None:
        """이 줄이 페이지 줄이면 그 메모 번호.

        줄 첫 글자의 서식으로 가린다.  이어서 친 평범한 글이 앞줄의 서식을
        물려받았더라도 페이지로 잘못 읽지 않도록 📄 로 시작하는 줄만 본다.
        """
        if not block.isValid() or not block.text().startswith(PAGE_MARK):
            return None
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor,
        )
        return self.page_id_at(cursor.charFormat().anchorHref())

    def _refresh_page_links(self) -> None:
        """페이지 줄의 글자를 그 메모의 지금 제목으로 맞춘다.

        제목을 고쳐도 본문에 옛 이름이 남지 않는다.
        """
        if self.store is None:
            return
        document = self.document()
        blocked = self.blockSignals(True)
        try:
            block = document.begin()
            while block.isValid():
                page_id = self.page_id_of_block(block)
                if page_id is not None:
                    row = self.store.note(page_id)
                    title = str(row["title"]) if row is not None else "지운 페이지"
                    wanted = f"{PAGE_MARK}{title}"
                    if block.text() != wanted:
                        cursor = QTextCursor(block)
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                        cursor.movePosition(
                            QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                        cursor.removeSelectedText()
                        self._write_page_link(cursor, page_id, title)
                block = block.next()
        finally:
            self.blockSignals(blocked)

    def _page_link_at(self, point) -> int | None:
        return self.page_id_at(self.anchorAt(point.toPoint()))

    def _toggle_marker_rect(self, block) -> QRectF:
        cursor = QTextCursor(block)
        glyph = self.cursorRect(cursor)
        size = 22.0
        return QRectF(glyph.left() - 3, glyph.top(), size, max(glyph.height(), size))

    def _toggle_block_at(self, point):
        block = self.document().begin()
        while block.isValid():
            if block.isVisible() and self._is_toggle_block(block):
                if self._toggle_marker_rect(block).contains(point):
                    return block
            block = block.next()
        return None

    # ------------------------------------------------------- 마우스 올림 --
    def _marker_block_at(self, point):
        """마우스 밑에 눌러서 동작하는 표시가 있으면 그 줄을 돌려준다."""
        return self._toggle_block_at(point) or self._checklist_block_at(point)

    def _hover_marker_rect(self) -> QRectF | None:
        if self._hover_marker is None:
            return None
        block = self.document().findBlock(self._hover_marker)
        if not block.isValid() or not block.isVisible():
            return None
        if self._is_toggle_block(block):
            # 누르는 자리는 넉넉해야 하지만, 그려지는 사각형까지 제목을 덮으면
            # 글자가 가려진다.  표시 글자에 맞춰 좁혀서 그린다.
            return self._toggle_marker_rect(block).adjusted(0, 1, -5, -2)
        if self._is_checklist_block(block):
            return self._checkbox_rect(block, hit_target=True).adjusted(3, 3, -3, -3)
        return None

    def _set_hover_marker(self, block) -> None:
        position = block.position() if block is not None else None
        # 표준 손가락 커서라서 배율이 달라져도 흐려지지 않는다.
        shape = (
            Qt.CursorShape.PointingHandCursor if block is not None
            else Qt.CursorShape.IBeamCursor
        )
        if self.viewport().cursor().shape() != shape:
            self.viewport().setCursor(shape)
        if position != self._hover_marker:
            self._hover_marker = position
            self.viewport().update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._image_resize is not None and event.buttons() & Qt.MouseButton.LeftButton:
            rect_left = self.image_rect_left(self._image_resize["at"])
            self.resize_image_to(event.position().x() - rect_left)
            event.accept()
            return
        super().mouseMoveEvent(event)
        if event.buttons() != Qt.MouseButton.NoButton:
            return
        if self.image_grip_at(event.position()) is not None:
            if self.viewport().cursor().shape() != Qt.CursorShape.SizeFDiagCursor:
                self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
            return
        block = self._marker_block_at(event.position())
        self._set_hover_marker(block)
        if block is None and self._page_link_at(event.position()) is not None:
            # 페이지 줄도 눌러서 여는 자리다.
            if self.viewport().cursor().shape() != Qt.CursorShape.PointingHandCursor:
                self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def leaveEvent(self, event) -> None:
        self._set_hover_marker(None)
        super().leaveEvent(event)

    def _checkbox_rect(self, block, hit_target: bool = False) -> QRectF:
        cursor = QTextCursor(block)
        glyph = self.cursorRect(cursor)
        size = 24.0 if hit_target else 15.0
        center_x = glyph.left() + 7.5
        center_y = glyph.top() + max(glyph.height(), self.fontMetrics().height()) / 2
        return QRectF(center_x - size / 2, center_y - size / 2, size, size)

    def _checklist_block_at(self, point):
        matches = []
        block = self.document().begin()
        while block.isValid():
            if self._is_checklist_block(block):
                rect = self._checkbox_rect(block, hit_target=True)
                if rect.contains(point):
                    matches.append((abs(rect.center().y() - point.y()), block))
            block = block.next()
        return min(matches, key=lambda item: item[0])[1] if matches else None

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        viewport_rect = self.viewport().rect()
        # 마우스가 올라온 표시 뒤에 옅은 사각형을 깔아, 어디를 눌러야 하는지 보인다.
        hover = self._hover_marker_rect()
        if hover is not None and hover.intersects(QRectF(viewport_rect)):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(59, 84, 232, 30))
            painter.drawRoundedRect(hover, 5.0, 5.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        self._paint_empty_toggle_hints(painter, viewport_rect)
        self._paint_dividers(painter, viewport_rect)
        self._paint_quote_bars(painter, viewport_rect)
        self._paint_drop_marker(painter)
        for block in self._visible_blocks():
            text = block.text()
            if text.startswith((UNCHECKED_PREFIX, CHECKED_PREFIX)):
                rect = self._checkbox_rect(block)
                if rect.bottom() >= viewport_rect.top() and rect.top() <= viewport_rect.bottom():
                    colour = QColor("#64748b")
                    painter.setPen(QPen(colour, 1.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(rect, 3.5, 3.5)
                    if text.startswith(CHECKED_PREFIX):
                        check_pen = QPen(QColor("#172033"), 2.0)
                        check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                        painter.setPen(check_pen)
                        painter.drawLine(QLineF(
                            rect.left() + 3.5, rect.center().y(),
                            rect.left() + 6.5, rect.bottom() - 3.5,
                        ))
                        painter.drawLine(QLineF(
                            rect.left() + 6.5, rect.bottom() - 3.5,
                            rect.right() - 3.0, rect.top() + 3.5,
                        ))
        painter.end()

    def _paint_dividers(self, painter: QPainter, viewport_rect) -> None:
        """구분선 줄 자리에 가로줄을 그린다."""
        painter.save()
        pen = QPen(QColor(DIVIDER_COLOR), 1.2)
        painter.setPen(pen)
        for block in self._visible_blocks():
            if not block.isVisible() or not self.is_divider_block(block):
                continue
            line = self._divider_line(block)
            if line.y1() < viewport_rect.top() - 4 or line.y1() > viewport_rect.bottom() + 4:
                continue
            painter.drawLine(line)
        painter.restore()

    def _paint_empty_toggle_hints(self, painter: QPainter, viewport_rect) -> None:
        """빈 토글 안쪽에 회색 안내를 그린다.  문서에는 넣지 않는다."""
        painter.save()
        painter.setFont(self.document().defaultFont())
        painter.setPen(QColor("#94a3b8"))
        metrics = QFontMetricsF(painter.font())
        for _toggle, child in self._empty_toggle_blocks(self._visible_blocks()):
            line = self.cursorRect(QTextCursor(child))
            if line.bottom() < viewport_rect.top() or line.top() > viewport_rect.bottom():
                continue
            available = self.viewport().width() - line.left() - 12
            if available < 40:
                continue
            # 한 줄에 담기지 않으면 줄여서 그린다.  다음 줄을 덮으면 안 된다.
            text = metrics.elidedText(EMPTY_TOGGLE_HINT, Qt.TextElideMode.ElideRight, available)
            painter.drawText(
                QRectF(line.left(), line.top(), available, max(float(line.height()), metrics.height())),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                text,
            )
        painter.restore()

    def choose_and_insert_image(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self, "이미지 삽입", "", "이미지 (*.png *.jpg *.jpeg *.webp)",
        )
        return bool(path and self.insert_image_file(Path(path)))

    def insert_image_file(self, path: Path) -> bool:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            QMessageBox.warning(self, "이미지 삽입 실패", "PNG, JPEG 또는 WebP 이미지를 선택해 주세요.")
            return False
        return self.insert_image(image, path.suffix.casefold())

    def insert_image(self, image: QImage, source_suffix: str = ".png") -> bool:
        if self.store is None or self.note_id is None:
            QMessageBox.information(self, "이미지 삽입", "메모를 먼저 저장한 뒤 이미지를 삽입해 주세요.")
            return False
        prepared = image
        if max(image.width(), image.height()) > MAX_IMAGE_EDGE:
            prepared = image.scaled(
                MAX_IMAGE_EDGE, MAX_IMAGE_EDGE, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        has_alpha = prepared.hasAlphaChannel()
        fmt_name = b"PNG" if has_alpha or source_suffix == ".png" else b"JPEG"
        mime_type = "image/png" if fmt_name == b"PNG" else "image/jpeg"
        encoded = self._encode_image(prepared, fmt_name)
        if len(encoded) > MAX_IMAGE_BYTES:
            QMessageBox.warning(self, "이미지 삽입 실패", "압축 후 이미지 크기가 8MB를 초과합니다.")
            return False
        attachment_id = self.store.add_attachment(
            self.note_id, mime_type, base64.b64encode(encoded).decode("ascii"),
            prepared.width(), prepared.height(),
        )
        url = QUrl(f"{IMAGE_URL_PREFIX}attachment/{attachment_id}")
        self.document().addResource(QTextDocument.ResourceType.ImageResource, url, prepared)
        image_format = QTextImageFormat()
        image_format.setName(url.toString())
        image_format.setProperty(IMAGE_ORIGINAL_WIDTH, prepared.width())
        image_format.setProperty(IMAGE_ORIGINAL_HEIGHT, prepared.height())
        width = min(float(prepared.width()), self._available_image_width())
        image_format.setWidth(width)
        image_format.setHeight(width * prepared.height() / max(1, prepared.width()))
        cursor = self.textCursor()
        cursor.insertImage(image_format)
        self.setTextCursor(cursor)
        return True

    @staticmethod
    def _encode_image(image: QImage, fmt_name: bytes) -> bytes:
        payload = QByteArray()
        buffer = QBuffer(payload)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        quality = 88 if fmt_name == b"JPEG" else -1
        image.save(buffer, fmt_name.decode("ascii"), quality)
        buffer.close()
        return bytes(payload)

    def insertFromMimeData(self, source: QMimeData) -> None:
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and self.insert_image(image):
                return
        for url in source.urls() if source.hasUrls() else []:
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}:
                if self.insert_image_file(Path(url.toLocalFile())):
                    return
        if source.hasHtml():
            self.textCursor().insertHtml(sanitize_rich_html(source.html()))
            return
        super().insertFromMimeData(source)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.insert_popup_visible():
            # 메뉴가 떠 있는 동안은 위아래·Enter·Esc 를 메뉴가 먼저 쓴다.
            if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
                self._move_insert_selection(1 if event.key() == Qt.Key.Key_Down else -1)
                return
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab}:
                if self.run_selected_insert():
                    return
            if event.key() == Qt.Key.Key_Escape:
                self.close_insert_popup()
                return
        if event.key() == Qt.Key.Key_V and event.modifiers() == (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            self.paste_as_plain_text()
            return
        cursor = self.textCursor()
        block = cursor.block()
        checklist = self._is_checklist_block(block)
        toggle = self._is_toggle_block(block)
        offset = cursor.position() - block.position()
        if not cursor.hasSelection():
            if event.key() == Qt.Key.Key_Space and offset == 1 and block.text() == ">":
                # 노션과 같은 입력: "> " 를 치면 토글이 된다.
                self._convert_to_toggle(block)
                return
            if self._run_typing_rule(event, block, offset):
                return
            if event.key() == Qt.Key.Key_Tab and self.step_table_cell(True):
                # 표 안에서 Tab 은 다음 칸이다.  들여쓰기보다 먼저다.
                return
            if event.key() == Qt.Key.Key_Backtab and self.step_table_cell(False):
                return
            if event.key() == Qt.Key.Key_Tab and offset == 0 and self._block_indent(block) < 8:
                self._shift_indent(block, 1)
                return
            if event.key() == Qt.Key.Key_Backtab:
                self._shift_indent(block, -1)
                return
        if not cursor.hasSelection() and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if self.heading_level(block):
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                self._open_clean_block(cursor)
                self.setTextCursor(cursor)
                self.setCurrentCharFormat(QTextCharFormat())
                return
            if self.page_id_of_block(block) is not None:
                self._finish_page_line(block)
                return
            if self.is_code_block(block):
                if not block.text()[len(CODE_PREFIX):].strip():
                    # 빈 코드 줄에서 Enter 를 누르면 코드에서 빠져나온다.
                    self._drop_line_prefix(block, CODE_PREFIX)
                    plain = QTextBlockFormat()
                    plain.setIndent(self._block_indent(block))
                    inner = QTextCursor(self.textCursor().block())
                    inner.setBlockFormat(plain)
                    self._restyle_block(self.textCursor().block(), QTextCharFormat())
                    self.setCurrentCharFormat(QTextCharFormat())
                    return
                # 코드는 여러 줄인 일이 많다.  Enter 로 다음 코드 줄을 연다.
                fmt = block.blockFormat()
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                cursor.insertBlock(fmt)
                cursor.insertText(CODE_PREFIX)
                self.setTextCursor(cursor)
                self.setCurrentCharFormat(self.code_char_format())
                return
            if self.is_quote_block(block) or self.is_callout_block(block):
                # 강조 상자는 한 줄짜리다.  Enter 로 나오면 배경과 여백이 다음
                # 줄까지 따라붙지 않도록 맨 줄 서식으로 시작한다.
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                self._open_clean_block(cursor)
                self.setTextCursor(cursor)
                self.setCurrentCharFormat(QTextCharFormat())
                return
        if toggle and not cursor.hasSelection():
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                if not block.text()[2:].strip():
                    self._remove_toggle_prefix(block)
                    return
                waiting = self._lone_empty_child(block) if cursor.atBlockEnd() else None
                if waiting is not None:
                    # 안내가 떠 있던 빈 줄이 곧 첫 내용 줄이다.  줄을 또 만들지 않는다.
                    moved = QTextCursor(waiting)
                    moved.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                    self.setTextCursor(moved)
                    return
                depth = self._block_indent(block)
                super().keyPressEvent(event)
                # 토글에서 Enter 를 누르면 그 안쪽으로 들어간다.
                self._shift_indent(self.textCursor().block(), depth + 1 - self._block_indent(self.textCursor().block()))
                return
            if event.key() == Qt.Key.Key_Backspace and offset <= 2:
                self._remove_toggle_prefix(block)
                return
            if event.key() == Qt.Key.Key_Space and offset <= 1:
                self.fold_toggle(block)
                return
        if not cursor.hasSelection() and event.key() == Qt.Key.Key_Backspace and offset <= 2:
            if self.is_quote_block(block):
                self.make_quote()
                return
            if self.is_code_block(block):
                self.make_code_block()
                return
        if checklist and not cursor.hasSelection():
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                if not block.text()[2:].strip():
                    self._remove_checklist_prefix(block)
                    return
                fmt = self.currentCharFormat()
                fmt.setFontStrikeOut(False)
                super().keyPressEvent(event)
                self.setCurrentCharFormat(fmt)
                self.textCursor().insertText(UNCHECKED_PREFIX)
                return
            if event.key() == Qt.Key.Key_Backspace and offset <= 2:
                self._remove_checklist_prefix(block)
                return
            if event.key() == Qt.Key.Key_Delete and offset <= 1:
                self._remove_checklist_prefix(block)
                return
            if event.key() == Qt.Key.Key_Space and offset <= 1:
                self._toggle_check_state(block)
                return
        should_linkify = event.key() in {
            Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter,
        }
        continuation_format = self.currentCharFormat() if should_linkify else None
        if should_linkify:
            self._linkify_previous_token()
        super().keyPressEvent(event)
        if continuation_format is not None:
            self.setCurrentCharFormat(continuation_format)

    def contextMenuEvent(self, event) -> None:
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        action = menu.addAction("일반 텍스트로 붙여넣기\tCtrl+Shift+V")
        action.setEnabled(bool(QApplication.clipboard().text()))
        action.triggered.connect(self.paste_as_plain_text)
        menu.exec(event.globalPos())

    def paste_as_plain_text(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self.textCursor().insertText(text)

    def _place_caret_outside_toggles(self) -> bool:
        """마지막 줄 아래 빈 곳을 누르면 토글 밖에서 이어 쓰게 한다.

        토글에는 늘 안쪽 줄이 하나 있으므로, 그냥 두면 문서 끝을 눌렀을 때 커서가
        토글 안으로 들어가 밖에 글을 쓸 수 없다.
        """
        document = self.document()
        last = document.lastBlock()
        if self._block_indent(last) == 0 and not self._is_toggle_block(last):
            return False
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        fmt = cursor.blockFormat()
        fmt.setIndent(0)
        cursor.setBlockFormat(fmt)
        cursor.setCharFormat(QTextCharFormat())
        self.setTextCursor(cursor)
        self.setFocus()
        return True

    def _is_below_last_line(self, point) -> bool:
        block = self.document().lastBlock()
        while block.isValid() and not block.isVisible():
            block = block.previous()
        if not block.isValid():
            return False
        return point.y() > self.cursorRect(QTextCursor(block)).bottom()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            grip = self.image_grip_at(event.position())
            if grip is not None:
                self.begin_image_resize(grip)
                self._claimed_press = True
                event.accept()
                return
        if (event.button() == Qt.MouseButton.LeftButton
                and not event.modifiers()
                and self._is_below_last_line(event.position())
                and self._place_caret_outside_toggles()):
            self._claimed_press = True
            event.accept()
            return
        self._claimed_press = False
        super().mousePressEvent(event)

    def image_rect_left(self, position: int) -> float:
        spot = QTextCursor(self.document())
        spot.setPosition(position)
        return float(self.cursorRect(spot).left())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._image_resize is not None:
            self.finish_image_resize()
            self._claimed_press = False
            event.accept()
            return
        if self._claimed_press:
            # 누를 때 이미 처리했다.  놓을 때 커서를 다시 옮기면 안 된다.
            self._claimed_press = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            page_id = self._page_link_at(event.position())
            if page_id is not None:
                # 페이지 줄은 그냥 눌러도 열린다.  바깥 주소와 달리 Ctrl 이 필요 없다.
                self.page_open_requested.emit(page_id)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            marker = self._toggle_block_at(event.position())
            if marker is not None:
                self.fold_toggle(marker)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            block = self._checklist_block_at(event.position())
            if block is not None:
                self._toggle_check_state(block)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            anchor = self.anchorAt(event.position().toPoint())
            url = self._safe_external_url(anchor)
            if url is not None:
                QDesktopServices.openUrl(url)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def _place_gutter(self) -> None:
        frame = self.frameWidth()
        self.gutter.setGeometry(
            max(0, self.width() - frame - LineGutter.WIDTH), frame,
            LineGutter.WIDTH, max(0, self.height() - frame * 2),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_gutter()
        self._refit_timer.start(0)

    def refit_images(self) -> None:
        if self._refitting_images:
            return
        self._refitting_images = True
        blocked = self.blockSignals(True)
        try:
            cursor = QTextCursor(self.document())
            while not cursor.atEnd():
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                fmt = cursor.charFormat()
                if fmt.isImageFormat():
                    image_fmt = fmt.toImageFormat()
                    original_width = float(image_fmt.property(IMAGE_ORIGINAL_WIDTH) or image_fmt.width() or 1)
                    original_height = float(image_fmt.property(IMAGE_ORIGINAL_HEIGHT) or image_fmt.height() or 1)
                    chosen = image_fmt.property(IMAGE_USER_WIDTH)
                    # 직접 끌어 정한 폭이 있으면 그 값을 지킨다.
                    wanted = float(chosen) if chosen else original_width
                    width = min(wanted, self._available_image_width())
                    image_fmt.setWidth(width)
                    image_fmt.setHeight(width * original_height / max(1.0, original_width))
                    cursor.setCharFormat(image_fmt)
                cursor.clearSelection()
        finally:
            self.blockSignals(blocked)
            self._refitting_images = False

    def _available_image_width(self) -> float:
        widths = []
        if self.store is not None and self.note_id is not None:
            views = getattr(self.store, "_rich_document_views", {}).get(self.note_id, ())
            widths = [view.viewport().width() - 28 for view in views if view.isVisible()]
        width = min(widths) if widths else self.viewport().width() - 28
        return max(80.0, float(width))

    def _register_content_images(self, content: str) -> None:
        if self.store is None:
            return
        for raw_id in set(_IMAGE_ID_RE.findall(str(content or ""))):
            row = self.store.attachment(int(raw_id))
            if row is None:
                continue
            try:
                image = QImage.fromData(base64.b64decode(str(row["data_base64"])))
            except (ValueError, TypeError):
                continue
            if not image.isNull():
                self.document().addResource(
                    QTextDocument.ResourceType.ImageResource,
                    QUrl(f"{IMAGE_URL_PREFIX}attachment/{raw_id}"), image,
                )

    def _linkify_previous_token(self) -> None:
        cursor = self.textCursor()
        block = cursor.block()
        offset = max(0, cursor.position() - block.position())
        prefix = block.text()[:offset].rstrip().rstrip(".,;:!?)\"]")
        match = _LINK_RE.search(prefix)
        if match is None:
            return
        value = match.group("url")
        cursor.setPosition(block.position() + match.start("url"))
        cursor.setPosition(block.position() + match.end("url"), QTextCursor.MoveMode.KeepAnchor)
        href = value if value.startswith(("http://", "https://")) else (
            f"mailto:{value}" if "@" in value else f"https://{value}"
        )
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(href)
        fmt.setForeground(Qt.GlobalColor.blue)
        fmt.setFontUnderline(True)
        cursor.mergeCharFormat(fmt)

    @staticmethod
    def _safe_external_url(value: str) -> QUrl | None:
        url = QUrl(str(value or ""))
        return url if url.scheme().casefold() in {"http", "https", "mailto"} else None
