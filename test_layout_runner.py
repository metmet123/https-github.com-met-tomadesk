"""Tests for saved Explorer window layout execution."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from action_runner import ActionRunner, _open_explorer
from window_layout import target_window_rect


MONITOR = {
    "number": 1,
    "device": r"\\.\DISPLAY1",
    "work_rect": (0, 0, 1920, 1032),
    "primary": True,
    "dpi": 96,
}


def layout_entry(path, *, always_new=False, monitor=1):
    return {
        "kind": "explorer",
        "path": path,
        "monitor": monitor,
        "rect": [20, 30, 800, 600],
        "state": "normal",
        "always_new": always_new,
    }


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += float(seconds)


class LayoutRunnerTest(unittest.TestCase):
    def runner(self, **overrides):
        options = {
            "explorer_window_provider": lambda: [],
            "explorer_opener": Mock(),
            "monitor_provider": lambda: [MONITOR],
            "window_mover": Mock(return_value=True),
            "layout_timeout": 0.3,
            "layout_poll_interval": 0.1,
        }
        options.update(overrides)
        return ActionRunner(**options)

    def test_reuses_an_existing_window_and_moves_it(self):
        opener = Mock()
        mover = Mock(return_value=True)
        runner = self.runner(
            explorer_window_provider=lambda: [{"hwnd": 101, "path": r"D:\제출"}],
            explorer_opener=opener,
            window_mover=mover,
        )

        result = runner._run_layout({"windows": [layout_entry(r"D:\제출")]})

        self.assertEqual(result, "1개 창 복원")
        opener.assert_not_called()
        mover.assert_called_once_with(
            101, [20, 30, 800, 600], MONITOR, "normal", source_dpi=96,
        )

    def test_forwards_visible_rect_basis_to_the_window_mover(self):
        mover = Mock(return_value=True)
        saved = layout_entry(r"D:\visible")
        saved["rect_basis"] = "visible"
        runner = self.runner(
            explorer_window_provider=lambda: [{"hwnd": 102, "path": r"D:\visible"}],
            window_mover=mover,
        )

        self.assertEqual(runner._run_layout({"windows": [saved]}), "1개 창 복원")
        mover.assert_called_once_with(
            102, [20, 30, 800, 600], MONITOR, "normal",
            source_dpi=96, rect_basis="visible",
        )

    def test_missing_saved_monitor_falls_back_inside_primary_work_area(self):
        restored_rects = []

        def move(_hwnd, rect, monitor, _state, **options):
            restored_rects.append(target_window_rect(
                rect,
                monitor["work_rect"],
                source_dpi=options.get("source_dpi", 96),
                source_work_area=options.get("source_work_area"),
            ))
            return True

        saved = layout_entry(r"D:\사라진보조", monitor=2)
        saved.update({
            "monitor_device": r"\\.\DISPLAY2",
            "work_area": [1920, 1032],
            "rect": [1800, 900, 500, 400],
        })
        runner = self.runner(
            explorer_window_provider=lambda: [
                {"hwnd": 103, "path": r"D:\사라진보조"},
            ],
            window_mover=move,
        )

        self.assertEqual(runner._run_layout({"windows": [saved]}), "1개 창 복원")
        self.assertEqual(restored_rects, [[1420, 632, 500, 400]])

    def test_forwards_saved_dpi_work_area_and_window_state(self):
        mover = Mock(return_value=True)
        saved = layout_entry(r"D:\배율")
        saved.update({
            "dpi": 144,
            "work_area": [1920, 1032],
            "state": "minimized",
        })
        runner = self.runner(
            explorer_window_provider=lambda: [{"hwnd": 104, "path": r"D:\배율"}],
            window_mover=mover,
        )

        self.assertEqual(runner._run_layout({"windows": [saved]}), "1개 창 복원")
        mover.assert_called_once_with(
            104, [20, 30, 800, 600], MONITOR, "minimized",
            source_dpi=144, source_work_area=[1920, 1032],
        )

    def test_opens_and_polls_until_a_new_matching_window_appears(self):
        clock = FakeClock()
        responses = [[], [], [{"hwnd": 202, "path": r"C:\자료"}]]

        def windows():
            return responses.pop(0) if len(responses) > 1 else responses[0]

        opener = Mock()
        mover = Mock(return_value=True)
        runner = self.runner(
            explorer_window_provider=windows,
            explorer_opener=opener,
            window_mover=mover,
            clock=clock.now,
            sleeper=clock.sleep,
        )

        self.assertEqual(
            runner._run_layout({"windows": [layout_entry(r"C:\자료")]}),
            "1개 창 복원",
        )
        opener.assert_called_once_with(r"C:\자료")
        mover.assert_called_once()
        self.assertEqual(mover.call_args.args[0], 202)
        self.assertAlmostEqual(clock.value, 0.1)

    def test_reports_timeout_without_stopping_the_layout(self):
        clock = FakeClock()
        opener = Mock()
        mover = Mock(return_value=True)
        runner = self.runner(
            explorer_opener=opener,
            window_mover=mover,
            clock=clock.now,
            sleeper=clock.sleep,
        )

        result = runner._run_layout({"windows": [layout_entry(r"C:\없음")]})

        self.assertEqual(
            result,
            r"0개 창 복원 · 실패 1개: C:\없음 (새 탐색기 창 경로 확인 실패)",
        )
        opener.assert_called_once_with(r"C:\없음")
        mover.assert_not_called()
        self.assertAlmostEqual(clock.value, 0.3)

    def test_mixed_success_and_failure_continues_in_saved_order(self):
        clock = FakeClock()
        open_windows = [{"hwnd": 301, "path": r"C:\기존"}]
        opened_paths = []

        def open_explorer(path):
            opened_paths.append(path)
            if path == r"C:\신규":
                open_windows.append({"hwnd": 302, "path": path})

        mover = Mock(return_value=True)
        runner = self.runner(
            explorer_window_provider=lambda: list(open_windows),
            explorer_opener=open_explorer,
            window_mover=mover,
            clock=clock.now,
            sleeper=clock.sleep,
        )
        payload = {"windows": [
            layout_entry(r"C:\기존"),
            layout_entry(r"C:\신규"),
            layout_entry(r"C:\실패"),
        ]}

        result = runner._run_layout(payload)

        self.assertEqual(
            result,
            r"2개 창 복원 · 실패 1개: C:\실패 (새 탐색기 창 경로 확인 실패)",
        )
        self.assertEqual(opened_paths, [r"C:\신규", r"C:\실패"])
        self.assertEqual([call.args[0] for call in mover.call_args_list], [301, 302])

    def test_always_new_does_not_reuse_a_matching_existing_window(self):
        open_windows = [{"hwnd": 401, "path": r"D:\같은폴더"}]

        def open_explorer(path):
            open_windows.append({"hwnd": 402, "path": path})

        mover = Mock(return_value=True)
        runner = self.runner(
            explorer_window_provider=lambda: list(open_windows),
            explorer_opener=open_explorer,
            window_mover=mover,
        )

        result = runner._run_layout({
            "windows": [layout_entry(r"D:\같은폴더", always_new=True)],
        })

        self.assertEqual(result, "1개 창 복원")
        self.assertEqual(mover.call_args.args[0], 402)

    def test_opens_all_new_windows_before_matching_or_moving(self):
        events = []
        opened = []

        def open_explorer(path):
            events.append(("open", path))
            opened.append(path)

        def handles():
            if len(opened) == 2:
                return {601, 602}
            return set()

        def paths(requested):
            events.append(("match", frozenset(requested)))
            return [
                {"hwnd": 601, "path": r"C:\첫째"},
                {"hwnd": 602, "path": r"C:\둘째"},
            ]

        def move(hwnd, *_args, **_kwargs):
            events.append(("move", hwnd))
            return True

        runner = self.runner(
            explorer_window_provider=None,
            explorer_handle_provider=handles,
            explorer_path_provider=paths,
            explorer_opener=open_explorer,
            window_mover=move,
        )

        result = runner._run_layout({"windows": [
            layout_entry(r"C:\첫째"),
            layout_entry(r"C:\둘째"),
        ]})

        self.assertEqual(result, "2개 창 복원")
        self.assertEqual(events[:2], [
            ("open", r"C:\첫째"),
            ("open", r"C:\둘째"),
        ])
        self.assertEqual(events[2], ("match", frozenset({601, 602})))
        self.assertEqual(events[3:5], [("move", 601), ("move", 602)])

    def test_new_handle_is_moved_only_after_its_path_is_verified(self):
        clock = FakeClock()
        handle_responses = [{701}, {701}, {701, 702}]
        events = []

        def handles():
            return handle_responses.pop(0) if len(handle_responses) > 1 else handle_responses[0]

        def paths(requested):
            requested = set(requested)
            events.append(("path", requested))
            if requested == {701}:
                return [{"hwnd": 701, "path": r"C:\기존"}]
            if requested == {702}:
                return [{"hwnd": 702, "path": r"C:\신규"}]
            return []

        def move(hwnd, *_args, **_kwargs):
            events.append(("move", hwnd))
            return True

        runner = self.runner(
            explorer_window_provider=None,
            explorer_handle_provider=handles,
            explorer_path_provider=paths,
            explorer_opener=Mock(),
            window_mover=move,
            clock=clock.now,
            sleeper=clock.sleep,
        )

        result = runner._run_layout({
            "windows": [layout_entry(r"C:\신규", always_new=True)],
        })

        self.assertEqual(result, "1개 창 복원")
        self.assertEqual(events, [
            ("path", {701}),
            ("path", {702}),
            ("move", 702),
            ("path", {701}),
        ])

    def test_waiting_for_a_handle_does_not_call_path_provider(self):
        clock = FakeClock()
        events = []
        handle_responses = [set(), set(), {703}]

        def handles():
            events.append(("handles", None))
            return handle_responses.pop(0) if len(handle_responses) > 1 else handle_responses[0]

        def paths(requested):
            events.append(("path", set(requested)))
            return [{"hwnd": 703, "path": r"C:\신규"}]

        def move(hwnd, *_args, **_kwargs):
            events.append(("move", hwnd))
            return True

        runner = self.runner(
            explorer_window_provider=None,
            explorer_handle_provider=handles,
            explorer_path_provider=paths,
            explorer_opener=Mock(),
            window_mover=move,
            clock=clock.now,
            sleeper=clock.sleep,
        )

        result = runner._run_layout({"windows": [layout_entry(r"C:\신규")]})

        self.assertEqual(result, "1개 창 복원")
        self.assertEqual(events, [
            ("handles", None),
            ("handles", None),
            ("handles", None),
            ("path", {703}),
            ("move", 703),
        ])

    def test_reuses_existing_window_when_explorer_opens_a_tab(self):
        clock = FakeClock()
        tab_opened = False
        mover = Mock(return_value=True)

        def open_explorer(_path):
            nonlocal tab_opened
            tab_opened = True

        def paths(requested):
            path = r"C:\탭대상" if tab_opened else r"C:\기존"
            return [{"hwnd": 704, "path": path}] if 704 in set(requested) else []

        runner = self.runner(
            explorer_window_provider=None,
            explorer_handle_provider=lambda: {704},
            explorer_path_provider=paths,
            explorer_opener=open_explorer,
            window_mover=mover,
            clock=clock.now,
            sleeper=clock.sleep,
        )

        result = runner._run_layout({
            "windows": [layout_entry(r"C:\탭대상", always_new=True)],
        })

        self.assertEqual(result, "1개 창 복원")
        self.assertEqual(mover.call_args.args[0], 704)
        self.assertAlmostEqual(clock.value, 0.1)

    def test_new_windows_are_mapped_by_verified_path_not_handle_order(self):
        events = []
        handle_responses = [set(), {801, 802}]

        def handles():
            return handle_responses.pop(0) if len(handle_responses) > 1 else handle_responses[0]

        def paths(requested):
            events.append(("path", frozenset(requested)))
            return [
                {"hwnd": 801, "path": r"C:\둘째"},
                {"hwnd": 802, "path": r"C:\첫째"},
            ]

        def move(hwnd, *_args, **_kwargs):
            events.append(("move", hwnd))
            return True

        runner = self.runner(
            explorer_window_provider=None,
            explorer_handle_provider=handles,
            explorer_path_provider=paths,
            explorer_opener=Mock(),
            window_mover=move,
        )

        result = runner._run_layout({"windows": [
            layout_entry(r"C:\첫째"),
            layout_entry(r"C:\둘째"),
        ]})

        self.assertEqual(result, "2개 창 복원")
        self.assertEqual(events, [
            ("path", frozenset({801, 802})),
            ("move", 802),
            ("move", 801),
        ])

    def test_wrong_folder_windows_are_neither_moved_nor_owned(self):
        from test_window_hide_restore import FakeStore

        store = FakeStore()
        mover = Mock(return_value=True)
        windows = []

        def open_wrong_folder(_path):
            windows.append({"hwnd": 810 + len(windows), "path": r"C:\Documents"})

        runner = self.runner(
            explorer_window_provider=lambda: list(windows),
            explorer_opener=open_wrong_folder,
            window_mover=mover,
            settings_store=store,
            window_visibility_provider=lambda _hwnd: True,
            layout_timeout=0.03,
        )

        result = runner._run_layout({"windows": [
            layout_entry(r"C:\Downloads"), layout_entry(r"C:\Submit"),
        ]}, layout_id=7)

        self.assertIn("0개 창 복원 · 실패 2개", result)
        mover.assert_not_called()
        self.assertEqual(json.loads(store.setting("layout_hidden_windows")), {})

    def test_partial_verified_new_window_retries_the_missing_folder(self):
        from test_window_hide_restore import FakeStore

        windows = []
        attempts = []

        def open_explorer(path):
            attempts.append(path)
            actual = path if path == r"C:\Downloads" or attempts.count(path) > 1 else r"C:\Documents"
            windows.append({"hwnd": 820 + len(windows), "path": actual})

        store = FakeStore()
        mover = Mock(return_value=True)
        runner = self.runner(
            explorer_window_provider=lambda: list(windows),
            explorer_opener=open_explorer,
            window_mover=mover,
            settings_store=store,
            window_visibility_provider=lambda _hwnd: True,
            window_layout_matcher=lambda *_args, **_kwargs: False,
            layout_timeout=0.03,
        )
        payload = {"windows": [
            layout_entry(r"C:\Downloads"), layout_entry(r"C:\Submit"),
        ]}

        first = runner._run_layout(payload, layout_id=7)
        self.assertIn("1개 창 복원 · 실패 1개", first)
        self.assertEqual([call.args[0] for call in mover.call_args_list], [820])
        self.assertEqual(len(json.loads(store.setting("layout_hidden_windows"))["action:7"]), 1)

        second = runner._run_layout(payload, layout_id=7)
        self.assertEqual(second, "2개 창 복원")
        self.assertEqual([call.args[0] for call in mover.call_args_list], [820, 820, 822])
        self.assertEqual(attempts, [r"C:\Downloads", r"C:\Submit", r"C:\Submit"])

    def test_default_layout_poll_interval_is_point_zero_three_seconds(self):
        runner = ActionRunner(
            explorer_window_provider=lambda: [],
            explorer_opener=Mock(),
            monitor_provider=lambda: [MONITOR],
            window_mover=Mock(return_value=True),
        )

        self.assertEqual(runner._layout_poll_interval, 0.03)

    def test_default_explorer_opener_requests_a_new_top_level_window(self):
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "한글 제출 폴더"
            target.mkdir()
            with patch("action_runner.subprocess.Popen") as popen:
                _open_explorer(str(target))
            popen.assert_called_once_with(
                ["explorer.exe", "/n,", str(target.resolve())], close_fds=True,
            )
            popen.reset_mock()
            with self.assertRaisesRegex(ValueError, "폴더 경로"):
                _open_explorer(str(target / "없는 폴더"))
            popen.assert_not_called()

    def test_run_routes_layout_and_returns_the_layout_result_format(self):
        runner = self.runner(
            explorer_window_provider=lambda: [{"hwnd": 501, "path": r"C:\업무"}],
        )
        row = {
            "action_type": "layout",
            "payload": json.dumps({"windows": [layout_entry(r"C:\업무")]}, ensure_ascii=False),
        }

        self.assertEqual(runner.run(row), "1개 창 복원")


if __name__ == "__main__":
    unittest.main()
