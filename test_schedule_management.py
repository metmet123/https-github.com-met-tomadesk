import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt, QTime
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLayout, QMessageBox, QVBoxLayout, QWidget

from alert_notes.calendar import CalendarPanel
from alert_notes.schedule_recurrence import DATETIME_FMT
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


class ScheduleStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_legacy_reminder_is_projected_without_removing_original(self):
        note_id = self.store.create_note("기존 알림", "보존")
        reminder_id = self.store.set_reminder(note_id, "202608101000", "보존")
        row = self.store.schedules.item(1)
        self.assertEqual(row["source_reminder_id"], reminder_id)
        self.assertEqual(row["note_id"], note_id)
        self.assertEqual(self.store.note(note_id)["reminder_id"], reminder_id)

    def test_existing_note_database_is_backed_up_before_schedule_upgrade(self):
        self.store.close()
        legacy_path = Path(self.temp.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        connection.execute(
            "CREATE TABLE notes (id INTEGER PRIMARY KEY, title TEXT NOT NULL, "
            "content TEXT NOT NULL, postit INTEGER NOT NULL DEFAULT 0, "
            "always_on_top INTEGER NOT NULL DEFAULT 1, color TEXT NOT NULL DEFAULT 'vanilla', "
            "opacity INTEGER NOT NULL DEFAULT 100, input_locked INTEGER NOT NULL DEFAULT 0, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.commit()
        connection.close()

        self.store = NoteReminderStore(legacy_path, "새 메모")

        self.assertIsNotNone(self.store.upgrade_backup_path)
        self.assertTrue(self.store.upgrade_backup_path.exists())
        backup = sqlite3.connect(self.store.upgrade_backup_path)
        try:
            schedule_table = backup.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedule_items'"
            ).fetchone()
        finally:
            backup.close()
        self.assertIsNone(schedule_table)

    def test_daily_and_weekday_recurrence_expansion(self):
        daily_id = self.store.schedules.save_item({
            "title": "매일 점검", "item_type": "task", "start_at": "202608030900",
            "end_at": "202608031000", "recurrence_rule": {"frequency": "daily", "count": 3},
        })
        weekly_id = self.store.schedules.save_item({
            "title": "월수 운동", "item_type": "event", "start_at": "202608030900",
            "end_at": "202608031000",
            "recurrence_rule": {"frequency": "weekly", "weekdays": [0, 2], "count": 4},
        })
        rows = self.store.schedules.items_for_range("202608030000", "202608120000")
        self.assertEqual(len([row for row in rows if row["id"] == daily_id]), 3)
        weekly = [row["display_start_at"] for row in rows if row["id"] == weekly_id]
        self.assertEqual(weekly, ["202608030900", "202608050900", "202608100900"])

    def test_multiple_notifications_complete_and_snooze(self):
        now = datetime.now().replace(second=0, microsecond=0)
        start = now + timedelta(minutes=10)
        item_id = self.store.schedules.save_item({
            "title": "알림 일정", "item_type": "event", "start_at": start.strftime(DATETIME_FMT),
            "end_at": (start + timedelta(hours=1)).strftime(DATETIME_FMT), "reminders": [10, 30],
        })
        due = self.store.schedules.due_notifications(now)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["item_id"], item_id)
        self.store.schedules.snooze_notification(due[0]["notification_id"], due[0]["occurrence_at"], 30)
        self.assertEqual(self.store.schedules.due_notifications(now), [])
        self.store.schedules.complete_notification(due[0]["notification_id"], due[0]["occurrence_at"])
        self.assertEqual(self.store.schedules.due_notifications(now + timedelta(hours=1)), [])

    def test_task_completion_and_changeable_hotkey(self):
        item_id = self.store.schedules.save_item({
            "title": "완료 업무", "item_type": "task", "start_at": "202608030900",
            "end_at": "202608031000", "hotkey": "Ctrl+Alt+7", "hotkey_action": "open",
        })
        self.assertEqual(self.store.schedules.hotkey_items()[0]["hotkey"], "Ctrl+Alt+7")
        self.store.schedules.set_completed(item_id, True)
        self.assertEqual(self.store.schedules.item(item_id)["status"], "completed")

    def test_recurring_occurrence_can_move_or_skip_without_changing_master(self):
        item_id = self.store.schedules.save_item({
            "title": "반복 회의", "item_type": "event", "start_at": "202608030900",
            "end_at": "202608031000", "recurrence_rule": {"frequency": "daily", "count": 3},
        })
        self.store.schedules.move_occurrence(item_id, "202608040900", "202608041300", "202608041400")
        self.store.schedules.skip_occurrence(item_id, "202608050900")
        rows = self.store.schedules.items_for_range("202608030000", "202608060000")
        self.assertEqual([row["display_start_at"] for row in rows], ["202608030900", "202608041300"])
        self.assertEqual(self.store.schedules.item(item_id)["start_at"], "202608030900")


class ScheduleUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_calendar_exposes_day_week_month_and_list(self):
        panel = CalendarPanel(self.store)
        self.assertEqual(set(panel.mode_buttons), {"day", "week", "month", "list"})
        panel._set_mode("month")
        self.assertEqual(panel.view_stack.currentWidget(), panel.month_page)
        panel._set_mode("list")
        self.assertEqual(panel.view_stack.currentWidget(), panel.list_widget)
        panel.close()

    def test_schedule_editor_saves_note_link_reminders_and_hotkey(self):
        note_id = self.store.create_note("연결 메모", "내용")
        panel = CalendarPanel(self.store)
        editor = panel.schedule_editor
        editor.new_item(datetime(2026, 8, 3, 9, 0))
        editor.title_edit.setText("연결 일정")
        editor.note_combo.setCurrentIndex(editor.note_combo.findData(note_id))
        editor.reminders_edit.setText("10, 30")
        editor.hotkey_enabled.setChecked(True)
        editor.hotkey_edit.setText("Ctrl+Alt+8")
        item_id = self.store.schedules.save_item(editor.values())
        item = self.store.schedules.item(item_id)
        self.assertEqual(item["note_id"], note_id)
        self.assertEqual(item["hotkey"], "Ctrl+Alt+8")
        self.assertEqual(self.store.schedules.notifications(item_id), [10, 30])
        panel.close()

    def test_new_schedule_opens_the_popover_not_the_drawer(self):
        panel = CalendarPanel(self.store)
        panel.show()
        self.assertFalse(panel.drawer_frame.isVisible())
        panel._new_schedule(datetime(2026, 8, 3, 9, 0))
        self.assertFalse(panel._drawer_open)
        self.assertTrue(panel.schedule_popover.isVisible())
        panel.schedule_popover.title_edit.setText("팝오버 저장 일정")
        self.assertTrue(panel.schedule_popover.save())
        self.assertFalse(panel.schedule_popover.isVisible())
        item = self.store.schedules.item(1)
        self.assertEqual(item["title"], "팝오버 저장 일정")
        self.assertEqual(item["start_at"], "202608030900")
        self.assertEqual(item["end_at"], "202608031000")
        panel.close()

    def test_popover_hands_its_draft_to_the_full_editor(self):
        panel = CalendarPanel(self.store)
        panel.show()
        panel._new_schedule(datetime(2026, 8, 3, 9, 0))
        panel.schedule_popover.title_edit.setText("넘겨줄 초안")
        panel.schedule_popover._pick_category("mint")
        panel.schedule_popover.full_edit_button.click()
        self.assertFalse(panel.schedule_popover.isVisible())
        self.assertTrue(panel._drawer_open)
        self.assertEqual(panel.schedule_editor.title_edit.text(), "넘겨줄 초안")
        self.assertEqual(panel.schedule_editor.category_combo.currentData(), "mint")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(panel.schedule_editor.request_close())
        self.assertFalse(panel._drawer_open)
        panel.close()

    def test_popover_edits_an_existing_item_in_place(self):
        item_id = self.store.schedules.save_item({
            "title": "기존 일정", "details": "", "item_type": "event",
            "start_at": "202608030900", "end_at": "202608031000",
            "all_day": False, "category": "sky", "priority": 0, "note_id": None,
            "status": "pending", "recurrence_rule": {"frequency": "none"},
            "reminders": [], "hotkey": "", "hotkey_action": "open",
        })
        panel = CalendarPanel(self.store)
        panel.show()
        panel._open_schedule(item_id)
        self.assertTrue(panel.schedule_popover.isVisible())
        self.assertEqual(panel.schedule_popover.title_edit.text(), "기존 일정")
        panel.schedule_popover.title_edit.setText("고친 일정")
        panel.schedule_popover.save()
        self.assertEqual(self.store.schedules.item(item_id)["title"], "고친 일정")
        panel.close()

    def test_drag_range_opens_the_popover_with_that_span(self):
        panel = CalendarPanel(self.store)
        panel.show()
        panel.anchor = datetime(2026, 8, 3).date()
        panel._set_mode("day")
        # 빈 자리를 09:00에서 12:00까지 끈 것과 같다.
        panel.canvas.range_selected(0, 9 * 60, 12 * 60)
        self.assertTrue(panel.schedule_popover.isVisible())
        values = panel.schedule_popover.values()
        self.assertEqual(values["start_at"], "202608030900")
        self.assertEqual(values["end_at"], "202608031200")
        panel.close()

    def test_popover_reads_natural_language_from_the_title(self):
        panel = CalendarPanel(self.store)
        panel.show()
        panel._new_schedule(datetime(2026, 8, 3, 9, 0))
        popover = panel.schedule_popover
        popover.title_edit.setText("내일 오후 3시 팀 회의 #개인 !30분전")
        values = popover.values()
        self.assertEqual(values["title"], "팀 회의")
        self.assertEqual(values["category"], "mint")
        self.assertEqual(values["reminders"], [30])
        tomorrow = datetime.now().date() + timedelta(days=1)
        self.assertEqual(values["start_at"], tomorrow.strftime("%Y%m%d") + "1500")
        self.assertFalse(popover.parse_label.isHidden())
        panel.close()

    def test_hand_edited_time_survives_further_typing(self):
        panel = CalendarPanel(self.store)
        panel.show()
        panel._new_schedule(datetime(2026, 8, 3, 9, 0))
        popover = panel.schedule_popover
        popover.title_edit.setText("내일 3시 회의")
        popover.start_time_edit.setTime(QTime(11, 0))
        popover.title_edit.setText("내일 3시 회의 준비")
        # 손으로 고친 시각은 파서가 다시 덮지 않는다.
        self.assertEqual(popover.values()["start_at"][-4:], "1100")
        panel.close()

    def test_clearing_the_date_returns_to_the_dragged_slot(self):
        panel = CalendarPanel(self.store)
        panel.show()
        panel._new_schedule(datetime(2026, 8, 3, 9, 0))
        popover = panel.schedule_popover
        popover.title_edit.setText("내일 오후 3시 회의")
        popover.title_edit.setText("회의")
        values = popover.values()
        self.assertEqual(values["start_at"], "202608030900")
        self.assertEqual(values["title"], "회의")
        panel.close()

    def test_natural_language_can_be_turned_off(self):
        self.store.set_setting("schedule_nlp_enabled", "false")
        panel = CalendarPanel(self.store)
        panel.show()
        panel._new_schedule(datetime(2026, 8, 3, 9, 0))
        popover = panel.schedule_popover
        popover.title_edit.setText("내일 오후 3시 팀 회의")
        values = popover.values()
        self.assertEqual(values["title"], "내일 오후 3시 팀 회의")
        self.assertEqual(values["start_at"], "202608030900")
        panel.close()

    def test_editing_an_item_does_not_reparse_its_title(self):
        item_id = self.store.schedules.save_item({
            "title": "9월 매출 정리", "details": "", "item_type": "event",
            "start_at": "202608030900", "end_at": "202608031000",
            "all_day": False, "category": "sky", "priority": 0, "note_id": None,
            "status": "pending", "recurrence_rule": {"frequency": "none"},
            "reminders": [], "hotkey": "", "hotkey_action": "open",
        })
        panel = CalendarPanel(self.store)
        panel.show()
        panel._open_schedule(item_id)
        values = panel.schedule_popover.values()
        self.assertEqual(values["title"], "9월 매출 정리")
        self.assertEqual(values["start_at"], "202608030900")
        panel.close()

    def test_popover_contents_stay_inside_its_frame(self):
        """날짜·시각 칸이 팝오버 폭을 넘겨 오른쪽이 잘리던 문제의 회귀 시험."""
        panel = CalendarPanel(self.store)
        panel.show()
        panel._new_schedule(datetime(2026, 8, 3, 9, 0))
        popover = panel.schedule_popover
        popover.time_chip.setChecked(True)
        for chip in (popover.reminder_chip, popover.repeat_chip, popover.memo_chip, popover.dday_chip):
            chip.setChecked(True)
        self.app.processEvents()
        self.assertLessEqual(popover.sizeHint().width(), popover.maximumWidth())
        inner = popover.width() - 32
        self.assertLessEqual(popover.time_row.minimumSizeHint().width(), inner)
        self.assertLessEqual(popover.body.layout().totalMinimumSize().width(), inner)
        panel.close()

    def test_popover_stays_inside_the_panel_at_every_width(self):
        """창을 좁혀도 팝오버가 오른쪽으로 잘리지 않는다."""
        panel = CalendarPanel(self.store)
        panel.resize(1200, 720)
        panel.show()
        panel.update_responsive_layout(1200)
        panel.anchor = datetime(2026, 8, 3).date()
        panel._set_mode("day")
        panel.canvas.range_selected(0, 9 * 60, 11 * 60)
        popover = panel.schedule_popover
        for chip in (popover.reminder_chip, popover.memo_chip):
            chip.setChecked(True)
        for width in (1200, 1000, 820, 640, 520, 420):
            panel.resize(width, 720)
            panel.update_responsive_layout(width)
            self.app.processEvents()
            self.assertGreaterEqual(popover.x(), 0, f"{width}px에서 왼쪽으로 넘침")
            self.assertLessEqual(
                popover.x() + popover.width(), panel.width(), f"{width}px에서 오른쪽으로 넘침"
            )
            self.assertLessEqual(popover.y() + popover.height(), panel.height() + 1)
        panel.close()

    def test_popover_stays_visible_when_the_calendar_is_wider_than_the_window(self):
        """캘린더는 최소 폭 때문에 창보다 넓어질 수 있다.

        그때 팝오버를 패널 폭 기준으로 세우면 잘려 나간 자리에 놓여 화면에서
        사라진다.  보이는 영역 안에 남아야 한다.
        """
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        # 탭 안에 든 것과 같은 상황: 캘린더의 최소 폭이 창 크기를 잡아 두지 않는다.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        panel = CalendarPanel(self.store)
        layout.addWidget(panel)
        host.setMinimumSize(0, 0)
        host.resize(1200, 700)
        host.show()
        panel.anchor = datetime(2026, 8, 3).date()
        panel._set_mode("day")
        panel.canvas.range_selected(0, 9 * 60, 11 * 60)
        popover = panel.schedule_popover
        for width in (1200, 900, 700, 560, 460):
            host.resize(width, 700)
            panel.update_responsive_layout(min(width, panel.width()))
            self.app.processEvents()
            visible = panel._visible_bounds()
            self.assertGreaterEqual(popover.x(), visible.left(), f"{width}px에서 왼쪽으로 넘침")
            self.assertLessEqual(
                popover.x() + popover.width(), visible.right() + 1, f"{width}px에서 오른쪽으로 넘침"
            )
        destroy_widget(host, self.app)

    def test_dragging_a_block_saves_the_new_time_and_ctrl_z_undoes_it(self):
        panel, (item_id,) = self._busy_day_panel(("옮길 일정", "202608030900", "202608031000"))
        block = panel.canvas.blocks()[0]
        origin = (block.start, block.end)
        block.start = datetime(2026, 8, 3, 11, 30)
        block.end = datetime(2026, 8, 3, 12, 30)
        panel.canvas.commit_move(block, origin)

        item = self.store.schedules.item(item_id)
        self.assertEqual(item["start_at"], "202608031130")
        self.assertEqual(item["end_at"], "202608031230")

        panel._undo_last_move()
        item = self.store.schedules.item(item_id)
        self.assertEqual(item["start_at"], "202608030900")
        self.assertEqual(item["end_at"], "202608031000")
        panel.close()

    def test_pulling_the_bottom_edge_saves_the_new_length(self):
        panel, (item_id,) = self._busy_day_panel(("늘일 일정", "202608030900", "202608030930"))
        block = panel.canvas.blocks()[0]
        origin = (block.start, block.end)
        block.end = datetime(2026, 8, 3, 10, 45)
        panel.canvas.commit_resize(block, origin)

        item = self.store.schedules.item(item_id)
        self.assertEqual(item["start_at"], "202608030900", "시작은 그대로여야 합니다")
        self.assertEqual(item["end_at"], "202608031045")
        panel.close()

    def test_deleting_from_the_popover_can_be_undone(self):
        panel, (item_id,) = self._busy_day_panel(("지울 일정", "202608030900", "202608031000"))
        panel._open_schedule(item_id)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            panel.schedule_popover._delete()
        self.assertIsNone(self.store.schedules.item(item_id))
        panel._undo_last_move()
        self.assertEqual(self.store.schedules.item(item_id)["title"], "지울 일정")
        panel.close()

    def test_mirror_item_still_opens_the_full_editor(self):
        note_id = self.store.create_note("알림 메모", "내용")
        self.store.set_reminder(note_id, "202608101000", "알림 메모")
        mirror = next(
            row for row in self.store.schedules.items_for_range("202608100000", "202608110000")
        )
        panel = CalendarPanel(self.store)
        panel.show()
        panel._open_schedule(int(mirror["id"]), str(mirror["occurrence_at"]))
        self.assertFalse(panel.schedule_popover.isVisible())
        self.assertTrue(panel._drawer_open)
        panel._close_drawer()
        panel.close()

    def test_month_grid_shows_three_items_and_more_count(self):
        for index in range(4):
            self.store.schedules.save_item({
                "title": f"월간 일정 {index + 1}", "details": "", "item_type": "event",
                "start_at": f"20260803{9 + index:02d}00", "end_at": f"20260803{10 + index:02d}00",
                "all_day": False, "category": "sky", "priority": 0, "note_id": None,
                "status": "pending", "recurrence_rule": {"frequency": "none"},
                "reminders": [], "hotkey": "", "hotkey_action": "open",
            })
        panel = CalendarPanel(self.store)
        panel.anchor = datetime(2026, 8, 3).date()
        panel._set_mode("month")
        texts = [panel.month_calendar.item(row, column).text() for row in range(6) for column in range(7)]
        target = next(text for text in texts if "월간 일정 1" in text)
        self.assertIn("월간 일정 3", target)
        self.assertIn("+1개 더보기", target)
        panel.close()

    def test_calendar_three_responsive_ranges(self):
        panel = CalendarPanel(self.store)
        panel.update_responsive_layout(1440)
        self.assertFalse(panel.navigation.isHidden())
        panel.update_responsive_layout(1100)
        self.assertFalse(panel.navigation.isVisible())
        panel._open_drawer(0)
        self.assertEqual(panel.root_layout.indexOf(panel.drawer_frame), -1)
        self.assertGreaterEqual(panel.drawer_frame.x(), panel.width() - 410)
        panel._close_drawer()
        panel.update_responsive_layout(800)
        panel.canvas.view.verticalScrollBar().setValue(4)
        scroll_before = panel.canvas.view.verticalScrollBar().value()
        panel._open_drawer(0)
        self.assertFalse(panel.calendar_body.isVisible())
        self.assertFalse(panel.drawer_frame.isHidden())
        panel._close_drawer()
        self.assertFalse(panel.calendar_body.isHidden())
        self.assertEqual(panel.canvas.view.verticalScrollBar().value(), scroll_before)
        self.assertFalse(panel.quick_memo_button.isHidden())
        panel.close()


    # ------------------------------------------------- 겹치는 시간대의 클릭 --
    def _busy_day_panel(self, *events):
        """주어진 일정들을 넣은 8월 3일 일간 화면."""
        ids = [
            self.store.schedules.save_item({
                "title": title, "start_at": start, "end_at": end,
                "category": "sky", "item_type": "event",
            })
            for title, start, end in events
        ]
        panel = CalendarPanel(self.store)
        panel.anchor = datetime(2026, 8, 3).date()
        panel.resize(1000, 720)
        panel.show()
        panel._set_mode("day")
        QTest.qWait(20)
        return panel, ids

    def test_new_schedule_in_a_busy_hour_does_not_overwrite_the_existing_one(self):
        """일정 옆 빈 자리를 끌면 일정1의 편집이 아니라 새 일정이 열린다."""
        panel, (first,) = self._busy_day_panel(("일정1", "202608031400", "202608031500"))
        panel.canvas.range_selected(0, 14 * 60 + 30, 15 * 60 + 30)

        popover = panel.schedule_popover
        self.assertIsNone(popover.item_id, "빈 자리를 눌렀는데 기존 일정의 편집이 열렸습니다")
        popover.title_edit.setText("일정2")
        popover.start_time_edit.setTime(QTime(14, 30))
        popover.end_time_edit.setTime(QTime(15, 30))
        self.assertTrue(popover.save())

        titles = sorted(row["title"] for row in self.store.schedules.items_for_range(
            "202608030000", "202608040000"))
        self.assertEqual(titles, ["일정1", "일정2"])
        self.assertEqual(self.store.schedules.item(first)["title"], "일정1")
        panel.close()

    def test_clicking_the_second_schedule_in_a_shared_hour_opens_that_one(self):
        """겹치는 두 일정은 폭을 나눠 나란히 서고, 각자 따로 열린다."""
        panel, (first, second) = self._busy_day_panel(
            ("일정1", "202608031400", "202608031500"),
            ("일정2", "202608031430", "202608031530"),
        )
        blocks = {block.item_id: block for block in panel.canvas.blocks()}
        self.assertEqual(set(blocks), {first, second})
        left, right = blocks[first].rect(), blocks[second].rect()
        # 같은 시간대인데 좌우로 나뉘어 서로 가리지 않는다.
        self.assertNotEqual(left.x(), right.x())
        self.assertLessEqual(left.right(), right.left() + 1)
        # 14:30에서 시작하는 일정은 14시 줄이 아니라 제자리에 놓인다.
        self.assertEqual(int(right.y()), 14 * 60 + 30)
        panel.canvas.block_clicked(blocks[second])
        self.assertEqual(panel.schedule_popover.item_id, second)
        panel.close()

    # ------------------------------------------------------- 팝오버 레이아웃 --
    def test_popover_grows_instead_of_overlapping_when_every_extra_opens(self):
        panel = CalendarPanel(self.store)
        panel.resize(1100, 800)
        panel.show()
        panel._new_schedule(datetime(2026, 8, 3, 9, 0))
        popover = panel.schedule_popover
        closed = popover.height()
        for chip in (popover.time_chip, popover.reminder_chip, popover.repeat_chip,
                     popover.memo_chip, popover.dday_chip):
            chip.setChecked(True)
        self.assertGreater(popover.height(), closed, "항목을 펼쳤는데 팝오버가 커지지 않았습니다")

        stacked = [popover.reminder_edit, popover.repeat_combo, popover.memo_edit, popover.dday_hint]
        for upper, lower in zip(stacked, stacked[1:]):
            self.assertLessEqual(
                upper.geometry().bottom(), lower.geometry().top(),
                f"{upper.accessibleName() or upper.objectName()} 가 아래 항목과 겹칩니다",
            )
        self.assertLessEqual(popover.save_button.geometry().bottom(), popover.height())
        self.assertGreaterEqual(popover.y(), 0)
        panel.close()

    # ------------------------------------------------------------ 현재 시각 --
    def test_day_view_centres_on_the_current_time_without_stealing_the_scroll(self):
        panel = CalendarPanel(self.store)
        panel.resize(1000, 720)
        panel.show()
        panel._set_mode("day")
        panel._today()
        QTest.qWait(30)

        canvas = panel.canvas
        bar = canvas.view.verticalScrollBar()
        now = datetime.now()
        centre = now.hour * 60 + now.minute
        expected = max(bar.minimum(), min(int(centre - canvas.view.viewport().height() / 2), bar.maximum()))
        self.assertEqual(bar.value(), expected)

        # 직접 스크롤한 뒤에는 화면을 빼앗지 않는다.
        canvas.mark_user_scroll()
        bar.setValue(bar.minimum())
        canvas.scroll_to_now()
        self.assertEqual(bar.value(), bar.minimum())
        # 탭이나 '오늘'을 다시 누르면 그때는 따라간다.
        canvas.scroll_to_now(force=True)
        self.assertEqual(bar.value(), expected)
        panel.close()


if __name__ == "__main__":
    unittest.main()
