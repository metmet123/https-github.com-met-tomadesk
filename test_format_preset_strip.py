import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication, QMessageBox

from alert_notes.format_preset_strip import preset_sample_icon
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel


class FormatPresetStripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "memo.db")
        self.note_id = self.store.create_note("프리셋", "샘플")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _panel(self, *, classic=False):
        if classic:
            self.store.set_setting("memo_editor_layout", "classic")
        panel = AlertNotesPanel(self.store)
        panel.resize(1080, 820)
        panel.update_responsive_layout(1080)
        panel.show()
        panel.show_note(self.note_id)
        self.app.processEvents()
        return panel

    def test_empty_and_saved_icons_are_distinct_and_light_color_has_outline(self):
        saved = {
            "family": "Malgun Gothic", "size": 17, "color": "#ffffff",
            "bold": True, "italic": False, "underline": False, "strike": False,
        }
        empty = preset_sample_icon(None, 2, QSize(22, 22)).pixmap(22, 22).toImage()
        white = preset_sample_icon(saved, 2, QSize(22, 22)).pixmap(22, 22).toImage()
        self.assertNotEqual(empty, white)
        outline = QColor("#94a3b8")
        near_outline = 0
        for y in range(white.height()):
            for x in range(white.width()):
                color = white.pixelColor(x, y)
                if color.alpha() and sum(abs(a - b) for a, b in zip(
                        (color.red(), color.green(), color.blue()),
                        (outline.red(), outline.green(), outline.blue()))) < 45:
                    near_outline += 1
        self.assertGreater(near_outline, 4)

    def test_click_applies_saved_preset_and_style_change_clears_active(self):
        panel = self._panel()
        toolbar = panel.editor.format_toolbar
        toolbar.preset_buttons[1].click()
        self.app.processEvents()
        self.assertTrue(toolbar.preset_buttons[1].isChecked())
        toolbar.style_buttons["italic"].click()
        self.app.processEvents()
        self.assertFalse(any(button.isChecked() for button in toolbar.preset_buttons.values()))
        close_alert_panel(panel, self.app)

    def test_empty_slot_opens_management_menu_without_message_box(self):
        panel = self._panel()
        toolbar = panel.editor.format_toolbar
        with patch.object(QMessageBox, "information") as information:
            toolbar.preset_buttons[2].click()
            self.app.processEvents()
        information.assert_not_called()
        self.assertTrue(toolbar._slot_popup_menu.isVisible())
        self.assertEqual([action.text() for action in toolbar._slot_popup_menu.actions()],
                         ["현재 서식 저장", "이름 바꾸기", "초기화"])
        toolbar._slot_popup_menu.close()
        close_alert_panel(panel, self.app)

    def test_context_and_settings_menus_have_shared_slot_actions_and_shortcut_entry(self):
        panel = self._panel()
        toolbar = panel.editor.format_toolbar
        menu = toolbar.slot_menu(1)
        self.assertEqual([action.text() for action in menu.actions()],
                         ["현재 서식 저장", "이름 바꾸기", "초기화"])
        actions = toolbar.preset_settings_menu.actions()
        self.assertEqual([action.text() for action in actions[:3]], ["서식 1", "서식 2", "서식 3"])
        self.assertTrue(all(action.menu() is not None for action in actions[:3]))
        self.assertEqual(actions[-1].text(), "편집 단축키 설정…")
        spy = QSignalSpy(toolbar.shortcut_settings_requested)
        with patch("alert_notes.editor.EditorShortcutSettingsDialog.exec", return_value=0) as dialog_exec:
            actions[-1].trigger()
        self.assertEqual(len(spy), 1)
        dialog_exec.assert_called_once()
        close_alert_panel(panel, self.app)

    def test_twelve_character_name_stays_26_pixels_and_tooltip_keeps_name(self):
        panel = self._panel()
        toolbar = panel.editor.format_toolbar
        name = "가나다라마바사아자차카타"
        self.store.set_setting("text_format_preset_name_1", name)
        toolbar.reload_presets()
        button = toolbar.preset_buttons[1]
        self.assertEqual((button.width(), button.height()), (26, 26))
        self.assertEqual(button.toolTip().splitlines()[0], name)
        close_alert_panel(panel, self.app)

    def test_legacy_json_is_applied_without_rewriting_storage(self):
        panel = self._panel()
        toolbar = panel.editor.format_toolbar
        payload = {
            "family": toolbar.font_box.currentFont().family(), "size": 18, "color": "#e11d48",
            "bold": True, "italic": True, "underline": True, "strike": False,
        }
        raw = json.dumps(payload, ensure_ascii=False)
        self.store.set_setting("text_format_preset_2", raw)
        toolbar.reload_presets()
        toolbar.preset_buttons[2].click()
        self.app.processEvents()
        current = toolbar.format_data()
        self.assertEqual(current["family"], payload["family"])
        self.assertEqual(current["size"], payload["size"])
        self.assertEqual(current["color"], payload["color"])
        self.assertTrue(current["bold"] and current["italic"] and current["underline"])
        self.assertEqual(self.store.setting("text_format_preset_2"), raw)
        close_alert_panel(panel, self.app)

    def test_classic_keeps_preset_strip_in_existing_below_body_position(self):
        panel = self._panel(classic=True)
        editor = panel.editor
        self.assertTrue(editor.preset_host.isVisible())
        self.assertIs(editor.preset_layout.itemAt(0).widget(), editor.format_toolbar.preset_strip)
        close_alert_panel(panel, self.app)


if __name__ == "__main__":
    unittest.main()
