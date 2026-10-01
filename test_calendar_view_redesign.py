"""Calendar redesign contracts; all data is synthetic and no user DB is opened."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

from alert_notes.calendar_canvas import CalendarCanvas
from alert_notes.calendar import CalendarPanel
from alert_notes.calendar_month_view import CalendarMonthView, _ActionLabel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def event(start="202609230900", end="202609231000", **values):
    return dict(id=1, occurrence_at=start, display_start_at=start, display_end_at=end,
                title="일정 제목", category="sky", status="pending", item_type="event",
                source_reminder_id=None, **values)


class CalendarRedesignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = CalendarCanvas()
        self.canvas.resize(1000, 700)
        self.canvas.show()
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.canvas, self.app)

    def render(self, items, start=date(2026, 9, 23), end=date(2026, 9, 24)):
        self.canvas.render_range(start, end, items)
        self.app.processEvents()

    def test_short_event_has_readable_height_without_changing_duration(self):
        self.render([event(end="202609230915")])
        block = self.canvas.blocks()[0]
        self.assertGreaterEqual(block.rect().height(), self.canvas.fontMetrics().height() + 4)
        self.assertEqual((block.end - block.start).total_seconds(), 900)
        self.assertIn("일정 제목", block.display_title())

    def test_point_keyboard_resize_is_noop(self):
        self.render([event(end="202609230901", time_mode="point")])
        block = self.canvas.blocks()[0]
        block.setSelected(True)
        changes = []
        self.canvas.scheduleResized.connect(lambda *args: changes.append(args))
        before = block.start, block.end
        self.assertTrue(self.canvas.handle_key(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)))
        self.assertEqual((block.start, block.end), before)
        self.assertEqual(changes, [])
        self.assertIn("종료 없음", block.display_title())

    def test_cross_midnight_has_two_segments_same_identity(self):
        self.render([event("202609232330", "202609240030")], end=date(2026, 9, 25))
        first, second = self.canvas.blocks()
        self.assertTrue(first.continues_after)
        self.assertTrue(second.continues_before)
        self.assertEqual(first.rect().height(), 30)
        self.assertEqual(second.rect().top(), 0)
        self.assertEqual(second.rect().height(), 30)
        self.assertEqual((first.item_id, first.occurrence_at), (second.item_id, second.occurrence_at))
        self.assertFalse(first._on_edge(first.rect().bottomLeft()))

    def test_previous_day_event_remains_visible(self):
        self.render([event("202609222330", "202609230100")])
        block, = self.canvas.blocks()
        self.assertTrue(block.continues_before)
        self.assertEqual(block.rect().height(), 60)
        self.assertEqual(block.start, datetime(2026, 9, 22, 23, 30))

    def test_midnight_end_does_not_add_empty_day(self):
        self.render([event("202609232300", "202609240000")], end=date(2026, 9, 25))
        self.assertEqual(len(self.canvas.blocks()), 1)

    def test_all_day_is_separate_and_clickable(self):
        self.render([event("202609220000", "202609250000", all_day=True)], end=date(2026, 9, 28))
        self.assertEqual(self.canvas.blocks(), [])
        self.assertTrue(self.canvas.all_day_area.isVisible())
        clicked = []
        self.canvas.scheduleClicked.connect(lambda *args: clicked.append(args))
        self.canvas._all_day_buttons[0].click()
        self.assertEqual(clicked, [(1, "202609220000")])
        self.render([])
        self.assertFalse(self.canvas.all_day_area.isVisible())

    def test_short_visual_blocks_do_not_overlap(self):
        self.render([event(end="202609230905"), event("202609230910", "202609230915")])
        a, b = self.canvas.blocks()
        self.assertFalse(a.rect().intersects(b.rect()))

    def test_many_collisions_stay_in_date_column(self):
        self.render([event() for _ in range(12)], end=date(2026, 9, 30))
        right = self.canvas.column_left(1)
        self.assertTrue(all(block.rect().right() <= right for block in self.canvas.blocks()))

    def test_cross_date_move_and_escape_restore(self):
        self.render([event()], end=date(2026, 9, 30))
        block = self.canvas.blocks()[0]
        original = block.start, block.end
        block.begin_press(545, False)
        block.drag_to(605, scene_x=self.canvas.column_left(1) + 10)
        self.assertEqual(block.start, datetime(2026, 9, 24, 10))
        self.assertEqual(block.end, datetime(2026, 9, 24, 11))
        self.canvas.view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertEqual((block.start, block.end), original)
        self.assertEqual(block.display_day, date(2026, 9, 23))

    def test_density_keeps_short_event_reading_height(self):
        self.render([event(end="202609230915")])
        self.canvas.set_compact(True)
        block = self.canvas.blocks()[0]
        self.assertGreaterEqual(block.rect().height() * .75, self.canvas.fontMetrics().height() + 3)
        self.assertEqual((block.end-block.start).total_seconds(), 900)


class CalendarPanelRedesignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.panel = CalendarPanel(self.store)
        self.panel.resize(1300, 800)
        self.panel.show()
        self.panel.anchor = date(2026, 9, 23)
        self.app.processEvents()

    def tearDown(self):
        self.panel.shutdown()
        destroy_widget(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def save(self, title="테스트", **values):
        return self.store.schedules.save_item(dict(title=title, start_at="202609230900", end_at="202609231000", **values))

    def test_month_week_count_and_individual_event_action(self):
        first = self.save("첫 일정")
        second = self.save("둘째 일정")
        self.panel._set_mode("month")
        self.app.processEvents()
        month = self.panel.month_calendar
        self.assertEqual(month.rowCount(), 5)
        seen = []
        month.scheduleActivated.connect(lambda *args: seen.append(args))
        chip = next(c for c in month.findChildren(_ActionLabel) if "둘째 일정" in c.text())
        QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
        self.assertEqual(seen[-1][0], second)
        self.assertNotEqual(first, second)
        month.setCurrentPage(2027, 2)
        self.assertEqual(month.rowCount(), 4)
        month.setCurrentPage(2026, 3)
        self.assertEqual(month.rowCount(), 6)

    def test_month_selection_opens_agenda_not_create(self):
        self.panel._set_mode("month")
        self.app.processEvents()
        month = self.panel.month_calendar
        cell = month.visualItemRect(month.item(3, 3))
        QTest.mouseClick(month.viewport(), Qt.MouseButton.LeftButton, pos=cell.center())
        self.assertTrue(self.panel.month_detail.isVisible())
        self.assertFalse(self.panel.schedule_popover.isVisible())
        self.panel.month_add_button.click()
        self.assertTrue(self.panel.schedule_popover.isVisible())
        self.assertEqual(self.panel.schedule_popover.current_range()[0].date(), date(2026, 9, 24))

    def test_filters_and_day_list(self):
        self.save("업무회의", category="sky")
        self.save("개인 약속", category="mint")
        self.panel._set_mode("day")
        self.assertTrue(self.panel.day_detail.isVisible())
        self.panel._select_category("mint")
        self.assertEqual([b.title for b in self.panel.canvas.blocks()], ["개인 약속"])
        self.panel.search_edit.setText("없음")
        self.panel.refresh()
        self.assertEqual(self.panel.canvas.blocks(), [])
        self.assertIn("조건", self.panel.day_agenda.item(0).text())

    def test_day_scroll_restored_after_view_switch(self):
        # Historical dates retain position; today's day view now follows the clock.
        self.panel.anchor = date(2020, 1, 1)
        self.panel._set_mode("day")
        self.panel.canvas.view.verticalScrollBar().setValue(450)
        self.panel._set_mode("month")
        self.panel._set_mode("day")
        self.assertEqual(self.panel.canvas.view.verticalScrollBar().value(), 450)

    def test_workweek_is_optional(self):
        self.panel._set_mode("week")
        self.assertEqual(self.panel.canvas.column_count, 7)
        self.panel._toggle_workweek(True)
        self.assertEqual(self.panel.canvas.column_count, 5)
        self.assertIn("주말", self.panel.view_settings.toolTip())
        self.panel._toggle_workweek(False)
        self.assertEqual(self.panel.canvas.column_count, 7)

    def test_moved_recurrence_enters_new_range_and_undo_preserves_prior_move(self):
        item_id = self.save(recurrence_rule={"frequency": "daily", "count": 2})
        self.store.schedules.move_occurrence(item_id, "202609230900", "202610011100", "202610011200")
        items = self.store.schedules.items_for_range("202610010000", "202610020000")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["occurrence_at"], "202609230900")
        self.panel._canvas_changed(item_id, "202609230900", datetime(2026,10,1,11), datetime(2026,10,1,12), datetime(2026,10,1,13), datetime(2026,10,1,14))
        self.panel._undo_last_move()
        restored = self.store.schedules.items_for_range("202610010000", "202610020000")
        self.assertEqual(restored[0]["display_start_at"], "202610011100")

    def test_moved_recurrence_alarm_uses_new_day(self):
        item_id = self.save(recurrence_rule={"frequency": "daily", "count": 2}, reminders=[5])
        self.store.schedules.move_occurrence(item_id, "202609230900", "202610011100", "202610011200")
        alarms = self.store.schedules.due_notifications(datetime(2026,10,1,10,55))
        self.assertEqual(len(alarms), 1)
        self.assertEqual(alarms[0]["occurrence_at"], "202609230900")

    def test_failed_move_restores_database_view(self):
        self.save()
        self.panel._set_mode("day")
        block = self.panel.canvas.blocks()[0]
        original = block.start, block.end
        block.begin_press(540, False)
        block.drag_to(600)
        with patch.object(self.store.schedules, "save_item", side_effect=RuntimeError("test failure")), patch("alert_notes.calendar.QMessageBox.warning") as warning:
            self.panel.canvas.commit_move(block, original)
        warning.assert_called_once()
        restored = self.panel.canvas.blocks()[0]
        self.assertEqual((restored.start, restored.end), original)

    def test_responsive_theme_matrix(self):
        from ui_theme import scaled_stylesheet
        from PyQt6.QtCore import QPoint
        self.save("주간회의")
        self.store.schedules.save_item({"title": "프로젝트 점검", "start_at": "202609220000", "end_at": "202609250000", "all_day": True, "category": "mint"})
        original_style = self.app.styleSheet()
        try:
            for scale in (1, 1.25, 1.5):
                self.app.setStyleSheet(scaled_stylesheet(scale))
                for width in (700, 1100, 1400):
                    self.panel.update_responsive_layout(width)
                    self.app.processEvents()
                    self.panel.resize(width, 800)
                    for mode in ("day", "week", "month"):
                        self.panel._set_mode(mode)
                        self.app.processEvents()
                        self.assertEqual(self.panel.width(), width, (scale, width, mode))
                        self.assertLessEqual(self.panel.period_label.fontMetrics().horizontalAdvance(self.panel.period_label.text()), self.panel.period_label.width(), (scale, width, mode, "period label"))
                        for button in (self.panel.new_schedule_button, self.panel.header_overflow, self.panel.view_settings, self.panel.filter_toggle):
                            pos = button.mapTo(self.panel, QPoint())
                            self.assertTrue(button.isVisible())
                            self.assertLessEqual(pos.x() + button.width(), self.panel.width(), (scale, width, mode, button.text()))
                        if os.environ.get("CALENDAR_CAPTURE_DIR"):
                            target = Path(os.environ["CALENDAR_CAPTURE_DIR"])
                            target.mkdir(parents=True, exist_ok=True)
                            self.panel.canvas.scroll_to_hour(8)
                            self.app.processEvents()
                            self.panel.grab().save(str(target / f"{mode}-{width}-{scale}.png"))
        finally:
            self.app.setStyleSheet(original_style)


if __name__ == "__main__":
    unittest.main()
