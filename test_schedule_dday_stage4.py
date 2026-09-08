import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.calendar import CalendarPanel
from alert_notes.schedule_day_context import same_day_context
from alert_notes.schedule_editor import ScheduleEditor
from alert_notes.schedule_recurrence import DATETIME_FMT
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.today_summary import TodaySummaryPanel
from qt_test_support import destroy_widget


def key(moment: datetime) -> str:
    return moment.strftime(DATETIME_FMT)


class ScheduleDdayStage4Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.today = date.today()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _deadline(self, title: str, day: date, hour: int = 18) -> int:
        note_id = self.store.create_note(title, "")
        target = datetime.combine(day, time(hour=hour))
        self.store.set_deadline(note_id, key(target), title, False)
        return note_id

    def _schedule(
        self,
        title: str,
        item_type: str,
        hour: int,
        *,
        dday: bool = False,
    ) -> int:
        start = datetime.combine(self.today, time(hour=hour))
        return self.store.schedules.save_item({
            "title": title,
            "item_type": item_type,
            "start_at": key(start),
            "end_at": key(start + timedelta(hours=1)),
            "count_as_dday": dday,
        })

    def test_past_deadlines_are_a_collapsible_top_group_and_bulk_complete(self):
        first = self._deadline("지난 마감 1", self.today - timedelta(days=2), 16)
        second = self._deadline("지난 마감 2", self.today - timedelta(days=1), 17)
        self._deadline("오늘 마감", self.today, 18)
        panel = TodaySummaryPanel(self.store)
        panel.show()
        self.app.processEvents()

        self.assertTrue(panel.past_deadline_header.isVisible())
        self.assertFalse(panel.past_deadline_list.isVisible())
        self.assertIn("2건", panel.past_deadline_toggle.text())
        self.assertLess(
            panel.past_deadline_header.geometry().top(),
            panel.deadline_list.geometry().top(),
        )
        QTest.mouseClick(panel.past_deadline_toggle, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(panel.past_deadline_list.isVisible())
        self.assertIn((self.today - timedelta(days=2)).strftime("%m/%d 16:00"), panel.past_deadline_list.item(0).text())
        self.assertFalse(self.store.note(first)["d_day_done_at"])

        QTest.mouseClick(panel.complete_past_deadlines_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(self.store.note(first)["d_day_done_at"])
        self.assertTrue(self.store.note(second)["d_day_done_at"])
        self.assertIsNotNone(self.store.note(first))
        self.assertFalse(panel.past_deadline_header.isVisible())
        destroy_widget(panel, self.app)

    def test_today_deadline_shows_target_time_on_the_same_row(self):
        self._deadline("예산 마감", self.today, 18)
        panel = TodaySummaryPanel(self.store)
        text = panel.deadline_list.item(0).text()
        self.assertIn("예산 마감", text)
        self.assertIn("오늘 18:00", text)
        destroy_widget(panel, self.app)

    def test_calendar_dday_only_filter_is_independent_and_persistent(self):
        self._schedule("일반 일정", "event", 9)
        self._schedule("일반 할 일", "task", 10)
        dday_task = self._schedule("D-Day 할 일", "task", 11, dday=True)
        deadline_id = self._deadline("메모 D-Day", self.today, 12)
        panel = CalendarPanel(self.store)
        panel.show()
        panel.anchor = self.today
        panel._set_mode("day")

        QTest.mouseClick(panel.dday_only_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        filtered = panel._filtered_schedule_items(
            self.today, self.today + timedelta(days=1)
        )
        self.assertEqual([int(item["id"]) for item in filtered], [dday_task])
        self.assertTrue(panel.calendar_deadline_strip.isVisible())
        self.assertIn("메모 D-Day", panel.calendar_deadline_strip.text())

        panel._set_mode("list")
        texts = [panel.list_widget.item(index).text() for index in range(panel.list_widget.count())]
        self.assertTrue(any("D-Day 할 일" in text for text in texts))
        deadline_row = next(
            panel.list_widget.item(index)
            for index in range(panel.list_widget.count())
            if "메모 D-Day" in panel.list_widget.item(index).text()
        )
        opened: list[int] = []
        panel.note_open_requested.connect(opened.append)
        panel._open_list_item(deadline_row)
        self.assertEqual(opened, [deadline_id])
        self.assertFalse(panel.calendar_filter_checks["events"].isChecked())
        self.assertFalse(panel.calendar_filter_checks["tasks"].isChecked())
        self.assertTrue(panel.calendar_filter_checks["dday"].isChecked())
        destroy_widget(panel, self.app)

        restored = CalendarPanel(self.store)
        self.assertFalse(restored.calendar_filter_checks["events"].isChecked())
        self.assertFalse(restored.calendar_filter_checks["tasks"].isChecked())
        self.assertTrue(restored.calendar_filter_checks["dday"].isChecked())
        destroy_widget(restored, self.app)

    def test_same_day_context_marks_only_real_overlaps(self):
        first = self._schedule("겹치는 일정", "event", 10)
        self._schedule("나중 일정", "event", 14)
        start = datetime.combine(self.today, time(hour=10, minute=30))
        context = same_day_context(
            self.store, start, start + timedelta(hours=1), current_id=None
        )
        self.assertEqual([item.overlaps for item in context], [True, False])
        self.assertEqual(context[0].item_id, first)

        editor = ScheduleEditor(self.store)
        editor.new_item(start, start + timedelta(hours=1), item_type="event")
        texts = [
            editor.day_context_list.item(index).text()
            for index in range(editor.day_context_list.count())
        ]
        self.assertTrue(texts[0].startswith("겹침 ·"))
        self.assertFalse(texts[1].startswith("겹침 ·"))
        destroy_widget(editor, self.app)

    def test_today_summary_keeps_three_representatives_not_a_second_long_list(self):
        for hour in range(8, 13):
            self._schedule(f"일정 {hour}", "event", hour)
        panel = TodaySummaryPanel(self.store)
        texts = [
            panel.schedule_list.item(index).text()
            for index in range(panel.schedule_list.count())
        ]
        self.assertEqual(len(texts), 4)
        self.assertIn("일정 포스트잇에서 체크 가능", texts[-1])
        destroy_widget(panel, self.app)


if __name__ == "__main__":
    unittest.main()
