"""Schedule category customization and conservative title recommendations."""

import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QPoint, QRect

from alert_notes.categories import (
    new_schedule_category, recommend_schedule_category,
    save_schedule_categories, schedule_categories,
)
from alert_notes.calendar import CalendarPanel
from alert_notes.ko_schedule_parser import parse
from alert_notes.quick_schedule import QuickScheduleDialog
from alert_notes.schedule_popover import SchedulePopover
from alert_notes.schedule_category_dialog import ScheduleCategoryDialog
from alert_notes.sqlite_store import NoteReminderStore
from ui_theme import scaled_stylesheet


class ScheduleCategoriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "notes.db"
        self.store = NoteReminderStore(self.path, "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_legacy_keys_and_custom_metadata_survive_reopen(self):
        rows = schedule_categories(self.store)
        self.assertEqual(rows[0]["id"], "sky")
        custom = new_schedule_category("이호조", "mint", ["결재"])
        save_schedule_categories(self.store, [*rows, custom])
        self.store.close()
        self.store = NoteReminderStore(self.path, "새 메모")
        self.assertEqual(schedule_categories(self.store)[-1], custom)

    def test_direct_name_alias_boundaries_and_ambiguity(self):
        rows = schedule_categories(self.store)
        finance = new_schedule_category("이호조", "mint", ["결재", "회계"])
        rows.append(finance)
        self.assertEqual(recommend_schedule_category("이호조 결재올리기", rows), finance["id"])
        self.assertEqual(recommend_schedule_category("결재 자료 정리", rows), finance["id"])
        self.assertIsNone(recommend_schedule_category("개인정보 정리", rows))
        self.assertIsNone(recommend_schedule_category("이호조 개인 일정", rows))
        rows.append(new_schedule_category("승인", "peach", ["결재"]))
        self.assertIsNone(recommend_schedule_category("결재 자료 정리", rows))
        self.assertEqual(recommend_schedule_category("이호조 결재", rows), finance["id"])

    def test_new_schedule_without_category_uses_first_custom_default(self):
        custom = new_schedule_category("이호조", "mint")
        save_schedule_categories(self.store, [custom])
        item_id = self.store.schedules.save_item({
            "title": "분류 기본값 확인", "start_at": "202609281500", "end_at": "202609281600",
        })
        self.assertEqual(self.store.schedules.item(item_id)["category"], custom["id"])

    def test_used_category_cannot_be_removed_or_silently_reassigned(self):
        self.store.schedules.save_item({
            "title": "기존 업무", "start_at": "202609281500", "end_at": "202609281600",
            "category": "sky",
        })
        dialog = ScheduleCategoryDialog(self.store)
        try:
            dialog.rows = [row for row in dialog.rows if row["id"] != "sky"]
            dialog._render()
            with patch.object(QMessageBox, "warning") as warning:
                dialog._save()
            warning.assert_called_once()
            self.assertIn("sky", [row["id"] for row in schedule_categories(self.store)])
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_compact_manager_keeps_alias_editing_and_delete_protection(self):
        dialog = ScheduleCategoryDialog(self.store)
        try:
            collapsed_height = dialog.height()
            self.assertTrue(all(fields[0] is None for fields in dialog._fields))
            dialog._toggle_editor(0)
            self.assertGreater(dialog.height(), collapsed_height)
            name, _color, aliases = dialog._fields[0]
            name.setText("새 업무")
            aliases.setText("결재, 회계")
            dialog._toggle_editor(0)
            self.assertEqual(dialog.rows[0]["name"], "새 업무")
            self.assertEqual(dialog.rows[0]["aliases"], ["결재", "회계"])
            self.assertEqual(dialog.height(), collapsed_height)
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_manager_rows_fit_at_supported_theme_scales(self):
        dialog = ScheduleCategoryDialog(self.store)
        try:
            for scale in (1.0, 1.25, 1.5):
                with self.subTest(scale=scale):
                    dialog.setStyleSheet(scaled_stylesheet(scale))
                    dialog.show()
                    self.app.processEvents()
                    card = dialog.list_layout.itemAt(0).widget()
                    row = card.layout().itemAt(0).layout()
                    controls = [row.itemAt(i).widget() for i in range(row.count())]
                    rects = [QRect(w.mapTo(card, QPoint()), w.size()) for w in controls]
                    for rect in rects:
                        self.assertTrue(card.rect().contains(rect))
                    for index, first in enumerate(rects):
                        for second in rects[index + 1:]:
                            self.assertFalse(first.intersects(second))
                    dialog._toggle_editor(0)
                    self.app.processEvents()
                    self.assertTrue(dialog._fields[0][2].isVisible())
                    dialog._toggle_editor(0)
            dialog.rows[0]["name"] = "이호조 결재올리기 업무 긴 이름"
            dialog._render()
            self.app.processEvents()
            name = dialog.list_layout.itemAt(0).widget().layout().itemAt(0).layout().itemAt(1).widget()
            self.assertEqual(name.toolTip(), dialog.rows[0]["name"])
            self.assertGreaterEqual(name.width(), 0)
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_duplicate_names_are_rejected(self):
        rows = schedule_categories(self.store)
        rows.append(new_schedule_category("업무", "mint"))
        with self.assertRaises(ValueError):
            save_schedule_categories(self.store, rows)

    def test_cancelled_explicit_category_token_stays_in_title(self):
        result = parse("#업무 회의", ignored_spans=((0, 3, "category"),))
        self.assertIsNone(result.category)
        self.assertEqual(result.title, "#업무 회의")

    def test_popover_explicit_tag_and_manual_choice_win(self):
        rows = schedule_categories(self.store)
        custom = new_schedule_category("이호조", "mint", ["결재"])
        save_schedule_categories(self.store, [*rows, custom])
        popover = SchedulePopover(self.store)
        try:
            from datetime import datetime, timedelta
            start = datetime(2026, 9, 28, 15)
            popover.open_new(start, start + timedelta(hours=1))
            popover.title_edit.setText("이호조 결재올리기")
            self.assertEqual(popover.values()["category"], custom["id"])
            popover._pick_category("peach", manual=True)
            popover.title_edit.setText("이호조 회의")
            self.assertEqual(popover.values()["category"], "peach")
            popover.open_new(start, start + timedelta(hours=1))
            popover.title_edit.setText("이호조 결재 #개인")
            self.assertEqual(popover.values()["category"], "mint")
        finally:
            popover.hide()
            popover.deleteLater()
            self.app.processEvents()

    def test_calendar_and_full_editor_refresh_after_category_change(self):
        panel = CalendarPanel(self.store)
        try:
            rows = schedule_categories(self.store)
            custom = new_schedule_category("이호조", "mint")
            save_schedule_categories(self.store, [*rows, custom])
            panel.refresh_categories()
            self.assertGreaterEqual(panel.schedule_editor.category_combo.findData(custom["id"]), 0)
            self.assertIn(custom["name"], [action.text() for action in panel.category_picker.menu().actions()])
            panel._select_category(custom["id"])
            self.assertEqual(panel._category_filter, custom["id"])
            self.store.schedules.save_item({
                "title": "이호조 결재", "start_at": "202609281500", "end_at": "202609281600",
                "category": custom["id"],
            })
            events = panel._filtered_schedule_items(date(2026, 9, 28), date(2026, 9, 29))
            self.assertEqual(events[0]["category_name"], "이호조")
            self.assertEqual(len(events[0]["category_colors"]), 2)
            editor = panel.schedule_editor
            editor.new_item()
            editor._recommend_category("이호조 회의")
            self.assertEqual(editor.category_combo.currentData(), custom["id"])
            editor._manual_category_selected(0)
            editor.category_combo.setCurrentIndex(0)
            editor._recommend_category("이호조 결재")
            self.assertEqual(editor.category_combo.currentData(), rows[0]["id"])
        finally:
            panel.hide()
            panel.deleteLater()
            self.app.processEvents()

    def test_quick_schedule_uses_custom_name_and_alias(self):
        rows = schedule_categories(self.store)
        custom = new_schedule_category("이호조", "mint", ["결재"])
        save_schedule_categories(self.store, [*rows, custom])
        dialog = QuickScheduleDialog(self.store)
        try:
            dialog.prepare()
            dialog.input_edit.setText("내일 3시 이호조 결재올리기")
            self.assertEqual(dialog.values()["category"], custom["id"])
            dialog.input_edit.setText("내일 3시 결재 보고")
            self.assertEqual(dialog.values()["category"], custom["id"])
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
