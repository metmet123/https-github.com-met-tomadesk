import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QInputDialog

from alert_notes.editor import MemoEditor
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.version_dialog import (
    VERSION_ID_ROLE, VersionHistoryDialog, local_version_datetime,
    version_day_label, version_kind_label,
)
from qt_test_support import close_alert_panel, destroy_widget


class StageERemediationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "stage_e.db", "새 메모")
        self.note_id = self.store.create_note("대상", "첫 줄\n둘째 줄")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_version_labels_use_local_time_korean_kinds_and_day_groups(self):
        service = self.store.memo_data
        version_id = service.create_version(self.note_id, kind="session_start", force=True)
        now = datetime.now(timezone.utc)
        self.store.conn.execute(
            "UPDATE memo_versions SET created_at_utc=? WHERE id=?",
            ((now - timedelta(days=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z"), version_id),
        )
        self.store.conn.commit()
        dialog = VersionHistoryDialog(service, self.note_id)
        dialog.show()
        self.app.processEvents()
        try:
            labels = [dialog.list.item(index).text() for index in range(dialog.list.count())]
            self.assertIn("어제", labels)
            self.assertTrue(any("편집 시작 전" in label for label in labels))
            self.assertFalse(any("session_start" in label or "T" in label for label in labels))
            version_rows = [
                dialog.list.item(index) for index in range(dialog.list.count())
                if dialog.list.item(index).data(VERSION_ID_ROLE) is not None
            ]
            self.assertRegex(version_rows[0].text(), r"\d{2}:\d{2} · 편집 시작 전")
        finally:
            destroy_widget(dialog, self.app)

    def test_version_helpers_cover_today_yesterday_and_unknown_kind(self):
        local = local_version_datetime("2026-09-15T05:39:53.196Z")
        self.assertIsNotNone(local.tzinfo)
        now = datetime.now().astimezone()
        self.assertEqual(version_day_label(now, now), "오늘")
        self.assertEqual(version_day_label(now - timedelta(days=1), now), "어제")
        self.assertEqual(version_kind_label("manual"), "직접 저장")
        self.assertEqual(version_kind_label("future_kind"), "future_kind")

    def test_version_diff_compares_display_plain_text_not_html(self):
        self.store.update_note(self.note_id, content="<html><body><p>첫 줄</p><p>둘째 줄</p></body></html>")
        version_id = self.store.memo_data.create_version(self.note_id, kind="manual", force=True)
        self.store.update_note(self.note_id, content="<html><body><p>첫 줄</p><p>바뀐 줄</p></body></html>")
        diff = self.store.memo_data.version_diff(version_id)
        self.assertIn("-둘째 줄", diff)
        self.assertIn("+바뀐 줄", diff)
        self.assertNotIn("<p>", diff)

    def test_editor_shows_backlink_count_and_annotation_ranges(self):
        target = self.store.note(self.note_id)
        self.store.create_note("연결한 메모", f"toma-note://v2/{target['sync_id']}")
        annotation_id = self.store.memo_data.add_annotation(
            self.note_id, "확인할 부분", start_offset=0, end_offset=2, quote="첫 ",
        )
        editor = MemoEditor(self.store)
        editor.show()
        editor.set_note(self.store.note(self.note_id))
        self.app.processEvents()
        try:
            self.assertFalse(editor.backlink_button.isVisible())
            editor.more_menu.open_at(editor.property_chips.more_button)
            self.assertTrue(editor.more_menu.action_buttons["backlinks"].isEnabled())
            editor.more_menu.close()
            self.assertEqual(editor.backlink_button.text(), "🔗 1")
            self.assertEqual(editor.annotation_menu_button.text(), "주석 1")
            self.assertEqual(len(editor.content_edit._annotation_selections()), 1)
            self.assertEqual(editor.content_edit.annotation_at_position(1)["id"], annotation_id)
        finally:
            editor.shutdown()
            destroy_widget(editor, self.app)

    def test_annotation_add_undo_redo_uses_document_shortcut_route(self):
        editor = MemoEditor(self.store)
        editor.show()
        editor.set_note(self.store.note(self.note_id))
        cursor = editor.content_edit.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
        editor.content_edit.setTextCursor(cursor)
        with patch.object(QInputDialog, "getMultiLineText", return_value=("통합 실행 취소", True)):
            editor._add_annotation()
        try:
            self.assertEqual(len(self.store.memo_data.annotations(self.note_id)), 1)
            self.assertTrue(editor.content_edit.external_undo_handler())
            self.assertEqual(self.store.memo_data.annotations(self.note_id), [])
            self.assertTrue(editor.content_edit.external_redo_handler())
            self.assertEqual(len(self.store.memo_data.annotations(self.note_id)), 1)
        finally:
            editor.shutdown()
            destroy_widget(editor, self.app)

    def test_edit_and_list_statuses_do_not_duplicate_each_other(self):
        panel = AlertNotesPanel(self.store)
        panel.show()
        self.app.processEvents()
        try:
            list_before = panel.list_panel.action_status.fullText()
            panel._editor_status("카테고리를 저장했습니다.", "success")
            self.assertIn("카테고리를 저장했습니다.", panel.editor.saved_status.text())
            self.assertEqual(panel.list_panel.action_status.fullText(), list_before)
            editor_before = panel.editor.saved_status.text()
            panel._list_status("2개 메모의 카테고리를 저장했습니다.", "success")
            self.assertIn("2개 메모", panel.list_panel.action_status.fullText())
            self.assertEqual(panel.editor.saved_status.text(), editor_before)
            self.assertNotIn("2개 메모", panel.status_label.text())
        finally:
            close_alert_panel(panel, self.app)

    def test_relations_group_exposes_template_save_entry(self):
        editor = MemoEditor(self.store)
        try:
            self.assertEqual(editor.relations_toggle.text(), "기록과 연결 ▸")
            self.assertEqual(editor.save_template_button.text(), "선택을 템플릿으로 저장")
        finally:
            editor.shutdown()
            destroy_widget(editor, self.app)


if __name__ == "__main__":
    unittest.main()
