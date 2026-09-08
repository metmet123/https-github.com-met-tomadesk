import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLayout, QMessageBox, QVBoxLayout, QWidget

from alert_notes.calendar import CalendarPanel
from alert_notes.schedule_editor import ScheduleEditor
from alert_notes.schedule_recurrence import DATETIME_FMT
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


class ScheduleEditorStage3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "notes.db"
        self.store = NoteReminderStore(self.path, "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _item(self, title: str, item_type: str) -> int:
        return self.store.schedules.save_item({
            "title": title,
            "item_type": item_type,
            "start_at": "202609081000",
            "end_at": "202609081100",
        })

    def test_calendar_has_two_full_editor_entry_buttons(self):
        panel = CalendarPanel(self.store)
        panel.resize(1200, 760)
        panel.show()
        self.app.processEvents()

        QTest.mouseClick(panel.new_task_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(panel._drawer_open)
        self.assertEqual(panel.schedule_editor._editor_kind, "task")
        self.assertEqual(panel.schedule_editor.heading.text(), "새 할 일")
        self.assertFalse(panel.schedule_editor.form.isRowVisible(panel.schedule_editor.end_edit))

        panel._close_drawer()
        QTest.mouseClick(panel.new_schedule_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(panel.schedule_editor._editor_kind, "event")
        self.assertEqual(panel.schedule_editor.heading.text(), "새 일정")
        self.assertTrue(panel.schedule_editor.form.isRowVisible(panel.schedule_editor.end_edit))
        destroy_widget(panel, self.app)

    def test_both_entry_buttons_fit_before_opening_a_narrow_editor(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        panel = CalendarPanel(self.store)
        layout.addWidget(panel)
        host.setMinimumSize(0, 0)
        host.resize(680, 760)
        host.show()
        panel.update_responsive_layout(680)
        self.app.processEvents()

        for button in (panel.new_schedule_button, panel.new_task_button):
            left = button.mapTo(host, QPoint()).x()
            self.assertGreaterEqual(left, 0)
            self.assertLessEqual(left + button.width(), host.width())
            self.assertTrue(button.isVisible())
        destroy_widget(host, self.app)

    def test_task_form_has_one_deadline_and_persists_dday_choice(self):
        editor = ScheduleEditor(self.store)
        editor.new_item(
            datetime(2026, 9, 8, 18, 0),
            datetime(2026, 9, 8, 19, 0),
            item_type="task",
        )
        editor.title_edit.setText("보고서 제출")
        editor.count_as_dday_check.setChecked(True)
        self.assertFalse(editor.form.isRowVisible(editor.type_combo))
        self.assertFalse(editor.form.isRowVisible(editor.end_edit))
        self.assertEqual(editor.form.labelForField(editor.start_edit).text(), "마감")
        QTest.mouseClick(editor.save_button, Qt.MouseButton.LeftButton)

        saved = self.store.schedules.item(editor.item_id)
        self.assertEqual(saved["item_type"], "task")
        self.assertEqual(saved["start_at"], "202609081800")
        self.assertEqual(saved["end_at"], "202609081900")
        self.assertEqual(saved["count_as_dday"], 1)
        destroy_widget(editor, self.app)

    def test_saved_kind_reopens_the_matching_fixed_form(self):
        task_id = self._item("할 일", "task")
        event_id = self._item("일정", "event")
        editor = ScheduleEditor(self.store)

        editor.load_item(task_id)
        self.assertEqual(editor._editor_kind, "task")
        self.assertEqual(editor.heading.text(), "할 일 편집")
        self.assertFalse(editor.form.isRowVisible(editor.end_edit))
        editor.load_item(event_id)
        self.assertEqual(editor._editor_kind, "event")
        self.assertEqual(editor.heading.text(), "일정 편집")
        self.assertTrue(editor.form.isRowVisible(editor.end_edit))
        self.assertFalse(editor.count_as_dday_check.isVisible())
        destroy_widget(editor, self.app)

    def test_existing_task_from_quick_popover_keeps_its_kind_in_full_edit(self):
        task_id = self._item("빠른 할 일", "task")
        panel = CalendarPanel(self.store)
        panel.schedule_popover.open_item(task_id)
        self.assertEqual(panel.schedule_popover.values()["item_type"], "task")
        panel._open_full_editor(panel.schedule_popover.values())
        self.assertEqual(panel.schedule_editor._editor_kind, "task")
        self.assertFalse(panel.schedule_editor.form.isRowVisible(panel.schedule_editor.end_edit))
        destroy_widget(panel, self.app)

    def test_unknown_stored_kind_is_not_automatically_converted(self):
        item_id = self._item("종류 확인", "event")
        self.store.conn.execute(
            "UPDATE schedule_items SET item_type='unknown' WHERE id=?", (item_id,)
        )
        self.store.conn.commit()
        editor = ScheduleEditor(self.store)
        with patch.object(QMessageBox, "warning") as warning:
            editor.load_item(item_id)
        warning.assert_called_once()
        raw = self.store.conn.execute(
            "SELECT item_type FROM schedule_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        self.assertEqual(raw, "unknown")
        destroy_widget(editor, self.app)

    def test_additive_dday_column_upgrade_is_backed_up(self):
        self.store.close()
        connection = sqlite3.connect(self.path)
        connection.execute("ALTER TABLE schedule_items DROP COLUMN count_as_dday")
        connection.commit()
        connection.close()

        self.store = NoteReminderStore(self.path, "새 메모")
        self.assertIsNotNone(self.store.upgrade_backup_path)
        backup = sqlite3.connect(self.store.upgrade_backup_path)
        try:
            old_columns = {
                row[1] for row in backup.execute("PRAGMA table_info(schedule_items)")
            }
        finally:
            backup.close()
        new_columns = {
            row[1] for row in self.store.conn.execute("PRAGMA table_info(schedule_items)")
        }
        self.assertNotIn("count_as_dday", old_columns)
        self.assertIn("count_as_dday", new_columns)


if __name__ == "__main__":
    unittest.main()
