import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QTextEdit

from alert_notes.database_bundle import export_database_bundle, import_database_bundle
from alert_notes.recurrence import (
    RULE_DAILY, RULE_MONTHLY, RULE_WEEKDAYS, RULE_WEEKLY,
    RecurrenceRule, is_allowed, next_occurrence,
)
from alert_notes.rich_text import editor_content, load_editor_content, plain_text_from_content
from alert_notes.schedule_store import EXCEPTION_COLUMNS, ITEM_COLUMNS, NOTIFICATION_COLUMNS, NOTIFICATION_LOG_COLUMNS
from alert_notes.sqlite_store import (
    DATETIME_FMT, HISTORY_COLUMNS, NOTE_COLUMNS, REMINDER_COLUMNS, SERIES_COLUMNS, SETTING_COLUMNS,
    NoteReminderStore,
)
from alert_notes.panel import AlertNotesPanel
from alert_notes.service import AlertService
from qt_test_support import close_alert_panel


class ReminderPhaseOneStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_postit_note_accepts_multiple_reminders(self):
        note_id = self.store.create_note("포스트잇", "내용")
        self.store.update_note(note_id, postit=True)
        first = self.store.add_reminder(note_id, "209901010900", "첫 알림")
        second = self.store.add_reminder(note_id, "209901011000", "둘째 알림")
        self.assertNotEqual(first, second)
        self.assertEqual([row["id"] for row in self.store.pending_reminders_for_note(note_id)], [first, second])
        self.assertEqual(len(self.store.schedules.items_for_range("209901010000", "209901020000")), 2)

    def test_recurring_completion_creates_next_and_history(self):
        note_id = self.store.create_note("반복", "점검")
        first_due = (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)
        reminder_id = self.store.add_recurring_reminder(
            note_id, first_due.strftime(DATETIME_FMT), "점검", RecurrenceRule(RULE_DAILY),
        )
        self.store.complete_reminder(reminder_id)
        pending = self.store.pending_reminders_for_note(note_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["due_at"], (first_due + timedelta(days=1)).strftime(DATETIME_FMT))
        self.assertEqual(self.store.history()[0]["action"], "completed")

    def test_snooze_and_skip_are_recorded(self):
        note_id = self.store.create_note("처리", "기록")
        first = self.store.add_reminder(note_id, "209901010900", "미루기")
        second = self.store.add_reminder(note_id, "209901011000", "건너뛰기")
        self.store.snooze_reminder(first, 15)
        self.store.skip_reminder(second)
        self.assertEqual({row["action"] for row in self.store.history()}, {"snoozed", "skipped"})
        self.assertEqual(self.store.reminder(second)["status"], "skipped")

    def test_current_only_edit_preserves_series_anchor(self):
        note_id = self.store.create_note("반복 편집", "내용")
        due = (datetime.now() + timedelta(days=2)).replace(second=0, microsecond=0)
        reminder_id = self.store.add_recurring_reminder(
            note_id, due.strftime(DATETIME_FMT), "내용", RecurrenceRule(RULE_DAILY),
        )
        moved = due + timedelta(hours=3)
        self.store.update_reminder(reminder_id, moved.strftime(DATETIME_FMT), "이번만")
        self.store.complete_reminder(reminder_id)
        next_row = self.store.pending_reminders_for_note(note_id)[0]
        self.assertEqual(next_row["due_at"], (due + timedelta(days=1)).strftime(DATETIME_FMT))

    def test_deleting_recurring_occurrence_keeps_series_and_deleting_note_cleans_it(self):
        note_id = self.store.create_note("반복 삭제", "내용")
        due = (datetime.now() + timedelta(days=2)).replace(second=0, microsecond=0)
        reminder_id = self.store.add_recurring_reminder(
            note_id, due.strftime(DATETIME_FMT), "내용", RecurrenceRule(RULE_DAILY),
        )
        self.store.delete_reminder(reminder_id)
        pending = self.store.pending_reminders_for_note(note_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["due_at"], (due + timedelta(days=1)).strftime(DATETIME_FMT))
        self.store.delete_note(note_id)
        self.assertIsNone(self.store.note(note_id))
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM reminder_series").fetchone()[0], 1)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0], 1)
        self.store.restore_note(note_id)
        self.assertIsNotNone(self.store.note(note_id))

    def test_old_unique_schema_is_backed_up_and_migrated(self):
        self.store.close()
        path = Path(self.temp.name) / "legacy.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
                postit INTEGER NOT NULL DEFAULT 0, always_on_top INTEGER NOT NULL DEFAULT 1,
                color TEXT NOT NULL DEFAULT 'vanilla', opacity INTEGER NOT NULL DEFAULT 100,
                input_locked INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL UNIQUE, due_at TEXT NOT NULL,
                memo TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO notes VALUES(7,'보존','내용',1,1,'mint',90,0,'202601010900','202601010900');
            INSERT INTO reminders VALUES(11,7,'209901010900','기존','pending','202601010900');
            """
        )
        conn.commit()
        conn.close()
        self.store = NoteReminderStore(path, "새 메모")
        self.assertIsNotNone(self.store.upgrade_backup_path)
        self.assertTrue(self.store.upgrade_backup_path.exists())
        self.assertEqual(self.store.reminder(11)["memo"], "기존")
        self.store.add_reminder(7, "209901011000", "추가")
        self.assertEqual(len(self.store.pending_reminders_for_note(7)), 2)

    def test_full_bundle_roundtrip_preserves_series_history_and_calendar_links(self):
        note_id = self.store.create_note("백업", "반복")
        due = (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)
        reminder_id = self.store.add_recurring_reminder(
            note_id, due.strftime(DATETIME_FMT), "반복", RecurrenceRule(RULE_DAILY),
        )
        self.store.complete_reminder(reminder_id)
        bundle = Path(self.temp.name) / "full.json"
        tables = (
            "notes", "reminder_series", "reminders", "reminder_history", "settings",
            "schedule_items", "schedule_notifications", "schedule_notification_log",
            "schedule_occurrence_exceptions",
        )
        export_database_bundle({"alert_notes": (self.store.conn, tables)}, bundle)
        restored_path = Path(self.temp.name) / "restored.db"
        restored = NoteReminderStore(restored_path, "새 메모")
        try:
            columns = {
                "notes": list(NOTE_COLUMNS), "reminder_series": list(SERIES_COLUMNS),
                "reminders": list(REMINDER_COLUMNS), "reminder_history": list(HISTORY_COLUMNS),
                "settings": list(SETTING_COLUMNS), "schedule_items": list(ITEM_COLUMNS),
                "schedule_notifications": list(NOTIFICATION_COLUMNS),
                "schedule_notification_log": list(NOTIFICATION_LOG_COLUMNS),
                "schedule_occurrence_exceptions": list(EXCEPTION_COLUMNS),
            }
            import_database_bundle({"alert_notes": (restored.conn, columns)}, bundle)
            self.assertEqual(len(restored.history()), 1)
            self.assertEqual(len(restored.pending_reminders_for_note(note_id)), 1)
            self.assertEqual(restored.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            restored.close()


class RichTextCompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_plain_text_loads_and_rich_text_roundtrips(self):
        editor = QTextEdit()
        load_editor_content(editor, "기존\n메모")
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = cursor.charFormat()
        fmt.setFontUnderline(True)
        cursor.mergeCharFormat(fmt)
        stored = editor_content(editor)
        self.assertTrue(stored.lstrip().lower().startswith("<!doctype html"))
        self.assertEqual(plain_text_from_content(stored), "기존\n메모")
        editor.close()


class RecurrenceRuleTest(unittest.TestCase):
    def test_all_rule_types_and_end_conditions(self):
        friday = datetime(2026, 8, 7, 10, 0)
        self.assertEqual(next_occurrence(friday, RecurrenceRule(RULE_DAILY)), datetime(2026, 8, 8, 10, 0))
        self.assertEqual(next_occurrence(friday, RecurrenceRule(RULE_WEEKDAYS)), datetime(2026, 8, 10, 10, 0))
        self.assertEqual(
            next_occurrence(friday, RecurrenceRule(RULE_WEEKLY, weekdays=(0, 2))),
            datetime(2026, 8, 10, 10, 0),
        )
        self.assertEqual(
            next_occurrence(datetime(2027, 1, 31, 9, 0), RecurrenceRule(RULE_MONTHLY, month_day=31)),
            datetime(2027, 2, 28, 9, 0),
        )
        self.assertFalse(is_allowed(datetime(2026, 8, 9), RecurrenceRule(RULE_DAILY, end_type="date", end_date="20260808"), 2))
        self.assertFalse(is_allowed(datetime(2026, 8, 8), RecurrenceRule(RULE_DAILY, end_type="count", max_occurrences=1), 2))


class ReminderPhaseOneUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("UI 메모", "본문 유지")
        self.panel = AlertNotesPanel(self.store)
        self.panel.current_id = self.note_id
        self.panel.refresh()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_editor_saves_rich_text_without_clearing_body(self):
        editor = self.panel.editor
        editor.content_edit.selectAll()
        editor.format_toolbar.style_buttons["bold"].click()
        self.panel.save_note(editor.values())
        stored = str(self.store.note(self.note_id)["content"])
        self.assertEqual(plain_text_from_content(stored), "본문 유지")
        self.assertIn("font-weight", stored)
        self.assertEqual(editor.content_edit.toPlainText(), "본문 유지")

    def test_history_tab_lists_pending_and_completed(self):
        reminder_id = self.store.add_reminder(self.note_id, "209901010900", "예정")
        self.panel.reminder_history.refresh()
        self.assertEqual(self.panel.reminder_history.pending_table.rowCount(), 1)
        self.store.complete_reminder(reminder_id)
        self.panel.reminder_history.refresh()
        self.assertEqual(self.panel.reminder_history.pending_table.rowCount(), 0)
        self.assertEqual(self.panel.reminder_history.history_table.rowCount(), 1)
        self.assertEqual(self.panel.reminder_history.history_table.item(0, 6).text(), "완료")

    def test_editor_auto_saves_and_shortcut_labels_follow_setting(self):
        self.store.set_setting("reminder_time_hotkey_modifier", "Shift")
        self.panel.editor.reload_shortcuts()
        self.assertIn("Shift+Q", self.panel.editor.quick_buttons[5].text())
        self.panel.editor.content_edit.setPlainText("자동 저장 확인")
        QTest.qWait(500)
        self.app.processEvents()
        self.assertEqual(plain_text_from_content(self.store.note(self.note_id)["content"]), "자동 저장 확인")
        self.assertTrue(self.panel.editor.saved_status.text().endswith("자동 저장됨"))
        self.panel.editor.postit_shortcut.activated.emit()
        QTest.qWait(500)
        self.app.processEvents()
        self.assertTrue(self.store.note(self.note_id)["postit"])

    def test_editor_coalesces_format_sync_and_cancels_pending_work_on_shutdown(self):
        editor = self.panel.editor
        editor.content_edit.setPlainText("안정성 확인 " * 800)
        for _ in range(40):
            editor.content_edit.insertPlainText(" 입력")
        QTest.qWait(520)
        self.app.processEvents()
        self.assertFalse(editor.format_toolbar.sync_timer.isActive())
        self.assertEqual(plain_text_from_content(self.store.note(self.note_id)["content"]), editor.content_edit.toPlainText())

        editor.content_edit.insertPlainText(" 종료 전 변경")
        self.assertTrue(editor.save_timer.isActive())
        self.panel.shutdown()
        self.assertFalse(editor.save_timer.isActive())
        self.assertFalse(editor.format_toolbar.sync_timer.isActive())
        self.app.processEvents()

    def test_datetime_result_summary_is_preserved(self):
        future = datetime.now() + timedelta(minutes=10)
        self.panel.editor.datetime_input.set_datetime(future)
        summary = self.panel.editor.datetime_input.summary.text()
        self.assertIn(f"오늘 {future:%H:%M} · ", summary)
        # S6: 저장 전에는 예약된 것처럼 보이면 안 된다.
        self.assertTrue(summary.startswith("예약하면 "), summary)
        self.assertNotIn("예약됨", summary)

    def test_editor_loads_recurring_reminder_for_edit(self):
        reminder_id = self.store.add_recurring_reminder(
            self.note_id, "209901010900", "반복", RecurrenceRule(RULE_DAILY),
        )
        self.panel.show_reminder(reminder_id)
        self.assertEqual(self.panel.tabs.currentIndex(), 0)
        self.assertEqual(self.panel.editor.editing_reminder_id, reminder_id)
        self.assertEqual(self.panel.editor.recurrence.rule().rule_type, RULE_DAILY)

    def test_alert_dialog_skip_is_saved_to_history(self):
        reminder_id = self.store.add_reminder(self.note_id, "200001010900", "건너뛰기")
        service = AlertService(self.store, lambda _note_id: None, parent=self.panel)
        service.check_now()
        self.assertEqual(service.active_dialog.reminder_id, reminder_id)
        service.active_dialog._skip()
        self.app.processEvents()
        self.assertEqual(self.store.history()[0]["action"], "skipped")
        service.stop()


if __name__ == "__main__":
    unittest.main()
