"""Focused checks for the memo body's local reading-width preference."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QTextImageFormat
from PyQt6.QtWidgets import QApplication, QInputDialog
import pytest

from alert_notes.editor import MemoEditor
from alert_notes.rich_memo_edit import IMAGE_ORIGINAL_HEIGHT, IMAGE_ORIGINAL_WIDTH, IMAGE_USER_WIDTH
from alert_notes.sqlite_store import NoteReminderStore
from ui_theme import scaled_stylesheet


def _editor(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "reading-width.db")
    editor = MemoEditor(store)
    editor.resize(1300, 900)
    editor.show()
    app.processEvents()
    return app, store, editor


def _close_editors(app, store, *editors):
    for editor in editors:
        editor.close()
        editor.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    store.close()


def test_setting_centers_only_body_and_survives_reopen(tmp_path, monkeypatch):
    app, store, editor = _editor(tmp_path)
    second = MemoEditor(store)
    second.resize(1300, 900)
    second.show()
    app.processEvents()
    try:
        original_title_width = editor.title_edit.width()
        wide = editor.content_edit.width()
        assert wide > editor.READING_BODY_WIDTH
        editor.content_edit.setPlainText("첫 줄\n둘째 줄")
        cursor = editor.content_edit.textCursor()
        cursor.setPosition(3)
        editor.content_edit.setTextCursor(cursor)
        original_html = editor.content_edit.toHtml()
        original_steps = editor.content_edit.document().availableUndoSteps()
        monkeypatch.setattr(QInputDialog, "getItem", lambda *_args: ("읽기 좋은 폭", True))
        editor._choose_reading_width()
        app.processEvents()
        assert store.setting(editor.READING_WIDTH_SETTING) == "reading"
        assert any(command.key == "reading_width" for command in editor.more_menu.commands)
        assert second.reading_width_mode
        assert second.content_edit.width() <= second.READING_BODY_WIDTH
        assert editor.content_edit.width() <= editor.READING_BODY_WIDTH
        assert editor.content_edit.x() > 0
        assert editor.title_edit.width() == original_title_width
        assert editor.content_edit.toHtml() == original_html
        assert editor.content_edit.textCursor().position() == 3
        assert editor.content_edit.document().availableUndoSteps() == original_steps
        editor.outline_button.click()
        app.processEvents()
        assert editor.outline_panel.isVisible()
        assert editor.content_edit.width() <= editor.READING_BODY_WIDTH
        editor.set_fullscreen(True)
        app.processEvents()
        assert editor.content_edit.width() <= editor.READING_BODY_WIDTH
        editor.set_fullscreen(False)
        editor.resize(550, 900)
        app.processEvents()
        assert editor.content_edit.width() <= editor.body_host.width()
        editor.close()
        reopened = MemoEditor(store)
        try:
            assert reopened.reading_width_mode
        finally:
            reopened.close()
            reopened.deleteLater()
    finally:
        _close_editors(app, store, second, editor)


def test_wide_table_and_image_use_full_body_without_rewriting_content(tmp_path):
    app, store, editor = _editor(tmp_path)
    try:
        editor.reading_width_mode = True
        editor._update_reading_width()
        app.processEvents()
        assert editor.content_edit.width() <= editor.READING_BODY_WIDTH
        cursor = editor.content_edit.textCursor()
        cursor.insertTable(1, 5)
        editor._refresh_reading_media()
        app.processEvents()
        assert editor._has_wide_media()
        assert editor.content_edit.width() > editor.READING_BODY_WIDTH
        before = editor.content_edit.toHtml()
        editor.reading_width_mode = False
        editor._update_reading_width()
        assert editor.content_edit.toHtml() == before
        editor.content_edit.clear()
        image = QTextImageFormat()
        image.setName("reading-width-test")
        image.setWidth(200)
        image.setProperty(IMAGE_ORIGINAL_WIDTH, 1000)
        cursor = editor.content_edit.textCursor()
        cursor.insertImage(image)
        assert editor._has_wide_media()
        image.setProperty(IMAGE_USER_WIDTH, 200)
        editor.content_edit.clear()
        editor.content_edit.textCursor().insertImage(image)
        assert not editor._has_wide_media()
        image.setProperty(IMAGE_ORIGINAL_HEIGHT, 100)
        image.setHeight(20)
        editor.content_edit.clear()
        editor.content_edit.textCursor().insertImage(image)
        editor.content_edit.document().setModified(False)
        before = editor.content_edit.toHtml()
        editor.reading_width_mode = True
        editor._refresh_reading_media()
        app.processEvents()
        assert editor.content_edit.toHtml() == before
        assert not editor.content_edit.document().isModified()
    finally:
        _close_editors(app, store, editor)


@pytest.mark.parametrize("scale", (1.0, 1.25, 1.5))
def test_reading_width_stays_inside_available_space_at_ui_scales(tmp_path, scale):
    app, store, editor = _editor(tmp_path)
    try:
        editor.setStyleSheet(scaled_stylesheet(scale))
        editor.reading_width_mode = True
        for width in (1300, 650, 550):
            editor.resize(width, 900)
            editor._refresh_reading_media()
            app.processEvents()
            assert editor.content_edit.width() <= editor.READING_BODY_WIDTH
            assert editor.content_edit.width() <= editor.body_host.width()
            assert editor.content_edit.x() >= 0
            if width == 550:
                assert editor.content_edit.width() >= editor.body_host.width() - 24
    finally:
        _close_editors(app, store, editor)
