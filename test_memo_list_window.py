"""Ctrl+Alt+M 메모 목록 창: 목록만 띄우고, 더블클릭하면 편집기를 펴고, X는 창만 숨긴다."""

import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect

import main_window
from test_settings_dday_ux import MainWindowFixture


class MemoListWindowTest(MainWindowFixture):
    def setUp(self):
        super().setUp()
        store = self.window.note_store
        self.first = store.create_note("첫 메모", "본문 하나")
        self.second = store.create_note("주간 보고", "본문 둘")
        self.panel = self.window.alert_panel
        self.panel.refresh()
        self.wide = self.window.geometry()
        self.app.processEvents()

    def open_list(self):
        self.window.show_memo_list_window()
        self.app.processEvents()

    def test_hotkey_opens_the_list_window(self):
        registered = self.window.hotkeys.registered[main_window.MEMO_SEARCH_HOTKEY_ID]
        self.assertEqual(registered[1], self.window.show_memo_list_window)

    def test_only_the_list_is_shown(self):
        self.open_list()
        self.assertTrue(self.window._memo_list_mode)
        self.assertTrue(self.panel.list_panel.isVisible())
        self.assertFalse(self.panel.editor_scroll.isVisible())
        self.assertFalse(self.panel.editor_remainder.isVisible())
        self.assertFalse(self.window.workspace_mode_bar.isVisible())
        self.assertEqual(self.panel.tabs.currentIndex(), 0)
        self.assertLess(self.window.width(), 760)
        self.assertIs(self.app.focusWidget(), self.panel.list_panel.search)

    def test_double_click_opens_editor_beside_the_list(self):
        self.open_list()
        narrow = self.window.width()
        self.panel.list_panel.note_activated.emit(self.second)
        self.app.processEvents()
        self.assertTrue(self.panel.editor_scroll.isVisible())
        self.assertTrue(self.panel.list_panel.isVisible())
        self.assertFalse(self.panel.editor_remainder.isVisible())
        self.assertEqual(self.panel.current_id, self.second)
        # 화면이 좁으면(오프스크린 800px) 화면 폭까지만 넓어진다.
        available = self.window.screen().availableGeometry().width()
        self.assertGreaterEqual(
            self.window.width(), min(available, narrow + self.panel.EDITOR_MINIMUM_WIDTH) - 1,
        )
        self.assertGreater(self.window.width(), narrow)

    def test_enter_on_a_row_opens_editor(self):
        self.open_list()
        item = self.panel.list_panel._item_for(self.first)
        self.panel.list_panel.table.itemActivated.emit(item, 1)
        self.app.processEvents()
        self.assertTrue(self.panel.editor_scroll.isVisible())
        self.assertEqual(self.panel.current_id, self.first)

    def test_side_button_folds_the_editor_back(self):
        self.open_list()
        narrow = self.window.width()
        self.panel.list_panel.note_activated.emit(self.first)
        self.app.processEvents()
        self.panel.toggle_memo_list()
        self.app.processEvents()
        self.assertFalse(self.panel.editor_scroll.isVisible())
        self.assertTrue(self.panel.list_panel.isVisible())
        self.assertEqual(self.window.width(), narrow)

    def test_new_memo_opens_editor(self):
        self.open_list()
        self.panel.create_note()
        self.app.processEvents()
        self.assertTrue(self.panel.editor_scroll.isVisible())

    def test_close_hides_without_quitting_and_restores_main_shape(self):
        self.open_list()
        with patch.object(self.window, "exit_application") as exit_application:
            self.window.title_bar.close_button.click()
        self.app.processEvents()
        exit_application.assert_not_called()
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window._memo_list_mode)
        self.assertEqual(self.window.geometry().size(), self.wide.size())
        self.assertTrue(self.panel.editor_scroll.isVisibleTo(self.panel))
        # 목록 창을 열기 전에 보던 작업공간으로 돌아간다.
        self.assertEqual(self.window.main_pages.currentIndex(), 0)
        self.assertTrue(self.window.workspace_mode_bar.isVisibleTo(self.window))
        self.assertEqual(self.window.title_bar.close_button.toolTip(), "프로그램 종료")

    def test_close_button_still_quits_outside_list_window(self):
        with patch.object(self.window, "exit_application") as exit_application:
            self.window.title_bar.close_button.click()
        exit_application.assert_called_once()

    def test_reopening_always_starts_as_list_only(self):
        self.open_list()
        self.panel.list_panel.note_activated.emit(self.first)
        self.app.processEvents()
        self.window.close_memo_list_window()
        self.open_list()
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.panel.editor_scroll.isVisible())
        self.assertLess(self.window.width(), 760)

    def test_pressing_again_while_open_folds_the_editor(self):
        self.open_list()
        self.panel.list_panel.note_activated.emit(self.first)
        self.app.processEvents()
        self.open_list()
        self.assertFalse(self.panel.editor_scroll.isVisible())

    def test_list_window_place_is_remembered(self):
        self.open_list()
        self.window.setGeometry(QRect(140, 90, 600, 640))
        self.app.processEvents()
        self.window.close_memo_list_window()
        self.open_list()
        geometry = self.window.geometry()
        self.assertEqual((geometry.x(), geometry.y(), geometry.height()), (140, 90, 640))
        self.assertEqual(geometry.width(), 600)

    def test_other_ways_of_opening_show_the_normal_window(self):
        self.open_list()
        self.window.restore_from_tray()
        self.app.processEvents()
        self.assertFalse(self.window._memo_list_mode)
        self.assertTrue(self.window.workspace_mode_bar.isVisible())
        self.assertTrue(self.panel.editor_scroll.isVisible())
        self.assertEqual(self.window.geometry().size(), self.wide.size())

    def test_search_shows_matching_schedules_and_opens_calendar(self):
        start = (datetime.now() + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
        item_id = self.window.note_store.schedules.save_item({
            "title": "주간 회의", "item_type": "event",
            "start_at": start.strftime("%Y%m%d%H%M"),
            "end_at": (start + timedelta(hours=1)).strftime("%Y%m%d%H%M"),
        })
        self.open_list()
        self.panel.list_panel.search.setText("주간")
        self.app.processEvents()
        results = self.panel.list_panel.schedule_results
        self.assertTrue(self.panel.list_panel.schedule_results_host.isVisible())
        self.assertEqual(results.count(), 1)
        self.assertIn("주간 회의", results.item(0).text())
        self.assertEqual(self.panel.list_panel.schedule_results_label.text(), "일정 1건")
        self.panel.list_panel._open_schedule_result(results.item(0))
        self.app.processEvents()
        self.assertFalse(self.window._memo_list_mode)
        self.assertEqual(self.panel.tabs.currentIndex(), 1)
        self.assertTrue(self.window.isVisible())
        self.assertEqual(int(item_id), int(item_id))

    def test_no_schedule_rows_without_search(self):
        self.open_list()
        self.assertFalse(self.panel.list_panel.schedule_results_host.isVisible())
        self.panel.list_panel.search.setText("없는 낱말")
        self.app.processEvents()
        self.assertFalse(self.panel.list_panel.schedule_results_host.isVisible())


if __name__ == "__main__":
    unittest.main()
