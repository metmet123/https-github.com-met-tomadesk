"""Phase 4 identity serialization checks, using only disposable Qt documents."""

import unittest
import base64
import json
import re
import tempfile
from pathlib import Path

from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.block_identity import (
    META_NAME, block_ids, is_pinned, load_ids, pinned_ids, stored_ids,
    stored_pins, with_ids, with_pins,
)
from alert_notes.block_link import block_url, parse_block_url
from alert_notes.note_clone_service import rewrite_cloned_content
from alert_notes.memo_archive import _rewrite_content, export_memo_archive, restore_memo_archive
from alert_notes.rich_memo_edit import RichMemoTextEdit
from alert_notes.editor import MemoEditor
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


class BlockIdentitySerializationTest(unittest.TestCase):
    def test_round_trip_preserves_text_html_and_ids(self):
        source = QTextDocument()
        source.setHtml(
            '<h2>제목</h2><p>본문 <a href="toma-note://42">📄 페이지</a></p>'
            '<p>▾ 토글</p><table><tr><td>칸</td></tr></table>'
        )
        source.setModified(False)
        ids = load_ids(source, source.toHtml())
        self.assertEqual(len(ids), source.blockCount())
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(source.isModified())
        text = source.toPlainText()
        html = with_ids(source.toHtml(), ids)
        self.assertEqual(stored_ids(html), ids)

        reopened = QTextDocument()
        reopened.setHtml(html)
        reopened.setModified(False)
        self.assertEqual(reopened.toPlainText(), text)
        self.assertEqual(load_ids(reopened, html), ids)
        self.assertFalse(reopened.isModified())
        self.assertEqual(reopened.firstBlock().blockFormat().headingLevel(), 2)
        self.assertIn("toma-note://42", reopened.toHtml())

    def test_legacy_load_does_not_mark_modified_and_duplicates_are_replaced(self):
        legacy = QTextDocument()
        legacy.setPlainText("first\nsecond\nthird")
        legacy.setModified(False)
        initial = load_ids(legacy, "first\nsecond\nthird")
        self.assertFalse(legacy.isModified())
        self.assertEqual(initial, block_ids(legacy))

        valid = with_ids(legacy.toHtml(), initial)
        token = base64.urlsafe_b64encode(
            json.dumps([initial[0], initial[0], initial[2]]).encode("ascii")
        ).decode("ascii").rstrip("=")
        duplicated = re.sub(
            rf'(name="{META_NAME}" content=")[^"]+',
            lambda match: match.group(1) + token, valid,
        )
        restored = QTextDocument()
        restored.setHtml(duplicated)
        ids = load_ids(restored, duplicated)
        self.assertEqual(ids[0], initial[0])
        self.assertNotEqual(ids[1], initial[0])
        self.assertEqual(ids[2], initial[2])

    def test_invalid_metadata_is_ignored(self):
        source = QTextDocument()
        source.setPlainText("content")
        html = with_ids(source.toHtml(), block_ids(source))
        corrupted = html.replace('content="', 'content="!')
        self.assertEqual(stored_ids(corrupted), [])
        again = QTextDocument()
        again.setHtml(corrupted)
        self.assertEqual(len(load_ids(again, corrupted)), again.blockCount())

    def test_editor_reopen_uses_meta_without_modifying_legacy_note(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            first = RichMemoTextEdit(store)
            second = RichMemoTextEdit(store)
            try:
                legacy = "<html><body><h2>제목</h2><p>본문</p></body></html>"
                first.set_content(legacy)
                self.assertFalse(first.document().isModified())
                self.assertEqual(first.document().property("tomaSourceContent"), legacy)
                ids = block_ids(first.document())
                saved = first.content()
                self.assertEqual(stored_ids(saved), ids)
                second.set_content(saved)
                self.assertEqual(block_ids(second.document()), ids)
                self.assertEqual(second.toPlainText(), first.toPlainText())
                self.assertFalse(second.document().isModified())
            finally:
                destroy_widget(second, app)
                destroy_widget(first, app)
                store.close()

    def test_independent_clone_gets_new_ids_without_changing_visible_text(self):
        source = QTextDocument()
        source.setHtml('<p>첫째</p><p>둘째</p>')
        original = with_ids(source.toHtml(), block_ids(source))
        cloned = rewrite_cloned_content(original, {}, {})
        self.assertEqual(len(stored_ids(cloned)), len(stored_ids(original)))
        self.assertTrue(set(stored_ids(cloned)).isdisjoint(stored_ids(original)))
        restored = QTextDocument()
        restored.setHtml(cloned)
        self.assertEqual(restored.toPlainText(), source.toPlainText())

    def test_block_move_keeps_ids_through_undo_and_redo(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            editor = RichMemoTextEdit(store)
            try:
                editor.set_content("one\ntwo\nthree")
                original = block_ids(editor.document())
                first = editor.document().firstBlock()
                third = editor.document().findBlockByNumber(2)
                self.assertTrue(editor.move_line(first.position(), third.position()))
                self.assertEqual(editor.toPlainText().splitlines(), ["two", "three", "one"])
                self.assertEqual(block_ids(editor.document()), [original[1], original[2], original[0]])
                editor.undo()
                self.assertEqual(block_ids(editor.document()), original)
                editor.redo()
                self.assertEqual(block_ids(editor.document()), [original[1], original[2], original[0]])
            finally:
                destroy_widget(editor, app)
                store.close()

    def test_split_and_heading_conversion_keep_surviving_identity(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            editor = RichMemoTextEdit(store)
            try:
                editor.set_content("alpha beta")
                original = block_ids(editor.document())[0]
                cursor = editor.textCursor()
                cursor.setPosition(6)
                editor.setTextCursor(cursor)
                editor.insertPlainText("\n")
                split_ids = block_ids(editor.document())
                self.assertEqual(split_ids[0], original)
                self.assertEqual(len(split_ids), 2)
                self.assertNotEqual(split_ids[0], split_ids[1])
                editor.undo()
                self.assertEqual(block_ids(editor.document()), [original])
                editor.redo()
                self.assertEqual(block_ids(editor.document()), split_ids)
                editor.setTextCursor(QTextCursor(editor.document().firstBlock()))
                editor.apply_heading(2)
                self.assertEqual(block_ids(editor.document())[0], original)
            finally:
                destroy_widget(editor, app)
                store.close()

    def test_outline_is_keyboard_navigable_and_does_not_cover_body(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            note_id = store.create_note(
                "목차 검증", "<html><body><h1>첫 제목</h1><p>본문</p>"
                "<h2>둘째 제목</h2><p>▾ 토글</p></body></html>",
            )
            editor = MemoEditor(store)
            try:
                editor.resize(1050, 750)
                editor.show()
                editor.set_note(store.note(note_id))
                app.processEvents()
                editor.outline_button.click()
                app.processEvents()
                panel = editor.outline_panel
                self.assertTrue(panel.isVisible())
                self.assertEqual(len(panel._entries), 3)
                self.assertEqual(panel.tree.topLevelItemCount(), 1)
                self.assertLess(editor.content_edit.geometry().right(), panel.geometry().left())
                target = panel.tree.topLevelItem(0).child(0)
                panel.tree.setCurrentItem(target)
                panel.tree.setFocus()
                QTest.keyClick(panel.tree, Qt.Key.Key_Return)
                self.assertEqual(editor.content_edit.textCursor().block().text(), "둘째 제목")
                editor.resize(600, 750)
                app.processEvents()
                self.assertFalse(panel.isVisible())
                self.assertFalse(editor.outline_button.isEnabled())
            finally:
                destroy_widget(editor, app)
                store.close()

    def test_versioned_block_url_is_distinct_from_legacy_note_url(self):
        source = QTextDocument()
        source.setPlainText("one")
        identity = block_ids(source)[0]
        url = block_url(42, identity)
        self.assertEqual(parse_block_url(url), (42, identity))
        self.assertIsNone(parse_block_url("toma-note://42"))
        self.assertIsNone(parse_block_url(f"toma-block://v1/0/{identity}"))
        self.assertIsNone(parse_block_url(f"toma-block://v2/42/{identity}"))

    def test_archive_restore_remaps_block_link_note_without_changing_block_id(self):
        document = QTextDocument()
        document.setPlainText("target")
        identity = block_ids(document)[0]
        original = block_url(42, identity)
        rewritten = _rewrite_content(
            f'<a href="{original}">🔗 target</a>', {42: 99}, {},
        )
        self.assertIn(block_url(99, identity), rewritten)
        self.assertNotIn(original, rewritten)

    def test_archive_merge_round_trip_keeps_block_ids_and_remaps_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = NoteReminderStore(root / "notes.db", "새 메모")
            try:
                target = QTextDocument()
                target.setPlainText("heading")
                identity = block_ids(target)[0]
                target_id = store.create_note("target", with_ids(target.toHtml(), [identity]))
                source_id = store.create_note(
                    "source", f'<html><body><p><a href="{block_url(target_id, identity)}">🔗 heading</a></p></body></html>',
                )
                archive = export_memo_archive(store, root / "block-links.tomamemo")
                restore_memo_archive(store, archive, "merge")
                merged_target = store.conn.execute("SELECT * FROM notes WHERE title='target (2)'").fetchone()
                merged_source = store.conn.execute("SELECT * FROM notes WHERE title='source (2)'").fetchone()
                self.assertIsNotNone(merged_target)
                self.assertIsNotNone(merged_source)
                self.assertNotEqual(int(merged_target["id"]), target_id)
                self.assertNotEqual(int(merged_source["id"]), source_id)
                self.assertEqual(stored_ids(str(merged_target["content"])), [identity])
                self.assertIn(block_url(int(merged_target["id"]), identity), str(merged_source["content"]))
            finally:
                store.close()

    def test_move_into_page_preserves_existing_target_ids_and_pins(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            target = QTextDocument()
            target.setPlainText("existing\nlast")
            target_ids = block_ids(target)
            target_html = with_pins(with_ids(target.toHtml(), target_ids), {target_ids[0]})
            page_id = store.create_note("target", target_html)
            editor = RichMemoTextEdit(store)
            try:
                editor.set_content("moved")
                moved_id = block_ids(editor.document())[0]
                editor.setTextCursor(QTextCursor(editor.document().firstBlock()))
                self.assertTrue(editor.toggle_selected_block_pins())
                self.assertTrue(editor._move_line_into_page([editor.document().firstBlock()], page_id))
                stored = str(store.note(page_id)["content"])
                self.assertEqual(stored_ids(stored)[:2], target_ids)
                self.assertEqual(stored_ids(stored)[-1], moved_id)
                self.assertIn(target_ids[0], stored_pins(stored))
                self.assertIn(moved_id, stored_pins(stored))
                reopened = QTextDocument()
                reopened.setHtml(stored)
                self.assertEqual(load_ids(reopened, stored)[:2], target_ids)
                self.assertIn("moved", reopened.toPlainText())
            finally:
                destroy_widget(editor, app)
                store.close()

    def test_pin_round_trip_move_undo_and_independent_clone(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            editor = RichMemoTextEdit(store)
            reopened = RichMemoTextEdit(store)
            try:
                editor.set_content("first\nsecond\nthird")
                identities = block_ids(editor.document())
                editor.setTextCursor(QTextCursor(editor.document().firstBlock()))
                self.assertTrue(editor.toggle_selected_block_pins())
                self.assertEqual(pinned_ids(editor.document()), {identities[0]})
                editor.undo()
                self.assertEqual(pinned_ids(editor.document()), set())
                editor.redo()
                self.assertEqual(pinned_ids(editor.document()), {identities[0]})
                saved = editor.content()
                self.assertEqual(stored_pins(saved), {identities[0]})
                reopened.set_content(saved)
                self.assertTrue(is_pinned(reopened.document().firstBlock()))
                self.assertFalse(reopened.document().isModified())
                self.assertEqual(stored_pins(rewrite_cloned_content(saved, {}, {})).intersection(
                    stored_pins(saved)), set())
                self.assertTrue(editor.move_line(
                    editor.document().firstBlock().position(),
                    editor.document().findBlockByNumber(2).position(),
                ))
                self.assertEqual(pinned_ids(editor.document()), {identities[0]})
                self.assertTrue(is_pinned(editor.document().lastBlock()))
                editor.undo()
                self.assertTrue(is_pinned(editor.document().firstBlock()))
            finally:
                destroy_widget(reopened, app)
                destroy_widget(editor, app)
                store.close()

    def test_pinned_plain_block_appears_in_outline_and_unlink_removes_pin(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            note_id = store.create_note("고정 검증", "첫 문단\n둘째 문단")
            editor = MemoEditor(store)
            try:
                editor.resize(1000, 720)
                editor.show()
                editor.set_note(store.note(note_id))
                body = editor.content_edit
                body.setTextCursor(QTextCursor(body.document().findBlockByNumber(1)))
                self.assertTrue(body.toggle_selected_block_pins())
                editor.outline_panel.refresh()
                self.assertEqual(len(editor.outline_panel._entries), 1)
                self.assertEqual(editor.outline_panel._entries[0].kind, "pinned")
                self.assertTrue(body.remove_linked_features([body.document().findBlockByNumber(1)]))
                self.assertFalse(is_pinned(body.document().findBlockByNumber(1)))
                body.undo()
                self.assertTrue(is_pinned(body.document().findBlockByNumber(1)))
            finally:
                destroy_widget(editor, app)
                store.close()

    def test_outline_copies_rich_block_link_and_opens_exact_target(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            target_id = store.create_note(
                "대상", "<html><body><h1>첫째</h1><h2>둘째</h2></body></html>",
            )
            source_id = store.create_note("출발", "링크를 붙일 자리")
            panel = AlertNotesPanel(store)
            try:
                panel.resize(1100, 760)
                panel.show()
                panel.show_note(target_id)
                app.processEvents()
                outline = panel.editor.outline_panel
                outline.refresh()
                target = outline.tree.topLevelItem(0).child(0)
                outline.tree.setCurrentItem(target)
                identity = target.data(0, Qt.ItemDataRole.UserRole)
                self.assertTrue(outline.copy_selected_link())
                self.assertIn(identity, stored_ids(str(store.note(target_id)["content"])))
                mime = QApplication.clipboard().mimeData()
                target_sync_id = str(store.note(target_id)["sync_id"])
                self.assertEqual(parse_block_url(mime.text()), (target_sync_id, identity))
                self.assertIn('href="toma-block://v2/', mime.html())
                saved = panel.editor.content_edit.content()
                store.update_note(target_id, content=saved)

                panel.show_note(source_id)
                body = panel.editor.content_edit
                body.setHtml(f'<p>{mime.html()}</p>')
                cursor = body.textCursor()
                cursor.setPosition(2)
                body.setTextCursor(cursor)
                self.assertTrue(body.open_current_link())
                self.assertEqual(panel.current_id, target_id)
                self.assertEqual(body.textCursor().block().text(), "둘째")
                panel.show_note(source_id)
                panel._open_block_link(target_id, block_ids(body.document())[0])
                self.assertEqual(panel.current_id, source_id)
            finally:
                destroy_widget(panel, app)
                store.close()

    def test_manual_unsaved_note_must_be_saved_before_copying_block_link(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
            note_id = store.create_note("manual", "<html><body><h1>원본</h1></body></html>")
            editor = MemoEditor(store)
            try:
                editor.set_auto_save_enabled(False)
                editor.resize(1000, 720)
                editor.show()
                editor.set_note(store.note(note_id))
                editor.content_edit.insertPlainText("변경")
                editor.outline_panel.refresh()
                editor.outline_panel.tree.setCurrentItem(editor.outline_panel.tree.topLevelItem(0))
                self.assertFalse(editor.outline_panel.copy_selected_link())
                self.assertEqual(stored_ids(str(store.note(note_id)["content"])), [])
            finally:
                destroy_widget(editor, app)
                store.close()


if __name__ == "__main__":
    unittest.main()
