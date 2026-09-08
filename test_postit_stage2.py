import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.deadline import countdown_text, deadline_badge_text, reminder_display_text
from alert_notes.editor import COLORS
from alert_notes.panel import AlertNotesPanel
from alert_notes.postit import PostitWindow
from alert_notes.rich_memo_edit import CHECKED_PREFIX, UNCHECKED_PREFIX, RichMemoTextEdit
from alert_notes.rich_text import plain_text_from_content
from alert_notes.sqlite_store import DATETIME_FMT, NoteReminderStore
from alert_notes.toma_pet_alert import TomaPetAlertDialog


class PostitStageTwoStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_deadline_upserts_one_alert_and_clears_it(self):
        note_id = self.store.create_note("마감", "제출 내용")
        first = (datetime.now() + timedelta(days=3)).strftime(DATETIME_FMT)
        second = (datetime.now() + timedelta(days=5)).strftime(DATETIME_FMT)
        self.store.set_deadline(note_id, first, "보고서", True)
        self.store.set_deadline(note_id, second, "최종 보고서", True)
        rows = list(self.store.conn.execute(
            "SELECT * FROM reminders WHERE note_id=? AND occurrence_kind='deadline'",
            (note_id,),
        ))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["due_at"], second)
        self.assertEqual(rows[0]["memo"], "최종 보고서")
        note = self.store.note(note_id)
        self.assertEqual(note["d_day_at"], second)
        self.assertTrue(note["d_day_alert"])
        self.store.set_deadline(note_id, second, "표시만", False)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM reminders WHERE note_id=? AND occurrence_kind='deadline'",
            (note_id,),
        ).fetchone()[0], 0)
        self.store.clear_deadline(note_id)
        note = self.store.note(note_id)
        self.assertEqual(note["d_day_at"], "")
        self.assertEqual(note["d_day_label"], "")

    def test_countdown_and_badge_cover_before_today_and_after(self):
        now = datetime(2026, 8, 15, 12, 0)
        self.assertEqual(countdown_text("202608181200", now), "D-3")
        self.assertEqual(countdown_text("202608151300", now), "1시간")
        self.assertEqual(countdown_text("202608151100", now), "D-DAY")
        self.assertEqual(countdown_text("202608131200", now), "D+2")
        note = {"d_day_at": "202608181200", "d_day_label": "출시"}
        self.assertEqual(deadline_badge_text(note, now), "D-3 : 출시")
        self.assertEqual(
            deadline_badge_text({"d_day_at": "202608181200", "d_day_label": "D-Day"}, now),
            "D-3",
        )
        self.assertEqual(
            deadline_badge_text({"d_day_at": "202608181200", "d_day_label": ""}, now),
            "D-3",
        )
        self.assertEqual(reminder_display_text("202608151930", now), "19:30 🔔")
        self.assertEqual(reminder_display_text("202608181930", now), "8/18 19:30 🔔")


class PostitStageTwoUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db")

    def tearDown(self):
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.store.close()
        self.temp.cleanup()

    def test_checklist_selection_enter_delete_and_checked_strike(self):
        note_id = self.store.create_note("할 일", "첫째\n둘째\n셋째")
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        editor.setPlainText("첫째\n둘째\n셋째")
        cursor = editor.textCursor()
        cursor.setPosition(0)
        second_end = editor.document().findBlockByNumber(1).position() + 2
        cursor.setPosition(second_end, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.toggle_checklist()
        lines = editor.toPlainText().splitlines()
        self.assertTrue(lines[0].startswith(UNCHECKED_PREFIX))
        self.assertTrue(lines[1].startswith(UNCHECKED_PREFIX))
        self.assertFalse(lines[2].startswith(UNCHECKED_PREFIX))

        editor.resize(360, 240)
        editor.show()
        self.app.processEvents()
        first_block = editor.document().findBlockByNumber(0)
        rich_cursor = QTextCursor(first_block)
        rich_cursor.setPosition(first_block.position() + 2)
        rich_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        original = QTextCharFormat()
        original.setAnchor(True)
        original.setAnchorHref("https://example.com")
        original.setForeground(QColor("#2563eb"))
        original.setFontUnderline(True)
        rich_cursor.mergeCharFormat(original)
        cursor = QTextCursor(editor.document().findBlockByNumber(0))
        visual_rect = editor._checkbox_rect(cursor.block())
        hit_rect = editor._checkbox_rect(cursor.block(), hit_target=True)
        self.assertEqual(visual_rect.width(), 15.0)
        self.assertEqual(hit_rect.width(), 24.0)
        checkbox_point = QPoint(int(hit_rect.right() - 1), int(hit_rect.center().y()))
        QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton, pos=checkbox_point)
        self.app.processEvents()
        self.assertTrue(editor.toPlainText().startswith(CHECKED_PREFIX))
        text_cursor = QTextCursor(editor.document().findBlockByNumber(0))
        text_cursor.setPosition(text_cursor.block().position() + 3)
        completed_selections = [
            selection for selection in editor.extraSelections()
            if selection.format.fontStrikeOut()
        ]
        self.assertTrue(completed_selections)
        self.assertFalse(text_cursor.charFormat().fontStrikeOut())
        self.assertEqual(text_cursor.charFormat().anchorHref(), "https://example.com")
        self.assertEqual(text_cursor.charFormat().foreground().color(), QColor("#2563eb"))
        editor._toggle_check_state(text_cursor.block())
        self.assertTrue(editor.toPlainText().startswith(UNCHECKED_PREFIX))
        self.assertFalse(text_cursor.charFormat().fontStrikeOut())
        self.assertEqual(text_cursor.charFormat().anchorHref(), "https://example.com")

        editor.moveCursor(QTextCursor.MoveOperation.EndOfBlock)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertTrue(editor.textCursor().block().text().startswith(UNCHECKED_PREFIX))
        QTest.keyClick(editor, Qt.Key.Key_Backspace)
        self.assertFalse(editor.textCursor().block().text().startswith(UNCHECKED_PREFIX))
        self.assertIn("☐", editor.toPlainText())
        editor.moveCursor(QTextCursor.MoveOperation.Start)
        QTest.keyClick(editor, Qt.Key.Key_Delete)
        self.assertFalse(editor.document().firstBlock().text().startswith((UNCHECKED_PREFIX, CHECKED_PREFIX)))
        editor.close()
        editor.deleteLater()
        self.app.processEvents()

    def test_postit_meta_row_alignment_visibility_and_compact_content(self):
        note_id = self.store.create_note("저장된 제목", "\n  첫 번째 유효한 줄\n둘째 줄")
        due = (datetime.now() + timedelta(days=3)).replace(hour=19, minute=30)
        self.store.set_deadline(note_id, due.strftime(DATETIME_FMT), "행정감사", False)
        reminder = datetime.now().replace(hour=19, minute=30).strftime(DATETIME_FMT)
        self.store.add_reminder(note_id, reminder, "알림")
        self.store.update_note(note_id, postit=True, postit_visible=True)
        window = PostitWindow(self.store, self.store.note(note_id))
        window.show()
        self.app.processEvents()
        window._set_controls_visible(False)
        self.assertTrue(window.bar.isHidden())
        self.assertFalse(window.meta_row.isHidden())
        self.assertIn(" : 행정감사", window.deadline_badge._full_text)
        self.assertTrue(window.reminder_label.text().endswith("🔔"))
        window._set_controls_visible(True)
        self.assertFalse(window.bar.isHidden())
        window._set_display_mode("title")
        self.assertEqual(window.bar.label._full_text, "첫 번째 유효한 줄")
        self.assertNotEqual(window.bar.label._full_text, "저장된 제목")
        window.close_silently()
        self.app.processEvents()

    def test_meta_row_optional_items_and_narrow_width_preserve_fixed_text(self):
        note_id = self.store.create_note("제목", "본문")
        self.store.update_note(note_id, postit=True, postit_visible=True)
        window = PostitWindow(self.store, self.store.note(note_id))
        window.show()
        self.app.processEvents()
        window._set_controls_visible(False)
        self.app.processEvents()
        self.assertTrue(window.meta_row.isHidden())

        reminder = (datetime.now() + timedelta(days=1)).replace(hour=19, minute=30)
        reminder_id = self.store.add_reminder(note_id, reminder.strftime(DATETIME_FMT), "예정 알림")
        later_reminder_id = self.store.add_reminder(
            note_id, (reminder + timedelta(hours=1)).strftime(DATETIME_FMT), "더 나중 알림",
        )
        window.update_note(self.store.note(note_id))
        window._set_controls_visible(False)
        self.app.processEvents()
        self.assertTrue(window.deadline_badge.isHidden())
        self.assertFalse(window.reminder_label.isHidden())
        self.assertEqual(window.reminder_label.text(), reminder_display_text(reminder.strftime(DATETIME_FMT)))
        self.assertEqual(
            window.reminder_label.x() + window.reminder_label.width(),
            window.meta_row.width() - window.meta_row.layout().contentsMargins().right(),
        )
        self.store.delete_reminder(reminder_id)
        self.store.delete_reminder(later_reminder_id)

        due = (datetime.now() + timedelta(days=3)).replace(hour=19, minute=30)
        self.store.set_deadline(
            note_id, due.strftime(DATETIME_FMT),
            "매우 긴 행정감사 제목입니다 계속 길어집니다", False,
        )
        window.update_note(self.store.note(note_id))
        window._set_controls_visible(False)
        self.app.processEvents()
        self.assertFalse(window.deadline_badge.isHidden())
        self.assertTrue(window.reminder_label.isHidden())
        self.assertEqual(window.deadline_badge.x(), window.meta_row.layout().contentsMargins().left())

        self.store.add_reminder(note_id, reminder.strftime(DATETIME_FMT), "예정 알림")
        window.update_note(self.store.note(note_id))
        window._set_controls_visible(False)
        window.resize(240, 220)
        self.app.processEvents()
        self.assertGreaterEqual(window.reminder_label.width(), window.reminder_label.sizeHint().width())
        self.assertEqual(window.deadline_badge.countdown.text(), "D-3 : ")
        self.assertGreaterEqual(
            window.deadline_badge.countdown.width(), window.deadline_badge.countdown.sizeHint().width(),
        )
        self.assertEqual(window.deadline_badge.title._full_text, "매우 긴 행정감사 제목입니다 계속 길어집니다")
        self.assertNotEqual(window.deadline_badge.title.text(), window.deadline_badge.title._full_text)
        self.assertEqual(
            window.reminder_label.x() + window.reminder_label.width(),
            window.meta_row.width() - window.meta_row.layout().contentsMargins().right(),
        )
        self.assertEqual(window.container.layout().indexOf(window.bar), 0)
        self.assertEqual(window.container.layout().indexOf(window.meta_row), 1)
        inactive_top = window.meta_row.y()
        window._set_controls_visible(True)
        self.app.processEvents()
        self.assertGreaterEqual(window.meta_row.y(), window.bar.y() + window.bar.height())
        self.assertGreater(window.meta_row.y(), inactive_top)
        self.assertLessEqual(
            window.format_bar.x() + window.format_bar.width(), window.container.width() - 10,
        )
        window.close_silently()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_unchecked_graphic_keeps_every_postit_background_visible(self):
        note_id = self.store.create_note("배경", "☐ 배경 투명 체크")
        self.store.update_note(note_id, postit=True, postit_visible=True)
        window = PostitWindow(self.store, self.store.note(note_id))
        window.resize(360, 240)
        window.show()
        self.app.processEvents()
        window._set_controls_visible(False)
        self.app.processEvents()
        block = window.memo.document().firstBlock()
        rect = window.memo._checkbox_rect(block)
        checkbox_center = rect.center().toPoint()
        for color_key in COLORS:
            for transparency in (0, 30, 50, 70, 100):
                window._apply_surface_style(color_key, transparency)
                self.app.processEvents()
                image = window.memo.viewport().grab().toImage()
                scale = image.devicePixelRatio()
                sample_x = round(checkbox_center.x() * scale)
                sample_y = round(checkbox_center.y() * scale)
                inside = image.pixelColor(sample_x, sample_y)
                blank = image.pixelColor(
                    sample_x, min(image.height() - 1, round((checkbox_center.y() + 32) * scale)),
                )
                self.assertEqual(
                    inside.rgba(), blank.rgba(),
                    msg=f"{color_key}/{transparency}% 체크박스 내부가 배경과 다릅니다.",
                )
        window.memo._toggle_check_state(block)
        self.app.processEvents()
        checked_image = window.memo.viewport().grab().toImage()
        scale = checked_image.devicePixelRatio()
        background = checked_image.pixelColor(
            round(checkbox_center.x() * scale),
            min(checked_image.height() - 1, round((checkbox_center.y() + 32) * scale)),
        ).rgba()
        clear_pixels = 0
        for x in range(round((rect.left() + 3) * scale), round((rect.right() - 2) * scale)):
            for y in range(round((rect.top() + 3) * scale), round((rect.bottom() - 2) * scale)):
                clear_pixels += checked_image.pixelColor(x, y).rgba() == background
        self.assertGreaterEqual(clear_pixels, round(35 * scale * scale))
        window.close_silently()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_compact_modes_persist_and_restore_expanded_geometry(self):
        note_id = self.store.create_note("접기 제목", "본문")
        self.store.update_note(note_id, postit=True, postit_visible=True, postit_startup=True)
        window = PostitWindow(self.store, self.store.note(note_id))
        window.resize(420, 310)
        window._set_display_mode("title")
        self.assertEqual(self.store.note(note_id)["postit_display_mode"], "title")
        self.assertTrue(window.memo.isHidden())
        self.assertLessEqual(window.height(), 64)
        window._set_display_mode("badge")
        self.assertTrue(window.container.isHidden())
        self.assertFalse(window.badge_button.isHidden())
        self.assertLessEqual(window.width(), 64)
        window.badge_button.click()
        self.app.processEvents()
        self.assertEqual(self.store.note(note_id)["postit_display_mode"], "normal")
        self.assertFalse(window.memo.isHidden())
        self.assertGreaterEqual(window.width(), 400)
        self.assertGreaterEqual(window.height(), 280)
        window.close_silently()
        self.app.processEvents()

    def test_deadline_is_visible_in_all_editors_and_toma_alert(self):
        note_id = self.store.create_note("출시", "릴리스 확인")
        due = (datetime.now() + timedelta(days=2)).strftime(DATETIME_FMT)
        self.store.set_deadline(note_id, due, "정식 출시", True)
        self.store.update_note(note_id, postit=True, postit_visible=True, postit_startup=True)
        panel = AlertNotesPanel(self.store)
        panel.select_note(note_id)
        self.app.processEvents()
        expected = deadline_badge_text(self.store.note(note_id))
        self.assertEqual(panel.editor.deadline_badge.text(), expected)
        self.assertIn(" : 정식 출시", expected)
        postit = panel.postits[note_id]
        self.assertEqual(postit.deadline_badge.text(), expected)
        panel.open_standalone_note(note_id)
        self.app.processEvents()
        self.assertEqual(panel.standalone_window.editor.deadline_badge.text(), expected)
        row = self.store.conn.execute(
            "SELECT reminders.*, notes.title note_title, notes.content note_content, '' repeat_summary "
            "FROM reminders JOIN notes ON notes.id=reminders.note_id "
            "WHERE reminders.note_id=? AND reminders.occurrence_kind='deadline'",
            (note_id,),
        ).fetchone()
        dialog = TomaPetAlertDialog(row, False)
        badges = dialog.findChildren(type(panel.editor.deadline_badge), "deadlineBadge")
        self.assertTrue(any("D-Day 알림" in badge.text() for badge in badges))
        dialog.close()
        dialog.deleteLater()
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        self.app.processEvents()

    def test_saved_checklist_prefix_and_graphics_sync_across_all_editors(self):
        content = (
            '<html><body><p><span style=" color:#c026d3;">'
            '☑ <a href="https://example.com" style=" color:#2563eb;">'
            '저장된 링크</a></span></p></body></html>'
        )
        note_id = self.store.create_note("기존 체크리스트", content)
        self.store.update_note(note_id, postit=True, postit_visible=True, postit_startup=True)
        panel = AlertNotesPanel(self.store)
        panel.select_note(note_id)
        panel.open_standalone_note(note_id)
        self.app.processEvents()
        postit = panel.postits[note_id]
        editors = (
            panel.editor.content_edit,
            postit.memo,
            panel.standalone_window.editor.content_edit,
        )
        self.assertTrue(all(editor.document() is editors[0].document() for editor in editors))
        self.assertTrue(all(editor.toPlainText().startswith(CHECKED_PREFIX) for editor in editors))
        self.assertTrue(all(
            any(selection.format.fontStrikeOut() for selection in editor.extraSelections())
            for editor in editors
        ))

        postit.memo._toggle_check_state(postit.memo.document().firstBlock())
        self.app.processEvents()
        self.assertTrue(all(editor.toPlainText().startswith(UNCHECKED_PREFIX) for editor in editors))
        self.assertTrue(all(
            not any(selection.format.fontStrikeOut() for selection in editor.extraSelections())
            for editor in editors
        ))
        link_cursor = QTextCursor(editors[0].document().firstBlock())
        link_cursor.setPosition(editors[0].document().firstBlock().position() + 3)
        self.assertEqual(link_cursor.charFormat().anchorHref(), "https://example.com")
        self.assertEqual(link_cursor.charFormat().foreground().color(), QColor("#2563eb"))

        postit.flush_pending_save()
        self.app.processEvents()
        saved = str(self.store.note(note_id)["content"])
        self.assertTrue(plain_text_from_content(saved).startswith(UNCHECKED_PREFIX))
        self.assertIn("☐ ", saved)
        self.assertNotIn("☑ ", saved)
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        self.app.processEvents()

    def test_checklist_toolbar_is_shared_and_quick_alert_is_registered(self):
        note_id = self.store.create_note("공통 편집", "한 줄")
        self.store.update_note(note_id, postit=True, postit_visible=True, postit_startup=True)
        panel = AlertNotesPanel(self.store)
        panel.select_note(note_id)
        panel.editor.content_edit.selectAll()
        panel.editor.format_toolbar.checklist_button.click()
        self.app.processEvents()
        postit = panel.postits[note_id]
        self.assertTrue(panel.editor.format_toolbar.checklist_button.isChecked())
        self.assertTrue(postit.memo.toPlainText().startswith(UNCHECKED_PREFIX))
        postit.memo.moveCursor(QTextCursor.MoveOperation.Start)
        postit._sync_format_buttons(postit.memo.currentCharFormat())
        self.assertTrue(postit.format_bar.checklist_button.isChecked())
        panel._set_postit_quick_reminder(note_id, 10)
        row = self.store.conn.execute(
            "SELECT * FROM reminders WHERE note_id=? AND occurrence_kind='regular'",
            (note_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIn("한 줄", row["memo"])
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
