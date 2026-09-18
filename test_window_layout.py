"""Tests for monitor-relative window layout collection and movement."""

import unittest
from unittest.mock import patch

import window_layout


class FakeWindowBoundsProvider:
    def __init__(self, raw_rect, visible_rect):
        self.raw_rect = raw_rect
        self.visible_rect = visible_rect

    def get_window_rect(self, _hwnd):
        return self.raw_rect

    def get_extended_frame_bounds(self, _hwnd):
        return self.visible_rect


class CoordinateConversionTest(unittest.TestCase):
    def test_absolute_window_rect_becomes_monitor_relative(self):
        self.assertEqual(
            window_layout.relative_rect((2020, 140, 2820, 740), (1920, 40, 3840, 1040)),
            [100, 100, 800, 600],
        )

    def test_rect_is_clamped_inside_the_work_area(self):
        self.assertEqual(
            window_layout.clamp_rect_to_work_area((-50, 900, 1300, 500), (0, 0, 1200, 1000)),
            [0, 500, 1200, 500],
        )

    def test_dpi_conversion_scales_size_and_preserves_relative_offset(self):
        self.assertEqual(
            window_layout.absolute_rect((40, 30, 800, 600), (1920, 20, 3840, 1100), 96, 144),
            [1960, 50, 1200, 900],
        )

    def test_work_area_shrink_scales_rect_and_keeps_it_inside_actual_monitor(self):
        target_work_rect = (0, 0, 1600, 900)
        scaled = window_layout.scale_rect_for_work_area(
            (960, 516, 960, 516), (1920, 1032), target_work_rect,
        )

        self.assertEqual(scaled, [800, 450, 800, 450])
        self.assertEqual(
            window_layout.clamp_rect_to_work_area(scaled, target_work_rect),
            [800, 450, 800, 450],
        )

    def test_visible_frame_is_preferred_and_raw_fallback_is_marked(self):
        visible = window_layout.window_bounds(
            10, FakeWindowBoundsProvider((-7, 0, 1927, 1047), (0, 0, 1920, 1040)),
        )
        fallback = window_layout.window_bounds(
            11, FakeWindowBoundsProvider((-7, 0, 1927, 1047), None),
        )

        self.assertEqual(visible, ((0, 0, 1920, 1040), "visible"))
        self.assertEqual(fallback, ((-7, 0, 1927, 1047), "window"))


class WindowCollectionTest(unittest.TestCase):
    def setUp(self):
        self.monitors = [
            {
                "handle": 11,
                "number": 1,
                "device": r"\\.\DISPLAY1",
                "monitor_rect": (0, 0, 1920, 1080),
                "work_rect": (0, 0, 1920, 1040),
                "primary": True,
                "dpi": 96,
            },
            {
                "handle": 22,
                "number": 2,
                "device": r"\\.\DISPLAY2",
                "monitor_rect": (1920, 0, 3840, 1080),
                "work_rect": (1920, 40, 3840, 1080),
                "primary": False,
                "dpi": 144,
            },
        ]

    def test_collects_window_identity_state_monitor_and_explorer_path(self):
        windows = [
            {
                "hwnd": 101,
                "visible": True,
                "title": "제출 자료",
                "program_path": r"C:\Windows\explorer.exe",
                "rect": (2020, 140, 2820, 740),
                "rect_basis": "visible",
                "monitor_handle": 22,
                "minimized": False,
                "maximized": True,
                "dpi": 144,
            },
            {"hwnd": 102, "visible": False, "rect": (0, 0, 100, 100)},
        ]
        entries = window_layout.collect_open_windows(
            window_provider=lambda: windows,
            monitor_provider=lambda: self.monitors,
            explorer_provider=lambda: [{"hwnd": 101, "path": r"D:\제출", "title": "제출"}],
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["hwnd"], 101)
        self.assertEqual(entries[0]["program_path"], r"C:\Windows\explorer.exe")
        self.assertEqual(entries[0]["explorer_path"], r"D:\제출")
        self.assertEqual(entries[0]["monitor"], 2)
        self.assertEqual(entries[0]["monitor_device"], r"\\.\DISPLAY2")
        self.assertEqual(entries[0]["work_area"], [1920, 1040])
        self.assertEqual(entries[0]["rect"], [100, 100, 800, 600])
        self.assertEqual(entries[0]["rect_basis"], "visible")
        self.assertEqual(entries[0]["state"], "maximized")
        self.assertEqual(entries[0]["dpi"], 144)

    def test_geometry_selects_monitor_when_handle_is_unavailable(self):
        entry = window_layout.describe_windows(
            [{"hwnd": 201, "rect": (2100, 100, 2500, 500), "title": "창"}],
            self.monitors,
        )[0]
        self.assertEqual(entry["monitor"], 2)


