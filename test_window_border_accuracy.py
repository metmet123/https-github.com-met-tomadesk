"""Focused tests for visible-frame layout save and border-aware restore."""

import unittest
from unittest.mock import patch

import window_layout


MONITOR = {
    "handle": 11,
    "number": 1,
    "device": r"\\.\DISPLAY1",
    "monitor_rect": (0, 0, 1920, 1080),
    "work_rect": (0, 0, 1920, 1040),
    "primary": True,
    "dpi": 96,
}


class FakeWindowsApi:
    def __init__(self, raw_rect=(-7, 0, 967, 1039), visible_rect=(0, 0, 960, 1032)):
        self.raw_rect = raw_rect
        self.visible_rect = visible_rect
        self.window_rect_calls = 0
        self.frame_rect_calls = 0

    def get_window_rect(self, _hwnd):
        self.window_rect_calls += 1
        return self.raw_rect

    def get_extended_frame_bounds(self, _hwnd):
        self.frame_rect_calls += 1
        return self.visible_rect


class VisibleBoundsSaveTest(unittest.TestCase):
    def test_edge_window_saves_in_visible_bounds_terms(self):
        api = FakeWindowsApi()
        rect, rect_basis = window_layout.window_bounds(101, api_provider=api)
        entry = window_layout.describe_windows(
            [{
                "hwnd": 101,
                "visible": True,
                "rect": rect,
                "rect_basis": rect_basis,
                "monitor_handle": 11,
            }],
            [MONITOR],
        )[0]

        self.assertEqual(entry["rect"], [0, 0, 960, 1032])
        self.assertEqual(entry["rect_basis"], window_layout.RECT_BASIS_VISIBLE)

    def test_dwm_failure_falls_back_to_marked_window_rect(self):
        api = FakeWindowsApi(visible_rect=None)
        rect, rect_basis = window_layout.window_bounds(101, api_provider=api)
        entry = window_layout.describe_windows(
            [{
                "hwnd": 101,
                "visible": True,
                "rect": rect,
                "rect_basis": rect_basis,
                "monitor_handle": 11,
            }],
            [MONITOR],
        )[0]

        self.assertEqual(entry["rect"], [-7, 0, 974, 1039])
        self.assertEqual(
            entry["rect_basis"], window_layout.RECT_BASIS_WINDOW_RECT_FALLBACK,
        )


class BorderAwareRestoreTest(unittest.TestCase):
    def _move(self, rect, rect_basis=None, state="normal", api=None):
        with patch.object(window_layout._USER32, "ShowWindow", return_value=True) as show, patch.object(
            window_layout._USER32, "SetWindowPos", return_value=True,
        ) as set_position:
            result = window_layout.move_window(
                301,
                rect,
                MONITOR,
                state,
                rect_basis=rect_basis,
                api_provider=api or FakeWindowsApi(),
            )
        return result, show, set_position

    def test_restore_readds_live_border_thickness(self):
        result, _show, set_position = self._move(
            [0, 0, 960, 1032], window_layout.RECT_BASIS_VISIBLE,
        )

        self.assertTrue(result)
        set_position.assert_called_once_with(
            301, 0, -7, 0, 974, 1039,
            window_layout.SWP_NOZORDER | window_layout.SWP_NOACTIVATE
            | window_layout.SWP_ASYNCWINDOWPOS,
        )

    def test_legacy_unmarked_rect_converts_to_same_raw_position(self):
        result, _show, set_position = self._move([-7, 0, 974, 1039])

        self.assertTrue(result)
        set_position.assert_called_once_with(
            301, 0, -7, 0, 974, 1039,
            window_layout.SWP_NOZORDER | window_layout.SWP_NOACTIVATE
            | window_layout.SWP_ASYNCWINDOWPOS,
        )

    def test_maximized_entry_keeps_existing_move_then_state_behavior(self):
        api = FakeWindowsApi()
        result, show, set_position = self._move(
            [0, 0, 960, 1032], window_layout.RECT_BASIS_VISIBLE, "maximized", api,
        )

        self.assertTrue(result)
        set_position.assert_called_once()
        self.assertEqual(
            show.call_args_list,
            [unittest.mock.call(301, window_layout.SW_RESTORE),
             unittest.mock.call(301, window_layout.SW_SHOWMAXIMIZED)],
        )
        self.assertEqual(api.window_rect_calls, 1)
        self.assertEqual(api.frame_rect_calls, 1)


if __name__ == "__main__":
    unittest.main()
