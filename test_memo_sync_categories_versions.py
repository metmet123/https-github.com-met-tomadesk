from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from alert_notes.block_link import block_url, parse_block_url
from alert_notes.memo_archive import export_memo_archive, restore_memo_archive
from alert_notes.note_clone_service import NoteCloneService
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.sync_identity import valid_sync_id
from alert_notes.panel import AlertNotesPanel


class MemoSyncFoundationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = NoteReminderStore(self.root / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_uuid_revision_category_inheritance_and_tombstones(self):
        parent = self.store.create_note("부모")
        note = self.store.note(parent)
        self.assertTrue(valid_sync_id(note["sync_id"]))
        revision = int(note["revision"])
        category = self.store.categories()[0]
        self.store.set_note_category(parent, int(category["id"]))
        self.assertEqual(int(self.store.note(parent)["revision"]), revision + 1)
        child = self.store.create_child_note(parent, "하위")
        self.assertEqual(self.store.note(child)["category_id"], category["id"])
        self.store.set_note_category(child, None)
        self.assertIsNone(self.store.note(child)["category_id"])
        self.store.delete_category(int(category["id"]))
        self.assertIsNone(self.store.note(parent)["category_id"])
        tombstone = self.store.conn.execute(
            "SELECT * FROM sync_tombstones WHERE entity_type='memo_category' AND sync_id=?",
            (category["sync_id"],),
        ).fetchone()
        self.assertIsNotNone(tombstone)

    def test_legacy_database_migrates_once_with_backup_and_stable_uuid(self):
        self.store.close()
        legacy = self.root / "legacy.db"
        conn = sqlite3.connect(legacy)
        conn.executescript(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL,
                postit INTEGER NOT NULL DEFAULT 0, postit_visible INTEGER NOT NULL DEFAULT 0,
                postit_startup INTEGER NOT NULL DEFAULT 0, postit_display_mode TEXT NOT NULL DEFAULT 'normal',
                always_on_top INTEGER NOT NULL DEFAULT 1, color TEXT NOT NULL DEFAULT 'vanilla',
                opacity INTEGER NOT NULL DEFAULT 100, background_transparency INTEGER NOT NULL DEFAULT 0,
                input_locked INTEGER NOT NULL DEFAULT 0, d_day_at TEXT NOT NULL DEFAULT '',
                d_day_label TEXT NOT NULL DEFAULT '', d_day_alert INTEGER NOT NULL DEFAULT 0,
                d_day_done_at TEXT NOT NULL DEFAULT '', monthly_rule TEXT NOT NULL DEFAULT '',
                monthly_shown_for TEXT NOT NULL DEFAULT '', hotkey TEXT NOT NULL DEFAULT '',
                hotkey_action TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, deleted_at TEXT NOT NULL DEFAULT '', parent_id INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0, embedded INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO notes(title,content,created_at,updated_at) VALUES('기존','본문','202609010900','202609010900');
            """
        )
        conn.commit()
        conn.close()
        migrated = NoteReminderStore(legacy, "새 메모")
        try:
            self.assertIsNotNone(migrated.upgrade_backup_path)
            self.assertTrue(migrated.upgrade_backup_path.exists())
            sync_id = str(migrated.note(1)["sync_id"])
            self.assertTrue(valid_sync_id(sync_id))
        finally:
            migrated.close()
        reopened = NoteReminderStore(legacy, "새 메모")
        try:
            self.assertIsNone(reopened.upgrade_backup_path)
            self.assertEqual(reopened.note(1)["sync_id"], sync_id)
        finally:
            reopened.close()
        self.store = NoteReminderStore(self.root / "notes.db", "새 메모")

    def test_install_id_is_stable_and_independent_databases_do_not_collide(self):
        device = self.store.device_id
        note_id = self.store.create_note("첫 메모")
        sync_id = self.store.note(note_id)["sync_id"]
        self.store.close()
        self.store = NoteReminderStore(self.root / "notes.db", "새 메모")
        self.assertEqual(self.store.device_id, device)
        self.assertEqual(self.store.note(note_id)["sync_id"], sync_id)
        other = NoteReminderStore(self.root / "other.db", "새 메모")
        try:
            other_id = other.create_note("다른 DB")
            self.assertEqual(other_id, note_id)
            self.assertNotEqual(other.note(other_id)["sync_id"], sync_id)
            self.assertNotEqual(other.device_id, device)
        finally:
            other.close()

    def test_clone_gets_new_note_attachment_and_annotation_uuids(self):
        note_id = self.store.create_note("원본", "<p>본문</p>")
        attachment_id = self.store.add_attachment(note_id, "image/png", "YWJj", 2, 3)
        annotation_id = self.store.memo_data.add_annotation(note_id, "설명", quote="본문")
        snapshot = NoteCloneService(self.store).snapshot([note_id])
        batch = NoteCloneService(self.store).clone(snapshot)
        clone_id = batch["roots"][0]
        self.assertNotEqual(self.store.note(note_id)["sync_id"], self.store.note(clone_id)["sync_id"])
        self.assertNotEqual(
            self.store.attachment(attachment_id)["sync_id"], batch["attachments"][0]["sync_id"],
        )
        self.assertNotEqual(
            self.store.memo_data.annotation(annotation_id)["sync_id"], batch["annotations"][0]["sync_id"],
        )

    def test_v2_archive_preserves_uuid_and_merge_keeps_conflict_copy(self):
        note_id = self.store.create_note("백업", "본문")
        original = str(self.store.note(note_id)["sync_id"])
        path = export_memo_archive(self.store, self.root / "all.tomamemo")
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["version"], 2)
        self.assertIn("parent_sync_id", manifest["tables"]["notes"][0])
        restore_memo_archive(self.store, path, "merge")
        rows = list(self.store.conn.execute("SELECT * FROM notes ORDER BY id"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["conflict_of_sync_id"], original)
        self.assertNotEqual(rows[1]["sync_id"], original)

    def test_v2_and_v1_block_links_and_backlinks_resolve(self):
        target = self.store.create_note("대상")
        source = self.store.create_note("출처")
        sync_id = str(self.store.note(target)["sync_id"])
        block_id = "5e3cdd78-8eb5-44cb-85e6-b0a73cc64de7"
        self.assertEqual(parse_block_url(block_url(target, block_id)), (target, block_id))
        self.assertEqual(parse_block_url(block_url(sync_id, block_id)), (sync_id, block_id))
        self.store.update_note(source, content=f'<a href="{block_url(sync_id, block_id)}">링크</a>')
        links = self.store.memo_data.backlinks_for(sync_id)
        self.assertEqual(links[0]["source_memo_id"], source)
        self.assertEqual(links[0]["target_block_id"], block_id)

    def test_annotations_templates_and_version_retention_restore(self):
        note_id = self.store.create_note("버전", "처음")
        annotation = self.store.memo_data.add_annotation(note_id, "주석", quote="처음")
        self.assertEqual(self.store.memo_data.resolve_annotation(annotation, "처음"), "resolved")
        self.assertEqual(self.store.memo_data.resolve_annotation(annotation, "처음 처음"), "needs_review")
        template = self.store.memo_data.save_template(
            "회의", "meeting", {"version": 1, "kind": "blocks", "html": "<p>회의</p>", "text": "회의", "blocks": []},
        )
        self.assertTrue(valid_sync_id(self.store.memo_data.templates()[0]["sync_id"]))
        for index in range(35):
            self.store.update_note(note_id, content=f"내용 {index}")
            self.store.memo_data.create_version(note_id)
        self.assertEqual(len([row for row in self.store.memo_data.versions(note_id) if row["kind"] == "auto"]), 30)
        self.store.memo_data.create_version(note_id, kind="manual", important=True, force=True)
        selected = self.store.memo_data.versions(note_id)[-1]
        expected = json.loads(selected["payload_json"])["note"]["content"]
        self.store.memo_data.restore_version(int(selected["id"]))
        self.assertEqual(self.store.note(note_id)["content"], expected)
        self.assertTrue(any(row["kind"] == "before_restore" for row in self.store.memo_data.versions(note_id)))

    def test_extended_archive_roundtrip_keeps_device_and_related_data(self):
        note_id = self.store.create_note("연결 데이터", "본문")
        category_id = self.store.create_category("개인", "#112233")
        self.store.set_note_category(note_id, category_id)
        self.store.memo_data.add_annotation(note_id, "주석")
        self.store.memo_data.save_template(
            "기본", "base", {"version": 1, "kind": "blocks", "html": "<p>본문</p>", "text": "본문", "blocks": []},
        )
        self.store.memo_data.create_version(note_id, kind="manual", important=True, force=True)
        device = self.store.device_id
        sync_id = self.store.note(note_id)["sync_id"]
        path = export_memo_archive(self.store, self.root / "extended.tomamemo")
        self.store.update_note(note_id, title="바뀜")
        restore_memo_archive(self.store, path, "replace")
        restored = self.store.note_by_sync_id(sync_id)
        self.assertEqual(restored["title"], "연결 데이터")
        self.assertEqual(self.store.device_id, device)
        self.assertEqual(len(self.store.memo_data.annotations(int(restored["id"]))), 1)
        self.assertEqual(len(self.store.memo_data.templates()), 1)
        self.assertEqual(len(self.store.memo_data.versions(int(restored["id"]))), 1)

    def test_version_restore_failure_rolls_back_snapshot_and_note(self):
        note_id = self.store.create_note("롤백", "이전")
        version_id = self.store.memo_data.create_version(note_id, kind="manual", force=True)
        self.store.update_note(note_id, content="현재")
        count = len(self.store.memo_data.versions(note_id))
        with patch.object(self.store, "_touch_note", side_effect=RuntimeError("실패")):
            with self.assertRaises(RuntimeError):
                self.store.memo_data.restore_version(version_id)
        self.assertEqual(self.store.note(note_id)["content"], "현재")
        self.assertEqual(len(self.store.memo_data.versions(note_id)), count)

    def test_version_restore_restores_attachment_and_rewrites_local_reference(self):
        note_id = self.store.create_note("첨부 복원", "")
        attachment_id = self.store.add_attachment(note_id, "image/png", "YWJj", 2, 3)
        attachment_sync_id = str(self.store.attachment(attachment_id)["sync_id"])
        self.store.update_note(
            note_id,
            content=f'<img src="toma-note-image://attachment/{attachment_id}" />',
        )
        version_id = self.store.memo_data.create_version(note_id, kind="manual", force=True)
        self.store.delete_attachment(attachment_id)
        self.store.update_note(note_id, content="첨부 없음")

        self.store.memo_data.restore_version(version_id)

        restored = self.store.note_attachments(note_id)
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["sync_id"], attachment_sync_id)
        self.assertIn(
            f'toma-note-image://attachment/{restored[0]["id"]}',
            self.store.note(note_id)["content"],
        )
        self.assertIsNone(self.store.conn.execute(
            "SELECT 1 FROM sync_tombstones WHERE entity_type='attachment' AND sync_id=?",
            (attachment_sync_id,),
        ).fetchone())


class MemoCategoryUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_editor_chip_filter_group_and_narrow_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            note_id = store.create_note("분류 메모", "내용과 일정 설명")
            category_id = int(store.categories()[0]["id"])
            store.set_note_category(note_id, category_id)
            panel = AlertNotesPanel(store)
            try:
                panel.resize(900, 720)
                panel.show()
                self.app.processEvents()
                panel.show_note(note_id)
                self.assertEqual(panel.editor.category_button.height(), 28)
                # 제목 옆 칩: 이름 ▾ (좁으면 말줄임), 전체 이름은 툴팁.
                self.assertTrue(panel.editor.category_button.text().endswith("▾"))
                self.assertIn(store.category(category_id)["name"], panel.editor.category_button.toolTip())
                self.assertLessEqual(panel.editor.category_button.width(), panel.editor.CATEGORY_CHIP_MAX_WIDTH)
                self.assertEqual(panel.list_panel.HEADERS, ["", "제목", "카테고리", "수정일"])
                panel.list_panel.view_combo.setCurrentIndex(
                    panel.list_panel.view_combo.findData("category")
                )
                self.app.processEvents()
                group = panel.list_panel.table.topLevelItem(0)
                self.assertIsNone(group.data(0, Qt.ItemDataRole.UserRole))
                self.assertGreater(group.childCount(), 0)
                self.assertFalse(panel.list_panel.table.dragEnabled())
                panel.list_panel.resize(430, 600)
                self.app.processEvents()
                # Both title filters now share this row. Narrow views expose
                # view/sort through More instead of squeezing the search field.
                self.assertTrue(panel.list_panel._controls_in_more)
                self.assertFalse(panel.list_panel.view_combo.isVisible())
                self.assertFalse(panel.list_panel.sort_combo.isVisible())
                self.assertTrue(panel.list_panel.more_categories_button.isVisible())
                self.assertGreaterEqual(panel.list_panel.search.width(), 120)
                panel.list_panel._set_category_filter(category_id)
                store.delete_category(category_id)
                panel.list_panel.refresh_category_filters()
                self.assertIsNone(panel.list_panel.category_filter_id)
                self.assertEqual(store.setting(panel.list_panel.FILTER_SETTING, "missing"), "")
            finally:
                panel.shutdown()
                panel.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
