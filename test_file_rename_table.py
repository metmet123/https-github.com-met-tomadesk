import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTableWidgetSelectionRange
from PyQt6.QtTest import QTest
from file_rename import parse_clipboard, format_clipboard
from file_rename_table import FileRenameWindow

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path):
    paths = [tmp_path / name for name in ("first.txt", "second.TXT", "archive.tar.gz")]
    for path in paths:
        path.write_text("original", encoding="utf-8")
    widget = FileRenameWindow()
    widget.add_paths(paths)
    yield widget
    widget.close()
    assert sorted(tmp_path.iterdir()) == sorted(paths)
    assert all(path.read_text(encoding="utf-8") == "original" for path in paths)


def select(window, top, left, bottom=None, right=None):
    window.table.clearSelection()
    window.table.setCurrentCell(top, left)
    window.table.setRangeSelected(QTableWidgetSelectionRange(
        top, left, top if bottom is None else bottom, left if right is None else right), True)


def values(window):
    return window._snapshot()[3]


def test_tsv_roundtrip_preserves_quoted_multiline_spaces_zeros():
    rows = [["001", " a ", ""], ["x\ty", "two\nlines", 'a"b']]
    assert parse_clipboard(format_clipboard(rows)) == rows
    assert parse_clipboard("a\t\r\n\t\r\n") == [["a", ""], ["", ""]]
    assert parse_clipboard("") == [[""]]
    with pytest.raises(ValueError):
        parse_clipboard('"unclosed')
    with pytest.raises(ValueError):
        parse_clipboard("a\tb\nc")


def test_paste_one_undo_redo_and_copy(window):
    before = values(window)
    rows = [["001", " a ", ""], ["x\ty", "two\nlines", 'a"b']]
    select(window, 0, 1)
    APP.clipboard().setText(format_clipboard(rows))
    window.paste_cells()
    assert values(window)[:2] == tuple(map(tuple, rows))
    select(window, 0, 1, 1, 3)
    window.copy_cells()
    assert parse_clipboard(APP.clipboard().text()) == rows
    window.undo()
    assert values(window) == before
    window.redo()
    assert values(window)[:2] == tuple(map(tuple, rows))


@pytest.mark.parametrize("text,row,col", [("a\tb", 0, 3), ("a\nb", 2, 1), ('"unclosed', 0, 1), ("a\tb\nc", 0, 1)])
def test_paste_invalid_or_overflow_is_atomic(window, text, row, col):
    before = window._snapshot()
    history = len(window._undo)
    select(window, row, col)
    APP.clipboard().setText(text)
    window.paste_cells()
    assert window._snapshot() == before
    assert len(window._undo) == history


def test_readonly_and_discontiguous_selection_rejected(window):
    before = values(window)
    select(window, 0, 0)
    APP.clipboard().setText("bad")
    window.paste_cells()
    select(window, 0, 1)
    window.table.setRangeSelected(QTableWidgetSelectionRange(2, 3, 2, 3), True)
    window.paste_cells()
    assert values(window) == before


def test_fill_down_delete_shortcuts_and_undo(window):
    window.table.item(0, 1).setText("001")
    select(window, 0, 1, 2, 1)
    QTest.keyClick(window.table, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert [row[0] for row in values(window)] == ["001"] * 3
    QTest.keyClick(window.table, Qt.Key.Key_Delete)
    assert [row[0] for row in values(window)] == [""] * 3
    QTest.keyClick(window.table, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert [row[0] for row in values(window)] == ["001"] * 3
    window.undo()
    assert [row[0] for row in values(window)] == ["001", "", ""]


def test_fill_names_counts_and_preview_copy(window):
    select(window, 0, 1, 2, 1)
    window.fill_names()
    assert [row[0] for row in values(window)] == ["first", "second", "archive.tar"]
    assert "동일 3개" in window.totals.text()
    window.table.item(0, 1).setText(" first changed")
    assert "변경 1개" in window.totals.text()
    assert "background-color" in window.table.item(0, 4).data(Qt.ItemDataRole.UserRole)
    select(window, 0, 4)
    window.copy_cells()
    assert parse_clipboard(APP.clipboard().text()) == [[" first changed.txt"]]


def test_remove_rows_and_reorder_keep_identity_and_undo(window):
    select(window, 0, 1, 2, 1)
    window.fill_names()
    before = window._snapshot()
    window.table.verticalHeader().moveSection(0, 2)
    assert window.paths == [before[0][1], before[0][2], before[0][0]]
    assert [row[0] for row in values(window)] == ["second", "archive.tar", "first"]
    assert [window.table.verticalHeader().logicalIndex(i) for i in range(3)] == [0, 1, 2]
    select(window, 1, 1)
    window.remove_rows()
    assert [p.name for p in window.paths] == ["second.TXT", "first.txt"]
    window.undo()
    assert [row[0] for row in values(window)] == ["second", "archive.tar", "first"]
    window.undo()
    assert window._snapshot() == before


def test_columns_separator_and_redo_invalidation(window):
    before = window._snapshot()
    window.change_columns(1)
    window.separator.setText("_")
    window.undo()
    assert window.separator.text() == ""
    window.undo()
    assert window._snapshot() == before
    window.table.item(0, 1).setText("new")
    assert not window._redo


def test_keyboard_copy_paste_enter_and_editor_commit(window):
    window.show()
    select(window, 0, 1)
    APP.clipboard().setText("001\tzero")
    QTest.keyClick(window.table, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert values(window)[0] == ("001", "zero", "")
    select(window, 0, 1, 0, 2)
    QTest.keyClick(window.table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert parse_clipboard(APP.clipboard().text()) == [["001", "zero"]]
    select(window, 0, 1)
    QTest.keyClick(window.table, Qt.Key.Key_Return)
    assert window.table.currentRow() == 1
    window.table.editItem(window.table.item(1, 1))
    APP.processEvents()
    editor = APP.focusWidget()
    QTest.keyClicks(editor, "edited")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    APP.processEvents()
    assert window.table.item(1, 1).text() == "edited"
    window.undo()
    assert window.table.item(1, 1).text() == ""


def test_remove_all_restore_add_dedup_and_history(window):
    before = window._snapshot()
    select(window, 0, 1, 2, 1)
    window.remove_rows()
    assert not window.paths
    assert "변경 0개" in window.totals.text()
    window.add_paths(before[0])
    assert window.paths == list(before[0])
    window.add_paths(before[0])
    window.undo()  # duplicate addition did not create a history entry
    assert not window.paths
    window.undo()
    assert window._snapshot() == before
    window.redo()
    assert not window.paths


def test_five_columns_atomic_clear_and_empty_paste(window):
    window.change_columns(1)
    window.change_columns(1)
    select(window, 0, 1)
    APP.clipboard().setText("a\tb\tc\td\te")
    window.paste_cells()
    assert values(window)[0] == ("a", "b", "c", "d", "e")
    select(window, 0, 1, 0, 5)
    window.clear_cells()
    assert values(window)[0] == ("",) * 5
    window.undo()
    assert values(window)[0][-1] == "e"
    select(window, 0, 5)
    APP.clipboard().setText("")
    window.paste_cells()
    assert values(window)[0] == ("a", "b", "c", "d", "")


def test_readonly_preview_cannot_be_cleared_and_names_require_one_column(window):
    select(window, 0, 1, 2, 2)
    before = window._snapshot()
    window.fill_names()
    assert window._snapshot() == before
    select(window, 0, 4)
    window.clear_cells()
    assert window._snapshot() == before
