"""Rectangular clipboard and cell formatting on disposable Qt documents."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QMimeData, Qt
from PyQt6.QtGui import QTextCursor, QTextImageFormat
from PyQt6.QtWidgets import QApplication, QMenu

from alert_notes.memo_clipboard import BLOCK_MIME, get_json
from alert_notes.rich_memo_edit import RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.table_clipboard import excel_mime, paste_range
from alert_notes.table_edit import populate_menu
from alert_notes.table_style import (
    align_cells, background_cells, merge_cells, padding_cells, split_cell, toggle_header,
)
from qt_test_support import destroy_widget


APP = QApplication.instance() or QApplication([])


class TableStageBTest(unittest.TestCase):
    def setUp(self):
        self.editor = RichMemoTextEdit()
        self.editor.resize(540, 380)
        self.editor.show()
        APP.processEvents()
        self.editor.insert_table(2, 2)
        self.table = self.editor.current_table()
        self.table.cellAt(0, 0).firstCursorPosition().insertText("001")
        self.table.cellAt(0, 1).firstCursorPosition().insertText("두 줄\n문장")
        self.table.cellAt(1, 1).firstCursorPosition().insertText("끝")
        self.goto(0, 0)

    def tearDown(self):
        destroy_widget(self.editor, APP)

    def goto(self, row, column):
        self.editor.setTextCursor(self.table.cellAt(row, column).firstCursorPosition())

    def select_all(self):
        cursor = self.table.cellAt(0, 0).firstCursorPosition()
        cursor.setPosition(self.table.cellAt(1, 1).lastCursorPosition().position(),
                           QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

    def test_excel_copy_is_rectangular_and_internal_html_survives(self):
        self.select_all()
        mime = self.editor.createMimeDataFromSelection()
        self.assertIn('001\t"두 줄\n문장"\r\n\t끝', mime.text())
        self.assertIn('mso-number-format', mime.html())
        self.assertIn('001', mime.html())
        payload = get_json(mime, BLOCK_MIME)
        self.assertIsNotNone(payload)
        self.assertIn('<table', payload['html'].lower())

    def test_explicit_copy_handles_a_single_cell(self):
        self.goto(0, 0)
        mime = excel_mime(self.editor)
        self.assertEqual(mime.text(), '001\r\n')
        self.assertIn('001', mime.html())

    def test_paste_expands_table_and_one_undo_restores_it(self):
        self.goto(1, 1)
        source = QMimeData()
        source.setText('002\t\r\n"가\n나"\t004\r\n')
        handled, error = paste_range(self.editor, source)
        self.assertTrue(handled)
        self.assertIsNone(error)
        self.assertEqual((self.table.rows(), self.table.columns()), (3, 3))
        self.assertEqual(self.table.cellAt(1, 1).firstCursorPosition().block().text(), '002')
        self.assertEqual(self.table.cellAt(1, 2).firstCursorPosition().block().text(), '')
        self.assertIn('가', self.table.cellAt(2, 1).firstCursorPosition().block().text())
        self.assertEqual(self.table.cellAt(2, 2).firstCursorPosition().block().text(), '004')
        self.editor.document().undo()
        self.assertEqual((self.table.rows(), self.table.columns()), (2, 2))
        self.assertEqual(self.table.cellAt(1, 1).firstCursorPosition().block().text(), '끝')
        self.editor.document().redo()
        self.assertEqual((self.table.rows(), self.table.columns()), (3, 3))

    def test_html_table_paste_uses_cells_even_when_plain_text_is_flat(self):
        self.goto(0, 0)
        source = QMimeData()
        source.setText('flattened text')
        source.setHtml('<table><tr><td>007</td><td>가<br>나</td></tr>'
                       '<tr><td></td><td>끝</td></tr></table>')
        self.editor.insertFromMimeData(source)
        self.assertEqual(self.table.cellAt(0, 0).firstCursorPosition().block().text(), '007')
        self.assertIn('가', self.table.cellAt(0, 1).firstCursorPosition().block().text())
        self.assertEqual(self.table.cellAt(1, 0).firstCursorPosition().block().text(), '')
        self.assertEqual(self.table.cellAt(1, 1).firstCursorPosition().block().text(), '끝')

    def test_internal_table_copy_uses_original_block_html(self):
        self.goto(0, 0)
        self.editor.textCursor().insertHtml('<a href="https://example.org">링크</a>')
        picture = QTextImageFormat()
        picture.setName('toma-note-image://attachment/42')
        self.goto(1, 0)
        self.editor.textCursor().insertImage(picture)
        self.select_all()
        source = self.editor.createMimeDataFromSelection()
        self.assertTrue(source.hasFormat(BLOCK_MIME))
        original_html = get_json(source, BLOCK_MIME)['html']
        self.assertIn('https://example.org', original_html)
        self.assertIn('toma-note-image://attachment/42', original_html)
        destination = RichMemoTextEdit()
        try:
            destination.insertFromMimeData(source)
            self.assertIn('001', destination.toPlainText())
            self.assertIn('끝', destination.toPlainText())
        finally:
            destroy_widget(destination, APP)

    def test_merged_source_and_target_reject_without_changes(self):
        source = QMimeData()
        source.setText('A\tB')
        source.setHtml('<table><tr><td colspan="2">A</td></tr></table>')
        before = self.editor.toHtml()
        self.assertTrue(paste_range(self.editor, source)[1])
        self.assertEqual(self.editor.toHtml(), before)
        self.table.mergeCells(0, 0, 1, 2)
        self.goto(0, 0)
        plain = QMimeData()
        plain.setText('X\tY')
        before = self.editor.toHtml()
        self.assertTrue(paste_range(self.editor, plain)[1])
        self.assertEqual(self.editor.toHtml(), before)

    def test_cell_format_commands_and_undo(self):
        self.goto(1, 0)
        self.assertTrue(background_cells(self.editor, '#dbeafe'))
        self.assertEqual(self.table.cellAt(1, 0).format().background().color().name(), '#dbeafe')
        self.editor.document().undo()
        self.assertNotEqual(self.table.cellAt(1, 0).format().background().color().name(), '#dbeafe')
        self.assertTrue(padding_cells(self.editor, 8))
        self.assertEqual(self.table.cellAt(1, 0).format().toTableCellFormat().leftPadding(), 8)
        self.assertTrue(align_cells(self.editor, Qt.AlignmentFlag.AlignRight))
        self.assertEqual(self.table.cellAt(1, 0).firstCursorPosition().block().blockFormat().alignment(),
                         Qt.AlignmentFlag.AlignRight)
        self.assertTrue(toggle_header(self.editor))
        self.assertEqual(self.table.format().headerRowCount(), 0)
        self.assertTrue(toggle_header(self.editor))
        self.assertEqual(self.table.format().headerRowCount(), 1)

    def test_merge_preserves_contents_and_split_keeps_them_in_first_cell(self):
        self.select_all()
        handled, error = merge_cells(self.editor)
        self.assertTrue(handled)
        self.assertIsNone(error)
        self.assertEqual(self.table.cellAt(0, 0).rowSpan(), 2)
        joined = self.editor.toPlainText()
        self.assertIn('001', joined)
        self.assertIn('두 줄', joined)
        self.assertIn('끝', joined)
        self.editor.document().undo()
        self.assertEqual(self.table.cellAt(0, 0).rowSpan(), 1)
        self.assertEqual(self.table.cellAt(1, 1).firstCursorPosition().block().text(), '끝')
        self.select_all()
        merge_cells(self.editor)
        handled, error = split_cell(self.editor)
        self.assertTrue(handled)
        self.assertIsNone(error)
        self.assertEqual(self.table.cellAt(0, 0).rowSpan(), 1)
        first = self.table.cellAt(0, 0).firstCursorPosition()
        first.setPosition(self.table.cellAt(0, 0).lastCursorPosition().position(),
                          QTextCursor.MoveMode.KeepAnchor)
        self.assertIn('끝', first.selectedText())
        self.assertEqual(self.table.cellAt(1, 1).firstCursorPosition().block().text(), '')
        self.editor.document().undo()
        self.assertEqual(self.table.cellAt(0, 0).rowSpan(), 2)

    def test_menu_exposes_stage_b_commands(self):
        menu = QMenu()
        populate_menu(menu, self.editor)
        labels = [action.text() for action in menu.actions()]
        self.assertIn('엑셀 범위 복사', labels)
        self.assertIn('엑셀 범위 붙여넣기', labels)
        self.assertIn('셀 서식', labels)
        self.assertIn('병합·분할', labels)

    def test_merged_table_survives_temporary_db_backup(self):
        self.select_all()
        self.assertIsNone(merge_cells(self.editor)[1])
        self.assertTrue(background_cells(self.editor, '#dbeafe'))
        original = self.editor.document().toHtml()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = NoteReminderStore(root / 'source.db')
            try:
                note_id = store.create_note('표 B', original)
                store.backup_database(root / 'copy.db')
            finally:
                store.close()
            copied = NoteReminderStore(root / 'copy.db')
            try:
                saved = copied.note(note_id)['content']
            finally:
                copied.close()
        reopened = RichMemoTextEdit()
        try:
            reopened.document().setHtml(saved)
            found = reopened.document().find('001')
            table = QTextCursor(found.block()).currentTable()
            self.assertIsNotNone(table)
            self.assertEqual(table.cellAt(0, 0).rowSpan(), 2)
            self.assertIn('끝', reopened.toPlainText())
            self.assertEqual(table.cellAt(0, 0).format().background().color().name(), '#dbeafe')
        finally:
            destroy_widget(reopened, APP)


if __name__ == '__main__':
    unittest.main()
