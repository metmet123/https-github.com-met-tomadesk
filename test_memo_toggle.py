"""메모 본문의 노션식 토글(펼치기·접기) 테스트."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtCore import QEvent, QMimeData, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

from alert_notes.rich_memo_edit import (
    EMPTY_TOGGLE_HINT, TOGGLE_CLOSED_PREFIX, TOGGLE_OPEN_PREFIX, RichMemoTextEdit,
)
from qt_test_support import destroy_widget


def press(widget, key, text="", modifiers=Qt.KeyboardModifier.NoModifier):
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers, text))


class MemoToggleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = RichMemoTextEdit()
        self.editor.resize(500, 400)
        self.editor.show()

    def tearDown(self):
        destroy_widget(self.editor, self.app)

    # ------------------------------------------------------------------ 만들기 --
    def _type_toggle(self, title="준비물"):
        cursor = self.editor.textCursor()
        cursor.insertText(">")
        self.editor.setTextCursor(cursor)
        press(self.editor, Qt.Key.Key_Space, " ")
        self.editor.textCursor().insertText(title)
        return self.editor.textCursor().block()

    def test_angle_bracket_and_space_makes_a_toggle(self):
        block = self._type_toggle()
        self.assertTrue(block.text().startswith(TOGGLE_OPEN_PREFIX))
        self.assertEqual(block.text(), f"{TOGGLE_OPEN_PREFIX}준비물")
        self.assertTrue(self.editor.current_block_is_toggle())

    def test_angle_bracket_in_the_middle_is_left_alone(self):
        self.editor.textCursor().insertText("a >")
        press(self.editor, Qt.Key.Key_Space, " ")
        self.assertFalse(self.editor.current_block_is_toggle())

    def test_toolbar_style_call_makes_and_unmakes_a_toggle(self):
        self.editor.textCursor().insertText("준비물")
        self.editor.make_toggle()
        self.assertTrue(self.editor.current_block_is_toggle())
        self.editor.make_toggle()
        self.assertFalse(self.editor.current_block_is_toggle())
        self.assertEqual(self.editor.document().begin().text(), "준비물")

    # ------------------------------------------------------------------ 자식 --
    def _toggle_with_children(self):
        toggle = self._type_toggle()
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("우산")
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("장갑")
        return self.editor.document().begin()

    def test_enter_on_a_toggle_writes_inside_it(self):
        toggle = self._toggle_with_children()
        children = list(self.editor._toggle_children(toggle))
        self.assertEqual([block.text() for block in children], ["우산", "장갑"])

    def test_folding_hides_the_children(self):
        toggle = self._toggle_with_children()
        self.editor.fold_toggle(toggle)
        self.assertTrue(toggle.text().startswith(TOGGLE_CLOSED_PREFIX))
        self.assertTrue(toggle.isVisible())
        self.assertFalse(any(child.isVisible() for child in self.editor._toggle_children(toggle)))

    def test_unfolding_brings_them_back(self):
        toggle = self._toggle_with_children()
        self.editor.fold_toggle(toggle)
        self.editor.fold_toggle(toggle)
        self.assertTrue(toggle.text().startswith(TOGGLE_OPEN_PREFIX))
        self.assertTrue(all(child.isVisible() for child in self.editor._toggle_children(toggle)))

    def test_space_at_the_marker_folds(self):
        toggle = self._toggle_with_children()
        cursor = QTextCursor(toggle)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        self.editor.setTextCursor(cursor)
        press(self.editor, Qt.Key.Key_Space, " ")
        self.assertTrue(self.editor.document().begin().text().startswith(TOGGLE_CLOSED_PREFIX))

    def test_text_outside_the_toggle_stays_visible(self):
        self._toggle_with_children()
        press(self.editor, Qt.Key.Key_Return)
        press(self.editor, Qt.Key.Key_Backtab)
        self.editor.textCursor().insertText("다음 문단")
        toggle = self.editor.document().begin()
        self.editor.fold_toggle(toggle)
        last = self.editor.document().lastBlock()
        self.assertEqual(last.text(), "다음 문단")
        self.assertTrue(last.isVisible(), "토글 밖의 문단까지 숨으면 안 됩니다")

    def test_nested_toggle_stays_folded_when_the_parent_reopens(self):
        self._type_toggle("바깥")
        press(self.editor, Qt.Key.Key_Return)          # 안쪽으로
        self.editor.textCursor().insertText(">")
        press(self.editor, Qt.Key.Key_Space, " ")
        self.editor.textCursor().insertText("안쪽")
        press(self.editor, Qt.Key.Key_Return)          # 안쪽의 안쪽
        self.editor.textCursor().insertText("깊은 줄")

        outer = self.editor.document().begin()
        inner = outer.next()
        deep = inner.next()
        self.editor.fold_toggle(inner)
        self.assertFalse(deep.isVisible())
        self.editor.fold_toggle(outer)
        self.editor.fold_toggle(outer)                 # 다시 펼친다
        self.assertTrue(inner.isVisible())
        self.assertFalse(deep.isVisible(), "안쪽 토글은 접힌 채로 남아야 합니다")

    # ------------------------------------------------------------------ 지우기 --
    def test_backspace_at_the_marker_removes_the_toggle(self):
        toggle = self._type_toggle()
        cursor = QTextCursor(toggle)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, n=2)
        self.editor.setTextCursor(cursor)
        press(self.editor, Qt.Key.Key_Backspace)
        self.assertEqual(self.editor.document().begin().text(), "준비물")

    def test_removing_a_folded_toggle_brings_its_content_back(self):
        toggle = self._toggle_with_children()
        self.editor.fold_toggle(toggle)
        self.editor._remove_toggle_prefix(self.editor.document().begin())
        blocks = []
        block = self.editor.document().begin()
        while block.isValid():
            blocks.append((block.text(), block.isVisible()))
            block = block.next()
        self.assertTrue(all(visible for _text, visible in blocks), blocks)

    # ------------------------------------------------------------------ 저장 --
    def test_folded_state_survives_a_round_trip(self):
        toggle = self._toggle_with_children()
        self.editor.fold_toggle(toggle)
        saved = self.editor.content()

        reopened = RichMemoTextEdit()
        reopened.resize(500, 400)
        reopened.show()
        reopened.set_content(saved)
        first = reopened.document().begin()
        self.assertTrue(first.text().startswith(TOGGLE_CLOSED_PREFIX))
        self.assertFalse(
            any(child.isVisible() for child in reopened._toggle_children(first)),
            "다시 열었을 때 접힌 토글이 펼쳐져 있습니다",
        )
        destroy_widget(reopened, self.app)


class EmptyToggleHintTest(unittest.TestCase):
    """펼쳐 두었는데 안이 빈 토글에 뜨는 안내."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = RichMemoTextEdit()
        self.editor.resize(500, 400)
        self.editor.show()

    def tearDown(self):
        destroy_widget(self.editor, self.app)

    def _make_toggle(self, title="테스트"):
        self.editor.textCursor().insertText(title)
        self.editor.make_toggle()
        return self.editor.document().begin()

    def _hinted(self):
        return [toggle.text() for toggle, _child in self.editor._empty_toggle_blocks()]

    def test_a_new_toggle_gets_a_line_for_the_hint(self):
        toggle = self._make_toggle()
        self.assertIsNotNone(self.editor._lone_empty_child(toggle))
        self.assertEqual(self._hinted(), [f"{TOGGLE_OPEN_PREFIX}테스트"])

    def test_the_cursor_stays_on_the_title(self):
        self._make_toggle()
        self.assertTrue(self.editor.current_block_is_toggle(), "커서가 안쪽 빈 줄로 끌려갔습니다")
        self.editor.textCursor().insertText("2")
        self.assertEqual(self.editor.document().begin().text(), f"{TOGGLE_OPEN_PREFIX}테스트2")

    def test_writing_inside_puts_the_hint_away(self):
        self._make_toggle()
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("우산")
        self.assertEqual(self._hinted(), [])

    def test_enter_reuses_the_empty_line_instead_of_adding_one(self):
        toggle = self._make_toggle()
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("우산")
        children = [block.text() for block in self.editor._toggle_children(toggle)]
        self.assertEqual(children, ["우산"])

    def test_a_folded_toggle_shows_no_hint(self):
        toggle = self._make_toggle()
        self.editor.fold_toggle(toggle)
        self.assertTrue(self.editor.document().begin().text().startswith(TOGGLE_CLOSED_PREFIX))
        self.assertEqual(self._hinted(), [])

    def test_undoing_the_toggle_takes_the_empty_line_with_it(self):
        toggle = self._make_toggle()
        self.editor._remove_toggle_prefix(toggle)
        blocks = []
        block = self.editor.document().begin()
        while block.isValid():
            blocks.append(block.text())
            block = block.next()
        self.assertEqual(blocks, ["테스트"])

    def test_the_hint_never_reaches_the_saved_memo(self):
        self._make_toggle()
        self.assertNotIn(EMPTY_TOGGLE_HINT, self.editor.content())

    def test_an_old_memo_without_the_empty_line_gets_one_on_open(self):
        self.editor.set_content(f"{TOGGLE_OPEN_PREFIX}테스트")
        toggle = self.editor.document().begin()
        self.assertIsNotNone(self.editor._lone_empty_child(toggle))
        self.assertFalse(self.editor.document().isModified(), "메모를 열자마자 수정 상태가 되면 안 됩니다")

    def _paste_into_hint(self, source):
        toggle = self._make_toggle()
        hint = self.editor._lone_empty_child(toggle)
        self.editor.setTextCursor(QTextCursor(hint))
        self.editor.insertFromMimeData(source)
        self.app.processEvents()
        return toggle

    def test_multiline_plain_text_paste_stays_inside_the_toggle(self):
        source = QMimeData()
        source.setText("첫 문단\n둘째 문단\n셋째 문단")
        toggle = self._paste_into_hint(source)
        children = list(self.editor._toggle_children(toggle))
        self.assertEqual([block.text() for block in children], ["첫 문단", "둘째 문단", "셋째 문단"])
        self.assertTrue(all(
            block.blockFormat().indent() == toggle.blockFormat().indent() + 1
            for block in children
        ))

    def test_html_paste_keeps_every_paragraph_inside_and_preserves_bold(self):
        source = QMimeData()
        source.setHtml("<p><b>첫 문단</b></p><p>둘째 문단</p>")
        toggle = self._paste_into_hint(source)
        children = list(self.editor._toggle_children(toggle))
        self.assertEqual([block.text() for block in children], ["첫 문단", "둘째 문단"])
        self.assertTrue(all(
            block.blockFormat().indent() == toggle.blockFormat().indent() + 1
            for block in children
        ))
        first_character = QTextCursor(children[0])
        first_character.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        first_character.movePosition(
            QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor,
        )
        self.assertGreaterEqual(first_character.charFormat().fontWeight(), 700)

    def test_html_paste_drops_the_generated_leading_blank(self):
        source = QMimeData()
        source.setHtml("<p><br></p><ul><li>첫 항목</li><li>둘째 항목</li></ul>")
        toggle = self._paste_into_hint(source)
        self.assertEqual(
            [block.text() for block in self.editor._toggle_children(toggle)],
            ["첫 항목", "둘째 항목"],
        )

    def test_one_ctrl_z_undoes_the_paste_and_its_indent_fix_together(self):
        source = QMimeData()
        source.setText("첫 문단\n둘째 문단")
        toggle = self._paste_into_hint(source)
        press(
            self.editor, Qt.Key.Key_Z, "z", Qt.KeyboardModifier.ControlModifier,
        )
        self.app.processEvents()
        self.assertEqual(toggle.text(), f"{TOGGLE_OPEN_PREFIX}테스트")
        self.assertIsNotNone(self.editor._lone_empty_child(toggle))
        self.assertNotIn("첫 문단", self.editor.toPlainText())
        self.assertNotIn("둘째 문단", self.editor.toPlainText())

    def test_backspace_removes_an_empty_child_before_filled_children(self):
        toggle = self._make_toggle()
        empty = self.editor._lone_empty_child(toggle)
        cursor = QTextCursor(empty)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertBlock()
        fmt = cursor.blockFormat()
        fmt.setIndent(toggle.blockFormat().indent() + 1)
        cursor.setBlockFormat(fmt)
        cursor.insertText("붙여넣은 내용")
        self.editor.setTextCursor(QTextCursor(empty))
        press(self.editor, Qt.Key.Key_Backspace)
        self.assertEqual(
            [block.text() for block in self.editor._toggle_children(toggle)],
            ["붙여넣은 내용"],
        )

    def test_backspace_on_the_empty_hint_turns_the_toggle_back_to_a_paragraph(self):
        toggle = self._make_toggle()
        self.editor.setTextCursor(QTextCursor(self.editor._lone_empty_child(toggle)))
        press(self.editor, Qt.Key.Key_Backspace)
        self.assertEqual([block.text() for block in self.editor._iter_blocks()], ["테스트"])

    def test_delete_on_the_empty_hint_turns_the_toggle_back_to_a_paragraph(self):
        toggle = self._make_toggle()
        self.editor.setTextCursor(QTextCursor(self.editor._lone_empty_child(toggle)))
        press(self.editor, Qt.Key.Key_Delete)
        self.assertEqual([block.text() for block in self.editor._iter_blocks()], ["테스트"])

    def test_backspace_removes_an_outside_blank_after_an_empty_toggle(self):
        toggle = self._make_toggle()
        hint = self.editor._lone_empty_child(toggle)
        cursor = QTextCursor(hint)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertBlock()
        outside = cursor.block()
        fmt = outside.blockFormat()
        fmt.setIndent(toggle.blockFormat().indent())
        cursor.setBlockFormat(fmt)
        cursor.insertBlock()
        cursor.insertText("다음 문단")
        self.assertEqual(
            [(block.text(), block.blockFormat().indent()) for block in self.editor._iter_blocks()],
            [(f"{TOGGLE_OPEN_PREFIX}테스트", 0), ("", 1), ("", 0), ("다음 문단", 0)],
        )
        self.editor.setTextCursor(QTextCursor(outside))
        press(self.editor, Qt.Key.Key_Backspace)
        self.assertEqual(
            [(block.text(), block.blockFormat().indent()) for block in self.editor._iter_blocks()],
            [(f"{TOGGLE_OPEN_PREFIX}테스트", 0), ("", 1), ("다음 문단", 0)],
        )


