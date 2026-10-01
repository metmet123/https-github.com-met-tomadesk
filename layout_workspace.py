"""Explorer workspaces: stable slots, scoped ownership, and folder navigation."""

import copy
import os
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from window_layout import (
    _USER32, _native_visible_windows, enumerate_explorer_window_handles,
    enumerate_monitors, explorer_window_paths, window_bounds,
)


def normalized_path(path):
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path)))) if path else ""


def workspace_payload(payload):
    """Normalize optional fields without changing the input or legacy payloads."""
    result = copy.deepcopy(payload)
    windows = result.get("windows", [])
    if not isinstance(windows, list):
        windows = []
    windows = [entry for entry in windows if isinstance(entry, dict) and entry.get("path")]
    seen = set()
    for index, entry in enumerate(windows):
        slot = str(entry.get("slot_id", "") or "")
        if not slot or slot in seen:
            slot = uuid.uuid5(uuid.NAMESPACE_URL, f"tomadesk:{index}:{entry['path']}").hex
        entry["slot_id"] = slot
        seen.add(slot)
    result["windows"] = windows
    options = result.get("workspace", {})
    options = dict(options) if isinstance(options, dict) else {}
    options["enabled"] = bool(options.get("enabled", False))
    options["restore_folders"] = options.get("restore_folders", "keep") if options.get("restore_folders") in ("keep", "initial") else "keep"
    target = str(options.get("target_slot", "") or "")
    if target not in seen:
        try:
            monitors = enumerate_monitors()
        except Exception:
            monitors = []
        def screen_x(entry):
            monitor = next((m for m in monitors if entry.get("monitor_device") and m.get("device") == entry["monitor_device"]), None)
            monitor = monitor or next((m for m in monitors if m.get("number") == entry.get("monitor")), {})
            return monitor.get("work_rect", (int(entry.get("monitor", 0)) * 100000,))[0] + entry.get("rect", [0])[0]
        rightmost = max(windows, key=screen_x, default={})
        target = rightmost.get("slot_id", "")
    options["target_slot"] = target
    options["favorites"] = [
        {"path": str(item["path"]), "name": str(item.get("name") or Path(item["path"]).name or item["path"])}
        for item in options.get("favorites", []) if isinstance(item, dict) and item.get("path")
    ] if isinstance(options.get("favorites", []), list) else []
    result["workspace"] = options
    return result


class NativeOwnership:
    """A window property disappears on destruction, including HWND reuse."""

    def __init__(self):
        self.name = f"TomaDesk.LayoutOwner.{os.getpid()}"
        _USER32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
        _USER32.SetPropW.restype = wintypes.BOOL
        _USER32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        _USER32.GetPropW.restype = wintypes.HANDLE
        _USER32.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        _USER32.RemovePropW.restype = wintypes.HANDLE

    def claim(self, hwnd):
        if _USER32.GetPropW(hwnd, self.name):
            raise RuntimeError("다른 배치에서 사용 중인 창입니다.")
        token = uuid.uuid4().int & 0x7fffffff or 1
        if not _USER32.SetPropW(hwnd, self.name, token):
            raise RuntimeError("탐색기 창 소유 확인 정보를 설정하지 못했습니다.")
        return token

    def valid(self, hwnd, token):
        return bool(token) and int(_USER32.GetPropW(hwnd, self.name) or 0) == token

    def release(self, hwnd, token):
        if self.valid(hwnd, token):
            _USER32.RemovePropW(hwnd, self.name)


def window_is_uncovered(hwnd, ignored=()):
    """Check actual Z-order rectangles, ignoring other windows in this group."""
    ignored = set(ignored)
    target, _basis = window_bounds(hwnd)
    if target is None:
        return False
    for item in _native_visible_windows():
        handle = int(item["hwnd"])
        if handle == hwnd:
            return not item.get("minimized")
        if handle in ignored or item.get("minimized"):
            continue
        rect = item["rect"]
        if min(target[2], rect[2]) > max(target[0], rect[0]) and min(target[3], rect[3]) > max(target[1], rect[1]):
            return False
    return False


def navigate_explorer(hwnd, path, ownership, token, timeout=5.0):
    """Run in a COM-initialized worker; verify identity and actual Shell path."""
    import pythoncom
    from window_restore import explorer_window_from_hwnd

    target = Path(path)
    if not target.is_dir():
        raise ValueError("폴더가 없거나 접근할 수 없습니다. 경로를 확인해 주세요.")
    pythoncom.CoInitialize()
    try:
        if not ownership.valid(hwnd, token) or hwnd not in enumerate_explorer_window_handles():
            raise RuntimeError("대상 탐색기 창이 닫혔습니다. 다시 선택해 주세요.")
        window = explorer_window_from_hwnd(hwnd)
        if window is None:
            raise RuntimeError("대상 탐색기 경로를 조회할 수 없습니다.")
        window.Navigate2(str(target.resolve()))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not ownership.valid(hwnd, token):
                raise RuntimeError("폴더 이동 중 대상 탐색기 창이 닫혔습니다.")
            paths = explorer_window_paths({hwnd})
            if any(normalized_path(item.get("path")) == normalized_path(target) for item in paths):
                return str(target.resolve())
            time.sleep(0.03)
        raise RuntimeError("탐색기 폴더 이동을 확인하지 못했습니다. 다시 시도해 주세요.")
    finally:
        pythoncom.CoUninitialize()


