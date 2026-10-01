"""메모 본문 편집기에 `@` 알림 입력을 붙인다.

쓰는 동안 인식한 조각을 칠하고 커서 아래에 해석을 한 줄로 보여 준다.  Enter를
치거나 커서가 다른 줄로 가면 칩으로 확정한다.  읽는 일과 칩을 만드는 일은
:mod:`memo_inline_alarm`이 맡고, 여기서는 편집기와의 접점만 다룬다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QLabel, QMenu, QTextEdit, QToolTip

from . import ko_schedule_parser
from .memo_inline_alarm import (
    ALARM_SCHEME, EXAMPLE_HINT, AlarmSpec, apply_phrase, chip_at, find_phrase,
    phrase_allowed, preview_text, utf16_len, utf16_offset_to_index,
)
from .recurrence import RULE_DAILY, RULE_MONTHLY, RULE_NONE, RULE_WEEKDAYS, RULE_WEEKLY
from .schedule_recurrence import DATETIME_FMT


TOKEN_BACKGROUNDS = {
    "date": QColor(223, 245, 223, 190),
    "time": QColor(219, 234, 254, 210),
    "reminder": QColor(254, 243, 199, 220),
    "repeat": QColor(237, 233, 254, 220),
}
AT_COLOR = QColor("#2f6fd6")
_RE_BARE_AT = re.compile(r"(?:^|\s)@\s?$")


class InlineAlarmController(QObject):
    def __init__(self, editor: QTextEdit):
        super().__init__(editor)
        self.editor = editor
        self._live: tuple[int, int] | None = None
        # 줄마다 사용자가 더블클릭으로 끈 조각.  (문서, 줄) → (구절 원문, 끈 조각)
        self._ignored: dict[tuple[int, int], tuple[str, set]] = {}
        self._dismissed: set[tuple[int, int, str]] = set()
        self._busy = False
        self._shown_phrase = None
        self.preview = QLabel(editor.viewport())
        self.preview.setObjectName("memoAlarmPreview")
        self.preview.setStyleSheet(
            "QLabel#memoAlarmPreview { background: #ffffff; color: #1d2430;"
            " border: 1px solid #c9d2df; border-radius: 6px; padding: 4px 8px; font-size: 12px; }"
        )
        self.preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.preview.hide()
        editor.textChanged.connect(self._on_text_changed)
        editor.cursorPositionChanged.connect(self._on_cursor_moved)
        editor.verticalScrollBar().valueChanged.connect(lambda _value: self._update_preview())
        editor.installEventFilter(self)

    # ---------------------------------------------------------------- 상태 --
    def reset(self) -> None:
        """새 내용을 불러왔다.  불러온 글자의 @를 확정하지 않도록 비운다."""
        self._live = None
        self._ignored.clear()
        self._dismissed.clear()
        self._shown_phrase = None
        self.preview.hide()

    def _doc_id(self) -> int:
        return id(self.editor.document())

    def _block_ignored(self, block) -> tuple:
        key = (self._doc_id(), block.blockNumber())
        stored = self._ignored.get(key)
        if stored is None:
            return ()
        old_text, spans = stored
        text = block.text()
        if old_text != text:
            spans = ko_schedule_parser.remap_ignored_spans(old_text, text, spans)
            self._ignored[key] = (text, spans)
        return tuple(sorted(spans))

    def _phrase_for(self, block):
        if not phrase_allowed(block):
            return None
        text = block.text()
        line_ignored = self._block_ignored(block)
        probe = find_phrase(text)
        if probe is None:
            return None
        offset = probe.at_index + 1
        ignored = tuple(
            (start - offset, end - offset, kind) for start, end, kind in line_ignored
            if start >= offset
        )
        phrase = find_phrase(text, ignored=ignored)
        if phrase is None:
            return None
        if (self._doc_id(), block.blockNumber(), phrase.source) in self._dismissed:
            return None
        return phrase

    def _current(self):
        cursor = self.editor.textCursor()
        block = cursor.block()
        phrase = self._phrase_for(block)
        if phrase is None:
            return block, None
        index = utf16_offset_to_index(block.text(), cursor.position() - block.position())
        if index <= phrase.at_index:
            return block, None
        return block, phrase

    def _live_block(self):
        if self._live is None or self._live[0] != self._doc_id():
            return None
        block = self.editor.document().findBlockByNumber(self._live[1])
        return block if block.isValid() else None

    # ---------------------------------------------------------------- 신호 --
    def _on_text_changed(self) -> None:
        if self._busy:
            return
        before = self._live
        block, phrase = self._current()
        if phrase is not None and self.editor.hasFocus():
            self._live = (self._doc_id(), block.blockNumber())
        elif self._live is not None and self._live == (self._doc_id(), block.blockNumber()):
            self._live = None
        if before is not None or self._live is not None:
            self._repaint()
        self._update_preview()

    def _on_cursor_moved(self) -> None:
        if self._busy:
            return
        live = self._live_block()
        if live is not None and live.blockNumber() != self.editor.textCursor().blockNumber():
            number = live.blockNumber()
            self._live = None
            # 마우스 클릭 처리 도중에 문서를 고치지 않도록 한 박자 늦춘다.
            QTimer.singleShot(0, lambda doc=self._doc_id(), n=number: self._commit_number(doc, n))
            self._repaint()
        self._update_preview()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.editor and event.type() == QEvent.Type.FocusOut:
            reason = event.reason()
            if reason not in (Qt.FocusReason.PopupFocusReason, Qt.FocusReason.ActiveWindowFocusReason):
                live = self._live_block()
                if live is not None:
                    self._live = None
                    self._commit_block(live)
            self.preview.hide()
        elif watched is self.editor and event.type() == QEvent.Type.FocusIn:
            self._update_preview()
        return False

    # ---------------------------------------------------------------- 확정 --
    def _commit_number(self, doc_id: int, number: int) -> None:
        if sip.isdeleted(self.editor) or doc_id != self._doc_id():
            return
        block = self.editor.document().findBlockByNumber(number)
        if block.isValid():
            self._commit_block(block)

    def _commit_block(self, block) -> bool:
        phrase = self._phrase_for(block)
        if phrase is None or not phrase.valid:
            self._repaint()
            return False
        self._busy = True
        try:
            result = apply_phrase(block, phrase)
        finally:
            self._busy = False
        self._ignored.pop((self._doc_id(), block.blockNumber()), None)
        self._repaint()
        self._update_preview()
        return result is not None

    def commit_current(self) -> bool:
        """Enter.  현재 줄의 구절을 칩으로 바꾸고 커서를 줄 끝 쪽에 둔다."""
        block, phrase = self._current()
        if phrase is None or not phrase.valid:
            return False
        cursor = self.editor.textCursor()
        at_end = cursor.atBlockEnd()
        self._busy = True
        try:
            result = apply_phrase(block, phrase)
        finally:
            self._busy = False
        if result is None:
            return False
        self._live = None
        self._ignored.pop((self._doc_id(), block.blockNumber()), None)
        moved = QTextCursor(self.editor.document())
        if at_end:
            moved.setPosition(block.position())
            moved.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        else:
            moved.setPosition(result[0])
        self.editor.setTextCursor(moved)
        self.editor.setCurrentCharFormat(QTextCharFormat())
        self._repaint()
        self._update_preview()
        return True

    # ---------------------------------------------------------------- 입력 --
    def wants_escape(self) -> bool:
        return self.preview.isVisible() and self._live_block() is not None

    def handle_key(self, event) -> bool:
        """처리했으면 True.  Enter는 확정만 하고 줄바꿈은 편집기에 맡긴다."""
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            popup = getattr(self.editor, "insert_popup_visible", None)
            if modifiers == Qt.KeyboardModifier.NoModifier and not (popup and popup()):
                self.commit_current()
            return False
        if key == Qt.Key.Key_Escape and self.wants_escape():
            block, phrase = self._current()
            if phrase is not None:
                self._dismissed.add((self._doc_id(), block.blockNumber(), phrase.source))
            self._live = None
            self.preview.hide()
            self._repaint()
            return True
        return False

    def handle_double_click(self, point: QPoint) -> bool:
        live = self._live_block()
        if live is None:
            return False
        position = self.editor.cursorForPosition(point).position()
        if self.editor.document().findBlock(position).blockNumber() != live.blockNumber():
            return False
        phrase = self._phrase_for(live)
        if phrase is None:
            return False
        text = live.text()
        index = utf16_offset_to_index(text, position - live.position())
        for span in phrase.spans:
            if span.start <= index < span.end:
                key = (self._doc_id(), live.blockNumber())
                _old, spans = self._ignored.get(key, (text, set()))
                if span.kind == "time":
                    # 시각은 범위 전체가 한 덩어리다.  하나만 끄면 남은 쪽이 다른 뜻이 된다.
                    spans |= {(s.start, s.end, s.kind) for s in phrase.spans if s.kind == "time"}
                else:
                    spans.add((span.start, span.end, span.kind))
                self._ignored[key] = (text, spans)
                self._repaint()
                self._update_preview()
                return True
        return False

    def handle_press(self, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton or event.modifiers():
            return False
        point = event.position().toPoint()
        anchor = str(self.editor.anchorAt(point) or "")
        if not anchor.startswith(ALARM_SCHEME):
            return False
        position = self.editor.cursorForPosition(point).position()
        found = chip_at(self.editor.document(), position)
        if found is None:
            return False
        self._show_chip_menu(found, self.editor.viewport().mapToGlobal(point))
        return True

    # ---------------------------------------------------------------- 칩 메뉴 --
    def _show_chip_menu(self, found, global_point) -> None:
        start, end, key, spec = found
        menu = QMenu(self.editor)
        edit_action = menu.addAction("시간 고치기")
        remove_action = menu.addAction("알림 지우기")
        menu.addSeparator()
        move_action = menu.addAction("일정으로 옮기기")
        can_move = getattr(self.editor, "store", None) is not None and hasattr(self.editor.store, "schedules")
        move_action.setEnabled(can_move)
        chosen = menu.exec(global_point)
        if chosen is edit_action:
            self._reopen_chip(start, end, spec)
        elif chosen is remove_action:
            self._remove_chip(start, end)
        elif chosen is move_action:
            self._move_to_schedule(start, end, spec)

    def _chip_cursor(self, start: int, end: int) -> QTextCursor:
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        return cursor

    def _reopen_chip(self, start: int, end: int, spec: AlarmSpec) -> None:
        source = spec.source or f"{spec.at:%Y-%m-%d %H:%M}"
        cursor = self._chip_cursor(start, end)
        self._busy = True
        try:
            cursor.beginEditBlock()
            cursor.removeSelectedText()
            cursor.insertText("@" + source, QTextCharFormat())
            cursor.endEditBlock()
        finally:
            self._busy = False
        self.editor.setTextCursor(cursor)
        self.editor.setCurrentCharFormat(QTextCharFormat())
        self.editor.setFocus()
        self._live = (self._doc_id(), cursor.blockNumber())
        self._repaint()
        self._update_preview()

    def _remove_chip(self, start: int, end: int) -> None:
        document = self.editor.document()
        if document.characterAt(end) == " ":
            end += 1
        cursor = self._chip_cursor(start, end)
        cursor.removeSelectedText()

    def _move_to_schedule(self, start: int, end: int, spec: AlarmSpec) -> None:
        store = self.editor.store
        block = self.editor.document().findBlock(start)
        from .memo_inline_alarm import collect_chips

        title = ""
        for entry in collect_chips(self.editor.document()):
            if entry.spec == spec:
                title = entry.memo
                break
        note_id = getattr(self.editor, "note_id", None)
        if not title and note_id is not None:
            row = store.note(int(note_id))
            title = str(row["title"]) if row is not None else ""
        title = title or block.text().strip() or "메모 일정"
        try:
            from .categories import schedule_categories

            category = schedule_categories(store)[0]["id"]
        except Exception:
            category = "default"
        values = {
            "id": None,
            "title": title,
            "details": "",
            "item_type": "event",
            "start_at": spec.at.strftime(DATETIME_FMT),
            "end_at": (spec.at + timedelta(hours=1)).strftime(DATETIME_FMT),
            "all_day": False,
            "category": category,
            "priority": 0,
            "note_id": int(note_id) if note_id is not None else None,
            "status": "pending",
            "recurrence_rule": _schedule_rule(spec),
            "reminders": list(spec.offsets) or [0],
            "hotkey": "",
            "hotkey_action": "open",
        }
        try:
            store.schedules.save_item(values)
        except Exception as exc:
            QToolTip.showText(self.editor.mapToGlobal(QPoint(12, 12)), f"일정으로 옮기지 못했습니다: {exc}", self.editor)
            return
        self._remove_chip(start, end)
        QToolTip.showText(
            self.editor.mapToGlobal(self.editor.cursorRect().bottomLeft()),
            f"‘{title}’ 일정을 {spec.at.month}/{spec.at.day} {spec.at:%H:%M}에 만들었습니다.",
            self.editor,
        )

    # ---------------------------------------------------------------- 화면 --
    def _repaint(self) -> None:
        refresh = getattr(self.editor, "_refresh_checklist_display", None)
        if refresh is not None:
            refresh()

    def selections(self) -> list:
        live = self._live_block()
        if live is None:
            return []
        phrase = self._phrase_for(live)
        if phrase is None:
            return []
        text = live.text()
        base = live.position()
        result = []
        at = QTextEdit.ExtraSelection()
        at.cursor = QTextCursor(self.editor.document())
        at.cursor.setPosition(base + utf16_len(text[:phrase.at_index]))
        at.cursor.setPosition(base + utf16_len(text[:phrase.at_index + 1]), QTextCursor.MoveMode.KeepAnchor)
        at.format.setForeground(AT_COLOR)
        at.format.setFontWeight(QFont.Weight.Bold)
        result.append(at)
        for span in phrase.spans:
            start, end = span.start, span.end
            while start < end and text[start:start + 1].isspace():
                start += 1
            while end > start and text[end - 1:end].isspace():
                end -= 1
            if start >= end:
                continue
            mark = QTextEdit.ExtraSelection()
            mark.cursor = QTextCursor(self.editor.document())
            mark.cursor.setPosition(base + utf16_len(text[:start]))
            mark.cursor.setPosition(base + utf16_len(text[:end]), QTextCursor.MoveMode.KeepAnchor)
            mark.format.setBackground(TOKEN_BACKGROUNDS.get(span.kind, TOKEN_BACKGROUNDS["time"]))
            result.append(mark)
        return result

    def preview_message(self) -> str:
        if not self.editor.hasFocus():
            return ""
        block, phrase = self._current()
        if phrase is not None and self._live == (self._doc_id(), block.blockNumber()):
            return preview_text(phrase)
        if not phrase_allowed(block):
            return ""
        cursor = self.editor.textCursor()
        index = utf16_offset_to_index(block.text(), cursor.position() - block.position())
        before = block.text()[:index]
        if _RE_BARE_AT.search(before) and not block.text()[index:].strip():
            return f"@ 뒤에 언제 알릴지 적어 주세요 · {EXAMPLE_HINT}"
        return ""

    def _update_preview(self) -> None:
        if sip.isdeleted(self.preview):
            return
        message = self.preview_message()
        if not message:
            self.preview.hide()
            return
        self.preview.setText(message)
        self.preview.adjustSize()
        viewport = self.editor.viewport()
        rect = self.editor.cursorRect()
        width = min(self.preview.width(), max(120, viewport.width() - 8))
        self.preview.resize(width, self.preview.height())
        x = max(4, min(rect.left() - 8, viewport.width() - width - 4))
        y = rect.bottom() + 6
        if y + self.preview.height() > viewport.height():
            y = max(0, rect.top() - self.preview.height() - 6)
        self.preview.move(x, y)
        self.preview.show()
        self.preview.raise_()


def _schedule_rule(spec: AlarmSpec) -> dict:
    rule = spec.rule
    if rule.rule_type == RULE_NONE:
        return {"frequency": "none", "interval": 1, "weekdays": [], "until": "", "count": 0}
    if rule.rule_type == RULE_DAILY:
        return {"frequency": "daily", "interval": 1, "weekdays": [], "until": "", "count": 0}
    if rule.rule_type == RULE_WEEKDAYS:
        return {"frequency": "weekly", "interval": 1, "weekdays": [0, 1, 2, 3, 4], "until": "", "count": 0}
    if rule.rule_type == RULE_WEEKLY:
        return {"frequency": "weekly", "interval": 1, "weekdays": list(rule.weekdays), "until": "", "count": 0}
    if rule.rule_type == RULE_MONTHLY:
        return {"frequency": "monthly", "interval": 1, "weekdays": [], "until": "", "count": 0}
    return {"frequency": "none", "interval": 1, "weekdays": [], "until": "", "count": 0}
