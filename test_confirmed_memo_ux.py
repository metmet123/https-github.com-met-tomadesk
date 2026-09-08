import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.panel import AlertNotesPanel
from alert_notes.recurrence import RULE_DAILY, RecurrenceRule
from alert_notes.rich_text import plain_text_from_content
from alert_notes.sqlite_store import NoteReminderStore
from settings_dialog import SettingsDialog
from qt_test_support import close_alert_panel
from main_window import MainWindow


class ConfirmedMemoUxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("원본", "저장된 본문")
        self.store.set_setting("memo_auto_save_enabled", "false")
        self.panel = AlertNotesPanel(self.store)
        self.panel.current_id = self.note_id
        self.panel.refresh()
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_manual_mode_keeps_draft_until_button_or_scoped_ctrl_s(self):
        editor = self.panel.editor
        self.assertFalse(editor.manual_save_button.isHidden())
        self.assertTrue(editor.manual_save_shortcut.isEnabled())
        self.assertEqual(
            editor.manual_save_shortcut.context(),
            Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        editor.content_edit.setPlainText("미저장 초안")
        QTest.qWait(450)
        self.app.processEvents()
        self.assertEqual(plain_text_from_content(self.store.note(self.note_id)["content"]), "저장된 본문")
        self.assertTrue(self.store.setting(f"memo_draft_{self.note_id}", ""))

        editor.manual_save_button.click()
        self.app.processEvents()
        self.assertEqual(plain_text_from_content(self.store.note(self.note_id)["content"]), "미저장 초안")
        self.assertEqual(self.store.setting(f"memo_draft_{self.note_id}", ""), "")
        self.assertIn("메모를 저장했습니다", editor.action_feedback.text())

    def test_reminder_buttons_require_explicit_save_and_do_not_save_memo(self):
        editor = self.panel.editor
        captured = []
        editor.reminder_save_requested.connect(captured.append)
        editor.content_edit.setPlainText("알림에는 사용하지만 메모는 미저장")
        editor.quick_buttons[5].click()
        self.assertEqual(captured, [])
        editor.reminder_save_button.click()
        self.app.processEvents()
        self.assertEqual(len(captured), 1)
        self.assertEqual(plain_text_from_content(self.store.note(self.note_id)["content"]), "저장된 본문")
        self.assertEqual(len(self.store.pending_reminders_for_note(self.note_id)), 1)
        self.assertIn("알림을 저장했습니다", editor.action_feedback.text())

    def test_shortcut_reminder_still_saves_immediately_and_recurrence_summary_returns(self):
        editor = self.panel.editor
        captured = []
        editor.reminder_save_requested.connect(captured.append)
        editor.time_shortcuts[0].activated.emit()
        self.assertEqual(len(captured), 1)
        editor.reminder_toggle.setChecked(True)
        editor.recurrence.set_rule(RecurrenceRule(RULE_DAILY))
        self.app.processEvents()
        self.assertTrue(editor.recurrence.summary_label.isVisible())
        self.assertTrue(editor.recurrence.next_label.isVisible())

    def test_settings_expose_autosave_and_quick_start_choices(self):
        dialog = SettingsDialog(
            {}, "window", Path(self.temp.name),
            memo_auto_save_enabled=False,
            show_start_guide_on_launch=False,
        )
        values = dialog.values()
        self.assertFalse(values["memo_auto_save_enabled"])
        self.assertFalse(values["show_start_guide_on_launch"])
        dialog.close()

    def test_new_action_type_only_is_not_a_substantive_dirty_change(self):
        class FormStub:
            _action_form_baseline = {"id": None, "type": "text", "name": "", "text": ""}

            def _action_form_state(self):
                return {"id": None, "type": "url", "name": "", "text": ""}

        form = FormStub()
        self.assertFalse(MainWindow._action_form_is_dirty(form))
        form._action_form_state = lambda: {
            "id": None, "type": "url", "name": "입력함", "text": "",
        }
        self.assertTrue(MainWindow._action_form_is_dirty(form))

    def test_manual_drafts_expire_after_seven_days(self):
        key = f"memo_draft_{self.note_id}"
        self.store.set_setting(key, json.dumps({
            "saved_at": (datetime.now() - timedelta(days=8)).strftime("%Y%m%d%H%M"),
            "values": {"title": "만료", "content": "만료"},
        }))
        self.assertEqual(self.store.purge_expired_memo_drafts(7), 1)
        self.assertEqual(self.store.setting(key, ""), "")


if __name__ == "__main__":
    unittest.main()
