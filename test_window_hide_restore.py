"""Focused Phase 3.6 tests using fake Explorer/Win32 providers."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from action_runner import ActionRunner, LAYOUT_WINDOW_STATE_SETTING
from main_window import MainWindow


MONITOR = {
    "number": 1,
    "device": r"\\.\DISPLAY1",
    "work_rect": (0, 0, 1920, 1040),
    "dpi": 96,
}


def entry(path):
    return {
        "kind": "explorer",
        "path": path,
        "monitor": 1,
        "rect": [20, 30, 800, 600],
        "state": "normal",
        "always_new": False,
    }


class FakeStore:
    def __init__(self, state=None):
        self.values = {
            LAYOUT_WINDOW_STATE_SETTING: json.dumps(state or {}, ensure_ascii=False),
        }

    def setting(self, key, default=""):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


class FakeExplorer:
    def __init__(self, windows):
        self.windows = {int(item["hwnd"]): dict(item) for item in windows}
        self.hidden = []
        self.shown = []
        self.next_hwnd = 900

    def handles(self):
        return set(self.windows)

    def paths(self, handles):
        return [
            {"hwnd": hwnd, "path": self.windows[hwnd]["path"]}
            for hwnd in handles if hwnd in self.windows
        ]

    def visible(self, hwnd):
        return bool(self.windows.get(hwnd, {}).get("visible", False))

    def hide(self, hwnd, path):
        if hwnd not in self.windows or self.windows[hwnd]["path"] != path:
            return False
        self.windows[hwnd]["visible"] = False
        self.hidden.append(hwnd)
        return True

    def show(self, hwnd, path):
        if hwnd not in self.windows or self.windows[hwnd]["path"] != path:
            return False
        self.windows[hwnd]["visible"] = True
        self.shown.append(hwnd)
        return True

    def open(self, path):
        self.next_hwnd += 1
        self.windows[self.next_hwnd] = {
            "hwnd": self.next_hwnd, "path": path, "visible": True,
        }


class WindowHideRestoreTest(unittest.TestCase):
    def runner(self, system, store=None, **overrides):
        options = {
            "explorer_handle_provider": system.handles,
            "explorer_path_provider": system.paths,
            "explorer_opener": system.open,
            "monitor_provider": lambda: [MONITOR],
            "window_mover": Mock(return_value=True),
            "window_visibility_provider": system.visible,
            "window_hider": system.hide,
            "window_shower": system.show,
            "settings_store": store or FakeStore(),
            "layout_timeout": 0.0,
        }
        options.update(overrides)
        return ActionRunner(**options)

    def test_all_visible_windows_are_hidden(self):
        system = FakeExplorer([
            {"hwnd": 101, "path": r"C:\One", "visible": True},
            {"hwnd": 102, "path": r"C:\Two", "visible": True},
        ])
        runner = self.runner(system)

        result = runner._run_layout(
            {"windows": [entry(r"C:\One"), entry(r"C:\Two")]}, layout_id=7,
        )

        self.assertEqual(result, "2개 창 숨김")
        self.assertEqual(system.hidden, [101, 102])

    def test_all_hidden_windows_are_shown(self):
        state = {"action:7": [
            {"hwnd": 101, "path": r"C:\One", "hidden": True},
            {"hwnd": 102, "path": r"C:\Two", "hidden": True},
        ]}
        system = FakeExplorer([
            {"hwnd": 101, "path": r"C:\One", "visible": False},
            {"hwnd": 102, "path": r"C:\Two", "visible": False},
        ])
        runner = self.runner(system, FakeStore(state))

        result = runner._run_layout(
            {"windows": [entry(r"C:\One"), entry(r"C:\Two")]}, layout_id=7,
        )

        self.assertEqual(result, "2개 창 복원")
        self.assertEqual(system.shown, [101, 102])

    def test_mixed_visibility_is_treated_as_show(self):
        state = {"action:7": [
            {"hwnd": 101, "path": r"C:\One", "hidden": True},
            {"hwnd": 102, "path": r"C:\Two", "hidden": True},
        ]}
        system = FakeExplorer([
            {"hwnd": 101, "path": r"C:\One", "visible": False},
            {"hwnd": 102, "path": r"C:\Two", "visible": True},
        ])
        runner = self.runner(system, FakeStore(state))

        result = runner._run_layout(
            {"windows": [entry(r"C:\One"), entry(r"C:\Two")]}, layout_id=7,
        )

        self.assertEqual(result, "2개 창 복원")
        self.assertEqual(system.shown, [101, 102])
        self.assertTrue(all(system.visible(hwnd) for hwnd in (101, 102)))

    def test_no_live_windows_falls_back_to_reopen_and_restore(self):
        state = {"action:7": [
            {"hwnd": 404, "path": r"C:\Gone", "hidden": True},
        ]}
        system = FakeExplorer([])
        mover = Mock(return_value=True)
        runner = self.runner(system, FakeStore(state), window_mover=mover)

        result = runner._run_layout({"windows": [entry(r"C:\Gone")]}, layout_id=7)

        self.assertEqual(result, "1개 창 복원")
        mover.assert_called_once()
        self.assertEqual(mover.call_args.args[0], 901)

    def test_application_exit_restores_all_hidden_windows_once(self):
        restore = Mock(return_value=(2, 0))
        window = SimpleNamespace(
            runner=SimpleNamespace(restore_all_hidden_windows=restore),
            _hidden_windows_exit_restored=False,
        )

        first = MainWindow._restore_hidden_windows_on_exit(window)
        second = MainWindow._restore_hidden_windows_on_exit(window)

        self.assertEqual(first, (2, 0))
        self.assertEqual(second, (0, 0))
        restore.assert_called_once_with()

    def test_reused_handle_with_different_path_is_rejected(self):
        state = {"action:7": [
            {"hwnd": 101, "path": r"C:\Original", "hidden": True},
        ]}
        store = FakeStore(state)
        system = FakeExplorer([
            {"hwnd": 101, "path": r"C:\Unrelated", "visible": False},
        ])
        shower = Mock(return_value=True)
        runner = self.runner(system, store, window_shower=shower)

        self.assertEqual(runner.restore_all_hidden_windows(), (0, 1))
        shower.assert_not_called()
        persisted = json.loads(store.setting(LAYOUT_WINDOW_STATE_SETTING))
        self.assertTrue(persisted["action:7"][0]["hidden"])

    def test_result_wording_distinguishes_hide_and_restore(self):
        system = FakeExplorer([
            {"hwnd": 101, "path": r"C:\One", "visible": True},
        ])
        runner = self.runner(system)
        payload = {"windows": [entry(r"C:\One")]}

        self.assertEqual(runner._run_layout(payload, layout_id=7), "1개 창 숨김")
        self.assertEqual(runner._run_layout(payload, layout_id=7), "1개 창 복원")


if __name__ == "__main__":
    unittest.main()
