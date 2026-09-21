import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.editor import MemoEditor
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget
from ui_theme import scaled_stylesheet


@pytest.fixture(scope="session")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui(application):
    app = application
    with TemporaryDirectory() as directory:
        store = NoteReminderStore(Path(directory) / "notes.db")
        note = store.create_note("검증 메모", "<h1>제목</h1><p>본문</p>")
        editor = MemoEditor(store)
        editor.setStyleSheet(scaled_stylesheet(1.0))
        editor.resize(800, 800)
        editor.show()
        editor.set_note(store.note(note))
        app.processEvents()
        yield app, editor, store
        editor.more_menu.close()
        editor.shutdown()
        destroy_widget(editor, app)
        store.close()


def test_outline_defaults_closed_and_returns_space(ui):
    app, editor, store = ui
    assert not editor.outline_button.isChecked()
    assert not editor.outline_panel.isVisible()
    initial_width = editor.content_edit.width()
    editor.outline_button.click()
    app.processEvents()
    assert editor.outline_panel.isVisible()
    assert editor.content_edit.width() < initial_width
    editor.resize(810, 790)
    app.processEvents()
    assert editor.outline_panel.isVisible()  # opening must not immediately undo itself
    assert editor.content_edit.geometry().right() < editor.outline_panel.geometry().left()
    editor.outline_panel.close_button.click()
    app.processEvents()
    assert not editor.outline_button.isChecked()
    assert editor.content_edit.width() >= initial_width
    second = MemoEditor(store)
    assert not second.outline_button.isChecked()
    second.shutdown()
    destroy_widget(second, app)


@pytest.mark.parametrize("width", [515, 620, 800])
def test_function_stays_next_to_format_without_opening_drawer(ui, width):
    app, editor, store = ui
    editor.resize(width, 800)
    app.processEvents()
    button = editor.function_button
    assert not editor.format_panel.isVisible()
    assert button.isVisible()
    assert editor.property_chips.more_button.text() == "더보기 ▾"
    assert button is editor.format_toolbar.insert_button
    assert button.menu() is editor.format_toolbar.insert_menu
    assert editor.property_chips.layout().itemAt(1).widget() is button
    editor.format_toolbar.apply_ui_scale(1.5)
    app.processEvents()
    assert button.size() == editor.fold_current_button.size()
    for widget in [button, *editor.property_chips.buttons.values()]:
        point = widget.mapTo(editor, QPoint())
        assert editor.rect().contains(QRect(point, widget.size()))


def test_more_search_dispatch_preserves_document_and_selection(ui):
    app, editor, store = ui
    callback = Mock()
    editor.memo_backup_requested.connect(callback)
    before = editor.content_edit.toPlainText()
    editor.property_chips.more_button.click()
    app.processEvents()
    menu = editor.more_menu
    menu.search.setText("백업")
    assert [c.key for c in menu.commands if not menu.rows[c.key].isHidden()] == ["backup"]
    QTest.keyClick(menu.search, Qt.Key.Key_Return)
    app.processEvents()
    callback.assert_called_once_with(editor)
    assert editor.content_edit.toPlainText() == before
    assert not menu.isVisible()


@pytest.mark.parametrize("outline", [False, True])
def test_more_is_inside_document_not_outline_and_escape_returns_focus(ui, outline):
    app, editor, store = ui
    editor.outline_button.setChecked(outline)
    app.processEvents()
    editor.property_chips.more_button.click()
    app.processEvents()
    bounds = QRect(editor.content_edit.mapToGlobal(QPoint()), editor.content_edit.size())
    assert bounds.contains(editor.more_menu.geometry())
    QTest.keyClick(editor.more_menu.search, Qt.Key.Key_Escape)
    app.processEvents()
    assert not editor.more_menu.isVisible()
    assert editor.property_chips.more_button.hasFocus()


def test_pins_persist_and_overflow_does_not_expand_editor(ui):
    app, editor, store = ui
    for command in editor.more_menu.commands:
        editor.more_menu.pin_buttons[command.key].click()
    app.processEvents()
    editor.resize(515, 800)
    app.processEvents()
    assert editor.width() == 515
    assert editor.pinned_commands.overflow.isVisible()
    assert editor.property_chips.more_button.isVisible()
    pins = json.loads(store.setting("memo_toolbar_pins"))
    assert len(pins) == len(editor.more_menu.commands)
    second = MemoEditor(store)
    assert second.more_menu.pins == pins
    second.shutdown()
    destroy_widget(second, app)
    editor.more_menu.pin_buttons["file"].click()
    assert "file" not in json.loads(store.setting("memo_toolbar_pins"))


def test_unknown_search_keeps_no_false_action(ui):
    app, editor, store = ui
    editor.property_chips.more_button.click()
    editor.more_menu.search.setText("없는 기능 987")
    assert editor.more_menu.empty.isVisible()
    QTest.keyClick(editor.more_menu.search, Qt.Key.Key_Return)
    assert editor.more_menu.isVisible()
