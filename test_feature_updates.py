import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox, QScrollArea

import action_runner
import A_shortcut_launcher as launcher
import excel_io
import excluded_apps_dialog
import main_window
import macro_step_editor
import macro_timing_editor
import settings_dialog
import storage_config
import window_restore
from excluded_apps_dialog import ExcludedAppsDialog
from foreground_app import is_app_excluded, normalize_app_list
from macro_recorder import MacroRecorder
from macro_step_editor import MacroStepDialog
from macro_timing_editor import TimingEditorDialog
from qt_test_support import accept_form_state, close_main_window
from settings_dialog import SettingsDialog
from store import Store


def accept_settings(dialog_class, values):
    """설정창은 이제 프로그램을 막지 않는다.

    exec() 로 기다리는 대신 저장을 누르면 신호가 온다.  가짜 창에서는
    연결하는 순간 손잡이를 불러 ‘저장을 눌렀다’를 흉내 낸다.
    """
    dialog = dialog_class.return_value
    dialog.values.return_value = values
    dialog.accepted.connect.side_effect = lambda handler: handler()


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


class FeatureUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp_dir.name) / "features.db")
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
        self.temp_dir.cleanup()

    def test_wheel_step_keeps_direction_position_and_timing(self):
        recorder = MacroRecorder(clock=lambda: 10.0)
        recorder.start()
        recorder.record_wheel(-120, "vertical", 320, 240, timestamp=10.0)
        steps = recorder.stop()
        self.assertEqual(
            steps,
            [{"type": "wheel", "delta": -120, "axis": "vertical", "x": 320, "y": 240}],
        )

    def test_recording_guide_emphasizes_stop_controls_only(self):
        self.window.record_stop_hotkey = "Ctrl+Enter"
        guide = self.window._recording_guide_text()
        self.assertIn("<span style='color:#dc2626; font-weight:700;'>Ctrl+Enter</span>", guide)
        self.assertIn("<span style='color:#dc2626; font-weight:700;'>녹화 종료</span>", guide)
        self.assertNotIn("3.", guide)

    def test_timing_editor_applies_user_delay_to_every_action(self):
        dialog = TimingEditorDialog([
            {"type": "click", "x": 10, "y": 20},
            {"type": "wait", "seconds": 0.5},
            {"type": "key", "key": "Enter"},
        ])
        dialog.apply_all_delay.setValue(0.37)
        dialog.apply_delay_to_all()
        self.assertEqual(dialog.steps(), [
            {"type": "click", "x": 10, "y": 20},
            {"type": "wait", "seconds": 0.37},
            {"type": "key", "key": "Enter"},
            {"type": "wait", "seconds": 0.37},
        ])
        dialog.apply_all_delay.setValue(0)
        dialog.apply_delay_to_all()
        self.assertEqual(dialog.steps(), [
            {"type": "click", "x": 10, "y": 20},
            {"type": "key", "key": "Enter"},
        ])
        dialog.close()

    def test_step_editor_updates_click_and_key_without_stale_key_codes(self):
        click_dialog = MacroStepDialog({"type": "click", "x": 10, "y": 20})
        click_dialog.x.setValue(-40)
        click_dialog.y.setValue(250)
        click_dialog.button.setCurrentIndex(click_dialog.button.findData("right"))
        self.assertEqual(
            click_dialog.step(),
            {"type": "click", "x": -40, "y": 250, "button": "right"},
        )
        click_dialog.close()

        key_dialog = MacroStepDialog({
            "type": "key", "key": "Ctrl+C", "vk": 67, "modifier_vks": [17],
        })
        key_dialog.key.setText("Alt+Tab")
        self.assertEqual(key_dialog.step(), {"type": "key", "key": "Alt+Tab"})
        key_dialog.close()

    def test_step_editor_updates_text_drag_and_wheel_fields(self):
        text_dialog = MacroStepDialog({"type": "text", "text": "기존", "press_enter": False})
        text_dialog.text.setPlainText("변경 문구")
        text_dialog.press_enter.setChecked(True)
        self.assertEqual(
            text_dialog.step(),
            {"type": "text", "text": "변경 문구", "press_enter": True},
        )
        text_dialog.close()

        drag_dialog = MacroStepDialog({
            "type": "drag", "start_x": 1, "start_y": 2, "end_x": 3, "end_y": 4,
            "duration": 0.2,
        })
        drag_dialog.end_x.setValue(300)
        drag_dialog.end_y.setValue(400)
        drag_dialog.duration.setValue(0.75)
        self.assertEqual(drag_dialog.step()["end_x"], 300)
        self.assertEqual(drag_dialog.step()["end_y"], 400)
        self.assertEqual(drag_dialog.step()["duration"], 0.75)
        drag_dialog.close()

        wheel_dialog = MacroStepDialog({
            "type": "wheel", "delta": -120, "axis": "vertical", "x": 5, "y": 6,
        })
        wheel_dialog.direction.setCurrentIndex(wheel_dialog.direction.findData("right"))
        wheel_dialog.notches.setValue(3)
        self.assertEqual(wheel_dialog.step(), {
            "type": "wheel", "delta": 360, "axis": "horizontal", "x": 5, "y": 6,
        })
        wheel_dialog.close()

    def test_step_editor_rejects_invalid_key_text(self):
        dialog = MacroStepDialog({"type": "key", "key": "Enter"})
        dialog.key.setText("지원하지않는키")
        with patch.object(macro_step_editor.QMessageBox, "warning") as warning:
            dialog._validate_and_accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        warning.assert_called_once()
        dialog.close()

    def test_timing_editor_cancelled_step_popup_keeps_original(self):
        dialog = TimingEditorDialog([{"type": "click", "x": 10, "y": 20}])
        with patch.object(macro_timing_editor.MacroStepDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            dialog._edit_cell(0, 1)
        self.assertEqual(dialog.steps()[0], {"type": "click", "x": 10, "y": 20})
        dialog.close()

    def test_existing_macro_can_restore_loaded_editor_state(self):
        self.window.current_id = 7
        original = {
            "steps": [
                {"type": "click", "x": 10, "y": 20},
                {"type": "wait", "seconds": 0.4},
            ],
            "timing_mode": "scaled",
            "playback_speed": 2.0,
            "repeat_count": 5,
        }
        self.window._load_payload("macro", original)
        self.window._capture_original_macro_state()
        self.window.macro_edit.setPlainText('{"steps": [{"type": "key", "key": "Enter"}]}')
        self.window.speed_slider.setValue(100)
        self.window.repeat_count_spin.setValue(1)

        self.window.restore_original_macro()

        restored = json.loads(self.window.macro_edit.toPlainText())
        self.assertEqual(restored["steps"], original["steps"])
        self.assertEqual(restored["timing_mode"], "scaled")
        self.assertEqual(restored["playback_speed"], 2.0)
        self.assertEqual(restored["repeat_count"], 5)
        self.assertEqual(self.window.speed_slider.value(), 200)
        self.assertEqual(self.window.repeat_count_spin.value(), 5)

    def test_macro_history_supports_multiple_undo_and_redo_steps(self):
        initial = self.window.macro_edit.toPlainText()
        first = '{"steps": [{"type": "key", "key": "Enter"}]}'
        second = '{"steps": [{"type": "key", "key": "Tab"}]}'

        self.window.macro_edit.setPlainText(first)
        self.window._commit_macro_history_state()
        self.window.macro_edit.setPlainText(second)
        self.window._commit_macro_history_state()

        self.assertTrue(self.window.macro_undo_button.isEnabled())
        self.window.undo_macro_edit()
        self.assertEqual(self.window.macro_edit.toPlainText(), first)
        self.window.undo_macro_edit()
        self.assertEqual(self.window.macro_edit.toPlainText(), initial)
        self.assertFalse(self.window.macro_undo_button.isEnabled())

        self.window.redo_macro_edit()
        self.assertEqual(self.window.macro_edit.toPlainText(), first)
        self.window.redo_macro_edit()
        self.assertEqual(self.window.macro_edit.toPlainText(), second)
        self.assertFalse(self.window.macro_redo_button.isEnabled())

    def test_new_edit_after_undo_clears_redo_history(self):
        self.window.macro_edit.setPlainText('{"steps": [{"type": "key", "key": "Enter"}]}')
        self.window._commit_macro_history_state()
        self.window.undo_macro_edit()
        self.assertTrue(self.window.macro_redo_button.isEnabled())

        self.window.macro_edit.setPlainText('{"steps": [{"type": "key", "key": "Escape"}]}')
        self.window._commit_macro_history_state()

        self.assertFalse(self.window.macro_redo_button.isEnabled())

    def test_initialization_can_be_undone(self):
        self.window.current_id = 7
        self.window._capture_original_macro_state()
        changed = '{"steps": [{"type": "key", "key": "Space"}]}'
        self.window.macro_edit.setPlainText(changed)
        self.window._commit_macro_history_state()

        self.window.restore_original_macro()
        self.assertNotEqual(self.window.macro_edit.toPlainText(), changed)
        self.window.undo_macro_edit()

        self.assertEqual(self.window.macro_edit.toPlainText(), changed)

    def test_continuous_json_and_slider_changes_commit_as_one_step_each(self):
        initial_undo_count = len(self.window._macro_undo_stack)
        self.window.macro_edit.setPlainText('{"steps": [')
        self.window.macro_edit.setPlainText('{"steps": []}')
        self.assertEqual(len(self.window._macro_undo_stack), initial_undo_count)
        self.window._commit_macro_history_state()
        self.assertEqual(len(self.window._macro_undo_stack), initial_undo_count + 1)

        self.window.speed_slider.setValue(120)
        self.window.speed_slider.setValue(150)
        self.window.speed_slider.setValue(180)
        self.window._commit_macro_history_state()
        self.assertEqual(len(self.window._macro_undo_stack), initial_undo_count + 2)

    def test_timing_dialog_and_json_import_each_commit_one_history_step(self):
        initial = self.window.macro_edit.toPlainText()
        timing_dialog = MagicMock()
        timing_dialog.exec.return_value = QDialog.DialogCode.Accepted
        timing_dialog.steps.return_value = [{"type": "key", "key": "Enter"}]
        with patch.object(main_window, "TimingEditorDialog", return_value=timing_dialog):
            self.window.edit_step_delays()
        self.assertEqual(len(self.window._macro_undo_stack), 1)
        self.window.undo_macro_edit()
        self.assertEqual(self.window.macro_edit.toPlainText(), initial)

        imported = {
            "steps": [{"type": "click", "x": 10, "y": 20}],
            "timing_mode": "scaled",
            "playback_speed": 2.0,
        }
        path = Path(self.temp_dir.name) / "macro.json"
        path.write_text(json.dumps(imported), encoding="utf-8")
        with patch.object(main_window.QFileDialog, "getOpenFileName", return_value=(str(path), "JSON (*.json)")):
            self.window.import_macro_json()
        self.assertEqual(len(self.window._macro_undo_stack), 1)
        self.window.undo_macro_edit()
        self.assertEqual(self.window.macro_edit.toPlainText(), initial)

    def test_recording_result_commits_as_one_history_step(self):
        initial = '{"steps": [{"type": "key", "key": "Tab"}]}'
        self.window.macro_edit.setPlainText(initial)
        self.window._reset_macro_history()
        self.window.recorder = MagicMock()
        self.window.recorder.stop.return_value = [{"type": "click", "x": 30, "y": 40}]
        self.window._recording = True

        self.window.stop_recording()

        self.assertEqual(len(self.window._macro_undo_stack), 1)
        self.window.undo_macro_edit()
        self.assertEqual(self.window.macro_edit.toPlainText(), initial)

    def test_save_and_new_action_reset_macro_history(self):
        self.window.type_combo.setCurrentIndex(self.window.type_combo.findData("macro"))
        self.window.hotkey_edit.setText("Ctrl+Alt+Space")
        self.window.macro_edit.setPlainText('{"steps": [{"type": "key", "key": "Enter"}]}')
        self.window._commit_macro_history_state()
        self.assertTrue(self.window.macro_undo_button.isEnabled())

        with patch.object(main_window.QMessageBox, "warning") as warning:
            self.window.save_action()
        self.assertFalse(warning.called, warning.call_args)
        self.assertFalse(self.window.macro_undo_button.isEnabled())
        self.assertFalse(self.window.macro_redo_button.isEnabled())

        self.window.macro_edit.setPlainText('{"steps": [{"type": "key", "key": "Tab"}]}')
        self.window._commit_macro_history_state()
        accept_form_state(self.window)
        self.window.new_action()
        self.assertFalse(self.window.macro_undo_button.isEnabled())
        self.assertFalse(self.window.macro_redo_button.isEnabled())

    def test_new_action_disables_restore_and_hotkey_buttons_are_clear(self):
        self.window.current_id = 3
        self.window._original_macro_state = {"document": "{}", "speed": 100, "repeat_count": 1}
        self.window._update_restore_macro_button()
        self.assertTrue(self.window.restore_macro_button.isEnabled())
        self.window.current_id = None
        self.window._original_macro_state = None
        self.window._update_restore_macro_button()
        self.assertFalse(self.window.restore_macro_button.isEnabled())
        self.assertEqual(self.window.restore_macro_button.text(), "초기화")
        self.assertEqual(self.window.macro_undo_button.accessibleName(), "되돌리기")
        self.assertEqual(self.window.macro_redo_button.accessibleName(), "다시 실행")
        self.assertEqual(self.window.edit_record_stop_hotkey_button.text(), "단축키 수정")
        self.assertEqual(self.window.edit_playback_stop_hotkey_button.text(), "단축키 수정")

    def test_recording_help_is_collapsed_and_replaces_notice_cards(self):
        self.assertTrue(self.window.recording_help_panel.isHidden())
        self.assertFalse(hasattr(self.window, "playback_stop_notice"))
        self.assertEqual(self.window.findChildren(type(self.window.recording_help_label), "emergencyNotice"), [])
        self.window.recording_help_toggle.click()
        self.app.processEvents()
        self.assertFalse(self.window.recording_help_panel.isHidden())
        self.assertEqual(self.window.recording_help_toggle.text(), "▾ 도움말 접기")
        self.assertIn(self.window.playback_stop_hotkey, self.window.recording_help_label.text())
        self.window.recording_help_toggle.click()
        self.assertTrue(self.window.recording_help_panel.isHidden())

    def test_excluded_apps_are_saved_in_each_action_payload(self):
        self.window.excluded_apps = [
            {"name": "notepad.exe", "path": r"C:\Windows\notepad.exe", "title": "메모장"}
        ]
        payload = self.window._payload("text")
        self.assertEqual(payload["excluded_apps"][0]["name"], "notepad.exe")
        self.assertEqual(payload["excluded_apps"][0]["path"], r"C:\Windows\notepad.exe")
        self.window._sync_excluded_apps_buttons()
        self.assertEqual(self.window.form_excluded_apps_button.text(), "제외 프로그램 선택 (1)")
        self.assertEqual(self.window.macro_excluded_apps_button.text(), "제외 프로그램 선택 (1)")

    def test_existing_action_restores_exclusions_and_new_action_clears_them(self):
        action_id = self.store.save_action({
            "name": "제외 작업", "hotkey": "Ctrl+Alt+8", "action_type": "text",
            "payload": {
                "text": "hello",
                "excluded_apps": [{"name": "notepad.exe", "path": r"C:\Windows\notepad.exe"}],
            },
            "active": True,
        })
        self.window.refresh()
        for row in range(self.window.table.rowCount()):
            item = self.window.table.item(row, 1)
            if int(item.data(Qt.ItemDataRole.UserRole)) == action_id:
                self.window.table.setCurrentCell(row, 1)
                break
        self.app.processEvents()
        self.assertEqual(self.window.excluded_apps[0]["name"], "notepad.exe")
        accept_form_state(self.window)
        self.window.new_action()
        self.assertEqual(self.window.excluded_apps, [])
        self.assertEqual(self.window.form_excluded_apps_button.text(), "제외 프로그램 선택")

    def test_cancelled_excluded_app_dialog_keeps_current_selection(self):
        original = [{"name": "notepad.exe", "path": r"C:\Windows\notepad.exe"}]
        self.window.excluded_apps = list(original)
        with patch.object(main_window, "ExcludedAppsDialog") as dialog_class:
            dialog_class.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.window.choose_excluded_apps()
        self.assertEqual(self.window.excluded_apps, original)

    def test_excluded_foreground_app_skips_execution_and_history(self):
        row = {
            "name": "메모장 제외 작업",
            "payload": json.dumps({
                "text": "hello",
                "excluded_apps": [{"name": "notepad.exe", "path": r"C:\Windows\notepad.exe"}],
            }),
        }
        current = {"name": "NOTEPAD.EXE", "path": r"c:\windows\NOTEPAD.EXE", "title": "메모장"}
        with (
            patch.object(main_window, "foreground_application", return_value=current),
            patch.object(self.window.runner, "run") as run,
            patch.object(self.store, "add_history") as history,
        ):
            self.window.run_saved_action(row)
        run.assert_not_called()
        history.assert_not_called()
        self.assertIn("NOTEPAD.EXE 프로그램에서는", self.window.status.text())

    def test_excluded_foreground_app_releases_only_its_action_hotkey(self):
        excluded_id = self.store.save_action({
            "name": "메모장 제외 작업", "hotkey": "Ctrl+Alt+8", "action_type": "text",
            "payload": {"text": "skip", "excluded_apps": [{"name": "notepad.exe", "path": r"C:\Windows\notepad.exe"}]},
            "active": True,
        })
        allowed_id = self.store.save_action({
            "name": "항상 실행 작업", "hotkey": "Ctrl+Alt+9", "action_type": "text",
            "payload": {"text": "run"}, "active": True,
        })
        current = {"name": "notepad.exe", "path": r"C:\Windows\notepad.exe"}
        with patch.object(main_window, "foreground_application", return_value=current):
            self.window.register_hotkeys(False)

        action_ids = {
            int(row["id"]): hotkey_id
            for hotkey_id, row in self.window._action_hotkey_rows.items()
        }
        excluded_hotkey_id = action_ids[excluded_id]
        allowed_hotkey_id = action_ids[allowed_id]
        self.assertNotIn(excluded_hotkey_id, self.window.hotkeys.registered)
        self.assertIn(allowed_hotkey_id, self.window.hotkeys.registered)

        current = {"name": "calc.exe", "path": r"C:\Windows\calc.exe"}
        with patch.object(main_window, "foreground_application", return_value=current):
            self.window._sync_action_hotkeys_for_foreground()
        self.assertIn(excluded_hotkey_id, self.window.hotkeys.registered)
        self.assertIn(allowed_hotkey_id, self.window.hotkeys.registered)

    def test_nonexcluded_foreground_app_runs_normally(self):
        row = {
            "name": "실행 작업", "action_type": "text", "payload": json.dumps({
                "text": "hello",
                "excluded_apps": [{"name": "notepad.exe", "path": r"C:\Windows\notepad.exe"}],
            }),
        }
        current = {"name": "calc.exe", "path": r"C:\Windows\calc.exe", "title": "계산기"}
        with (
            patch.object(main_window, "foreground_application", return_value=current),
            patch.object(self.window.runner, "run", return_value="완료") as run,
            patch.object(self.store, "add_history") as history,
        ):
            self.window.run_saved_action(row)
        run.assert_called_once_with(row)
        history.assert_called_once_with(row, "완료")

    def test_excluded_app_matching_prefers_path_and_falls_back_to_name(self):
        selected = [{"name": "tool.exe", "path": r"C:\Apps\tool.exe"}]
        self.assertTrue(is_app_excluded(
            {"name": "TOOL.EXE", "path": r"c:\apps\TOOL.EXE"}, selected
        ))
        self.assertFalse(is_app_excluded(
            {"name": "tool.exe", "path": r"D:\Other\tool.exe"}, selected
        ))
        self.assertTrue(is_app_excluded({"name": "TOOL.EXE", "path": ""}, selected))
        self.assertFalse(is_app_excluded(None, selected))

    def test_excluded_app_dialog_keeps_selection_and_removes_duplicates(self):
        running = [
            {"name": "notepad.exe", "path": r"C:\Windows\notepad.exe", "title": "메모장"},
            {"name": "NOTEPAD.EXE", "path": r"c:\windows\NOTEPAD.EXE", "title": "다른 창"},
        ]
        with patch.object(excluded_apps_dialog, "visible_applications", return_value=running):
            dialog = ExcludedAppsDialog([running[0]], self.window)
        self.assertEqual(dialog.list_widget.count(), 1)
        self.assertEqual(dialog.selected_apps()[0]["name"], "notepad.exe")
        dialog.list_widget.item(0).setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(dialog.selected_apps(), [])
        with patch.object(excluded_apps_dialog, "visible_applications", return_value=running):
            dialog.refresh()
        self.assertEqual(dialog.selected_apps(), [])
        dialog.close()

    def test_excluded_app_dialog_adds_executable_once(self):
        with patch.object(excluded_apps_dialog, "visible_applications", return_value=[]):
            dialog = ExcludedAppsDialog([], self.window)
        with patch.object(
            excluded_apps_dialog.QFileDialog,
            "getOpenFileName",
            return_value=(r"C:\Tools\sample.exe", "실행 파일 (*.exe)"),
        ):
            dialog.add_executable()
            dialog.add_executable()
        self.assertEqual(dialog.list_widget.count(), 1)
        self.assertEqual(dialog.selected_apps(), [{
            "name": "sample.exe", "path": r"C:\Tools\sample.exe", "title": "",
        }])
        dialog.close()

    def test_excel_roundtrip_and_legacy_import_preserve_compatibility(self):
        path = Path(self.temp_dir.name) / "excluded.xlsx"
        actions = [
            {
                "id": 1, "active": 1, "name": "작업", "hotkey": "Ctrl+Alt+1",
                "action_type": "text",
                "payload": json.dumps({
                    "text": "hello", "press_enter": True,
                    "excluded_apps": [{"name": "notepad.exe", "path": r"C:\Windows\notepad.exe"}],
                }),
            },
            {
                "id": 2, "active": 1, "name": "폴더 복원", "hotkey": "Ctrl+Alt+2",
                "action_type": "path",
                "payload": json.dumps({
                    "path": r"C:\Work", "restore_if_minimized": True,
                }),
            },
            {
                "id": 3, "active": 1, "name": "5회 반복", "hotkey": "Ctrl+Alt+3",
                "action_type": "macro",
                "payload": json.dumps({
                    "steps": [{"type": "key", "key": "Enter"}],
                    "timing_mode": "scaled", "playback_speed": 1.5,
                    "repeat_count": 5,
                }),
            },
        ]
        excel_io.export_actions_xlsx(actions, path)
        imported = excel_io.import_actions_xlsx(path)
        self.assertEqual(imported[0]["payload"]["excluded_apps"][0]["name"], "notepad.exe")
        self.assertTrue(imported[1]["payload"]["restore_if_minimized"])
        self.assertEqual(imported[2]["payload"]["repeat_count"], 5)

        from openpyxl import Workbook
        legacy_path = Path(self.temp_dir.name) / "legacy.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(excel_io.BASE_HEADERS)
        sheet.append([2, "예", "이전 작업", "Ctrl+Alt+2", "text", "legacy", "예", "", "", ""])
        workbook.save(legacy_path)
        legacy = excel_io.import_actions_xlsx(legacy_path)
        self.assertEqual(legacy[0]["payload"]["excluded_apps"], [])

    def test_path_restore_option_is_saved_loaded_and_cleared_for_new_action(self):
        self.window.path_edit.setText(r"C:\Tools\sample.exe")
        self.window.path_restore_check.setChecked(True)
        payload = self.window._payload("path")
        self.assertEqual(payload["path"], r"C:\Tools\sample.exe")
        self.assertTrue(payload["restore_if_minimized"])

        self.window._load_payload("path", payload)
        self.assertTrue(self.window.path_restore_check.isChecked())
        accept_form_state(self.window)
        self.window.new_action()
        self.assertFalse(self.window.path_restore_check.isChecked())

    def test_path_runner_restores_matching_minimized_window_without_reopening(self):
        target = Path(self.temp_dir.name) / "sample.exe"
        target.touch()
        runner = action_runner.ActionRunner()
        with (
            patch.object(action_runner, "restore_minimized_target", return_value=True) as restore,
            patch.object(action_runner.os, "startfile") as startfile,
        ):
            runner._run_path({"path": str(target), "restore_if_minimized": True})
        restore.assert_called_once_with(str(target))
        startfile.assert_not_called()

    def test_path_runner_opens_normally_when_restore_is_disabled_or_not_found(self):
        target = Path(self.temp_dir.name) / "sample.exe"
        target.touch()
        runner = action_runner.ActionRunner()
        with (
            patch.object(action_runner, "restore_minimized_target", return_value=False) as restore,
            patch.object(action_runner.os, "startfile") as startfile,
        ):
            runner._run_path({"path": str(target), "restore_if_minimized": True})
            runner._run_path({"path": str(target), "restore_if_minimized": False})
        restore.assert_called_once_with(str(target))
        self.assertEqual(startfile.call_count, 2)

    def test_window_restore_routes_files_and_folders_to_the_matching_finder(self):
        program = Path(self.temp_dir.name) / "sample.exe"
        program.touch()
        folder = Path(self.temp_dir.name) / "folder"
        folder.mkdir()
        with (
            patch.object(window_restore, "_find_minimized_program_window", return_value=101) as program_finder,
            patch.object(window_restore, "_find_minimized_explorer_window", return_value=202) as folder_finder,
            patch.object(window_restore, "_restore_window", return_value=True) as restore,
        ):
            self.assertTrue(window_restore.restore_minimized_target(str(program)))
            self.assertTrue(window_restore.restore_minimized_target(str(folder)))
        program_finder.assert_called_once_with(program)
        folder_finder.assert_called_once_with(folder)
        self.assertEqual(restore.call_args_list, [((101,),), ((202,),)])

    def test_action_runner_replays_wheel_step(self):
        runner = action_runner.ActionRunner()
        with patch.object(action_runner, "scroll") as scroll:
            runner._run_step({
                "type": "wheel", "delta": -240, "axis": "vertical", "x": 30, "y": 40,
            })
        scroll.assert_called_once_with(-240, "vertical", 30, 40)

    def test_recorded_text_does_not_trigger_clipboard_paste(self):
        runner = action_runner.ActionRunner()
        with (
            patch.object(action_runner, "wait_for_modifier_release") as release,
            patch.object(action_runner, "send_unicode_text") as send_text,
            patch.object(runner, "_paste_text") as paste,
        ):
            runner._run_step({"type": "text", "text": " ", "press_enter": False})
        release.assert_called_once()
        send_text.assert_called_once_with(" ")
        paste.assert_not_called()

    def test_recorded_copy_waits_for_clipboard_update(self):
        runner = action_runner.ActionRunner()
        with (
            patch.object(action_runner, "clipboard_sequence_number", return_value=42),
            patch.object(action_runner, "send_virtual_key") as send_key,
            patch.object(action_runner, "wait_for_clipboard_change", return_value=True) as wait_copy,
        ):
            runner._run_step({"type": "key", "key": "Ctrl+C", "vk": 67, "modifier_vks": [17]})
        send_key.assert_called_once_with(67, [17])
        wait_copy.assert_called_once_with(42)

    def test_copy_paste_space_sequence_has_only_one_paste_key(self):
        runner = action_runner.ActionRunner()
        steps = [
            {"type": "key", "key": "Ctrl+C", "vk": 67, "modifier_vks": [17]},
            {"type": "click", "x": 100, "y": 200},
            {"type": "key", "key": "Ctrl+V", "vk": 86, "modifier_vks": [17]},
            {"type": "text", "text": " ", "press_enter": False},
        ]
        with (
            patch.object(action_runner, "clipboard_sequence_number", return_value=8),
            patch.object(action_runner, "wait_for_clipboard_change"),
            patch.object(action_runner, "send_virtual_key") as send_key,
            patch.object(action_runner, "click"),
            patch.object(action_runner, "wait_for_modifier_release"),
            patch.object(action_runner, "send_unicode_text") as send_text,
            patch.object(runner, "_paste_text") as paste,
        ):
            runner._run_macro({"steps": steps, "timing_mode": "recorded"})
        self.assertEqual(send_key.call_args_list, [
            ((67, [17]),),
            ((86, [17]),),
        ])
        send_text.assert_called_once_with(" ")
        paste.assert_not_called()

    def test_macro_runner_repeats_complete_sequence_and_reports_count(self):
        runner = action_runner.ActionRunner()
        payload = {
            "steps": [{"type": "key", "key": "Enter"}],
            "timing_mode": "scaled",
            "playback_speed": 2.0,
            "repeat_count": 5,
        }
        with patch.object(runner, "_run_macro_with_speed") as execute:
            count = runner._run_macro(payload)
        self.assertEqual(count, 5)
        self.assertEqual(execute.call_count, 5)
        execute.assert_called_with(payload["steps"], 2.0)

        row = {
            "action_type": "macro",
            "payload": json.dumps({"steps": [], "repeat_count": 5}),
        }
        with patch.object(runner, "_run_macro_with_speed"):
            self.assertEqual(runner.run(row), "실행 완료 · 5회 반복")

    def test_macro_runner_stops_before_the_next_repetition(self):
        runner = action_runner.ActionRunner()

        def stop_after_first(_steps, _speed):
            runner.stop()

        with patch.object(runner, "_run_macro_with_speed", side_effect=stop_after_first) as execute:
            with self.assertRaisesRegex(RuntimeError, "중지"):
                runner._run_macro({"steps": [], "repeat_count": 5})
        self.assertEqual(execute.call_count, 1)

    def test_macro_runner_validates_repeat_range_and_legacy_timing(self):
        runner = action_runner.ActionRunner()
        for invalid in (0, 1000, 1.5, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "반복 횟수"):
                    runner._run_macro({"steps": [], "repeat_count": invalid})

        with patch.object(runner, "_run_macro_with_speed") as execute:
            runner._run_macro({
                "steps": [], "timing_mode": "recorded", "playback_speed": 8.0,
            })
        execute.assert_called_once_with([], 1.0)

        with patch.object(runner, "_run_macro_with_fixed_delay") as execute_fixed:
            runner._run_macro({
                "steps": [], "timing_mode": "fixed",
                "fixed_delay_seconds": 0.4, "repeat_count": 2,
            })
        self.assertEqual(execute_fixed.call_count, 2)

    def test_repeat_ui_speed_reset_and_json_stay_in_sync(self):
        self.assertFalse(hasattr(self.window, "timing_recorded_radio"))
        self.assertFalse(hasattr(self.window, "timing_speed_radio"))
        self.assertTrue(self.window.speed_slider.isEnabled())
        self.assertEqual(self.window.repeat_count_spin.minimum(), 1)
        self.assertEqual(self.window.repeat_count_spin.maximum(), 999)

        self.window.speed_slider.setValue(250)
        self.window.repeat_count_spin.setValue(5)
        self.window.speed_reset_button.click()
        payload = json.loads(self.window.macro_edit.toPlainText())

        self.assertEqual(self.window.speed_slider.value(), 100)
        self.assertEqual(payload["timing_mode"], "scaled")
        self.assertEqual(payload["playback_speed"], 1.0)
        self.assertEqual(payload["repeat_count"], 5)
        self.assertIn("1.0배 재생 · 5회 반복", self.window.macro_summary_label.text())

    def test_recorded_payload_loads_as_one_x_and_defaults_to_one_repeat(self):
        self.window._load_payload("macro", {
            "steps": [{"type": "key", "key": "Enter"}],
            "timing_mode": "recorded",
            "playback_speed": 4.0,
        })
        payload = json.loads(self.window.macro_edit.toPlainText())
        self.assertEqual(self.window.speed_slider.value(), 100)
        self.assertEqual(self.window.repeat_count_spin.value(), 1)
        self.assertEqual(payload["timing_mode"], "scaled")
        self.assertEqual(payload["repeat_count"], 1)

    def test_before_save_test_reports_the_repeat_count(self):
        self.window.repeat_count_spin.setValue(5)
        with patch.object(
            self.window.runner, "run", return_value="실행 완료 · 5회 반복"
        ) as run:
            self.window.test_macro_before_save()
        payload = json.loads(run.call_args.args[0]["payload"])
        self.assertEqual(payload["repeat_count"], 5)
        self.assertIn("5회 반복", self.window.status.text())

    def test_control_hotkeys_are_registered(self):
        registered = self.window.hotkeys.registered
        self.assertEqual(registered[main_window.EXIT_HOTKEY_ID][0], "Ctrl+Alt+F9")
        self.assertEqual(registered[main_window.MAIN_OPEN_HOTKEY_ID][0], "Ctrl+Alt+F10")
        self.assertEqual(registered[main_window.TRAY_HIDE_HOTKEY_ID][0], "Ctrl+Alt+F11")
        self.assertEqual(registered[main_window.HOTKEY_ID_STOP][0], "Ctrl+Alt+Esc")
        self.assertEqual(registered[main_window.QUICK_MEMO_HOTKEY_ID][0], "Ctrl+Alt+N")
        self.assertEqual(registered[main_window.NEW_MEMO_HOTKEY_ID][0], "Ctrl+Alt+Shift+N")
        self.assertEqual(registered[main_window.TODAY_VIEW_HOTKEY_ID][0], "Ctrl+Alt+C")
        self.assertEqual(registered[main_window.MEMO_SEARCH_HOTKEY_ID][0], "Ctrl+Alt+M")

    def test_changeable_note_hotkey_is_registered_and_opens_its_note(self):
        note_id = self.window.note_store.create_note("전역 단축키 메모", "내용")
        self.window.note_store.update_note(note_id, hotkey="Ctrl+Alt+7", hotkey_action="open")
        self.window.register_hotkeys(False)
        callback = next(
            callback
            for hotkey, callback in self.window.hotkeys.registered.values()
            if hotkey == "Ctrl+Alt+7"
        )

        with (
            patch.object(self.window.alert_panel, "open_standalone_note") as open_standalone_note,
            patch.object(self.window, "restore_from_tray") as restore_from_tray,
        ):
            callback()

        open_standalone_note.assert_called_once_with(note_id)
        restore_from_tray.assert_not_called()

    def test_new_memo_hotkey_opens_only_the_standalone_editor(self):
        self.window.hide()
        callback = self.window.hotkeys.registered[main_window.NEW_MEMO_HOTKEY_ID][1]
        with (
            patch.object(self.window.alert_panel, "open_standalone_note") as open_standalone,
            patch.object(self.window, "restore_from_tray") as restore_from_tray,
        ):
            callback()
        note_id = open_standalone.call_args.args[0]
        self.assertEqual(self.window.note_store.note(note_id)["title"], "새 메모")
        self.assertFalse(self.window.isVisible())
        restore_from_tray.assert_not_called()

    def test_main_settings_success_message_is_shown_once(self):
        values = {
            main_window.EXIT_HOTKEY_SETTING: self.window.exit_hotkey,
            main_window.MAIN_OPEN_HOTKEY_SETTING: self.window.main_open_hotkey,
            main_window.TRAY_HIDE_HOTKEY_SETTING: self.window.tray_hide_hotkey,
            main_window.RECORD_STOP_HOTKEY_SETTING: self.window.record_stop_hotkey,
            main_window.PLAYBACK_STOP_HOTKEY_SETTING: self.window.playback_stop_hotkey,
            main_window.QUICK_MEMO_HOTKEY_SETTING: self.window.quick_memo_hotkey,
            main_window.NEW_MEMO_HOTKEY_SETTING: self.window.new_memo_hotkey,
            main_window.TODAY_VIEW_HOTKEY_SETTING: self.window.today_view_hotkey,
            main_window.MEMO_SEARCH_HOTKEY_SETTING: self.window.memo_search_hotkey,
            "startup_mode": self.window.startup_mode,
            "data_dir": self.store.data_dir,
        }
        with (
            patch.object(main_window, "SettingsDialog") as dialog_class,
            patch.object(main_window, "save_storage_paths"),
            patch.object(main_window.QMessageBox, "information") as information,
            patch.object(main_window.QMessageBox, "warning") as warning,
        ):
            accept_settings(dialog_class, values)
            self.window.show_settings()
        warning.assert_not_called()
        information.assert_called_once()
        self.assertEqual(information.call_args.args[2], "설정이 저장되었습니다.")

    def test_exit_hotkey_remains_registered_while_recording(self):
        self.window.recorder = MagicMock()
        with patch.object(self.window, "_show_recording_guide", return_value=True):
            self.window.start_recording()
        registered = self.window.hotkeys.registered
        self.assertEqual(registered[main_window.EXIT_HOTKEY_ID][0], self.window.exit_hotkey)
        self.assertEqual(
            registered[main_window.RECORD_STOP_HOTKEY_ID][0],
            self.window.record_stop_hotkey,
        )
        self.window.recorder.stop.return_value = []
        self.window.stop_recording()

    def test_full_backup_and_restore_use_unified_data_folder(self):
        self.store.save_action({
            "name": "백업 대상", "hotkey": "Ctrl+Alt+7", "action_type": "text",
            "payload": {"text": "before"}, "active": True,
        })
        with patch.object(main_window.QMessageBox, "information"):
            self.window.export_backup()
        backups = list(self.store.data_dir.glob("backup_*.json"))
        self.assertEqual(len(backups), 1)

        self.store.save_action({
            "name": "복원 시 제거", "hotkey": "Ctrl+Alt+8", "action_type": "text",
            "payload": {"text": "after"}, "active": True,
        })
        application = MagicMock()
        with (
            patch.object(main_window.QFileDialog, "getOpenFileName", return_value=(str(backups[0]), "JSON (*.json)")),
            patch.object(main_window.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(main_window.QMessageBox, "information"),
            patch.object(main_window.QApplication, "instance", return_value=application),
        ):
            self.window.import_backup()
        self.assertEqual([row["name"] for row in self.store.actions()], ["백업 대상"])
        application.quit.assert_called_once()

    def test_settings_dialog_contains_only_requested_settings(self):
        data_dir = Path(self.temp_dir.name) / "data"
        backup_dir = Path(self.temp_dir.name) / "backup"
        dialog = SettingsDialog(
            hotkeys={
                main_window.EXIT_HOTKEY_SETTING: "Ctrl+Alt+F9",
                main_window.MAIN_OPEN_HOTKEY_SETTING: "Ctrl+Alt+F10",
                main_window.TRAY_HIDE_HOTKEY_SETTING: "Ctrl+Alt+F11",
                main_window.RECORD_STOP_HOTKEY_SETTING: "Ctrl+Alt+F12",
                main_window.PLAYBACK_STOP_HOTKEY_SETTING: "Ctrl+Alt+Esc",
            },
            startup_mode="tray",
            data_dir=data_dir,
            backup_dir=backup_dir,
            action_hotkeys=set(),
            parent=self.window,
        )
        values = dialog.values()
        self.assertEqual(values["startup_mode"], "tray")
        self.assertEqual(values["data_dir"], data_dir)
        self.assertNotIn("backup_dir", values)
        self.assertNotIn("backup_dir", dialog.path_labels)
        self.assertEqual(len(dialog.hotkey_builders), 14)
        self.assertEqual(values["screen_ocr_hotkey"], "Ctrl+Alt+O")
        self.assertEqual(values["file_rename_hotkey"], "")
        self.assertIn(main_window.WINDOW_PIN_HOTKEY_SETTING, dialog.hotkey_builders)
        self.assertIn(main_window.SHORTCUT_OVERLAY_HOTKEY_SETTING, dialog.hotkey_builders)
        self.assertIn(main_window.EXIT_HOTKEY_SETTING, dialog.hotkey_builders)
        self.assertIn(main_window.QUICK_SCHEDULE_HOTKEY_SETTING, dialog.hotkey_builders)
        self.assertIn(main_window.QUICK_MEMO_HOTKEY_SETTING, dialog.hotkey_builders)
        self.assertIn(main_window.NEW_MEMO_HOTKEY_SETTING, dialog.hotkey_builders)
        self.assertIn(main_window.TODAY_VIEW_HOTKEY_SETTING, dialog.hotkey_builders)
        self.assertIn(main_window.MEMO_SEARCH_HOTKEY_SETTING, dialog.hotkey_builders)
        # 줄 높이를 낮춰 창을 줄였다.  누르기 힘들 만큼 낮아지지는 않게 지킨다.
        self.assertGreaterEqual(dialog.hotkey_builders["main_open_hotkey"].minimumHeight(), 30)
        self.assertLessEqual(dialog.hotkey_builders["main_open_hotkey"].sizeHint().height(), 36)
        self.assertGreaterEqual(dialog.height(), dialog.sizeHint().height())
        dialog.resize(1050, 700)
        dialog.show()
        QApplication.processEvents()
        positions = [
            dialog.hotkey_grid.getItemPosition(dialog.hotkey_grid.indexOf(field))
            for field in dialog.hotkey_field_widgets
        ]
        self.assertEqual(dialog._hotkey_columns, 2)
        self.assertEqual([(row, column) for row, column, _, _ in positions[:7]], [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0)])
        self.assertEqual([(row, column) for row, column, _, _ in positions[7:]], [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1)])
        self.assertEqual(dialog.findChildren(QScrollArea), [])
        self.assertGreaterEqual(dialog.minimumWidth(), 980)
        self.assertGreaterEqual(dialog.minimumHeight(), 660)
        self.assertIs(dialog.hotkey_card.parentWidget(), dialog.hotkey_page)
        self.assertIs(dialog.schedule_postit_card.parentWidget(), dialog.schedule_page)
        self.assertIs(dialog.deadline_card.parentWidget(), dialog.schedule_page)
        self.assertIs(dialog.startup_card.parentWidget(), dialog.program_page)
        self.assertIs(dialog.pet_card.parentWidget(), dialog.program_page)
        self.assertIs(dialog.paths_card.parentWidget(), dialog.data_page)
        self.assertEqual(
            [dialog.settings_tabs.tabText(index) for index in range(4)],
            ["단축키", "일정·D-Day", "프로그램", "데이터"],
        )
        self.assertLess(
            dialog.settings_tabs.mapTo(dialog, QPoint()).y() + dialog.settings_tabs.height(),
            dialog.dialog_buttons.mapTo(dialog, QPoint()).y(),
        )
        self.assertEqual(
            dialog.dialog_buttons.button(QDialogButtonBox.StandardButton.Cancel).text(),
            "취소",
        )
        dialog.close()

    def test_settings_dialog_can_select_data_folder_and_run_full_backup_restore(self):
        backup = MagicMock()
        restore = MagicMock()
        dialog = SettingsDialog(
            hotkeys={
                main_window.EXIT_HOTKEY_SETTING: "Ctrl+Alt+F9",
                main_window.MAIN_OPEN_HOTKEY_SETTING: "Ctrl+Alt+F10",
                main_window.TRAY_HIDE_HOTKEY_SETTING: "Ctrl+Alt+F11",
                main_window.RECORD_STOP_HOTKEY_SETTING: "Ctrl+Alt+F12",
                main_window.PLAYBACK_STOP_HOTKEY_SETTING: "Ctrl+Alt+Esc",
            },
            startup_mode="window",
            data_dir=Path(self.temp_dir.name) / "data",
            backup_dir=Path(self.temp_dir.name) / "backup",
            action_hotkeys=set(),
            on_full_backup=backup,
            on_full_restore=restore,
            parent=self.window,
        )
        selected = Path(self.temp_dir.name) / "chosen-data"
        selected.mkdir()
        with patch.object(
            settings_dialog.QFileDialog, "getExistingDirectory", return_value=str(selected)
        ):
            dialog._select_folder("data_dir", "데이터 폴더")
        self.assertEqual(dialog.values()["data_dir"], selected)
        self.assertEqual(dialog.path_labels["data_dir"].text(), str(selected))
        dialog.full_backup_button.click()
        dialog.full_restore_button.click()
        backup.assert_called_once()
        restore.assert_called_once()
        dialog.close()

    def test_storage_defaults_use_application_directory(self):
        application = Path(self.temp_dir.name) / "portable"
        data_dir, backup_dir = storage_config.default_storage_paths(application)
        self.assertEqual(data_dir, application / "data")
        self.assertEqual(backup_dir, application / "data")

    def test_storage_config_roundtrip_and_legacy_migration(self):
        root = Path(self.temp_dir.name)
        config = root / "config" / "storage_paths.json"
        data_dir = root / "portable" / "data"
        backup_dir = root / "portable" / "backup"
        storage_config.save_storage_paths(data_dir, backup_dir, config)
        self.assertEqual(
            storage_config.load_storage_paths(root / "unused", config),
            (data_dir.resolve(), data_dir.resolve()),
        )
        saved_config = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(set(saved_config), {"data_dir"})

        legacy = root / "legacy"
        legacy_data = legacy / "data"
        legacy_backup = legacy / "backup"
        legacy_data.mkdir(parents=True)
        legacy_backup.mkdir()
        (legacy_data / "hotkeys.db").write_bytes(b"legacy-db")
        (legacy_backup / "backup_old.json").write_text("{}", encoding="utf-8")
        destination_data = root / "new" / "data"
        destination_backup = root / "new" / "backup"
        migrated = storage_config.migrate_legacy_storage(
            destination_data,
            destination_backup,
            config_file=root / "missing-config.json",
            legacy_root=legacy,
        )
        self.assertTrue(migrated)
        self.assertEqual((destination_data / "hotkeys.db").read_bytes(), b"legacy-db")
        self.assertTrue((destination_data / "backup_old.json").is_file())

    def test_legacy_backup_name_collision_is_preserved_without_duplicate_copies(self):
        root = Path(self.temp_dir.name)
        legacy = root / "legacy"
        source = legacy / "backup"
        source.mkdir(parents=True)
        (source / "backup.json").write_text("old", encoding="utf-8")
        destination = root / "portable" / "data"
        destination.mkdir(parents=True)
        (destination / "backup.json").write_text("new", encoding="utf-8")

        storage_config.migrate_legacy_storage(
            destination,
            config_file=root / "missing.json",
            legacy_root=legacy,
        )
        storage_config.migrate_legacy_storage(
            destination,
            config_file=root / "missing.json",
            legacy_root=legacy,
        )

        self.assertEqual((destination / "backup.json").read_text(encoding="utf-8"), "new")
        self.assertEqual((destination / "backup_이전1.json").read_text(encoding="utf-8"), "old")
        self.assertFalse((destination / "backup_이전2.json").exists())

    def test_database_collision_uses_next_free_number_for_each_database(self):
        destination = Path(self.temp_dir.name) / "numbered-data"
        destination.mkdir()
        (destination / "hotkeys.db").write_bytes(b"old-hotkeys")
        (destination / "hotkeys2.db").write_bytes(b"older-hotkeys")
        (destination / "alert_notes.db").write_bytes(b"old-notes")

        preserved = storage_config.copy_databases_preserving_existing(
            destination,
            {
                "hotkeys.db": lambda path: path.write_bytes(b"current-hotkeys"),
                "alert_notes.db": lambda path: path.write_bytes(b"current-notes"),
            },
        )

        self.assertEqual([path.name for path in preserved], ["hotkeys3.db", "alert_notes2.db"])
        self.assertEqual((destination / "hotkeys.db").read_bytes(), b"current-hotkeys")
        self.assertEqual((destination / "hotkeys2.db").read_bytes(), b"older-hotkeys")
        self.assertEqual((destination / "hotkeys3.db").read_bytes(), b"old-hotkeys")
        self.assertEqual((destination / "alert_notes.db").read_bytes(), b"current-notes")
        self.assertEqual((destination / "alert_notes2.db").read_bytes(), b"old-notes")

    def test_database_copy_failure_restores_original_names(self):
        destination = Path(self.temp_dir.name) / "rollback-data"
        destination.mkdir()
        (destination / "hotkeys.db").write_bytes(b"old-hotkeys")
        (destination / "alert_notes.db").write_bytes(b"old-notes")

        def fail_after_partial_write(path):
            path.write_bytes(b"partial-notes")
            raise OSError("copy failed")

        with self.assertRaisesRegex(OSError, "copy failed"):
            storage_config.copy_databases_preserving_existing(
                destination,
                {
                    "hotkeys.db": lambda path: path.write_bytes(b"current-hotkeys"),
                    "alert_notes.db": fail_after_partial_write,
                },
            )

        self.assertEqual((destination / "hotkeys.db").read_bytes(), b"old-hotkeys")
        self.assertEqual((destination / "alert_notes.db").read_bytes(), b"old-notes")
        self.assertFalse((destination / "hotkeys2.db").exists())
        self.assertFalse((destination / "alert_notes2.db").exists())

    def test_storage_path_save_failure_rolls_back_database_replacement(self):
        destination = Path(self.temp_dir.name) / "finalize-rollback-data"
        destination.mkdir()
        (destination / "hotkeys.db").write_bytes(b"old-hotkeys")

        with self.assertRaisesRegex(OSError, "config failed"):
            storage_config.copy_databases_preserving_existing(
                destination,
                {"hotkeys.db": lambda path: path.write_bytes(b"current-hotkeys")},
                finalize=MagicMock(side_effect=OSError("config failed")),
            )

        self.assertEqual((destination / "hotkeys.db").read_bytes(), b"old-hotkeys")
        self.assertFalse((destination / "hotkeys2.db").exists())

    def test_store_database_backup_opens_at_new_location(self):
        self.store.save_action({
            "name": "이동 작업", "hotkey": "Ctrl+Alt+9", "action_type": "text",
            "payload": {"text": "hello"}, "active": True,
        })
        destination = Path(self.temp_dir.name) / "new-data" / "hotkeys.db"
        self.store.backup_database(destination)
        moved = Store(destination)
        try:
            self.assertEqual(moved.actions()[0]["name"], "이동 작업")
        finally:
            moved.close()

    def test_existing_database_is_numbered_before_path_change(self):
        new_data = Path(self.temp_dir.name) / "existing-data"
        new_data.mkdir()
        (new_data / "hotkeys.db").write_bytes(b"existing")
        (new_data / "hotkeys2.db").write_bytes(b"existing-numbered")
        (new_data / "alert_notes.db").write_bytes(b"existing-notes")
        values = {
            main_window.EXIT_HOTKEY_SETTING: self.window.exit_hotkey,
            main_window.MAIN_OPEN_HOTKEY_SETTING: self.window.main_open_hotkey,
            main_window.TRAY_HIDE_HOTKEY_SETTING: self.window.tray_hide_hotkey,
            main_window.RECORD_STOP_HOTKEY_SETTING: self.window.record_stop_hotkey,
            main_window.PLAYBACK_STOP_HOTKEY_SETTING: self.window.playback_stop_hotkey,
            "startup_mode": self.window.startup_mode,
            "data_dir": new_data,
        }
        application = MagicMock()
        with (
            patch.object(main_window, "SettingsDialog") as dialog_class,
            patch.object(main_window, "save_storage_paths") as save_paths,
            patch.object(main_window.QMessageBox, "information") as information,
            patch.object(main_window.QMessageBox, "warning") as warning,
            patch.object(main_window.QApplication, "instance", return_value=application),
        ):
            accept_settings(dialog_class, values)
            self.window.show_settings()
        warning.assert_not_called()
        save_paths.assert_called_once_with(new_data)
        information.assert_called_once()
        self.assertIn("hotkeys3.db", information.call_args.args[2])
        self.assertIn("alert_notes2.db", information.call_args.args[2])
        self.assertEqual((new_data / "hotkeys2.db").read_bytes(), b"existing-numbered")
        self.assertEqual((new_data / "hotkeys3.db").read_bytes(), b"existing")
        self.assertEqual((new_data / "alert_notes2.db").read_bytes(), b"existing-notes")
        moved = Store(new_data / "hotkeys.db")
        try:
            self.assertEqual(moved.actions(), self.store.actions())
        finally:
            moved.close()
        application.quit.assert_called_once()

    def test_empty_data_folder_is_copied_and_restart_is_requested(self):
        new_data = Path(self.temp_dir.name) / "empty-data"
        new_data.mkdir()
        (self.store.data_dir / "backup_existing.json").write_text("{}", encoding="utf-8")
        values = {
            main_window.EXIT_HOTKEY_SETTING: self.window.exit_hotkey,
            main_window.MAIN_OPEN_HOTKEY_SETTING: self.window.main_open_hotkey,
            main_window.TRAY_HIDE_HOTKEY_SETTING: self.window.tray_hide_hotkey,
            main_window.RECORD_STOP_HOTKEY_SETTING: self.window.record_stop_hotkey,
            main_window.PLAYBACK_STOP_HOTKEY_SETTING: self.window.playback_stop_hotkey,
            "startup_mode": self.window.startup_mode,
            "data_dir": new_data,
        }
        application = MagicMock()
        with (
            patch.object(main_window, "SettingsDialog") as dialog_class,
            patch.object(main_window, "save_storage_paths") as save_paths,
            patch.object(main_window.QMessageBox, "information"),
            patch.object(main_window.QApplication, "instance", return_value=application),
        ):
            accept_settings(dialog_class, values)
            self.window.show_settings()
        moved = Store(new_data / "hotkeys.db")
        moved.close()
        save_paths.assert_called_once_with(new_data)
        self.assertTrue((new_data / "backup_existing.json").is_file())
        application.quit.assert_called_once()

    def test_startup_storage_failure_offers_alternate_folders(self):
        data_dir = Path(self.temp_dir.name) / "selected-data"
        replacement_store = MagicMock()
        with (
            patch.object(launcher, "Store", side_effect=[OSError("쓰기 거부"), replacement_store]) as store,
            patch.object(
                launcher.QMessageBox,
                "question",
                return_value=launcher.QMessageBox.StandardButton.Yes,
            ),
            patch.object(
                launcher.QFileDialog,
                "getExistingDirectory",
                return_value=str(data_dir),
            ),
            patch.object(launcher, "save_storage_paths") as save_paths,
        ):
            result = launcher._open_store_with_recovery()
        self.assertIs(result, replacement_store)
        save_paths.assert_called_once_with(data_dir)
        store.assert_called_with(data_dir=data_dir)

    def test_column_widths_are_interactive_and_persisted(self):
        self.window.table.setColumnWidth(3, 246)
        self.app.processEvents()
        ratios = json.loads(self.store.setting(main_window.TABLE_COLUMN_RATIOS_SETTING))
        self.assertEqual(len(ratios), 4)
        self.assertAlmostEqual(sum(ratios), 1.0, places=5)
        self.assertEqual(
            self.window.table_header.sectionResizeMode(3),
            self.window.table_header.ResizeMode.Interactive,
        )

    def test_maximize_toggle_clears_stale_resize_state(self):
        self.window.setGeometry(QRect(100, 100, 900, 600))
        self.window._resize_drag = ("stale",)
        self.window.toggle_maximized()
        self.app.processEvents()
        self.assertIsNone(self.window._resize_drag)

    def test_mouse_move_without_left_button_never_resizes(self):
        self.window.setGeometry(QRect(100, 100, 900, 600))
        original = self.window.geometry()
        self.window._resize_drag = (
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
            original.bottomRight(),
            original,
        )
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(400, 300),
            QPointF(original.right() + 200, original.bottom() + 200),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.assertFalse(self.window.eventFilter(self.window, move))
        self.assertIsNone(self.window._resize_drag)
        self.assertEqual(self.window.geometry(), original)

if __name__ == "__main__":
    unittest.main()
