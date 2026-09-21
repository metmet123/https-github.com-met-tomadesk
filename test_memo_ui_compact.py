import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel


class CompactMemoUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "memo.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _panel(self):
        note_id = self.store.create_note("검사", "짧은 글자 선택 시험")
        panel = AlertNotesPanel(self.store)
        panel.resize(1600, 920)
        panel.update_responsive_layout(1600)
        panel.show()
        panel.show_note(note_id)
        self.app.processEvents()
        return panel, note_id

    def test_property_panel_uses_document_space_and_closed_shortcut_saves(self):
        panel, note_id = self._panel()
        editor = panel.editor
        self.assertEqual(editor.layout_mode, "compact")
        self.assertFalse(editor.property_panel.isVisible())
        baseline = editor.content_edit.mapTo(editor, QPoint(0, 0)).y()
        editor.property_chips.buttons["reminder"].click()
        self.app.processEvents()
        self.assertEqual(editor.property_panel.active_page, "reminder")
        self.assertGreater(editor.content_edit.mapTo(editor, QPoint(0, 0)).y(), baseline)
        self.assertTrue(editor.close_compact_panel())
        self.app.processEvents()
        editor.content_edit.setFocus()
        QTest.keyClick(editor.content_edit, Qt.Key.Key_1, Qt.KeyboardModifier.AltModifier)
        self.app.processEvents()
        self.assertEqual(len(self.store.pending_reminders_for_note(note_id)), 1)
        self.assertIn("🔔", editor.property_chips.buttons["reminder"].text())
        self.assertNotEqual(editor.property_chips.buttons["reminder"].toolTip(), "")
        close_alert_panel(panel, self.app)

    def test_summary_reopen_and_narrow_list_drawer(self):
        panel, _note_id = self._panel()
        self.assertFalse(panel.editor_remainder.isVisible())
        self.assertTrue(panel.editor.summary_button.isVisible())
        panel.editor.summary_button.click()
        self.app.processEvents()
        self.assertTrue(panel.editor_remainder.isVisible())
        panel.update_responsive_layout(900)
        self.app.processEvents()
        self.assertFalse(panel.list_panel.isVisible())
        panel.editor.sidebar_button.click()
        self.app.processEvents()
        self.assertTrue(panel.list_panel.isVisible())
        close_alert_panel(panel, self.app)

    def test_text_selection_tool_reserves_only_when_needed(self):
        panel, _note_id = self._panel()
        body = panel.editor.content_edit
        cursor = body.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
        body.setTextCursor(cursor)
        body.text_format_bar.sync()
        self.app.processEvents()
        self.assertTrue(body.text_format_bar.isVisible())
        self.assertFalse(body.block_action_bar.isVisible())
        self.assertFalse(body.character_action_bar.isVisible())
        self.assertFalse(panel.editor.format_panel.isVisible())
        if body.text_format_bar.is_reserved:
            self.assertEqual(body._block_action_bar_height, 42)
        body.text_format_bar.style_buttons["bold"].click()
        self.app.processEvents()
        selected = body.textCursor()
        self.assertTrue(selected.hasSelection())
        self.assertTrue(selected.charFormat().fontWeight() >= 700)
        body.text_format_bar.clear_selection()
        self.assertEqual(body._block_action_bar_height, 0)
        close_alert_panel(panel, self.app)

    def test_format_shortcut_remains_active_with_toolbar_folded(self):
        panel, _note_id = self._panel()
        body = panel.editor.content_edit
        cursor = body.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
        body.setTextCursor(cursor)
        body.setFocus()
        self.assertFalse(panel.editor.format_panel.isVisible())
        QTest.keyClick(body, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertTrue(body.textCursor().charFormat().fontWeight() >= 700)
        close_alert_panel(panel, self.app)

    def test_escape_closes_property_before_clearing_selection(self):
        panel, _note_id = self._panel()
        body = panel.editor.content_edit
        cursor = body.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
        body.setTextCursor(cursor)
        panel.editor._toggle_property_page("other")
        self.app.processEvents()
        body.setFocus()
        QTest.keyClick(body, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertFalse(panel.editor.property_panel.isVisible())
        self.assertTrue(body.textCursor().hasSelection())
        QTest.keyClick(body, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertFalse(body.textCursor().hasSelection())
        close_alert_panel(panel, self.app)

    def test_width_breakpoints_and_floating_selection_bar(self):
        panel, _note_id = self._panel()
        for width in (780, 900, 1080, 1920):
            panel.resize(width, 900)
            panel.update_responsive_layout(width)
            self.app.processEvents()
            self.assertEqual(panel.width(), width)
            self.assertEqual(
                panel.splitter.orientation() == Qt.Orientation.Vertical, width < 1080
            )
            self.assertTrue(panel.editor.property_chips.buttons["hotkey"].isVisible())
            self.assertTrue(panel.editor.property_chips.buttons["format"].isVisible())
            self.assertTrue(panel.editor.property_chips.more_button.isVisible())
            self.assertEqual(panel.editor_scroll.horizontalScrollBar().maximum(), 0)
            panel.editor.property_chips.buttons["reminder"].click()
            self.app.processEvents()
            last_quick = max(
                button.mapTo(panel.editor.property_panel, button.rect().topRight()).x()
                for button in panel.editor.quick_buttons.values()
            )
            self.assertLess(last_quick, panel.editor.property_panel.width())
            panel.editor.close_compact_panel()
        body = panel.editor.content_edit
        body.setPlainText("first\nsecond\nA fairly long selected third line\nfourth")
        start = len("first\nsecond\n")
        cursor = body.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(start + len("A fairly long selected third line"),
                           QTextCursor.MoveMode.KeepAnchor)
        body.setTextCursor(cursor)
        body.text_format_bar.sync()
        self.app.processEvents()
        self.assertTrue(body.text_format_bar.isVisible())
        self.assertFalse(body.text_format_bar.is_reserved)
        self.assertEqual(body._block_action_bar_height, 0)
        close_alert_panel(panel, self.app)

    def test_compact_control_order_heights_and_shared_status(self):
        panel, _note_id = self._panel()
        editor = panel.editor
        self.assertEqual(
            editor.property_chips.ORDER,
            ("format", "reminder", "deadline", "hotkey", "other"),
        )
        self.assertIs(editor.format_expand_button, editor.property_chips.buttons["format"])
        for button in editor.property_chips.buttons.values():
            self.assertEqual(button.height(), 28)
        self.assertEqual(editor.format_expand_button.height(), 28)
        self.assertEqual(editor.delete_button.text(), "삭제")
        self.assertEqual(editor.delete_button.height(), 28)
        self.assertIn("휴지통", editor.delete_button.toolTip())

        editor.property_chips.buttons["format"].click()
        self.app.processEvents()
        self.assertTrue(editor.format_panel.isVisible())
        self.assertLess(editor.property_chips.y(), editor.format_panel.y())
        self.assertTrue(editor.format_toolbar.preset_strip.isVisible())

        editor.show_action_feedback("메모를 저장했습니다.", "success")
        self.app.processEvents()
        self.assertIn("메모를 저장했습니다.", editor.saved_status.text())
        self.assertNotIn("메모를 저장했습니다.", panel.list_panel.action_status.text())
        self.assertNotIn("메모를 저장했습니다.", panel.status_label.text())
        self.assertFalse(editor.action_feedback.isVisible())
        panel.toggle_memo_list(True)
        self.app.processEvents()
        self.assertTrue(panel.status_label.isVisible())
        close_alert_panel(panel, self.app)

    def test_classic_setting_keeps_prior_controls(self):
        self.store.set_setting("memo_editor_layout", "classic")
        panel, _note_id = self._panel()
        self.assertEqual(panel.editor.layout_mode, "classic")
        self.assertFalse(hasattr(panel.editor, "property_chips"))
        self.assertTrue(panel.editor.format_toolbar.isVisible())
        close_alert_panel(panel, self.app)

    def test_new_note_focus_setting_applies_only_on_creation(self):
        self.store.set_setting("memo_new_note_focus_mode", "true")
        panel, note_id = self._panel()
        self.assertFalse(panel.editor_fullscreen)
        panel.create_note()
        self.app.processEvents()
        self.assertTrue(panel.editor_fullscreen)
        panel.toggle_editor_fullscreen(False)
        panel.show_note(note_id)
        self.assertFalse(panel.editor_fullscreen)
        close_alert_panel(panel, self.app)

    def test_postit_quick_reminder_shortcut_uses_its_own_window(self):
        panel, note_id = self._panel()
        panel._open_postit(self.store.note(note_id), show=True)
        postit = panel.postits[note_id]
        postit.memo.setFocus()
        QTest.keyClick(postit.memo, Qt.Key.Key_1, Qt.KeyboardModifier.AltModifier)
        self.app.processEvents()
        self.assertEqual(len(self.store.pending_reminders_for_note(note_id)), 1)
        close_alert_panel(panel, self.app)

    def test_ctrl_enter_saves_when_property_panel_is_closed(self):
        panel, note_id = self._panel()
        body = panel.editor.content_edit
        self.assertFalse(panel.editor.property_panel.isVisible())
        body.setFocus()
        QTest.keyClick(body, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(len(self.store.pending_reminders_for_note(note_id)), 1)
        close_alert_panel(panel, self.app)

    def test_heading_and_checklist_shortcuts_do_not_collide(self):
        panel, _note_id = self._panel()
        body = panel.editor.content_edit
        body.setPlainText("")
        body.setFocus()
        QTest.keyClick(body, Qt.Key.Key_1,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.app.processEvents()
        self.assertEqual(body.heading_level(body.textCursor().block()), 1)
        QTest.keyClick(body, Qt.Key.Key_6,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.app.processEvents()
        self.assertEqual(body.heading_level(body.textCursor().block()), 4)
        QTest.keyClick(body, Qt.Key.Key_4,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.app.processEvents()
        self.assertTrue(body._is_checklist_block(body.textCursor().block()))
        close_alert_panel(panel, self.app)

    def test_tab_indents_caret_line_and_selected_blocks_in_one_undo(self):
        panel, _note_id = self._panel()
        body = panel.editor.content_edit
        body.setPlainText("alpha\nbeta\ngamma")
        body.setFocus()
        caret = body.textCursor()
        caret.setPosition(2)
        body.setTextCursor(caret)
        QTest.keyClick(body, Qt.Key.Key_Tab)
        self.assertEqual(body._block_indent(body.document().firstBlock()), 1)
        QTest.keyClick(body, Qt.Key.Key_Backtab)
        self.assertEqual(body._block_indent(body.document().firstBlock()), 0)
        first = body.document().firstBlock()
        second = first.next()
        third = second.next()
        body.block_selection.set_positions((first.position(), third.position()))
        QTest.keyClick(body, Qt.Key.Key_Tab)
        self.assertEqual([body._block_indent(block) for block in (first, second, third)],
                         [1, 0, 1])
        QTest.keyClick(body, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual([body._block_indent(block) for block in (first, second, third)],
                         [0, 0, 0])
        close_alert_panel(panel, self.app)
