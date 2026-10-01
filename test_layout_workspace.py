"""Workspace contracts using injected Explorer and ownership boundaries."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from action_runner import ActionRunner, LAYOUT_WINDOW_STATE_SETTING
from layout_workspace import NativeOwnership, WorkspaceRuntime, workspace_payload, window_is_uncovered


MONITOR = {"number": 1, "device": "display1", "work_rect": (0, 0, 1920, 1040), "dpi": 96}


class MemoryStore:
    def __init__(self):
        self.values = {}

    def setting(self, key, default=""):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


class Ownership:
    def __init__(self):
        self.values = {}
        self.next = 1

    def claim(self, hwnd):
        if hwnd in self.values:
            raise RuntimeError("이미 소유한 창")
        self.next += 1
        self.values[hwnd] = self.next
        return self.next

    def valid(self, hwnd, token):
        return self.values.get(hwnd) == token

    def release(self, hwnd, token):
        if self.valid(hwnd, token):
            self.values.pop(hwnd)


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folders = [str(Path(self.temp.name) / str(i)) for i in range(5)]
        for folder in self.folders:
            Path(folder).mkdir()
        self.windows = {}
        self.next_hwnd = 100
        self.store = MemoryStore()
        self.markers = Ownership()
        self.runner = ActionRunner(
            explorer_handle_provider=lambda: set(self.windows),
            explorer_path_provider=lambda handles: [{"hwnd": h, "path": self.windows[h]["path"]} for h in handles if h in self.windows],
            explorer_opener=self.open,
            monitor_provider=lambda: [MONITOR],
            window_mover=Mock(return_value=True),
            window_visibility_provider=lambda hwnd: self.windows[hwnd]["visible"],
            window_hider=lambda hwnd, path: self.visibility(hwnd, path, False),
            window_shower=lambda hwnd, path: self.visibility(hwnd, path, True),
            window_layout_matcher=lambda *args, **kwargs: True,
            window_activator=Mock(return_value=True),
            settings_store=self.store, layout_timeout=0,
        )
        self.runtime = WorkspaceRuntime(self.runner, self.markers, uncovered=lambda h, ignored: True, navigator=self.navigate)
        self.payload = workspace_payload({"windows": [
            {"path": path, "monitor": 1, "rect": [i * 300, 0, 300, 800], "state": "normal"}
            for i, path in enumerate(self.folders[:4])
        ], "workspace": {"enabled": True}})

    def tearDown(self):
        self.runtime.shutdown()
        self.temp.cleanup()

    def open(self, path):
        self.next_hwnd += 1
        self.windows[self.next_hwnd] = {"path": path, "visible": True}

    def visibility(self, hwnd, path, visible):
        if self.windows[hwnd]["path"] != path:
            return False
        self.windows[hwnd]["visible"] = visible
        return True

    def navigate(self, hwnd, path, ownership, token):
        if not ownership.valid(hwnd, token):
            raise RuntimeError("소유 확인 실패")
        self.windows[hwnd]["path"] = path
        return path

    def test_four_windows_and_default_rightmost_target(self):
        self.assertEqual(self.payload["workspace"]["target_slot"], self.payload["windows"][-1]["slot_id"])
        self.assertEqual(self.runtime.show("a", self.payload), [])
        self.assertEqual(len(self.runtime.groups["a"]), 4)
        self.assertEqual(self.runner._window_mover.call_count, 4)

    def test_keep_manual_navigation_through_hide_and_show(self):
        self.runtime.show("a", self.payload)
        record = self.runtime.groups["a"][self.payload["windows"][-1]["slot_id"]]
        hwnd = record["hwnd"]
        self.windows[hwnd]["path"] = self.folders[4]
        self.assertEqual(self.runtime.hide("a", self.payload), [])
        self.assertEqual(self.runtime.show("a", self.payload), [])
        self.assertEqual(record["hwnd"], hwnd)
        self.assertEqual(record["path"], self.folders[4])
        self.assertEqual(self.payload["windows"][-1]["path"], self.folders[3])

    def test_initial_mode_returns_to_initial_folder(self):
        self.runtime.show("a", self.payload)
        slot = self.payload["windows"][-1]["slot_id"]
        self.windows[self.runtime.groups["a"][slot]["hwnd"]]["path"] = self.folders[4]
        self.payload["workspace"]["restore_folders"] = "initial"
        self.assertEqual(self.runtime.show("a", self.payload), [])
        self.assertEqual(self.runtime.groups["a"][slot]["path"], self.folders[3])

    def test_reorder_retains_target_and_owned_hwnds(self):
        self.runtime.show("a", self.payload)
        expected = {s: r["hwnd"] for s, r in self.runtime.groups["a"].items()}
        target = self.payload["workspace"]["target_slot"]
        self.payload["windows"].reverse()
        new = workspace_payload(self.payload)
        self.runtime.show("a", new)
        self.assertEqual(expected, {s: r["hwnd"] for s, r in self.runtime.groups["a"].items()})
        self.assertEqual(new["workspace"]["target_slot"], target)

    def test_removed_hidden_slot_is_shown_before_release(self):
        self.runtime.show("a", self.payload)
        entry = self.payload["windows"].pop()
        record = self.runtime.groups["a"][entry["slot_id"]]
        self.windows[record["hwnd"]]["visible"] = False
        record["hidden"] = True
        self.runtime.refresh("a", self.payload)
        self.assertTrue(self.windows[record["hwnd"]]["visible"])
        self.assertNotIn(entry["slot_id"], self.runtime.groups["a"])
        self.assertFalse(self.markers.valid(record["hwnd"], record["token"]))

    def test_hwnd_reuse_without_marker_never_manipulates_replacement(self):
        self.runtime.show("a", self.payload)
        slot = self.payload["windows"][0]["slot_id"]
        old = self.runtime.groups["a"][slot]
        self.markers.values.pop(old["hwnd"])
        self.windows[old["hwnd"]]["path"] = self.folders[4]
        self.runtime.show("a", self.payload)
        self.assertNotEqual(old["hwnd"], self.runtime.groups["a"][slot]["hwnd"])
        self.assertEqual(self.windows[old["hwnd"]]["path"], self.folders[4])

    def test_other_workspace_does_not_reuse_owned_window(self):
        self.runtime.show("a", self.payload)
        handles_a = {r["hwnd"] for r in self.runtime.groups["a"].values()}
        self.runtime.show("b", self.payload)
        self.assertFalse(handles_a & {r["hwnd"] for r in self.runtime.groups["b"].values()})

    def test_same_path_can_have_two_distinct_slots(self):
        self.payload["windows"][1]["path"] = self.payload["windows"][0]["path"]
        self.runtime.show("a", self.payload)
        self.assertEqual(len({r["hwnd"] for r in self.runtime.groups["a"].values()}), 4)

    def test_closed_target_recreates_only_that_slot_at_selected_folder(self):
        self.runtime.show("a", self.payload)
        first, last = self.payload["windows"][0]["slot_id"], self.payload["windows"][-1]["slot_id"]
        for slot in (first, last):
            hwnd = self.runtime.groups["a"][slot]["hwnd"]
            del self.windows[hwnd]
            self.markers.values.pop(hwnd)
        before = len(self.windows)
        record = self.runtime.navigation_target("a", self.payload, last, self.folders[4])
        self.assertEqual(len(self.windows), before + 1)
        self.assertEqual(record["path"], self.folders[4])
        self.assertNotIn(first, self.runtime.groups["a"])
        self.assertEqual(self.payload["windows"][-1]["path"], self.folders[3])

    def test_invalid_favorite_does_not_open_or_change_windows(self):
        before = copy.deepcopy(self.windows)
        with self.assertRaises(ValueError):
            self.runtime.navigation_target("a", self.payload, self.payload["windows"][0]["slot_id"], str(Path(self.temp.name) / "missing"))
        self.assertEqual(self.windows, before)

    def test_wrong_opened_path_is_not_moved_or_owned(self):
        self.runner._explorer_opener = lambda path: self.open(self.folders[4])
        errors = self.runtime.show("a", self.payload)
        self.assertEqual(len(errors), 4)
        self.assertEqual(self.runtime.groups["a"], {})
        self.runner._window_mover.assert_not_called()

    def test_occluded_window_makes_group_unready(self):
        self.runtime.show("a", self.payload)
        self.assertTrue(self.runtime.at_layout("a", self.payload))
        target = next(iter(self.runtime.groups["a"].values()))["hwnd"]
        self.runtime.uncovered = lambda hwnd, ignored: hwnd != target
        self.assertFalse(self.runtime.at_layout("a", self.payload))

    def test_restart_reuses_verified_hidden_records_at_initial_paths(self):
        self.runtime.show("a", self.payload)
        self.runtime.hide("a", self.payload)
        handles = set(self.windows)
        self.runtime.shutdown()
        self.runtime = WorkspaceRuntime(self.runner, self.markers, uncovered=lambda h, ignored: True, navigator=self.navigate)
        self.runtime.show("a", self.payload)
        self.assertEqual(set(self.windows), handles)
        self.assertTrue(all(w["visible"] for w in self.windows.values()))

    def test_normalization_is_nonmutating_and_repairs_deleted_target(self):
        original = copy.deepcopy(self.payload)
        original["windows"].pop()
        new = workspace_payload(original)
        self.assertNotEqual(new["workspace"]["target_slot"], original["workspace"]["target_slot"])
        self.assertEqual(original["workspace"]["target_slot"], self.payload["workspace"]["target_slot"])

    def test_default_target_uses_monitor_position_not_monitor_number(self):
        monitors = [{"number": 1, "device": "right", "work_rect": (1920, 0, 3840, 1080)}, {"number": 2, "device": "left", "work_rect": (0, 0, 1920, 1080)}]
        data = {"windows": [{"path": self.folders[0], "monitor": 1, "rect": [0, 0, 600, 900]}, {"path": self.folders[1], "monitor": 2, "rect": [500, 0, 600, 900]}], "workspace": {"enabled": True}}
        with patch("layout_workspace.enumerate_monitors", return_value=monitors):
            payload = workspace_payload(data)
        self.assertEqual(payload["workspace"]["target_slot"], payload["windows"][0]["slot_id"])

    def test_hidden_records_follow_current_folder_for_exit_recovery(self):
        self.runtime.show("a", self.payload)
        record = next(iter(self.runtime.groups["a"].values()))
        self.windows[record["hwnd"]]["path"] = self.folders[4]
        self.runtime.hide("a", self.payload)
        records = json.loads(self.store.setting(LAYOUT_WINDOW_STATE_SETTING))["a"]
        self.assertTrue(any(r["path"] == self.folders[4] and r["hidden"] for r in records))
        self.assertEqual(self.runner.restore_all_hidden_windows(), (4, 0))

    def test_path_query_failure_preserves_hidden_ownership_and_recovery_records(self):
        self.runtime.show("a", self.payload)
        self.runtime.hide("a", self.payload)
        saved = self.store.setting(LAYOUT_WINDOW_STATE_SETTING)
        self.runner._explorer_path_provider = lambda handles: []
        with self.assertRaisesRegex(RuntimeError, "경로"):
            self.runtime.refresh("a", self.payload)
        self.assertEqual(self.store.setting(LAYOUT_WINDOW_STATE_SETTING), saved)
        self.assertEqual(len(self.runtime.groups["a"]), 4)

    def test_restart_resets_changed_owned_folder_to_initial(self):
        self.runtime.show("a", self.payload)
        slot = self.payload["windows"][-1]["slot_id"]
        hwnd = self.runtime.groups["a"][slot]["hwnd"]
        self.windows[hwnd]["path"] = self.folders[4]
        self.runtime.hide("a", self.payload)
        self.runtime.shutdown()
        self.runtime = WorkspaceRuntime(self.runner, self.markers, uncovered=lambda h, ignored: True, navigator=self.navigate)
        self.assertEqual(self.runtime.show("a", self.payload), [])
        self.assertEqual(self.runtime.groups["a"][slot]["hwnd"], hwnd)
        self.assertEqual(self.windows[hwnd]["path"], self.folders[3])

    def test_legacy_layout_cannot_take_a_workspace_owned_hwnd(self):
        self.runtime.show("a", self.payload)
        handles = set(self.windows)
        legacy = {"windows": [dict(self.payload["windows"][0])]}
        self.runner._run_layout(legacy, layout_id=12)
        self.assertEqual(len(self.windows), len(handles) + 1)
        self.assertTrue(all(w["visible"] for w in self.windows.values()))


class OcclusionTest(unittest.TestCase):
    def test_actual_order_ignores_group_but_detects_other_cover(self):
        windows = [{"hwnd": 3, "rect": (0, 0, 100, 100)}, {"hwnd": 2, "rect": (0, 0, 100, 100)}, {"hwnd": 1, "rect": (0, 0, 100, 100)}]
        with patch("layout_workspace.window_bounds", return_value=((0, 0, 100, 100), "visible")), patch("layout_workspace._native_visible_windows", return_value=windows):
            self.assertFalse(window_is_uncovered(1, {1, 2}))
            self.assertTrue(window_is_uncovered(1, {1, 2, 3}))
            windows[0]["minimized"] = True
            self.assertTrue(window_is_uncovered(1, {1, 2}))

    def test_native_ownership_property_disappears_when_window_is_destroyed(self):
        import win32gui
        marker = NativeOwnership()
        hwnd = win32gui.CreateWindowEx(0, "STATIC", "TomaDesk ownership test", 0, 0, 0, 10, 10, 0, 0, 0, None)
        try:
            token = marker.claim(hwnd)
            self.assertTrue(marker.valid(hwnd, token))
            marker.release(hwnd, token)
            self.assertFalse(marker.valid(hwnd, token))
            token = marker.claim(hwnd)
        finally:
            win32gui.DestroyWindow(hwnd)
        self.assertFalse(marker.valid(hwnd, token))


if __name__ == "__main__":
    unittest.main()
