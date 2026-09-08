import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from alert_notes.database_bundle import export_database_bundle, import_database_bundle
from alert_notes.panel import AlertNotesPanel
from alert_notes.postit import PostitWindow
from alert_notes.rich_memo_edit import RichMemoTextEdit
from alert_notes.rich_text import plain_text_from_content
from alert_notes.sqlite_store import (
    ATTACHMENT_COLUMNS, HISTORY_COLUMNS, NOTE_COLUMNS, REMINDER_COLUMNS, SERIES_COLUMNS,
    SETTING_COLUMNS, NoteReminderStore,
)


class PostitStageOneStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_postit_state_and_attachment_schema_roundtrip(self):
        note_id = self.store.create_note("이미지", "본문")
        self.store.update_note(
            note_id, postit=True, postit_visible=True, postit_startup=True,
            background_transparency=70,
        )
        attachment_id = self.store.add_attachment(
            note_id, "image/png", base64.b64encode(b"png-data").decode("ascii"), 320, 180,
        )
        note = self.store.note(note_id)
        self.assertTrue(note["postit_visible"])
        self.assertTrue(note["postit_startup"])
        self.assertEqual(note["background_transparency"], 70)
        self.assertEqual(self.store.attachment(attachment_id)["width"], 320)
        self.store.delete_note(note_id)
        self.assertIsNotNone(self.store.attachment(attachment_id))
        self.store.restore_note(note_id)
        self.assertEqual(self.store.attachment(attachment_id)["width"], 320)

    def test_attachment_is_in_json_bundle(self):
        note_id = self.store.create_note("백업", "본문")
        self.store.add_attachment(note_id, "image/png", "AA==", 10, 20)
        path = Path(self.temp.name) / "bundle.json"
        export_database_bundle(
            {"alert_notes": (self.store.conn, ("notes", "note_attachments"))}, path,
        )
        restored = NoteReminderStore(Path(self.temp.name) / "restored.db")
        try:
            imported = import_database_bundle(
                {"alert_notes": (restored.conn, {
                    "notes": list(NOTE_COLUMNS), "note_attachments": list(ATTACHMENT_COLUMNS),
                })}, path,
            )
            self.assertEqual(imported, {"alert_notes"})
            self.assertEqual(restored.note_attachments(note_id)[0]["data_base64"], "AA==")
        finally:
            restored.close()

    def test_legacy_bundle_maps_pinned_state_and_opacity(self):
        legacy = {
            "format": "sqlite-database-bundle", "version": 1,
            "databases": {"alert_notes": {"notes": [{
                "id": 7, "title": "이전 메모", "content": "내용", "postit": 1,
                "always_on_top": 1, "color": "mint", "opacity": 70,
                "input_locked": 0, "hotkey": "", "hotkey_action": "open",
                "created_at": "202608010900", "updated_at": "202608010900",
            }]}}
        }
        path = Path(self.temp.name) / "legacy.json"
        path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        restored = NoteReminderStore(Path(self.temp.name) / "legacy-restored.db")
        try:
            import_database_bundle(
                {"alert_notes": (restored.conn, {"notes": list(NOTE_COLUMNS)})}, path,
            )
            note = restored.note(7)
            self.assertTrue(note["postit_visible"])
            self.assertTrue(note["postit_startup"])
            self.assertEqual(note["background_transparency"], 30)
        finally:
            restored.close()


class PostitStageOneUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db")

    def tearDown(self):
        for widget in list(self.app.topLevelWidgets()):
            if isinstance(widget, PostitWindow):
                widget.close_silently()
            else:
                widget.close()
                widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.store.close()
        self.temp.cleanup()

    def test_rich_editor_inserts_scales_and_restores_database_image(self):
        note_id = self.store.create_note("그림", "")
        editor = RichMemoTextEdit(self.store)
        editor.resize(300, 240)
        editor.set_note_context(note_id)
        image = QImage(800, 400, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ef4444"))
        self.assertTrue(editor.insert_image(image))
        html = editor.content()
        self.assertIn("toma-note-image://attachment/", html)
        self.assertEqual(len(self.store.note_attachments(note_id)), 1)
        self.store.update_note(note_id, content=html)
        restored = RichMemoTextEdit(self.store)
        restored.resize(220, 180)
        restored.set_note_context(note_id)
        restored.set_content(html)
        self.app.processEvents()
        self.assertIn("[이미지]", plain_text_from_content(restored.content()))
        cursor = QTextCursor(restored.document())
        found_width = None
        while not cursor.atEnd():
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            if cursor.charFormat().isImageFormat():
                found_width = cursor.charFormat().toImageFormat().width()
                break
            cursor.clearSelection()
        self.assertIsNotNone(found_width)
        self.assertLessEqual(found_width, restored.viewport().width())
        editor.deleteLater()
        restored.deleteLater()

    def test_editors_for_same_note_share_one_document(self):
        note_id = self.store.create_note("공유", "처음")
        first = RichMemoTextEdit(self.store)
        second = RichMemoTextEdit(self.store)
        for editor in (first, second):
            editor.set_note_context(note_id)
            editor.set_content(str(self.store.note(note_id)["content"]))
        self.assertIs(first.document(), second.document())
        first.moveCursor(QTextCursor.MoveOperation.End)
        first.insertPlainText(" 수정")
        self.assertEqual(second.toPlainText(), "처음 수정")
        first.deleteLater()
        second.deleteLater()

    def test_rich_paste_keeps_formatting_and_removes_active_html(self):
        note_id = self.store.create_note("붙여넣기", "")
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        mime = QMimeData()
        mime.setHtml("<p><b>굵게</b><script>alert(1)</script></p>")
        editor.insertFromMimeData(mime)
        html = editor.content().casefold()
        self.assertIn("font-weight:700", html.replace(" ", ""))
        self.assertNotIn("script", html)
        editor.deleteLater()

    def test_link_is_recognized_and_only_safe_schemes_open(self):
        note_id = self.store.create_note("링크", "")
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        editor.show()
        editor.setFocus()
        QTest.keyClicks(editor, "https://example.com ")
        self.app.processEvents()
        self.assertIn('href="https://example.com"', editor.content())
        self.assertIsNotNone(editor._safe_external_url("https://example.com"))
        self.assertIsNone(editor._safe_external_url("javascript:alert(1)"))
        editor.deleteLater()

    def test_postit_has_eight_resize_targets_and_focus_scoped_shortcuts(self):
        note_id = self.store.create_note("크기 조절", "본문")
        self.store.update_note(note_id, postit=True, postit_visible=True)
        window = PostitWindow(self.store, self.store.note(note_id))
        window.resize(320, 240)
        points = {
            QPoint(1, 120): Qt.Edge.LeftEdge,
            QPoint(8, 120): Qt.Edge.LeftEdge,
            QPoint(14, 120): Qt.Edge.LeftEdge,
            QPoint(319, 120): Qt.Edge.RightEdge,
            QPoint(311, 120): Qt.Edge.RightEdge,
            QPoint(305, 120): Qt.Edge.RightEdge,
            QPoint(160, 1): Qt.Edge.TopEdge,
            QPoint(160, 8): Qt.Edge.TopEdge,
            QPoint(160, 14): Qt.Edge.TopEdge,
            QPoint(160, 239): Qt.Edge.BottomEdge,
            QPoint(160, 231): Qt.Edge.BottomEdge,
            QPoint(160, 225): Qt.Edge.BottomEdge,
            QPoint(1, 1): Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            QPoint(8, 8): Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            QPoint(319, 1): Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            QPoint(311, 8): Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            QPoint(1, 239): Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
            QPoint(8, 231): Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
            QPoint(319, 239): Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
            QPoint(311, 231): Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        }
        for local, expected in points.items():
            self.assertEqual(window._resize_edges(window.mapToGlobal(local)), expected)
        self.assertEqual(window._resize_edges(window.mapToGlobal(QPoint(20, 120))), Qt.Edge(0))
        self.assertEqual(window._resize_edges(window.mapToGlobal(QPoint(160, 20))), Qt.Edge(0))

        class ResizeHandle:
            def __init__(self):
                self.edges = []

            def startSystemResize(self, edges):
                self.edges.append(edges)
                return True

        class BorderPress:
            def __init__(self, point):
                self._point = QPointF(point)
                self.accepted = False

            @staticmethod
            def type():
                return QEvent.Type.MouseButtonPress

            @staticmethod
            def button():
                return Qt.MouseButton.LeftButton

            def globalPosition(self):
                return self._point

            def accept(self):
                self.accepted = True

        handle = ResizeHandle()
        with patch.object(window, "windowHandle", return_value=handle):
            for local, expected in (
                (QPoint(8, 120), Qt.Edge.LeftEdge),
                (QPoint(311, 120), Qt.Edge.RightEdge),
                (QPoint(160, 8), Qt.Edge.TopEdge),
                (QPoint(160, 231), Qt.Edge.BottomEdge),
            ):
                press = BorderPress(window.mapToGlobal(local))
                self.assertTrue(window.eventFilter(window, press))
                self.assertTrue(press.accepted)
                self.assertEqual(handle.edges[-1], expected)
        self.assertTrue(all(
            shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
            for shortcut in window.shortcuts
        ))
        cycled = []
        window.cycle_requested.connect(lambda note, backwards: cycled.append((note, backwards)))
        window.show()
        window.activateWindow()
        window.memo.setFocus()
        self.app.processEvents()
        QTest.keyClick(window.memo, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(cycled, [(note_id, False)])
        window.options_menu.show()
        self.app.processEvents()
        QTest.keyClick(window.options_menu, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertFalse(window.options_menu.isVisible())
        window.close_silently()

    def test_postit_controls_are_progressive_and_format_shortcuts_apply(self):
        note_id = self.store.create_note("집중 모드", "서식")
        self.store.update_note(note_id, postit=True, postit_visible=True)
        window = PostitWindow(self.store, self.store.note(note_id))
        window.show()
        window._set_controls_visible(False)
        self.assertTrue(window.format_bar.isHidden())
        self.assertTrue(all(button.isHidden() for button in window.bar.control_buttons))
        self.assertTrue(window.bar.isHidden())
        self.assertTrue(window.bar.label.isHidden())
        window._set_controls_visible(True)
        self.assertFalse(window.format_bar.isHidden())
        self.assertTrue(all(not button.isHidden() for button in window.bar.control_buttons))
        window.activateWindow()
        window.memo.setFocus()
        window.memo.selectAll()
        self.app.processEvents()
        QTest.keyClick(window.memo, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        self.assertGreaterEqual(window.memo.currentCharFormat().fontWeight(), 700)
        window.memo.moveCursor(QTextCursor.MoveOperation.End)
        window.memo.insertPlainText("\n목록")
        QTest.keyClick(
            window.memo, Qt.Key.Key_L,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        self.assertIsNotNone(window.memo.textCursor().currentList())
        window.close_silently()

    def test_panel_hides_without_unpinning_and_preserves_rich_text(self):
        note_id = self.store.create_note("서식", "<html><body><p><b>굵게</b></p></body></html>")
        self.store.update_note(
            note_id, postit=True, postit_visible=True, postit_startup=True,
        )
        panel = AlertNotesPanel(self.store)
        window = panel.postits[note_id]
        window.memo.moveCursor(QTextCursor.MoveOperation.End)
        window.memo.insertPlainText(" 추가")
        window.flush_pending_save()
        self.app.processEvents()
        saved = str(self.store.note(note_id)["content"])
        self.assertIn("font-weight:700", saved.replace(" ", ""))
        panel._hide_postit(note_id)
        self.assertTrue(self.store.note(note_id)["postit"])
        self.assertFalse(self.store.note(note_id)["postit_visible"])
        panel.toggle_note_postit(note_id)
        self.assertTrue(panel.postits[note_id].isVisible())
        panel.shutdown()
        panel.close()

    def test_postit_options_update_color_transparency_lock_and_startup(self):
        note_id = self.store.create_note("옵션", "본문")
        self.store.update_note(note_id, postit=True, postit_visible=True, postit_startup=True)
        window = PostitWindow(self.store, self.store.note(note_id))
        window.options_panel.color_selected.emit("mint")
        window.options_panel.transparency_selected.emit(100)
        window.options_panel.lock_toggled.emit(True)
        window.options_panel.startup_toggled.emit(False)
        note = self.store.note(note_id)
        self.assertEqual(note["color"], "mint")
        self.assertEqual(note["background_transparency"], 100)
        self.assertTrue(note["input_locked"])
        self.assertFalse(note["postit_startup"])
        self.assertTrue(window.memo.isReadOnly())
        window.close_silently()

    def test_new_postit_and_hide_actions_keep_distinct_state(self):
        note_id = self.store.create_note("첫 메모", "본문")
        self.store.update_note(
            note_id, postit=True, postit_visible=True, postit_startup=True,
        )
        panel = AlertNotesPanel(self.store)
        first = panel.postits[note_id]
        first.new_requested.emit(note_id)
        self.app.processEvents()
        self.assertEqual(len(panel.postits), 2)
        created_id = max(panel.postits)
        created = self.store.note(created_id)
        self.assertTrue(created["postit"])
        self.assertTrue(created["postit_visible"])
        created_window = panel.postits[created_id]
        created_window.show()
        created_window.activateWindow()
        created_window.memo.setFocus()
        self.app.processEvents()
        QTest.keyClick(
            created_window.memo, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier,
        )
        self.app.processEvents()
        hidden = self.store.note(created_id)
        self.assertTrue(hidden["postit"])
        self.assertFalse(hidden["postit_visible"])
        panel.shutdown()
        panel.close()

    def test_ctrl_d_uses_confirmation_before_deleting_note(self):
        note_id = self.store.create_note("삭제 확인", "본문")
        self.store.update_note(note_id, postit=True, postit_visible=True, postit_startup=True)
        panel = AlertNotesPanel(self.store)
        window = panel.postits[note_id]
        window.show()
        window.activateWindow()
        window.memo.setFocus()
        self.app.processEvents()
        with patch("alert_notes.panel.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            QTest.keyClick(window.memo, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
            self.app.processEvents()
        self.assertIsNotNone(self.store.note(note_id))
        with patch("alert_notes.panel.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            QTest.keyClick(window.memo, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
            self.app.processEvents()
        self.assertIsNone(self.store.note(note_id))
        panel.shutdown()
        panel.close()


if __name__ == "__main__":
    unittest.main()
