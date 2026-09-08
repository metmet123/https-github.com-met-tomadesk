import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import main_window
from alert_notes.schedule_recurrence import DATETIME_FMT
from hotkey_defs import HotkeyError
from qt_test_support import close_main_window
from store import Store


class TrackingHotkeys:
    fail_text = ""

    def __init__(self, _window_id):
        self.registered = {}
        self.unregister_all_calls = 0

    def register(self, hotkey_id, hotkey, callback):
        if hotkey == self.fail_text:
            raise HotkeyError(f"{hotkey}: 테스트 충돌")
        self.registered[hotkey_id] = (hotkey, callback)

    def unregister(self, hotkey_id):
        self.registered.pop(hotkey_id, None)

    def unregister_all(self):
        self.unregister_all_calls += 1
        self.registered.clear()

    def handle_native_event(self, _message):
        return False


class FakeRecorder:
    ignore_click = None

    def start(self):
        pass

    def stop(self):
        return []


class StageTwoUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "hotkeys.db")
        self.patches = [
            patch.object(main_window, "Store", return_value=self.store),
            patch.object(main_window, "HotkeyManager", TrackingHotkeys),
            patch.object(main_window, "WindowsHookRecorder", FakeRecorder),
            patch.object(main_window, "foreground_application", return_value=None),
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

    def test_the_row_menu_can_test_one_checked_action(self):
        action_id = self.store.save_action({
            "name": "테스트", "hotkey": "Ctrl+Alt+1", "action_type": "text",
            "payload": {"text": "내용", "press_enter": False}, "active": True,
        })
        self.window.refresh()
        # 단추 줄은 걷었다.  같은 일은 줄에서 오른쪽 단추로 부른다.
        self.assertEqual(self.window.table.columnCount(), 7)
        self.assertTrue(self.window.table.isColumnHidden(main_window.ID_COLUMN))
        self.assertFalse(self.window.test_action_action.isEnabled())
        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(self.window.test_action_action.isEnabled())
        with patch.object(self.window.runner, "run", return_value="테스트 성공") as run:
            self.window.test_selected_action()
        self.assertEqual(int(run.call_args.args[0]["id"]), action_id)
        self.assertIn("테스트 성공", self.window.status.text())

    def test_note_autosave_skips_calendar_history_and_hotkey_reregistration(self):
        panel = self.window.alert_panel
        note_id = panel.store.create_note("메모", "이전")
        panel.current_id = note_id
        panel.editor.set_note(panel.store.note(note_id))
        values = panel.editor.values()
        values["content"] = "변경"
        unregister_before = self.window.hotkeys.unregister_all_calls
        with (
            patch.object(panel.calendar, "refresh") as calendar_refresh,
            patch.object(panel.reminder_history, "refresh") as history_refresh,
        ):
            panel.save_editor_values(note_id, values, panel.editor)
        calendar_refresh.assert_not_called()
        history_refresh.assert_not_called()
        self.assertEqual(self.window.hotkeys.unregister_all_calls, unregister_before)

    def test_200_note_200_schedule_autosave_query_budget(self):
        panel = self.window.alert_panel
        note_ids = [panel.store.create_note(f"메모 {index}", "내용") for index in range(200)]
        for index in range(200):
            panel.store.schedules.save_item({
                "title": f"일정 {index}", "item_type": "event",
                "start_at": f"202609{(index % 28) + 1:02d}0900",
                "end_at": f"202609{(index % 28) + 1:02d}1000",
            })
        note_id = note_ids[0]
        panel.current_id = note_id
        panel.editor.set_note(panel.store.note(note_id))
        values = panel.editor.values()
        values["content"] = "성능 측정 변경"
        statements = []
        panel.store.conn.set_trace_callback(statements.append)
        started = time.perf_counter()
        try:
            panel.save_editor_values(note_id, values, panel.editor)
        finally:
            panel.store.conn.set_trace_callback(None)
        elapsed = time.perf_counter() - started
        selects = sum(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        print(f"AUTOSAVE_200X200 elapsed={elapsed:.4f}s selects={selects}")
        self.assertLessEqual(selects, 5)
        self.assertLess(elapsed, 2.0)

    def test_content_hotkey_change_reregisters_once_but_same_signature_does_not(self):
        panel = self.window.alert_panel
        note_id = panel.store.create_note("메모", "내용")
        panel.current_id = note_id
        panel.editor.set_note(panel.store.note(note_id))
        values = panel.editor.values()
        values.update(hotkey="Ctrl+Alt+7", hotkey_action="open")
        before = self.window.hotkeys.unregister_all_calls
        panel.save_editor_values(note_id, values, panel.editor)
        self.assertEqual(self.window.hotkeys.unregister_all_calls, before + 1)
        self.window._on_content_shortcuts_changed()
        self.assertEqual(self.window.hotkeys.unregister_all_calls, before + 1)

    def test_registration_failure_is_visible_and_retryable(self):
        TrackingHotkeys.fail_text = "Ctrl+Alt+6"
        try:
            self.store.save_action({
                "name": "충돌 작업", "hotkey": TrackingHotkeys.fail_text,
                "action_type": "text", "payload": {"text": "내용"}, "active": True,
            })
            self.window.refresh()
            self.window.register_hotkeys(False)
            self.assertEqual(self.window.table.item(0, 6).status(), "등록 실패")
            self.assertIn("실패 1개", self.window.registration_notice.text())
            self.assertIn("실패 상세", self.window.registration_notice.text())
            self.assertTrue(self.window.registration_notice.isVisible())
            self.assertTrue(self.window.registration_details_action.isEnabled())
            TrackingHotkeys.fail_text = ""
            with patch.object(main_window.QMessageBox, "information"):
                self.window.retry_registration_action.trigger()
            self.assertEqual(self.window.table.item(0, 6).status(), "등록됨")
            self.assertFalse(self.window.registration_notice.isVisible())
        finally:
            TrackingHotkeys.fail_text = ""

    def test_calendar_timeline_covers_full_day_boundaries(self):
        schedules = self.window.note_store.schedules
        for title, start_at, end_at in (
            ("자정", "202608310000", "202608310100"),
            ("아침", "202608310759", "202608310859"),
            ("밤", "202608312359", "202609010030"),
        ):
            schedules.save_item({
                "title": title, "item_type": "event", "start_at": start_at, "end_at": end_at,
            })
        calendar = self.window.alert_panel.calendar
        calendar.anchor = __import__("datetime").date(2026, 8, 31)
        calendar._set_mode("day")
        canvas = calendar.canvas
        # 자정·아침·밤 세 일정이 모두 제 분 위치에 놓인다.
        tops = {block.title: int(block.rect().y()) for block in canvas.blocks()}
        self.assertEqual(tops["자정"], 0)
        self.assertEqual(tops["아침"], 7 * 60 + 59)
        self.assertEqual(tops["밤"], 23 * 60 + 59)
        # 하루의 양 끝이 모두 시간축 안에 있다.
        self.assertEqual(canvas.datetime_at(0, 0).strftime(DATETIME_FMT), "202608310000")
        self.assertEqual(canvas.datetime_at(0, 23 * 60).strftime(DATETIME_FMT), "202608312300")
        self.assertEqual(canvas.datetime_at(0, 24 * 60).strftime(DATETIME_FMT), "202609010000")


if __name__ == "__main__":
    unittest.main()
