"""메모 본문의 `@ 내일 3시` 알림: 인식, 칩, 저장 동기화, 편집기, 빠른 메모 창."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes import memo_inline_alarm as alarm
from alert_notes.recurrence import RULE_MONTHLY, RULE_WEEKLY, RecurrenceRule
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


NOW = datetime(2026, 10, 1, 11, 30)


def chip_html(text: str, now=None) -> str:
    """줄마다 @ 구절을 칩으로 바꾼 본문 HTML."""
    document = QTextDocument()
    document.setPlainText(text)
    block = document.begin()
    while block.isValid():
        phrase = alarm.find_phrase(block.text(), now or datetime.now())
        if phrase is not None and phrase.valid:
            alarm.apply_phrase(block, phrase)
        block = block.next()
    return document.toHtml()


class PhraseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reads_time_after_at(self):
        phrase = alarm.find_phrase("보고서 초안 보내기 @ 내일 오후 3시", NOW)
        self.assertTrue(phrase.valid)
        self.assertEqual(phrase.spec.at, datetime(2026, 10, 2, 15, 0))
        self.assertEqual(phrase.at_index, len("보고서 초안 보내기 "))

    def test_space_after_at_is_optional(self):
        self.assertEqual(alarm.find_phrase("치과 @내일 3시", NOW).spec.at, datetime(2026, 10, 2, 15, 0))

    def test_email_at_is_not_a_marker(self):
        self.assertIsNone(alarm.find_phrase("메일 hj@company.com 내일 3시", NOW))

    def test_bare_at_is_nothing(self):
        self.assertIsNone(alarm.find_phrase("회의 @ ", NOW))

    def test_unreadable_phrase_has_no_spec(self):
        phrase = alarm.find_phrase("회의 @ 본사", NOW)
        self.assertIsNotNone(phrase)
        self.assertIsNone(phrase.spec)
        self.assertFalse(phrase.valid)
        self.assertIn("예:", alarm.preview_text(phrase))

    def test_past_time_is_an_issue(self):
        phrase = alarm.find_phrase("점심 @ 오늘 오전 9시", NOW)
        self.assertFalse(phrase.valid)
        self.assertIn("지난", phrase.issue)

    def test_date_only_uses_current_time(self):
        self.assertEqual(alarm.find_phrase("서류 @ 금요일", NOW).spec.at, datetime(2026, 10, 2, 11, 30))
        self.assertEqual(alarm.find_phrase("@내일", NOW).spec.at, datetime(2026, 10, 2, 11, 30))
        self.assertEqual(alarm.find_phrase("점검 @ 내일 종일", NOW).spec.at, datetime(2026, 10, 2, 11, 30))
        # 오늘만 적으면 지금이라 이미 지난 시각이다.
        self.assertIn("지난", alarm.find_phrase("@ 오늘", NOW).issue)

    def test_offset_moves_due_earlier(self):
        phrase = alarm.find_phrase("회의 @ 다음 주 월 오전 10시 !1일전", NOW)
        self.assertEqual(phrase.spec.at, datetime(2026, 10, 5, 10, 0))
        self.assertEqual(phrase.spec.offsets, (1440,))
        self.assertEqual(phrase.spec.dues(), [datetime(2026, 10, 4, 10, 0)])
        self.assertEqual(phrase.leftover, "")
        phrase = alarm.find_phrase("회의 @ 내일 오후 3시 !30분전", NOW)
        self.assertEqual(phrase.spec.dues(), [datetime(2026, 10, 2, 14, 30)])

    def test_weekly_without_yoil(self):
        phrase = alarm.find_phrase("주간 보고 @ 매주 월 9시", NOW)
        self.assertTrue(phrase.valid)
        self.assertEqual(phrase.spec.rule, RecurrenceRule(RULE_WEEKLY, (0,)))
        self.assertEqual(phrase.spec.at, datetime(2026, 10, 5, 9, 0))

    def test_monthly_day(self):
        phrase = alarm.find_phrase("카드값 @ 매월 25일 10시", NOW)
        self.assertEqual(phrase.spec.rule.rule_type, RULE_MONTHLY)
        self.assertEqual(phrase.spec.rule.month_day, 25)
        self.assertEqual(phrase.spec.at, datetime(2026, 10, 25, 10, 0))

    def test_yearly_is_refused(self):
        self.assertIn("매년", alarm.find_phrase("생일 @ 매년 3시", NOW).issue)

    def test_words_inside_phrase_are_kept(self):
        phrase = alarm.find_phrase("@ 내일 치과 3시", NOW)
        self.assertEqual(phrase.leftover, "치과")

    def test_href_round_trip(self):
        spec = alarm.AlarmSpec(datetime(2026, 10, 5, 9, 0), (30, -5), RecurrenceRule(RULE_WEEKLY, (0, 2)), "매주 월 9시")
        key, back = alarm.parse_chip_href(alarm.chip_href("abcdef123456", spec))
        self.assertEqual(key, "abcdef123456")
        self.assertEqual(back, spec)

    def test_labels(self):
        self.assertEqual(alarm.chip_label(alarm.AlarmSpec(datetime(2026, 10, 2, 15, 0)), NOW), "⏰ 10/2(금) 15:00")
        weekly = alarm.AlarmSpec(datetime(2026, 10, 5, 9, 0), (60,), RecurrenceRule(RULE_WEEKLY, (0,)))
        self.assertEqual(alarm.chip_label(weekly, NOW), "⏰ 매주 월 09:00 · 1시간 전")

    def test_apply_phrase_makes_one_chip_and_keeps_text(self):
        document = QTextDocument()
        document.setPlainText("☐ 치과 예약 @ 내일 3시")
        phrase = alarm.find_phrase(document.begin().text(), NOW)
        alarm.apply_phrase(document.begin(), phrase, key="abc123abc123")
        text = document.begin().text()
        self.assertTrue(text.startswith("☐ 치과 예약 ⏰ 10/2(목) 15:00".replace("(목)", "(금)")))
        entries = alarm.collect_chips(document)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].key, "abc123abc123")
        self.assertEqual(entries[0].memo, "치과 예약")
        self.assertFalse(entries[0].checked)

    def test_chip_survives_html_round_trip(self):
        html = chip_html("할 일 @ 내일 3시")
        entries = alarm.collect_chips_from_content(html)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].memo, "할 일")

    def test_code_and_table_lines_are_skipped(self):
        document = QTextDocument()
        document.setPlainText("⌗ print('@ 내일 3시')")
        self.assertFalse(alarm.phrase_allowed(document.begin()))
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        table = cursor.insertTable(1, 1)
        self.assertFalse(alarm.phrase_allowed(table.cellAt(0, 0).firstCursorPosition().block()))


class ParserShorthandTest(unittest.TestCase):
    """빠른 일정과 같이 쓰는 파서에 더한 줄임말."""

    def parse(self, text):
        from alert_notes.ko_schedule_parser import parse
        return parse(text, now=NOW)

    def test_one_letter_weekday_before_time(self):
        self.assertEqual(self.parse("금 5시 회의").start, datetime(2026, 10, 2, 17, 0))
        self.assertEqual(self.parse("다음 주 월 오전 10시").start, datetime(2026, 10, 5, 10, 0))

    def test_one_letter_weekday_needs_a_time_and_a_boundary(self):
        self.assertEqual(self.parse("화장실 3시").title, "화장실")
        self.assertIsNone(self.parse("일 3시간 걸림").start)
        self.assertIsNone(self.parse("토 회의").start)
        self.assertEqual(self.parse("카드값 매월 25일 10시").start.date(), NOW.date())

    def test_weekly_repeat_without_yoil(self):
        self.assertEqual(self.parse("매주 월 9시").recurrence["weekdays"], [0])
        self.assertEqual(self.parse("매주 월간회의 9시").recurrence["weekdays"], [])

    def test_day_reminder(self):
        self.assertEqual(self.parse("내일 3시 !1일전").reminders, (1440,))


class SyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def pending(self, note_id):
        return self.store.pending_reminders_for_note(note_id)

    def test_new_chip_creates_alarm(self):
        note_id = self.store.create_note("메모", chip_html("보고서 보내기 @ 내일 오후 3시"))
        rows = self.pending(note_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["memo"], "보고서 보내기")
        self.assertTrue(rows[0]["inline_key"])
        expected = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d") + "1500"
        self.assertEqual(rows[0]["due_at"], expected)

    def test_saving_again_does_not_duplicate_and_updates_text(self):
        html = chip_html("보고서 보내기 @ 내일 오후 3시")
        note_id = self.store.create_note("메모", html)
        self.store.update_note(note_id, content=html)
        self.store.update_note(note_id, content=html.replace("보고서 보내기", "보고서 최종본 보내기"))
        rows = self.pending(note_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["memo"], "보고서 최종본 보내기")

    def test_removing_chip_removes_alarm(self):
        note_id = self.store.create_note("메모", chip_html("보고서 @ 내일 3시"))
        self.store.update_note(note_id, content="보고서")
        self.assertEqual(self.pending(note_id), [])

    def test_ordinary_reminders_are_left_alone(self):
        note_id = self.store.create_note("메모", "본문")
        due = (datetime.now() + timedelta(days=2)).strftime("%Y%m%d%H%M")
        self.store.add_reminder(note_id, due, "보통 알림")
        self.store.update_note(note_id, content=chip_html("칩 @ 내일 3시"))
        self.store.update_note(note_id, content="칩 없음")
        rows = self.pending(note_id)
        self.assertEqual([row["memo"] for row in rows], ["보통 알림"])

    def test_checking_line_parks_alarm_and_unchecking_revives(self):
        html = chip_html("☐ 치과 예약 @ 내일 3시")
        note_id = self.store.create_note("메모", html)
        self.store.update_note(note_id, content=html.replace("☐", "☑"))
        self.assertEqual(self.pending(note_id), [])
        self.store.update_note(note_id, content=html)
        self.assertEqual(len(self.pending(note_id)), 1)

    def test_deleted_from_alarm_list_is_not_recreated(self):
        html = chip_html("회의 @ 내일 3시")
        note_id = self.store.create_note("메모", html)
        self.store.delete_reminder(int(self.pending(note_id)[0]["id"]))
        self.store.update_note(note_id, content=html)
        self.assertEqual(self.pending(note_id), [])

    def test_clear_reminder_is_not_undone_by_saving(self):
        html = chip_html("회의 @ 내일 3시")
        note_id = self.store.create_note("메모", html)
        self.store.clear_reminder(note_id)
        self.store.update_note(note_id, content=html)
        self.assertEqual(self.pending(note_id), [])

    def test_changed_time_replaces_alarm(self):
        note_id = self.store.create_note("메모", chip_html("회의 @ 내일 3시"))
        self.store.update_note(note_id, content=chip_html("회의 @ 내일 5시"))
        rows = self.pending(note_id)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["due_at"].endswith("1700"))

    def test_offsets_make_one_alarm_each(self):
        note_id = self.store.create_note("메모", chip_html("회의 @ 내일 3시 !10분전 !1시간전"))
        self.assertEqual(sorted(row["due_at"][-4:] for row in self.pending(note_id)), ["1400", "1450"])

    def test_weekly_chip_creates_repeating_alarm_that_keeps_its_key(self):
        note_id = self.store.create_note("메모", chip_html("주간 보고 @ 매주 월 9시"))
        rows = self.pending(note_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rule_type"], RULE_WEEKLY)
        key = rows[0]["inline_key"]
        self.store.complete_reminder(int(rows[0]["id"]))
        following = self.pending(note_id)
        self.assertEqual(len(following), 1)
        self.assertEqual(following[0]["inline_key"], key)
        self.assertGreater(following[0]["due_at"], rows[0]["due_at"])

    def test_fired_alarm_is_not_recreated(self):
        html = chip_html("회의 @ 내일 3시")
        note_id = self.store.create_note("메모", html)
        self.store.complete_reminder(int(self.pending(note_id)[0]["id"]))
        self.store.update_note(note_id, content=html)
        self.assertEqual(self.pending(note_id), [])

    def test_old_database_gets_inline_key_column(self):
        path = Path(self.temp.name) / "notes.db"
        note_id = self.store.create_note("이전 메모", "원본 내용")
        due = (datetime.now() + timedelta(days=2)).strftime("%Y%m%d%H%M")
        self.store.add_reminder(note_id, due, "기존 알림")
        self.store.close()
        import sqlite3
        conn = sqlite3.connect(path)
        conn.execute("ALTER TABLE reminders DROP COLUMN inline_key")
        conn.commit()
        conn.close()
        self.store = NoteReminderStore(path, "새 메모")
        backup_path = self.store.upgrade_backup_path
        self.assertIsNotNone(backup_path)
        self.assertTrue(backup_path.is_file())
        columns = {row[1] for row in self.store.conn.execute("PRAGMA table_info(reminders)")}
        self.assertIn("inline_key", columns)
        self.assertEqual(
            self.store.conn.execute("SELECT content FROM notes WHERE id = ?", (note_id,)).fetchone()[0],
            "원본 내용",
        )
        self.assertEqual(self.store.pending_reminders_for_note(note_id)[0]["memo"], "기존 알림")
        with sqlite3.connect(backup_path) as backup:
            old_columns = {row[1] for row in backup.execute("PRAGMA table_info(reminders)")}
            self.assertNotIn("inline_key", old_columns)
            self.assertEqual(backup.execute("SELECT content FROM notes WHERE id = ?", (note_id,)).fetchone()[0], "원본 내용")


class EditorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from alert_notes.rich_memo_edit import RichMemoTextEdit
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.resize(620, 400)
        self.editor.show()
        self.editor.setFocus()
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def type(self, text):
        # 오프스크린 QTest.keyClicks는 한글 글자에서 프로세스가 죽는다.  입력과 같은 경로로 넣는다.
        self.editor.insertPlainText(text)
        self.app.processEvents()

    def chips(self):
        return alarm.collect_chips(self.editor.document())

    def test_typing_shows_preview_and_enter_makes_chip(self):
        self.type("보고서 보내기 @ 내일 오후 3시")
        self.assertTrue(self.editor.inline_alarms.preview.isVisible())
        self.assertIn("Enter 확정", self.editor.inline_alarms.preview.text())
        self.assertTrue(self.editor.inline_alarms.selections())
        QTest.keyClick(self.editor, Qt.Key.Key_Return)
        self.app.processEvents()
        chips = self.chips()
        self.assertEqual(len(chips), 1)
        self.assertEqual(chips[0].memo, "보고서 보내기")
        self.assertEqual(self.editor.document().blockCount(), 2)
        self.assertEqual(self.editor.textCursor().blockNumber(), 1)
        self.assertNotIn("@", self.editor.toPlainText())

    def test_bare_at_shows_examples(self):
        self.type("회의 @")
        self.assertIn("예:", self.editor.inline_alarms.preview.text())

    def test_escape_keeps_plain_text(self):
        self.type("회의 @ 내일 3시")
        QTest.keyClick(self.editor, Qt.Key.Key_Escape)
        QTest.keyClick(self.editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.chips(), [])
        self.assertIn("@ 내일 3시", self.editor.toPlainText())

    def test_leaving_line_commits(self):
        self.type("첫 줄\n둘째 줄 @ 내일 3시")
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.editor.setTextCursor(cursor)
        for _ in range(3):
            self.app.processEvents()
        self.assertEqual(len(self.chips()), 1)

    def test_loaded_text_is_never_committed(self):
        self.editor.set_content("예전 메모 @ 내일 3시\n다음 줄")
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)
        for _ in range(3):
            self.app.processEvents()
        self.assertEqual(self.chips(), [])

    def test_double_click_cancels_a_piece(self):
        self.type("회의 @ 내일 3시")
        controller = self.editor.inline_alarms
        live = controller._live_block()
        phrase = controller._phrase_for(live)
        date_span = next(span for span in phrase.spans if span.kind == "date")
        cursor = QTextCursor(live)
        cursor.setPosition(live.position() + date_span.start + 1)
        point = self.editor.cursorRect(cursor).center()
        self.assertTrue(controller.handle_double_click(point))
        phrase = controller._phrase_for(live)
        self.assertNotIn("date", {span.kind for span in phrase.spans})

    def test_chip_reopen_puts_phrase_back(self):
        self.type("회의 @ 내일 3시")
        QTest.keyClick(self.editor, Qt.Key.Key_Return)
        start, end, _href = alarm.chip_runs(self.editor.document().begin())[0]
        found = alarm.chip_at(self.editor.document(), start)
        self.editor.inline_alarms._reopen_chip(found[0], found[1], found[3])
        self.assertIn("@내일 3시", self.editor.document().begin().text())

    def test_chip_moves_to_schedule(self):
        self.type("팀 회의 @ 내일 3시")
        QTest.keyClick(self.editor, Qt.Key.Key_Return)
        start, end, key, spec = alarm.chip_at(self.editor.document(), alarm.chip_runs(self.editor.document().begin())[0][0])
        self.editor.inline_alarms._move_to_schedule(start, end, spec)
        self.assertEqual(self.chips(), [])
        rows = self.store.schedules.items_for_range("200001010000", "209912312359")
        self.assertTrue(any(str(row["title"]) == "팀 회의" for row in rows))


class QuickMemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from alert_notes.quick_capture import QuickMemoDialog
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.dialog = QuickMemoDialog(self.store)
        self.dialog.prepare()
        self.saved = []
        self.dialog.note_saved.connect(self.saved.append)

    def tearDown(self):
        destroy_widget(self.dialog, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_title_phrase_sets_alarm_and_clean_title(self):
        self.dialog.title_edit.setText("보고서 보내기 @ 내일 오후 3시")
        self.assertTrue(self.dialog.alarm_preview.isVisibleTo(self.dialog))
        self.dialog._save()
        note = self.store.note(self.saved[0])
        self.assertEqual(note["title"], "보고서 보내기")
        rows = self.store.pending_reminders_for_note(self.saved[0])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["due_at"].endswith("1500"))

    def test_content_lines_each_get_alarm(self):
        self.dialog.title_edit.setText("할 일")
        self.dialog.content_edit.setPlainText("치과 @ 내일 3시\n장보기 @ 내일 저녁 7시\n메모만")
        self.dialog._save()
        rows = self.store.pending_reminders_for_note(self.saved[0])
        self.assertEqual(sorted(row["memo"] for row in rows), ["장보기", "치과"])

    def test_plain_memo_is_unchanged(self):
        self.dialog.title_edit.setText("그냥 메모")
        self.dialog.content_edit.setPlainText("hj@company.com")
        self.dialog._save()
        note = self.store.note(self.saved[0])
        self.assertEqual(note["content"], "hj@company.com")
        self.assertEqual(self.store.pending_reminders_for_note(self.saved[0]), [])


if __name__ == "__main__":
    unittest.main()