class WorkspaceRuntime:
    """Main-thread state; native operations use the runner's existing seams."""

    def __init__(self, runner, ownership=None, uncovered=None, navigator=None):
        self.runner = runner
        self.ownership = ownership or NativeOwnership()
        self.uncovered = uncovered or window_is_uncovered
        self.navigator = navigator or navigate_explorer
        self.groups = {}

    def _paths(self):
        handles = set(self.runner._explorer_handle_provider())
        self.known_handles = handles
        return {int(item["hwnd"]): str(item["path"]) for item in self.runner._explorer_path_provider(handles) if int(item.get("hwnd", 0)) in handles and item.get("path")}

    def refresh(self, key, payload):
        group = self.groups.setdefault(key, {})
        slots = {entry["slot_id"] for entry in payload["windows"]}
        paths = self._paths()
        for slot, record in list(group.items()):
            hwnd = record["hwnd"]
            if self.ownership.valid(hwnd, record["token"]) and hwnd not in paths:
                raise RuntimeError("대상 탐색기 경로를 확인하지 못했습니다. 숨김 기록은 유지합니다.")
            if slot not in slots or hwnd not in paths or not self.ownership.valid(hwnd, record["token"]):
                # Removed live slots are restored before ownership is released.
                if record.get("hidden") and hwnd in paths and self.ownership.valid(hwnd, record["token"]):
                    if not self.runner._window_shower(hwnd, paths[hwnd]):
                        raise RuntimeError("배치에서 제외할 숨김 창을 복원하지 못했습니다.")
                self.ownership.release(hwnd, record["token"])
                group.pop(slot)
            else:
                record["path"] = paths[hwnd]
        return group

    def persist(self, key):
        self.runner._save_layout_records(key, [
            {"hwnd": r["hwnd"], "path": r["path"], "hidden": bool(r.get("hidden")), "slot_id": slot}
            for slot, r in self.groups.get(key, {}).items()
        ])

    def _reserved(self, key):
        return {
            int(record["hwnd"])
            for other, records in self.runner._layout_records().items() if other != key
            for record in self.runner._verified_layout_records(records)
        } | {r["hwnd"] for other, group in self.groups.items() if other != key for r in group.values() if self.ownership.valid(r["hwnd"], r["token"])}

    def ensure(self, key, payload, only_slot=None):
        group = self.refresh(key, payload)
        paths = self._paths()
        before = set(paths)
        used = self._reserved(key) | {r["hwnd"] for r in group.values()}
        pending = []
        errors = []
        recovery = self.runner._verified_layout_records(self.runner._layout_records().get(key, []))
        recovered = {r["hwnd"] for r in recovery}
        saved_slots = {r.get("slot_id"): r for r in self.runner._layout_records().get(key, []) if isinstance(r, dict) and r.get("slot_id") and r.get("hwnd") in recovered}
        # Never replace persistent records while leaving a previous owned HWND hidden.
        for record in recovery:
            if record.get("hidden") and record["hwnd"] not in used:
                if not self.runner._window_shower(record["hwnd"], record["path"]):
                    raise RuntimeError("이전 실행의 숨긴 창을 복원하지 못했습니다. 기록을 유지합니다.")
        for entry in payload["windows"]:
            slot = entry["slot_id"]
            if only_slot is not None and slot != only_slot:
                continue
            if slot in group:
                continue
            target = entry["path"]
            prior = saved_slots.get(slot)
            if prior and prior["hwnd"] not in used and not entry.get("always_new"):
                hwnd = prior["hwnd"]
                record = {"hwnd": hwnd, "token": self.ownership.claim(hwnd), "path": paths[hwnd], "hidden": False}
                group[slot] = record
                used.add(hwnd)
                if normalized_path(record["path"]) != normalized_path(target):
                    try:
                        record["path"] = self.navigator(hwnd, target, self.ownership, record["token"])
                    except Exception as exc:
                        errors.append(f"{target}: 초기 폴더 복원 실패 ({exc})")
                continue
            candidates = [h for h, p in paths.items() if h not in used and normalized_path(p) == normalized_path(target) and (self.runner._window_visibility_provider(h) or h in recovered)]
            hwnd = next(iter(candidates), 0) if not entry.get("always_new") else 0
            if hwnd:
                try:
                    group[slot] = {"hwnd": hwnd, "token": self.ownership.claim(hwnd), "path": paths[hwnd], "hidden": not self.runner._window_visibility_provider(hwnd)}
                    used.add(hwnd)
                except Exception as exc:
                    errors.append(str(exc))
            else:
                try:
                    self.runner._explorer_opener(target)
                    pending.append(entry)
                except Exception as exc:
                    errors.append(f"{target}: {exc}")
        deadline = self.runner._clock() + self.runner._layout_timeout
        while pending:
            paths = self._paths()
            for entry in list(pending):
                hwnd = next((h for h, p in paths.items() if h not in used and h not in before and normalized_path(p) == normalized_path(entry["path"])), 0)
                if not hwnd:
                    continue
                try:
                    group[entry["slot_id"]] = {"hwnd": hwnd, "token": self.ownership.claim(hwnd), "path": paths[hwnd], "hidden": False}
                    used.add(hwnd)
                except Exception as exc:
                    errors.append(str(exc))
                pending.remove(entry)
            if not pending or self.runner._clock() >= deadline:
                break
            self.runner._sleeper(self.runner._layout_poll_interval)
        errors.extend(f"{entry['path']}: 새 탐색기 창 경로 확인 실패" for entry in pending)
        self.persist(key)
        return group, errors

    def at_layout(self, key, payload, ignored=()):
        group = self.refresh(key, payload)
        if len(group) != len(payload["windows"]) or not group:
            return False
        monitors = list(self.runner._monitor_provider())
        ignore = set(ignored) | {r["hwnd"] for r in group.values()}
        return all(
            self.runner._window_visibility_provider(group[e["slot_id"]]["hwnd"])
            and self.runner._record_matches_saved_layout(group[e["slot_id"]], {group[e["slot_id"]]["hwnd"]: e}, monitors)
            and self.uncovered(group[e["slot_id"]]["hwnd"], ignore)
            for e in payload["windows"]
        )

    def hide(self, key, payload):
        group = self.refresh(key, payload)
        # Record intent before the first hide, for safe recovery after a crash.
        for record in group.values():
            record["hidden"] = True
        self.persist(key)
        errors = []
        for record in group.values():
            try:
                record["hidden"] = bool(self.runner._window_hider(record["hwnd"], record["path"]))
            except Exception as exc:
                record["hidden"] = not self.runner._window_visibility_provider(record["hwnd"])
                errors.append(str(exc))
            if not record["hidden"]:
                errors.append(f"{record['path']}: 창 숨김 실패")
        self.persist(key)
        return errors

    def show(self, key, payload):
        from action_runner import _saved_monitor, _primary_monitor

        group, errors = self.ensure(key, payload)
        monitors = list(self.runner._monitor_provider())
        for entry in payload["windows"]:
            record = group.get(entry["slot_id"])
            if record is None:
                continue
            try:
                if not self.runner._window_visibility_provider(record["hwnd"]):
                    if not self.runner._window_shower(record["hwnd"], record["path"]):
                        raise RuntimeError("탐색기 표시 실패")
                record["hidden"] = False
                if payload["workspace"]["restore_folders"] == "initial" and normalized_path(record["path"]) != normalized_path(entry["path"]):
                    record["path"] = self.navigator(record["hwnd"], entry["path"], self.ownership, record["token"])
                monitor = _saved_monitor(entry, monitors) or _primary_monitor(monitors)
                if monitor is None:
                    raise RuntimeError("사용 가능한 모니터 없음")
                self.runner._move_layout_window({"hwnd": record["hwnd"], "entry": entry, "monitor": monitor})
                self.runner._window_activator(record["hwnd"])
            except Exception as exc:
                errors.append(f"{entry['path']}: {exc}")
        # Navigation may have changed the folder even when verification timed out.
        self.refresh(key, payload)
        self.persist(key)
        return errors

    def navigation_target(self, key, payload, slot, path):
        if slot not in {e["slot_id"] for e in payload["windows"]}:
            raise ValueError("대상 탐색기를 선택해 주세요.")
        if not Path(path).is_dir():
            raise ValueError("폴더가 없거나 접근할 수 없습니다. 경로를 확인해 주세요.")
        group = self.refresh(key, payload)
        if slot not in group:
            # Only recreate the requested slot, directly at the selected folder.
            # ensure() must not release the other slots while opening this one.
            entry = next(e for e in payload["windows"] if e["slot_id"] == slot)
            original = entry["path"]
            try:
                entry["path"] = path
                group, errors = self.ensure(key, payload, only_slot=slot)
            finally:
                entry["path"] = original
            if errors or slot not in group:
                raise RuntimeError("대상 창 재생성 실패: " + "; ".join(errors))
            from action_runner import _saved_monitor, _primary_monitor
            monitors = list(self.runner._monitor_provider())
            self.runner._move_layout_window({"hwnd": group[slot]["hwnd"], "entry": entry, "monitor": _saved_monitor(entry, monitors) or _primary_monitor(monitors)})
        record = group[slot]
        if not self.runner._window_visibility_provider(record["hwnd"]):
            if not self.runner._window_shower(record["hwnd"], record["path"]):
                raise RuntimeError("대상 탐색기 창을 표시하지 못했습니다.")
        record["hidden"] = False
        self.persist(key)
        return dict(record)

    def shutdown(self):
        for group in self.groups.values():
            for record in group.values():
                self.ownership.release(record["hwnd"], record["token"])
        self.groups.clear()