class WindowMovementTest(unittest.TestCase):
    def test_saved_125_and_150_percent_sizes_restore_at_100_percent(self):
        monitor = {"work_rect": (0, 0, 1920, 1032), "dpi": 96}
        for source_dpi, expected_width, expected_height in (
            (120, 640, 480),
            (144, 533, 400),
        ):
            with self.subTest(source_dpi=source_dpi), patch.object(
                window_layout._USER32, "ShowWindow", return_value=True,
            ), patch.object(
                window_layout._USER32, "SetWindowPos", return_value=True,
            ) as set_position:
                self.assertTrue(window_layout.move_window(
                    305, (20, 30, 800, 600), monitor,
                    source_dpi=source_dpi, rect_basis="visible",
                ))
            self.assertEqual(
                set_position.call_args.args[2:6],
                (20, 30, expected_width, expected_height),
            )

    def test_visible_edge_rect_adds_live_borders_after_clamping(self):
        monitor = {"work_rect": (0, 0, 1920, 1040), "dpi": 96}
        bounds = FakeWindowBoundsProvider(
            (-7, 0, 1927, 1047), (0, 0, 1920, 1040),
        )
        with patch.object(window_layout._USER32, "ShowWindow", return_value=True), patch.object(
            window_layout._USER32, "SetWindowPos", return_value=True,
        ) as set_position:
            self.assertTrue(window_layout.move_window(
                300, (0, 0, 1920, 1040), monitor,
                rect_basis="visible", api_provider=bounds,
            ))

        set_position.assert_called_once_with(
            300, 0, -7, 0, 1934, 1047,
            window_layout.SWP_NOZORDER | window_layout.SWP_NOACTIVATE
            | window_layout.SWP_ASYNCWINDOWPOS,
        )

    def test_legacy_raw_rect_is_converted_before_clamping(self):
        monitor = {"work_rect": (0, 0, 1920, 1040), "dpi": 96}
        bounds = FakeWindowBoundsProvider(
            (-7, 0, 1927, 1047), (0, 0, 1920, 1040),
        )
        with patch.object(window_layout._USER32, "ShowWindow", return_value=True), patch.object(
            window_layout._USER32, "SetWindowPos", return_value=True,
        ) as set_position:
            self.assertTrue(window_layout.move_window(
                303, (-7, 0, 1934, 1047), monitor, api_provider=bounds,
            ))

        self.assertEqual(set_position.call_args.args[2:6], (-7, 0, 1934, 1047))

    def test_missing_visible_bounds_falls_back_to_previous_movement(self):
        monitor = {"work_rect": (0, 0, 1920, 1040), "dpi": 96}
        bounds = FakeWindowBoundsProvider((-7, 0, 1927, 1047), None)
        with patch.object(window_layout._USER32, "ShowWindow", return_value=True), patch.object(
            window_layout._USER32, "SetWindowPos", return_value=True,
        ) as set_position:
            self.assertTrue(window_layout.move_window(
                304, (-7, 0, 1934, 1047), monitor,
                rect_basis="window", api_provider=bounds,
            ))

        self.assertEqual(set_position.call_args.args[2:6], (0, 0, 1920, 1040))

    def test_moves_with_clamped_dpi_scaled_coordinates_and_restores_state(self):
        monitor = {"work_rect": (1920, 40, 3120, 940), "dpi": 144}
        with patch.object(window_layout._USER32, "ShowWindow", return_value=True) as show, patch.object(
            window_layout._USER32, "SetWindowPos", return_value=True,
        ) as set_position:
            self.assertTrue(window_layout.move_window(
                301, (1000, 700, 800, 600), monitor, "normal", source_dpi=96,
                rect_basis="visible",
            ))

        set_position.assert_called_once_with(
            301, 0, 1920, 40, 1200, 900,
            window_layout.SWP_NOZORDER | window_layout.SWP_NOACTIVATE
            | window_layout.SWP_ASYNCWINDOWPOS,
        )
        self.assertEqual(
            show.call_args_list,
            [unittest.mock.call(301, window_layout.SW_RESTORE),
             unittest.mock.call(301, window_layout.SW_SHOWNORMAL)],
        )

    def test_does_not_apply_state_when_movement_fails(self):
        monitor = {"work_rect": (0, 0, 1000, 800), "dpi": 96}
        with patch.object(window_layout._USER32, "ShowWindow", return_value=True) as show, patch.object(
            window_layout._USER32, "SetWindowPos", return_value=False,
        ):
            self.assertFalse(window_layout.move_window(302, (0, 0, 500, 400), monitor))
        show.assert_called_once_with(302, window_layout.SW_RESTORE)

    def test_restores_maximized_and_minimized_states(self):
        monitor = {"work_rect": (0, 0, 1920, 1032), "dpi": 96}
        for state, command in (
            ("maximized", window_layout.SW_SHOWMAXIMIZED),
            ("minimized", window_layout.SW_SHOWMINIMIZED),
        ):
            with self.subTest(state=state), patch.object(
                window_layout._USER32, "ShowWindow", return_value=True,
            ) as show, patch.object(
                window_layout._USER32, "SetWindowPos", return_value=True,
            ):
                self.assertTrue(window_layout.move_window(
                    306, (20, 30, 800, 600), monitor, state,
                    rect_basis="visible",
                ))
            self.assertEqual(
                show.call_args_list,
                [unittest.mock.call(306, window_layout.SW_RESTORE),
                 unittest.mock.call(306, command)],
            )


if __name__ == "__main__":
    unittest.main()
