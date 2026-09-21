import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from alert_notes.memo_list import MemoListPanel
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.title_symbols import leading_title_symbol, title_symbol_key
from qt_test_support import close_alert_panel, destroy_widget
from ui_theme import scaled_stylesheet


class TitleSymbolRuleTest(unittest.TestCase):
    def test_leading_symbol_keeps_visible_grapheme_and_ignores_punctuation(self):
        self.assertEqual(leading_title_symbol("  ✨테스트"), "✨")
        self.assertEqual(leading_title_symbol("⚡ 업무"), "⚡")
        self.assertEqual(leading_title_symbol("★중요"), "★")
        self.assertEqual(leading_title_symbol("❤️ 마음"), "❤️")
        self.assertEqual(title_symbol_key("❤️"), "❤")
        self.assertEqual(leading_title_symbol("👩🏽\u200d💻 개발"), "👩🏽\u200d💻")
        self.assertEqual(leading_title_symbol("🇰🇷 출장"), "🇰🇷")
        self.assertIsNone(leading_title_symbol("- 일반 문장"))
        self.assertIsNone(leading_title_symbol("업무일반"))


class StageDMemoListTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.previous_style = self.app.styleSheet()
        self.app.setStyleSheet(scaled_stylesheet(1.0))
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "stage_d.db", "새 메모")
        self.work = int(self.store.categories()[0]["id"])
        self.sparkle_one = self.store.create_note("✨테스트 메모", "본문")
        self.sparkle_two = self.store.create_note("✨개발용", "본문")
        self.bolt = self.store.create_note("⚡업무용", "본문")
        self.plain = self.store.create_note("업무일반", "본문")
        self.store.set_note_category(self.sparkle_one, self.work)
        self.store.set_note_category(self.bolt, self.work)
        self.panel = MemoListPanel(self.store)
        self.panel.resize(480, 700)
        self.panel.show()
        self.panel.set_rows(self.store.notes())
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()
        self.app.setStyleSheet(self.previous_style)

    def test_title_symbol_button_filters_dynamically_and_combines_with_category(self):
        self.assertIn("✨ 2", self.panel.title_symbol_button.text())
        self.assertEqual(self.store.setting("memo_title_symbol_filter", "missing"), "missing")

        self.panel._set_title_symbol_filter("✨")
        self.panel.set_rows(self.store.notes())
        self.app.processEvents()
        self.assertEqual(self.panel.row_count(), 2)
        self.assertFalse(self.panel.table.dragEnabled())
        self.assertEqual(
            {self.panel.table.topLevelItem(i).text(1) for i in range(2)},
            {"✨테스트 메모", "✨개발용"},
        )

        self.panel._set_category_filter(self.work)
        self.panel.set_rows(self.store.notes())
        self.assertEqual(self.panel.row_count(), 1)
        self.assertEqual(self.panel.table.topLevelItem(0).text(1), "✨테스트 메모")

    def test_category_chips_unassigned_filter_color_and_compact_cells(self):
        unassigned = next(
            button for button in self.panel.category_filter_buttons
            if button.property("category_id") == "none"
        )
        assigned = next(
            button for button in self.panel.category_filter_buttons
            if button.property("category_id") == self.work
        )
        self.assertEqual(unassigned.objectName(), "memoCategoryFilterChip")
        self.assertFalse(assigned.icon().isNull())

        self.panel._set_category_filter("none")
        self.panel.set_rows(self.store.notes())
        self.assertEqual(self.panel.row_count(), 2)
        self.assertTrue(all(
            item.text(2) == "—" for item in self.panel._note_items()
        ))
        self.assertTrue(unassigned.isChecked())

    def test_480_width_keeps_four_columns_and_more_controls(self):
        self.panel.resize(480, 700)
        self.app.processEvents()
        self.panel._resize_table_columns()
        self.app.processEvents()
        self.assertTrue(self.panel.view_combo.isHidden())
        self.assertTrue(self.panel.sort_combo.isHidden())
        self.assertTrue(self.panel.more_categories_button.isVisible())
        self.assertEqual(self.panel.visible_columns(), [0, 1, 2, 3])
        self.assertEqual(self.panel.table.horizontalScrollBar().maximum(), 0)
        first = next(self.panel._note_items())
        self.assertRegex(first.text(3), r"^\d{2}-\d{2}$")
        self.assertRegex(first.toolTip(3), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_checked_rows_replace_footer_with_bulk_actions(self):
        first = next(self.panel._note_items())
        first.setCheckState(0, Qt.CheckState.Checked)
        self.app.processEvents()
        self.assertTrue(self.panel.selection_chip.isVisible())
        self.assertEqual(self.panel.selection_chip.text(), "1개 선택")
        self.assertTrue(self.panel.bulk_category_button.isVisible())
        self.assertTrue(self.panel.delete_button.isVisible())
        self.assertFalse(self.panel.export_button.isVisible())
        self.assertFalse(self.panel.action_status.isVisible())

    def test_conflict_copy_has_marker_and_original_tooltip(self):
        original = self.store.note(self.plain)
        conflict = self.store.create_note("업무일반 (2)", "충돌")
        self.store.conn.execute(
            "UPDATE notes SET conflict_of_sync_id=? WHERE id=?",
            (str(original["sync_id"]), conflict),
        )
        self.store.conn.commit()
        self.panel.set_rows(self.store.notes())
        item = self.panel._item_for(conflict)
        self.assertIn("⚠ 충돌", item.text(1))
        self.assertIn("원본: 업무일반", item.toolTip(1))
        self.assertIn("비교한 뒤 정리", item.toolTip(1))

    def test_long_footer_status_is_elided_but_tooltip_keeps_full_text(self):
        message = "문서 구조를 현재 커서 위치에 가져왔습니다. 저장된 항목을 확인해 주세요."
        self.panel.resize(300, 600)
        self.panel.action_status.setText(message)
        self.app.processEvents()
        self.assertEqual(self.panel.action_status.fullText(), message)
        self.assertEqual(self.panel.action_status.toolTip(), message)
        self.assertIn("…", self.panel.action_status.text())

    def test_bulk_category_assignment_clears_checks_and_reports_success(self):
        destroy_widget(self.panel, self.app)
        main = AlertNotesPanel(self.store)
        try:
            main.show()
            self.app.processEvents()
            main.list_panel._set_all_checked(True)
            selected = main.list_panel.checked_ids()
            main.assign_note_categories(selected, self.work)
            self.app.processEvents()
            self.assertEqual(main.list_panel.checked_ids(), [])
            self.assertIn(f"{len(selected)}개 메모", main.list_panel.action_status.fullText())
            self.assertEqual(main.list_panel.action_status.property("level"), "success")
        finally:
            close_alert_panel(main, self.app)
            self.panel = None


if __name__ == "__main__":
    unittest.main()
