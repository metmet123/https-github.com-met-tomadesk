import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QApplication

from alert_notes.block_identity import heading_folded_ids
from alert_notes.panel import AlertNotesPanel
from alert_notes.rich_memo_edit import RichMemoTextEdit, HEADING_STYLES, HEADING_FOLDED_PREFIX
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel


class MemoLatencyOptimizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.a = self.store.create_note("A", "<html><body><p>본문</p></body></html>")
        self.b = self.store.create_note("B", "둘")
        self.panel = AlertNotesPanel(self.store)
        self.panel.resize(1100, 800)
        self.panel.show()
        self.panel.select_note(self.a)
        self.app.processEvents()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_move_preserves_draft_selection_undo_and_avoids_unrelated_refresh(self):
        edit = self.panel.editor.content_edit
        cursor = edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(" 추가")
        edit.setTextCursor(cursor)
        self.panel.editor.save_timer.stop()
        before = (edit.toPlainText(), cursor.position(), edit.document().availableUndoSteps())
        self.panel.list_panel._item_for(self.a).setCheckState(0, Qt.CheckState.Checked)
        with patch.object(self.panel.editor, "set_note") as editor, \
                patch.object(self.panel.calendar, "refresh") as calendar, \
                patch.object(self.panel, "refresh") as refresh:
            self.panel.move_note(self.a, 0, 1)
            editor.assert_not_called()
            calendar.assert_not_called()
            refresh.assert_not_called()
        self.assertEqual(before, (edit.toPlainText(), edit.textCursor().position(), edit.document().availableUndoSteps()))
        self.assertIn(self.a, self.panel.list_panel.checked_ids())
        edit.undo()
        self.assertNotIn("추가", edit.toPlainText())

    def test_reorder_preserves_editor_and_failed_move_preserves_order(self):
        before = self.panel.editor.content_edit.document()
        with patch.object(self.panel.editor, "set_note") as reload:
            self.panel.reorder_siblings(0, [self.b, self.a])
            self.panel.move_note(self.a, self.a, 0)
            reload.assert_not_called()
        self.assertIs(before, self.panel.editor.content_edit.document())
        self.assertEqual([r["id"] for r in self.store.child_notes(0)], [self.b, self.a])

    def test_preview_reuses_content_but_invalidates_changed_body(self):
        from alert_notes.rich_text import display_plain_text_from_content
        with patch("alert_notes.memo_list.display_plain_text_from_content", wraps=display_plain_text_from_content) as parse:
            self.panel._refresh_list_filters()
            self.assertEqual(parse.call_count, 0)
            self.store.update_note(self.b, content="새로운 본문")
            self.panel._refresh_list_filters()
            self.assertEqual(parse.call_count, 1)
        self.assertEqual(self.panel.list_panel._preview_cache[self.b][1], "새로운 본문")

    def test_backlinks_reuse_parse_and_reflect_rename_delete_restore_and_rollback(self):
        service = self.store.memo_data
        target = str(self.store.note(self.a)["sync_id"])
        self.store.update_note(self.b, content=f"toma-note://{self.a}")
        self.assertEqual(len(service.backlinks_for(target)), 1)
        cached = service._backlink_targets[self.b]
        self.store.update_note(self.b, title="바뀐 제목")
        self.assertEqual(service.backlinks_for(target)[0]["source_title"], "바뀐 제목")
        self.assertIs(cached, service._backlink_targets[self.b])
        self.store.conn.execute("UPDATE notes SET deleted_at='deleted' WHERE id=?", (self.b,))
        self.assertEqual(service.backlinks_for(target), [])
        self.store.conn.rollback()
        self.assertEqual(len(service.backlinks_for(target)), 1)
        self.store.conn.execute("UPDATE notes SET content='' WHERE id=?", (self.b,))
        self.assertEqual(service.backlinks_for(target), [])
        self.store.conn.rollback()
        self.assertEqual(len(service.backlinks_for(target)), 1)

    def test_legacy_heading_fragment_matches_previous_cursor_rule(self):
        for prefix in ("", HEADING_FOLDED_PREFIX):
            for text in ("한글", "😀 제목", "", "e\u0301"):
                doc = QTextDocument()
                size, _, top, _ = HEADING_STYLES[2]
                doc.setHtml(f'<p style="margin-top:{top}px"><span style="font-size:{size}pt">{prefix}{text}</span></p>')
                block = doc.begin()
                cursor = QTextCursor(block)
                if block.text().startswith(HEADING_FOLDED_PREFIX):
                    cursor.setPosition(block.position() + len(HEADING_FOLDED_PREFIX))
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                expected = next((level for level, (points, _, margin, _) in HEADING_STYLES.items()
                                 if abs(cursor.charFormat().fontPointSize() - points) < .1
                                 and abs(block.blockFormat().topMargin() - margin) < .1), 0)
                self.assertEqual(RichMemoTextEdit.heading_level(block), expected, (prefix, text))

    def test_structure_refresh_does_not_reenter(self):
        edit = self.panel.editor.content_edit
        edit._structure_dirty = True
        with patch.object(edit, "_refresh_toggle_visibility", side_effect=edit._refresh_structure) as refresh:
            edit._refresh_structure()
        self.assertEqual(refresh.call_count, 1)

    def test_long_memo_load_scans_structure_once_and_keeps_folds(self):
        edit = self.panel.editor.content_edit
        body = "".join(f"<h2>제목 {i}</h2><p>본문 {i}</p>" for i in range(60))
        draft = self.store.create_note("긴 메모", f"<html><body>{body}</body></html>")
        self.panel.select_note(draft)
        edit._set_heading_folded(edit.document().begin(), True)
        target = self.store.create_note("접힌 긴 메모", edit.content())
        original = RichMemoTextEdit._refresh_toggle_visibility
        with patch.object(RichMemoTextEdit, "_refresh_toggle_visibility",
                          autospec=True, side_effect=original) as refresh:
            self.panel.select_note(target)
        # 줄마다 문서 전체를 다시 훑으면 긴 메모 열기가 수 초 걸린다.
        self.assertLessEqual(refresh.call_count, 2)
        document = edit.document()
        self.assertEqual(len(heading_folded_ids(document)), 1)
        self.assertFalse(document.begin().next().isVisible())
        self.assertTrue(document.begin().next().next().isVisible())
        self.assertEqual(document.availableUndoSteps(), 0)
        self.assertFalse(document.isModified())


if __name__ == "__main__":
    unittest.main()
