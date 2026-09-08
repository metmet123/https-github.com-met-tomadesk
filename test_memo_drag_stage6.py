"""메모 층 나누기 6단계 — 줄 끌어 옮기기와 페이지·토글 안으로 넣기."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

from alert_notes.line_gutter import LineGutter
from alert_notes.rich_memo_edit import PAGE_MARK, TOGGLE_OPEN_PREFIX, RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def press(widget, key, text=""):
    widget.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
    )


def block_texts(editor):
    texts = []
    block = editor.document().begin()
    while block.isValid():
        texts.append(block.text())
        block = block.next()
    return texts


def indents(editor):
    depths = []
    block = editor.document().begin()
    while block.isValid():
        depths.append(block.blockFormat().indent())
        block = block.next()
    return depths


class DragLinesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("메모", "")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.resize(560, 400)
        self.editor.show()
        self.editor.set_note_context(self.note_id)
        self._write(["첫째 줄", "둘째 줄", "셋째 줄"])

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def _write(self, lines):
        cursor = self.editor.textCursor()
        for index, line in enumerate(lines):
            if index:
                cursor.insertBlock()
            cursor.insertText(line)
        self.editor.setTextCursor(cursor)
        self.app.processEvents()

    def _block(self, text):
        block = self.editor.document().begin()
        while block.isValid():
            if block.text() == text:
                return block
            block = block.next()
        raise AssertionError(f"{text} 줄이 없습니다: {block_texts(self.editor)}")

    def _move(self, source, target, inside=False):
        return self.editor.move_line(
            self._block(source).position(), self._block(target).position(), inside,
        )

    # --------------------------------------------------------- 순서 --
    def test_a_line_moves_below_another(self):
        self.assertTrue(self._move("첫째 줄", "셋째 줄"))
        self.assertEqual(block_texts(self.editor), ["둘째 줄", "셋째 줄", "첫째 줄"])

    def test_a_line_moves_up(self):
        self.assertTrue(self._move("셋째 줄", "첫째 줄"))
        self.assertEqual(block_texts(self.editor), ["첫째 줄", "셋째 줄", "둘째 줄"])

    def test_no_blank_line_is_left_behind(self):
        self._move("첫째 줄", "셋째 줄")
        self.assertNotIn("", block_texts(self.editor), block_texts(self.editor))

    def test_the_writing_keeps_its_look(self):
        cursor = QTextCursor(self._block("둘째 줄"))
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor,
        )
        self.editor.setTextCursor(cursor)
        self.editor.toggle_character_style("bold")
        self._move("둘째 줄", "셋째 줄")
        moved = self._block("둘째 줄")
        probe = QTextCursor(moved)
        probe.setPosition(moved.position() + 1)
        self.assertGreaterEqual(probe.charFormat().fontWeight(), 700)

    def test_a_line_cannot_land_on_itself(self):
        self.assertFalse(self._move("둘째 줄", "둘째 줄"))
        self.assertEqual(block_texts(self.editor), ["첫째 줄", "둘째 줄", "셋째 줄"])

    # --------------------------------------------------------- 토글 --
    def test_dropping_on_a_toggle_puts_the_line_inside(self):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertText("준비물")
        self.editor.setTextCursor(cursor)
        self.editor.make_toggle()
        toggle = f"{TOGGLE_OPEN_PREFIX}준비물"
        self.assertTrue(self._move("첫째 줄", toggle, inside=True))
        parent = self._block(toggle)
        children = [item.text() for item in self.editor._toggle_children(parent)]
        self.assertIn("첫째 줄", children, block_texts(self.editor))

    def test_the_hint_line_makes_way_for_the_dropped_one(self):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertText("준비물")
        self.editor.setTextCursor(cursor)
        self.editor.make_toggle()
        toggle = f"{TOGGLE_OPEN_PREFIX}준비물"
        self._move("첫째 줄", toggle, inside=True)
        children = [
            item.text() for item in self.editor._toggle_children(self._block(toggle))
        ]
        self.assertEqual(children, ["첫째 줄"], block_texts(self.editor))

    def test_a_toggle_takes_its_own_lines_along(self):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertText("준비물")
        self.editor.setTextCursor(cursor)
        self.editor.make_toggle()
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("우산")
        toggle = f"{TOGGLE_OPEN_PREFIX}준비물"
        self.assertTrue(self._move(toggle, "첫째 줄"))
        texts = block_texts(self.editor)
        self.assertLess(texts.index(toggle), texts.index("우산"), texts)
        self.assertEqual(texts.index(toggle), texts.index("첫째 줄") + 1, texts)

    def test_a_toggle_cannot_be_dropped_inside_itself(self):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertText("준비물")
        self.editor.setTextCursor(cursor)
        self.editor.make_toggle()
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("우산")
        toggle = f"{TOGGLE_OPEN_PREFIX}준비물"
        self.assertFalse(self._move(toggle, "우산"), "자기 안으로 들어갔습니다")

    # --------------------------------------------------------- 페이지 --
    def test_dropping_on_a_page_moves_the_text_into_it(self):
        self.editor.insert_page_link()
        self.editor.textCursor().insertText("회차별 감상")
        self.editor.sync_page_titles()
        page_id = int(self.store.child_notes(self.note_id)[0]["id"])
        line = f"{PAGE_MARK}회차별 감상"
        self.assertTrue(self._move("첫째 줄", line, inside=True))
        self.assertNotIn("첫째 줄", block_texts(self.editor))
        self.assertIn("첫째 줄", str(self.store.note(page_id)["content"]))

    def test_what_was_already_in_the_page_stays(self):
        self.editor.insert_page_link()
        self.editor.textCursor().insertText("회차별 감상")
        self.editor.sync_page_titles()
        page_id = int(self.store.child_notes(self.note_id)[0]["id"])
        self.store.update_note(page_id, content="<p>먼저 있던 줄</p>")
        self._move("첫째 줄", f"{PAGE_MARK}회차별 감상", inside=True)
        content = str(self.store.note(page_id)["content"])
        self.assertIn("먼저 있던 줄", content)
        self.assertIn("첫째 줄", content)


class GutterTest(unittest.TestCase):
    """손잡이 칸이 줄을 알아보고 커서를 바꾸는지."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = RichMemoTextEdit()
        self.editor.resize(560, 300)
        self.editor.show()
        cursor = self.editor.textCursor()
        cursor.insertText("첫째 줄")
        cursor.insertBlock()
        cursor.insertText("둘째 줄")
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.editor, self.app)

    def _hover(self, y):
        point = QPointF(8.0, float(y))
        self.editor.gutter.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, point, point,
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        ))

    def test_the_handles_sit_on_the_right_edge(self):
        self.assertEqual(self.editor.viewportMargins().right(), LineGutter.WIDTH)
        self.assertEqual(self.editor.viewportMargins().left(), 0)
        self.assertEqual(self.editor.gutter.width(), LineGutter.WIDTH)
        self.assertGreater(
            self.editor.gutter.x(), self.editor.width() // 2,
            "손잡이가 아직 왼쪽에 있습니다",
        )

    def test_hovering_a_line_shows_its_handle(self):
        first = self.editor.document().begin()
        line = self.editor.cursorRect(QTextCursor(first))
        self._hover(line.center().y())
        hovered = self.editor.gutter.hovered_block()
        self.assertIsNotNone(hovered)
        self.assertEqual(hovered.text(), "첫째 줄")
        self.assertEqual(
            self.editor.gutter.cursor().shape(), Qt.CursorShape.OpenHandCursor,
        )

    def test_below_the_last_line_there_is_no_handle(self):
        self._hover(280)
        self.assertIsNone(self.editor.gutter.hovered_block())
        self.assertEqual(
            self.editor.gutter.cursor().shape(), Qt.CursorShape.ArrowCursor,
        )

    def test_the_handle_sits_beside_its_line(self):
        second = self.editor.document().begin().next()
        line = self.editor.cursorRect(QTextCursor(second))
        rect = self.editor.gutter.handle_rect(second)
        self.assertLessEqual(abs(rect.center().y() - line.center().y()), 3)
        self.assertLess(rect.right(), LineGutter.WIDTH)

    def test_a_drag_shows_where_it_will_land(self):
        first = self.editor.document().begin()
        second = first.next()
        self.editor.begin_line_drag(first)
        self.editor.update_line_drag(
            QPoint(60, self.editor.cursorRect(QTextCursor(second)).bottom() - 1)
        )
        self.assertIsNotNone(self.editor._drop_at)
        self.editor.cancel_line_drag()
        self.assertIsNone(self.editor._drop_at)


if __name__ == "__main__":
    unittest.main()
