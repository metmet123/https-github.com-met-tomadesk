import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import QApplication, QToolButton

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel


class TextFormatRangePresetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "memo.db")
        self.note_id = self.store.create_note("선택 서식", "abcdef ghijkl")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _panel(self, editor_width=700):
        panel = AlertNotesPanel(self.store)
        panel.resize(1280, 820)
        panel.update_responsive_layout(1280)
        panel.show()
        panel.show_note(self.note_id)
        panel.editor.content_edit.setFixedWidth(editor_width)
        self.app.processEvents()
        return panel

    @staticmethod
    def _select(body, start=0, end=6):
        cursor = body.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        body.setTextCursor(cursor)
        body.text_format_bar.sync()

    def test_selection_bar_has_three_24px_preset_samples(self):
        panel = self._panel()
        body = panel.editor.content_edit
        self._select(body)
        self.app.processEvents()
        bar = body.text_format_bar
        self.assertTrue(bar.isVisible())
        self.assertEqual(tuple(bar.preset_strip.buttons), (1, 2, 3))
        self.assertTrue(all((button.width(), button.height()) == (24, 24)
                            for button in bar.preset_strip.buttons.values()))
        close_alert_panel(panel, self.app)

    def test_selection_preset_applies_and_checks_both_strips(self):
        panel = self._panel()
        body = panel.editor.content_edit
        toolbar = panel.editor.format_toolbar
        self._select(body)
        bar = body.text_format_bar
        bar.preset_strip.buttons[1].click()
        self.app.processEvents()
        self.assertTrue(body.textCursor().hasSelection())
        self.assertTrue(toolbar.preset_buttons[1].isChecked())
        self.assertTrue(bar.preset_strip.buttons[1].isChecked())
        close_alert_panel(panel, self.app)

    def test_main_save_refreshes_selection_icon_immediately(self):
        panel = self._panel()
        body = panel.editor.content_edit
        toolbar = panel.editor.format_toolbar
        self._select(body)
        self.app.processEvents()
        before = body.text_format_bar.preset_strip.buttons[2].icon().cacheKey()
        toolbar.current_color = QColor("#e11d48")
        toolbar.style_buttons["italic"].setChecked(True)
        toolbar.save_current_preset(2)
        self.app.processEvents()
        after = body.text_format_bar.preset_strip.buttons[2].icon().cacheKey()
        self.assertNotEqual(before, after)
        self.assertIn("#e11d48", body.text_format_bar.preset_strip.buttons[2].toolTip().lower())
        close_alert_panel(panel, self.app)

    def test_empty_selection_slot_opens_shared_management_menu(self):
        panel = self._panel()
        body = panel.editor.content_edit
        self._select(body)
        body.text_format_bar.preset_strip.buttons[2].click()
        self.app.processEvents()
        menu = body.text_format_bar._preset_menu
        self.assertIsNotNone(menu)
        self.assertTrue(menu.isVisible())
        self.assertEqual([action.text() for action in menu.actions()],
                         ["현재 서식 저장", "이름 바꾸기", "초기화"])
        menu.close()
        close_alert_panel(panel, self.app)

    def test_reserved_row_fits_515px_and_other_selection_modes_hide_it(self):
        panel = self._panel(515)
        body = panel.editor.content_edit
        bar = body.text_format_bar
        original = bar._candidate_clear
        bar._candidate_clear = lambda _candidate: False
        self._select(body)
        self.app.processEvents()
        self.assertTrue(bar.is_reserved)
        self.assertEqual(bar.width(), body.width() - 2 * body.frameWidth())
        for button in bar.findChildren(QToolButton):
            if button.isVisible():
                pos = button.mapTo(bar, QPoint(0, 0))
                self.assertTrue(bar.rect().contains(QRect(pos, button.size())),
                                f"{button.accessibleName()} {pos} {button.size()}")
        bar._candidate_clear = original
        body.character_selection.add_cursor(body.textCursor())
        bar.sync()
        self.app.processEvents()
        self.assertFalse(bar.isVisible())
        body.character_selection.clear()
        body.begin_block_selection(body.document().firstBlock())
        bar.sync()
        self.app.processEvents()
        self.assertFalse(bar.isVisible())
        close_alert_panel(panel, self.app)


if __name__ == "__main__":
    unittest.main()