class WritingOutsideAToggleTest(unittest.TestCase):
    """토글 밑 빈 곳을 누르면 토글 밖에 글을 쓸 수 있어야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = RichMemoTextEdit()
        self.editor.resize(500, 400)
        self.editor.show()

    def tearDown(self):
        destroy_widget(self.editor, self.app)

    def _click(self, y: float):
        point = QPointF(120.0, y)
        self.editor.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, point, point,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ))

    def _blocks(self):
        blocks = []
        block = self.editor.document().begin()
        while block.isValid():
            blocks.append((block.text(), block.blockFormat().indent()))
            block = block.next()
        return blocks

    def test_clicking_below_an_empty_toggle_writes_outside_it(self):
        self.editor.textCursor().insertText("취미")
        self.editor.make_toggle()
        self._click(360.0)
        self.editor.textCursor().insertText("다음 문단")
        self.assertEqual(self.editor.textCursor().block().blockFormat().indent(), 0)
        self.assertEqual(self._blocks()[-1], ("다음 문단", 0))

    def test_clicking_below_a_filled_toggle_writes_outside_it(self):
        self.editor.textCursor().insertText("취미")
        self.editor.make_toggle()
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("드라마")
        self._click(360.0)
        self.editor.textCursor().insertText("다음 문단")
        self.assertEqual(self._blocks()[-1], ("다음 문단", 0))
        toggle = self.editor.document().begin()
        self.assertEqual(
            [block.text() for block in self.editor._toggle_children(toggle)], ["드라마"],
            "토글 밖 문단이 토글 안으로 들어갔습니다",
        )

    def test_clicking_below_plain_text_adds_nothing(self):
        self.editor.textCursor().insertText("그냥 메모")
        before = self._blocks()
        self._click(360.0)
        self.assertEqual(self._blocks(), before, "토글이 없는데 빈 줄이 늘었습니다")

    def test_the_new_line_stays_out_of_a_folded_toggle(self):
        self.editor.textCursor().insertText("취미")
        self.editor.make_toggle()
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("드라마")
        self.editor.fold_toggle(self.editor.document().begin())
        self._click(360.0)
        self.editor.textCursor().insertText("다음 문단")
        last = self.editor.document().lastBlock()
        self.assertEqual(last.text(), "다음 문단")
        self.assertTrue(last.isVisible(), "접힌 토글 때문에 새 문단까지 숨었습니다")


class PostitToggleTest(unittest.TestCase):
    """포스트잇 입력도 메모 입력과 같은 서식을 쓴다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from alert_notes.postit import PostitWindow
        from alert_notes.sqlite_store import NoteReminderStore

        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        note_id = self.store.create_note("포스트잇", "")
        self.window = PostitWindow(self.store, self.store.note(note_id))
        self.window.show()

    def tearDown(self):
        self.window.close_silently()
        destroy_widget(self.window, self.app)
        self.store.close()
        self.temp.cleanup()

    def _insert(self, name: str):
        panel = self.window.format_bar.insert_button.menu().actions()[0].defaultWidget()
        item = next(
            panel.feature_list.item(row)
            for row in range(panel.feature_list.count())
            if name in panel.feature_list.item(row).text()
        )
        panel._run_item(item)

    def test_the_format_bar_has_an_insert_button_without_an_on_off_state(self):
        button = self.window.format_bar.insert_button
        self.assertIsNotNone(button.menu(), "기능 목록이 붙어 있지 않습니다")
        self.assertFalse(button.isCheckable(), "켜짐/꺼짐 표시가 남습니다")

    def test_the_menu_makes_a_toggle_in_the_postit(self):
        self.window.memo.textCursor().insertText("준비물")
        self._insert("토글")
        self.assertTrue(self.window.memo.current_block_is_toggle())

    def test_the_button_stays_unpressed_while_the_cursor_sits_on_a_toggle(self):
        self.window.memo.textCursor().insertText("준비물")
        self._insert("토글")
        self.window._sync_format_buttons(self.window.memo.currentCharFormat())
        self.assertFalse(self.window.format_bar.insert_button.isChecked())

    def test_an_empty_postit_toggle_shows_the_hint_too(self):
        self.window.memo.textCursor().insertText("준비물")
        self._insert("토글")
        self.assertEqual(
            [toggle.text() for toggle, _child in self.window.memo._empty_toggle_blocks()],
            [f"{TOGGLE_OPEN_PREFIX}준비물"],
        )

    def test_typing_the_notion_way_works_in_the_postit(self):
        self.window.memo.textCursor().insertText(">")
        press(self.window.memo, Qt.Key.Key_Space, " ")
        self.window.memo.textCursor().insertText("준비물")
        self.assertEqual(self.window.memo.document().begin().text(), f"{TOGGLE_OPEN_PREFIX}준비물")


