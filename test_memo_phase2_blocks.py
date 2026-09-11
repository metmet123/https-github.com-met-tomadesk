import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QMimeData, QPointF, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QApplication, QMenu

from alert_notes.memo_clipboard import BLOCK_MIME, get_json
from alert_notes.rich_memo_edit import (
    LINK_MARK, PAGE_MARK, TOGGLE_OPEN_PREFIX, RichMemoTextEdit,
)
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def texts(editor):
    values = []
    block = editor.document().begin()
    while block.isValid():
        values.append(block.text())
        block = block.next()
    return values


def press(widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers))


class PhaseTwoBlockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            destroy_widget(widget, self.app)
        self.store.close()
        self.temp.cleanup()

    def editor(self, content="첫째\n둘째\n셋째\n넷째", note_id=None):
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        editor.setPlainText(content)
        editor.resize(680, 420)
        self.widgets.append(editor)
        return editor

    @staticmethod
    def block(editor, number):
        return editor.document().findBlockByNumber(number)

    def test_non_contiguous_reverse_selection_and_toggle_family(self):
        editor = self.editor()
        editor.block_selection.toggle(self.block(editor, 0), include_family=False)
        editor.block_selection.toggle(self.block(editor, 2), include_family=False)
        self.assertEqual(editor.block_selection.positions(), [0, 6])

        editor.block_selection.clear()
        editor.block_selection.begin_drag(self.block(editor, 3))
        editor.block_selection.update_drag(self.block(editor, 1))
        editor.block_selection.finish_drag()
        self.assertEqual([block.text() for block in editor.block_selection.blocks()], ["둘째", "셋째", "넷째"])

        editor.setPlainText(f"{TOGGLE_OPEN_PREFIX}부모\n자식\n밖")
        child = next(block for block in editor._iter_blocks() if block.text() == "자식")
        fmt = child.blockFormat()
        fmt.setIndent(1)
        QTextCursor(child).setBlockFormat(fmt)
        editor._drop_empty_placeholder(editor.document().begin())
        editor.block_selection.select_only(self.block(editor, 0))
        self.assertEqual([block.text() for block in editor.block_selection.blocks()], [f"{TOGGLE_OPEN_PREFIX}부모", "자식"])

    def test_plain_text_selection_is_untouched_until_alt_block_selection(self):
        editor = self.editor("가나다\n라마바")
        cursor = QTextCursor(editor.document())
        cursor.setPosition(1)
        cursor.setPosition(3, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        before = (editor.textCursor().selectionStart(), editor.textCursor().selectionEnd())
        editor.mousePressEvent(QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
        ))
        editor.mouseReleaseEvent(QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5),
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.AltModifier,
        ))
        self.assertEqual(before, (editor.textCursor().selectionStart(), editor.textCursor().selectionEnd()))
        self.assertEqual(editor.block_selection.count(), 1)

    def test_non_contiguous_clipboard_keeps_document_order_and_metadata(self):
        editor = self.editor()
        heading = QTextCursor(self.block(editor, 2))
        editor.setTextCursor(heading)
        editor.apply_heading2()
        editor.block_selection.toggle(self.block(editor, 2), include_family=False)
        editor.block_selection.toggle(self.block(editor, 0), include_family=False)
        self.assertTrue(editor.block_commands.execute("copy"))
        mime = QApplication.clipboard().mimeData()
        payload = get_json(mime, BLOCK_MIME)
        self.assertEqual(mime.text(), "첫째\n셋째")
        self.assertEqual([item["heading"] for item in payload["blocks"]], [0, 2])

        pasted = self.editor("")
        pasted.insertFromMimeData(mime)
        self.assertEqual(pasted.toPlainText(), "첫째\n셋째")
        self.assertEqual(pasted.heading_level(self.block(pasted, 1)), 2)

    def test_move_buttons_preserve_order_and_each_direction_is_one_undo(self):
        editor = self.editor()
        editor.block_selection.toggle(self.block(editor, 1), include_family=False)
        editor.block_selection.toggle(self.block(editor, 2), include_family=False)
        self.assertTrue(editor.block_commands.execute("move_down"))
        self.assertEqual(texts(editor), ["첫째", "넷째", "둘째", "셋째"])
        press(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(texts(editor), ["첫째", "둘째", "셋째", "넷째"])

        editor.block_selection.clear()
        editor.block_selection.toggle(self.block(editor, 1), include_family=False)
        editor.block_selection.toggle(self.block(editor, 2), include_family=False)
        self.assertTrue(editor.block_commands.execute("move_up"))
        self.assertEqual(texts(editor), ["둘째", "셋째", "첫째", "넷째"])

    def test_conversion_indent_group_and_delete_use_dispatcher(self):
        editor = self.editor()
        editor.block_selection.toggle(self.block(editor, 0), include_family=False)
        editor.block_selection.toggle(self.block(editor, 2), include_family=False)
        self.assertTrue(editor.block_commands.execute("checklist"))
        self.assertEqual(texts(editor)[0][:2], "☐ ")
        self.assertEqual(texts(editor)[2][:2], "☐ ")
        self.assertTrue(editor.block_commands.execute("indent"))
        self.assertEqual([self.block(editor, n).blockFormat().indent() for n in (0, 2)], [1, 1])
        self.assertTrue(editor.block_commands.execute("outdent"))

        editor.block_selection.clear()
        editor.block_selection.toggle(self.block(editor, 0), include_family=False)
        editor.block_selection.toggle(self.block(editor, 1), include_family=False)
        self.assertTrue(editor.block_commands.execute("group_toggle"))
        self.assertTrue(texts(editor)[0].startswith(TOGGLE_OPEN_PREFIX))
        self.assertGreaterEqual(self.block(editor, 1).blockFormat().indent(), 1)
        self.assertTrue(editor.block_commands.execute("delete"))
        self.assertNotIn("첫째", "\n".join(texts(editor)))

    def test_all_planned_conversions_are_undoable(self):
        cases = (
            ("toggle", lambda editor, block: editor._is_toggle_block(block)),
            ("checklist", lambda editor, block: editor._is_checklist_block(block)),
            ("bullet", lambda _editor, block: block.textList() is not None),
            ("callout", lambda editor, block: editor.is_callout_block(block)),
            ("quote", lambda editor, block: editor.is_quote_block(block)),
            ("code", lambda editor, block: editor.is_code_block(block)),
            ("heading2", lambda editor, block: editor.heading_level(block) == 2),
        )
        for command, predicate in cases:
            with self.subTest(command=command):
                editor = self.editor("변환 대상\n그대로")
                editor.block_selection.select_only(self.block(editor, 0), include_family=False)
                self.assertTrue(editor.block_commands.execute(command))
                self.assertTrue(predicate(editor, self.block(editor, 0)))
                press(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                self.assertEqual(editor.toPlainText(), "변환 대상\n그대로")

    def test_body_conversion_does_not_touch_unselected_middle_block(self):
        editor = self.editor("하나\n둘\n셋")
        all_text = QTextCursor(editor.document())
        all_text.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(all_text)
        editor.apply_heading2()
        editor.block_selection.toggle(self.block(editor, 0), include_family=False)
        editor.block_selection.toggle(self.block(editor, 2), include_family=False)
        self.assertTrue(editor.block_commands.execute("body"))
        self.assertEqual(editor.heading_level(self.block(editor, 0)), 0)
        self.assertEqual(editor.heading_level(self.block(editor, 1)), 2)
        self.assertEqual(editor.heading_level(self.block(editor, 2)), 0)

    def test_alt_keyboard_and_gutter_mouse_share_selection_commands(self):
        editor = self.editor()
        editor.show()
        self.app.processEvents()
        block = self.block(editor, 1)
        point = QPointF(8, editor.cursorRect(QTextCursor(block)).center().y())
        editor.gutter.mousePressEvent(QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, point, point,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
        ))
        editor.gutter.mouseReleaseEvent(QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease, point, point,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.AltModifier,
        ))
        self.assertEqual([item.text() for item in editor.block_selection.blocks()], ["둘째"])
        press(editor, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(texts(editor), ["첫째", "셋째", "둘째", "넷째"])

    def test_unlink_features_keeps_page_row_and_undo_redo_embedded_state(self):
        parent = self.store.create_note("부모", "")
        page = self.store.create_child_note(parent, "페이지", embedded=True)
        editor = self.editor(note_id=parent)
        editor.set_content(
            f'<html><body><p><a href="toma-note://{page}">{PAGE_MARK}페이지</a></p></body></html>'
        )
        editor.block_selection.select_only(editor.document().begin(), include_family=False)
        self.assertTrue(editor.block_commands.execute("unlink_links"))
        self.assertEqual(editor.toPlainText(), "페이지")
        self.assertIsNotNone(self.store.note(page))
        self.assertEqual(int(self.store.note(page)["embedded"]), 0)
        self.assertFalse(editor._block_has_anchor(editor.document().begin()))

        press(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(int(self.store.note(page)["embedded"]), 1)
        self.assertTrue(editor.toPlainText().startswith(PAGE_MARK))
        press(editor, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(int(self.store.note(page)["embedded"]), 0)
        self.assertEqual(editor.toPlainText(), "페이지")

    def test_unlink_features_preserves_ordinary_character_format(self):
        target = self.store.create_note("대상", "")
        editor = self.editor("")
        cursor = editor.textCursor()
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(f"toma-note://{target}")
        fmt.setFontWeight(700)
        fmt.setForeground(QColor("#c62828"))
        cursor.insertText(f"{LINK_MARK}대상", fmt)
        editor.block_selection.select_only(editor.document().begin(), include_family=False)
        self.assertTrue(editor.block_commands.execute("unlink_links"))
        self.assertEqual(editor.toPlainText(), "대상")
        check = QTextCursor(editor.document().begin())
        check.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        self.assertFalse(check.charFormat().isAnchor())
        self.assertEqual(check.charFormat().fontWeight(), 700)
        self.assertEqual(check.charFormat().foreground().color().name(), "#c62828")

    def test_partial_link_selection_only_unlinks_the_selected_run(self):
        editor = self.editor("")
        cursor = editor.textCursor()
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref("https://example.com")
        cursor.insertText("앞", fmt)
        cursor.insertText("뒤", fmt)
        selection = QTextCursor(editor.document())
        selection.setPosition(0)
        selection.setPosition(1, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(selection)
        self.assertTrue(editor.block_commands.execute("unlink_links"))
        first = QTextCursor(editor.document())
        first.setPosition(0)
        first.setPosition(1, QTextCursor.MoveMode.KeepAnchor)
        second = QTextCursor(editor.document())
        second.setPosition(1)
        second.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
        self.assertFalse(first.charFormat().isAnchor())
        self.assertTrue(second.charFormat().isAnchor())

    def test_duplicate_uses_structured_payload_and_one_undo(self):
        editor = self.editor("원본\n다음")
        editor.block_selection.select_only(self.block(editor, 0), include_family=False)
        self.assertTrue(editor.block_commands.execute("duplicate"))
        self.assertEqual(texts(editor), ["원본", "원본", "다음"])
        press(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(texts(editor), ["원본", "다음"])

    def test_page_duplicate_undo_removes_the_cloned_page_only(self):
        parent = self.store.create_note("부모", "")
        page = self.store.create_child_note(parent, "페이지", embedded=True)
        editor = self.editor(note_id=parent)
        editor.set_content(
            f'<html><body><p><a href="toma-note://{page}">{PAGE_MARK}페이지</a></p></body></html>'
        )
        editor.block_selection.select_only(editor.document().begin(), include_family=False)
        self.assertTrue(editor.block_commands.execute("duplicate"))
        page_ids = [editor.page_id_of_block(block) for block in editor._iter_blocks()]
        page_ids = [value for value in page_ids if value is not None]
        self.assertEqual(len(page_ids), 2)
        clone = next(value for value in page_ids if value != page)
        self.assertIsNotNone(self.store.note(clone))
        press(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertIsNone(self.store.note(clone))
        self.assertIsNotNone(self.store.note(page))
        self.assertEqual(editor.toPlainText(), f"{PAGE_MARK}페이지")

    def test_context_menu_has_common_and_page_specific_commands(self):
        parent = self.store.create_note("부모", "")
        page = self.store.create_child_note(parent, "페이지", embedded=True)
        editor = self.editor(note_id=parent)
        editor.set_content(
            f'<html><body><p><a href="toma-note://{page}">{PAGE_MARK}페이지</a></p></body></html>'
        )
        editor.block_selection.select_only(editor.document().begin(), include_family=False)
        menu = QMenu()
        editor._populate_block_context_menu(menu)
        labels = [action.text() for action in menu.actions()]
        self.assertIn("블록", labels)
        self.assertIn("블록 변환", labels)
        self.assertIn("연동 기능 삭제", labels)
        self.assertIn("페이지·링크", labels)
        page_menu = next(action.menu() for action in menu.actions() if action.text() == "페이지·링크")
        self.assertIn("메모 유지", page_menu.actions()[0].text())

    def test_floating_bar_and_escape_follow_selection(self):
        editor = self.editor()
        editor.show()
        self.app.processEvents()
        editor.block_selection.select_only(self.block(editor, 1), include_family=False)
        self.app.processEvents()
        self.assertTrue(editor.block_action_bar.isVisible())
        self.assertEqual(editor.block_action_bar.count_label.text(), "1개 선택")
        press(editor, Qt.Key.Key_Escape)
        self.assertEqual(editor.block_selection.count(), 0)
        self.assertFalse(editor.block_action_bar.isVisible())


if __name__ == "__main__":
    unittest.main()
