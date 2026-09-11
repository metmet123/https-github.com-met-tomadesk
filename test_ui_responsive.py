import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QFontDatabase, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QBoxLayout, QLabel

import main_window
from qt_test_support import close_main_window
from store import Store
from ui_theme import APP_STYLESHEET


class _FakeHotkeyManager:
    def __init__(self, _window_id):
        pass

    def register(self, *_args):
        pass

    def unregister_all(self):
        pass

    def handle_native_event(self, _message):
        return False


class _FakeRecorder:
    ignore_click = None

    def stop(self):
        return []


class ResponsiveUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font_path = Path(r"C:\Windows\Fonts\malgun.ttf")
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp_dir.name) / "ui-test.db")
        self.store.save_action({
            "name": "활성 문구", "hotkey": "Ctrl+Alt+1", "action_type": "text",
            "payload": {"text": "hello"}, "active": True,
        })
        self.store.save_action({
            "name": "비활성 사이트", "hotkey": "Ctrl+Alt+2", "action_type": "url",
            "payload": {"url": "https://example.com"}, "active": False,
        })
        self.patches = [
            patch.object(main_window, "Store", return_value=self.store),
            patch.object(main_window, "HotkeyManager", _FakeHotkeyManager),
            patch.object(main_window, "WindowsHookRecorder", _FakeRecorder),
        ]
        for item in self.patches:
            item.start()
        self.window = main_window.MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        close_main_window(self.window, self.app)
        for item in reversed(self.patches):
            item.stop()
        self.store.conn.close()
        self.temp_dir.cleanup()

    def test_filters_empty_state_and_delete_count(self):
        self.window.active_filter.setCurrentIndex(1)
        self.assertEqual(
            sum(not self.window.table.isRowHidden(row) for row in range(2)),
            1,
        )
        visible_row = next(row for row in range(2) if not self.window.table.isRowHidden(row))
        self.window.table.item(visible_row, 0).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(self.window.delete_action_button.text(), "삭제 (1)")

        self.window.action_search.setText("없는 작업")
        self.assertTrue(self.window.empty_search_label.isVisible())
        self.assertFalse(self.window.table.isVisible())

    def test_workspace_mode_buttons_fit_their_text(self):
        self.window.resize(1400, 900)
        self.window._update_responsive_layout()
        self.app.processEvents()
        shortcut = self.window.shortcut_mode_button
        memo = self.window.alert_mode_button
        for button in (shortcut, memo):
            text = button.fontMetrics().horizontalAdvance(button.text())
            self.assertGreater(button.width(), text, f"{button.text()} 글자가 잘립니다")
            self.assertLess(
                button.width(), text + 80,
                f"{button.text()} 버튼이 글자에 견줘 너무 넓습니다",
            )
        self.assertGreater(
            shortcut.width(), memo.width(),
            "글자 수가 다른데 두 버튼 폭이 같습니다",
        )

    def test_workspace_shift_tab_hint_and_compact_task_list(self):
        self.window.resize(1247, 849)
        self.window._update_responsive_layout()
        self.app.processEvents()

        self.assertEqual(self.window.workspace_switch_hint.text(), "Ctrl+Tab 전환")
        self.assertTrue(self.window.workspace_switch_hint.isVisible())
        self.assertEqual(
            [button.text() for button in self.window.workspace_utility_buttons],
            ["시작", "휴지통", "설정", "설명서"],
        )
        self.assertTrue(all(button.isVisible() for button in self.window.workspace_utility_buttons))
        self.assertLess(self.window.active_filter.y(), 100)
        self.assertLess(self.window.table.y(), 150)

        self.assertEqual(self.window.main_pages.currentIndex(), 0)
        QTest.keyClick(self.window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(self.window.main_pages.currentIndex(), 1)
        self.assertTrue(self.window.alert_mode_button.isChecked())
        self.assertTrue(all(button.isVisible() for button in self.window.workspace_utility_buttons))
        self.assertFalse(self.window.alert_panel.tabs.tabBar().isVisible())
        self.assertLessEqual(self.window.workspace_mode_bar.height(), 50)
        self.assertTrue(all(button.isVisible() for button in self.window.alert_tab_buttons))
        self.assertLessEqual(abs(
            self.window.alert_tab_buttons[0].mapTo(self.window, QPoint()).y()
            - self.window.alert_mode_button.mapTo(self.window, QPoint()).y()
        ), 1)
        self.window.alert_tab_buttons[1].click()
        self.app.processEvents()
        self.assertEqual(self.window.alert_panel.tabs.currentIndex(), 1)
        self.assertTrue(self.window.alert_tab_buttons[1].isChecked())
        self.window.alert_panel.tabs.setCurrentIndex(2)
        self.app.processEvents()
        self.assertTrue(self.window.alert_tab_buttons[2].isChecked())
        QTest.keyClick(self.window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(self.window.main_pages.currentIndex(), 0)
        self.assertTrue(self.window.shortcut_mode_button.isChecked())
        self.assertFalse(any(button.isVisible() for button in self.window.alert_tab_buttons))

        for combo in (self.window.active_filter, self.window.type_filter):
            before = combo.currentIndex()
            combo.setFocus()
            event = QWheelEvent(
                QPointF(4, 4), QPointF(4, 4), QPoint(), QPoint(0, 120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            QApplication.sendEvent(combo, event)
            self.assertEqual(combo.currentIndex(), before)

    def test_narrow_layout_splitter_persistence_and_status(self):
        self.window.resize(900, 650)
        self.window._update_responsive_layout()
        self.assertFalse(self.window.workspace_switch_hint.isVisible())
        self.assertTrue(all(button.isVisible() for button in self.window.workspace_utility_buttons))
        self.assertEqual(self.window.splitter.orientation(), Qt.Orientation.Vertical)
        self.window.splitter.setSizes([280, 350])
        self.window._save_splitter_sizes()
        saved_ratio = float(self.store.setting("main_splitter_vertical_ratio"))
        self.assertAlmostEqual(
            saved_ratio,
            self.window.splitter.sizes()[0] / sum(self.window.splitter.sizes()),
            places=4,
        )

        self.window.resize(1300, 700)
        self.window._update_responsive_layout()
        self.assertEqual(self.window.splitter.orientation(), Qt.Orientation.Horizontal)
        horizontal_ratio = self.window.splitter.sizes()[0] / sum(self.window.splitter.sizes())
        self.window.resize(1550, 760)
        self.window._update_responsive_layout()
        resized_ratio = self.window.splitter.sizes()[0] / sum(self.window.splitter.sizes())
        self.assertAlmostEqual(horizontal_ratio, resized_ratio, places=2)
        self.window._set_status("완료", "success")
        self.assertEqual(self.window.status.property("level"), "success")

    def test_table_columns_fill_width_and_form_reflows_with_editor_width(self):
        self.window.resize(1600, 760)
        self.window._update_responsive_layout()
        self.app.processEvents()
        table_width = sum(
            self.window.table.columnWidth(column)
            for column in range(self.window.table.columnCount())
        )
        self.assertLessEqual(abs(table_width - self.window.table.viewport().width()), 4)
        self.assertEqual(
            self.window.form_bottom_layout.direction(),
            QBoxLayout.Direction.LeftToRight,
        )

        self.window.resize(1100, 700)
        self.window.splitter.setSizes([650, 450])
        self.window._update_responsive_layout()
        self.app.processEvents()
        self.assertEqual(
            self.window.form_bottom_layout.direction(),
            QBoxLayout.Direction.TopToBottom,
        )
        index = self.window.form_grid.indexOf(self.window.hotkey_edit)
        row, _column, _row_span, _column_span = self.window.form_grid.getItemPosition(index)
        self.assertEqual(row, 2)

    def test_window_geometry_is_saved_restored_and_kept_on_screen(self):
        target = QRect(120, 130, 980, 640)
        self.window.setGeometry(target)
        self.window._save_window_geometry()
        self.assertTrue(self.store.setting("main_window_geometry"))

        self.window.setGeometry(QRect(10, 10, 820, 560))
        self.window._restore_window_geometry()
        restored = self.window.geometry()
        self.assertGreaterEqual(restored.width(), self.window.minimumWidth())
        self.assertGreaterEqual(restored.height(), self.window.minimumHeight())

        self.window.setGeometry(QRect(10000, 10000, 900, 650))
        self.window._keep_window_on_screen()
        center = self.window.frameGeometry().center()
        self.assertTrue(any(screen.availableGeometry().contains(center) for screen in self.app.screens()))

    def test_corner_drag_resizes_and_respects_minimum(self):
        self.window.setGeometry(QRect(100, 100, 900, 600))
        self.app.processEvents()
        corner = self.window.mapToGlobal(QPoint(self.window.width() - 2, self.window.height() - 2))
        self.assertEqual(
            self.window._resize_edges_at(corner),
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        )
        start = self.window.geometry()
        self.window._resize_drag = (
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
            QPoint(start.right(), start.bottom()),
            start,
        )
        self.window._resize_from_drag(QPoint(start.right() + 120, start.bottom() + 80))
        self.assertEqual(self.window.size().width(), 1020)
        self.assertEqual(self.window.size().height(), 680)

    def test_polish_states_hit_areas_and_accessible_controls(self):
        self.assertNotIn("@blue", APP_STYLESHEET)
        self.assertGreaterEqual(self.window.table.verticalHeader().defaultSectionSize(), 40)
        self.assertGreaterEqual(self.window.record_start_button.sizeHint().height(), 40)
        self.assertEqual(self.window.record_start_button.accessibleName(), "녹화 시작")
        # 단추 줄 대신 줄에서 오른쪽 단추로 부르는 메뉴가 상태를 알린다.
        self.assertFalse(self.window.activate_selected_action.isEnabled())

        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(self.window.activate_selected_action.isEnabled())

        self.window.macro_edit.setPlainText("{")
        self.assertFalse(self.window.macro_summary_label.property("valid"))
        self.window.macro_edit.setPlainText('{"steps": []}')
        self.assertTrue(self.window.macro_summary_label.property("valid"))

        self.window._recording = True
        self.window._set_recording_controls()
        self.assertTrue(self.window.recording_deck.property("recording"))
        self.assertIn(self.window.record_stop_hotkey, self.window.recording_badge.text())

    def test_empty_filter_and_compact_macro_layout(self):
        self.window.resize(1420, 720)
        self.window.type_combo.setCurrentIndex(self.window.type_combo.findData("macro"))
        # 시간·반복 설정과 복원 버튼은 고급 옵션 안에 있다.
        self.window.macro_advanced_options_toggle.setChecked(True)
        self.window.active_filter.setCurrentIndex(1)
        self.window.type_filter.setCurrentIndex(self.window.type_filter.findData("macro"))
        self.app.processEvents()

        self.assertTrue(self.window.empty_search_label.isVisible())
        self.assertLessEqual(self.window.form_card.height(), 100)
        form_scroll = self.window.form_panel.verticalScrollBar()
        form_scroll.setValue(form_scroll.maximum())
        self.app.processEvents()
        help_bottom = self.window.help_section.mapTo(
            self.window.form_panel.viewport(),
            QPoint(0, self.window.help_section.height()),
        ).y()
        self.assertLessEqual(help_bottom, self.window.form_panel.viewport().height() + 1)
        self.assertTrue(self.window.macro_save_button.isVisible())
        self.assertFalse(self.window.form_save_button.isVisible())
        self.assertIs(self.window.macro_save_button.parentWidget(), self.window.recording_deck)
        self.assertTrue(self.window.restore_macro_button.isVisible())
        self.assertTrue(self.window.macro_undo_button.isVisible())
        self.assertTrue(self.window.macro_redo_button.isVisible())
        self.assertLessEqual(self.window.macro_undo_button.width(), 44)
        self.assertLessEqual(self.window.macro_redo_button.width(), 44)
        self.assertEqual(len({button.y() for button in self.window.utility_buttons}), 1)
        self.assertTrue(all(button.width() < 180 for button in self.window.utility_buttons))

    def test_macro_sections_repeat_layout_and_help_order(self):
        self.window.type_combo.setCurrentIndex(self.window.type_combo.findData("macro"))
        self.window.macro_advanced_options_toggle.setChecked(True)
        self.window.resize(2000, 900)
        self.window._update_responsive_layout()
        self.app.processEvents()
        self.window._update_responsive_layout()
        self.app.processEvents()
        self.assertEqual(self.window.recording_section.title(), "녹화 제어")
        self.assertEqual(self.window.timing_section.title(), "시간 설정")
        self.assertEqual(self.window.help_section.title(), "도움말")
        self.assertLess(self.window.recording_section.y(), self.window.timing_section.y())
        self.assertLess(self.window.timing_section.y(), self.window.help_section.y())
        self.assertEqual(
            self.window.stop_hotkey_layout.direction(),
            QBoxLayout.Direction.LeftToRight,
        )
        self.assertEqual(self.window.form_panel.horizontalScrollBar().maximum(), 0)
        self.assertTrue(self.window.recording_help_panel.isHidden())
        self.assertEqual(self.window.findChildren(QLabel, "sequencePreview"), [])

        self.window.resize(900, 650)
        self.window._update_responsive_layout()
        self.app.processEvents()
        self.window._update_responsive_layout()
        self.app.processEvents()
        self.assertEqual(
            self.window.stop_hotkey_layout.direction(),
            QBoxLayout.Direction.TopToBottom,
        )
        self.assertEqual(self.window.form_panel.horizontalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
