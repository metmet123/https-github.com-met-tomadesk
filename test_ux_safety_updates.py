from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from alert_notes.sqlite_store import NoteReminderStore
from storage_config import load_storage_paths, save_storage_paths
from store import Store


class SevenDayTrashTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_action_delete_is_recoverable(self):
        store = Store(self.root / "hotkeys.db")
        try:
            action_id = store.save_action({
                "name": "복원 작업", "hotkey": "Ctrl+Alt+F8", "action_type": "text",
                "active": True, "payload": {"text": "복원"},
            })
            store.delete_action(action_id)
            self.assertIsNone(store.action(action_id))
            self.assertEqual([row["id"] for row in store.trashed_actions()], [action_id])
            store.restore_action(action_id)
            self.assertIsNotNone(store.action(action_id))
            self.assertFalse(bool(store.action(action_id)["active"]))
        finally:
            store.close()

    def test_note_and_linked_schedule_restore_together(self):
        notes = NoteReminderStore(self.root / "notes.db", "새 메모")
        try:
            note_id = notes.create_note("복원 메모", "내용")
            schedule_id = notes.schedules.save_item({
                "title": "연결 일정", "note_id": note_id,
                "start_at": "209901010900", "end_at": "209901011000",
            })
            notes.delete_note(note_id)
            self.assertIsNone(notes.note(note_id))
            self.assertIsNone(notes.schedules.item(schedule_id))
            notes.restore_note(note_id)
            self.assertIsNotNone(notes.note(note_id))
            self.assertIsNotNone(notes.schedules.item(schedule_id))
        finally:
            notes.close()

    def test_schedule_delete_is_recoverable(self):
        notes = NoteReminderStore(self.root / "notes.db", "새 메모")
        try:
            item_id = notes.schedules.save_item({
                "title": "복원 일정", "start_at": "209901010900", "end_at": "209901011000",
            })
            notes.schedules.delete_item(item_id)
            self.assertIsNone(notes.schedules.item(item_id))
            notes.schedules.restore_item(item_id)
            self.assertIsNotNone(notes.schedules.item(item_id))
        finally:
            notes.close()


class UnifiedBackupPathTest(unittest.TestCase):
    def test_storage_config_keeps_backups_in_the_data_folder(self):
        """A backup argument is accepted but never splits the storage location."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "storage_paths.json"
            data = root / "data"
            backup = root / "backup"
            save_storage_paths(data, backup, config)
            self.assertEqual(load_storage_paths(root, config), (data.resolve(), data.resolve()))


if __name__ == "__main__":
    unittest.main()
