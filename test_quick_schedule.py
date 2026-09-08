"""빠른 일정 창(Ctrl+Alt+A) 테스트."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from alert_notes.quick_schedule import QuickScheduleDialog
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def press(widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers))


class QuickScheduleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.dialog = QuickScheduleDialog(self.store)
        self.dialog.prepare()

    def tearDown(self):
        destroy_widget(self.dialog, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_default_start_is_the_next_half_hour(self):
        self.assertEqual(
            self.dialog.default_start(datetime(2026, 9, 2, 13, 40)), datetime(2026, 9, 2, 14, 0)
        )
        self.assertEqual(
            self.dialog.default_start(datetime(2026, 9, 2, 13, 10)), datetime(2026, 9, 2, 13, 30)
        )

    def test_one_line_becomes_a_schedule(self):
        self.dialog.input_edit.setText("내일 오후 3시 팀 회의 #업무 !30분전")
        item_id = self.dialog.save()
        item = self.store.schedules.item(item_id)
        tomorrow = datetime.now().date() + timedelta(days=1)
        self.assertEqual(item["title"], "팀 회의")
        self.assertEqual(item["category"], "sky")
        self.assertEqual(item["start_at"], tomorrow.strftime("%Y%m%d") + "1500")
        self.assertEqual(self.store.schedules.notifications(item_id), [30])

    def test_preview_shows_what_was_read(self):
        self.dialog.input_edit.setText("내일 오후 3시 팀 회의 #개인")
        self.assertEqual(self.dialog.title_label.text(), "팀 회의")
        self.assertIn("15:00", self.dialog.fields_label.text())
        self.assertIn("개인", self.dialog.fields_label.text())

    def test_conflict_line_reports_an_overlap(self):
        start = self.dialog.default_start() + timedelta(days=1)
        start = start.replace(hour=15, minute=0)
        self.store.schedules.save_item({
            "title": "선약", "details": "", "item_type": "event",
            "start_at": start.strftime("%Y%m%d%H%M"),
            "end_at": (start + timedelta(hours=1)).strftime("%Y%m%d%H%M"),
            "all_day": False, "category": "sky", "priority": 0, "note_id": None,
            "status": "pending", "recurrence_rule": {"frequency": "none"},
            "reminders": [], "hotkey": "", "hotkey_action": "open",
        })
        self.dialog.input_edit.setText("내일 오후 3시 팀 회의")
        self.assertIn("선약", self.dialog.conflict_label.text())
        self.assertEqual(self.dialog.conflict_label.property("conflict"), "true")

    def test_conflict_line_says_the_slot_is_free(self):
        self.dialog.input_edit.setText("내일 오후 3시 팀 회의")
        self.assertIn("없음", self.dialog.conflict_label.text())
        self.assertEqual(self.dialog.conflict_label.property("conflict"), "false")

    def test_ctrl_d_turns_the_line_into_a_deadline(self):
        saved = []
        self.dialog.note_saved.connect(saved.append)
        self.dialog.input_edit.setText("다음주 금요일 제안서 마감")
        press(self.dialog, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(saved), 1)
        note = self.store.note(saved[0])
        self.assertEqual(note["title"], "제안서 마감")
        self.assertTrue(note["d_day_at"])
        # 일정으로는 저장하지 않는다.
        self.assertIsNone(self.store.schedules.item(1))

    def test_ctrl_m_turns_the_line_into_a_memo(self):
        saved = []
        self.dialog.note_saved.connect(saved.append)
        self.dialog.input_edit.setText("사무실 정리")
        press(self.dialog, Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.store.note(saved[0])["title"], "사무실 정리")

    def test_tab_saves_and_asks_for_the_full_view(self):
        opened = []
        self.dialog.detail_requested.connect(opened.append)
        self.dialog.input_edit.setText("내일 10시 점검")
        press(self.dialog, Qt.Key.Key_Tab)
        self.assertEqual(len(opened), 1)
        self.assertEqual(self.store.schedules.item(opened[0])["title"], "점검")

    def test_empty_line_saves_nothing(self):
        self.dialog.input_edit.setText("   ")
        self.assertIsNone(self.dialog.save())
        self.assertIsNone(self.store.schedules.item(1))

    def test_plain_title_still_saves_at_the_default_slot(self):
        self.dialog.input_edit.setText("9월 매출 정리")
        item_id = self.dialog.save()
        item = self.store.schedules.item(item_id)
        self.assertEqual(item["title"], "9월 매출 정리")
        self.assertEqual(item["start_at"], self.dialog.default_start().strftime("%Y%m%d%H%M"))


if __name__ == "__main__":
    unittest.main()
