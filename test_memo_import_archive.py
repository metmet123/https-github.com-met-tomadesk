import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import tempfile
import unittest
from pathlib import Path
import zipfile

from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication

from alert_notes.memo_archive import (
    export_memo_archive, inspect_memo_archive, restore_memo_archive,
)
from alert_notes.rich_memo_edit import RichMemoTextEdit, TOGGLE_OPEN_PREFIX
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.structured_import import (
    STRATEGY_PRESERVE, STRATEGY_TOP_TWO_TOGGLES, heading_levels_for_strategy,
    load_clipboard, load_import_file,
)


class StructuredImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.editor = RichMemoTextEdit()

    def tearDown(self):
        self.editor.close()
        self.editor.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_markdown_file_uses_present_top_two_heading_ranks_as_toggles(self):
        path = Path(self.temp.name) / "plan.md"
        path.write_text("# 큰 제목\n본문\n### 작은 제목\n- 항목\n#### 더 작은 제목\n끝", encoding="utf-8")
        document = load_import_file(path)
        levels = heading_levels_for_strategy(document.html, STRATEGY_TOP_TWO_TOGGLES)
        self.assertEqual(levels, {1, 3})
        self.editor.insert_structured_html(document.html, levels)
        blocks = []
        block = self.editor.document().begin()
        while block.isValid():
            blocks.append((block.text(), block.blockFormat().indent()))
            block = block.next()
        self.assertTrue(blocks[0][0].startswith(TOGGLE_OPEN_PREFIX))
        self.assertGreater(blocks[1][1], blocks[0][1])
        self.assertTrue(any(text.startswith(TOGGLE_OPEN_PREFIX) and "작은 제목" in text for text, _ in blocks))

    def test_preserve_strategy_keeps_headings_without_toggle_prefix(self):
        mime = QMimeData()
        mime.setData("text/markdown", b"# Title\n\n**bold**")
        document = load_clipboard(mime)
        self.assertEqual(heading_levels_for_strategy(document.html, STRATEGY_PRESERVE), set())
        self.editor.insert_structured_html(document.html, set())
        self.assertFalse(self.editor.toPlainText().startswith(TOGGLE_OPEN_PREFIX))
        self.assertIn("bold", self.editor.toPlainText())

    def test_external_html_removes_scripts_and_remote_images(self):
        mime = QMimeData()
        mime.setHtml('<h1>제목</h1><script>alert(1)</script><img src="https://bad/x.png"><p>본문</p>')
        document = load_clipboard(mime)
        self.assertNotIn("script", document.html.casefold())
        self.assertNotIn("https://bad", document.html)

    def test_html_details_becomes_a_native_toggle(self):
        mime = QMimeData()
        mime.setHtml("<details><summary>설명</summary><p>안쪽 내용</p></details><p>바깥</p>")
        document = load_clipboard(mime)
        self.editor.insert_structured_html(document.html, set())
        blocks = []
        block = self.editor.document().begin()
        while block.isValid():
            blocks.append((block.text(), block.blockFormat().indent()))
            block = block.next()
        toggle_index = next(index for index, value in enumerate(blocks) if "설명" in value[0])
        inside_index = next(index for index, value in enumerate(blocks) if "안쪽 내용" in value[0])
        outside_index = next(index for index, value in enumerate(blocks) if "바깥" in value[0])
        self.assertTrue(blocks[toggle_index][0].startswith(TOGGLE_OPEN_PREFIX))
        self.assertGreater(blocks[inside_index][1], blocks[toggle_index][1])
        self.assertEqual(blocks[outside_index][1], blocks[toggle_index][1])

    def test_structured_insert_is_one_undo_step(self):
        self.editor.setPlainText("앞")
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)
        self.editor.insert_structured_html("<h1>제목</h1><p>본문</p>", {1})
        self.assertIn("제목", self.editor.toPlainText())
        self.editor.undo()
        self.assertEqual(self.editor.toPlainText(), "앞")

    def test_structured_insert_into_empty_toggle_stays_inside_and_undoes_once(self):
        self.editor.textCursor().insertText("빈 토글")
        self.editor.make_toggle()
        self.editor._ensure_toggle_children()
        toggle = self.editor.document().begin()
        child = next(self.editor._toggle_children(toggle))
        cursor = QTextCursor(child)
        self.editor.setTextCursor(cursor)
        before = self.editor.toHtml()
        self.editor.insert_structured_html("<p>첫 문단</p><p>둘째 문단</p>", set())
        self.assertTrue(all(block.blockFormat().indent() > toggle.blockFormat().indent()
                            for block in self.editor._toggle_children(toggle)))
        self.editor.undo()
        self.assertEqual(self.editor.toHtml(), before)

    def test_document_file_drop_is_routed_to_structured_import(self):
        path = Path(self.temp.name) / "drop.md"
        path.write_text("# 드롭", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        received = []
        self.editor.structured_files_dropped.connect(received.extend)
        self.editor.insertFromMimeData(mime)
        self.assertEqual(received, [path])


class MemoArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = NoteReminderStore(self.root / "source.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _build_archive(self) -> tuple[Path, int, int, int]:
        parent = self.store.create_note("부모", "")
        child = self.store.create_child_note(parent, "페이지", embedded=True)
        attachment = self.store.add_attachment(child, "image/png", "aGVsbG8=", 10, 20)
        self.store.update_note(
            parent,
            content=(f'<html><body><a href="toma-note://{child}">페이지</a>'
                     f'<img src="toma-note-image://attachment/{attachment}"></body></html>'),
            pinned=True, color="mint", postit=True,
        )
        reminder = self.store.add_reminder(parent, "202609101200", "확인")
        trash = self.store.create_note("휴지통", "삭제됨")
        self.store.delete_note(trash)
        path = export_memo_archive(self.store, self.root / "all.tomamemo")
        return path, parent, child, reminder

    def test_round_trip_replace_preserves_memo_graph_and_non_memo_data(self):
        path, parent, child, _reminder = self._build_archive()
        preview = inspect_memo_archive(path)
        self.assertEqual((preview.active_notes, preview.trashed_notes, preview.attachments), (2, 1, 1))
        target = NoteReminderStore(self.root / "target.db", "새 메모")
        old = target.create_note("기존", "기존 내용")
        target.set_setting("keep", "yes")
        schedule_id = target.schedules.save_item({
            "title": "사용자 일정", "details": "", "item_type": "event", "note_id": old,
            "start_at": "202609110900", "end_at": "202609111000",
        })
        try:
            result = restore_memo_archive(target, path, "replace")
            self.assertEqual((result.notes, result.attachments, result.reminders), (3, 1, 1))
            restored = target.conn.execute("SELECT * FROM notes WHERE id=?", (parent,)).fetchone()
            self.assertIsNotNone(restored)
            self.assertEqual(restored["color"], "mint")
            self.assertIn(f"toma-note://{child}", restored["content"])
            self.assertEqual(target.setting("keep"), "yes")
            schedule = target.schedules.item(schedule_id)
            self.assertEqual(schedule["title"], "사용자 일정")
            self.assertIsNone(schedule["note_id"])
            self.assertEqual(
                target.conn.execute("SELECT COUNT(*) FROM schedule_items WHERE source_reminder_id IS NOT NULL").fetchone()[0],
                1,
            )
        finally:
            target.close()

    def test_merge_remaps_ids_links_attachments_and_titles(self):
        path, parent, child, _reminder = self._build_archive()
        before = self.store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        result = restore_memo_archive(self.store, path, "merge")
        self.assertEqual(result.notes, 3)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], before + 3)
        merged_parent = self.store.conn.execute(
            "SELECT * FROM notes WHERE title='부모 (2)'"
        ).fetchone()
        merged_child = self.store.conn.execute(
            "SELECT * FROM notes WHERE title='페이지 (2)'"
        ).fetchone()
        self.assertEqual(int(merged_child["parent_id"]), int(merged_parent["id"]))
        self.assertIn(f"toma-note://{int(merged_child['id'])}", merged_parent["content"])
        attachment_id = self.store.conn.execute(
            "SELECT id FROM note_attachments WHERE note_id=?", (int(merged_child["id"]),)
        ).fetchone()[0]
        self.assertIn(f"toma-note-image://attachment/{attachment_id}", merged_parent["content"])

    def test_tampered_attachment_is_rejected_before_database_change(self):
        path, *_ = self._build_archive()
        broken = self.root / "broken.tomamemo"
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(broken, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                target.writestr(info.filename, b"broken" if info.filename.startswith("attachments/") else data)
        count = self.store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "무결성"):
            restore_memo_archive(self.store, broken, "replace")
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], count)

    def test_merge_clears_only_conflicting_restored_hotkey(self):
        note_id = self.store.create_note("단축키 메모", "본문")
        self.store.update_note(note_id, hotkey="Ctrl+Alt+K")
        path = export_memo_archive(self.store, self.root / "hotkey.tomamemo")

        def reject(value, **_kwargs):
            if value == "Ctrl+Alt+K":
                raise ValueError("충돌")

        result = restore_memo_archive(self.store, path, "merge", reject)
        restored = self.store.conn.execute(
            "SELECT hotkey FROM notes WHERE title='단축키 메모 (2)'"
        ).fetchone()
        self.assertEqual(restored["hotkey"], "")
        self.assertEqual(result.cleared_hotkeys, 1)

    def test_projection_failure_rolls_back_replace(self):
        path, *_ = self._build_archive()
        target = NoteReminderStore(self.root / "rollback.db", "새 메모")
        original = target.create_note("남아야 함", "원본")
        original_migrate = target.schedules.migrate_legacy_reminders
        target.schedules.migrate_legacy_reminders = lambda: (_ for _ in ()).throw(RuntimeError("투영 실패"))
        try:
            with self.assertRaisesRegex(RuntimeError, "투영 실패"):
                restore_memo_archive(target, path, "replace")
            self.assertIsNotNone(target.note(original))
            self.assertEqual(target.note(original)["title"], "남아야 함")
        finally:
            target.schedules.migrate_legacy_reminders = original_migrate
            target.close()


if __name__ == "__main__":
    unittest.main()
