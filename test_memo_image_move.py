"""Move pasted images without changing their attachment or display format."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QImage, QKeyEvent, QMouseEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

from alert_notes.image_move import move_image
from alert_notes.block_identity import block_ids
from alert_notes.rich_memo_edit import IMAGE_USER_WIDTH, RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


class MemoImageMoveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("그림 이동", "")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.resize(600, 420)
        self.editor.show()
        self.editor.set_note_context(self.note_id)
        image = QImage(240, 120, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkCyan)
        self.assertTrue(self.editor.insert_image(image))
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def image(self):
        return next(self.editor._image_fragments())

    def mouse(self, kind, point, buttons):
        self.editor.__getattribute__({
            QEvent.Type.MouseButtonPress: "mousePressEvent",
            QEvent.Type.MouseMove: "mouseMoveEvent",
            QEvent.Type.MouseButtonRelease: "mouseReleaseEvent",
        }[kind])(QMouseEvent(kind, point, point, Qt.MouseButton.LeftButton,
                            buttons, Qt.KeyboardModifier.NoModifier))

    def test_click_selects_but_does_not_move_or_resize(self):
        rect = self.editor.image_rect(self.image())
        point = QPointF(rect.left() + 12, rect.top() + 12)
        before = self.editor.content()
        self.mouse(QEvent.Type.MouseButtonPress, point, Qt.MouseButton.LeftButton)
        self.mouse(QEvent.Type.MouseButtonRelease, point, Qt.MouseButton.NoButton)
        self.assertEqual(self.editor._selected_image_at, self.image().position())
        self.assertEqual(self.editor.content(), before)

    def test_move_preserves_attachment_size_and_single_undo(self):
        source = self.image()
        original = source.charFormat().toImageFormat()
        self.editor.begin_image_resize(source)
        self.assertTrue(self.editor.resize_image_to(160))
        self.editor.finish_image_resize()
        source = self.image()
        original = source.charFormat().toImageFormat()
        original_at = source.position()
        original_id = block_ids(self.editor.document())[
            self.editor.document().findBlock(source.position()).blockNumber()
        ]
        cursor = QTextCursor(self.editor.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertText("뒤 문단")
        before = self.editor.content()
        after_block = self.editor.document().lastBlock()
        moved = move_image(self.editor.document(), original_at, after_block.position(), separate=True)
        self.assertIsNotNone(moved)
        fragments = list(self.editor._image_fragments())
        self.assertEqual(len(fragments), 1)
        moved_format = fragments[0].charFormat().toImageFormat()
        self.assertEqual(moved_format.name(), original.name())
        attachment_id = int(original.name().rsplit("/", 1)[-1])
        self.assertIsNotNone(self.store.attachment(attachment_id))
        self.assertAlmostEqual(moved_format.width(), original.width())
        self.assertEqual(moved_format.property(IMAGE_USER_WIDTH), original.property(IMAGE_USER_WIDTH))
        self.assertIn(original_id, block_ids(self.editor.document()))
        self.assertNotEqual(self.editor.content(), before)
        self.editor.undo()
        self.assertEqual(self.editor.content(), before)
        self.editor.redo()
        self.assertEqual(len(list(self.editor._image_fragments())), 1)
        saved = self.editor.content()
        reopened = RichMemoTextEdit()
        try:
            reopened.set_content(saved)
            restored = next(reopened._image_fragments()).charFormat().toImageFormat()
            self.assertEqual(restored.name(), original.name())
            self.assertAlmostEqual(restored.width(), original.width())
        finally:
            destroy_widget(reopened, self.app)

    def test_escape_or_outside_drop_cancels_without_document_change(self):
        rect = self.editor.image_rect(self.image())
        point = QPointF(rect.left() + 12, rect.top() + 12)
        before = self.editor.content()
        self.mouse(QEvent.Type.MouseButtonPress, point, Qt.MouseButton.LeftButton)
        self.editor.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                           Qt.KeyboardModifier.NoModifier))
        self.assertIsNone(self.editor._image_move_press)
        self.assertEqual(self.editor.content(), before)
        self.mouse(QEvent.Type.MouseButtonPress, point, Qt.MouseButton.LeftButton)
        outside = QPointF(self.editor.viewport().width() + 40, point.y() + 70)
        self.mouse(QEvent.Type.MouseMove, outside, Qt.MouseButton.LeftButton)
        self.mouse(QEvent.Type.MouseButtonRelease, outside, Qt.MouseButton.NoButton)
        self.assertEqual(self.editor.content(), before)

    def test_drag_near_bottom_auto_scrolls(self):
        cursor = QTextCursor(self.editor.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for index in range(100):
            cursor.insertBlock()
            cursor.insertText(f"줄 {index}")
        self.app.processEvents()
        rect = self.editor.image_rect(self.image())
        source = QPointF(rect.left() + 12, rect.top() + 12)
        edge = QPointF(30, self.editor.viewport().height() - 3)
        self.mouse(QEvent.Type.MouseButtonPress, source, Qt.MouseButton.LeftButton)
        self.mouse(QEvent.Type.MouseMove, edge, Qt.MouseButton.LeftButton)
        self.assertEqual(self.editor._image_scroll_direction, 1)
        before = self.editor.verticalScrollBar().value()
        self.editor._auto_scroll_image_drag()
        self.assertGreater(self.editor.verticalScrollBar().value(), before)
        self.editor._cancel_image_drag()

    def test_mouse_drag_moves_image_before_another_paragraph(self):
        cursor = QTextCursor(self.editor.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertText("목적지")
        self.app.processEvents()
        image_rect = self.editor.image_rect(self.image())
        source = QPointF(image_rect.left() + 12, image_rect.top() + 12)
        target_block = self.editor.document().lastBlock()
        target_rect = self.editor.cursorRect(QTextCursor(target_block))
        target = QPointF(target_rect.left() + 12, target_rect.top() + 2)
        original_name = self.image().charFormat().toImageFormat().name()
        self.mouse(QEvent.Type.MouseButtonPress, source, Qt.MouseButton.LeftButton)
        self.mouse(QEvent.Type.MouseMove, target, Qt.MouseButton.LeftButton)
        self.assertIsNotNone(self.editor._image_drop)
        self.mouse(QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.NoButton)
        self.assertEqual(len(list(self.editor._image_fragments())), 1)
        self.assertEqual(self.image().charFormat().toImageFormat().name(), original_name)
        self.assertIsNone(self.editor._image_drop)
        self.assertLess(self.image().position(), self.editor.document().find("목적지").position())

    def test_move_after_paragraph_places_image_on_its_own_line(self):
        cursor = QTextCursor(self.editor.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertText("목적지")
        target = self.editor.document().lastBlock()
        source_at = self.image().position()
        moved = move_image(
            self.editor.document(), source_at,
            target.position() + target.length() - 1, separate=True, after=True,
        )
        self.assertIsNotNone(moved)
        image_block = self.editor.document().findBlock(self.image().position())
        self.assertEqual(image_block.length(), 2)
        self.assertEqual(image_block.previous().text(), "목적지")

    def test_move_into_table_cell_preserves_original_attachment(self):
        cursor = QTextCursor(self.editor.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        self.editor.setTextCursor(cursor)
        self.editor.insert_table(2, 2)
        table = self.editor.textCursor().currentTable()
        self.assertIsNotNone(table)
        original_name = self.image().charFormat().toImageFormat().name()
        source_at = self.image().position()
        target_at = table.cellAt(1, 1).firstCursorPosition().position()
        moved = move_image(self.editor.document(), source_at, target_at)
        self.assertIsNotNone(moved)
        self.assertEqual(len(list(self.editor._image_fragments())), 1)
        self.assertEqual(self.image().charFormat().toImageFormat().name(), original_name)
        self.assertIsNotNone(QTextCursor(self.editor.document().findBlock(self.image().position())).currentTable())

    def test_open_toggle_accepts_image_in_child_but_closed_toggle_does_not(self):
        cursor = QTextCursor(self.editor.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertText("접기")
        self.editor.setTextCursor(cursor)
        self.editor.make_toggle()
        toggle = self.editor.textCursor().block()
        child = toggle.next()
        self.assertEqual(child.blockFormat().indent(), 1)
        self.app.processEvents()
        line = self.editor.cursorRect(QTextCursor(toggle))
        point = QPointF(line.left() + 40, line.center().y())
        self.editor._image_move_press = {"at": self.image().position(), "active": True}
        open_drop = self.editor._image_drop_at(point.toPoint())
        self.assertIsNotNone(open_drop)
        self.assertEqual(open_drop[0], child.position())
        self.editor._cancel_image_drag()
        moved = move_image(self.editor.document(), self.image().position(), child.position())
        self.assertIsNotNone(moved)
        self.assertEqual(self.editor.document().findBlock(self.image().position()).blockFormat().indent(), 1)
        moved_at = self.image().position()
        self.editor.fold_toggle(toggle)
        self.app.processEvents()
        self.editor._image_move_press = {"at": moved_at, "active": True}
        closed_drop = self.editor._image_drop_at(point.toPoint())
        if closed_drop is not None:
            self.assertNotEqual(closed_drop[0], child.position())
        self.editor._cancel_image_drag()


if __name__ == "__main__":
    unittest.main()
