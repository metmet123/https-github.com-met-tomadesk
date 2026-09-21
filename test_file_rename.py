import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QMimeData, QUrl, QPointF, Qt
from PyQt6.QtGui import QDropEvent
from file_rename import compose_name, load_files, mark_edge_spaces, explorer_selection
from file_rename_table import FileRenameWindow

APP = QApplication.instance() or QApplication([])


def test_name_rules():
    assert compose_name("old.TXT", [" 테스트", "", "01"], "_") == " 테스트_01.TXT"
    assert compose_name("archive.tar.gz", ["new", "", ""]) == "new.gz"
    assert compose_name("noextension", ["new", "x"], " ") == "new x"
    assert compose_name("old.txt", ["", "", ""]) is None
    assert compose_name("old.txt", [" ", "", ""]) == " .txt"
    assert mark_edge_spaces("  value  ") == "··value··"
    assert mark_edge_spaces("  ") == "··"


def test_load_preserves_order_and_files(tmp_path):
    paths = [tmp_path / name for name in ["z.txt", "a.txt", "b.txt"]]
    for path in paths:
        path.write_text("unchanged", encoding="utf-8")
    accepted, skipped = load_files(paths + [paths[0], tmp_path, tmp_path / "missing"])
    assert accepted == paths
    assert len(skipped) == 2
    assert load_files(paths, existing=paths) == ([], [])
    assert all(path.read_text(encoding="utf-8") == "unchanged" for path in paths)


def test_explorer_selection_retains_shell_order():
    window = MagicMock()
    window.HWND = 42
    window.Document.SelectedItems.return_value.Count = 2
    view = window._oleobj_.QueryInterface.return_value.QueryService.return_value.QueryActiveShellView.return_value
    with patch("win32gui.GetClassName", return_value="CabinetWClass"), patch(
        "win32com.shell.shell.DragQueryFileW", side_effect=lambda handle, i: 2 if i == -1 else ["z.txt", "a.txt"][i]
    ):
        assert explorer_selection(42, [window]) == ["z.txt", "a.txt"]
        assert view.GetItemObject.call_args.args[0] == 0x80000001
        assert explorer_selection(43, [window]) == []
    with patch("win32gui.GetClassName", return_value="Chrome_WidgetWin_1"):
        assert explorer_selection(42, [window]) == []


def test_preview_columns_preserve_values_and_never_rename(tmp_path):
    path = tmp_path / "원본.txt"
    path.write_text("original", encoding="utf-8")
    window = FileRenameWindow()
    try:
        window.add_paths([path])
        assert window.table.item(0, 4).text() == "건너뜀"
        window.table.item(0, 1).setText(" 새")
        window.table.item(0, 3).setText("01")
        window.separator.setText("_")
        assert window.table.item(0, 4).text() == "·새_01.txt"
        assert not window.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable
        assert not window.table.item(0, 4).flags() & Qt.ItemFlag.ItemIsEditable
        window.change_columns(-1)
        assert window.input_columns == 3  # populated column is protected
        window.change_columns(1)
        window.change_columns(1)
        window.change_columns(1)
        assert window.input_columns == 5
        assert window.table.item(0, 6).text() == "·새_01.txt"
        window.change_columns(-1)
        window.change_columns(-1)
        window.table.item(0, 3).setText("")
        window.change_columns(-1)
        window.change_columns(-1)
        assert window.input_columns == 2
        window.add_paths([path])
        assert window.table.rowCount() == 1
        assert window.table.item(0, 1).text() == " 새"
        assert not window.execute_button.isEnabled()
        assert list(tmp_path.iterdir()) == [path]
        assert path.read_text(encoding="utf-8") == "original"
        window.resize(620, 400)
        window.show()
        APP.processEvents()
        assert window.table.height() > 200
    finally:
        window.close()


def test_local_url_drop(tmp_path):
    path = tmp_path / "drop.txt"
    path.touch()
    window = FileRenameWindow()
    try:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)), QUrl("https://example.com/file")])
        event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        window.dropEvent(event)
        assert window.paths == [path]
        assert event.isAccepted()
    finally:
        window.close()


def test_main_window_captures_before_activation_and_reuses_dialog():
    from main_window import MainWindow
    calls = []
    dialog = SimpleNamespace(
        add_paths=lambda paths: calls.append(("paths", paths)),
        show=lambda: calls.append("show"), raise_=lambda: None, activateWindow=lambda: None,
    )
    fake = SimpleNamespace(_recording=False, _macro_playing=False, excluded_apps=[],
                           file_rename_window=dialog)
    with patch("main_window.foreground_application", return_value=None), patch(
        "main_window.explorer_selection", return_value=["z.txt"]
    ) as capture:
        MainWindow.show_file_rename(fake)
        assert calls == [("paths", ["z.txt"]), "show"]
        fake._recording = True
        MainWindow.show_file_rename(fake)
        assert capture.call_count == 1


def test_rename_hotkey_save_clear_registration_and_collision():
    from test_settings_dday_ux import SettingsWindowTest
    from main_window import FILE_RENAME_HOTKEY_ID
    from PyQt6.QtWidgets import QMessageBox
    case = SettingsWindowTest()
    case.setUpClass()
    case.setUp()
    try:
        for hotkey in ("Ctrl+Alt+R", ""):
            case.window.show_settings()
            dialog = case.window._settings_dialog
            dialog.hotkey_builders["file_rename_hotkey"].setText(hotkey)
            with patch.object(QMessageBox, "information"), patch.object(QMessageBox, "warning") as warning:
                dialog._validate_and_accept()
            assert not warning.called
            assert case.store.setting("file_rename_hotkey", "unset") == hotkey
            assert case.window.file_rename_hotkey == hotkey
            assert (FILE_RENAME_HOTKEY_ID in case.window.hotkeys.registered) == bool(hotkey)
            if hotkey:
                import pytest
                with pytest.raises(ValueError):
                    case.window._validate_unique_hotkey(hotkey, None)
                with pytest.raises(ValueError):
                    case.window._validate_content_hotkey(hotkey)
            APP.processEvents()
    finally:
        case.tearDown()
