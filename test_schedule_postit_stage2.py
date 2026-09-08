import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.schedule_postit_model import SchedulePostitModel
from alert_notes.schedule_postit_settings import (
    COMPLETE_STRIKE,
    COMPLETE_TRASH,
    SchedulePostitPreferences,
    VIEW_DAY,
    VIEW_DUE,
    VIEW_PRIORITY,
    VIEW_WEEK,
    load_position,
    save_position,
)
from alert_notes.schedule_postit import SchedulePostitWindow
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


class SchedulePostitSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_defaults_and_roundtrip_preserve_empty_hotkey(self):
        defaults = SchedulePostitPreferences.load(self.store)
        self.assertEqual(defaults.view, VIEW_DAY)
        self.assertEqual(defaults.max_rows, 8)
        self.assertTrue(defaults.show_events)
        self.assertTrue(defaults.show_tasks)
        self.assertFalse(defaults.show_memo_deadlines)
        self.assertEqual(defaults.hotkey, "")

        wanted = SchedulePostitPreferences(
            view=VIEW_PRIORITY,
            max_rows=11,
            show_events=False,
            show_tasks=True,
            show_memo_deadlines=True,
            completion_mode=COMPLETE_TRASH,
            hotkey="Ctrl+Alt+8",
        )
        wanted.save(self.store)
        self.assertEqual(SchedulePostitPreferences.load(self.store), wanted)

    def test_invalid_values_are_bounded_and_empty_scope_falls_back(self):
        prefs = SchedulePostitPreferences(
            view="unknown", max_rows=99, show_events=False, show_tasks=False,
            show_memo_deadlines=False, completion_mode="erase",
        ).normalized()
        self.assertEqual(prefs.view, VIEW_DAY)
        self.assertEqual(prefs.max_rows, 15)
        self.assertTrue(prefs.show_events)
        self.assertTrue(prefs.show_tasks)
        self.assertEqual(prefs.completion_mode, COMPLETE_STRIKE)

    def test_position_roundtrip_uses_settings_not_schema_columns(self):
        self.assertIsNone(load_position(self.store))
        save_position(self.store, 120, 240)
        self.assertEqual(load_position(self.store), (120, 240))


class SchedulePostitModelTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.model = SchedulePostitModel(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _schedule(
        self, title: str, item_type: str, start: str, end: str,
        *, priority: int = 0, recurrence_rule=None,
    ) -> int:
        return self.store.schedules.save_item({
            "title": title,
            "item_type": item_type,
            "start_at": start,
            "end_at": end,
            "priority": priority,
            "recurrence_rule": recurrence_rule or {"frequency": "none"},
        })

    def test_day_scope_and_display_filters_are_independent(self):
        self._schedule("회의", "event", "202609081000", "202609081100")
        self._schedule("보고", "task", "202609081400", "202609081430")
        self._schedule("내일", "event", "202609091000", "202609091100")
        selected = date(2026, 9, 8)

        all_items = self.model.items(selected, SchedulePostitPreferences(), today=selected)
        self.assertEqual([item.title for item in all_items], ["회의", "보고"])
        tasks = self.model.items(
            selected,
            SchedulePostitPreferences(show_events=False, show_tasks=True),
            today=selected,
        )
        self.assertEqual([item.title for item in tasks], ["보고"])

    def test_day_boundary_includes_overlap_but_excludes_next_midnight(self):
        self._schedule("자정을 넘김", "event", "202609072350", "202609080020")
        self._schedule("날짜 끝", "task", "202609082359", "202609090000")
        self._schedule("다음 날 자정", "task", "202609090000", "202609090030")

        items = self.model.items(
            date(2026, 9, 8), SchedulePostitPreferences(), today=date(2026, 9, 8)
        )

        self.assertEqual([item.title for item in items], ["자정을 넘김", "날짜 끝"])

    def test_week_due_and_priority_views_have_stable_rules(self):
        self._schedule("월요일", "task", "202609070900", "202609070930", priority=1)
        second = self._schedule("화요일 둘째", "task", "202609081100", "202609081130", priority=3)
        first = self._schedule("화요일 첫째", "task", "202609081000", "202609081030", priority=3)
        self._schedule("다음 주", "task", "202609140900", "202609140930", priority=2)
        selected = date(2026, 9, 8)

        week = self.model.items(
            selected, SchedulePostitPreferences(view=VIEW_WEEK), today=selected
        )
        self.assertEqual([item.title for item in week], ["월요일", "화요일 첫째", "화요일 둘째"])
        priority = self.model.items(
            selected, SchedulePostitPreferences(view=VIEW_PRIORITY), today=selected
        )
        self.assertEqual([item.item_id for item in priority[:2]], [first, second])
        due = self.model.items(
            selected, SchedulePostitPreferences(view=VIEW_DUE), today=selected
        )
        self.assertEqual(due[-1].title, "다음 주")

    def test_memo_deadline_is_opt_in_and_past_deadline_stays_out(self):
        current = date(2026, 9, 8)
        today_note = self.store.create_note("예산 집행", "")
        past_note = self.store.create_note("지난 마감", "")
        self.store.set_deadline(today_note, "202609081800", "예산 집행 마감", False)
        self.store.set_deadline(past_note, "202609071800", "지난 마감", False)

        hidden = self.model.items(current, SchedulePostitPreferences(), today=current)
        self.assertEqual(hidden, [])
        shown = self.model.items(
            current,
            SchedulePostitPreferences(show_memo_deadlines=True),
            today=current,
        )
        self.assertEqual([(item.item_id, item.title) for item in shown], [(today_note, "예산 집행 마감")])

    def test_recurring_completion_marks_only_one_occurrence(self):
        item_id = self._schedule(
            "매일 점검", "task", "202609080900", "202609080930",
            recurrence_rule={"frequency": "daily", "count": 2},
        )
        prefs = SchedulePostitPreferences()
        first = self.model.items(date(2026, 9, 8), prefs, today=date(2026, 9, 8))[0]
        self.model.set_completed(first, True, COMPLETE_STRIKE)

        first_after = self.model.items(date(2026, 9, 8), prefs, today=date(2026, 9, 8))[0]
        second = self.model.items(date(2026, 9, 9), prefs, today=date(2026, 9, 8))[0]
        self.assertTrue(first_after.completed)
        self.assertFalse(second.completed)
        self.assertEqual(self.store.schedules.item(item_id)["status"], "pending")

        self.model.set_completed(first_after, False, COMPLETE_STRIKE)
        restored = self.model.items(date(2026, 9, 8), prefs, today=date(2026, 9, 8))[0]
        self.assertFalse(restored.completed)

    def test_trash_mode_uses_existing_soft_delete_for_one_time_item(self):
        item_id = self._schedule("한 번 할 일", "task", "202609081000", "202609081030")
        item = self.model.items(
            date(2026, 9, 8), SchedulePostitPreferences(), today=date(2026, 9, 8)
        )[0]
        self.model.set_completed(item, True, COMPLETE_TRASH)
        self.assertIsNone(self.store.schedules.item(item_id))
        self.assertEqual(int(self.store.schedules.trashed_items()[0]["id"]), item_id)


class SchedulePostitWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.window = SchedulePostitWindow(self.store)

    def tearDown(self):
        destroy_widget(self.window, self.app)
        self.store.close()
        self.temp.cleanup()

    def _today_item(self, title: str, hour: int) -> int:
        start = datetime.combine(date.today(), datetime.min.time()).replace(hour=hour)
        return self.store.schedules.save_item({
            "title": title,
            "item_type": "task",
            "start_at": start.strftime("%Y%m%d%H%M"),
            "end_at": (start + timedelta(minutes=30)).strftime("%Y%m%d%H%M"),
        })

    def test_real_buttons_move_dates_return_today_and_change_view(self):
        original = self.window.selected_date
        QTest.mouseClick(self.window.next_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.selected_date, original + timedelta(days=1))
        QTest.mouseClick(self.window.previous_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.selected_date, original)
        self.window.selected_date = original + timedelta(days=5)
        QTest.mouseClick(self.window.today_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.selected_date, date.today())
        QTest.mouseClick(self.window.view_buttons[VIEW_WEEK], Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.preferences.view, VIEW_WEEK)
        self.assertEqual(SchedulePostitPreferences.load(self.store).view, VIEW_WEEK)

    def test_repeated_date_moves_and_today_return_use_real_buttons(self):
        original = date.today()
        for _ in range(4):
            QTest.mouseClick(self.window.next_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.selected_date, original + timedelta(days=4))
        for _ in range(7):
            QTest.mouseClick(self.window.previous_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.selected_date, original - timedelta(days=3))
        QTest.mouseClick(self.window.today_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.selected_date, original)

    def test_real_checkbox_path_marks_and_unmarks_the_item(self):
        item_id = self._today_item("체크 경로", 10)
        self.window.refresh()
        self.window.show()
        self.app.processEvents()
        self.assertEqual(len(self.window.rows), 1)
        QTest.mouseClick(self.window.rows[0].check, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.store.schedules.item(item_id)["status"], "completed")
        self.assertTrue(self.window.rows[0].item.completed)
        QTest.mouseClick(self.window.rows[0].check, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.store.schedules.item(item_id)["status"], "pending")

    def test_zero_one_eight_and_nine_rows_use_actual_row_hints(self):
        self.window.show()
        self.app.processEvents()
        self.assertEqual(len(self.window.rows), 0)
        self.assertEqual(
            self.window.scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        for index in range(9):
            self._today_item(f"항목 {index + 1}", 8 + index)
            self.window.refresh()
            self.app.processEvents()
            if index == 0:
                self.assertGreater(self.window.rows[0].sizeHint().height(), 0)
            if index == 7:
                expected = sum(row.sizeHint().height() for row in self.window.rows[:8]) + 2
                self.assertEqual(self.window.scroll.height(), expected)
                self.assertEqual(
                    self.window.scroll.verticalScrollBarPolicy(),
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
                )
        self.assertEqual(len(self.window.rows), 9)
        self.assertEqual(
            self.window.scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )

    def test_empty_hotkey_is_not_a_widget_shortcut(self):
        self.assertEqual(SchedulePostitPreferences.load(self.store).hotkey, "")
        self.assertEqual(self.window.hide_shortcut.key().toString(), "Esc")

    def test_saved_preferences_and_position_restore_in_a_new_window(self):
        wanted = SchedulePostitPreferences(
            view=VIEW_DUE,
            max_rows=9,
            show_events=False,
            show_tasks=True,
            show_memo_deadlines=True,
            completion_mode=COMPLETE_STRIKE,
        )
        wanted.save(self.store)
        save_position(self.store, 96, 128)
        replacement = SchedulePostitWindow(self.store)
        try:
            replacement.show()
            self.app.processEvents()
            self.assertEqual(replacement.preferences, wanted)
            self.assertEqual((replacement.x(), replacement.y()), (96, 128))
            self.assertTrue(replacement.view_buttons[VIEW_DUE].isChecked())
        finally:
            destroy_widget(replacement, self.app)


if __name__ == "__main__":
    unittest.main()
