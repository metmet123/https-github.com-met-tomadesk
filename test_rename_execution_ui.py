import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from unittest.mock import patch
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox, QTableWidgetSelectionRange
from rename_engine import RenameEngine, windows_move
from file_rename_table import FileRenameWindow

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path):
    folder = tmp_path / "files"
    folder.mkdir()
    paths = [folder / name for name in ("a.txt", "b.txt", "c.txt")]
    for i, path in enumerate(paths):
        path.write_text(str(i))
    engine = RenameEngine(tmp_path / "journal" / "history.sqlite3")
    widget = FileRenameWindow(engine=engine)
    widget.add_paths(paths)
    yield widget
    widget.close()


def select(window, row, column):
    window.table.clearSelection()
    window.table.setCurrentCell(row, column)
    window.table.setRangeSelected(QTableWidgetSelectionRange(row, column, row, column), True)


def test_validate_disable_skip_bad_filter_and_copy(window):
    window.table.item(0, 1).setText("bad?")
    window.table.item(1, 1).setText("new")
    assert not window.execute_button.isEnabled()
    window.skip_invalid.setChecked(True)
    assert window.execute_button.isEnabled()
    window.problems_only.setChecked(True)
    assert not window.table.isRowHidden(0)
    assert window.table.isRowHidden(1)
    select(window, 0, 1)
    APP.clipboard().setText("x\ny")
    before = window._snapshot()
    window.paste_cells()
    assert window._snapshot() == before
    window.copy_errors()
    assert "금지" in APP.clipboard().text()
    select(window, 1, 1)  # Even a lingering/programmatic hidden selection is safe.
    window.remove_rows()
    assert window._snapshot() == before


def test_confirm_no_preserves_files_yes_updates_rows_and_file_undo(window):
    before = list(window.paths)
    window.table.item(0, 1).setText("b")
    window.table.item(1, 1).setText("a")
    assert window.execute_button.isEnabled()
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.No):
        window.execute_files()
    assert [p.read_text() for p in before] == ["0", "1", "2"]
    assert not window.engine.history()
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
        window.execute_files()
    assert window.paths == [before[1], before[0], before[2]]
    assert [p.read_text() for p in window.paths] == ["0", "1", "2"]
    assert not window._undo and not window._redo
    assert window.file_undo_button.isEnabled()
    assert "성공 2개" in window.status.text()
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
        window.undo_files()
    assert window.paths == before
    assert [p.read_text() for p in before] == ["0", "1", "2"]


def test_skip_invalid_confirm_changes_only_valid_files(window):
    before = list(window.paths)
    window.table.item(0, 1).setText("NUL")
    window.table.item(1, 1).setText("new")
    window.skip_invalid.setChecked(True)
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
        window.execute_files()
    assert before[0].read_text() == "0"
    assert window.paths[1].name == "new.txt"
    assert window.paths[1].read_text() == "1"
    assert window.table.item(0, 1).text() == "NUL"


def test_recover_reopened_dialog_needs_explicit_confirmation(window):
    calls = 0
    def fail(source, target, expected, parent):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise PermissionError("locked")
        windows_move(source, target, expected, parent)
    paths = list(window.paths)
    window.engine.move = fail
    window.table.item(0, 1).setText("b")
    window.table.item(1, 1).setText("a")
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
        window.execute_files()
    assert window.engine.pending()
    reopened = FileRenameWindow(engine=RenameEngine(window.engine.path))
    try:
        assert reopened.recover_button.isEnabled()
        assert not reopened.execute_button.isEnabled()
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.No):
            reopened.recover_files()
        assert reopened.engine.pending()
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
            reopened.recover_files()
        assert not reopened.engine.pending()
        assert [p.read_text() for p in paths] == ["0", "1", "2"]
    finally:
        reopened.close()


def test_external_change_during_confirmation_is_rejected(window):
    path = window.paths[0]
    window.table.item(0, 1).setText("new")
    def confirm(*_):
        path.write_text("changed")
        return QMessageBox.StandardButton.Yes
    with patch.object(QMessageBox, "exec", side_effect=confirm):
        window.execute_files()
    assert path.read_text() == "changed"
    assert not path.with_name("new.txt").exists()
    assert "중단" in window.status.text()


def test_selection_survives_edit_and_stage3_minimum_layout(window):
    select(window, 0, 1)
    window.table.item(0, 1).setText("new")
    assert window.table.selectedRanges()
    window.resize(620, 470)
    window.show()
    APP.processEvents()
    assert window.table.height() > 200
    assert window.height() >= 470


def test_main_uses_stable_journal_root_and_falls_back_safely(tmp_path):
    from main_window import MainWindow
    from test_settings_dday_ux import SettingsWindowTest
    case = SettingsWindowTest()
    case.setUpClass()
    case.setUp()
    try:
        with patch("main_window.user_storage_root", return_value=tmp_path), patch("main_window.foreground_application", return_value=None):
            case.window.show_file_rename(False)
        widget = case.window.file_rename_window
        assert widget.engine.path == tmp_path / "rename_history" / "history.sqlite3"
        widget.close()
        case.window.file_rename_window = None
        with patch("main_window.RenameEngine", side_effect=OSError("unavailable")), patch("main_window.foreground_application", return_value=None):
            case.window.show_file_rename(False)
        assert case.window.file_rename_window.engine is None
        assert not case.window.file_rename_window.execute_button.isEnabled()
        assert "미리보기" in case.window.file_rename_window.status.text()
        case.window.file_rename_window.close()
    finally:
        case.tearDown()
