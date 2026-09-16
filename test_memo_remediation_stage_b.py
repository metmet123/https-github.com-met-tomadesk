from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QApplication

from alert_notes.block_identity import block_ids, stored_ids, with_ids
from alert_notes.link_rewrite import rewrite_internal_links
from alert_notes.memo_archive import export_memo_archive, restore_memo_archive
from alert_notes.memo_clipboard import page_sync_ids_from_html
from alert_notes.editor import MemoEditor
from alert_notes.note_clone_service import NoteCloneService
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore


class MemoRemediationStageBTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = NoteReminderStore(self.root / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_note_switch_does_not_shutdown_today_summary(self):
        notes = [self.store.create_note(f"메모 {index}", f"본문 {index}") for index in range(3)]
        panel = AlertNotesPanel(self.store)
        try:
            for note_id in notes:
                panel.show_note(note_id)
            self.store.update_note(notes[0], d_day_at="202701011200", d_day_label="마감")
            panel.summary.refresh()
            self.assertFalse(panel.summary._shutdown)
            self.assertTrue(panel.summary.date_label.text())
        finally:
            panel.shutdown()
            panel.close()

    def test_session_versions_keep_pre_edit_and_final_state_once(self):
        note_id = self.store.create_note("버전", "처음")
        panel = AlertNotesPanel(self.store)
        try:
            panel.show_note(note_id)
            values = panel.editor.values()
            values["content"] = "둘째"
            panel.save_editor_values(note_id, values, panel.editor)
            values = panel.editor.values()
            values["content"] = "셋째"
            panel.save_editor_values(note_id, values, panel.editor)
            starts = [row for row in self.store.memo_data.versions(note_id) if row["kind"] == "session_start"]
            self.assertEqual(len(starts), 1)
            self.assertEqual(self.store.memo_data.version_payload(int(starts[0]["id"]))["note"]["content"], "처음")
            panel._finish_version_session(flush=False)
            autos = [row for row in self.store.memo_data.versions(note_id) if row["kind"] == "auto"]
            self.assertEqual(len(autos), 1)
            self.assertEqual(self.store.memo_data.version_payload(int(autos[0]["id"]))["note"]["content"], "셋째")
        finally:
            panel.shutdown()
            panel.close()

    def test_unchanged_session_makes_no_version_and_retention_is_combined(self):
        note_id = self.store.create_note("버전", "처음")
        panel = AlertNotesPanel(self.store)
        try:
            panel.show_note(note_id)
            panel._finish_version_session(flush=False)
            self.assertEqual(self.store.memo_data.versions(note_id), [])
        finally:
            panel.shutdown()
            panel.close()
        for index in range(36):
            self.store.update_note(note_id, content=f"내용 {index}")
            self.store.memo_data.create_version(
                note_id, kind="session_start" if index % 2 else "auto", force=True,
            )
        automatic = [
            row for row in self.store.memo_data.versions(note_id)
            if row["kind"] in {"auto", "session_start"} and not row["important"]
        ]
        self.assertEqual(len(automatic), 30)

    def test_annotation_context_recovery_and_revision(self):
        note_id = self.store.create_note("주석", "")
        annotation_id = self.store.memo_data.add_annotation(
            note_id, "설명", start_offset=6, end_offset=10, quote="같음",
            context_before="왼쪽 ", context_after=" 오른쪽",
        )
        before = self.store.memo_data.annotation(annotation_id)
        self.assertEqual(
            self.store.memo_data.resolve_annotation(annotation_id, "앞 추가 왼쪽 같음 오른쪽 / 같음"),
            "resolved",
        )
        resolved = self.store.memo_data.annotation(annotation_id)
        self.assertEqual(resolved["start_offset"], 8)
        self.assertGreater(resolved["revision"], before["revision"])
        self.assertEqual(self.store.memo_data.resolve_annotation(annotation_id, "같음 / 같음"), "needs_review")
        self.assertEqual(self.store.memo_data.resolve_annotation(annotation_id, "사라짐"), "needs_review")

    def test_empty_annotation_boundary_uses_context(self):
        note_id = self.store.create_note("빈 문단", "")
        annotation_id = self.store.memo_data.add_annotation(
            note_id, "빈 곳", start_offset=2, end_offset=2, quote="",
            context_before="앞", context_after="뒤",
        )
        self.assertEqual(self.store.memo_data.resolve_annotation(annotation_id, "추가앞뒤"), "resolved")
        row = self.store.memo_data.annotation(annotation_id)
        self.assertEqual((row["start_offset"], row["end_offset"]), (3, 3))

    def test_editor_reopen_uses_block_id_to_disambiguate_annotation(self):
        original = QTextDocument()
        original.setPlainText("같음\n같음")
        identities = block_ids(original)
        note_id = self.store.create_note("블록 복구", with_ids(original.toHtml(), identities))
        annotation_id = self.store.memo_data.add_annotation(
            note_id, "둘째", block_id=identities[1], start_offset=3, end_offset=5, quote="같음",
        )
        changed = QTextDocument()
        changed.setPlainText("추가\n같음\n같음")
        changed_ids = ["12345678-1234-4abc-8def-1234567890ab", *identities]
        self.store.update_note(note_id, content=with_ids(changed.toHtml(), changed_ids))
        editor = MemoEditor(self.store)
        try:
            editor.set_note(self.store.note(note_id))
            row = self.store.memo_data.annotation(annotation_id)
            self.assertEqual(row["location_status"], "resolved")
            self.assertEqual((row["start_offset"], row["end_offset"]), (6, 8))
        finally:
            editor.shutdown()
            editor.close()

    def test_clone_remaps_v1_v2_note_and_block_links_inside_graph(self):
        target_doc = QTextDocument()
        target_doc.setPlainText("대상 블록")
        old_block = block_ids(target_doc)[0]
        target_id = self.store.create_note("대상", with_ids(target_doc.toHtml(), [old_block]))
        target_sync = str(self.store.note(target_id)["sync_id"])
        outside = self.store.create_note("외부", "")
        source_id = self.store.create_note(
            "출처",
            f'<a href="toma-note://v2/{target_sync}">📄 대상</a>'
            f'<a href="toma-block://v2/{target_sync}/{old_block}">🔗 블록</a>'
            f'<a href="toma-note://{outside}">🔗 외부</a>',
        )
        batch = NoteCloneService(self.store).clone(NoteCloneService(self.store).snapshot([source_id, target_id]))
        clone_source = self.store.note(batch["id_map"][source_id])
        clone_target = self.store.note(batch["id_map"][target_id])
        new_block = stored_ids(str(clone_target["content"]))[0]
        self.assertIn(f'toma-note://v2/{clone_target["sync_id"]}', clone_source["content"])
        self.assertIn(f'toma-block://v2/{clone_target["sync_id"]}/{new_block}', clone_source["content"])
        self.assertIn(f"toma-note://{outside}", clone_source["content"])
        self.assertNotEqual(old_block, new_block)

    def test_archive_merge_remaps_v2_links_to_conflict_copy(self):
        target = self.store.create_note("대상", "본문")
        target_sync = str(self.store.note(target)["sync_id"])
        source = self.store.create_note("출처", f'<a href="toma-note://v2/{target_sync}">🔗 대상</a>')
        archive = export_memo_archive(self.store, self.root / "links.tomamemo")
        restore_memo_archive(self.store, archive, "merge")
        merged_target = self.store.conn.execute("SELECT * FROM notes WHERE title='대상 (2)'").fetchone()
        merged_source = self.store.conn.execute("SELECT * FROM notes WHERE title='출처 (2)'").fetchone()
        self.assertIn(f'toma-note://v2/{merged_target["sync_id"]}', merged_source["content"])
        self.assertNotIn(f'toma-note://v2/{target_sync}', merged_source["content"])

    def test_v2_page_detection_and_generic_external_preservation(self):
        sync_id = "01234567-89ab-4cde-8fab-0123456789ab"
        html = f'<a href="toma-note://v2/{sync_id}">📄 페이지</a>'
        self.assertEqual(page_sync_ids_from_html(html), [sync_id])
        self.assertEqual(rewrite_internal_links(html, note_sync_ids={}), html)

    def test_template_validation_allows_plain_code_text_and_rejects_local_resources(self):
        valid = {
            "version": 1, "kind": "blocks", "html": "<p>C:\\work from PyQt6 QObject</p>",
            "text": "C:\\work from PyQt6 QObject", "blocks": [],
        }
        self.assertIsNotNone(self.store.memo_data.save_template("코드", "code", valid))
        for invalid in (
            {**valid, "html": '<img src="file:///C:/secret.png">'},
            {**valid, "unknown": True},
            {**valid, "attachments": [{"path": "C:/x.png", "data_base64": "AA=="}]},
            {**valid, "attachments": [{"unexpected": True, "data_base64": "AA=="}]},
        ):
            with self.assertRaises(ValueError):
                self.store.memo_data.save_template("거부", "reject", invalid)


if __name__ == "__main__":
    unittest.main()
