import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

import main_window
from alert_notes.reminder_history import ReminderHistoryPanel
from alert_notes.schedule_editor import ScheduleEditor
from alert_notes.service import AlertService
from alert_notes.sqlite_store import NoteReminderStore
from hotkey_builder import HotkeyBuilder, split_hotkey_text
from hotkey_parser import parse_hotkey
from settings_dialog import HOTKEY_DEFAULTS, SettingsDialog
from store import Store


class StageOneQtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_three_modifier_hotkey_roundtrip_and_defaults(self):
        parsed = parse_hotkey("Ctrl+Alt+Shift+N")
        self.assertEqual(parsed.text, "Ctrl+Alt+Shift+N")
        self.assertEqual(split_hotkey_text(parsed.text), (["Ctrl", "Alt", "Shift"], "N"))
        builder = HotkeyBuilder()
        builder.setText(parsed.text)
        self.assertEqual(builder.text(), parsed.text)
        self.assertEqual(
            {key for key, value in HOTKEY_DEFAULTS.items() if not value},
            {"file_rename_hotkey"},
        )
        self.assertEqual(
            {key: parse_hotkey(value).text if key != "file_rename_hotkey" else ""
             for key, value in HOTKEY_DEFAULTS.items()},
            HOTKEY_DEFAULTS,
        )

    def test_settings_defaults_can_be_saved_and_invalid_change_keeps_original(self):
        with tempfile.TemporaryDirectory() as temp:
            dialog = SettingsDialog(HOTKEY_DEFAULTS, "window", Path(temp))
            dialog._validate_and_accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

            dialog = SettingsDialog(HOTKEY_DEFAULTS, "window", Path(temp))
            dialog.hotkey_builders["new_memo_hotkey"].setText(HOTKEY_DEFAULTS["quick_memo_hotkey"])
            with patch.object(QMessageBox, "information") as information:
                dialog._validate_and_accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.values()["new_memo_hotkey"], HOTKEY_DEFAULTS["new_memo_hotkey"])
            information.assert_called_once()

    def test_deadline_actions_keep_note_flag_consistent(self):
        with tempfile.TemporaryDirectory() as temp:
            store = NoteReminderStore(Path(temp) / "notes.db")
            try:
                note_id = store.create_note("마감", "내용")
                for action in ("delete", "complete", "clear"):
                    store.set_deadline(note_id, "209912312359", action, True)
                    reminder_id = int(store.pending_reminders_for_note(note_id)[0]["id"])
                    if action == "delete":
                        store.delete_reminder(reminder_id)
                    elif action == "complete":
                        store.complete_reminder(reminder_id)
                    else:
                        store.clear_reminder(note_id)
                    note = store.note(note_id)
                    self.assertEqual(note["d_day_at"], "209912312359")
                    self.assertEqual(note["d_day_alert"], 0)
            finally:
                store.close()

    def test_mirror_sync_preserves_item_identity_and_user_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            store = NoteReminderStore(Path(temp) / "notes.db")
            try:
                note_id = store.create_note("회의", "내용")
                reminder_id = store.add_reminder(note_id, "209901011000", "첫 알림")
                mirror = store.conn.execute(
                    "SELECT * FROM schedule_items WHERE source_reminder_id=?", (reminder_id,)
                ).fetchone()
                item_id = int(mirror["id"])
                with store.conn:
                    store.conn.execute(
                        "UPDATE schedule_items SET category='peach',priority=3 WHERE id=?", (item_id,)
                    )
                    store.conn.execute(
                        "INSERT INTO schedule_notifications(item_id,minutes_before) VALUES(?,15)", (item_id,)
                    )
                store.update_reminder(reminder_id, "209901021100", "변경 알림")
                updated = store.schedules.item(item_id)
                self.assertEqual(updated["source_reminder_id"], reminder_id)
                self.assertEqual(updated["start_at"], "209901021100")
                self.assertEqual(updated["category"], "peach")
                self.assertEqual(updated["priority"], 3)
                self.assertEqual(store.schedules.notifications(item_id), [15])
                with self.assertRaisesRegex(ValueError, "메모의 알림 설정"):
                    store.schedules.save_item({"id": item_id})

                editor = ScheduleEditor(store)
                editor.load_item(item_id)
                self.assertFalse(editor.save_button.isEnabled())
                self.assertFalse(editor.delete_button.isEnabled())
                self.assertFalse(editor.mirror_notice.isHidden())
            finally:
                store.close()

    def test_delete_buttons_require_checked_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            store = NoteReminderStore(Path(temp) / "notes.db")
            try:
                note_id = store.create_note("알림", "내용")
                reminder_id = store.add_reminder(note_id, "209901011000", "보존")
                panel = ReminderHistoryPanel(store)
                panel.pending_table.selectRow(0)
                with patch.object(QMessageBox, "question") as question:
                    panel._delete_pending()
                question.assert_not_called()
                self.assertIsNotNone(store.reminder(reminder_id))

                panel.pending_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                    panel._delete_pending()
                self.assertIsNone(store.reminder(reminder_id))
            finally:
                store.close()

    def test_alert_service_pause_is_nestable(self):
        store = MagicMock()
        store.due_reminders.return_value = []
        store.schedules.due_notifications.return_value = []
        service = AlertService(store, lambda _note_id: None)
        service.start()
        service.pause()
        service.pause()
        service.check_now()
        store.due_reminders.assert_not_called()
        service.resume(check_now=False)
        self.assertFalse(service.timer.isActive())
        service.resume(check_now=False)
        self.assertTrue(service.timer.isActive())
        service.stop()


class ExcelImportSafetyTest(unittest.TestCase):
    def test_cancelled_import_does_not_backup_or_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "hotkeys.db")
            try:
                action_id = store.save_action({
                    "name": "기존", "hotkey": "Ctrl+Alt+1", "action_type": "text",
                    "payload": {"text": "기존"}, "active": True,
                })
                store.delete_action(action_id)
                dummy = MagicMock()
                dummy.store = store
                imported = [{
                    "name": "신규", "hotkey": "Ctrl+Alt+2", "action_type": "text",
                    "payload": {"text": "신규"}, "active": True,
                }]
                with (
                    patch.object(main_window.QFileDialog, "getOpenFileName", return_value=("input.xlsx", "")),
                    patch.object(main_window, "import_actions_xlsx", return_value=imported),
                    patch.object(main_window.QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question,
                ):
                    main_window.MainWindow.import_excel(dummy)
                self.assertEqual(len(store.trashed_actions()), 1)
                self.assertEqual(list(Path(temp).glob("backup_*.json")), [])
                self.assertIn("영구 삭제될 휴지통 작업: 1개", question.call_args.args[2])
            finally:
                store.close()

    def test_backup_rotation_covers_manual_auto_and_restore_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            names = [
                "backup_20260101000000.json",
                "auto_backup_20260102.json",
                "before_restore_20260103000000.json",
                "backup_20260104000000.json",
            ]
            for index, name in enumerate(names):
                path = root / name
                path.write_text("{}", encoding="utf-8")
                os.utime(path, (index + 1, index + 1))
            dummy = MagicMock()
            dummy.store.backup_dir = root
            main_window.MainWindow._rotate_backups(dummy, keep=2)
            self.assertEqual(
                sorted(path.name for path in root.glob("*.json")),
                sorted(names[-2:]),
            )


if __name__ == "__main__":
    unittest.main()
