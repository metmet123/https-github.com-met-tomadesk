"""Table selection, split, fill, and small formulas on disposable documents."""

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor, QTextFormat
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from alert_notes.rich_memo_edit import RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.table_calculation import block_calculation, stored_formula
from alert_notes.table_fill import fill_handle
from alert_notes.table_formula import calculate, parse_formula, series_values, shifted_formula
from alert_notes.table_input import delete_selected, resize_selected
from alert_notes.table_style import split_cell
from qt_test_support import destroy_widget


APP = QApplication.instance() or QApplication([])


class TableInputFormulaTest(unittest.TestCase):
    def setUp(self):
        self.editor = RichMemoTextEdit()
        self.editor.resize(700, 400)
        self.editor.show()
        self.table = self.editor.textCursor().insertTable(4, 4)
        APP.processEvents()

    def tearDown(self):
        destroy_widget(self.editor, APP)

    def cell(self, row, column):
        return self.table.cellAt(row, column)

    def value(self, row, column):
        return self.cell(row, column).firstCursorPosition().block().text()

    def select(self, first_row, first_column, last_row, last_column):
        cursor = self.cell(first_row, first_column).firstCursorPosition()
        cursor.setPosition(self.cell(last_row, last_column).lastCursorPosition().position(),
                           QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        APP.processEvents()

    def drag_fill(self, target_row, target_column):
        handle = fill_handle(self.editor)
        self.assertIsNotNone(handle)
        destination = self.editor.cursorRect(self.cell(target_row, target_column).firstCursorPosition()).center()
        QTest.mousePress(self.editor.viewport(), Qt.MouseButton.LeftButton,
                         pos=handle.center().toPoint())
        QTest.mouseMove(self.editor.viewport(), destination)
        QTest.mouseRelease(self.editor.viewport(), Qt.MouseButton.LeftButton, pos=destination)
        APP.processEvents()

    def test_formula_parser_and_series_are_bounded(self):
        self.assertEqual(parse_formula("=sum(A1:B2)"), ("SUM", 0, 1, 0, 1))
        self.assertEqual(calculate(["2", "3", "텍스트"], "AVERAGE"), "2.5")
        self.assertEqual(calculate(["2", "3"], "PRODUCT"), "6")
        self.assertEqual(shifted_formula("=SUM($A1:B$2)", 1, 1), "=SUM($A2:C$2)")
        self.assertEqual(series_values(["1", "3"], 2), ["5", "7"])
        self.assertEqual(series_values(["2026-09-22"], 2), ["2026-09-23", "2026-09-24"])
        self.assertEqual(series_values(["001"], 2), ["001", "001"])
        with self.assertRaises(ValueError):
            parse_formula("=A1+B2")

    def test_typed_formula_enter_result_reload_and_recalculation(self):
        self.cell(0, 0).firstCursorPosition().insertText("2")
        self.cell(1, 0).firstCursorPosition().insertText("3")
        self.editor.setTextCursor(self.cell(2, 0).firstCursorPosition())
        QTest.keyClicks(self.editor, "=SUM(A1:A2)")
        QTest.keyClick(self.editor, Qt.Key.Key_Return)
        self.assertEqual(self.value(2, 0), "5")
        self.assertEqual(stored_formula(self.cell(2, 0)), "=SUM(A1:A2)")
        saved = self.editor.content()
        reopened = RichMemoTextEdit()
        try:
            reopened.set_content(saved)
            from alert_notes.table_calculation import _tables
            frame = next(_tables(reopened.document().rootFrame()))
            self.assertEqual(stored_formula(frame.cellAt(2, 0)), "=SUM(A1:A2)")
        finally:
            destroy_widget(reopened, APP)
        self.editor.setTextCursor(self.cell(0, 0).lastCursorPosition())
        QTest.keyClicks(self.editor, "1")
        QTest.qWait(180)
        self.assertEqual(self.value(2, 0), "24")

    def test_formula_mouse_range_and_block_calculation(self):
        self.cell(0, 0).firstCursorPosition().insertText("2")
        self.cell(1, 0).firstCursorPosition().insertText("3")
        self.editor.setTextCursor(self.cell(2, 1).firstCursorPosition())
        QTest.keyClicks(self.editor, "=SUM(")
        self.select(0, 0, 1, 0)
        from alert_notes.table_calculation import formula_from_mouse_range
        self.assertEqual(formula_from_mouse_range(self.editor, self.table, 2, 1), (True, None))
        self.assertEqual(self.value(2, 1), "5")
        self.select(0, 0, 1, 0)
        self.assertEqual(block_calculation(self.editor, "PRODUCT"), (True, None))
        self.assertEqual(self.value(2, 0), "6")
        self.assertEqual(stored_formula(self.cell(2, 0)), "=PRODUCT(A1:A2)")

    def test_formula_f2_escape_restores_result(self):
        self.cell(0, 0).firstCursorPosition().insertText("4")
        from alert_notes.table_calculation import set_formula
        self.assertEqual(set_formula(self.editor, self.table, 2, 0, "=SUM(A1)"), (True, None))
        self.editor.setTextCursor(self.cell(2, 0).firstCursorPosition())
        QTest.keyClick(self.editor, Qt.Key.Key_F2)
        self.assertEqual(self.value(2, 0), "=SUM(A1)")
        QTest.keyClick(self.editor, Qt.Key.Key_Escape)
        self.assertEqual(self.value(2, 0), "4")
        self.assertEqual(stored_formula(self.cell(2, 0)), "=SUM(A1)")

    def test_mouse_click_in_formula_picks_cell_reference(self):
        self.cell(0, 0).firstCursorPosition().insertText("6")
        self.editor.setTextCursor(self.cell(2, 2).firstCursorPosition())
        QTest.keyClicks(self.editor, "=SUM(")
        APP.processEvents()
        point = self.editor.cursorRect(self.cell(0, 0).firstCursorPosition()).center()
        QTest.mouseClick(self.editor.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(self.value(2, 2), "6")
        self.assertEqual(stored_formula(self.cell(2, 2)), "=SUM(A1)")

    def test_drag_fill_numbers_dates_and_formulas(self):
        self.cell(0, 0).firstCursorPosition().insertText("1")
        self.cell(1, 0).firstCursorPosition().insertText("2")
        self.select(0, 0, 1, 0)
        self.drag_fill(2, 0)
        self.assertEqual(self.value(2, 0), "3")
        self.cell(0, 1).firstCursorPosition().insertText("2026-09-22")
        self.editor.setTextCursor(self.cell(0, 1).firstCursorPosition())
        self.drag_fill(1, 1)
        self.assertEqual(self.value(1, 1), "2026-09-23")
        self.cell(0, 2).firstCursorPosition().insertText("4")
        self.cell(1, 2).firstCursorPosition().insertText("5")
        from alert_notes.table_calculation import set_formula
        self.assertEqual(set_formula(self.editor, self.table, 0, 3, "=SUM(A1:C1)"), (True, None))
        APP.processEvents()
        self.drag_fill(1, 3)
        self.assertEqual(stored_formula(self.cell(1, 3)), "=SUM(A2:C2)")
        self.assertEqual(self.value(1, 3), "7")

    def test_split_regular_cell_preserves_neighbours_and_undo(self):
        self.cell(1, 1).firstCursorPosition().insertText("중앙")
        self.cell(1, 2).firstCursorPosition().insertText("옆")
        self.editor.setTextCursor(self.cell(1, 1).firstCursorPosition())
        self.assertEqual(split_cell(self.editor, 2, 2), (True, None))
        self.assertEqual((self.table.rows(), self.table.columns()), (5, 5))
        self.assertEqual(self.value(1, 1), "중앙")
        self.assertEqual(self.value(1, 3), "옆")
        saved = self.editor.content()
        reopened = RichMemoTextEdit()
        try:
            reopened.set_content(saved)
            from alert_notes.table_calculation import _tables
            recovered = next(_tables(reopened.document().rootFrame()))
            self.assertEqual((recovered.rows(), recovered.columns()), (5, 5))
            self.assertEqual(recovered.cellAt(1, 3).firstCursorPosition().block().text(), "옆")
        finally:
            destroy_widget(reopened, APP)
        self.editor.document().undo()
        self.assertEqual((self.table.rows(), self.table.columns()), (4, 4))
        self.assertEqual(self.value(1, 2), "옆")

    def test_split_equal_rows_keeps_one_undo_step(self):
        self.cell(1, 1).firstCursorPosition().insertText("첫 줄\n둘째 줄")
        self.editor.setTextCursor(self.cell(1, 1).firstCursorPosition())
        self.assertEqual(split_cell(self.editor, 2, 1, True), (True, None))

        def top(row):
            cell = self.cell(row, 1)
            fmt = cell.format().toTableCellFormat()
            pad = (fmt.topPadding() if fmt.hasProperty(QTextFormat.Property.TableCellTopPadding)
                   else self.table.format().cellPadding())
            return self.editor.cursorRect(cell.firstCursorPosition()).top() - pad

        self.assertAlmostEqual(top(2) - top(1), top(3) - top(2), delta=1.0)
        self.editor.document().undo()
        self.assertEqual((self.table.rows(), self.table.columns()), (4, 4))

    def test_delete_whole_columns_offers_keep_or_remove(self):
        self.cell(0, 1).firstCursorPosition().insertText("보존")
        self.select(0, 1, 3, 2)

        def choose(label):
            def click():
                dialog = APP.activeModalWidget()
                self.assertIsInstance(dialog, QMessageBox)
                next(button for button in dialog.buttons() if button.text() == label).click()
            QTimer.singleShot(0, click)

        choose("취소")
        self.assertTrue(delete_selected(self.editor))
        self.assertEqual((self.table.rows(), self.table.columns()), (4, 4))
        self.assertEqual(self.value(0, 1), "보존")
        self.select(0, 1, 3, 2)
        choose("남김")
        self.assertTrue(delete_selected(self.editor))
        self.assertEqual((self.table.rows(), self.table.columns()), (4, 4))
        self.assertEqual(self.value(0, 1), "")
        self.cell(0, 1).firstCursorPosition().insertText("다시")
        self.select(0, 1, 3, 2)
        choose("지우기")
        self.assertTrue(delete_selected(self.editor))
        self.assertEqual((self.table.rows(), self.table.columns()), (4, 2))

    def test_partial_range_delete_clears_contents_without_structure_change(self):
        self.cell(1, 0).firstCursorPosition().insertText("내용")
        self.select(1, 0, 1, 1)
        self.assertTrue(delete_selected(self.editor))
        self.assertEqual((self.table.rows(), self.table.columns()), (4, 4))
        self.assertEqual(self.value(1, 0), "")

    def test_f5_selection_and_ctrl_resize(self):
        self.editor.setTextCursor(self.cell(0, 0).firstCursorPosition())
        QTest.keyClick(self.editor, Qt.Key.Key_F5)
        self.assertIsNotNone(self.editor._table_selected_cell)
        QTest.keyClick(self.editor, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(self.table.format().columnWidthConstraints()), 4)
        QTest.keyClick(self.editor, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        self.assertGreater(self.cell(0, 0).format().toTableCellFormat().bottomPadding(), 0)

    def test_f5_s_opens_split_dialog_and_m_merges_selected_cells(self):
        self.editor.setTextCursor(self.cell(0, 0).firstCursorPosition())
        QTest.keyClick(self.editor, Qt.Key.Key_F5)

        def accept_split():
            dialog = APP.activeModalWidget()
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.StandardButton.Ok).click()

        QTimer.singleShot(0, accept_split)
        QTest.keyClick(self.editor, Qt.Key.Key_S)
        self.assertEqual((self.table.rows(), self.table.columns()), (5, 4))
        self.select(0, 0, 1, 0)
        QTest.keyClick(self.editor, Qt.Key.Key_M)
        self.assertEqual(self.cell(0, 0).rowSpan(), 2)

    def test_f5_shift_arrows_extend_rectangular_cell_selection(self):
        self.editor.setTextCursor(self.cell(1, 1).firstCursorPosition())
        QTest.keyClick(self.editor, Qt.Key.Key_F5)
        QTest.keyClick(self.editor, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClick(self.editor, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.editor.textCursor().selectedTableCells(), (1, 2, 1, 2))

    def test_ctrl_down_scales_different_row_heights_similarly(self):
        self.cell(0, 0).firstCursorPosition().insertText("첫째\n둘째\n셋째")
        self.cell(1, 0).firstCursorPosition().insertText("짧게")
        self.select(0, 0, 1, 0)

        def row_heights():
            tops = []
            for row in range(3):
                cell = self.cell(row, 0)
                fmt = cell.format().toTableCellFormat()
                pad = (fmt.topPadding() if fmt.hasProperty(QTextFormat.Property.TableCellTopPadding)
                       else self.table.format().cellPadding())
                tops.append(self.editor.cursorRect(cell.firstCursorPosition()).top() - pad)
            return [tops[1] - tops[0], tops[2] - tops[1]]

        before = row_heights()
        self.assertTrue(resize_selected(self.editor, Qt.Key.Key_Down))
        after = row_heights()
        self.assertGreater(after[0], before[0])
        self.assertGreater(after[1], before[1])
        self.assertAlmostEqual(after[0] / before[0], after[1] / before[1], delta=0.02)

    def test_formula_survives_temporary_database_backup(self):
        self.cell(0, 0).firstCursorPosition().insertText("8")
        self.cell(1, 0).firstCursorPosition().insertText("2")
        from alert_notes.table_calculation import set_formula, _tables
        self.assertEqual(set_formula(self.editor, self.table, 2, 0, "=AVERAGE(A1:A2)"),
                         (True, None))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = NoteReminderStore(root / "source.db")
            try:
                note_id = store.create_note("표 계산", self.editor.content())
                store.backup_database(root / "copy.db")
            finally:
                store.close()
            copy = NoteReminderStore(root / "copy.db")
            try:
                saved = str(copy.note(note_id)["content"])
            finally:
                copy.close()
        reopened = RichMemoTextEdit()
        try:
            reopened.set_content(saved)
            table = next(_tables(reopened.document().rootFrame()))
            self.assertEqual(table.cellAt(2, 0).firstCursorPosition().block().text(), "5")
            self.assertEqual(stored_formula(table.cellAt(2, 0)), "=AVERAGE(A1:A2)")
        finally:
            destroy_widget(reopened, APP)


if __name__ == "__main__":
    unittest.main()
