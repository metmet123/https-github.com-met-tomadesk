"""1~2단계의 입력 취소·요일·시작 후 알림 회귀 (격리 DB)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QDate, QPoint, QRect, QTime, Qt
from PyQt6.QtGui import QInputMethodEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.ko_schedule_parser import parse
from alert_notes.schedule_popover import StandaloneSchedulePopover
from alert_notes.schedule_editor import ScheduleEditor
from alert_notes.schedule_reminders import parse_reminder_value
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


class ReminderParserTest(unittest.TestCase):
    def test_bare_after_uses_explicit_clock_context_anywhere(self):
        now = datetime(2026, 9, 23, 9)
        for text in ("18시 회의 5분후", "18시 회의 5분 후", "회의 18시 5 분 후",
                     "5분 후 회의 18시", "회의 10~18시 5분후"):
            with self.subTest(text=text):
                parsed = parse(text, now=now)
                self.assertEqual(parsed.reminders, (-5,))
                self.assertEqual(parsed.title, "회의")
                self.assertEqual(parsed.start.minute, 0)
                self.assertEqual(parsed.start.hour, 10 if "10~" in text else 18)
                edges = [(s.start, s.end) for s in parsed.spans]
                self.assertTrue(all(a[1] <= b[0] for a, b in zip(edges, edges[1:])))

    def test_relative_minutes_and_compound_remain_relative(self):
        now = datetime(2026, 9, 23, 9)
        for phrase, minutes in (("30분후", 30), ("30분 후", 30), ("90분 후", 90),
                                ("1시간 30분 후", 90), ("1시간30분후", 90)):
            for text in (phrase + " 회의", "회의 " + phrase):
                with self.subTest(text=text):
                    parsed = parse(text, now=now)
                    self.assertEqual(parsed.start, now + timedelta(minutes=minutes))
                    self.assertEqual(parsed.reminders, ())
                    self.assertEqual(parsed.title, "회의")

    def test_iso_date_is_not_clock_context_for_after_alarm(self):
        parsed = parse("2026-10-02 회의 30분 후", now=datetime(2026, 9, 23, 9))
        self.assertEqual(parsed.reminders, ())
        self.assertEqual(parsed.start, datetime(2026, 10, 2, 9, 30))
        self.assertEqual(parsed.title, "회의")

    def test_cancelled_clock_does_not_turn_after_alarm_into_relative_time(self):
        text = "18시 회의 5분 후"
        parsed = parse(text)
        ignored = tuple((s.start, s.end, s.kind) for s in parsed.spans if s.kind == "time")
        cancelled = parse(text, ignored_spans=ignored)
        self.assertIsNone(cancelled.start)
        self.assertEqual(cancelled.reminders, (-5,))
        self.assertEqual(cancelled.title, "18시 회의")

    def test_cancelled_after_alarm_is_not_reinterpreted_as_relative_time(self):
        text = "5분 후 회의 18시"
        parsed = parse(text)
        ignored = tuple((s.start, s.end, s.kind) for s in parsed.spans if s.kind == "reminder")
        cancelled = parse(text, ignored_spans=ignored)
        self.assertEqual(cancelled.start.hour, 18)
        self.assertEqual(cancelled.reminders, ())
        self.assertIn("5분 후", cancelled.title)

    def test_conflicting_dates_are_not_silently_chosen(self):
        parsed = parse("10.2. 회의 10/3", now=datetime(2026, 9, 23))
        self.assertTrue(parsed.issues)
        self.assertIsNone(parsed.start)
        self.assertIn("10.2.", parsed.title)
        self.assertIn("10/3", parsed.title)

    def test_before_and_explicit_after_spacing_and_order(self):
        for expression, expected in (
            ("5분전", 5), ("5분 전", 5), ("5 분 전", 5),
            ("5분후 알림", -5), ("5분 후 알림", -5),
            ("알람 5 분 후", -5), ("알림5분후", -5),
            ("!5분후", -5), ("알림", 0),
        ):
            with self.subTest(expression=expression):
                parsed = parse("18시 견학 " + expression, now=datetime(2026, 9, 23, 9))
                self.assertEqual(parsed.reminders, (expected,))
                self.assertEqual(parsed.title, "견학")
                self.assertEqual(parsed.start.hour, 18)
                self.assertEqual(parsed.start.minute, 0)

    def test_adjacent_alarm_is_not_clock_minutes(self):
        parsed = parse("18시 5분 전 견학")
        self.assertEqual(parsed.start.minute, 0)
        self.assertEqual(parsed.reminders, (5,))
        self.assertEqual(parsed.title, "견학")

    def test_alarm_words_are_not_read_inside_other_words(self):
        self.assertEqual(parse("알림장 준비").title, "알림장 준비")

    def test_reminder_input_roundtrip(self):
        for text, value in (("5분 후", -5), ("5 분 전", 5), ("-5", -5), ("0", 0)):
            self.assertEqual(parse_reminder_value(text), value)
        for text in ("후", "-5분 전", "999999", "abc"):
            with self.assertRaises(ValueError):
                parse_reminder_value(text)


class ScheduleNlpStage12Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.popover = StandaloneSchedulePopover(self.store)
        self.popover.open_at_current_time()
        start = datetime(2026, 9, 23, 10)
        self.popover.open_new(start, start + timedelta(hours=1))
        self.popover.show()
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.popover, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_cancellation_survives_prefix_suffix_and_undo(self):
        edit = self.popover.title_edit
        edit.setText("회의 금요일")
        token = next(s for s in edit.token_spans() if s.kind == "date")
        QTest.mouseDClick(edit, Qt.MouseButton.LeftButton, pos=edit.token_rect(token).center())
        edit.setCursorPosition(0)
        edit.insert("긴 ")
        edit.end(False)
        edit.insert(" 준비")
        self.assertIn("금요일", self.popover.values()["title"])
        self.assertFalse(any(s.kind == "date" for s in edit.token_spans()))
        edit.undo()
        self.assertIn("금요일", self.popover.values()["title"])
        edit.setText(edit.text().replace("금요일", "토요일"))
        self.assertTrue(any(s.kind == "date" for s in edit.token_spans()))

    def cancel_token(self, kind):
        token = next(s for s in self.popover.title_edit.token_spans() if s.kind == kind)
        self.popover.title_edit.token_double_clicked.emit(token.start, token.end, token.kind)

    def test_auto_alarm_cancel_keeps_manual_added_alarm(self):
        self.popover.title_edit.setText("18시 회의 5분 후")
        self.popover._quick_reminder(10)
        self.assertEqual(self.popover.values()["reminders"], [-5, 10])
        self.cancel_token("reminder")
        self.assertEqual(self.popover.values()["reminders"], [10])
        self.assertIn("5분 후", self.popover.values()["title"])

    def test_manual_replacement_survives_auto_alarm_cancel(self):
        self.popover.title_edit.setText("18시 회의 5분 전")
        self.popover._select_reminder_preset(5, True)
        self.cancel_token("reminder")
        self.assertEqual(self.popover.values()["reminders"], [5])

    def test_cancel_date_keeps_manual_time_and_other_way_round(self):
        self.popover.title_edit.setText("10.2. 18시 회의")
        self.popover.start_time_edit.setTime(QTime(11, 0))
        self.cancel_token("date")
        self.assertEqual(self.popover.values()["start_at"], "202609231100")
        self.popover.title_edit.setText("10.3. 18시 회의")
        self.popover.date_edit.setDate(QDate(2026, 10, 4))
        self.cancel_token("time")
        self.assertEqual(self.popover.values()["start_at"], "202610041100")

    def test_edited_explicit_time_overrides_manual_but_unrelated_text_does_not(self):
        self.popover.title_edit.setText("10.2. 18시 회의")
        self.popover.start_time_edit.setTime(QTime(11, 0))
        self.popover.title_edit.setText("10.2. 18시 회의 준비")
        self.assertEqual(self.popover.values()["start_at"][-4:], "1100")
        self.popover.title_edit.setText("10.2. 17시 회의 준비")
        self.assertEqual(self.popover.values()["start_at"][-4:], "1700")
        self.cancel_token("time")
        self.assertEqual(self.popover.values()["start_at"][-4:], "1100")

    def test_cancel_new_date_expression_restores_previous_manual_date(self):
        self.popover.title_edit.setText("10.2. 18시 회의")
        self.popover.date_edit.setDate(QDate(2026, 10, 4))
        self.popover.title_edit.setText("10.5. 18시 회의")
        self.assertEqual(self.popover.values()["start_at"][:8], "20261005")
        self.cancel_token("date")
        self.assertEqual(self.popover.values()["start_at"][:8], "20261004")

    def test_utf16_emoji_before_cancelled_weekday(self):
        edit = self.popover.title_edit
        edit.setText("😀 회의 금요일")
        edit.end(False)
        self.app.processEvents()
        token = next(s for s in edit.token_spans() if s.kind == "date")
        QTest.mouseDClick(edit, Qt.MouseButton.LeftButton, pos=edit.token_rect(token).center())
        self.assertEqual(self.popover.values()["title"], "😀 회의 금요일")

    def test_ime_preedit_does_not_commit_a_token(self):
        edit = self.popover.title_edit
        edit.setText("회의 ")
        edit.end(False)
        self.app.sendEvent(edit, QInputMethodEvent("금요일", []))
        self.assertEqual(edit.text(), "회의 ")
        self.assertTrue(edit._preediting)
        self.assertEqual(edit.token_spans(), ())
        commit = QInputMethodEvent()
        commit.setCommitString("금요일")
        self.app.sendEvent(edit, commit)
        self.assertFalse(edit._preediting)
        self.assertTrue(any(s.kind == "date" for s in edit.token_spans()))

    def test_ime_preedit_keeps_an_existing_time_token_visible(self):
        edit = self.popover.title_edit
        edit.setText("2시 10분 회의")
        edit.end(False)
        before = tuple(edit.token_spans())
        self.assertTrue(any(span.kind == "time" for span in before))

        self.app.sendEvent(edit, QInputMethodEvent("전", []))

        self.assertEqual(edit.text(), "2시 10분 회의")
        self.assertTrue(edit._preediting)
        self.assertEqual(edit.paintable_token_spans(), before)

        commit = QInputMethodEvent()
        commit.setCommitString("전")
        self.app.sendEvent(edit, commit)
        self.assertFalse(edit._preediting)
        self.assertTrue(all(
            edit.text()[span.start:span.end] == span.text
            for span in edit.paintable_token_spans()
        ))

    def test_time_only_title_is_saved_as_untitled(self):
        # 빠른 일정 창은 날짜·시간만 적어도 ‘제목없음’으로 저장한다(2026-10-01 요청).
        self.popover.title_edit.setText("10.2. 18시")
        self.assertEqual(self.popover.values()["title"], "제목없음")
        with patch("alert_notes.schedule_popover.QMessageBox.warning") as warning:
            self.assertTrue(self.popover.save())
        warning.assert_not_called()
        self.assertIsNotNone(self.popover.item_id)

    def test_conflicting_dates_do_not_save(self):
        self.popover.title_edit.setText("10.2. 회의 10/3")
        with patch("alert_notes.schedule_popover.QMessageBox.warning") as warning:
            self.assertFalse(self.popover.save())
        warning.assert_called_once()

    def test_live_window_input_geometry(self):
        edit = self.popover.title_edit
        edit.setText("금요일 18시 견학 5분 전")
        edit.setFocus()
        self.app.processEvents()
        self.assertTrue(self.popover.isVisible())
        mapped = QRect(edit.mapTo(self.popover, QPoint()), edit.size())
        self.assertTrue(self.popover.rect().contains(mapped), f"window={self.popover.rect()} edit={mapped}")
        print(f"WINDOW platform={self.app.platformName()} size={self.popover.width()}x{self.popover.height()} "
              f"title={edit.width()}x{edit.height()} tokens={len(edit.token_spans())}")

    def test_after_alarm_save_reopen_full_editor_and_cancel(self):
        self.popover.title_edit.setText("18시 견학 알림 5분 후")
        self.assertEqual(self.popover.values()["reminders"], [-5])
        self.assertEqual(self.popover.parse_label.text(), "18:00\n18:00의 5분 후 알람 · 18:05")
        self.assertIn("5분 후", self.popover.parse_label.toolTip())
        self.assertTrue(self.popover.save())
        item_id = self.popover.item_id
        self.assertEqual(self.store.schedules.notifications(item_id), [-5])
        self.assertTrue(self.popover.open_item(item_id))
        self.assertEqual(self.popover.values()["reminders"], [-5])
        editor = ScheduleEditor(self.store)
        try:
            editor.load_item(item_id)
            self.assertEqual(editor.values()["reminders"], [-5])
        finally:
            destroy_widget(editor, self.app)

    def test_after_alarm_due_across_midnight_and_not_early(self):
        item_id = self.store.schedules.save_item({
            "title": "자정 넘어 알림", "start_at": "203001012358", "end_at": "203001012359",
            "reminders": [-5],
        })
        self.assertEqual(self.store.schedules.due_notifications(datetime(2030, 1, 2, 0, 2)), [])
        due = self.store.schedules.due_notifications(datetime(2030, 1, 2, 0, 3))
        self.assertEqual([row["item_id"] for row in due], [item_id])
        overview = self.store.schedules.notification_overview(datetime(2030, 1, 2), days=1)
        self.assertEqual(overview[0]["due_at"], "203001020003")


if __name__ == "__main__":
    unittest.main()