class MarkerCursorTest(unittest.TestCase):
    """토글·체크리스트 표시 위에서는 글자 입력용 커서를 쓰지 않는다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = RichMemoTextEdit()
        self.editor.resize(500, 400)
        self.editor.show()

    def tearDown(self):
        destroy_widget(self.editor, self.app)

    def _hover(self, point: QPointF):
        self.editor.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, point, point,
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        ))

    def _shape(self):
        return self.editor.viewport().cursor().shape()

    def test_the_toggle_marker_shows_a_hand(self):
        self.editor.textCursor().insertText("취미")
        self.editor.make_toggle()
        toggle = self.editor.document().begin()
        self._hover(self.editor._toggle_marker_rect(toggle).center())
        self.assertEqual(self._shape(), Qt.CursorShape.PointingHandCursor)
        self.assertIsNotNone(self.editor._hover_marker_rect())

    def test_plain_text_keeps_the_writing_cursor(self):
        self.editor.textCursor().insertText("취미")
        self.editor.make_toggle()
        toggle = self.editor.document().begin()
        self._hover(self.editor._toggle_marker_rect(toggle).center())
        self._hover(QPointF(400.0, 300.0))
        self.assertEqual(self._shape(), Qt.CursorShape.IBeamCursor)
        self.assertIsNone(self.editor._hover_marker_rect())

    def test_the_checklist_box_shows_a_hand_too(self):
        self.editor.textCursor().insertText("우산")
        self.editor.toggle_checklist()
        block = self.editor.document().begin()
        self._hover(self.editor._checkbox_rect(block).center())
        self.assertEqual(self._shape(), Qt.CursorShape.PointingHandCursor)

    def test_leaving_the_editor_puts_the_cursor_back(self):
        self.editor.textCursor().insertText("취미")
        self.editor.make_toggle()
        toggle = self.editor.document().begin()
        self._hover(self.editor._toggle_marker_rect(toggle).center())
        self.editor.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertEqual(self._shape(), Qt.CursorShape.IBeamCursor)


class ToolbarToggleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_toolbar_button_makes_a_toggle(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from alert_notes.sqlite_store import NoteReminderStore
        from alert_notes.text_format_toolbar import TextFormatToolbar

        temp = TemporaryDirectory()
        store = NoteReminderStore(Path(temp.name) / "notes.db", "새 메모")
        editor = RichMemoTextEdit(store)
        editor.show()
        toolbar = TextFormatToolbar(editor, store)
        editor.textCursor().insertText("준비물")
        panel = toolbar.insert_button.menu().actions()[0].defaultWidget()
        items = [panel.feature_list.item(row) for row in range(panel.feature_list.count())]
        labels = [item.text() for item in items]
        self.assertFalse(toolbar.insert_button.isCheckable(), "켜짐/꺼짐 표시가 남습니다")
        self.assertTrue(any("토글" in label for label in labels), labels)
        self.assertTrue(any("페이지" in label for label in labels), labels)
        panel._run_item(next(item for item in items if "토글" in item.text()))
        self.assertTrue(editor.current_block_is_toggle())
        # 아직 만들지 않은 기능은 눌러도 아무 일이 없도록 흐리게 둔다.
        page = next(item for item in items if "페이지" in item.text())
        self.assertEqual(bool(page.flags() & Qt.ItemFlag.ItemIsEnabled), hasattr(editor, "insert_page_link"))
        destroy_widget(toolbar, self.app)
        destroy_widget(editor, self.app)
        store.close()
        temp.cleanup()


if __name__ == "__main__":
    unittest.main()
