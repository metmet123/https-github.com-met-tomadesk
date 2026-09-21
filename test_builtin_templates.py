"""Shipped memo templates must coexist with personal templates without DB migration."""

import json
import os
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import QApplication

from alert_notes.builtin_templates import (
    DATE_FORMAT_SETTING, TIME_FORMAT_SETTING, builtin_payload, fill_template_payload,
    format_template_date, format_template_time, selected_template_formats,
)
from alert_notes.rich_memo_edit import RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.template_dialog import TemplateManagerDialog
from qt_test_support import destroy_widget
from ui_theme import scaled_stylesheet


class BuiltinTemplatesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_nine_builtins_do_not_create_database_rows(self):
        rows = self.store.memo_data.available_templates()
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(row["id"] < 0 for row in rows))
        self.assertEqual(self.store.memo_data.templates(), [])
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM memo_templates").fetchone()[0], 0)

    def test_personal_templates_remain_after_builtin_rows(self):
        personal_id = self.store.memo_data.save_template("내 양식", "my", builtin_payload(-1))
        self.assertEqual(len(self.store.memo_data.templates()), 1)
        self.assertEqual(self.store.memo_data.available_templates()[-1]["id"], personal_id)

    def test_tokens_only_change_text_not_html_attributes(self):
        payload = {"html": '<p data-x="{{title}}">{{title}} &amp; {{unknown}}</p>',
                   "text": "{{title}} {{unknown}}"}
        result = fill_template_payload(payload, title='A&B <C>')
        self.assertIn('data-x="{{title}}"', result["html"])
        self.assertIn("A&amp;B &lt;C&gt; &amp; {{unknown}}", result["html"])
        self.assertEqual(result["text"], "A&B <C> {{unknown}}")

    def test_requested_date_formats_and_time_boundaries(self):
        moment = datetime(2026, 1, 5, 14, 30)
        self.assertEqual(format_template_date(moment, "iso"), "2026-01-05")
        self.assertEqual(format_template_date(moment, "dots"), "2026.1.5.")
        self.assertEqual(format_template_date(moment, "korean"), "2026년 1월 5일")
        self.assertEqual(format_template_time(moment, "24h"), "14:30")
        self.assertEqual(format_template_time(moment, "12h"), "오후 2:30")
        self.assertEqual(format_template_time(datetime(2026, 1, 5, 0, 5), "12h"), "오전 12:05")
        self.assertEqual(format_template_time(datetime(2026, 1, 5, 12, 0), "12h"), "오후 12:00")

    def test_settings_fall_back_without_overwriting_unknown_values(self):
        self.store.set_setting(DATE_FORMAT_SETTING, "future-date-code")
        self.store.set_setting(TIME_FORMAT_SETTING, "future-time-code")
        self.assertEqual(selected_template_formats(self.store), ("iso", "24h"))
        self.assertEqual(self.store.setting(DATE_FORMAT_SETTING), "future-date-code")

    def test_manager_preview_changes_before_settings_are_saved(self):
        dialog = TemplateManagerDialog(self.store.memo_data)
        try:
            self.assertTrue(dialog.date_buttons["iso"].isChecked())
            self.assertIn("예시 메모 제목", dialog.preview.toPlainText())
            dialog.date_buttons["dots"].click()
            dialog.time_format.setCurrentIndex(dialog.time_format.findData("12h"))
            self.assertEqual(self.store.setting(DATE_FORMAT_SETTING), "")
            self.assertEqual(self.store.setting(TIME_FORMAT_SETTING), "")
            self.assertRegex(dialog.preview.toPlainText(), r"\d{4}\.\d{1,2}\.\d{1,2}\.")
            self.assertRegex(dialog.preview.toPlainText(), r"(?:오전|오후) \d{1,2}:\d{2}")
            self.assertIn("저장하세요", dialog.format_status.text())
            dialog.save_format_button.click()
            self.assertEqual(self.store.setting(DATE_FORMAT_SETTING), "dots")
            self.assertEqual(self.store.setting(TIME_FORMAT_SETTING), "12h")
            self.assertIn("저장되었습니다", dialog.format_status.text())
        finally:
            destroy_widget(dialog, self.app)
        reopened = TemplateManagerDialog(self.store.memo_data)
        try:
            self.assertTrue(reopened.date_buttons["dots"].isChecked())
            self.assertEqual(reopened.time_format.currentData(), "12h")
        finally:
            destroy_widget(reopened, self.app)

    def test_manager_controls_fit_dialog_at_supported_scales(self):
        for scale in (1.0, 1.25, 1.5):
            with self.subTest(scale=scale):
                dialog = TemplateManagerDialog(self.store.memo_data)
                try:
                    dialog.setStyleSheet(scaled_stylesheet(scale))
                    dialog.show()
                    self.app.processEvents()
                    for widget in (dialog.list, dialog.preview, dialog.save_format_button):
                        bounds = QRect(widget.mapTo(dialog, QPoint()), widget.size())
                        self.assertTrue(dialog.rect().contains(bounds), (scale, widget.objectName(), bounds))
                finally:
                    destroy_widget(dialog, self.app)

    def test_saved_formats_apply_to_builtin_and_personal_only_when_inserted(self):
        self.store.set_setting(DATE_FORMAT_SETTING, "korean")
        self.store.set_setting(TIME_FORMAT_SETTING, "12h")
        personal_id = self.store.memo_data.save_template("개인", "mine", builtin_payload(-1))
        note_id = self.store.create_note("대상", "")
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        try:
            for template_id in (-1, personal_id):
                editor.clear()
                self.assertTrue(editor._insert_template(template_id))
                self.assertRegex(editor.toPlainText(), r"\d{4}년 \d{1,2}월 \d{1,2}일")
                self.assertRegex(editor.toPlainText(), r"(?:오전|오후) \d{1,2}:\d{2}")
                self.assertNotIn("{{date}}", editor.toPlainText())
            inserted = editor.toPlainText()
            self.store.set_setting(DATE_FORMAT_SETTING, "dots")
            self.assertEqual(editor.toPlainText(), inserted)
        finally:
            destroy_widget(editor, self.app)

    def test_insert_uses_live_title_and_toggle_children(self):
        note_id = self.store.create_note("저장된 제목", "")
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        editor.template_title_provider = lambda: "입력 중 제목"
        try:
            self.assertTrue(editor._insert_template(-1))
            self.assertIn("입력 중 제목", editor.toPlainText())
            self.assertNotIn("{{date}}", editor.toPlainText())
            block = editor.document().begin()
            while block.isValid() and not block.text().startswith("▾ "):
                block = block.next()
            self.assertTrue(block.isValid())
            self.assertEqual(block.blockFormat().indent(), 0)
            self.assertEqual(block.next().blockFormat().indent(), 1)
            editor.undo()
            self.assertNotIn("입력 중 제목", editor.toPlainText())
        finally:
            destroy_widget(editor, self.app)

    def test_builtin_checklist_markers_are_interactive_blocks(self):
        note_id = self.store.create_note("체크", "")
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        try:
            self.assertTrue(editor._insert_template(-2))
            blocks = []
            block = editor.document().begin()
            while block.isValid():
                if block.text().startswith("☐"):
                    blocks.append(block)
                block = block.next()
            self.assertGreaterEqual(len(blocks), 3)
            self.assertTrue(all(editor._is_checklist_block(block) for block in blocks))
        finally:
            destroy_widget(editor, self.app)

    def test_all_builtins_insert_and_saved_content_survives_reopen(self):
        note_id = self.store.create_note("원본 제목", "")
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        try:
            for template_id in range(-1, -10, -1):
                editor.clear()
                self.assertTrue(editor._insert_template(template_id), template_id)
                self.assertTrue(editor.toPlainText().strip(), template_id)
            html = editor.content()
            self.store.update_note(note_id, content=html)
            editor.set_content(str(self.store.note(note_id)["content"]))
            self.assertIn("수행 순서", editor.toPlainText())
            self.assertNotIn("{{date}}", editor.toPlainText())
        finally:
            destroy_widget(editor, self.app)

    def test_slash_menu_exposes_nine_templates_without_growing_unbounded(self):
        note_id = self.store.create_note("메뉴", "")
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        try:
            editor.setPlainText("/템플릿")
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            editor.setTextCursor(cursor)
            editor._refresh_insert_popup()
            self.assertEqual(len(editor.insert_popup_items()), 9)
            self.assertLessEqual(editor._insert_popup.height(), 8 * editor.INSERT_ROW_HEIGHT + 12)
            self.assertTrue(editor.run_selected_insert())
            self.assertIn("작성:", editor.toPlainText())
        finally:
            destroy_widget(editor, self.app)

    def test_manager_copies_builtin_without_mutating_source(self):
        dialog = TemplateManagerDialog(self.store.memo_data)
        try:
            dialog.list.setCurrentRow(0)
            self.assertFalse(bool(dialog.list.item(0).flags() & Qt.ItemFlag.ItemIsDragEnabled))
            with patch("alert_notes.template_dialog.QInputDialog.getText", side_effect=[
                ("복사한 양식", True), ("copied", True),
            ]):
                dialog._copy_builtin()
            rows = self.store.memo_data.available_templates()
            self.assertEqual(len(rows), 10)
            self.assertEqual(rows[0]["id"], -1)
            self.assertEqual(rows[-1]["name"], "복사한 양식")
            data = json.loads(rows[-1]["payload_json"])
            self.assertEqual(data["text"], builtin_payload(-1)["text"])
        finally:
            destroy_widget(dialog, self.app)


if __name__ == "__main__":
    unittest.main()
