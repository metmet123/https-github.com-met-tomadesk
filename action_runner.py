import json
import hashlib
import os
import re
import subprocess
import time
import webbrowser
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from input_controller import (
    click,
    clipboard_sequence_number,
    drag,
    scroll,
    send_alt_tab,
    send_hotkey,
    send_unicode_text,
    send_virtual_key,
    wait_for_clipboard_change,
    wait_for_modifier_release,
)
from macro_playback_config import (
    validate_playback_speed,
    validate_repeat_count,
    validate_timing_mode,
)
from stop_monitor import StopHotkeyMonitor
from window_layout import (
    bring_window_to_front,
    enumerate_explorer_window_handles,
    enumerate_monitors,
    explorer_window_paths,
    hide_explorer_window,
    is_window_visible,
    move_window,
    show_explorer_window,
    window_matches_layout,
)
from window_restore import restore_minimized_target


LAYOUT_WINDOW_STATE_SETTING = "layout_hidden_windows"


class ActionRunner:
    def __init__(
        self,
        stop_hotkey: str = "Ctrl+Alt+Esc",
        *,
        explorer_window_provider=None,
        explorer_handle_provider=None,
        explorer_path_provider=None,
        explorer_opener=None,
        monitor_provider=None,
        window_mover=None,
        clock=None,
        sleeper=None,
        layout_timeout: float = 5.0,
        layout_poll_interval: float = 0.03,
        settings_store=None,
        window_visibility_provider=None,
        window_hider=None,
        window_shower=None,
        window_layout_matcher=None,
        window_activator=None,
    ):
        self.stop_requested = False
        self.workspace_handler = None
        self.workspace_hide_handler = None
        self.workspace_reserved_handles = None
        self.stop_monitor = StopHotkeyMonitor(stop_hotkey)
        if explorer_window_provider is not None:
            self._explorer_snapshot_provider = _ExplorerSnapshotProvider(explorer_window_provider)
            self._explorer_handle_provider = self._explorer_snapshot_provider.handles
            self._explorer_path_provider = self._explorer_snapshot_provider.paths
        else:
            self._explorer_snapshot_provider = None
            self._explorer_handle_provider = (
                explorer_handle_provider or enumerate_explorer_window_handles
            )
            self._explorer_path_provider = explorer_path_provider or explorer_window_paths
        self._explorer_opener = explorer_opener or _open_explorer
        self._monitor_provider = monitor_provider or enumerate_monitors
        self._window_mover = window_mover or move_window
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._layout_timeout = max(0.0, float(layout_timeout))
        self._layout_poll_interval = max(0.01, float(layout_poll_interval))
        self._settings_store = settings_store
        self._window_visibility_provider = window_visibility_provider or is_window_visible
        self._window_hider = window_hider or (
            lambda hwnd, path: hide_explorer_window(
                hwnd, path,
                handle_provider=self._explorer_handle_provider,
                path_provider=self._explorer_path_provider,
            )
        )
        self._window_shower = window_shower or (
            lambda hwnd, path: show_explorer_window(
                hwnd, path,
                handle_provider=self._explorer_handle_provider,
                path_provider=self._explorer_path_provider,
            )
        )
        self._window_layout_matcher = window_layout_matcher or window_matches_layout
        self._window_activator = window_activator or bring_window_to_front
        self._tracked_layout_hwnds = frozenset(
            int(record.get("hwnd", 0) or 0)
            for records in self._layout_records().values()
            if isinstance(records, list)
            for record in records
            if isinstance(record, dict) and int(record.get("hwnd", 0) or 0)
        )

    def set_stop_hotkey(self, hotkey: str) -> None:
        self.stop_monitor.set_hotkey(hotkey)

    def stop(self) -> None:
        self.stop_requested = True

    def _stop_requested(self) -> bool:
        return self.stop_requested or self.stop_monitor.pressed()

    def _raise_if_stopped(self) -> None:
        if self._stop_requested():
            self.stop_requested = True
            raise RuntimeError("사용자가 반복작업을 중지했습니다.")

    def _wait(self, seconds) -> None:
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            self._raise_if_stopped()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.01, remaining))

    def run(self, row) -> str:
        self.stop_requested = False
        payload = json.loads(row["payload"] or "{}")
        handlers = {
            "text": self._run_text,
            "url": self._run_url,
            "path": self._run_path,
            "macro": self._run_macro,
            "layout": self._run_layout,
        }
        handler = handlers.get(row["action_type"])
        if handler is None:
            raise ValueError("지원하지 않는 작업 유형입니다.")
        if row["action_type"] == "layout":
            try:
                layout_id = row["id"]
            except (KeyError, IndexError, TypeError):
                layout_id = None
            result = self._run_layout(payload, layout_id=layout_id)
        else:
            result = handler(payload)
        if row["action_type"] == "macro":
            return f"실행 완료 · {result}회 반복"
        if row["action_type"] == "layout":
            return str(result)
        return "실행 완료"

    def _run_text(self, payload: dict) -> None:
        self._paste_text(payload.get("text", ""), bool(payload.get("press_enter", True)))

    def _run_url(self, payload: dict) -> None:
        url = payload.get("url", "").strip()
        if not url:
            raise ValueError("URL이 비어 있습니다.")
        webbrowser.open(url)

    def _run_path(self, payload: dict) -> None:
        target = payload.get("path", "").strip()
        if not target or not Path(target).exists():
            raise ValueError("파일 또는 폴더 경로를 확인해 주세요.")
        if bool(payload.get("restore_if_minimized", False)) and restore_minimized_target(target):
            return
        os.startfile(target)

    def _run_layout(self, payload: dict, layout_id=None) -> str:
        if self.workspace_handler:
            result = self.workspace_handler(payload, layout_id)
            if result is not None:
                return result
        windows = payload.get("windows", [])
        if not isinstance(windows, list):
            windows = []
        layout_key = _layout_state_key(payload, layout_id)
        if self._settings_store is not None:
            toggled = self._toggle_layout_windows(layout_key, windows)
            if toggled is not None:
                return toggled
        try:
            monitors = list(self._monitor_provider())
            monitor_error = ""
        except Exception as exc:
            monitors = []
            monitor_error = str(exc) or exc.__class__.__name__

        restored = 0
        failures: dict[int, str] = {}
        claimed_hwnds: set[int] = self._reserved_layout_handles(layout_key)
        prepared: list[dict] = []
        try:
            known_handles = {int(hwnd) for hwnd in self._explorer_handle_provider() if int(hwnd or 0)}
            known_windows = (
                _windows_for_handles(self._explorer_path_provider(known_handles), known_handles)
                if known_handles else []
            )
            if self._settings_store is not None:
                known_windows = [
                    window for window in known_windows
                    if self._window_visibility_provider(int(window.get("hwnd", 0) or 0))
                ]
        except Exception:
            known_handles = set()
            known_windows = []

        for index, entry in enumerate(windows, start=1):
            label = _layout_entry_label(entry, index)
            try:
                if not isinstance(entry, dict):
                    raise ValueError("저장 형식 오류")
                path = str(entry.get("path", "") or "").strip()
                if not path:
                    raise ValueError("폴더 경로 없음")
                if monitor_error:
                    raise RuntimeError(f"모니터 조회 실패: {monitor_error}")
                monitor = _saved_monitor(entry, monitors)
                if monitor is None:
                    monitor = _primary_monitor(monitors)
                if monitor is None:
                    raise RuntimeError("사용 가능한 모니터 없음")

                hwnd = 0
                if not bool(entry.get("always_new", False)):
                    hwnd = _matching_explorer_hwnd(known_windows, path, claimed_hwnds)
                if hwnd:
                    claimed_hwnds.add(hwnd)
                prepared.append({
                    "index": index,
                    "entry": entry,
                    "label": label,
                    "path": path,
                    "monitor": monitor,
                    "hwnd": hwnd,
                    "moved": False,
                })
            except Exception as exc:
                reason = str(exc) or exc.__class__.__name__
                failures[index] = f"{label} ({reason})"

        pending: list[dict] = []
        for item in prepared:
            if item["hwnd"]:
                continue
            try:
                self._explorer_opener(item["path"])
                pending.append(item)
            except Exception as exc:
                reason = str(exc) or exc.__class__.__name__
                failures[item["index"]] = f"{item['label']} ({reason})"

        for item in prepared:
            if item["hwnd"] and item["index"] not in failures:
                try:
                    self._move_layout_window(item)
                    item["moved"] = True
                    restored += 1
                except Exception as exc:
                    reason = str(exc) or exc.__class__.__name__
                    failures[item["index"]] = f"{item['label']} ({reason})"

        if pending:
            self._match_new_explorer_windows(pending, known_handles, claimed_hwnds)
            for item in pending:
                if item.get("move_error") and not item["moved"]:
                    failures[item["index"]] = (
                        f"{item['label']} ({item['move_error']})"
                    )
                elif item["moved"]:
                    restored += 1

        for item in prepared:
            if item["moved"] or item["index"] in failures:
                continue
            hwnd = int(item["hwnd"] or 0)
            if not hwnd:
                failures[item["index"]] = (
                    f"{item['label']} (새 탐색기 창 경로 확인 실패)"
                )
                continue
            try:
                self._move_layout_window(item)
                item["moved"] = True
                restored += 1
            except Exception as exc:
                reason = str(exc) or exc.__class__.__name__
                failures[item["index"]] = f"{item['label']} ({reason})"

        result = f"{restored}개 창 복원"
        if failures:
            ordered_failures = [failures[index] for index in sorted(failures)]
            result += f" · 실패 {len(failures)}개: " + ", ".join(ordered_failures)
        if self._settings_store is not None:
            records = [
                {"hwnd": int(item["hwnd"]), "path": item["path"], "hidden": False}
                for item in prepared
                if item.get("moved") and int(item.get("hwnd", 0) or 0)
            ]
            self._save_layout_records(layout_key, records)
        return result

    def _toggle_layout_windows(self, layout_key: str, windows: list) -> str | None:
        saved_records = self._layout_records().get(layout_key, [])
        valid_count = sum(
            isinstance(entry, dict) and bool(str(entry.get("path", "") or "").strip())
            for entry in windows
        )
        if saved_records:
            candidates = self._verified_layout_records(saved_records)
            if not candidates:
                self._save_layout_records(layout_key, [])
                return None
            layout_entries = _layout_entries_for_records(windows, candidates)
            complete = (
                valid_count > 0
                and len(saved_records) == valid_count
                and len(candidates) == valid_count
                and len(layout_entries) == valid_count
            )
            if not complete:
                # A previous partial run must never become the whole layout.
                # Make every still-owned window visible so the normal runner
                # can reuse it, then let that path open and place the missing
                # payload entries.
                updated: list[dict] = []
                for record in candidates:
                    hwnd = int(record["hwnd"])
                    path = str(record["path"])
                    try:
                        visible = bool(self._window_visibility_provider(hwnd))
                        if record.get("hidden") or not visible:
                            visible = bool(self._window_shower(hwnd, path))
                    except Exception:
                        visible = False
                    updated.append({"hwnd": hwnd, "path": path, "hidden": not visible})
                self._save_layout_records(layout_key, updated)
                return None
        else:
            candidates = self._matching_layout_records(windows, layout_key)
            if not candidates:
                return None
            complete = len(candidates) == valid_count

        try:
            all_visible = complete and all(
                self._window_visibility_provider(int(record["hwnd"])) for record in candidates
            )
        except Exception:
            all_visible = False
        if not saved_records and not all_visible:
            # A hidden window without our persisted ownership marker may belong
            # to another app. Never un-hide it; the scratch path opens a new one.
            return None
        layout_entries = _layout_entries_for_records(windows, candidates)
        monitors: list[dict] = []
        monitor_error = ""
        try:
            monitors = list(self._monitor_provider())
        except Exception as exc:
            monitor_error = str(exc) or exc.__class__.__name__
        all_at_saved_layout = all_visible and not monitor_error and all(
            self._record_matches_saved_layout(record, layout_entries, monitors)
            for record in candidates
        )
        action = "hide" if all_at_saved_layout else "show"
        if action == "hide":
            # Record ownership before the first SW_HIDE. If persistence fails,
            # no window is hidden; if the process stops mid-loop, startup can
            # still offer safe recovery for every candidate.
            self._save_layout_records(layout_key, [
                {"hwnd": int(record["hwnd"]), "path": str(record["path"]), "hidden": True}
                for record in candidates
            ])
        changed = 0
        failures: list[str] = []
        updated: list[dict] = []
        restored: list[int] = []
        for record in candidates:
            hwnd = int(record["hwnd"])
            path = str(record["path"])
            try:
                if action == "hide":
                    succeeded = bool(self._window_hider(hwnd, path))
                else:
                    visible = bool(self._window_visibility_provider(hwnd))
                    if record.get("hidden") or not visible:
                        visible = bool(self._window_shower(hwnd, path))
                    if not visible:
                        raise RuntimeError("창 표시 전환 실패")
                    entry = layout_entries.get(hwnd)
                    if entry is None:
                        raise RuntimeError("저장된 창 배치 항목 없음")
                    if monitor_error:
                        raise RuntimeError(f"모니터 조회 실패: {monitor_error}")
                    monitor = _saved_monitor(entry, monitors) or _primary_monitor(monitors)
                    if monitor is None:
                        raise RuntimeError("사용 가능한 모니터 없음")
                    self._move_layout_window({
                        "hwnd": hwnd,
                        "entry": entry,
                        "monitor": monitor,
                    })
                    succeeded = True
            except Exception as exc:
                succeeded = False
                reason = str(exc) or exc.__class__.__name__
            else:
                reason = "창 확인 또는 표시 전환 실패"
            if succeeded:
                changed += 1
            else:
                failures.append(f"{path} ({reason})")
            hidden = action == "hide" and succeeded
            if action == "show" and not succeeded:
                try:
                    hidden = not self._window_visibility_provider(hwnd)
                except Exception:
                    hidden = True
            updated.append({"hwnd": hwnd, "path": path, "hidden": hidden})
            if action == "show" and succeeded:
                restored.append(hwnd)

        # Restored windows must come up above the app that currently has focus.
        for hwnd in restored:
            try:
                self._window_activator(hwnd)
            except Exception:
                pass
        self._save_layout_records(layout_key, updated)
        result = f"{changed}개 창 {'숨김' if action == 'hide' else '복원'}"
        if failures:
            result += f" · 실패 {len(failures)}개: " + ", ".join(failures)
        return result

    def _record_matches_saved_layout(
        self, record: dict, layout_entries: dict[int, dict], monitors: list[dict],
    ) -> bool:
        hwnd = int(record.get("hwnd", 0) or 0)
        entry = layout_entries.get(hwnd)
        if entry is None:
            return False
        monitor = _saved_monitor(entry, monitors) or _primary_monitor(monitors)
        if monitor is None:
            return False
        options = {
            "source_dpi": int(entry.get("dpi", 96) or 96),
        }
        if "work_area" in entry:
            options["source_work_area"] = entry.get("work_area")
        if "rect_basis" in entry:
            options["rect_basis"] = entry.get("rect_basis")
        try:
            return bool(self._window_layout_matcher(
                hwnd,
                entry.get("rect", [0, 0, 1, 1]),
                monitor,
                str(entry.get("state", "normal") or "normal"),
                **options,
            ))
        except Exception:
            return False

    def _reserved_layout_handles(self, layout_key):
        reserved = {
            int(record["hwnd"])
            for other, records in self._layout_records().items() if other != layout_key
            for record in self._verified_layout_records(records)
        }
        if self.workspace_reserved_handles:
            reserved.update(self.workspace_reserved_handles(layout_key))
        return reserved

    def _matching_layout_records(self, windows: list, layout_key=None) -> list[dict]:
        try:
            handles = {int(hwnd) for hwnd in self._explorer_handle_provider() if int(hwnd or 0)}
            open_windows = _windows_for_handles(self._explorer_path_provider(handles), handles)
        except Exception:
            return []
        records: list[dict] = []
        claimed: set[int] = self._reserved_layout_handles(layout_key)
        for entry in windows:
            if not isinstance(entry, dict):
                continue
            path = str(entry.get("path", "") or "").strip()
            hwnd = _matching_explorer_hwnd(open_windows, path, claimed)
            if hwnd:
                claimed.add(hwnd)
                records.append({"hwnd": hwnd, "path": path, "hidden": False})
        return records

    def _verified_layout_records(self, records: list[dict]) -> list[dict]:
        try:
            handles = {int(hwnd) for hwnd in self._explorer_handle_provider() if int(hwnd or 0)}
            paths = _windows_for_handles(self._explorer_path_provider(handles), handles)
        except Exception:
            return []
        by_handle = {
            int(window.get("hwnd", 0) or 0): window
            for window in paths if isinstance(window, dict)
        }
        verified: list[dict] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            hwnd = int(record.get("hwnd", 0) or 0)
            path = str(record.get("path", "") or "")
            actual = by_handle.get(hwnd)
            if (
                hwnd in handles and actual is not None
                and _normalized_path(actual.get("path", "")) == _normalized_path(path)
            ):
                verified.append({"hwnd": hwnd, "path": path, "hidden": bool(record.get("hidden"))})
        return verified

    def tracks_layout_window(self, hwnd: int) -> bool:
        """Fast hook-thread check against the last main-thread state snapshot."""
        return int(hwnd or 0) in self._tracked_layout_hwnds

    def hide_layout_for_window(self, hwnd: int) -> str | None:
        """Hide the complete verified saved layout that owns ``hwnd``."""
        if self.workspace_hide_handler:
            result = self.workspace_hide_handler(int(hwnd))
            if result is not None:
                return result
        target = int(hwnd or 0)
        state = self._layout_records()
        match = next(
            (
                (layout_key, records)
                for layout_key, records in state.items()
                if isinstance(records, list)
                and any(
                    isinstance(record, dict)
                    and int(record.get("hwnd", 0) or 0) == target
                    for record in records
                )
            ),
            None,
        )
        if match is None:
            return None
        layout_key, saved_records = match
        candidates = self._verified_layout_records(saved_records)
        if len(candidates) != len(saved_records) or not candidates:
            return None

        # Persist ownership for the whole group before hiding its first window.
        self._save_layout_records(layout_key, [
            {"hwnd": int(record["hwnd"]), "path": str(record["path"]), "hidden": True}
            for record in candidates
        ])
        changed = 0
        failures: list[str] = []
        updated: list[dict] = []
        for record in candidates:
            record_hwnd = int(record["hwnd"])
            path = str(record["path"])
            try:
                hidden = bool(self._window_hider(record_hwnd, path))
            except Exception as exc:
                hidden = False
                reason = str(exc) or exc.__class__.__name__
            else:
                reason = "창 확인 또는 숨김 실패"
            if hidden:
                changed += 1
            else:
                failures.append(f"{path} ({reason})")
            updated.append({"hwnd": record_hwnd, "path": path, "hidden": hidden})
        self._save_layout_records(layout_key, updated)
        result = f"{changed}개 창 숨김"
        if failures:
            result += f" · 실패 {len(failures)}개: " + ", ".join(failures)
        return result

    def restore_all_hidden_windows(self) -> tuple[int, int]:
        state = self._layout_records()
        restored = 0
        failed = 0
        for layout_key, records in list(state.items()):
            updated: list[dict] = []
            verified = {
                int(record["hwnd"]): record
                for record in self._verified_layout_records(records)
            }
            for record in records:
                if not isinstance(record, dict) or not record.get("hidden"):
                    updated.append(record)
                    continue
                hwnd = int(record.get("hwnd", 0) or 0)
                current = verified.get(hwnd)
                try:
                    shown = bool(
                        current is not None
                        and self._window_shower(hwnd, str(record.get("path", "") or ""))
                    )
                except Exception:
                    shown = False
                if not shown:
                    failed += 1
                    updated.append(record)
                else:
                    restored += 1
                    current["hidden"] = False
                    updated.append(current)
            state[layout_key] = updated
        self._write_layout_records(state)
        return restored, failed

    def alive_hidden_window_count(self) -> int:
        count = 0
        for records in self._layout_records().values():
            hidden = [record for record in records if isinstance(record, dict) and record.get("hidden")]
            count += len(self._verified_layout_records(hidden))
        return count

    def _layout_records(self) -> dict[str, list[dict]]:
        if self._settings_store is None:
            return {}
        try:
            value = json.loads(self._settings_store.setting(LAYOUT_WINDOW_STATE_SETTING, "{}"))
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _save_layout_records(self, layout_key: str, records: list[dict]) -> None:
        state = self._layout_records()
        if records:
            state[layout_key] = records
        else:
            state.pop(layout_key, None)
        self._write_layout_records(state)

    def _write_layout_records(self, state: dict[str, list[dict]]) -> None:
        self._tracked_layout_hwnds = frozenset(
            int(record.get("hwnd", 0) or 0)
            for records in state.values()
            if isinstance(records, list)
            for record in records
            if isinstance(record, dict) and int(record.get("hwnd", 0) or 0)
        )
        if self._settings_store is not None:
            self._settings_store.set_setting(
                LAYOUT_WINDOW_STATE_SETTING, json.dumps(state, ensure_ascii=False),
            )

    def _move_layout_window(self, item: dict) -> None:
        entry = item["entry"]
        move_options = {
            "source_dpi": int(entry.get("dpi", 96) or 96),
        }
        if "work_area" in entry:
            move_options["source_work_area"] = entry.get("work_area")
        if "rect_basis" in entry:
            move_options["rect_basis"] = entry.get("rect_basis")
        moved = self._window_mover(
            int(item["hwnd"]),
            entry.get("rect", [0, 0, 1, 1]),
            item["monitor"],
            str(entry.get("state", "normal") or "normal"),
            **move_options,
        )
        if not moved:
            raise RuntimeError("창 위치 적용 실패")

    def _match_new_explorer_windows(
        self, pending: list[dict], known_handles: set[int], claimed_hwnds: set[int],
    ) -> None:
        discovered: set[int] = set()
        tab_check_ready = False
        tab_checked = False
        deadline = self._clock() + self._layout_timeout
        while True:
            try:
                handles = {
                    int(hwnd) for hwnd in self._explorer_handle_provider() if int(hwnd or 0)
                }
            except Exception:
                handles = set()
            discovered.update(handles - known_handles)
            if discovered:
                try:
                    verified = _windows_for_handles(
                        self._explorer_path_provider(discovered), discovered,
                    )
                except Exception:
                    verified = []
                for item in pending:
                    if item["hwnd"]:
                        continue
                    hwnd = _matching_explorer_hwnd(verified, item["path"], claimed_hwnds)
                    if hwnd:
                        item["hwnd"] = hwnd
                        claimed_hwnds.add(hwnd)
                        self._move_new_layout_window(item)
            if tab_check_ready and not tab_checked:
                self._match_tabbed_explorer_windows(
                    pending, known_handles, claimed_hwnds,
                )
                tab_checked = True
            if all(item["hwnd"] for item in pending):
                break
            now = self._clock()
            if now >= deadline:
                break
            tab_check_ready = True
            self._sleeper(min(self._layout_poll_interval, deadline - now))

    def _match_tabbed_explorer_windows(
        self, pending: list[dict], known_handles: set[int], claimed_hwnds: set[int],
    ) -> None:
        """Reuse an existing Explorer top-level window when opening created a tab."""
        available_handles = set(known_handles) - set(claimed_hwnds)
        if not available_handles:
            return
        try:
            windows = _windows_for_handles(
                self._explorer_path_provider(available_handles), available_handles,
            )
        except Exception:
            return
        for item in pending:
            if item["hwnd"]:
                continue
            hwnd = _matching_explorer_hwnd(windows, item["path"], claimed_hwnds)
            if not hwnd:
                continue
            item["hwnd"] = hwnd
            claimed_hwnds.add(hwnd)
            self._move_new_layout_window(item)

    def _move_new_layout_window(self, item: dict) -> None:
        try:
            self._move_layout_window(item)
            item["moved"] = True
            item.pop("move_error", None)
        except Exception as exc:
            item["moved"] = False
            item["move_error"] = str(exc) or exc.__class__.__name__

    def _run_macro(self, payload: dict) -> int:
        steps = payload.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError("매크로 단계 형식이 올바르지 않습니다.")
        timing_mode = validate_timing_mode(payload.get("timing_mode", "scaled"))
        repeat_count = validate_repeat_count(payload.get("repeat_count", 1))
        speed = 1.0 if timing_mode == "recorded" else payload.get("playback_speed", 1.0)
        for _iteration in range(repeat_count):
            self._raise_if_stopped()
            if timing_mode == "fixed":
                self._run_macro_with_fixed_delay(steps, payload.get("fixed_delay_seconds", 0.3))
            else:
                self._run_macro_with_speed(steps, speed)
        return repeat_count

    def _run_macro_with_speed(self, steps: list[dict], speed) -> None:
        factor = validate_playback_speed(speed)
        for step in steps:
            self._raise_if_stopped()
            if step.get("type") == "wait":
                adjusted = dict(step)
                adjusted["seconds"] = float(step.get("seconds", 0.3)) / factor
                self._run_step(adjusted)
            else:
                self._run_step(step, playback_speed=factor)

    def _run_macro_with_fixed_delay(self, steps: list[dict], seconds) -> None:
        """Run meaningful steps with one user-selected gap between each step."""
        try:
            delay = float(seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("고정 대기 시간 형식이 올바르지 않습니다.") from exc
        if not 0.1 <= delay <= 60:
            raise ValueError("고정 대기 시간은 0.10~60.00초여야 합니다.")
        actions = [step for step in steps if step.get("type") != "wait"]
        for index, step in enumerate(actions):
            self._raise_if_stopped()
            if index:
                self._wait(delay)
            self._run_step(step)

    def _run_step(self, step: dict, playback_speed: float = 1.0) -> None:
        kind = step.get("type")
        if kind == "click":
            click(int(step.get("x", 0)), int(step.get("y", 0)), str(step.get("button", "left")))
        elif kind == "drag":
            completed = drag(int(step.get("start_x", 0)), int(step.get("start_y", 0)),
                             int(step.get("end_x", 0)), int(step.get("end_y", 0)),
                             _fast_drag_duration(step.get("duration", 0.2), playback_speed),
                             self._stop_requested)
            if not completed:
                self._raise_if_stopped()
        elif kind == "wheel":
            scroll(
                int(step.get("delta", 0)),
                str(step.get("axis", "vertical")),
                int(step.get("x", 0)),
                int(step.get("y", 0)),
            )
        elif kind == "wait":
            self._wait(float(step.get("seconds", 0.3)))
        elif kind == "text":
            self._type_recorded_text(step.get("text", ""), bool(step.get("press_enter", False)))
        elif kind == "key":
            if _is_alt_tab_step(step):
                send_alt_tab()
                return
            if step.get("vk") is not None:
                vk = int(step["vk"])
                modifiers = [int(value) for value in step.get("modifier_vks", [])]
                if vk in {0x10, 0x11, 0x12, 0x5B, 0x5C, *range(0xA0, 0xA6)} and not modifiers:
                    return
                clipboard_before_copy = clipboard_sequence_number() if _is_copy_step(vk, modifiers) else 0
                if modifiers:
                    send_virtual_key(vk, modifiers)
                else:
                    send_virtual_key(vk)
                if clipboard_before_copy:
                    wait_for_clipboard_change(clipboard_before_copy)
            else:
                self._run_legacy_key_step(str(step.get("key", "Enter")))
        else:
            raise ValueError(f"지원하지 않는 매크로 단계입니다: {kind}")

    def _run_legacy_key_step(self, key: str) -> None:
        """Replay old JSON safely, including recorder artifacts from older builds."""
        match = re.search(r"(?:^|\+)VK_([0-9A-Fa-f]{2})$", key)
        if match:
            vk = int(match.group(1), 16)
            # Old recorder versions accidentally saved left/right modifiers
            # as independent keys. They have no standalone macro action.
            if vk in {0x10, 0x11, 0x12, 0x5B, 0x5C, *range(0xA0, 0xA6)}:
                return
            send_virtual_key(vk)
            return
        send_hotkey(key)

    def _paste_text(self, text: str, press_enter: bool) -> None:
        # WM_HOTKEY can arrive before Ctrl/Alt/Shift/Win key-up messages.
        # Pasting before they are released changes Ctrl+V into another shortcut.
        wait_for_modifier_release()
        clipboard = QApplication.clipboard()
        old_text = clipboard.text()
        clipboard.setText(text)
        time.sleep(0.05)
        send_hotkey("Ctrl+V")
        if press_enter:
            send_hotkey("Enter")
        QTimer.singleShot(300, lambda: clipboard.setText(old_text))

    def _type_recorded_text(self, text: str, press_enter: bool) -> None:
        """Replay recorder text directly so it never turns into an extra paste."""
        wait_for_modifier_release()
        send_unicode_text(text)
        if press_enter:
            send_hotkey("Enter")


def _open_explorer(path: str) -> None:
    # Layout entries need distinct top-level windows.  Plain ``startfile`` can
    # be absorbed as a tab by Windows 11 Explorer, leaving a multi-window
    # layout with only one HWND to place.
    target = Path(path)
    if not target.is_dir():
        raise ValueError("폴더 경로를 확인해 주세요.")
    subprocess.Popen(["explorer.exe", "/n,", str(target.resolve())], close_fds=True)


def _layout_state_key(payload: dict, layout_id=None) -> str:
    if layout_id not in (None, ""):
        return f"action:{layout_id}"
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "payload:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _ExplorerSnapshotProvider:
    """Adapt the legacy full-window provider to split handle/path discovery."""

    def __init__(self, provider):
        self._provider = provider
        self._snapshot: list[dict] = []

    def handles(self) -> set[int]:
        self._snapshot = list(self._provider())
        return _window_handles(self._snapshot)

    def paths(self, handles) -> list[dict]:
        wanted = {int(hwnd) for hwnd in handles}
        return [
            window for window in self._snapshot
            if isinstance(window, dict) and int(window.get("hwnd", 0) or 0) in wanted
        ]


def _normalized_path(path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path)))) if path else ""


