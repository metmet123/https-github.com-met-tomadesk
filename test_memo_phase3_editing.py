"""Phase 3 memo folding, spacing, paste, and keyboard behavior."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QTextCharFormat, QTextCursor, QWheelEvent
from PyQt6.QtWidgets import QApplication

from alert_notes.editor import MemoEditor
from alert_notes.editor_shortcut_settings import EditorShortcutSettingsDialog
from alert_notes.note_shortcuts import STRUCTURE_SHORTCUTS
from alert_notes.rich_memo_edit import HEADING_FOLDED_PREFIX, RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


class MemoPhaseThreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.widgets = []

    def tearDown(self):
        for widget in reversed(self.widgets):
            destroy_widget(widget, self.app)
        self.store.close()
        self.temp.cleanup()

    def editor(self, text=""):
        widget = RichMemoTextEdit(self.store)
        widget.setPlainText(text)
        widget.resize(620, 400)
        self.widgets.append(widget)
        return widget

    @staticmethod
    def block(editor, index):
        return editor.document().findBlockByNumber(index)

    def heading(self, editor, index, level):
        editor.setTextCursor(QTextCursor(self.block(editor, index)))
        editor.apply_heading(level)

    def test_nested_headings_fold_only_their_section_and_survive_reopen(self):
        editor = self.editor("H1\nintro\nH2\nnested\nH1 peer\nend")
        self.heading(editor, 0, 1)
        self.heading(editor, 2, 2)
        self.heading(editor, 4, 1)
        self.assertTrue(editor.fold_heading(self.block(editor, 2)))
        self.assertEqual([self.block(editor, i).isVisible() for i in range(6)],
                         [True, True, True, False, True, True])
        self.assertTrue(editor.fold_heading(self.block(editor, 0)))
        self.assertEqual([self.block(editor, i).isVisible() for i in range(6)],
                         [True, False, False, False, True, True])
        saved = editor.content()
        clone = self.editor()
        clone.set_content(saved)
        self.assertEqual(clone.heading_level(self.block(clone, 0)), 1)
        self.assertTrue(self.block(clone, 0).text().startswith(HEADING_FOLDED_PREFIX))
        self.assertEqual([self.block(clone, i).isVisible() for i in range(6)],
                         [True, False, False, False, True, True])
        clone.fold_heading(self.block(clone, 0))
        self.assertEqual([self.block(clone, i).isVisible() for i in range(6)],
                         [True, True, True, False, True, True])

    def test_heading_marker_has_a_mouse_path_to_fold_and_unfold(self):
        editor = self.editor("Heading\nchild")
        editor.show()
        self.app.processEvents()
        self.heading(editor, 0, 1)
        self.app.processEvents()
        heading = self.block(editor, 0)
        point = editor._heading_marker_rect(heading).center()
        for expected in (False, True):
            event = QMouseEvent(
                QMouseEvent.Type.MouseButtonRelease, QPointF(point), QPointF(point),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            editor.mouseReleaseEvent(event)
            self.assertEqual(self.block(editor, 1).isVisible(), expected)
            point = editor._heading_marker_rect(heading).center()

    def test_same_level_heading_inside_toggle_does_not_end_outer_section(self):
        editor = self.editor("Outer\n▾ group\nInner\ninside\nPeer\nafter")
        self.heading(editor, 0, 1)
        self.heading(editor, 2, 1)
        self.heading(editor, 4, 1)
        for index in (2, 3):
            block = self.block(editor, index)
            fmt = block.blockFormat()
            fmt.setIndent(1)
            QTextCursor(block).setBlockFormat(fmt)
        editor.fold_heading(self.block(editor, 0))
        self.assertEqual([self.block(editor, i).isVisible() for i in range(6)],
                         [True, False, False, False, True, True])

    def test_all_folds_includes_nested_toggle_and_one_undo_restores(self):
        editor = self.editor("Title\n▾ group\ninside\npeer")
        self.heading(editor, 0, 1)
        inside = self.block(editor, 2)
        fmt = inside.blockFormat()
        fmt.setIndent(1)
        QTextCursor(inside).setBlockFormat(fmt)
        editor.document().clearUndoRedoStacks()
        self.assertFalse(editor.toggle_all_folds())
        self.assertFalse(self.block(editor, 2).isVisible())
        self.assertTrue(self.block(editor, 0).text().startswith(HEADING_FOLDED_PREFIX))
        editor.undo()
        self.assertFalse(self.block(editor, 0).text().startswith(HEADING_FOLDED_PREFIX))
        self.assertTrue(self.block(editor, 1).text().startswith("▾ "))

    def test_line_spacing_mixed_selection_undo_and_html_round_trip(self):
        editor = self.editor("one\ntwo\nthree")
        editor.setTextCursor(QTextCursor(self.block(editor, 0)))
        self.assertTrue(editor.apply_line_spacing(1.5))
        select = QTextCursor(editor.document())
        select.setPosition(self.block(editor, 0).position())
        select.setPosition(self.block(editor, 1).position() + 1, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(select)
        self.assertIsNone(editor.selected_line_spacing())
        editor.document().clearUndoRedoStacks()
        self.assertTrue(editor.apply_line_spacing(2.0))
        self.assertEqual(editor.selected_line_spacing(), 2.0)
        editor.undo()
        editor.setTextCursor(select)
        self.assertIsNone(editor.selected_line_spacing())
        clone = self.editor()
        clone.set_content(editor.content())
        self.assertEqual(self.block(clone, 0).blockFormat().lineHeight(), 150)

    def test_line_spacing_uses_non_contiguous_phase2_block_selection(self):
        editor = self.editor("first\nmiddle\nlast")
        editor.block_selection.toggle(self.block(editor, 0), include_family=False)
        editor.block_selection.toggle(self.block(editor, 2), include_family=False)
        editor.document().clearUndoRedoStacks()
        self.assertTrue(editor.apply_line_spacing(1.15))
        self.assertEqual([self.block(editor, i).blockFormat().lineHeight() for i in range(3)],
                         [115, 0, 115])
        editor.undo()
        self.assertEqual([self.block(editor, i).blockFormat().lineHeight() for i in range(3)],
                         [0, 0, 0])

    def test_three_paste_modes_keep_distinct_format_and_each_undo(self):
        editor = self.editor("target")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        fmt = QTextCharFormat()
        fmt.setFontItalic(True)
        editor.setCurrentCharFormat(fmt)
        source = QMimeData()
        source.setHtml("<b>source</b>")
        source.setText("source")
        QApplication.clipboard().setMimeData(source)
        editor.document().clearUndoRedoStacks()
        editor.insertFromMimeData(source)
        self.assertIn("source", editor.toPlainText())
        self.assertGreaterEqual(editor.textCursor().charFormat().fontWeight(), 700)
        editor.undo()
        self.assertEqual(editor.toPlainText(), "target")
        editor.setCurrentCharFormat(fmt)
        editor.paste_matching_format()
        self.assertTrue(editor.textCursor().charFormat().fontItalic())
        editor.undo()
        self.assertEqual(editor.toPlainText(), "target")
        editor.paste_as_plain_text()
        self.assertFalse(editor.textCursor().charFormat().fontWeight() >= 700)
        self.assertFalse(editor.textCursor().charFormat().fontItalic())
        editor.undo()
        self.assertEqual(editor.toPlainText(), "target")

    def test_keyboard_shortcuts_open_only_valid_internal_link_and_toggle_fold(self):
        wrapper = MemoEditor(self.store)
        self.widgets.append(wrapper)
        body = wrapper.content_edit
        body.setPlainText("Title\nplain")
        body.setTextCursor(QTextCursor(self.block(body, 0)))
        body.apply_heading1()
        self.assertEqual(len(wrapper.structure_shortcuts), len(STRUCTURE_SHORTCUTS))
        wrapper.structure_shortcuts[1].activated.emit()
        self.assertFalse(self.block(body, 1).isVisible())
        wrapper.structure_shortcuts[1].activated.emit()
        self.assertTrue(self.block(body, 1).isVisible())
        body.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right,
                                     Qt.KeyboardModifier.AltModifier))
        self.assertEqual(body.textCursor().blockNumber(), 1)
        body.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Left,
                                     Qt.KeyboardModifier.AltModifier))
        self.assertEqual(body.textCursor().blockNumber(), 0)
        opened = []
        body.page_open_requested.connect(opened.append)
        wrapper.structure_shortcuts[0].activated.emit()
        self.assertEqual(opened, [])
        target = self.store.create_note("연결 대상", "")
        body.setPlainText("")
        cursor = body.textCursor()
        body._write_link_run(cursor, target, "연결 대상")
        cursor.setPosition(body.document().firstBlock().position() + 2)
        body.setTextCursor(cursor)
        wrapper.structure_shortcuts[0].activated.emit()
        self.assertEqual(opened, [target])
        body.setPlainText("")
        stale = QTextCharFormat()
        stale.setAnchor(True)
        stale.setAnchorHref(f"toma-note://{target}")
        cursor = body.textCursor()
        cursor.insertText("일반 글", stale)
        body.setTextCursor(cursor)
        wrapper.structure_shortcuts[0].activated.emit()
        self.assertEqual(opened, [target])
        dialog = EditorShortcutSettingsDialog(self.store)
        self.widgets.append(dialog)
        self.assertEqual(dialog.structure_builders["open_link"].text(), "Ctrl+Alt+Enter")

    def test_spacing_wheel_is_ignored_with_and_without_focus(self):
        wrapper = MemoEditor(self.store)
        self.widgets.append(wrapper)
        wrapper.show()
        combo = wrapper.format_toolbar.line_spacing_box
        self.app.processEvents()
        original = combo.currentIndex()
        for focused in (False, True):
            (combo if focused else wrapper.content_edit).setFocus()
            wheel = QWheelEvent(
                QPointF(8, 8), QPointF(8, 8), QPoint(0, 0), QPoint(0, 120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate, False,
            )
            QApplication.sendEvent(combo, wheel)
            self.assertEqual(combo.currentIndex(), original)

    def test_shortcut_dialog_rejects_existing_reminder_binding(self):
        dialog = EditorShortcutSettingsDialog(self.store)
        self.widgets.append(dialog)
        dialog.structure_builders["open_link"].setText("Ctrl+Enter")
        with patch("alert_notes.editor_shortcut_settings.QMessageBox.warning") as warning:
            dialog._save()
        warning.assert_called_once()
        self.assertEqual(self.store.setting(STRUCTURE_SHORTCUTS["open_link"][1], ""), "")


if __name__ == "__main__":
    unittest.main()
