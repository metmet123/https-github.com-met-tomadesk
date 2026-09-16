import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel


class MemoRemediationUiC1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "memo.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _panel(self, *, classic=False):
        if classic:
            self.store.set_setting("memo_editor_layout", "classic")
        note_id = self.store.create_note("UI-C1", "서식 패널 검사")
        panel = AlertNotesPanel(self.store)
        panel.resize(1080, 820)
        panel.update_responsive_layout(1080)
        panel.show()
        panel.show_note(note_id)
        self.app.processEvents()
        return panel

    def test_format_is_first_chip_and_reuses_single_toggle_path(self):
        panel = self._panel()
        editor = panel.editor
        self.assertEqual(editor.property_chips.ORDER[0], "format")
        self.assertIs(editor.format_expand_button, editor.property_chips.buttons["format"])
        self.assertTrue(editor.property_chips.format_separator.isVisible())
        root = editor.layout()
        self.assertLess(root.indexOf(editor.property_chips), root.indexOf(editor.property_panel))
        self.assertLess(root.indexOf(editor.property_panel), root.indexOf(editor.format_panel))
        self.assertLess(root.indexOf(editor.format_panel), root.indexOf(editor.body_host))
        close_alert_panel(panel, self.app)

    def test_five_format_cycles_do_not_move_reminder_chip(self):
        panel = self._panel()
        editor = panel.editor
        format_button = editor.property_chips.buttons["format"]
        reminder_button = editor.property_chips.buttons["reminder"]
        baseline = reminder_button.mapTo(editor, QPoint(0, 0)).y()
        for _ in range(5):
            format_button.click()
            self.app.processEvents()
            self.assertTrue(editor.format_panel.isVisible())
            self.assertEqual(reminder_button.mapTo(editor, QPoint(0, 0)).y(), baseline)
            format_button.click()
            self.app.processEvents()
            self.assertFalse(editor.format_panel.isVisible())
            self.assertEqual(reminder_button.mapTo(editor, QPoint(0, 0)).y(), baseline)
        close_alert_panel(panel, self.app)

    def test_format_and_property_drawers_are_mutually_exclusive(self):
        panel = self._panel()
        editor = panel.editor
        editor.property_chips.buttons["format"].click()
        self.app.processEvents()
        self.assertTrue(editor.format_panel.isVisible())
        self.assertFalse(editor.property_panel.isVisible())

        editor.property_chips.buttons["reminder"].click()
        self.app.processEvents()
        self.assertFalse(editor.format_panel.isVisible())
        self.assertTrue(editor.property_panel.isVisible())
        self.assertEqual(editor.property_panel.active_page, "reminder")

        editor.property_chips.buttons["format"].click()
        self.app.processEvents()
        self.assertTrue(editor.format_panel.isVisible())
        self.assertFalse(editor.property_panel.isVisible())
        self.assertIsNone(editor.property_panel.active_page)
        self.assertTrue(editor.property_chips.buttons["format"].isChecked())
        self.assertFalse(editor.property_chips.buttons["reminder"].isChecked())
        close_alert_panel(panel, self.app)

    def test_escape_closes_format_and_updates_accessibility(self):
        panel = self._panel()
        editor = panel.editor
        button = editor.property_chips.buttons["format"]
        self.assertEqual(button.accessibleName(), "서식 도구 펼치기")
        button.click()
        self.app.processEvents()
        self.assertEqual(button.accessibleName(), "서식 도구 접기")
        editor.content_edit.setFocus()
        QTest.keyClick(editor.content_edit, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertFalse(editor.format_panel.isVisible())
        self.assertFalse(any(value.isChecked() for value in editor.property_chips.buttons.values()))
        self.assertEqual(button.accessibleName(), "서식 도구 펼치기")
        close_alert_panel(panel, self.app)

    def test_classic_layout_keeps_original_format_toolbar(self):
        panel = self._panel(classic=True)
        editor = panel.editor
        self.assertFalse(hasattr(editor, "property_chips"))
        self.assertTrue(editor.format_toolbar.isVisible())
        close_alert_panel(panel, self.app)


if __name__ == "__main__":
    unittest.main()
