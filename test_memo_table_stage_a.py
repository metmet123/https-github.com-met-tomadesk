"""Table A operations on a temporary QTextDocument; no user data is opened."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QTextCursor, QTextImageFormat
from PyQt6.QtWidgets import QApplication, QMenu

from alert_notes.rich_memo_edit import RichMemoTextEdit
from alert_notes.table_edit import (
    clear_contents, insert, outside_paragraph, populate_menu, remove, select, set_width,
)
from qt_test_support import destroy_widget


APP = QApplication.instance() or QApplication([])


class TableStageATest(unittest.TestCase):
    def setUp(self):
        self.editor = RichMemoTextEdit()
        self.editor.resize(520, 370)
        self.editor.show()
        APP.processEvents()
        self.editor.insert_table(2, 3)
        self.table = self.editor.current_table()
        for row in range(2):
            for column in range(3):
                self.table.cellAt(row, column).firstCursorPosition().insertText(f"{row}{column}")
        self.goto(0, 0)

    def tearDown(self):
        destroy_widget(self.editor, APP)

    def goto(self, row, column):
        self.editor.setTextCursor(self.table.cellAt(row, column).firstCursorPosition())

    def test_context_bar_and_menu_only_inside_table(self):
        APP.processEvents()
        self.assertTrue(self.editor.table_action_bar.isVisible())
        for width in (300, 520, 800):
            self.editor.resize(width, 370)
            APP.processEvents()
            bar = self.editor.table_action_bar
            self.assertLessEqual(bar.geometry().right(), self.editor.rect().right())
            self.assertLessEqual(bar.layout().sizeHint().width(), bar.width())
        menu = QMenu()
        populate_menu(menu, self.editor)
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        self.assertIn("내용만 지우기", labels)
        self.assertIn("본문 폭에 맞춤", labels)
        outside_paragraph(self.editor, True)
        APP.processEvents()
        self.assertFalse(self.editor.table_action_bar.isVisible())

    def test_insert_above_below_left_right_and_single_undo(self):
        self.goto(1, 1)
        self.assertTrue(insert(self.editor, "row", True))
        self.assertEqual(self.table.rows(), 3)
        self.assertEqual(self.table.cellAt(2, 1).firstCursorPosition().block().text(), "11")
        self.editor.document().undo()
        self.assertEqual(self.table.rows(), 2)
        self.goto(0, 1)
        self.assertTrue(insert(self.editor, "column", False))
        self.assertEqual(self.table.columns(), 4)
        self.editor.document().undo()
        self.assertEqual(self.table.columns(), 3)
        self.goto(0, 0)
        self.assertTrue(insert(self.editor, "row", False))
        self.assertTrue(insert(self.editor, "column", True))
        self.assertEqual((self.table.rows(), self.table.columns()), (3, 4))

    def test_selection_and_clear_keep_table_and_undo(self):
        self.goto(0, 1)
        self.assertTrue(select(self.editor, "column"))
        self.assertEqual(self.editor.textCursor().selectedTableCells(), (0, 2, 1, 1))
        self.assertTrue(clear_contents(self.editor))
        self.assertEqual((self.table.rows(), self.table.columns()), (2, 3))
        self.assertEqual(self.table.cellAt(0, 1).firstCursorPosition().block().text(), "")
        self.assertEqual(self.table.cellAt(1, 1).firstCursorPosition().block().text(), "")
        self.assertEqual(self.table.cellAt(0, 0).firstCursorPosition().block().text(), "00")
        self.editor.document().undo()
        self.assertEqual(self.table.cellAt(0, 1).firstCursorPosition().block().text(), "01")
        self.assertEqual(self.table.cellAt(1, 1).firstCursorPosition().block().text(), "11")

    def test_clear_keeps_other_cell_link_and_image(self):
        self.goto(0, 0)
        self.editor.textCursor().insertHtml('<a href="https://example.org">링크</a>')
        image = QTextImageFormat()
        image.setName("toma-note-image://attachment/42")
        self.goto(1, 2)
        self.editor.textCursor().insertImage(image)
        before = self.editor.document().toHtml()
        self.assertIn("toma-note-image://attachment/42", before)
        self.goto(0, 1)
        self.assertTrue(clear_contents(self.editor))
        after = self.editor.document().toHtml()
        self.assertIn("toma-note-image://attachment/42", after)
        self.assertIn("https://example.org", after)
        self.assertEqual((self.table.rows(), self.table.columns()), (2, 3))
        self.editor.document().undo()
        self.assertEqual(self.table.cellAt(0, 1).firstCursorPosition().block().text(), "01")

    def test_clear_multiline_cell_preserves_its_border(self):
        self.goto(0, 2)
        self.editor.textCursor().insertText("첫 줄\n둘째 줄")
        self.goto(0, 2)
        self.assertTrue(clear_contents(self.editor))
        self.assertEqual((self.table.rows(), self.table.columns()), (2, 3))
        self.assertEqual(self.table.cellAt(0, 2).firstCursorPosition().block().text(), "")
        self.assertEqual(self.table.cellAt(1, 2).firstCursorPosition().block().text(), "12")
        self.editor.document().undo()
        self.assertIn("첫 줄", self.editor.toPlainText())
        self.assertIn("둘째 줄", self.editor.toPlainText())

    def test_selected_row_delete_only_selected_row(self):
        self.goto(0, 1)
        self.assertTrue(select(self.editor, "row"))
        self.assertEqual(self.editor.textCursor().selectedTableCells(), (0, 1, 0, 3))
        self.assertTrue(remove(self.editor, "row"))
        self.assertEqual(self.table.rows(), 1)
        self.assertEqual(self.table.cellAt(0, 1).firstCursorPosition().block().text(), "11")
        self.editor.document().undo()
        self.assertEqual(self.table.rows(), 2)

    def test_delete_row_column_table_and_undo(self):
        self.goto(0, 1)
        self.assertTrue(remove(self.editor, "column"))
        self.assertEqual(self.table.columns(), 2)
        self.editor.document().undo()
        self.assertEqual(self.table.columns(), 3)
        self.goto(1, 0)
        self.assertTrue(remove(self.editor, "row"))
        self.assertEqual(self.table.rows(), 1)
        self.editor.document().undo()
        self.assertEqual(self.table.rows(), 2)
        self.goto(0, 0)
        self.assertTrue(remove(self.editor, "table"))
        self.assertIsNone(self.editor.current_table())
        self.editor.document().undo()
        restored = QTextCursor(self.editor.document().find("00").block()).currentTable()
        self.assertIsNotNone(restored)
        self.assertEqual((restored.rows(), restored.columns()), (2, 3))

    def test_outside_paragraph_and_width_survive_html(self):
        self.assertTrue(set_width(self.editor, "even"))
        self.assertEqual(len(self.table.format().columnWidthConstraints()), 3)
        self.assertTrue(set_width(self.editor, "fit"))
        self.assertFalse(self.table.format().columnWidthConstraints())
        self.assertTrue(outside_paragraph(self.editor, False))
        self.editor.textCursor().insertText("표 뒤")
        self.assertIsNone(self.editor.current_table())
        html = self.editor.document().toHtml()
        reopened = RichMemoTextEdit()
        try:
            reopened.document().setHtml(html)
            self.assertIn("표 뒤", reopened.toPlainText())
            self.assertIn("00", reopened.toPlainText())
        finally:
            destroy_widget(reopened, APP)

    def test_drag_boundary_changes_two_columns_as_one_undo(self):
        APP.processEvents()
        cell = self.table.cellAt(0, 1)
        x = self.editor.cursorRect(cell.firstCursorPosition()).left() - self.table.format().cellPadding()
        original_next_x = self.editor.cursorRect(self.table.cellAt(0, 1).firstCursorPosition()).left()
        y = self.editor.cursorRect(cell.firstCursorPosition()).center().y()
        def mouse(kind, px):
            buttons = Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
            return QMouseEvent(kind, QPointF(px, y), QPointF(px, y),
                               Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
        self.editor.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, x))
        self.assertIsNotNone(self.editor._table_width_drag)
        self.editor.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, x + 25))
        self.editor.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, x + 25))
        self.assertEqual(len(self.table.format().columnWidthConstraints()), 3)
        APP.processEvents()
        self.assertGreater(self.editor.cursorRect(self.table.cellAt(0, 1).firstCursorPosition()).left(), original_next_x)
        self.editor.document().undo()
        self.assertFalse(self.table.format().columnWidthConstraints())

    def test_escape_cancels_width_drag_without_document_change(self):
        APP.processEvents()
        cell = self.table.cellAt(0, 1)
        x = self.editor.cursorRect(cell.firstCursorPosition()).left() - self.table.format().cellPadding()
        y = self.editor.cursorRect(cell.firstCursorPosition()).center().y()
        press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        self.editor.mousePressEvent(press)
        self.assertIsNotNone(self.editor._table_width_drag)
        from PyQt6.QtGui import QKeyEvent
        self.editor.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                            Qt.KeyboardModifier.NoModifier))
        self.assertIsNone(self.editor._table_width_drag)
        self.assertFalse(self.table.format().columnWidthConstraints())


if __name__ == "__main__":
    unittest.main()
