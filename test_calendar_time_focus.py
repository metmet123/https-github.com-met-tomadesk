"""Working-hours coordinates and quick draft contracts, synthetic data only."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.calendar_canvas import CalendarCanvas
from alert_notes.timeline_axis import TimelineAxis
from alert_notes.schedule_popover import StandaloneSchedulePopover
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget
from test_calendar_view_redesign import event


class TimeAxisTest(unittest.TestCase):
    def test_round_trip_every_minute_and_boundaries(self):
        for compressed in (False, True):
            axis = TimelineAxis(compressed)
            for minute in range(1441):
                self.assertAlmostEqual(axis.minute(axis.y(minute)), minute)
        axis = TimelineAxis(True)
        self.assertEqual([axis.y(x) for x in (0, 540, 1080, 1440)], [0, 180, 720, 840])
        self.assertEqual(axis.y(600) - axis.y(540), 60)
        self.assertEqual(axis.y(540) - axis.y(480), 20)


class TimeFocusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = CalendarCanvas()
        self.canvas.follow_now = True
        self.canvas.set_working_hours(True)
        self.canvas.resize(700, 600)
        self.canvas.show()
        self.canvas.render_range(date.today(), date.today() + timedelta(days=1), [])
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.canvas, self.app)

    def test_boundary_move_resize_and_duration_preserved(self):
        c = self.canvas
        c.render_range(date(2026, 9, 23), date(2026, 9, 24), [event("202609230830", "202609230930")])
        b, = c.blocks()
        self.assertEqual(b.rect().top(), 170)
        self.assertEqual(b.rect().height(), 40)
        b.begin_press(c.minute_to_y(520), False)
        b.drag_to(c.minute_to_y(610), 1)
        self.assertEqual(b.start, datetime(2026, 9, 23, 10))
        self.assertEqual(b.end - b.start, timedelta(hours=1))
        b.begin_press(b.rect().bottom(), True)
        b.drag_to(c.minute_to_y(1110), 1)
        self.assertEqual(b.end, datetime(2026, 9, 23, 18, 30))

    def test_midnight_centre_has_scroll_room(self):
        c = self.canvas
        for hour, minute in ((0, 0), (9, 0), (18, 0), (23, 59)):
            now = datetime.combine(date.today(), datetime.min.time()).replace(hour=hour, minute=minute)
            with patch("alert_notes.calendar_canvas.datetime") as clock:
                clock.now.return_value = now
                c.scroll_to_now(force=True)
            actual = c.view.mapToScene(c.view.viewport().rect().center()).y()
            self.assertAlmostEqual(actual, c.minute_to_y(hour * 60 + minute), delta=2)

    def test_follow_pauses_and_resumes_after_ten_seconds(self):
        c = self.canvas
        with patch("alert_notes.calendar_canvas.monotonic", return_value=100):
            c.mark_user_scroll()
        with patch.object(c, "scroll_to_now") as scroll:
            with patch("alert_notes.calendar_canvas.monotonic", return_value=109):
                c._clock_tick()
            scroll.assert_not_called()
            with patch("alert_notes.calendar_canvas.monotonic", return_value=110):
                c._clock_tick()
            scroll.assert_called_once_with(force=True)
            scroll.reset_mock()
            c.editing_guard = lambda: True
            with patch("alert_notes.calendar_canvas.monotonic", return_value=500):
                c._clock_tick()
            scroll.assert_not_called()
            c.editing_guard = lambda: False
            with patch("alert_notes.calendar_canvas.monotonic", return_value=509):
                c._clock_tick()
            scroll.assert_not_called()
            with patch("alert_notes.calendar_canvas.monotonic", return_value=510):
                c._clock_tick()
            scroll.assert_called_once_with(force=True)
            scroll.reset_mock()
            c._start = date(2020, 1, 1)
            c._last_interaction = float("-inf")
            c._clock_tick()
            scroll.assert_not_called()

    def test_padding_cannot_create_schedule(self):
        c = self.canvas
        values = []
        c.rangeSelected.connect(lambda *v: values.append(v))
        c.view.verticalScrollBar().setValue(c.view.verticalScrollBar().minimum())
        QTest.mouseClick(c.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(120, 10))
        self.assertEqual(values, [])

    def test_day_render_scales_and_boundary_events(self):
        from ui_theme import scaled_stylesheet
        c = self.canvas
        c.render_range(date(2026, 9, 23), date(2026, 9, 24), [
            dict(event("202609230830", "202609230930"), id=1),
            dict(event("202609231730", "202609231830"), id=2),
            dict(event("202609232350", "202609240000"), id=3),
        ])
        for scale in (1, 1.25, 1.5):
            c.setStyleSheet(scaled_stylesheet(scale))
            c.scroll_to_hour(7)
            self.app.processEvents()
            QTest.qWait(20)
            self.assertEqual(c.blocks()[0].rect().top(), c.minute_to_y(510))
            self.assertEqual(c.blocks()[1].rect().bottom(), c.minute_to_y(1110))
            folder = os.environ.get("TOMADESK_FOCUS_CAPTURES")
            if folder:
                target = Path(folder)
                target.mkdir(parents=True, exist_ok=True)
                c.grab().save(str(target / f"day-{scale}.png"))


class MiniTimelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "test.db", "새 메모")
        self.p = StandaloneSchedulePopover(self.store)
        self.p.open_at_current_time()
        self.p.open_new(datetime(2026, 9, 23, 9), datetime(2026, 9, 23, 10))
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.p, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_existing_event_read_only_and_not_saved_on_drag(self):
        p = self.p
        self.store.schedules.save_item(dict(title="기존 일정", start_at="202609230900", end_at="202609231000"))
        mini = p.mini_timeline
        mini.set_draft(*p.current_range(), refresh=True)
        block, = mini.canvas.blocks()
        self.assertEqual(block.acceptedMouseButtons(), Qt.MouseButton.NoButton)
        mini.canvas.scroll_to_hour(8)
        view = mini.canvas.view
        first = view.mapFromScene(QPointF(120, mini.canvas.minute_to_y(540)))
        last = view.mapFromScene(QPointF(120, mini.canvas.minute_to_y(600)))
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
        QTest.mouseMove(view.viewport(), last)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=last)
        self.assertEqual(p.current_range(), (datetime(2026, 9, 23, 9), datetime(2026, 9, 23, 10)))
        self.assertEqual(len(self.store.schedules.items_for_range("202609230000", "202609240000")), 1)
        self.assertIn("time", p._touched)

    def test_cancel_restores_point_mode_and_original_range(self):
        p = self.p
        p._time_mode = "point"
        original = p.current_range()
        p._mini_started()
        p._mini_preview(datetime(2026, 9, 23, 12), datetime(2026, 9, 23, 13))
        self.assertIn("12:00", p.time_summary_button.text())
        p._escape_requested()
        self.assertEqual(p.current_range(), original)
        self.assertEqual(p._time_mode, "point")
        self.assertNotIn("time", p._touched)

    def test_nlp_and_manual_time_stay_synchronized(self):
        p = self.p
        p.title_edit.setText("회의 내일 10~11시 5분 전")
        self.assertEqual(p.mini_timeline._draft[:2], p.current_range())
        first = p._start.replace(hour=13, minute=0)
        p._mini_started()
        p._mini_selected(first, first + timedelta(hours=1))
        p.title_edit.setText(p.title_edit.text() + " 제목 수정")
        self.assertEqual(p.current_range(), (first, first + timedelta(hours=1)))
        self.assertIn("13:00", p.parse_label.text())

    def test_scales_widths_drawer_and_render(self):
        p = self.p
        for scale in (1, 1.25, 1.5):
            p.open_at_current_time(scale)
            for width in (420, 700, 1100):
                p._standalone_bounds = QRect(0, 0, width, 900)
                p._relayout()
                self.app.processEvents()
                QTest.qWait(40)
                self.assertLessEqual(p.width(), width)
                if p.mini_timeline.isVisible():
                    self.assertAlmostEqual(p.mini_timeline.overlay.rect().top(), p.mini_timeline.canvas.minute_to_y(p._start.hour * 60 + p._start.minute))
                self.assertTrue(p.rect().contains(QRect(p.save_button.mapTo(p, QPoint()), p.save_button.size())))
                for button in (p.time_chip, p.duration_chip, p.save_button, p.full_edit_button, *p.category_chips.values()):
                    if not button.isVisible():
                        continue  # 시간 모드의 반대 선택지만 화면에 표시한다.
                    self.assertTrue(button.visibleRegion().boundingRect().contains(button.rect()), (scale, width, button.text(), button.size(), button.visibleRegion().boundingRect()))
                if width == 420:
                    self.assertTrue(p.timeline_toggle.isVisible())
                    y = p.timeline_toggle.mapTo(p, QPoint()).y()
                    p.timeline_toggle.setChecked(True)
                    self.app.processEvents()
                    QTest.qWait(40)
                    self.assertTrue(p.mini_timeline.isVisible())
                    self.assertEqual(y, p.timeline_toggle.mapTo(p, QPoint()).y())
                    self.assertLessEqual(p.height(), 884)
                    folder = os.environ.get("TOMADESK_FOCUS_CAPTURES")
                    if folder:
                        target = Path(folder)
                        target.mkdir(parents=True, exist_ok=True)
                        p.grab().save(str(target / f"mini-expanded-{scale}.png"))
                    p._escape_requested()
                    self.assertFalse(p.mini_timeline.isVisible())
                else:
                    self.assertFalse(p.timeline_toggle.isVisible())
                    self.assertEqual(p.mini_timeline.width(), 220)
                folder = os.environ.get("TOMADESK_FOCUS_CAPTURES")
                if folder:
                    target = Path(folder)
                    target.mkdir(parents=True, exist_ok=True)
                    p.grab().save(str(target / f"mini-{scale}-{width}.png"))

    def test_short_screen_keeps_save_and_timeline_inside(self):
        p = self.p
        p.open_at_current_time(1.5)
        p._standalone_bounds = QRect(0, 0, 420, 540)
        p._relayout()
        p.timeline_toggle.setChecked(True)
        self.app.processEvents()
        QTest.qWait(30)
        self.assertLessEqual(p.height(), 524)
        for widget in (p.mini_timeline, p.save_button, p.timeline_toggle):
            self.assertTrue(p.rect().contains(QRect(widget.mapTo(p, QPoint()), widget.size())))
        self.assertGreater(p.body_scroll.verticalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