def _window_handles(windows) -> set[int]:
    return {
        int(window.get("hwnd", 0) or 0)
        for window in windows
        if isinstance(window, dict) and int(window.get("hwnd", 0) or 0)
    }


def _windows_for_handles(windows, handles) -> list[dict]:
    wanted = {int(hwnd) for hwnd in handles}
    return [
        window for window in windows
        if isinstance(window, dict) and int(window.get("hwnd", 0) or 0) in wanted
    ]


def _matching_explorer_hwnd(windows, path: str, excluded_hwnds=()) -> int:
    wanted = _normalized_path(path)
    excluded = {int(hwnd) for hwnd in excluded_hwnds}
    for window in windows:
        if not isinstance(window, dict):
            continue
        hwnd = int(window.get("hwnd", 0) or 0)
        if hwnd and hwnd not in excluded and _normalized_path(window.get("path", "")) == wanted:
            return hwnd
    return 0


def _layout_entries_for_records(windows, records) -> dict[int, dict]:
    """Pair verified handles with saved layout entries, including duplicate paths."""
    available = [
        entry for entry in windows
        if isinstance(entry, dict) and str(entry.get("path", "") or "").strip()
    ]
    matched: dict[int, dict] = {}
    used: set[int] = set()
    for record in records:
        wanted = _normalized_path(record.get("path", ""))
        for index, entry in enumerate(available):
            if index in used or _normalized_path(entry.get("path", "")) != wanted:
                continue
            used.add(index)
            matched[int(record.get("hwnd", 0) or 0)] = entry
            break
    return matched


