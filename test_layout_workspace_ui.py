"""Qt behavior, optional settings compatibility, and workspace integration."""

import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

import excel_io
import main_window
import test_layout_workspace as runtime_tests
from layout_favorites_panel import FavoritesDialog, FavoritesPanel, WorkspaceSettings
from layout_workspace import workspace_payload
from qt_test_support import close_main_window, destroy_widget
from store import Store
from test_layout_action import _FakeRecorder, _TrackingHotkeys


class WorkspaceUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "test.db")
        self.patches = [patch.object(main_window, "HotkeyManager", _TrackingHotkeys), patch.object(main_window, "WindowsHookRecorder", _FakeRecorder)]
        for item in self.patches:
            item.start()
        self.window = main_window.MainWindow(store=self.store)
        self.entries = [{"path": str(Path(self.temp.name) / f"folder{i}"), "monitor": 1, "rect": [i * 300, 0, 300, 800], "state": "normal"} for i in range(4)]
        for entry in self.entries:
            Path(entry["path"]).mkdir()
        self.window.type_combo.setCurrentIndex(self.window.type_combo.findData("layout"))
        self.window._set_layout_rows(self.entries)

    def tearDown(self):
        close_main_window(self.window, self.app)
        for item in reversed(self.patches):
            item.stop()
        self.store.close()
        self.temp.cleanup()

    def enabled_payload(self):
        self.window.layout_workspace_settings.enabled.setChecked(True)
        return self.window._payload("layout")

    def controller_fixture(self):
        system = runtime_tests.WorkspaceTest()
        system.setUp()
        self.addCleanup(system.tearDown)
        system.runner._settings_store = self.store
        self.window.runner = system.runner
        controller = self.window.layout_workspace_controller
        controller.runtime = system.runtime
        system.runner.workspace_handler = controller.execute
        system.runner.workspace_hide_handler = controller.hide_for_window
        system.runner.workspace_reserved_handles = controller.reserved_handles
        payload = copy.deepcopy(system.payload)
        action_id = self.store.save_action({"name": "업무 배치", "hotkey": "Ctrl+Alt+L", "action_type": "layout", "active": True, "payload": payload})
        return system, controller, payload, action_id

    def test_settings_save_reload_target_restore_and_favorites(self):
        payload = self.enabled_payload()
        settings = self.window.layout_workspace_settings
        settings.target.setCurrentIndex(1)
        settings.restore.setCurrentIndex(1)
        settings.options["favorites"] = [{"name": "업무 폴더", "path": self.entries[0]["path"]}]
        settings.options["geometry"] = {"rect": [0, 0, 280, 650], "dpi": 96}
        expected = self.window._payload("layout")
        self.window._load_payload("layout", expected)
        self.assertEqual(self.window._payload("layout"), expected)
        self.assertEqual(settings.target.currentData(), payload["windows"][1]["slot_id"])
        self.assertEqual(settings.restore.currentData(), "initial")

    def test_reorder_and_remove_repair_target_without_changing_slot_ids(self):
        payload = self.enabled_payload()
        target = payload["workspace"]["target_slot"]
        buttons = self.window.layout_table.cellWidget(3, 5).findChildren(QPushButton)
        self.window._move_layout_row(next(b for b in buttons if b.text() == "↑"), -1)
        changed = self.window._payload("layout")
        self.assertEqual(changed["workspace"]["target_slot"], target)
        self.assertEqual(changed["windows"][2]["slot_id"], target)
        buttons = self.window.layout_table.cellWidget(2, 5).findChildren(QPushButton)
        self.window._delete_layout_row(next(b for b in buttons if b.text() == "삭제"))
        changed = self.window._payload("layout")
        self.assertNotEqual(changed["workspace"]["target_slot"], target)
        self.assertIn(changed["workspace"]["target_slot"], {e["slot_id"] for e in changed["windows"]})

    def test_unchecked_target_is_excluded_and_default_reselected(self):
        payload = self.enabled_payload()
        old = payload["workspace"]["target_slot"]
        self.window.layout_table.item(3, 0).setCheckState(Qt.CheckState.Unchecked)
        updated = self.window._payload("layout")
        self.assertEqual(len(updated["windows"]), 3)
        self.assertNotEqual(updated["workspace"]["target_slot"], old)

    def test_excel_preserves_all_optional_workspace_fields(self):
        payload = self.enabled_payload()
        payload["workspace"].update(favorites=[{"name": "자료", "path": self.entries[0]["path"]}], geometry={"rect": [10, 10, 280, 650], "dpi": 96})
        action = {"id": None, "name": "자료 배치", "hotkey": "Ctrl+Alt+L", "action_type": "layout", "active": True, "payload": payload}
        path = Path(self.temp.name) / "workspace.xlsx"
        excel_io.export_actions_xlsx([action], path)
        self.assertEqual(excel_io.import_actions_xlsx(path)[0]["payload"], payload)

    def test_disable_preserves_settings_for_reenable(self):
        payload = self.enabled_payload()
        payload["workspace"]["favorites"] = [{"path": self.entries[0]["path"], "name": "자료"}]
        self.window._load_payload("layout", payload)
        self.window.layout_workspace_settings.enabled.setChecked(False)
        disabled = self.window._payload("layout")
        self.assertFalse(disabled["workspace"]["enabled"])
        self.assertEqual(disabled["windows"], payload["windows"])
        self.window._load_payload("layout", disabled)
        self.window.layout_workspace_settings.enabled.setChecked(True)
        self.assertEqual(self.window._payload("layout"), payload)

    def test_first_save_then_disable_keeps_custom_restore_setting(self):
        self.enabled_payload()
        self.window.hotkey_edit.setText("Ctrl+Alt+L")
        self.window.layout_workspace_settings.restore.setCurrentIndex(1)
        with patch.object(main_window.QMessageBox, "warning") as warning:
            self.assertTrue(self.window.save_action(), str(warning.call_args))
        self.window.layout_workspace_settings.enabled.setChecked(False)
        with patch.object(main_window.QMessageBox, "warning") as warning:
            self.assertTrue(self.window.save_action(), str(warning.call_args))
        saved = json.loads(self.store.action(self.window.current_id)["payload"])
        self.assertFalse(saved["workspace"]["enabled"])
        self.assertEqual(saved["workspace"]["restore_folders"], "initial")
        self.assertTrue(all(e.get("slot_id") for e in saved["windows"]))

    def test_unsaved_workspace_settings_are_detected(self):
        self.enabled_payload()
        self.window._set_action_form_baseline()
        self.assertFalse(self.window._action_form_is_dirty())
        self.window.layout_workspace_settings.restore.setCurrentIndex(1)
        self.assertTrue(self.window._action_form_is_dirty())
        self.window.layout_workspace_settings.restore.setCurrentIndex(0)
        self.assertFalse(self.window._action_form_is_dirty())
        self.window.layout_workspace_settings.enabled.setChecked(False)
        self.assertTrue(self.window._action_form_is_dirty())

    def test_panel_saved_favorites_do_not_mark_unrelated_unsaved_name_clean(self):
        system, controller, payload, action_id = self.controller_fixture()
        controller.execute(payload, action_id)
        self.window.current_id = action_id
        self.window._load_payload("layout", payload)
        self.window._set_action_form_baseline()
        old_name = self.window.name_edit.text()
        self.window.name_edit.setText("아직 저장하지 않은 이름")
        dialog = Mock()
        dialog.exec.return_value = 1
        dialog.favorites.return_value = [{"name": "자료", "path": system.folders[0]}]
        with patch("layout_workspace_controller.FavoritesDialog", return_value=dialog):
            controller.manage_favorites(f"action:{action_id}")
        self.assertTrue(self.window._action_form_is_dirty())
        self.window.name_edit.setText(old_name)
        self.assertFalse(self.window._action_form_is_dirty())

    def test_panel_keyboard_click_busy_and_close(self):
        panel = FavoritesPanel()
        payload = self.enabled_payload()
        payload["workspace"]["favorites"] = [{"name": "자료", "path": self.entries[0]["path"]}]
        panel.configure("업무", payload)
        requests = []
        panel.folder_requested.connect(lambda slot, path: requests.append((slot, path)))
        panel.show()
        panel.list.setCurrentRow(0)
        panel.list.setFocus()
        self.app.processEvents()
        QTest.keyClick(panel.list, Qt.Key.Key_Return)
        self.assertEqual(requests, [(payload["workspace"]["target_slot"], self.entries[0]["path"])])
        panel.set_busy(True)
        panel._request(panel.list.item(0))
        self.assertEqual(len(requests), 1)
        panel.set_busy(False)
        panel.close()
        self.assertFalse(panel.isVisible())
        panel.show()
        self.assertTrue(panel.isVisible())
        destroy_widget(panel, self.app)

    def test_panel_temporary_target_survives_refresh_without_changing_default(self):
        panel = FavoritesPanel()
        payload = self.enabled_payload()
        default = payload["workspace"]["target_slot"]
        panel.configure("업무", payload)
        panel.target.setCurrentIndex(0)
        chosen = panel.target.currentData()
        panel.configure("업무", payload)
        self.assertEqual(panel.target.currentData(), chosen)
        self.assertEqual(payload["workspace"]["target_slot"], default)
        destroy_widget(panel, self.app)

    def test_favorites_edit_only_changes_list_not_disk(self):
        dialog = FavoritesDialog([{"path": self.entries[0]["path"], "name": "첫째"}, {"path": self.entries[1]["path"], "name": "둘째"}], self.window)
        dialog.list.setCurrentRow(1)
        dialog.move(-1)
        self.assertEqual(dialog.favorites()[0]["name"], "둘째")
        dialog.remove()
        self.assertEqual(len(dialog.favorites()), 1)
        self.assertTrue(Path(self.entries[1]["path"]).is_dir())
        destroy_widget(dialog, self.app)

    def test_toolbar_fit_and_stable_height_across_widths_and_scales(self):
        panel = FavoritesPanel()
        payload = self.enabled_payload()
        payload["workspace"]["favorites"] = [{"path": self.entries[0]["path"], "name": "긴 폴더 이름 " * 20}]
        for scale in (1.0, 1.25, 1.5):
            panel.apply_scale(scale)
            panel.configure("업무", payload)
            for width in (240, 280, 400):
                panel.resize(round(width * scale), round(650 * scale))
                panel.show()
                self.app.processEvents()
                self.assertLessEqual(panel.manage.geometry().right(), panel.contentsRect().right())
                self.assertLess(panel.target.geometry().right(), panel.manage.geometry().left())
                y = panel.target.y()
                panel.set_busy(True)
                self.app.processEvents()
                self.assertEqual(panel.target.y(), y)
                self.assertGreater(panel.list.height(), panel.height() * .7)
                panel.set_busy(False)
        destroy_widget(panel, self.app)

    def test_controller_group_toggle_and_covered_panel_restore(self):
        system, controller, payload, action_id = self.controller_fixture()
        with patch("layout_workspace_controller.window_is_uncovered", return_value=True):
            self.assertIn("복원", controller.execute(payload, action_id))
            self.assertIn("숨김", controller.execute(payload, action_id))
            self.assertTrue(all(not w["visible"] for w in system.windows.values()))
            self.assertIn("복원", controller.execute(payload, action_id))
        with patch("layout_workspace_controller.window_is_uncovered", return_value=False):
            self.assertIn("복원", controller.execute(payload, action_id))
            self.assertTrue(all(w["visible"] for w in system.windows.values()))

    def test_async_navigation_updates_current_path_and_keeps_initial_folder(self):
        system, controller, payload, action_id = self.controller_fixture()
        controller.execute(payload, action_id)
        key = f"action:{action_id}"
        slot = payload["workspace"]["target_slot"]
        controller.navigate(key, slot, system.folders[4])
        self.assertEqual(controller.busy_key, key)
        self.assertFalse(controller.contexts[key]["panel"].list.isEnabled())
        self.assertIn("이동 중", controller.execute(payload, action_id))
        deadline = time.monotonic() + 3
        while controller.busy_key is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(controller.busy_key)
        self.assertEqual(system.runtime.groups[key][slot]["path"], system.folders[4])
        saved = json.loads(self.store.action(action_id)["payload"])
        self.assertEqual(saved["windows"][-1]["path"], system.folders[3])

    def test_current_geometry_save_preserves_initial_paths_and_latest_settings(self):
        system, controller, payload, action_id = self.controller_fixture()
        controller.execute(payload, action_id)
        key = f"action:{action_id}"
        panel = controller.contexts[key]["panel"]
        captured = [{"hwnd": record["hwnd"], "monitor": 1, "monitor_device": "display1", "rect": [30, 40, 350, 700], "state": "normal", "dpi": 96} for record in system.runtime.groups[key].values()]
        captured.append({"hwnd": int(panel.winId()), "monitor": 1, "dpi": 96})
        newer = copy.deepcopy(payload)
        newer["workspace"]["restore_folders"] = "initial"
        row = dict(self.store.action(action_id))
        row["payload"] = newer
        self.store.save_action(row)
        with patch("layout_workspace_controller.collect_open_windows", return_value=captured), patch("layout_workspace_controller.enumerate_monitors", return_value=[runtime_tests.MONITOR]):
            controller.save_geometry(key)
        saved = json.loads(self.store.action(action_id)["payload"])
        self.assertEqual([e["path"] for e in saved["windows"]], [e["path"] for e in payload["windows"]])
        self.assertTrue(all(e["rect"] == [30, 40, 350, 700] for e in saved["windows"]))
        self.assertEqual(saved["workspace"]["restore_folders"], "initial")
        self.assertIn("geometry", saved["workspace"])

    def test_disabling_running_workspace_restores_hidden_windows_and_releases_panel(self):
        system, controller, payload, action_id = self.controller_fixture()
        controller.execute(payload, action_id)
        key = f"action:{action_id}"
        system.runtime.hide(key, payload)
        payload["workspace"]["enabled"] = False
        controller.sync_saved(action_id, "layout", payload)
        self.assertNotIn(key, controller.contexts)
        self.assertTrue(all(w["visible"] for w in system.windows.values()))
        self.assertFalse(system.markers.values)

    def test_deleting_running_workspace_restores_windows_and_clears_recovery_group(self):
        system, controller, payload, action_id = self.controller_fixture()
        controller.execute(payload, action_id)
        key = f"action:{action_id}"
        system.runtime.hide(key, payload)
        controller.remove_actions([action_id])
        self.assertNotIn(key, controller.contexts)
        self.assertNotIn(key, self.window.runner._layout_records())
        self.assertTrue(all(w["visible"] for w in system.windows.values()))


if __name__ == "__main__":
    unittest.main()
