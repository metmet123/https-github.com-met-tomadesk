"""Stage 2 tests for saving and editing Explorer window layouts."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPushButton

import excel_io
import main_window
from qt_test_support import close_main_window
from store import Store


class _TrackingHotkeys:
    def __init__(self, _window_id):
        self.registered = {}

    def register(self, hotkey_id, hotkey, callback):
        self.registered[hotkey_id] = (hotkey, callback)

    def unregister(self, hotkey_id):
        self.registered.pop(hotkey_id, None)

    def unregister_all(self):
        self.registered.clear()

    def handle_native_event(self, _message):
        return False


class _FakeRecorder:
    ignore_click = None

    def stop(self):
        return []


class LayoutActionUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "layout.db")
        self.patches = [
            patch.object(main_window, "Store", return_value=self.store),
            patch.object(main_window, "HotkeyManager", _TrackingHotkeys),
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
        self.store.close()
        self.temp.cleanup()

    @staticmethod
    def _captured_windows():
        return [
            {
                "hwnd": 101, "explorer_path": r"D:\제출", "monitor": 2,
                "rect": [100, 80, 900, 700], "rect_basis": "visible",
                "state": "normal", "monitor_device": r"\\.\DISPLAY2",
                "work_area": [1920, 1032], "dpi": 96,
            },
            {
                "hwnd": 102, "explorer_path": r"C:\자료", "monitor": 1,
                "rect": [0, 0, 800, 600], "rect_basis": "visible",
                "state": "maximized",
            },
            {
                "hwnd": 103, "explorer_path": "", "monitor": 1,
                "rect": [20, 20, 400, 300], "state": "normal",
            },
        ]

    def _select_layout_type(self):
        index = self.window.type_combo.findData("layout")
        self.window.type_combo.setCurrentIndex(index)
        self.app.processEvents()
        return index

    def test_layout_is_last_and_stack_pages_follow_action_order(self):
        self.assertEqual(list(main_window.ACTION_LABELS), ["text", "url", "path", "macro", "layout"])
        self.assertEqual(self.window.stack.count(), len(main_window.ACTION_LABELS))
        for index, action_type in enumerate(main_window.ACTION_LABELS):
            self.window.type_combo.setCurrentIndex(index)
            self.assertEqual(self.window.type_combo.currentData(), action_type)
            self.assertEqual(self.window.stack.currentIndex(), index)

    def test_capture_selection_new_window_order_and_delete_shape_payload(self):
        self._select_layout_type()
        with patch.object(main_window, "collect_open_windows", return_value=self._captured_windows()):
            self.window.capture_layout_windows()
        self.assertEqual(self.window.layout_table.rowCount(), 2)
        self.assertEqual(self.window.layout_table.item(0, 1).text(), "제출")

        self.window.layout_table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        self.window.layout_table.cellWidget(0, 4).setChecked(True)
        payload = self.window._payload("layout")
        self.assertEqual(payload, {"windows": [{
            "kind": "explorer", "path": r"D:\제출", "monitor": 2,
            "rect": [100, 80, 900, 700], "rect_basis": "visible",
            "state": "normal", "always_new": True,
            "monitor_device": r"\\.\DISPLAY2", "work_area": [1920, 1032],
            "dpi": 96,
        }]})

        actions = self.window.layout_table.cellWidget(0, 5).findChildren(QPushButton)
        down = next(button for button in actions if button.text() == "↓")
        self.window._move_layout_row(down, 1)
        self.assertEqual(self.window.layout_table.item(1, 1).text(), "제출")
        actions = self.window.layout_table.cellWidget(1, 5).findChildren(QPushButton)
        remove = next(button for button in actions if button.text() == "삭제")
        self.window._delete_layout_row(remove)
        self.assertEqual(self.window.layout_table.rowCount(), 1)

    def test_save_list_filter_and_reload_preserve_layout_payload(self):
        layout_index = self._select_layout_type()
        self.window.name_edit.setText("제출 창 배치")
        self.window.hotkey_edit.setText("Ctrl+Alt+L")
        with patch.object(main_window, "collect_open_windows", return_value=self._captured_windows()[:2]):
            self.window.capture_layout_windows()
        self.window.layout_table.cellWidget(1, 4).setChecked(True)
        expected = self.window._payload("layout")

        self.assertTrue(self.window.save_action())
        row = self.store.actions()[0]
        self.assertEqual(row["action_type"], "layout")
        self.assertEqual(json.loads(row["payload"]), expected)
        self.assertEqual(self.window.table.item(0, 5).text(), "창 배치")

        filter_index = self.window.type_filter.findData("layout")
        self.window.type_filter.setCurrentIndex(filter_index)
        self.window._filter_actions("")
        self.assertFalse(self.window.table.isRowHidden(0))

        self.window.new_action()
        self.window.table.selectRow(0)
        self.window.load_selected()
        self.assertEqual(self.window.type_combo.currentIndex(), layout_index)
        self.assertEqual(self.window._payload("layout"), expected)

    def test_layout_requires_a_hotkey_and_at_least_one_selected_window(self):
        self._select_layout_type()
        self.window.hotkey_edit.setText("")
        with self.assertRaisesRegex(Exception, "단축키"):
            self.window._form_data()

        self.window.hotkey_edit.setText("Ctrl+Alt+L")
        with self.assertRaisesRegex(ValueError, "하나 이상 선택"):
            self.window._form_data()

    def test_existing_four_types_keep_their_page_indexes_and_payloads(self):
        expected = {
            "text": {"text": "문구", "press_enter": True},
            "url": {"url": "https://example.com"},
            "path": {"path": str(Path(self.temp.name)), "restore_if_minimized": True},
            "macro": {
                "steps": [{"type": "key", "key": "Enter"}],
                "timing_mode": "scaled", "playback_speed": 1.0, "repeat_count": 1,
            },
        }
        for index, action_type in enumerate(("text", "url", "path", "macro")):
            self.window.type_combo.setCurrentIndex(index)
            self.window._load_payload(action_type, expected[action_type])
            payload = self.window._payload(action_type)
            for key, value in expected[action_type].items():
                self.assertEqual(payload[key], value)
            self.assertEqual(self.window.stack.currentIndex(), index)


class LayoutExcelRoundTripTest(unittest.TestCase):
    def test_layout_payload_round_trips_through_xlsx(self):
        payload = {"windows": [
            {
                "kind": "explorer", "path": r"D:\제출", "monitor": 2,
                "rect": [100, 80, 900, 700], "rect_basis": "visible",
                "state": "normal", "always_new": False,
                "monitor_device": r"\\.\DISPLAY2", "work_area": [1920, 1032],
                "dpi": 96,
            },
            {
                "kind": "explorer", "path": r"C:\자료", "monitor": 1,
                "rect": [0, 0, 800, 600], "state": "maximized", "always_new": True,
            },
        ]}
        action = {
            "id": 7, "active": 1, "name": "창 배치", "hotkey": "Ctrl+Alt+L",
            "action_type": "layout", "payload": payload,
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "layout.xlsx"
            excel_io.export_actions_xlsx([action], path)
            imported = excel_io.import_actions_xlsx(path)
        self.assertEqual(imported[0]["payload"], payload)
        self.assertEqual(imported[0]["action_type"], "layout")


if __name__ == "__main__":
    unittest.main()