def _saved_monitor(entry: dict, monitors) -> dict | None:
    device = str(entry.get("monitor_device", "") or "")
    if device:
        for monitor in monitors:
            if str(monitor.get("device", "") or "").casefold() == device.casefold():
                return monitor
    number = int(entry.get("monitor", 0) or 0)
    for monitor in monitors:
        if int(monitor.get("number", 0) or 0) == number:
            return monitor
    return None


def _primary_monitor(monitors) -> dict | None:
    for monitor in monitors:
        if bool(monitor.get("primary", False)):
            return monitor
    return monitors[0] if monitors else None


def _layout_entry_label(entry, index: int) -> str:
    if not isinstance(entry, dict):
        return f"항목 {index}"
    path = str(entry.get("path", "") or "").strip()
    return path or f"항목 {index}"


def _fast_drag_duration(recorded_duration, playback_speed: float = 1.0) -> float:
    """Use the fastest safe drag duration, leaving room for following waits."""
    try:
        recorded = float(recorded_duration)
        speed = float(playback_speed)
    except (TypeError, ValueError):
        recorded, speed = 0.2, 1.0
    speed = max(0.5, min(speed, 10.0))
    # Keep a substantial speed-up without making browser/grid selections skip
    # intermediate pointer movement.  Macro steps remain synchronous, so any
    # following wait begins only after the mouse button has been released.
    return min(0.35, max(0.12, recorded * 0.35 / speed))


def _is_copy_step(vk: int, modifiers: list[int]) -> bool:
    return int(vk) == 0x43 and 0x11 in {int(value) for value in modifiers}


def _is_alt_tab_step(step: dict) -> bool:
    key = str(step.get("key", "")).replace(" ", "").upper()
    if key == "ALT+TAB":
        return True
    try:
        modifiers = {int(value) for value in step.get("modifier_vks", [])}
        return int(step.get("vk", -1)) == 0x09 and 0x12 in modifiers
    except (TypeError, ValueError):
        return False
