"""Toggle Always on Top for the current foreground window."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable


HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SET_WINDOW_POS_FLAGS = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
EXCLUDED_WINDOW_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd"})


@dataclass(frozen=True)
class WindowPinResult:
    """Result shown to the user after a pin request."""

    changed: bool
    pinned: bool
    title: str
    message: str


class NativeWindowPinApi:
    """Small injectable boundary around the user32 calls used by this feature."""

    def __init__(self):
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetClassNameW.restype = ctypes.c_int
        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        self._user32.SetWindowPos.restype = wintypes.BOOL

    def foreground_window(self) -> int:
        return int(self._user32.GetForegroundWindow() or 0)

    def is_window(self, hwnd: int) -> bool:
        return bool(hwnd and self._user32.IsWindow(int(hwnd)))

    def window_class(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        if not self._user32.GetClassNameW(int(hwnd), buffer, len(buffer)):
            return ""
        return buffer.value

    def window_title(self, hwnd: int) -> str:
        length = max(0, int(self._user32.GetWindowTextLengthW(int(hwnd))))
        buffer = ctypes.create_unicode_buffer(length + 1)
        if length and self._user32.GetWindowTextW(int(hwnd), buffer, len(buffer)):
            return buffer.value
        return ""

    def set_topmost(self, hwnd: int, pinned: bool) -> bool:
        insert_after = HWND_TOPMOST if pinned else HWND_NOTOPMOST
        return bool(self._user32.SetWindowPos(
            int(hwnd), insert_after, 0, 0, 0, 0, SET_WINDOW_POS_FLAGS,
        ))


class WindowPinController:
    """Track windows pinned by TomaDesk and restore them when disabled or closed."""

    def __init__(
        self,
        api=None,
        *,
        is_own_postit: Callable[[int], bool] | None = None,
        count_changed: Callable[[int], None] | None = None,
    ):
        self._api = api or NativeWindowPinApi()
        self._is_own_postit = is_own_postit or (lambda _hwnd: False)
        self._count_changed = count_changed
        self._pinned: set[int] = set()
        self._enabled = True

    @property
    def pinned_count(self) -> int:
        self._prune_closed_windows()
        return len(self._pinned)

    def pinned_windows(self) -> set[int]:
        self._prune_closed_windows()
        return set(self._pinned)

    def toggle_foreground(self) -> WindowPinResult:
        return self.toggle(self._api.foreground_window())

    def toggle(self, hwnd: int) -> WindowPinResult:
        self._prune_closed_windows()
        hwnd = int(hwnd or 0)
        if not self._enabled:
            return WindowPinResult(False, False, "", "창 고정 기능이 꺼져 있습니다.")
        if not hwnd or not self._api.is_window(hwnd):
            return WindowPinResult(False, False, "", "고정할 창을 찾지 못했습니다.")

        title = self._api.window_title(hwnd).strip() or "제목 없는 창"
        window_class = self._api.window_class(hwnd)
        if window_class in EXCLUDED_WINDOW_CLASSES:
            return WindowPinResult(False, False, title, f"{title}: 고정할 수 없는 Windows 영역입니다.")
        if self._is_own_postit(hwnd):
            return WindowPinResult(False, False, title, f"{title}: 토마데스크 포스트잇은 이미 항상 위에 있습니다.")

        pin = hwnd not in self._pinned
        if not self._api.set_topmost(hwnd, pin):
            action = "고정" if pin else "해제"
            return WindowPinResult(False, not pin, title, f"{title}: 창 {action}에 실패했습니다.")

        if pin:
            self._pinned.add(hwnd)
            message = f"{title}: 항상 위에 고정했습니다."
        else:
            self._pinned.discard(hwnd)
            message = f"{title}: 항상 위 고정을 해제했습니다."
        self._notify_count_changed()
        return WindowPinResult(True, pin, title, message)

    def release_all(self) -> int:
        """Remove Always on Top from every live window pinned by this controller."""
        released = 0
        changed = False
        for hwnd in tuple(self._pinned):
            if not self._api.is_window(hwnd):
                self._pinned.discard(hwnd)
                changed = True
                continue
            if self._api.set_topmost(hwnd, False):
                self._pinned.discard(hwnd)
                released += 1
                changed = True
        if changed:
            self._notify_count_changed()
        return released

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._enabled == enabled:
            return
        self._enabled = enabled
        if not enabled:
            self.release_all()

    def shutdown(self) -> int:
        return self.release_all()

    def _prune_closed_windows(self) -> None:
        closed = {hwnd for hwnd in self._pinned if not self._api.is_window(hwnd)}
        if not closed:
            return
        self._pinned.difference_update(closed)
        self._notify_count_changed()

    def _notify_count_changed(self) -> None:
        if self._count_changed is not None:
            self._count_changed(len(self._pinned))
