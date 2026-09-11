import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QKeyEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QApplication

from alert_notes.memo_clipboard import BLOCK_MIME, NOTES_MIME
from alert_notes.note_clone_service import NoteCloneService
from alert_notes.panel import AlertNotesPanel
from alert_notes.rich_memo_edit import LINK_MARK, PAGE_MARK, RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel, destroy_widget


def key(widget, code, modifiers):
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, code, modifiers))


class PhaseOneClipboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            if isinstance(widget, AlertNotesPanel):
                close_alert_panel(widget, self.app)
            else:
                destroy_widget(widget, self.app)
        self.store.close()
        self.temp.cleanup()

    def editor(self, note_id=None):
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        self.widgets.append(editor)
        return editor

    def test_orphan_internal_anchor_is_removed_but_marked_links_remain(self):
        target = self.store.create_note("대상", "")
        editor = self.editor()
        editor.set_content(
            '<html><body><p><a href="toma-note://%d">일반 본문</a></p>'
            '<p><a href="toma-note://%d">%s대상</a></p>'
            '<p><a href="toma-note://%d">%s대상</a></p></body></html>'
            % (target, target, PAGE_MARK, target, LINK_MARK)
        )
        first = QTextCursor(editor.document().begin())
        first.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        self.assertFalse(first.charFormat().isAnchor())
        page = editor.document().begin().next()
        link = page.next()
        self.assertEqual(editor.page_id_of_block(page), target)
        self.assertEqual(editor._valid_internal_link_at_position(link.position()), target)

    def test_internal_mime_keeps_external_html_text_and_block_metadata(self):
        editor = self.editor()
        editor.setPlainText("제목\n☐ 할 일\n⌗ code")
        editor.setTextCursor(QTextCursor(editor.document().begin()))
        editor.apply_heading1()
        selection = QTextCursor(editor.document())
        selection.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(selection)
        mime = editor.createMimeDataFromSelection()
        self.assertTrue(mime.hasFormat(BLOCK_MIME))
        self.assertTrue(mime.hasHtml())
        self.assertEqual(mime.text(), "제목\n☐ 할 일\n⌗ code")

        pasted = self.editor()
        pasted.insertFromMimeData(mime)
        self.assertEqual(pasted.toPlainText(), editor.toPlainText())
        self.assertEqual(pasted.heading_level(pasted.document().begin()), 1)

    def test_deep_clone_gets_new_ids_and_keeps_reference_links(self):
        outside = self.store.create_note("참조 대상", "")
        root = self.store.create_note("원본", "")
        child = self.store.create_child_note(root, "하위", embedded=True)
        grandchild = self.store.create_child_note(child, "하위의 하위", embedded=True)
        attachment = self.store.add_attachment(root, "image/png", "AA==", 1, 1)
        self.store.update_note(
            root,
            content=(
                f'<html><body><p><a href="toma-note://{child}">{PAGE_MARK}하위</a></p>'
                f'<p><a href="toma-note://{outside}">{LINK_MARK}참조 대상</a></p>'
                f'<p><img src="toma-note-image://attachment/{attachment}" /></p></body></html>'
            ),
            d_day_at="202701011200", d_day_label="마감", d_day_alert=True,
            monthly_rule='{"kind":"monthly"}', hotkey="Ctrl+Alt+K", pinned=True,
        )
        snapshot = NoteCloneService(self.store).snapshot([root])
        batch = NoteCloneService(self.store).clone(snapshot, rename_roots=True)
        mapping = batch["id_map"]
        self.assertEqual(set(mapping), {root, child, grandchild})
        self.assertTrue(all(old != new for old, new in mapping.items()))
        cloned = self.store.note(mapping[root])
        self.assertIn(f"toma-note://{mapping[child]}", cloned["content"])
        self.assertIn(f"toma-note://{outside}", cloned["content"])
        self.assertNotIn(f"attachment/{attachment}", cloned["content"])
        self.assertEqual(int(self.store.note(mapping[child])["parent_id"]), mapping[root])
        self.assertEqual(int(self.store.note(mapping[grandchild])["parent_id"]), mapping[child])
        self.assertEqual(cloned["d_day_at"], "")
        self.assertEqual(cloned["monthly_rule"], "")
        self.assertEqual(cloned["hotkey"], "")
        self.assertEqual(int(cloned["pinned"]), 0)

    def test_page_paste_undo_redo_moves_document_and_database_together(self):
        source_note = self.store.create_note("원본", "")
        page = self.store.create_child_note(source_note, "페이지", embedded=True)
        nested = self.store.create_child_note(page, "중첩", embedded=True)
        source = self.editor(source_note)
        source.set_content(
            f'<html><body><p><a href="toma-note://{page}">{PAGE_MARK}페이지</a></p></body></html>'
        )
        selection = QTextCursor(source.document())
        selection.select(QTextCursor.SelectionType.Document)
        source.setTextCursor(selection)
        mime = source.createMimeDataFromSelection()

        destination_note = self.store.create_note("대상", "")
        destination = self.editor(destination_note)
        destination.set_content("")
        destination.insertFromMimeData(mime)
        clones = self.store.child_notes(destination_note)
        self.assertEqual(len(clones), 1)
        cloned_page = int(clones[0]["id"])
        self.assertEqual(len(self.store.note_descendants(cloned_page)), 1)
        self.assertNotEqual(cloned_page, page)

        menu = destination.createStandardContextMenu()
        destination._wire_context_history_actions(menu)
        undo_action = next(action for action in menu.actions() if "Ctrl+Z" in action.text())
        undo_action.trigger()
        self.assertIsNone(self.store.note(cloned_page))
        self.assertNotIn(PAGE_MARK, destination.toPlainText())
        key(destination, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertIsNotNone(self.store.note(cloned_page))
        self.assertIn(PAGE_MARK, destination.toPlainText())
        self.assertIsNotNone(self.store.note(nested))

        key(destination, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        destination.insertPlainText("새 편집")
        key(destination, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        key(destination, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertIsNone(self.store.note(cloned_page), "새 편집 분기에서는 폐기된 페이지 복제를 되살리지 않는다")
        self.assertIn("새 편집", destination.toPlainText())

    def test_list_copy_paste_is_deep_and_batch_undoable(self):
        root = self.store.create_note("목록 원본", "본문")
        self.store.create_child_note(root, "하위", embedded=False)
        other = self.store.create_note("두 번째 원본", "본문 2")
        panel = AlertNotesPanel(self.store)
        self.widgets.append(panel)
        panel.refresh()
        panel.list_panel._item_for(root).setCheckState(0, Qt.CheckState.Checked)
        panel.list_panel._item_for(other).setCheckState(0, Qt.CheckState.Checked)
        self.assertTrue(panel.copy_selected_notes())
        self.assertTrue(QApplication.clipboard().mimeData().hasFormat(NOTES_MIME))
        self.assertTrue(panel.paste_copied_notes())
        batch = panel._list_clone_undo[-1]
        self.assertEqual(len(batch["roots"]), 2)
        new_root = batch["id_map"][root]
        self.assertIn("복사본", self.store.note(new_root)["title"])
        self.assertEqual(len(self.store.note_descendants(new_root)), 1)
        self.assertTrue(panel.undo_note_clone())
        self.assertIsNone(self.store.note(new_root))
        self.assertTrue(panel.redo_note_clone())
        self.assertIsNotNone(self.store.note(new_root))

    def test_alt_c_copies_and_applies_only_character_format(self):
        editor = self.editor()
        editor.setPlainText("원본\n대상")
        source = QTextCursor(editor.document().begin())
        source.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setFontWeight(700)
        fmt.setForeground(QColor("#c62828"))
        source.mergeCharFormat(fmt)
        source.clearSelection()
        source.setPosition(1)
        editor.setTextCursor(source)
        key(editor, Qt.Key.Key_C, Qt.KeyboardModifier.AltModifier)

        target_block = editor.document().begin().next()
        target = QTextCursor(target_block)
        target.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(target)
        key(editor, Qt.Key.Key_C, Qt.KeyboardModifier.AltModifier)
        check = QTextCursor(target_block)
        check.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        self.assertEqual(check.charFormat().fontWeight(), 700)
        self.assertEqual(check.charFormat().foreground().color().name(), "#c62828")
        self.assertFalse(check.charFormat().isAnchor())


if __name__ == "__main__":
    unittest.main()
