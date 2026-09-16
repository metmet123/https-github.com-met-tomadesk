from __future__ import annotations

import base64
import json
import re
import weakref
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import (
    QByteArray, QBuffer, QEvent, QIODevice, QLineF, QMimeData, QPoint, QPointF, QRectF,
    QTimer, Qt, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QDesktopServices, QFont, QFontMetricsF, QImage, QImageReader, QKeyEvent, QKeySequence,
    QMouseEvent, QPainter, QPen, QTextCharFormat, QTextCursor, QTextDocument, QTextDocumentFragment,
    QTextBlockFormat, QTextFrameFormat, QTextImageFormat, QTextLength,
    QTextListFormat, QTextTableCellFormat, QTextTableFormat,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QListWidget, QListWidgetItem, QMenu, QMessageBox, QTextEdit, QToolTip,
)

from .insert_menu import (
    install_insert_shortcuts, item_label, item_tooltip, matching_items,
)
from .insert_preferences import get_insert_preferences
from .note_link_dialog import NoteLinkDialog
from .line_gutter import LineGutter
from .rich_text import editor_content, load_editor_content, sanitize_rich_html
from .memo_clipboard import (
    BLOCK_MIME, apply_block_metadata, attachment_ids_from_html, get_json,
    page_ids_from_html, page_sync_ids_from_html, selected_block_metadata, set_json,
)
from .note_clone_service import NoteCloneService, rewrite_cloned_content
from .block_selection import BlockSelectionManager
from .block_commands import BlockCommandDispatcher
from .block_action_bar import BlockActionBar
from .block_identity import (
    HEADING_FOLDED_PROPERTY, PIN_PROPERTY, block_ids, heading_folded_ids, is_pinned,
    load_heading_folds, load_ids, load_pins, pinned_ids, restore_ids, set_ids_from,
    set_pinned, with_heading_folds, with_ids, with_pins,
    SECTION_BREAK_PROPERTY, is_section_break, load_section_breaks, section_break_ids,
    with_section_breaks,
)
from .block_link import parse_block_url
from .character_range_selection import CharacterRangeSelection
from .character_range_action_bar import CharacterRangeActionBar
from .text_format_range_bar import TextFormatRangeBar


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
_PAGE_SYNC_RE = re.compile(r"toma-note://v2/([0-9a-fA-F-]{36})", re.IGNORECASE)
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
# Tab 한 번의 들여쓰기 폭.  Qt 기본값 40px 은 좁은 편집기에서 너무 넓었다.
# 저장되는 것은 칸 수(-qt-block-indent)라 기존 메모도 새 폭으로 보인다.
INDENT_WIDTH = 20
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
# QTextDocument does not serialize custom block properties to HTML. Keep the
# old closed marker readable while migrating it to non-rendered block metadata.
HEADING_FOLDED_PREFIX = "▶ "
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
    block_link_open_requested = pyqtSignal(int, str)
    annotation_activated = pyqtSignal(int)
    page_renamed = pyqtSignal(int)
    page_removed = pyqtSignal(int)
    structured_files_dropped = pyqtSignal(object)

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
        self._identity_reordered = False
        self._claimed_press = False
        # 본문에 지금 들어 있는 페이지들.  줄이 사라지면 그 페이지도 휴지통으로
        # 보내야 하므로, 직전에 무엇이 있었는지 들고 있어야 한다.
        self._known_pages: set[int] = set()
        # `/` 를 쳤을 때 뜨는 삽입 메뉴.  쓸 때 만든다.
        self._insert_popup = None
        self._typing_transaction = False
        # 끌고 있는 줄과 놓을 자리.
        self._drag_source: int | None = None
        self._drop_at = None
        # 크기를 끌고 있는 그림.
        self._image_resize = None
        # 구조(토글·줄 수)가 바뀌었을 때만 문서를 다시 계산한다.
        self._watched_document = None
        self._structure_dirty = True
        self._block_count = 0
        self._copied_character_format: QTextCharFormat | None = None
        self._composite_edits: list[dict] = []
        self._block_selecting = False
        self._block_action_bar_height = 0
        self._left_press_point: QPoint | None = None
        self._left_press_target: tuple[str, int] | None = None
        self._left_press_dragged = False
        self._character_press_point: QPoint | None = None
        self._character_press_position: int | None = None
        self._character_dragging = False
        # 본문 찾기로 표시해 둔 자리.  칠할 때 체크리스트 표시와 함께 얹는다.
        self._find_ranges: list[tuple[int, int]] = []
        self._find_current = -1
        self._annotations: list[dict] = []
        self.external_undo_handler = None
        self.external_redo_handler = None
        self._folded_table_formats: dict[int, QTextTableFormat] = {}
        self._folded_table_formats: dict[int, QTextTableFormat] = {}
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
        self._caret_guard_timer = QTimer(self)
        self._caret_guard_timer.setSingleShot(True)
        self._caret_guard_timer.setInterval(0)
        self._caret_guard_timer.timeout.connect(self._keep_caret_on_visible_line)
        self.cursorPositionChanged.connect(self._caret_guard_timer.start)
        self.textChanged.connect(lambda: self.gutter.update() if hasattr(self, "gutter") else None)
        self.viewport().setMouseTracking(True)
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        # 줄 손잡이 칸.  본문 오른쪽 끝에 둔다.
        self.gutter = LineGutter(self)
        self.setViewportMargins(0, 0, LineGutter.WIDTH, 0)
        self._place_gutter()
        self.block_selection = BlockSelectionManager(self)
        self.character_selection = CharacterRangeSelection(self)
        self.block_commands = BlockCommandDispatcher(self)
        self.block_action_bar = BlockActionBar(self, self.block_commands)
        self.character_action_bar = CharacterRangeActionBar(self)
        self.text_format_bar = TextFormatRangeBar(self)
        self.block_selection.changed.connect(self._block_selection_changed)
        self.character_selection.changed.connect(self._character_selection_changed)
        self.block_selection.changed.connect(self.text_format_bar.sync)
        self.character_selection.changed.connect(self.text_format_bar.sync)
        self.verticalScrollBar().valueChanged.connect(lambda _value: self.block_action_bar.sync())
        self.verticalScrollBar().valueChanged.connect(lambda _value: self.text_format_bar.sync())
        self.selectionChanged.connect(self._queue_text_format_bar_sync)
        # 넣을 수 있는 것들의 단축키.  목록 한곳에 적힌 것을 그대로 건다.
        self.insert_shortcuts = install_insert_shortcuts(self)

    def set_note_context(self, note_id: int | None) -> None:
        if hasattr(self, "block_selection"):
            self.block_selection.clear()
            self.character_selection.clear()
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
        # QTextEdit may delete its previous document inside setDocument().
        # Disconnect while that document is still alive.
        self._unwatch_document()
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
        self._unwatch_document()
        self._watched_document = document
        self._composite_edits = getattr(document, "_toma_composite_edits", [])
        setattr(document, "_toma_composite_edits", self._composite_edits)
        document.contentsChange.connect(self._note_contents_change)
        document.undoCommandAdded.connect(self._discard_composite_redos)
        document.undoCommandAdded.connect(self._snapshot_block_ids)
        self._block_count = document.blockCount()
        self._structure_dirty = True

    def _unwatch_document(self) -> None:
        old = self._watched_document
        self._watched_document = None
        if old is None or sip.isdeleted(old):
            return
        for signal, slot in (
            (old.contentsChange, self._note_contents_change),
            (old.undoCommandAdded, self._discard_composite_redos),
            (old.undoCommandAdded, self._snapshot_block_ids),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _snapshot_block_ids(self) -> None:
        document = self.document()
        history = getattr(document, "_toma_block_id_states", None)
        if history is None:
            history = {}
            setattr(document, "_toma_block_id_states", history)
        step = int(document.availableUndoSteps())
        for future in [value for value in history if value > step]:
            del history[future]
        previous = history.get(step - 1)
        if previous is None:
            previous = history.get(max((value for value in history if value < step), default=-1))
        if (previous is not None and len(previous) == document.blockCount()
                and not self._identity_reordered):
            # Character/format edits do not change block ownership. Share the
            # immutable snapshot instead of scanning a long memo per keystroke.
            history[step] = previous
        else:
            history[step] = tuple(block_ids(document))

    def _restore_block_id_snapshot(self) -> None:
        document = self.document()
        history = getattr(document, "_toma_block_id_states", {})
        ids = history.get(int(document.availableUndoSteps()))
        if ids is not None:
            restore_ids(document, ids)

    def undo(self) -> None:
        super().undo()
        self._restore_block_id_snapshot()

    def redo(self) -> None:
        super().redo()
        self._restore_block_id_snapshot()

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
        if self._is_toggle_block(first) or self.heading_level(first):
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
            self._valid_internal_link_at_position(cursor.position() - 1) is not None
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
        self.character_selection.clear()
        self._folded_table_formats.clear()
        self._register_content_images(content)
        load_editor_content(self, content)
        self._repair_legacy_heading_formats()
        # 이 기능이 생기기 전에 만든 빈 토글에도 안내가 들어갈 자리를 만들어 준다.
        self._ensure_toggle_children()
        # 페이지 줄에 옛 제목이 남아 있으면 지금 제목으로 맞춘다.
        self._refresh_page_links()
        self._refresh_note_links()
        self._remove_orphan_internal_links()
        self._refresh_known_pages()
        self._reset_typing_format()
        load_ids(self.document(), content)
        load_pins(self.document(), content)
        self._load_heading_fold_state(content)
        load_section_breaks(self.document(), content)
        # 접어 둔 토글과 제목의 상태를 화면에 적용한다.
        self._refresh_toggle_visibility()
        setattr(self.document(), "_toma_block_id_states", {
            int(self.document().availableUndoSteps()): tuple(block_ids(self.document())),
        })
        self.document().setProperty("tomaSourceContent", str(content or ""))
        self.document().setModified(False)
        self._refit_timer.start(0)

    def _repair_legacy_heading_formats(self) -> None:
        """Restore headings saved with block margins but default-size text."""
        legacy = []
        for block in self._iter_blocks():
            standard_level = int(block.blockFormat().headingLevel())
            if standard_level in HEADING_STYLES:
                fmt = block.blockFormat()
                fmt.setLeftMargin(max(18.0, fmt.leftMargin()))
                fmt.setProperty(HEADING_LEVEL_PROPERTY, standard_level)
                QTextCursor(block).setBlockFormat(fmt)
                continue
            level = self.heading_level(block)
            if level not in HEADING_STYLES:
                continue
            start = block.position() + (len(HEADING_FOLDED_PREFIX)
                                        if self._heading_is_folded(block) else 0)
            probe = QTextCursor(self.document())
            probe.setPosition(start)
            if start < block.position() + len(block.text()):
                probe.movePosition(QTextCursor.MoveOperation.NextCharacter,
                                   QTextCursor.MoveMode.KeepAnchor)
            if abs(probe.charFormat().fontPointSize() - HEADING_STYLES[level][0]) >= 0.1:
                legacy.append((block.position(), level))
        if not legacy:
            return
        document = self.document()
        undo_enabled = document.isUndoRedoEnabled()
        # Loading content establishes a new document baseline.  Repairing its
        # old presentation must not become the first user-visible Undo step.
        document.setUndoRedoEnabled(False)
        try:
            for position, level in legacy:
                block = document.findBlock(position)
                fmt = block.blockFormat()
                fmt.setHeadingLevel(level)
                fmt.setProperty(HEADING_LEVEL_PROPERTY, level)
                QTextCursor(block).setBlockFormat(fmt)
                point_size, spacing, _top, _bottom = HEADING_STYLES[level]
                char_format = QTextCharFormat()
                char_format.setFontPointSize(point_size)
                char_format.setFontWeight(QFont.Weight.Bold)
                char_format.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
                char_format.setFontLetterSpacing(spacing)
                cursor = QTextCursor(block)
                cursor.setPosition(position + (len(HEADING_FOLDED_PREFIX)
                                               if self._heading_is_folded(block) else 0))
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                    QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(char_format)
        finally:
            document.setUndoRedoEnabled(undo_enabled)

    def _load_heading_fold_state(self, content: str) -> None:
        """Load new invisible fold metadata and migrate old visible ▶ prefixes."""
        load_heading_folds(self.document(), content)
        block = self.document().begin()
        while block.isValid():
            if self.heading_level(block) and block.text().startswith(HEADING_FOLDED_PREFIX):
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(
                    QTextCursor.MoveOperation.NextCharacter,
                    QTextCursor.MoveMode.KeepAnchor,
                    len(HEADING_FOLDED_PREFIX),
                )
                cursor.removeSelectedText()
                fmt = block.blockFormat()
                fmt.setProperty(HEADING_FOLDED_PROPERTY, True)
                fmt.setLeftMargin(max(18.0, fmt.leftMargin()))
                QTextCursor(block).setBlockFormat(fmt)
            block = block.next()

    def content(self) -> str:
        html = self._html_with_original_table_formats()
        if not html:
            return ""
        html = with_ids(html, block_ids(self.document()))
        html = with_pins(html, pinned_ids(self.document()))
        html = with_heading_folds(html, heading_folded_ids(self.document()))
        return with_section_breaks(html, section_break_ids(self.document()))

    def _html_with_original_table_formats(self) -> str:
        """Store real table formatting while folded tables use a zero-size frame."""
        html = editor_content(self)
        if not html or not self._folded_table_formats:
            return html
        copy = QTextDocument()
        copy.setHtml(html)
        seen = set()
        block = copy.begin()
        while block.isValid():
            table = QTextCursor(block).currentTable()
            if table is not None:
                key = int(table.firstPosition())
                if key not in seen and key in self._folded_table_formats:
                    table.setFormat(QTextTableFormat(self._folded_table_formats[key]))
                    seen.add(key)
            block = block.next()
        return copy.toHtml()

    def insert_structured_html(self, html: str, toggle_heading_levels=()) -> None:
        """Insert one sanitized external document as one undoable native edit."""
        source = QTextDocument()
        self._configure_document(source)
        source.setHtml(sanitize_rich_html(html, remove_external_images=True))
        toggle_levels = {int(value) for value in toggle_heading_levels}
        from .structured_import import DETAIL_END_MARKER, DETAIL_START_MARKER

        stack: list[tuple[str, int]] = []
        marker_blocks = []
        block = source.begin()
        while block.isValid():
            text = block.text()
            if text.startswith(DETAIL_END_MARKER):
                while stack:
                    kind, _value = stack.pop()
                    if kind == "details":
                        break
                marker_blocks.append(block)
                block = block.next()
                continue
            level = int(block.blockFormat().headingLevel())
            if level:
                while stack and stack[-1][0] == "heading" and stack[-1][1] >= level:
                    stack.pop()
            is_details = text.startswith(DETAIL_START_MARKER)
            is_toggle = is_details or level in toggle_levels
            block_cursor = QTextCursor(block)
            block_format = block.blockFormat()
            block_format.setIndent(max(0, block_format.indent()) + len(stack))
            if level:
                own_level = min(4, max(1, level))
                point_size, spacing, top, bottom = HEADING_STYLES[own_level]
                block_format.setTopMargin(top)
                block_format.setBottomMargin(bottom)
                block_format.setProperty(HEADING_LEVEL_PROPERTY, own_level)
                block_cursor.setBlockFormat(block_format)
                styled = QTextCursor(block)
                styled.movePosition(
                    QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
                )
                char_format = QTextCharFormat()
                char_format.setFontWeight(QFont.Weight.Bold)
                char_format.setFontPointSize(point_size)
                char_format.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
                char_format.setFontLetterSpacing(spacing)
                styled.mergeCharFormat(char_format)
            else:
                block_cursor.setBlockFormat(block_format)
            if is_toggle:
                marker = QTextCursor(block)
                marker.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                if is_details:
                    marker.movePosition(
                        QTextCursor.MoveOperation.NextCharacter,
                        QTextCursor.MoveMode.KeepAnchor, len(DETAIL_START_MARKER),
                    )
                marker.insertText(TOGGLE_OPEN_PREFIX)
                stack.append(("details", 0) if is_details else ("heading", level))
            block = block.next()
        for marker_block in reversed(marker_blocks):
            marker = QTextCursor(marker_block)
            marker.movePosition(
                QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
            )
            marker.removeSelectedText()

        cursor = self.textCursor()
        transaction = QTextCursor(cursor)
        transaction.beginEditBlock()
        try:
            def insert_document() -> None:
                cursor.insertHtml(source.toHtml())
                self.setTextCursor(cursor)

            self._paste_into_lone_empty_toggle(insert_document)
        finally:
            transaction.endEditBlock()
        self._structure_dirty = True

    def _discard_composite_redos(self) -> None:
        """A new edit after Undo invalidates the matching database redo batch."""
        self._composite_edits[:] = [entry for entry in self._composite_edits if entry["active"]]
        self._refresh_structure()

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
        document.setIndentWidth(INDENT_WIDTH)
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
        self.apply_character_format(fmt)
        self.setFocus()

    def apply_character_format(self, fmt: QTextCharFormat) -> None:
        """Apply a toolbar format to all saved ranges as one undoable edit."""
        ranges = self.character_selection.ranges()
        if not ranges:
            cursor = self.textCursor()
            cursor.mergeCharFormat(fmt)
            self.mergeCurrentCharFormat(fmt)
            return
        transaction = QTextCursor(self.document())
        transaction.beginEditBlock()
        try:
            for start, end in ranges:
                cursor = QTextCursor(self.document())
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(fmt)
        finally:
            transaction.endEditBlock()
        self._refresh_checklist_display()

    def add_current_character_selection(self) -> bool:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return False
        added = self.character_selection.add_cursor(cursor)
        if added:
            cursor.clearSelection()
            self.setTextCursor(cursor)
        return added

    def unlink_selected_character_ranges(self) -> bool:
        """Remove only anchors in selected text, never page/block structure."""
        ranges = self.character_selection.ranges()
        if not ranges:
            return False
        runs: list[tuple[int, int]] = []
        for start, end in ranges:
            block = self.document().findBlock(start)
            while block.isValid() and block.position() < end:
                # An embedded page is a DB-backed block, not an inline link.
                if self.page_id_of_block(block) is None:
                    iterator = block.begin()
                    while not iterator.atEnd():
                        fragment = iterator.fragment()
                        iterator += 1
                        if fragment.isValid() and fragment.charFormat().isAnchor():
                            left = max(start, fragment.position())
                            right = min(end, fragment.position() + fragment.length())
                            if left < right:
                                runs.append((left, right))
                block = block.next()
        if not runs:
            return False
        transaction = QTextCursor(self.document())
        transaction.beginEditBlock()
        try:
            for start, end in runs:
                cursor = QTextCursor(self.document())
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                self._clear_anchor_in_cursor(cursor)
        finally:
            transaction.endEditBlock()
        self._refresh_checklist_display()
        return True

    def toggle_bullet_list(self) -> None:
        if self.character_selection.count():
            return
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
        if self.character_selection.count():
            return
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
        selections.extend(self._annotation_selections())
        selections.extend(self._block_selection_highlights())
        selections.extend(self._character_selection_highlights())
        self.setExtraSelections(selections)
        self.viewport().update()

    def set_annotations(self, rows) -> None:
        self._annotations = [dict(row) for row in rows]
        self._refresh_checklist_display()

    def _annotation_selections(self):
        selections = []
        document_end = max(0, self.document().characterCount() - 1)
        for row in self._annotations:
            if str(row.get("location_status") or "") != "resolved":
                continue
            start = max(0, min(int(row.get("start_offset") or 0), document_end))
            end = max(start, min(int(row.get("end_offset") or start), document_end))
            cursor = QTextCursor(self.document())
            cursor.setPosition(start)
            if end > start:
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            mark = QTextEdit.ExtraSelection()
            mark.cursor = cursor
            mark.format.setBackground(QColor(254, 240, 138, 150))
            mark.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
            mark.format.setUnderlineColor(QColor("#ca8a04"))
            if not cursor.hasSelection():
                mark.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            selections.append(mark)
        return selections

    def annotation_at_position(self, position: int):
        for row in reversed(self._annotations):
            if str(row.get("location_status") or "") != "resolved":
                continue
            start = int(row.get("start_offset") or 0)
            end = int(row.get("end_offset") or start)
            if start <= int(position) <= max(start, end):
                return row
        return None

    def _block_selection_highlights(self):
        if not hasattr(self, "block_selection"):
            return []
        selections = []
        for block in self.block_selection.blocks():
            mark = QTextEdit.ExtraSelection()
            mark.cursor = QTextCursor(block)
            mark.cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
            )
            mark.format.setBackground(QColor(219, 234, 254, 190))
            mark.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            selections.append(mark)
        return selections

    def _block_selection_changed(self) -> None:
        if self.block_selection.count():
            self.character_selection.clear()
        self._refresh_checklist_display()
        self.block_action_bar.sync()
        self.gutter.update()

    def _character_selection_highlights(self):
        if not hasattr(self, "character_selection"):
            return []
        selections = []
        for start, end in self.character_selection.ranges():
            mark = QTextEdit.ExtraSelection()
            mark.cursor = QTextCursor(self.document())
            mark.cursor.setPosition(start)
            mark.cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            mark.format.setBackground(QColor(191, 219, 254, 215))
            selections.append(mark)
        return selections

    def _character_selection_changed(self) -> None:
        if self.character_selection.count():
            self.block_selection.clear()
        self._refresh_checklist_display()
        self.character_action_bar.sync()

    def _sync_selection_bar_height(self) -> None:
        height = self.block_action_bar.HEIGHT + 4 if self.block_selection.count() else 0
        if self.character_selection.count():
            height = self.character_action_bar.HEIGHT + 4
        elif height == 0 and self.text_format_bar.is_reserved:
            height = self.text_format_bar.HEIGHT + 4
        self._set_block_action_bar_height(height)

    def set_format_toolbar(self, toolbar, open_more) -> None:
        self.text_format_bar.bind(toolbar, open_more)
        self._queue_text_format_bar_sync()

    def _queue_text_format_bar_sync(self) -> None:
        QTimer.singleShot(0, self.text_format_bar.sync)

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
        """접힌 제목·토글 안에 있는 자리면 그 범위를 펴서 보이게 한다."""
        document = self.document()
        block = document.findBlock(max(0, min(int(position), document.characterCount() - 1)))
        if not block.isValid() or block.isVisible():
            return False
        opened = False
        # Open enclosing headings from the outside in. A nested heading may be
        # hidden while its ancestor is closed, but its marker still persists.
        stack = []
        probe = document.begin()
        while probe.isValid() and probe.position() < block.position():
            level = self.heading_level(probe)
            if level:
                depth = self._block_indent(probe)
                while stack and stack[-1][0] >= level and stack[-1][1] >= depth:
                    stack.pop()
                stack.append((level, depth, probe))
            probe = probe.next()
        for _level, _depth, heading in stack:
            if self._heading_is_folded(heading):
                self._set_heading_folded(heading, False)
                opened = True
        if opened:
            self._refresh_toggle_visibility()
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

    def _parent_toggle(self, child):
        """들여쓴 줄을 직접 품은 가장 가까운 토글을 찾는다."""
        if not child.isValid():
            return None
        depth = self._block_indent(child)
        if depth <= 0:
            return None
        probe = child.previous()
        while probe.isValid():
            if self._block_indent(probe) < depth:
                return probe if self._is_toggle_block(probe) else None
            probe = probe.previous()
        return None

    def _toggle_for_lone_empty_child(self, child):
        """안내 줄이라면 그 줄을 가진 토글을 돌려준다."""
        if not child.isValid() or child.text().strip():
            return None
        toggle = self._parent_toggle(child)
        empty = self._lone_empty_child(toggle) if toggle is not None else None
        if empty is not None and empty.position() == child.position():
            return toggle
        return None

    @staticmethod
    def _delete_empty_block(block) -> None:
        """빈 문단 하나와 그 문단 구분자만 제거한다."""
        if not block.isValid() or block.text().strip():
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        following = block.next()
        if following.isValid():
            cursor.setPosition(following.position(), QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            return
        cursor.deletePreviousChar()

    def _delete_empty_block_and_restore(self, block, visible_anchor) -> None:
        """빈 줄만 지우고 커서와 본문 스크롤을 보이는 문단에 유지한다.

        빈 토글의 안내 줄은 접혀 있으면 화면에 없다.  그 줄의 위치로 커서를
        복원하면 Qt가 숨은 커서를 보이게 하려고 문서 맨 위로 스크롤할 수 있다.
        삭제할 줄과 복원할 줄을 따로 받아 항상 보이는 문단으로 돌아간다.
        """
        if not block.isValid() or not visible_anchor.isValid():
            return
        document = self.document()
        restore_at = visible_anchor.position() + visible_anchor.length() - 1
        scroll_bar = self.verticalScrollBar()
        scroll_value = scroll_bar.value()
        transaction = QTextCursor(document)
        transaction.beginEditBlock()
        try:
            self._delete_empty_block(block)
        finally:
            transaction.endEditBlock()
        restored = QTextCursor(document)
        restored.setPosition(max(0, min(restore_at, document.characterCount() - 1)))
        self.setTextCursor(restored)
        self._restore_inner_scroll(scroll_value)

    def _restore_inner_scroll(self, value: int) -> None:
        scroll_bar = self.verticalScrollBar()
        scroll_bar.setValue(max(scroll_bar.minimum(), min(int(value), scroll_bar.maximum())))

    @staticmethod
    def _table_at_block(block):
        return QTextCursor(block).currentTable() if block.isValid() else None

    def _is_table_boundary_block(self, block) -> bool:
        """외부 표가 끝난 직후 Qt가 두는 빈 구조 문단인지 확인한다."""
        if not block.isValid() or block.text().strip():
            return False
        previous = block.previous()
        previous_table = self._table_at_block(previous)
        if previous_table is None:
            return False
        current_table = self._table_at_block(block)
        previous_key = previous_table.firstPosition()
        current_key = current_table.firstPosition() if current_table is not None else None
        return previous_key != current_key

    def _move_caret_past_table_boundary(self, join_previous_edit: bool = False) -> bool:
        """표 오른쪽 끝의 구조 문단 대신 왼쪽의 깨끗한 문단을 연다."""
        cursor = self.textCursor()
        if cursor.hasSelection() or not self._is_table_boundary_block(cursor.block()):
            return False
        if join_previous_edit:
            cursor.joinPreviousEditBlock()
        try:
            self._open_clean_block(cursor)
        finally:
            if join_previous_edit:
                cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.setCurrentCharFormat(QTextCharFormat())
        return True

    def _keep_pasted_blocks_inside_toggle(self, toggle, start: int, end: int) -> None:
        """빈 안내 줄에 붙인 문단들을 토글의 첫 깊이 안으로 넣는다."""
        if end <= start or not toggle.isValid():
            return
        document = self.document()
        first = document.findBlock(start)
        last = document.findBlock(max(start, end - 1))
        if not first.isValid() or not last.isValid():
            return
        minimum_depth = self._block_indent(toggle) + 1
        pasted = []
        block = first
        while block.isValid():
            pasted.append(block)
            if block.position() == last.position():
                break
            block = block.next()
        for block in pasted:
            if self._block_indent(block) < minimum_depth:
                block_cursor = QTextCursor(block)
                fmt = block.blockFormat()
                fmt.setIndent(minimum_depth)
                block_cursor.setBlockFormat(fmt)
        if pasted and not pasted[0].text().strip() and any(
            block.text().strip() for block in pasted[1:]
        ):
            self._delete_empty_block(pasted[0])
        self._refresh_toggle_visibility()

    def _paste_into_lone_empty_toggle(self, insert, first_block_format=None) -> None:
        """토글 자식에 붙인 새 문단을 같은 토글 안에 두고 첫 문단 서식을 지킨다."""
        cursor = self.textCursor()
        placeholder_toggle = None if cursor.hasSelection() else self._toggle_for_lone_empty_child(
            cursor.block()
        )
        toggle = placeholder_toggle
        if toggle is None and not cursor.hasSelection():
            toggle = self._parent_toggle(cursor.block())
        if toggle is None:
            insert()
            return
        start = cursor.position()
        transaction = QTextCursor(cursor)
        transaction.beginEditBlock()
        try:
            insert()
            self._keep_pasted_blocks_inside_toggle(toggle, start, self.textCursor().position())
            if placeholder_toggle is not None and first_block_format is not None:
                first = self.document().findBlock(start)
                if first.isValid():
                    block_cursor = QTextCursor(first)
                    block_format = QTextBlockFormat(first_block_format)
                    block_format.setIndent(max(
                        self._block_indent(toggle) + 1, block_format.indent(),
                    ))
                    block_cursor.setBlockFormat(block_format)
        finally:
            transaction.endEditBlock()

    @staticmethod
    def _clipboard_plain_text(value: str) -> str:
        """클립보드 줄바꿈을 QTextDocument와 비교할 한 가지 형태로 맞춘다."""
        return str(value or "").replace("\r\n", "\n").replace("\r", "\n").replace(
            "\u2028", "\n"
        ).replace("\u2029", "\n")

    @classmethod
    def _html_with_plain_text_line_breaks(cls, html: str, plain_text: str) -> str:
        """HTML의 장식용 빈 줄만 걷고 클립보드 원문의 줄바꿈을 따른다.

        일부 프로그램은 눈에 보이는 문단 간격을 ``<p><br></p>`` 또는 연속
        ``<br>`` 로 함께 복사한다.  같은 클립보드의 text/plain에는 그 빈 줄이
        없으므로, 글자는 같고 HTML 쪽 줄바꿈만 더 많을 때에만 초과분을 지운다.
        QTextDocument에서 직접 고치므로 남은 글자·목록·문단 서식은 유지된다.
        """
        cleaned = sanitize_rich_html(html)
        wanted = cls._clipboard_plain_text(plain_text)
        if not wanted:
            return cleaned
        document = QTextDocument()
        document.setHtml(cleaned)

        def raw_characters():
            result = []
            # QTextDocument 끝의 암시적 문단 구분자는 toPlainText()에 나오지 않는다.
            for position in range(max(0, document.characterCount() - 1)):
                character = document.characterAt(position)
                visible = "\n" if character in {"\u2028", "\u2029"} else character
                result.append((position, character, visible))
            return result

        def newline_gaps(characters):
            gaps: dict[int, list[tuple[int, str]]] = {}
            visible_count = 0
            for position, raw, visible in characters:
                if visible == "\n":
                    gaps.setdefault(visible_count, []).append((position, raw))
                else:
                    visible_count += 1
            return gaps

        wanted_without_breaks = wanted.replace("\n", "")
        changed = False
        while True:
            characters = raw_characters()
            actual = "".join(visible for _position, _raw, visible in characters)
            if actual == wanted:
                break
            if actual.replace("\n", "") != wanted_without_breaks:
                return cleaned
            actual_gaps = newline_gaps(characters)
            wanted_gaps = newline_gaps([
                (position, character, character)
                for position, character in enumerate(wanted)
            ])
            excess = next((
                gap for gap, breaks in actual_gaps.items()
                if len(breaks) > len(wanted_gaps.get(gap, []))
            ), None)
            if excess is None:
                return cleaned
            candidates = actual_gaps[excess]
            soft_break = next((position for position, raw in candidates if raw == "\u2028"), None)
            if soft_break is not None:
                cursor = QTextCursor(document)
                cursor.setPosition(soft_break)
                cursor.deleteChar()
                changed = True
                continue
            blank = document.begin()
            removed_blank = False
            candidate_positions = {position for position, _raw in candidates}
            while blank.isValid():
                if (
                    not blank.text()
                    and blank.position() in candidate_positions
                    and blank.next().isValid()
                ):
                    cls._delete_empty_block(blank)
                    removed_blank = changed = True
                    break
                blank = blank.next()
            if removed_blank:
                continue
            # 남은 초과분은 비어 있지 않은 두 HTML 문단 사이의 구분자다.
            # text/plain에 경계가 없을 때만 합쳐야 원문의 줄바꿈과 같아진다.
            cursor = QTextCursor(document)
            cursor.setPosition(candidates[-1][0])
            cursor.deleteChar()
            changed = True
        return document.toHtml() if changed else cleaned

    def _html_for_paste(self, source: QMimeData) -> str:
        html = sanitize_rich_html(source.html())
        cursor = self.textCursor()
        inside_toggle = not cursor.hasSelection() and self._parent_toggle(cursor.block()) is not None
        if inside_toggle and source.hasText():
            return self._html_with_plain_text_line_breaks(html, source.text())
        return html

    @staticmethod
    def _first_html_block_format(html: str):
        document = QTextDocument()
        document.setHtml(html)
        first = document.begin()
        return QTextBlockFormat(first.blockFormat()) if first.isValid() else None

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
        cursor.beginEditBlock()
        self._syncing_toggle_children = True
        try:
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.insertText(TOGGLE_OPEN_PREFIX)
            block = cursor.block()
            following = block.next()
            if not following.isValid() or self._block_indent(following) <= self._block_indent(block):
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                self._open_clean_block(cursor, self._block_indent(block) + 1)
        finally:
            self._syncing_toggle_children = False
            cursor.endEditBlock()
        restored = QTextCursor(block)
        restored.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self.setTextCursor(restored)
        self._structure_dirty = True
        self._refresh_structure()
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
            # The marker characters were the immediately preceding edit. Join
            # them so one Ctrl+Z restores the state before the whole shortcut.
            wipe.joinPreviousEditBlock()
            try:
                if eaten:
                    wipe.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    wipe.movePosition(
                        QTextCursor.MoveOperation.NextCharacter,
                        QTextCursor.MoveMode.KeepAnchor, eaten,
                    )
                    wipe.removeSelectedText()
                    self.setTextCursor(wipe)
                self._typing_transaction = True
                handler()
            finally:
                self._typing_transaction = False
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
        if self.character_selection.count():
            return
        if level not in HEADING_STYLES:
            return
        point_size, spacing, top, bottom = HEADING_STYLES[level]
        original = self.textCursor()
        transaction = QTextCursor(original)
        if not self._typing_transaction:
            transaction.beginEditBlock()
        try:
            for block in list(self._selected_blocks()):
                block_cursor = QTextCursor(block)
                block_format = block.blockFormat()
                block_format.setTopMargin(top)
                block_format.setBottomMargin(bottom)
                block_format.setLeftMargin(max(18.0, block_format.leftMargin()))
                block_format.setProperty(HEADING_LEVEL_PROPERTY, level)
                block_format.setHeadingLevel(level)
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
            if not self._typing_transaction:
                transaction.endEditBlock()
        self.setTextCursor(original)
        if not original.hasSelection():
            # A zero-length selection on an empty heading cannot style future
            # characters.  Keep the heading's typing format at the caret too.
            self.setCurrentCharFormat(char_format)
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
        if self.character_selection.count():
            return
        original = self.textCursor()
        transaction = QTextCursor(original)
        transaction.beginEditBlock()
        try:
            for block in list(self._selected_blocks()):
                self._set_heading_folded(block, False)
                block_cursor = QTextCursor(block)
                block_format = block.blockFormat()
                block_format.setTopMargin(0)
                block_format.setBottomMargin(0)
                if abs(block_format.leftMargin() - 18.0) < 0.1:
                    block_format.setLeftMargin(0)
                block_format.clearProperty(HEADING_LEVEL_PROPERTY)
                block_format.setHeadingLevel(0)
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
            level = int(block.blockFormat().property(HEADING_LEVEL_PROPERTY) or 0)
        except (TypeError, ValueError):
            level = 0
        if level in HEADING_STYLES:
            return level
        level = int(block.blockFormat().headingLevel())
        if level in HEADING_STYLES:
            return level
        probe = QTextCursor(block)
        if block.text().startswith(HEADING_FOLDED_PREFIX):
            probe.setPosition(block.position() + len(HEADING_FOLDED_PREFIX))
        probe.movePosition(
            QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor,
        )
        size = probe.charFormat().fontPointSize()
        for candidate, (point_size, _spacing, top, _bottom) in HEADING_STYLES.items():
            if abs(size - point_size) < 0.1 and abs(block.blockFormat().topMargin() - top) < 0.1:
                return candidate
        # Recover headings created on an empty line before typing format was
        # persisted.  Their distinctive block margins survived the HTML save.
        if abs(block.blockFormat().leftMargin() - 18.0) < 0.1:
            for candidate, (_size, _spacing, top, bottom) in HEADING_STYLES.items():
                if (abs(block.blockFormat().topMargin() - top) < 0.1
                        and abs(block.blockFormat().bottomMargin() - bottom) < 0.1):
                    return candidate
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

    @staticmethod
    def _heading_is_folded(block) -> bool:
        return block.isValid() and bool(
            block.blockFormat().property(HEADING_FOLDED_PROPERTY)
            or block.text().startswith(HEADING_FOLDED_PREFIX)
        )

    def _set_heading_folded(self, block, folded: bool) -> None:
        if not block.isValid() or self._heading_is_folded(block) == folded:
            return
        block_format = block.blockFormat()
        block_format.setLeftMargin(max(18.0, block_format.leftMargin()))
        if folded:
            block_format.setProperty(HEADING_FOLDED_PROPERTY, True)
        else:
            block_format.clearProperty(HEADING_FOLDED_PROPERTY)
        QTextCursor(block).setBlockFormat(block_format)

    def fold_heading(self, block) -> bool:
        if (not self.heading_level(block) or not block.text().strip()
                or self.page_id_of_block(block) is not None):
            return False
        closing = not self._heading_is_folded(block)
        if closing and self.textCursor().block() != block:
            level = self.heading_level(block)
            depth = self._block_indent(block)
            child = block.next()
            while child.isValid() and not (
                self.heading_level(child) and self.heading_level(child) <= level
                and self._block_indent(child) <= depth
            ) and not (
                not self.heading_level(child) and self._block_indent(child) <= depth
                and is_section_break(child)
            ):
                if child.contains(self.textCursor().position()):
                    self.setTextCursor(QTextCursor(block))
                    break
                child = child.next()
        transaction = QTextCursor(self.document())
        transaction.beginEditBlock()
        try:
            self._set_heading_folded(block, closing)
        finally:
            transaction.endEditBlock()
        self._refresh_toggle_visibility()
        return True

    def toggle_current_fold(self) -> bool:
        block = self.textCursor().block()
        if self.heading_level(block):
            return self.fold_heading(block)
        if self._is_toggle_block(block):
            self.fold_toggle(block)
            return True
        return False

    def enter_current_fold(self) -> bool:
        block = self.textCursor().block()
        level = self.heading_level(block)
        toggle = self._is_toggle_block(block)
        if not level and not toggle:
            return False
        if level and self._heading_is_folded(block):
            self.fold_heading(block)
        elif toggle and not self._toggle_is_open(block):
            self.fold_toggle(block)
        child = block.next()
        if not child.isValid() or not child.isVisible():
            return False
        if (level and self.heading_level(child) and self.heading_level(child) <= level
                and self._block_indent(child) <= self._block_indent(block)):
            return False
        if toggle and self._block_indent(child) <= self._block_indent(block):
            return False
        self.setTextCursor(QTextCursor(child))
        self.ensureCursorVisible()
        return True

    # ------------------------------------------------------ 제목 끝 표시 --
    def _heading_section_owner(self, block):
        """이 본문 줄이 속한 제목(끝 표시로 끊기지 않은 가장 가까운 위 제목)."""
        if not block.isValid() or self.heading_level(block):
            return None
        depth = self._block_indent(block)
        if depth > 0 and self._parent_toggle(block) is not None:
            return None
        probe = block
        while probe.isValid():
            if probe != block and self.heading_level(probe):
                if self._block_indent(probe) <= depth and self.page_id_of_block(probe) is None:
                    return probe
            elif self._block_indent(probe) <= depth and is_section_break(probe):
                return None
            probe = probe.previous()
        return None

    def mark_section_break(self, block) -> bool:
        """제목 아래 맨 앞 줄에서 Shift+Tab: 이 줄부터 제목 밖으로 뺀다."""
        if (self._block_indent(block) != 0 or is_section_break(block)
                or self._is_toggle_block(block) or self._heading_section_owner(block) is None):
            return False
        fmt = block.blockFormat()
        fmt.setProperty(SECTION_BREAK_PROPERTY, True)
        QTextCursor(block).setBlockFormat(fmt)
        self._refresh_toggle_visibility()
        self.viewport().update()
        return True

    def clear_section_break(self, block) -> bool:
        """끝 표시 줄 맨 앞 Backspace: 표시만 지워 다시 제목에 넣는다."""
        if not is_section_break(block):
            return False
        fmt = block.blockFormat()
        fmt.clearProperty(SECTION_BREAK_PROPERTY)
        QTextCursor(block).setBlockFormat(fmt)
        self._refresh_toggle_visibility()
        self.viewport().update()
        return True

    def _open_line_after_folded_heading(self, heading) -> None:
        """접힌 제목에서 Enter: 숨은 본문 뒤, 제목 밖에 새 줄을 연다."""
        level = self.heading_level(heading)
        depth = self._block_indent(heading)
        last = heading
        probe = heading.next()
        while probe.isValid() and not probe.isVisible():
            if self.heading_level(probe) and self.heading_level(probe) <= level \
                    and self._block_indent(probe) <= depth:
                break
            last = probe
            probe = probe.next()
        cursor = QTextCursor(last)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.beginEditBlock()
        try:
            self._open_clean_block(cursor, depth)
            if last != heading:
                fmt = cursor.blockFormat()
                fmt.setProperty(SECTION_BREAK_PROPERTY, True)
                cursor.setBlockFormat(fmt)
        finally:
            cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.setCurrentCharFormat(QTextCharFormat())
        self._refresh_toggle_visibility()

    def _keep_caret_on_visible_line(self) -> None:
        """Ctrl+End·↓ 등으로 숨은 줄에 들어간 커서를 보이는 줄로 데려온다."""
        cursor = self.textCursor()
        block = cursor.block()
        if block.isVisible() or cursor.hasSelection():
            return
        probe = block.previous()
        while probe.isValid() and not probe.isVisible():
            probe = probe.previous()
        if not probe.isValid():
            return
        moved = QTextCursor(probe)
        moved.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self.setTextCursor(moved)

    def _paint_section_breaks(self, painter: QPainter, viewport_rect) -> None:
        painter.save()
        pen = QPen(QColor("#cbd5e1"), 1.0, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        for block in self._visible_blocks():
            if not block.isVisible() or not is_section_break(block):
                continue
            rect = self.cursorRect(QTextCursor(block))
            y = rect.top() - 1.5
            if y < viewport_rect.top() - 4 or y > viewport_rect.bottom() + 4:
                continue
            painter.drawLine(QLineF(rect.left(), y, viewport_rect.right() - 8, y))
        painter.restore()

    def _nearest_fold_parent(self, block):
        """커서 줄을 품은 가장 가까운 토글이나 제목."""
        toggle = self._parent_toggle(block)
        heading = None
        probe = block.previous()
        while probe.isValid():
            if self.heading_level(probe) and self.page_id_of_block(probe) is None:
                heading = probe
                break
            probe = probe.previous()
        if toggle is not None and (heading is None or toggle.position() > heading.position()):
            return toggle
        return heading

    def fold_nearest_parent(self) -> bool:
        """제목·토글이 아닌 줄에서 누른 접기: 이 줄을 품은 제목·토글을 접는다."""
        parent = self._nearest_fold_parent(self.textCursor().block())
        if parent is None:
            return False
        if self._is_toggle_block(parent):
            self.fold_toggle(parent)
            return True
        return self.fold_heading(parent)

    def fold_summary(self) -> tuple[bool, bool]:
        """(접을 수 있는 제목·토글이 있는가, 모두 접혀 있는가)."""
        found = False
        for block in self._iter_blocks():
            if self._is_toggle_block(block):
                found = True
                if self._toggle_is_open(block):
                    return True, False
            elif (self.heading_level(block) and self.page_id_of_block(block) is None
                  and block.text().removeprefix(HEADING_FOLDED_PREFIX).strip()):
                found = True
                if not self._heading_is_folded(block):
                    return True, False
        return found, found

    def exit_current_fold(self) -> bool:
        block = self.textCursor().block()
        if self.heading_level(block) or self._is_toggle_block(block):
            return self.toggle_current_fold()
        toggle = self._parent_toggle(block)
        heading = None
        probe = block.previous()
        while probe.isValid():
            if self.heading_level(probe):
                heading = probe
                break
            probe = probe.previous()
        parent = toggle if toggle is not None and (
            heading is None or toggle.position() > heading.position()
        ) else heading
        if parent is None:
            return False
        self.setTextCursor(QTextCursor(parent))
        self.ensureCursorVisible()
        return True

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
        folded_heading = None
        changed = False
        block = document.begin()
        while block.isValid():
            indent = self._block_indent(block)
            level = self.heading_level(block)
            if (folded_heading is not None and level and level <= folded_heading[0]
                    and indent <= folded_heading[1]):
                folded_heading = None
            if (folded_heading is not None and not level and indent <= folded_heading[1]
                    and is_section_break(block)):
                # 제목 끝 표시가 있는 줄부터는 제목 밖이다.
                folded_heading = None
            if hidden_depth is not None and indent <= hidden_depth:
                hidden_depth = None
            visible = hidden_depth is None and folded_heading is None
            if block.isVisible() != visible:
                block.setVisible(visible)
                changed = True
            if visible and level and self._heading_is_folded(block):
                folded_heading = (level, indent)
            if visible and self._is_toggle_block(block) and not self._toggle_is_open(block):
                hidden_depth = indent
            block = block.next()
        if self._sync_folded_table_frames():
            changed = True
        if changed:
            document.markContentsDirty(0, max(1, document.characterCount()))
            self.viewport().update()

    def _sync_folded_table_frames(self) -> bool:
        """Hide the empty grid when every cell belongs to a folded section."""
        tables: dict[int, tuple[object, bool]] = {}
        block = self.document().begin()
        while block.isValid():
            table = self._table_at_block(block)
            if table is not None:
                key = int(table.firstPosition())
                previous = tables.get(key)
                tables[key] = (
                    table,
                    block.isVisible() or (previous[1] if previous is not None else False),
                )
            block = block.next()
        changed = False
        for key, (table, any_visible) in tables.items():
            if not any_visible and key not in self._folded_table_formats:
                self._folded_table_formats[key] = QTextTableFormat(table.format())
                hidden = QTextTableFormat(table.format())
                hidden.setBorder(0)
                hidden.setCellPadding(0)
                hidden.setCellSpacing(0)
                hidden.setWidth(QTextLength(QTextLength.Type.FixedLength, 0))
                table.setFormat(hidden)
                changed = True
            elif any_visible and key in self._folded_table_formats:
                table.setFormat(self._folded_table_formats.pop(key))
                changed = True
        live = set(tables)
        for key in set(self._folded_table_formats).difference(live):
            self._folded_table_formats.pop(key, None)
        return changed

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
        return self.block_commands.execute(
            "move_to", source_at=source_at, target_at=target_at, inside=inside,
        )

    def move_line(self, source_at: int, target_at: int, inside: bool = False) -> bool:
        """줄 하나(토글이면 그 안까지)를 다른 자리로 옮긴다."""
        document = self.document()
        source = document.findBlock(source_at)
        target = document.findBlock(target_at)
        if not source.isValid() or not target.isValid():
            return False
        family = self._block_family(source)
        current_ids = block_ids(document)
        source_ids = [current_ids[block.blockNumber()] for block in family]
        source_pins = [is_pinned(block) for block in family]
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
        self._identity_reordered = True
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
            set_ids_from(document, start, source_ids)
            moved_block = document.findBlock(start)
            for pinned in source_pins:
                set_pinned(moved_block, pinned)
                moved_block = moved_block.next()
            if inside:
                # 토글 안내가 떠 있던 빈 줄은 이제 쓸모가 없다.  같이 걷어낸다.
                # 옮기면서 자리가 밀렸으므로 지금 자리로 다시 찾는다.
                self._drop_empty_placeholder(document.findBlock(landing_at))
        finally:
            cut.endEditBlock()
            self._identity_reordered = False
        self._refresh_toggle_visibility()
        return True

    def begin_block_selection(self, block) -> None:
        self._block_selecting = True
        self.block_selection.begin_drag(block, additive=True)

    def update_block_selection(self, block) -> None:
        if self._block_selecting:
            self.block_selection.update_drag(block)

    def finish_block_selection(self) -> None:
        self._block_selecting = False
        self.block_selection.finish_drag()

    def mime_for_blocks(self, blocks) -> QMimeData | None:
        """Build one ordered clipboard payload from non-contiguous blocks."""
        blocks = sorted(
            {block.position(): block for block in blocks if block is not None and block.isValid()}.values(),
            key=lambda block: block.position(),
        )
        if not blocks:
            return None
        carrier = QTextDocument()
        self._configure_document(carrier)
        writer = QTextCursor(carrier)
        metadata = []
        for index, block in enumerate(blocks):
            if index:
                writer.insertBlock()
            selected = QTextCursor(block)
            selected.movePosition(
                QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
            )
            writer.insertFragment(QTextDocumentFragment(selected))
            fmt = block.blockFormat()
            metadata.append({
                "indent": int(fmt.indent()),
                "heading": int(self.heading_level(block)),
                "user_state": int(block.userState()),
            })
        html = carrier.toHtml()
        mime = QMimeData()
        mime.setHtml(html)
        mime.setText("\n".join(block.text() for block in blocks))
        page_snapshot = {"version": 1, "roots": [], "notes": [], "attachments": []}
        attachments = []
        if self.store is not None:
            page_ids = self._page_ids_for_html(html)
            page_snapshot = NoteCloneService(self.store).snapshot(page_ids)
            for attachment_id in attachment_ids_from_html(html):
                row = self.store.attachment(attachment_id)
                if row is not None:
                    attachments.append(dict(row))
        set_json(mime, BLOCK_MIME, {
            "version": 1,
            "kind": "blocks",
            "html": html,
            "text": mime.text(),
            "blocks": metadata,
            "pages": page_snapshot,
            "attachments": attachments,
        })
        return mime

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
        source_all_ids = block_ids(self.document())
        moved_ids = [source_all_ids[block.blockNumber()] for block in family]
        moved_pins = [is_pinned(block) for block in family]
        moved = cut.selection().toHtml()
        carrier = QTextDocument()
        target_content = str(row["content"] or "")
        carrier.setHtml(target_content)
        load_ids(carrier, target_content)
        load_pins(carrier, target_content)
        landing = QTextCursor(carrier)
        landing.movePosition(QTextCursor.MoveOperation.End)
        if carrier.characterCount() > 1:
            landing.insertBlock()
        landing.insertHtml(moved)
        # Rich HTML transports visible format, not QTextBlockUserData. Reattach
        # identity/pin metadata to the appended family only when the boundary
        # survived the paste intact; otherwise let missing blocks get new IDs.
        appended = []
        candidate = carrier.lastBlock()
        for _ in family:
            if not candidate.isValid():
                break
            appended.append(candidate)
            candidate = candidate.previous()
        appended.reverse()
        existing = set(block_ids(carrier))
        existing.difference_update(
            getattr(block.userData(), "block_id", "") for block in appended
        )
        if (len(appended) == len(family)
                and [block.text() for block in appended] == [block.text() for block in family]
                and not existing.intersection(moved_ids)):
            set_ids_from(carrier, appended[0].position(), moved_ids)
            for block, pinned in zip(appended, moved_pins):
                if pinned:
                    set_pinned(block, True)
        target_html = with_ids(carrier.toHtml(), block_ids(carrier))
        target_html = with_pins(target_html, pinned_ids(carrier))
        self.store.update_note(page_id, content=target_html)
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
        template_matches = []
        if self.store is not None:
            normalized = query.casefold()
            template_query = "" if normalized in {"template", "템플릿"} else normalized
            template_mode = normalized.startswith("template") or normalized.startswith("템플릿")
            for row in self.store.memo_data.templates():
                trigger = str(row["trigger"])
                name = str(row["name"])
                if template_mode or not normalized or normalized in trigger.casefold() or normalized in name.casefold():
                    if template_mode and template_query and template_query not in trigger.casefold() and template_query not in name.casefold():
                        continue
                    template_matches.append((f"템플릿 · {name}", int(row["id"])))
        if not matches and not template_matches:
            self.close_insert_popup()
            return
        popup = self._ensure_insert_popup()
        popup.clear()
        for item, handler in matches:
            entry = QListWidgetItem(item_label(item))
            trigger = self.insert_preferences.triggers.get(item.item_id or item.method, item.typing)
            entry.setToolTip(item_tooltip(item, trigger))
            entry.setData(Qt.ItemDataRole.UserRole, item[2])
            popup.addItem(entry)
        for label, template_id in template_matches:
            entry = QListWidgetItem(label)
            entry.setToolTip("저장한 블록 템플릿을 새 UUID로 삽입합니다")
            entry.setData(Qt.ItemDataRole.UserRole, f"template:{template_id}")
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
        try:
            if callable(handler):
                handler()
            elif method.startswith("template:"):
                self._insert_template(int(method.split(":", 1)[1]))
        except ValueError as exc:
            QMessageBox.warning(self, "삽입할 수 없음", str(exc))
            return False
        return True

    def _insert_template(self, template_id: int) -> bool:
        row = self.store.conn.execute("SELECT * FROM memo_templates WHERE id=?", (int(template_id),)).fetchone()
        if row is None or int(row["payload_version"]) != 1:
            raise ValueError("지원하지 않는 템플릿 형식입니다.")
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError as exc:
            raise ValueError("템플릿 데이터를 읽을 수 없습니다.") from exc
        if not isinstance(payload, dict) or int(payload.get("version", 0)) != 1:
            raise ValueError("지원하지 않는 템플릿 형식입니다.")
        return self._paste_internal_blocks(payload)

    def save_selection_as_template(self) -> bool:
        if self.store is None:
            return False
        mime = (
            self.mime_for_blocks(self.block_commands.blocks())
            if self.block_selection.count() else self.createMimeDataFromSelection()
        )
        payload = get_json(mime, BLOCK_MIME) if mime is not None else None
        if payload is None:
            return False
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "블록 템플릿 저장", "템플릿 이름")
        if not ok or not name.strip():
            return False
        trigger, ok = QInputDialog.getText(self, "블록 템플릿 저장", "호출어 (/ 제외)")
        if not ok or not trigger.strip():
            return False
        try:
            self.store.memo_data.save_template(name, trigger, payload, payload_version=1)
        except ValueError as exc:
            QMessageBox.warning(self, "템플릿을 저장할 수 없음", str(exc))
            return False
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
        """모든 토글과 제목 범위를 한 번에 접거나 편다."""
        blocks = [block for block in self._iter_blocks()
                  if self._is_toggle_block(block) or (
                      self.heading_level(block) and self.page_id_of_block(block) is None
                      and block.text().removeprefix(HEADING_FOLDED_PREFIX).strip()
                  )]
        if not blocks:
            return False
        opening = not any(
            self._toggle_is_open(block) if self._is_toggle_block(block)
            else not self._heading_is_folded(block)
            for block in blocks
        )
        transaction = QTextCursor(self.document())
        transaction.beginEditBlock()
        try:
            for block in blocks:
                if self._is_toggle_block(block) and self._toggle_is_open(block) != opening:
                    self._set_toggle_open(block, opening)
                elif self.heading_level(block) and self._heading_is_folded(block) == opening:
                    self._set_heading_folded(block, not opening)
        finally:
            transaction.endEditBlock()
        self._refresh_toggle_visibility()
        return opening

    def apply_line_spacing(self, multiplier: float) -> bool:
        """Apply a proportional line height to selected paragraphs in one undo."""
        if self.character_selection.count():
            return False
        percent = int(round(float(multiplier) * 100))
        if percent not in {100, 115, 150, 200}:
            return False
        blocks = self.block_commands.blocks()
        if not blocks:
            return False
        transaction = QTextCursor(self.document())
        transaction.beginEditBlock()
        try:
            for block in blocks:
                cursor = QTextCursor(block)
                fmt = block.blockFormat()
                fmt.setLineHeight(percent, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
                cursor.setBlockFormat(fmt)
        finally:
            transaction.endEditBlock()
        self.setFocus()
        return True

    def selected_line_spacing(self) -> float | None:
        values = set()
        for block in self.block_commands.blocks():
            value = int(block.blockFormat().lineHeight())
            values.add(round((value if value > 0 else 100) / 100, 2))
        return next(iter(values)) if len(values) == 1 else None

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
    def page_id_at(self, anchor: str | None = None) -> int | None:
        # Keep the old class-style numeric parser call working for extensions.
        owner = self if isinstance(self, RichMemoTextEdit) else None
        value = self if owner is None and anchor is None else anchor
        match = _PAGE_ID_RE.fullmatch(str(value or "").strip())
        if match is not None:
            return int(match.group(1))
        match = _PAGE_SYNC_RE.fullmatch(str(value or "").strip())
        if match is None or owner is None or owner.store is None:
            return None
        row = owner.store.note_by_sync_id(match.group(1), include_trashed=True)
        return None if row is None else int(row["id"])

    def _note_href(self, note_id: int) -> str:
        row = self.store.note(int(note_id)) if self.store is not None else None
        return (
            f"{PAGE_URL_PREFIX}v2/{row['sync_id']}" if row is not None and str(row["sync_id"] or "")
            else f"{PAGE_URL_PREFIX}{int(note_id)}"
        )

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
        self.character_selection.clear()
        cursor = self.textCursor()
        self._write_link_run(cursor, note_id, title or DEFAULT_PAGE_TITLE)
        self.setTextCursor(cursor)
        self.setCurrentCharFormat(QTextCharFormat())
        self.setFocus()
        return True

    def _write_link_run(self, cursor, note_id: int, title: str) -> None:
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(self._note_href(note_id))
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
        self.character_selection.clear()
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
        fmt.setAnchorHref(self._note_href(page_id))
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
        cursor = self.cursorForPosition(point.toPoint())
        return self._valid_internal_link_at_position(cursor.position())

    def _internal_link_runs(self, block):
        """Yield contiguous internal-anchor runs in *block* with their text."""
        runs = []
        iterator = block.begin()
        current = None
        while not iterator.atEnd():
            fragment = iterator.fragment()
            iterator += 1
            if not fragment.isValid():
                continue
            href = str(fragment.charFormat().anchorHref() or "")
            note_id = self.page_id_at(href)
            start = fragment.position()
            end = start + fragment.length()
            if note_id is None:
                current = None
                continue
            if current is not None and current[2] == start and current[3] == href:
                current[2] = end
                current[4] += fragment.text()
            else:
                current = [start, note_id, end, href, fragment.text()]
                runs.append(current)
        return runs

    @staticmethod
    def _is_valid_internal_link_text(text: str) -> bool:
        return str(text).startswith((PAGE_MARK, LINK_MARK))

    def _valid_internal_link_at_position(self, position: int) -> int | None:
        block = self.document().findBlock(max(0, int(position)))
        if not block.isValid():
            return None
        for start, note_id, end, _href, text in self._internal_link_runs(block):
            if start <= position < end and self._is_valid_internal_link_text(text):
                return int(note_id)
        return None

    def _block_link_at_position(self, position: int) -> tuple[int, str] | None:
        block = self.document().findBlock(max(0, int(position)))
        if not block.isValid():
            return None
        runs = []
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            iterator += 1
            if not fragment.isValid():
                continue
            target = parse_block_url(fragment.charFormat().anchorHref())
            if target is None:
                continue
            memo_ref, block_id = target
            if isinstance(memo_ref, str):
                row = self.store.note_by_sync_id(memo_ref) if self.store is not None else None
                if row is None:
                    continue
                target = (int(row["id"]), block_id)
            start = fragment.position()
            end = start + fragment.length()
            if runs and runs[-1][1] == start and runs[-1][2] == target:
                runs[-1] = (runs[-1][0], end, target, runs[-1][3] + fragment.text())
            else:
                runs.append((start, end, target, fragment.text()))
        for start, end, target, text in runs:
            if start <= position < end and text.startswith(LINK_MARK):
                return target
        return None

    def _remove_orphan_internal_links(self) -> None:
        """Strip stale toma-note anchors that no longer carry a link marker."""
        stale = []
        block = self.document().begin()
        while block.isValid():
            for start, _note_id, end, _href, text in self._internal_link_runs(block):
                if not self._is_valid_internal_link_text(text):
                    stale.append((start, end))
            block = block.next()
        if not stale:
            return
        blocked = self.blockSignals(True)
        try:
            for start, end in stale:
                cursor = QTextCursor(self.document())
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setAnchor(False)
                fmt.setAnchorHref("")
                fmt.setFontUnderline(False)
                cursor.mergeCharFormat(fmt)
        finally:
            self.blockSignals(blocked)

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

    def _heading_marker_rect(self, block) -> QRectF:
        glyph = self.cursorRect(QTextCursor(block))
        left = max(0.0, glyph.left() - 18)
        return QRectF(left, glyph.top(), 18.0, max(glyph.height(), 20))

    def _heading_block_at(self, point):
        for block in self._visible_blocks():
            if block.isVisible() and self.heading_level(block) and self.page_id_of_block(block) is None:
                if self._heading_marker_rect(block).contains(point):
                    return block
        return None

    # ------------------------------------------------------- 마우스 올림 --
    def _marker_block_at(self, point):
        """마우스 밑에 눌러서 동작하는 표시가 있으면 그 줄을 돌려준다."""
        return self._toggle_block_at(point) or self._heading_block_at(point) or self._checklist_block_at(point)

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
        if self.heading_level(block):
            return self._heading_marker_rect(block)
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
        if (self._character_press_point is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            if ((event.position().toPoint() - self._character_press_point).manhattanLength()
                    > QApplication.startDragDistance()):
                self._character_dragging = True
            if self._character_dragging:
                cursor = self.textCursor()
                cursor.clearSelection()
                self.setTextCursor(cursor)
                event.accept()
                return
        if (self._left_press_point is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._left_press_point).manhattanLength()
                > QApplication.startDragDistance()):
            self._left_press_dragged = True
        if self._block_selecting and event.buttons() & Qt.MouseButton.LeftButton:
            self.update_block_selection(self.cursorForPosition(event.position().toPoint()).block())
            event.accept()
            return
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
        annotation = self.annotation_at_position(
            self.cursorForPosition(event.position().toPoint()).position()
        )
        if annotation is not None:
            if self.viewport().cursor().shape() != Qt.CursorShape.PointingHandCursor:
                self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.showText(
                event.globalPosition().toPoint(), str(annotation.get("comment") or "주석"),
                self.viewport(), self.viewport().rect(), 2500,
            )
            return
        if block is None and (
            self._page_link_at(event.position()) is not None
            or self._block_link_at_position(
                self.cursorForPosition(event.position().toPoint()).position()
            ) is not None
        ):
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
        self._paint_section_breaks(painter, viewport_rect)
        self._paint_quote_bars(painter, viewport_rect)
        self._paint_heading_markers(painter, viewport_rect)
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

    def _paint_heading_markers(self, painter: QPainter, viewport_rect) -> None:
        painter.save()
        painter.setPen(QColor("#64748b"))
        for block in self._visible_blocks():
            if not block.isVisible() or not self.heading_level(block):
                continue
            if self.page_id_of_block(block) is not None:
                continue
            rect = self._heading_marker_rect(block)
            if rect.intersects(QRectF(viewport_rect)):
                marker = "▶" if self._heading_is_folded(block) else "▾"
                painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), marker)
        painter.restore()

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
        self.character_selection.clear()
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
        self.character_selection.clear()
        self._move_caret_past_table_boundary()
        payload = get_json(source, BLOCK_MIME)
        if payload is not None and self._paste_internal_blocks(payload):
            return
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and self.insert_image(image):
                return
        for url in source.urls() if source.hasUrls() else []:
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}:
                if self.insert_image_file(Path(url.toLocalFile())):
                    return
        document_paths = [
            Path(url.toLocalFile()) for url in source.urls() if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.casefold() in {".md", ".markdown", ".html", ".htm", ".txt"}
        ] if source.hasUrls() else []
        if document_paths:
            self.structured_files_dropped.emit(document_paths)
            return
        if source.hasHtml():
            html = self._html_for_paste(source)
            first_block_format = self._first_html_block_format(html)
            transaction = QTextCursor(self.document())
            transaction.beginEditBlock()
            try:
                self._paste_into_lone_empty_toggle(
                    lambda: self.textCursor().insertHtml(html), first_block_format,
                )
            finally:
                transaction.endEditBlock()
            # QTextDocument는 표 조각의 최종 경계 커서를 편집 블록이 닫힐 때
            # 확정한다.  그 뒤에 확인해야 바깥 표의 끝을 놓치지 않는다.
            self._move_caret_past_table_boundary(join_previous_edit=True)
            return
        self._paste_into_lone_empty_toggle(lambda: super(RichMemoTextEdit, self).insertFromMimeData(source))

    def createMimeDataFromSelection(self) -> QMimeData:
        mime = super().createMimeDataFromSelection()
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return mime
        html = str(mime.html() or "")
        page_snapshot = {"version": 1, "roots": [], "notes": [], "attachments": []}
        attachments = []
        if self.store is not None:
            page_ids = self._page_ids_for_html(html)
            page_snapshot = NoteCloneService(self.store).snapshot(page_ids)
            for attachment_id in attachment_ids_from_html(html):
                row = self.store.attachment(attachment_id)
                if row is not None:
                    attachments.append(dict(row))
        set_json(mime, BLOCK_MIME, {
            "version": 1,
            "kind": "blocks",
            "html": html,
            "text": str(mime.text() or ""),
            "blocks": selected_block_metadata(cursor, self.heading_level),
            "pages": page_snapshot,
            "attachments": attachments,
        })
        return mime

    def _page_ids_for_html(self, html: str) -> list[int]:
        if self.store is None:
            return []
        found = [value for value in page_ids_from_html(html) if self.store.note(value) is not None]
        for sync_id in page_sync_ids_from_html(html):
            row = self.store.note_by_sync_id(sync_id)
            if row is not None:
                found.append(int(row["id"]))
        return list(dict.fromkeys(found))

    @staticmethod
    def _set_block_heading_metadata(block, level: int) -> None:
        cursor = QTextCursor(block)
        fmt = block.blockFormat()
        if level in HEADING_STYLES:
            _size, _spacing, top, bottom = HEADING_STYLES[level]
            fmt.setTopMargin(top)
            fmt.setBottomMargin(bottom)
            fmt.setProperty(HEADING_LEVEL_PROPERTY, level)
            fmt.setHeadingLevel(level)
        else:
            fmt.clearProperty(HEADING_LEVEL_PROPERTY)
            fmt.setHeadingLevel(0)
        cursor.setBlockFormat(fmt)

    def _paste_internal_blocks(self, payload: dict) -> bool:
        html = str(payload.get("html") or "")
        if not html:
            return False
        normalized = QMimeData()
        normalized.setHtml(html)
        normalized.setText(str(payload.get("text") or ""))
        html = self._html_for_paste(normalized)
        first_block_format = self._first_html_block_format(html)
        service = NoteCloneService(self.store) if self.store is not None else None
        page_batch = {"notes": [], "attachments": [], "id_map": {}, "roots": []}
        loose_rows, loose_map = [], {}
        before = int(self.document().availableUndoSteps())
        try:
            if service is not None and self.note_id is not None:
                page_snapshot = payload.get("pages") or {}
                root_parents = {
                    int(value): int(self.note_id) for value in page_snapshot.get("roots") or []
                }
                page_batch = service.clone(page_snapshot, root_parents=root_parents)
                loose_rows, loose_map = service.clone_attachments(
                    payload.get("attachments") or [], int(self.note_id),
                )
            html = rewrite_cloned_content(html, page_batch.get("id_map") or {}, loose_map)
            start = self.textCursor().selectionStart()
            paste_toggle = None if self.textCursor().hasSelection() else self._parent_toggle(
                self.textCursor().block()
            )
            if paste_toggle is None and not self.textCursor().hasSelection():
                paste_toggle = self._toggle_for_lone_empty_child(self.textCursor().block())
            transaction = QTextCursor(self.document())
            transaction.beginEditBlock()
            try:
                self._paste_into_lone_empty_toggle(
                    lambda: self.textCursor().insertHtml(html), first_block_format,
                )
                apply_block_metadata(
                    self.document(), start, payload.get("blocks") or [],
                    self._set_block_heading_metadata,
                )
                if paste_toggle is not None:
                    self._keep_pasted_blocks_inside_toggle(
                        paste_toggle, start, self.textCursor().position(),
                    )
            finally:
                transaction.endEditBlock()
        except Exception:
            if service is not None:
                cleanup = {
                    "notes": page_batch.get("notes") or [],
                    "attachments": [*(page_batch.get("attachments") or []), *loose_rows],
                }
                service.remove_batch(cleanup)
            raise
        batch = {
            "notes": page_batch.get("notes") or [],
            "attachments": [*(page_batch.get("attachments") or []), *loose_rows],
        }
        after = int(self.document().availableUndoSteps())
        if service is not None and (batch["notes"] or batch["attachments"]):
            self._composite_edits.append({"before": before, "after": after, "batch": batch, "active": True})
        self._refresh_known_pages()
        return True

    def _undo_composite_or_document(self) -> None:
        if callable(self.external_undo_handler) and self.external_undo_handler():
            return
        steps = int(self.document().availableUndoSteps())
        entry = next(
            (value for value in reversed(self._composite_edits)
             if value["active"] and int(value["after"]) == steps),
            None,
        )
        self._page_sync_timer.stop()
        self.undo()
        if entry is not None and self.store is not None:
            if entry.get("batch") is not None:
                NoteCloneService(self.store).remove_batch(entry["batch"])
            self._apply_note_states(entry.get("before_states") or [])
            entry["active"] = False
        self._refresh_known_pages()

    def _redo_composite_or_document(self) -> None:
        if callable(self.external_redo_handler) and self.external_redo_handler():
            return
        steps = int(self.document().availableUndoSteps())
        entry = next(
            (value for value in self._composite_edits
             if not value["active"] and int(value["before"]) == steps),
            None,
        )
        if entry is not None and self.store is not None:
            if entry.get("batch") is not None:
                NoteCloneService(self.store).restore_batch(entry["batch"])
            self._apply_note_states(entry.get("after_states") or [])
            entry["active"] = True
        self.redo()
        self._refresh_known_pages()

    def _apply_note_states(self, states) -> None:
        if self.store is None or not states:
            return
        for state in states:
            self.store.set_note_embedded(int(state["id"]), bool(state["embedded"]))

    @staticmethod
    def _clear_anchor_in_cursor(cursor: QTextCursor) -> None:
        fmt = QTextCharFormat()
        fmt.setAnchor(False)
        fmt.setAnchorHref("")
        fmt.setFontUnderline(False)
        cursor.mergeCharFormat(fmt)

    def remove_linked_features(self, blocks, links_only: bool = False, exact_range=None) -> bool:
        """Remove structural behaviour while preserving ordinary content and pages."""
        blocks = sorted(
            {block.position(): block for block in blocks if block is not None and block.isValid()}.values(),
            key=lambda block: block.position(),
        )
        if not blocks:
            return False
        before_steps = int(self.document().availableUndoSteps())
        before_states, after_states = [], []
        transaction = QTextCursor(self.document())
        transaction.beginEditBlock()
        try:
            for original in blocks:
                block = self.document().findBlock(original.position())
                if not block.isValid():
                    continue
                page_id = self.page_id_of_block(block)
                if page_id is not None and self.store is not None:
                    row = self.store.note(page_id)
                    if row is not None:
                        before_states.append({"id": page_id, "embedded": int(row["embedded"] or 0)})
                        after_states.append({"id": page_id, "embedded": 0})
                if not links_only:
                    if self._is_toggle_block(block):
                        self._remove_toggle_prefix(block)
                        block = self.document().findBlock(block.position())
                    if self._is_checklist_block(block):
                        self._remove_checklist_prefix(block)
                    for prefix in (CALLOUT_PREFIX, QUOTE_PREFIX, CODE_PREFIX):
                        if block.text().startswith(prefix):
                            self._drop_line_prefix(block, prefix)
                            break
                    if self.is_divider_block(block):
                        wipe = QTextCursor(block)
                        wipe.movePosition(
                            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
                        )
                        wipe.removeSelectedText()
                    fmt = block.blockFormat()
                    fmt.setObjectIndex(-1)
                    fmt.clearProperty(HEADING_LEVEL_PROPERTY)
                    fmt.clearProperty(PIN_PROPERTY)
                    fmt.setHeadingLevel(0)
                    fmt.clearBackground()
                    fmt.setLeftMargin(0)
                    fmt.setTopMargin(0)
                    fmt.setBottomMargin(0)
                    QTextCursor(block).setBlockFormat(fmt)
                marker_selected = exact_range is None or (
                    int(exact_range[0]) <= block.position() < int(exact_range[1])
                )
                run = QTextCursor(block)
                if exact_range is None:
                    run.movePosition(
                        QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
                    )
                else:
                    run.setPosition(max(block.position(), int(exact_range[0])))
                    run.setPosition(
                        min(block.position() + block.length() - 1, int(exact_range[1])),
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                if marker_selected and page_id is not None and block.text().startswith(PAGE_MARK):
                    run.setPosition(block.position())
                    run.movePosition(
                        QTextCursor.MoveOperation.NextCharacter,
                        QTextCursor.MoveMode.KeepAnchor, len(PAGE_MARK),
                    )
                    run.removeSelectedText()
                    block = self.document().findBlock(block.position())
                    run = QTextCursor(block)
                    run.movePosition(
                        QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
                    )
                elif marker_selected and block.text().startswith(LINK_MARK):
                    run.setPosition(block.position())
                    run.movePosition(
                        QTextCursor.MoveOperation.NextCharacter,
                        QTextCursor.MoveMode.KeepAnchor, len(LINK_MARK),
                    )
                    run.removeSelectedText()
                    block = self.document().findBlock(block.position())
                    run = QTextCursor(block)
                    run.movePosition(
                        QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
                    )
                self._clear_anchor_in_cursor(run)
        finally:
            transaction.endEditBlock()
        after_steps = int(self.document().availableUndoSteps())
        if before_states:
            self._apply_note_states(after_states)
            self._composite_edits.append({
                "before": before_steps,
                "after": after_steps,
                "before_states": before_states,
                "after_states": after_states,
                "active": True,
            })
        self._refresh_known_pages()
        return True

    @staticmethod
    def _visual_character_format(source: QTextCharFormat) -> QTextCharFormat:
        source = QTextCharFormat(source)
        fmt = QTextCharFormat()
        fmt.setFont(source.font())
        if source.foreground().style() != Qt.BrushStyle.NoBrush:
            fmt.setForeground(source.foreground())
        if source.background().style() != Qt.BrushStyle.NoBrush:
            fmt.setBackground(source.background())
        return fmt

    def _copy_or_apply_character_format(self) -> None:
        cursor = self.textCursor()
        if self.character_selection.count():
            if self._copied_character_format is None:
                self._show_format_feedback("복사된 서식이 없습니다")
            else:
                self.apply_character_format(self._copied_character_format)
                self._show_format_feedback("서식 적용됨")
            return
        if cursor.hasSelection() and self._copied_character_format is not None:
            cursor.mergeCharFormat(self._copied_character_format)
            self.mergeCurrentCharFormat(self._copied_character_format)
            self._show_format_feedback("서식 적용됨")
            return
        if cursor.hasSelection():
            self._show_format_feedback("복사된 서식이 없습니다")
            return
        probe = QTextCursor(cursor)
        if probe.atBlockEnd() and probe.position() > probe.block().position():
            probe.movePosition(QTextCursor.MoveOperation.PreviousCharacter)
        self._copied_character_format = self._visual_character_format(probe.charFormat())
        self._show_format_feedback("서식 복사됨")

    def _show_format_feedback(self, message: str) -> None:
        # One native, non-activating popup; subsequent Alt+C replaces it rather
        # than stacking modal dialogs over the editor.
        QToolTip.showText(
            self.mapToGlobal(QPoint(max(8, self.width() - 180), -12)),
            message, self, self.rect(), 1800,
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = QKeySequence(event.keyCombination()).toString()
        format_handler = getattr(self, "format_shortcut_handlers", {}).get(key)
        if format_handler is not None:
            format_handler()
            event.accept()
            return
        if (event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and getattr(self, "reminder_save_handler", None) is not None):
            self.reminder_save_handler()
            event.accept()
            return
        if event.key() == Qt.Key.Key_M and event.modifiers() == (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            self.add_current_character_selection()
            return
        if self.character_selection.count():
            if event.key() == Qt.Key.Key_Escape:
                self.character_selection.clear()
                return
            # The ranges are transient. Text and structural edits return to
            # ordinary single-caret editing; formatting shortcuts stay active.
            if event.modifiers() == Qt.KeyboardModifier.NoModifier or event.key() in (
                Qt.Key.Key_V, Qt.Key.Key_X, Qt.Key.Key_Backspace, Qt.Key.Key_Delete,
            ):
                self.character_selection.clear()
        if event.modifiers() == Qt.KeyboardModifier.AltModifier:
            if event.key() == Qt.Key.Key_Right and self.enter_current_fold():
                return
            if event.key() == Qt.Key.Key_Left and self.exit_current_fold():
                return
        if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down} and event.modifiers() == Qt.KeyboardModifier.AltModifier:
            command = "move_up" if event.key() == Qt.Key.Key_Up else "move_down"
            if self.block_commands.execute(command):
                return
        if event.key() == Qt.Key.Key_Escape and self.block_selection.count():
            self.block_selection.clear()
            return
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier and self.block_selection.count():
            self.block_commands.execute("copy")
            return
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.AltModifier:
            self._copy_or_apply_character_format()
            return
        if event.key() == Qt.Key.Key_Z and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._undo_composite_or_document()
            return
        if event.key() == Qt.Key.Key_Y and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._redo_composite_or_document()
            return
        if event.key() == Qt.Key.Key_Z and event.modifiers() == (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            self._redo_composite_or_document()
            return
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
        if event.key() in {Qt.Key.Key_Tab, Qt.Key.Key_Backtab} and self.block_selection.count():
            amount = 1 if event.key() == Qt.Key.Key_Tab else -1
            transaction = QTextCursor(self.document())
            transaction.beginEditBlock()
            try:
                for selected_block in self.block_selection.blocks():
                    if amount < 0 or self._block_indent(selected_block) < 8:
                        self._shift_indent(selected_block, amount)
            finally:
                transaction.endEditBlock()
            return
        if event.key() == Qt.Key.Key_V and event.modifiers() == (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            self.paste_as_plain_text()
            return
        boundary_keys = {
            Qt.Key.Key_Backspace, Qt.Key.Key_Delete,
            Qt.Key.Key_Return, Qt.Key.Key_Enter,
        }
        plain_typing = bool(event.text()) and not event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if (event.key() in boundary_keys or plain_typing) and self._is_table_boundary_block(
            self.textCursor().block()
        ):
            moved = self._move_caret_past_table_boundary()
            if moved and event.key() in boundary_keys:
                # 구조 경계에서 이 키를 그대로 넘기면 표를 합치거나 깨끗한 줄을
                # 즉시 다시 지운다.  첫 입력은 안전한 바깥 줄을 여는 데만 쓴다.
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
            if event.key() == Qt.Key.Key_Tab and self._block_indent(block) < 8:
                self._shift_indent(block, 1)
                return
            if event.key() == Qt.Key.Key_Backtab:
                if self._block_indent(block) == 0 and self.mark_section_break(block):
                    return
                self._shift_indent(block, -1)
                return
            if (event.key() == Qt.Key.Key_Backspace and offset == 0
                    and is_section_break(block) and self.clear_section_break(block)):
                return
        if not cursor.hasSelection() and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if self.heading_level(block):
                if self._heading_is_folded(block):
                    self._open_line_after_folded_heading(block)
                    return
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
        if not cursor.hasSelection() and not block.text().strip() and event.key() in {
            Qt.Key.Key_Backspace, Qt.Key.Key_Delete,
        }:
            parent_toggle = self._parent_toggle(block)
            if parent_toggle is not None:
                if len(list(self._toggle_children(parent_toggle))) == 1:
                    self._remove_toggle_prefix(parent_toggle)
                else:
                    restore_at = parent_toggle.position() + parent_toggle.length() - 1
                    self._delete_empty_block(block)
                    restored = QTextCursor(self.document())
                    restored.setPosition(restore_at)
                    self.setTextCursor(restored)
                return
            if event.key() == Qt.Key.Key_Backspace:
                previous = block.previous()
                preceding_toggle = self._toggle_for_lone_empty_child(previous)
                if (
                    preceding_toggle is not None
                    and self._block_indent(block) <= self._block_indent(preceding_toggle)
                ):
                    self._delete_empty_block_and_restore(block, preceding_toggle)
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
        point_cursor = self.cursorForPosition(event.pos())
        point_block = point_cursor.block()
        if self.character_selection.count():
            if self.character_selection.contains(point_cursor.position()):
                menu = QMenu(self)
                heading = menu.addAction(
                    f"{self.character_selection.count()}개 글자 구간 선택 · 서식 도구로 일괄 적용"
                )
                heading.setEnabled(False)
                menu.addAction("선택 글자 링크 기능 해제", self.unlink_selected_character_ranges)
                menu.addAction("선택 해제", self.character_selection.clear)
                menu.exec(self._context_menu_position(menu, event.globalPos()))
                return
            self.character_selection.clear()
        if self.block_selection.count() and not self.block_selection.contains(point_block):
            self.block_selection.select_only(point_block)
        elif not self.block_selection.count():
            current = self.textCursor()
            if not current.hasSelection() or not (
                current.selectionStart() <= point_cursor.position() <= current.selectionEnd()
            ):
                self.setTextCursor(point_cursor)
        block_mode = self.block_selection.count() > 0
        menu = QMenu(self) if block_mode else self.createStandardContextMenu()
        if block_mode:
            heading = menu.addAction(f"{self.block_selection.count()}개 블록 선택")
            heading.setEnabled(False)
        else:
            self._wire_context_history_actions(menu)
        menu.addSeparator()
        self._populate_block_context_menu(menu)
        if not block_mode:
            menu.addSeparator()
            paste_menu = menu.addMenu("붙여넣기 방식")
            source = QApplication.clipboard().mimeData()
            original = paste_menu.addAction("원본 서식 유지\tCtrl+V")
            original.setEnabled(bool(source and (source.hasText() or source.hasImage() or source.hasUrls())))
            original.triggered.connect(self.paste)
            matching = paste_menu.addAction("현재 서식에 맞추기")
            matching.setEnabled(bool(QApplication.clipboard().text()))
            matching.triggered.connect(self.paste_matching_format)
            plain = paste_menu.addAction("텍스트만\tCtrl+Shift+V")
            plain.setEnabled(bool(QApplication.clipboard().text()))
            plain.triggered.connect(self.paste_as_plain_text)
        menu.exec(self._context_menu_position(menu, event.globalPos()))

    def _context_menu_position(self, menu: QMenu, requested: QPoint) -> QPoint:
        if not (self.block_selection.count() or self.character_selection.count()
                or self.textCursor().hasSelection()):
            return requested
        screen = QApplication.screenAt(requested) or self.screen()
        bounds = screen.availableGeometry()
        size = menu.sizeHint()
        top_left = self.mapToGlobal(QPoint(0, 0))
        y = max(bounds.top(), min(requested.y(), bounds.bottom() - size.height()))
        right = top_left.x() + self.width() + 8
        if right + size.width() <= bounds.right():
            return QPoint(right, y)
        left = top_left.x() - size.width() - 8
        if left >= bounds.left():
            return QPoint(left, y)
        x = max(bounds.left(), min(requested.x(), bounds.right() - size.width()))
        below = top_left.y() + self.height() + 6
        if below + size.height() <= bounds.bottom():
            return QPoint(x, below)
        above = top_left.y() - size.height() - 6
        if above >= bounds.top():
            return QPoint(x, above)
        return QPoint(x, y)

    def toggle_selected_block_pins(self, _checked: bool = False) -> bool:
        blocks = self.block_commands.blocks()
        if not blocks:
            return False
        wanted = not all(is_pinned(block) for block in blocks)
        transaction = QTextCursor(self.document())
        transaction.beginEditBlock()
        try:
            for block in blocks:
                set_pinned(block, wanted)
        finally:
            transaction.endEditBlock()
        return True

    def _populate_block_context_menu(self, menu) -> None:
        block_menu = menu.addMenu("블록")
        for label, command in (
            ("위로 이동\tAlt+↑", "move_up"), ("아래로 이동\tAlt+↓", "move_down"),
            ("복사", "copy"), ("독립 복제", "duplicate"),
            ("내어쓰기", "outdent"), ("들여쓰기", "indent"),
            ("토글로 묶기", "group_toggle"), ("삭제", "delete"),
        ):
            action = block_menu.addAction(label)
            action.triggered.connect(lambda _checked=False, name=command: self.block_commands.execute(name))
        block_menu.addSeparator()
        template_action = block_menu.addAction("선택을 템플릿으로 저장")
        template_action.setEnabled(self.block_selection.count() > 0 or self.textCursor().hasSelection())
        template_action.triggered.connect(self.save_selection_as_template)
        pin = block_menu.addAction("본문 블록 고정")
        pin.setCheckable(True)
        pin.setChecked(all(is_pinned(block) for block in self.block_commands.blocks()))
        pin.triggered.connect(self.toggle_selected_block_pins)
        fold = block_menu.addAction("현재 제목·토글 접기/펴기\tCtrl+Alt+Space")
        fold.setEnabled(bool(self.heading_level(self.textCursor().block()) or self.current_block_is_toggle()))
        fold.triggered.connect(self.toggle_current_fold)
        block_menu.addAction("모두 접기/펴기\tCtrl+Shift+E", self.toggle_all_folds)
        convert_menu = menu.addMenu("블록 변환")
        for label, command in (
            ("본문", "body"), ("제목 1", "heading1"), ("제목 2", "heading2"),
            ("제목 3", "heading3"), ("제목 4", "heading4"),
            ("토글", "toggle"), ("체크리스트", "checklist"),
            ("글머리표", "bullet"), ("강조 상자", "callout"),
            ("인용문", "quote"), ("코드 줄", "code"),
        ):
            action = convert_menu.addAction(label)
            action.triggered.connect(lambda _checked=False, name=command: self.block_commands.execute(name))
        linked = menu.addAction("연동 기능 삭제")
        linked.triggered.connect(lambda: self.block_commands.execute("unlink_features"))
        blocks = self.block_commands.blocks()
        has_page = any(self.page_id_of_block(block) is not None for block in blocks)
        has_link = any(self._block_has_anchor(block) for block in blocks)
        if has_page or has_link:
            page_link_menu = menu.addMenu("페이지·링크")
            label = "페이지 연결 해제 (메모 유지)" if has_page else "링크 기능 해제 (글자 유지)"
            action = page_link_menu.addAction(label)
            action.triggered.connect(lambda: self.block_commands.execute("unlink_links"))

    @staticmethod
    def _block_has_anchor(block) -> bool:
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            iterator += 1
            if fragment.isValid() and fragment.charFormat().isAnchor():
                return True
        return False

    def _wire_context_history_actions(self, menu) -> None:
        """Route context-menu Undo/Redo through document and database history."""
        for action in menu.actions():
            shortcut = action.shortcut()
            hint = action.text().rsplit("\t", 1)[-1].replace(" ", "").upper()
            is_undo = (
                shortcut.matches(QKeySequence(QKeySequence.StandardKey.Undo))
                == QKeySequence.SequenceMatch.ExactMatch
                or hint == "CTRL+Z"
            )
            is_redo = (
                shortcut.matches(QKeySequence(QKeySequence.StandardKey.Redo))
                == QKeySequence.SequenceMatch.ExactMatch
                or hint in {"CTRL+Y", "CTRL+SHIFT+Z"}
            )
            if is_undo:
                action.triggered.disconnect()
                action.triggered.connect(self._undo_composite_or_document)
            elif is_redo:
                action.triggered.disconnect()
                action.triggered.connect(self._redo_composite_or_document)

    def paste_as_plain_text(self) -> None:
        self._paste_clipboard_text(match_current=False)

    def paste_matching_format(self) -> None:
        self._paste_clipboard_text(match_current=True)

    def _paste_clipboard_text(self, match_current: bool) -> None:
        text = QApplication.clipboard().text()
        if text:
            self._move_caret_past_table_boundary()
            fmt = QTextCharFormat(self.currentCharFormat()) if match_current else QTextCharFormat()
            # Neither text-only mode should carry a source anchor to another memo.
            fmt.setAnchor(False)
            fmt.setAnchorHref("")
            transaction = QTextCursor(self.document())
            transaction.beginEditBlock()
            try:
                def insert():
                    cursor = self.textCursor()
                    cursor.insertText(text, fmt)
                    self.setTextCursor(cursor)
                self._paste_into_lone_empty_toggle(insert)
            finally:
                transaction.endEditBlock()

    def open_current_link(self) -> bool:
        """Open a real internal link under the caret, never a stale anchor."""
        position = self.textCursor().position()
        target = self._block_link_at_position(position)
        if target is None and position > self.textCursor().block().position():
            target = self._block_link_at_position(position - 1)
        if target is not None:
            self.block_link_open_requested.emit(*target)
            return True
        note_id = self._valid_internal_link_at_position(position)
        if note_id is None and position > self.textCursor().block().position():
            note_id = self._valid_internal_link_at_position(position - 1)
        if note_id is None:
            return False
        self.page_open_requested.emit(note_id)
        return True

    def _place_caret_outside_toggles(self) -> bool:
        """마지막 줄 아래 빈 곳을 누르면 토글 밖에서 이어 쓰게 한다.

        토글에는 늘 안쪽 줄이 하나 있으므로, 그냥 두면 문서 끝을 눌렀을 때 커서가
        토글 안으로 들어가 밖에 글을 쓸 수 없다.
        """
        document = self.document()
        last = document.lastBlock()
        hidden_heading_tail = not last.isVisible() and self._heading_section_owner(last) is not None
        if (self._block_indent(last) == 0 and not self._is_toggle_block(last)
                and not hidden_heading_tail):
            return False
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        fmt = cursor.blockFormat()
        fmt.setIndent(0)
        if hidden_heading_tail:
            # 접힌 제목 아래 빈 곳을 눌렀다.  새 줄을 제목 밖에 두어야 쓴 글이 보인다.
            fmt.setProperty(SECTION_BREAK_PROPERTY, True)
        else:
            fmt.clearProperty(SECTION_BREAK_PROPERTY)
        cursor.setBlockFormat(fmt)
        cursor.setCharFormat(QTextCharFormat())
        self.setTextCursor(cursor)
        if hidden_heading_tail:
            self._refresh_toggle_visibility()
        self.setFocus()
        return True

    def _is_below_last_line(self, point) -> bool:
        block = self.document().lastBlock()
        while block.isValid() and not block.isVisible():
            block = block.previous()
        if not block.isValid():
            return False
        return point.y() > self.cursorRect(QTextCursor(block)).bottom()

    def _click_target_at(self, point) -> tuple[str, object] | None:
        block_target = self._block_link_at_position(self.cursorForPosition(point.toPoint()).position())
        if block_target is not None:
            return "block", block_target
        page_id = self._page_link_at(point)
        if page_id is not None:
            return "page", int(page_id)
        for name, finder in (
            ("toggle", self._toggle_block_at),
            ("heading", self._heading_block_at),
            ("checklist", self._checklist_block_at),
        ):
            block = finder(point)
            if block is not None:
                return name, block.position()
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.character_selection.clear()
            self._left_press_point = None
            self._left_press_target = None
            self._left_press_dragged = False
            cursor = self.textCursor()
            if cursor.hasSelection():
                cursor.clearSelection()
                self.setTextCursor(cursor)
            self.begin_block_selection(self.cursorForPosition(event.position().toPoint()).block())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.block_selection.clear()
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._character_press_point = event.position().toPoint()
                self._character_press_position = self.cursorForPosition(
                    event.position().toPoint()
                ).position()
                self._character_dragging = False
            else:
                self.character_selection.clear()
                self._character_press_point = None
                self._character_press_position = None
            self._left_press_point = event.position().toPoint()
            self._left_press_target = self._click_target_at(event.position())
            self._left_press_dragged = False
            grip = self.image_grip_at(event.position())
            if grip is not None:
                self._character_press_point = None
                self._character_press_position = None
                self.begin_image_resize(grip)
                self._claimed_press = True
                self._left_press_target = None
                event.accept()
                return
            if self._character_press_point is not None:
                # Ctrl+drag is wholly ours: QTextEdit must not receive a press
                # whose matching move/release is consumed by range selection.
                self._claimed_press = False
                self.setFocus()
                event.accept()
                return
        if (event.button() == Qt.MouseButton.LeftButton
                and not event.modifiers()
                and self._is_below_last_line(event.position())
                and self._place_caret_outside_toggles()):
            self._claimed_press = True
            self._left_press_target = None
            event.accept()
            return
        self._claimed_press = False
        super().mousePressEvent(event)

    def image_rect_left(self, position: int) -> float:
        spot = QTextCursor(self.document())
        spot.setPosition(position)
        return float(self.cursorRect(spot).left())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        character_press = (
            event.button() == Qt.MouseButton.LeftButton
            and self._character_press_point is not None
        )
        if event.button() == Qt.MouseButton.LeftButton and self._character_press_point is not None:
            if ((event.position().toPoint() - self._character_press_point).manhattanLength()
                    > QApplication.startDragDistance()):
                self._character_dragging = True
            if self._character_dragging and self._character_press_position is not None:
                cursor = QTextCursor(self.document())
                cursor.setPosition(self._character_press_position)
                cursor.setPosition(
                    self.cursorForPosition(event.position().toPoint()).position(),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                self.character_selection.add_cursor(cursor)
                caret = self.textCursor()
                caret.clearSelection()
                self.setTextCursor(caret)
                self._character_press_point = None
                self._character_press_position = None
                self._character_dragging = False
                self._left_press_point = None
                self._left_press_target = None
                self._left_press_dragged = False
                event.accept()
                return
            self._character_press_point = None
            self._character_press_position = None
            self._character_dragging = False
            caret = self.cursorForPosition(event.position().toPoint())
            self.setTextCursor(caret)
        clicked_target = None
        if event.button() == Qt.MouseButton.LeftButton:
            if (self._left_press_point is not None and not self._left_press_dragged
                    and (event.position().toPoint() - self._left_press_point).manhattanLength()
                    <= QApplication.startDragDistance()):
                target = self._click_target_at(event.position())
                if target == self._left_press_target:
                    clicked_target = target
            self._left_press_point = None
            self._left_press_target = None
            self._left_press_dragged = False
        if self._block_selecting:
            self.finish_block_selection()
            event.accept()
            return
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
        if clicked_target is not None:
            kind, value = clicked_target
            if kind == "page":
                self.page_open_requested.emit(value)
            elif kind == "block":
                self.block_link_open_requested.emit(*value)
            else:
                block = self.document().findBlock(value)
                if kind == "toggle":
                    self.fold_toggle(block)
                elif kind == "heading":
                    self.fold_heading(block)
                else:
                    self._toggle_check_state(block)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not event.modifiers():
            annotation = self.annotation_at_position(
                self.cursorForPosition(event.position().toPoint()).position()
            )
            if annotation is not None:
                self.annotation_activated.emit(int(annotation["id"]))
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            anchor = self.anchorAt(event.position().toPoint())
            url = self._safe_external_url(anchor)
            if url is not None:
                QDesktopServices.openUrl(url)
                event.accept()
                return
        if character_press:
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.text_format_bar.sync()

    def _place_gutter(self) -> None:
        frame = self.frameWidth()
        self.gutter.setGeometry(
            max(0, self.width() - frame - LineGutter.WIDTH), frame,
            LineGutter.WIDTH,
            max(0, self.height() - frame * 2 - self._block_action_bar_height),
        )

    def _set_block_action_bar_height(self, height: int) -> None:
        height = max(0, int(height))
        if self._block_action_bar_height == height:
            return
        self._block_action_bar_height = height
        self.setViewportMargins(0, 0, LineGutter.WIDTH, height)
        self._place_gutter()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_gutter()
        if hasattr(self, "block_action_bar"):
            self.block_action_bar.sync()
            self.character_action_bar.sync()
            self.text_format_bar.sync()
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
