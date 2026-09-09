import json
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.insert_menu import build_insert_menu
from alert_notes.insert_preferences import (
    ORDER_KEY, TRIGGERS_KEY, default_order, default_triggers,
    get_insert_preferences, normalize_order, validate_triggers,
)
from alert_notes.rich_memo_edit import HEADING_STYLES, RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore


class MemoHeadingPreferencesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.show()

    def tearDown(self):
        self.editor.close()
        self.editor.deleteLater()
        self.app.processEvents()
        self.store.close()
        self.temp.cleanup()

    def test_defaults_have_stable_heading_order_and_triggers(self):
        prefs = get_insert_preferences(self.store)
        self.assertEqual(prefs.order[:5], ["heading1", "heading2", "heading3", "heading4", "body"])
        self.assertEqual(prefs.triggers["heading1"], "# ")
        self.assertEqual(prefs.triggers["heading4"], "#### ")

    def test_unknown_and_duplicate_order_values_are_safely_merged(self):
        result = normalize_order(["table", "unknown", "table", "heading1"])
        self.assertEqual(result[:2], ["table", "heading1"])
        self.assertEqual(set(result), set(default_order()))

    def test_order_and_triggers_persist(self):
        prefs = get_insert_preferences(self.store)
        order = list(prefs.order)
        order[0], order[1] = order[1], order[0]
        triggers = dict(prefs.triggers)
        triggers["heading1"] = "!# "
        self.assertFalse(prefs.save(order, triggers))
        self.assertEqual(json.loads(self.store.setting(ORDER_KEY)), order)
        self.assertEqual(json.loads(self.store.setting(TRIGGERS_KEY))["heading1"], "!# ")

    def test_invalid_trigger_values_are_rejected_without_writing(self):
        triggers = default_triggers()
        triggers["heading1"] = ""
        triggers["heading2"] = triggers["heading3"]
        errors = validate_triggers(triggers)
        self.assertIn("heading1", errors)
        self.assertIn("heading2", errors)
        self.assertIn("heading3", errors)

    def test_heading_applies_to_every_selected_line_and_survives_html(self):
        self.editor.setPlainText("하나\n둘")
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.editor.setTextCursor(cursor)
        self.editor.apply_heading2()
        expected = HEADING_STYLES[2]
        block = self.editor.document().firstBlock()
        while block.isValid():
            char = QTextCursor(block)
            char.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            self.assertAlmostEqual(char.charFormat().fontPointSize(), expected[0])
            self.assertEqual(block.blockFormat().topMargin(), expected[2])
            block = block.next()
        clone = RichMemoTextEdit(self.store)
        clone.setHtml(self.editor.toHtml())
        block = clone.document().firstBlock()
        char = QTextCursor(block)
        char.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        self.assertAlmostEqual(char.charFormat().fontPointSize(), expected[0])
        clone.deleteLater()

    def test_heading_enter_opens_a_clean_body_line(self):
        self.editor.setPlainText("제목")
        self.editor.apply_heading1()
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)
        QTest.keyClick(self.editor, Qt.Key.Key_Return)
        block = self.editor.textCursor().block()
        self.assertEqual(block.blockFormat().topMargin(), 0)
        QTest.keyClicks(self.editor, "body")
        self.assertLess(self.editor.textCursor().charFormat().fontPointSize(), HEADING_STYLES[1][0])

    def test_markdown_trigger_applies_heading_and_one_undo_restores_typed_marker(self):
        self.editor.clear()
        self.editor.setFocus()
        QTest.keyClicks(self.editor, "# ")
        self.assertEqual(self.editor.toPlainText(), "")
        self.assertEqual(self.editor.document().firstBlock().blockFormat().topMargin(), HEADING_STYLES[1][2])
        self.editor.undo()
        self.assertEqual(self.editor.toPlainText(), "#")
        self.assertEqual(self.editor.document().firstBlock().blockFormat().topMargin(), 0)

    def test_panel_and_slash_menu_share_saved_order(self):
        prefs = get_insert_preferences(self.store)
        order = list(prefs.order)
        order.insert(0, order.pop(order.index("table")))
        prefs.save(order, prefs.triggers)
        menu = build_insert_menu(self.editor)
        panel = menu.actions()[0].defaultWidget()
        self.assertEqual(panel.feature_list.item(0).data(Qt.ItemDataRole.UserRole), "table")
        self.editor.setPlainText("/")
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)
        self.editor._refresh_insert_popup()
        self.assertIn("표", self.editor.insert_popup_items()[0])
        menu.deleteLater()

    def test_panel_move_button_persists_an_accessible_drag_alternative(self):
        menu = build_insert_menu(self.editor)
        panel = menu.actions()[0].defaultWidget()
        first = panel.feature_list.item(0).data(Qt.ItemDataRole.UserRole)
        panel.feature_list.setCurrentRow(0)
        panel.down_button.click()
        self.assertEqual(panel.preferences.order[1], first)
        self.assertEqual(json.loads(self.store.setting(ORDER_KEY))[1], first)
        menu.deleteLater()

    def test_long_press_drag_reorders_the_visible_list(self):
        menu = build_insert_menu(self.editor)
        panel = menu.actions()[0].defaultWidget()
        panel.show()
        self.app.processEvents()
        before = [panel.feature_list.item(row).data(Qt.ItemDataRole.UserRole)
                  for row in range(panel.feature_list.count())]
        source = panel.feature_list.visualItemRect(panel.feature_list.item(0)).center()
        target = panel.feature_list.visualItemRect(panel.feature_list.item(2)).center()
        viewport = panel.feature_list.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=source)
        QTest.qWait(380)
        QTest.mouseMove(viewport, target, delay=20)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=target)
        self.app.processEvents()
        after = [panel.feature_list.item(row).data(Qt.ItemDataRole.UserRole)
                 for row in range(panel.feature_list.count())]
        self.assertNotEqual(after, before)
        menu.deleteLater()

    def test_panel_marks_duplicate_fixed_alias_before_save(self):
        menu = build_insert_menu(self.editor)
        panel = menu.actions()[0].defaultWidget()
        panel.trigger_edits["heading1"].setText("* ")
        self.assertFalse(panel._validate_edits())
        self.assertTrue(panel.trigger_edits["heading1"].property("invalid"))
        self.assertFalse(panel.error_label.isHidden())
        menu.deleteLater()

    def test_all_visible_panel_rows_have_descriptions(self):
        menu = build_insert_menu(self.editor)
        panel = menu.actions()[0].defaultWidget()
        for row in range(panel.feature_list.count()):
            self.assertTrue(panel.feature_list.item(row).toolTip())
        menu.deleteLater()

    def test_saved_order_refreshes_other_open_editor_panel_immediately(self):
        other = RichMemoTextEdit(self.store)
        menu = build_insert_menu(other)
        panel = menu.actions()[0].defaultWidget()
        prefs = get_insert_preferences(self.store)
        order = list(prefs.order)
        order.insert(0, order.pop(order.index("quote")))
        prefs.save(order, prefs.triggers)
        self.assertEqual(panel.feature_list.item(0).data(Qt.ItemDataRole.UserRole), "quote")
        menu.deleteLater()
        other.deleteLater()


if __name__ == "__main__":
    unittest.main()
