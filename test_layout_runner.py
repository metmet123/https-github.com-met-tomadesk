"""Tests for saved Explorer window layout execution."""

import json
import unittest
from unittest.mock import Mock

from action_runner import ActionRunner


MONITOR = {
    "number": 1,
    "device": r"\\.\DISPLAY1",
    "work_rect": (0, 0, 1920, 1040),
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
            r"0개 창 복원 · 실패 1개: C:\없음 (새 탐색기 창 매칭 시간 초과)",
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
            r"2개 창 복원 · 실패 1개: C:\실패 (새 탐색기 창 매칭 시간 초과)",
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
        self.assertEqual(events[2:4], [("move", 601), ("move", 602)])
        self.assertEqual(events[4], ("match", frozenset({601, 602})))

    def test_path_lookup_for_new_handle_happens_only_after_it_is_moved(self):
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
            ("move", 702),
            ("path", {702}),
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
            ("move", 703),
            ("path", {703}),
        ])

    def test_reassigns_moved_windows_when_verified_paths_are_swapped(self):
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
            ("move", 801),
            ("move", 802),
            ("path", frozenset({801, 802})),
            ("move", 802),
            ("move", 801),
        ])

    def test_default_layout_poll_interval_is_point_zero_three_seconds(self):
        runner = ActionRunner(
            explorer_window_provider=lambda: [],
            explorer_opener=Mock(),
            monitor_provider=lambda: [MONITOR],
            window_mover=Mock(return_value=True),
        )

        self.assertEqual(runner._layout_poll_interval, 0.03)

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
