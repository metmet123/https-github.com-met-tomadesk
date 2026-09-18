"""Headless checks for Explorer empty-area double-click navigation."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from explorer_dblclick import (
    WM_MBUTTONDOWN,
    WM_MBUTTONUP,
    ExplorerDoubleClickNavigator,
    WindowHit,
    is_explorer_file_list,
)
from main_window import MainWindow
from store import EXPLORER_DBLCLICK_SETTING, EXPLORER_MIDDLE_CLICK_SETTING, Store


EXPLORER_HWND = 101
FILE_LIST_CLASS_CHAIN = (
    "DirectUIHWND",
    "SHELLDLL_DefView",
    "CtrlNotifySink",
    "DirectUIHWND",
    "DUIViewWndClassName",
    "ShellTabWindowClass",
    "CabinetWClass",
)
NAVIGATION_TREE_CLASS_CHAIN = (
    "SysTreeView32",
    "NamespaceTreeControl",
    "CtrlNotifySink",
    "DirectUIHWND",
    "DUIViewWndClassName",
    "ShellTabWindowClass",
    "CabinetWClass",
)
HEADER_CLASS_CHAIN = ("SysHeader32",) + FILE_LIST_CLASS_CHAIN


def file_list_hit() -> WindowHit:
    return WindowHit(
        child_hwnd=103,
        top_hwnd=EXPLORER_HWND,
        top_class="CabinetWClass",
        class_chain=FILE_LIST_CLASS_CHAIN,
    )


class ExplorerDoubleClickTest(unittest.TestCase):
    def navigator(self, *, hit=None, selected_count=0, foreground=EXPLORER_HWND, **overrides):
        sender = overrides.pop("hotkey_sender", Mock())
        options = {
            "window_hit_provider": Mock(return_value=hit or file_list_hit()),
            "selection_count_provider": Mock(return_value=selected_count),
            "foreground_window_provider": Mock(return_value=foreground),
            "hotkey_sender": sender,
            "recording_provider": Mock(return_value=False),
        }
        options.update(overrides)
        return ExplorerDoubleClickNavigator(**options), sender

    def test_actual_file_list_with_shell_tab_container_sends_alt_up(self):
        self.assertTrue(is_explorer_file_list(file_list_hit()))
        navigator, sender = self.navigator()

        handled = navigator.handle_double_click(640, 480, 1234)

        self.assertTrue(handled)
        sender.assert_called_once_with("Alt+Up")

    def test_selected_item_double_click_is_ignored(self):
        navigator, sender = self.navigator(selected_count=1)

        handled = navigator.handle_double_click(640, 480, 1234)

        self.assertFalse(handled)
        sender.assert_not_called()


class ExplorerMiddleClickTest(unittest.TestCase):
    def navigator(
        self,
        *,
        hit=None,
        recording=False,
        enabled=True,
        selected_count=0,
        foreground=EXPLORER_HWND,
        **overrides,
    ):
        sender = overrides.pop("hotkey_sender", Mock())
        options = dict(
            window_hit_provider=Mock(return_value=hit or file_list_hit()),
            selection_count_provider=Mock(return_value=selected_count),
            foreground_window_provider=Mock(return_value=foreground),
            hotkey_sender=sender,
            recording_provider=Mock(return_value=recording),
            double_click_enabled=True,
            middle_click_enabled=enabled,
        )
        options.update(overrides)
        navigator = ExplorerDoubleClickNavigator(**options)
        return navigator, sender

    def test_file_list_swallows_down_and_up_then_sends_alt_up(self):
        navigator, sender = self.navigator()

        down_handled = navigator._handle_hook_event(WM_MBUTTONDOWN, 640, 480, 100)
        up_handled = navigator._handle_hook_event(WM_MBUTTONUP, 640, 480, 120)
        event = navigator._events.get_nowait()
        sent = navigator.handle_middle_click()

        self.assertTrue(down_handled)
        self.assertTrue(up_handled)
        self.assertEqual(event, ("middle", 120))
        self.assertTrue(sent)
        sender.assert_called_once_with("Alt+Up")

    def test_middle_click_worker_sends_without_initializing_com(self):
        com_initializer = Mock()
        com_uninitializer = Mock()
        navigator, sender = self.navigator(
            com_initializer=com_initializer,
            com_uninitializer=com_uninitializer,
        )
        navigator._events.put(("middle", 120))
        navigator._events.put(navigator._STOP)

        navigator._worker_loop()

        sender.assert_called_once_with("Alt+Up")
        com_initializer.assert_not_called()
        com_uninitializer.assert_not_called()

    def test_non_explorer_shell_hosts_are_not_swallowed(self):
        cases = (
            ("desktop", "Progman"),
            ("file dialog", "#32770"),
            ("other shell host", "ATL:Q-Dir"),
        )
        for label, top_class in cases:
            with self.subTest(label=label):
                hit = WindowHit(
                    203,
                    201,
                    top_class,
                    FILE_LIST_CLASS_CHAIN[:-1] + (top_class,),
                )
                selection_count = Mock(return_value=0)
                navigator, sender = self.navigator(
                    hit=hit, selection_count_provider=selection_count
                )
                self.assertFalse(navigator.handle_double_click(640, 480, 90))
                self.assertFalse(
                    navigator._handle_hook_event(WM_MBUTTONDOWN, 640, 480, 100)
                )
                self.assertFalse(
                    navigator._handle_hook_event(WM_MBUTTONUP, 640, 480, 120)
                )
                self.assertTrue(navigator._events.empty())
                selection_count.assert_not_called()
                sender.assert_not_called()

    def test_explorer_non_file_list_controls_are_not_swallowed(self):
        cases = (
            ("navigation tree", NAVIGATION_TREE_CLASS_CHAIN),
            ("column header", HEADER_CLASS_CHAIN),
        )
        for label, chain in cases:
            with self.subTest(label=label):
                hit = WindowHit(203, EXPLORER_HWND, "CabinetWClass", chain)
                selection_count = Mock(return_value=0)
                navigator, sender = self.navigator(
                    hit=hit, selection_count_provider=selection_count
                )
                self.assertFalse(navigator.handle_double_click(640, 120, 90))
                self.assertFalse(
                    navigator._handle_hook_event(WM_MBUTTONDOWN, 640, 120, 100)
                )
                self.assertFalse(
                    navigator._handle_hook_event(WM_MBUTTONUP, 640, 120, 120)
                )
                self.assertTrue(navigator._events.empty())
                selection_count.assert_not_called()
                sender.assert_not_called()

    def test_recording_and_disabled_setting_pass_through(self):
        for label, options in (
            ("recording", {"recording": True}),
            ("disabled", {"enabled": False}),
        ):
            with self.subTest(label=label):
                navigator, sender = self.navigator(**options)
                self.assertFalse(
                    navigator._handle_hook_event(WM_MBUTTONDOWN, 640, 480, 100)
                )
                self.assertFalse(
                    navigator._handle_hook_event(WM_MBUTTONUP, 640, 480, 120)
                )
                self.assertTrue(navigator._events.empty())
                sender.assert_not_called()

    def test_non_explorer_window_is_ignored(self):
        hit = WindowHit(203, 201, "Notepad", ("Edit", "Notepad"))
        selection_count = Mock(return_value=0)
        navigator, sender = self.navigator(
            hit=hit, selection_count_provider=selection_count
        )

        handled = navigator.handle_double_click(640, 480, 1234)

        self.assertFalse(handled)
        selection_count.assert_not_called()
        sender.assert_not_called()

    def test_shell_tab_window_outside_file_list_root_is_not_excluded(self):
        hit = file_list_hit()

        self.assertIn("ShellTabWindowClass", hit.class_chain)
        self.assertTrue(is_explorer_file_list(hit))

    def test_foreground_change_during_evaluation_is_ignored(self):
        foreground = {"hwnd": EXPLORER_HWND}

        def selection_count(_hwnd):
            foreground["hwnd"] = 999
            return 0

        navigator, sender = self.navigator(
            selection_count_provider=selection_count,
            foreground_window_provider=lambda: foreground["hwnd"],
        )

        handled = navigator.handle_double_click(640, 480, 1234)

        self.assertFalse(handled)
        sender.assert_not_called()

    def test_recording_stops_the_feature_before_window_lookup(self):
        window_hit_provider = Mock(return_value=file_list_hit())
        navigator, sender = self.navigator(
            window_hit_provider=window_hit_provider,
            recording_provider=Mock(return_value=True),
        )

        handled = navigator.handle_double_click(640, 480, 1234)

        self.assertFalse(handled)
        window_hit_provider.assert_not_called()
        sender.assert_not_called()


class ExplorerDoubleClickSettingTest(unittest.TestCase):
    @staticmethod
    def window_stub(store):
        window = SimpleNamespace(
            store=store,
            _recording=False,
            _explorer_double_click_navigator=None,
            _explorer_double_click_enabled=False,
            _explorer_middle_click_enabled=False,
        )
        window._set_explorer_double_click_enabled = MethodType(
            MainWindow._set_explorer_double_click_enabled, window
        )
        window._set_explorer_middle_click_enabled = MethodType(
            MainWindow._set_explorer_middle_click_enabled, window
        )
        window._sync_explorer_mouse_hook = MethodType(
            MainWindow._sync_explorer_mouse_hook, window
        )
        return window

    def test_setting_off_at_startup_does_not_install_hook(self):
        store = Mock()
        store.setting.return_value = "false"
        window = self.window_stub(store)

        with patch("main_window.ExplorerDoubleClickNavigator") as navigator_class:
            MainWindow._configure_explorer_double_click_from_store(window)

        navigator_class.assert_not_called()
        self.assertIsNone(window._explorer_double_click_navigator)

    def test_setting_on_to_off_uninstalls_hook_immediately(self):
        navigator = Mock()
        window = self.window_stub(Mock())
        window._explorer_double_click_enabled = True
        window._explorer_double_click_navigator = navigator

        MainWindow._set_explorer_double_click_enabled(window, False)

        navigator.stop.assert_called_once_with()
        self.assertIsNone(window._explorer_double_click_navigator)
        window.store.set_setting.assert_called_once_with(
            EXPLORER_DBLCLICK_SETTING, "false"
        )

    def test_setting_off_to_on_reinstalls_hook_immediately(self):
        window = self.window_stub(Mock())
        navigator = Mock()
        with patch(
            "main_window.ExplorerDoubleClickNavigator", return_value=navigator
        ) as navigator_class:
            MainWindow._set_explorer_double_click_enabled(window, True)

        navigator_class.assert_called_once_with(
            recording_provider=unittest.mock.ANY,
            double_click_enabled=True,
            middle_click_enabled=False,
        )
        navigator.start.assert_called_once_with()
        self.assertIs(window._explorer_double_click_navigator, navigator)
        window.store.set_setting.assert_called_once_with(
            EXPLORER_DBLCLICK_SETTING, "true"
        )

    def test_one_enabled_feature_keeps_shared_hook_until_both_are_off(self):
        navigator = Mock()
        window = self.window_stub(Mock())
        window._explorer_double_click_enabled = True
        window._explorer_middle_click_enabled = True
        window._explorer_double_click_navigator = navigator

        MainWindow._set_explorer_double_click_enabled(window, False)

        navigator.stop.assert_not_called()
        navigator.configure_features.assert_called_once_with(
            double_click_enabled=False, middle_click_enabled=True
        )

        MainWindow._set_explorer_middle_click_enabled(window, False)

        navigator.stop.assert_called_once_with()
        self.assertIsNone(window._explorer_double_click_navigator)

    def test_middle_click_default_is_on_when_setting_is_missing(self):
        with TemporaryDirectory() as temp:
            store = Store(path=Path(temp) / "hotkeys.db")
            try:
                window = self.window_stub(store)
                navigator = Mock()
                with patch(
                    "main_window.ExplorerDoubleClickNavigator", return_value=navigator
                ):
                    MainWindow._configure_explorer_double_click_from_store(window)
            finally:
                store.close()

        self.assertTrue(window._explorer_middle_click_enabled)
        navigator.start.assert_called_once_with()

    def test_middle_click_setting_is_saved_separately(self):
        window = self.window_stub(Mock())

        with patch("main_window.ExplorerDoubleClickNavigator") as navigator_class:
            MainWindow._set_explorer_middle_click_enabled(window, True)

        navigator_class.assert_called_once()
        window.store.set_setting.assert_called_once_with(
            EXPLORER_MIDDLE_CLICK_SETTING, "true"
        )

    def test_default_is_on_when_setting_is_missing(self):
        with TemporaryDirectory() as temp:
            store = Store(path=Path(temp) / "hotkeys.db")
            try:
                window = self.window_stub(store)
                navigator = Mock()
                with patch(
                    "main_window.ExplorerDoubleClickNavigator", return_value=navigator
                ):
                    MainWindow._configure_explorer_double_click_from_store(window)
            finally:
                store.close()

        navigator.start.assert_called_once_with()
        self.assertIs(window._explorer_double_click_navigator, navigator)


if __name__ == "__main__":
    unittest.main()
