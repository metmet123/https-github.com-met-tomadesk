"""Navigate up when Explorer's empty file-list area is double-clicked."""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

import input_controller
from window_restore import explorer_window_from_hwnd


WH_MOUSE_LL = 14
WM_LBUTTONDBLCLK = 0x0203
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_QUIT = 0x0012
GA_ROOT = 2

EXPLORER_WINDOW_CLASSES = frozenset({"CabinetWClass", "ExploreWClass"})
FILE_LIST_ROOT_CLASS = "SHELLDLL_DefView"
EXCLUDED_CONTROL_CLASSES = frozenset(
    {
        # These controls can appear below SHELLDLL_DefView in supported or
        # legacy Explorer layouts. Ancestor-only tab container classes are
        # intentionally omitted because they are outside the file-list root.
        "SysHeader32",
        "SysTreeView32",
        "NamespaceTreeControl",
        "Breadcrumb Parent",
        "UniversalSearchBand",
        "SearchBox",
        "TITLE_BAR_SCAFFOLDING_WINDOW_CLASS",
        "PreviewPane",
        "DetailsPane",
        "msctls_statusbar32",
    }
)
_EXCLUDED_CONTROL_CLASSES_CASEFOLD = frozenset(
    name.casefold() for name in EXCLUDED_CONTROL_CLASSES
)


@dataclass(frozen=True)
class WindowHit:
    """Window information captured from the exact double-click coordinates."""

    child_hwnd: int
    top_hwnd: int
    top_class: str
    class_chain: tuple[str, ...]


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MouseHookData(ctypes.Structure):
    _fields_ = [
        ("pt", _Point),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class WindowsMouseHook:
    """WH_MOUSE_LL backend kept separate so tests can replace installation."""

    def __init__(self) -> None:
        self._thread_id = 0

    def run(
        self,
        event_sink: Callable[[int, int, int, int], bool],
        ready: threading.Event,
        error_sink: Callable[[Exception], None],
    ) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        hook_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            hook_proc_type,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self._thread_id = int(kernel32.GetCurrentThreadId())
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)

        @hook_proc_type
        def callback(code, message_id, data):
            message_value = int(message_id)
            if code >= 0 and message_value in {
                WM_LBUTTONDBLCLK,
                WM_MBUTTONDOWN,
                WM_MBUTTONUP,
            }:
                try:
                    event = ctypes.cast(data, ctypes.POINTER(_MouseHookData)).contents
                    if event_sink(
                        message_value,
                        int(event.pt.x),
                        int(event.pt.y),
                        int(event.time),
                    ):
                        return 1
                except Exception:
                    # Never let a transient window lookup failure break global input.
                    pass
            return user32.CallNextHookEx(None, code, message_id, data)

        hook = user32.SetWindowsHookExW(WH_MOUSE_LL, callback, None, 0)
        if not hook:
            error_code = ctypes.get_last_error()
            error_sink(OSError(error_code, ctypes.FormatError(error_code)))
            ready.set()
            self._thread_id = 0
            return
        ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnhookWindowsHookEx(hook)
            self._thread_id = 0

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


class ExplorerDoubleClickNavigator:
    """Own the hook and evaluate queued clicks away from the input callback."""

    _STOP = object()

    def __init__(
        self,
        *,
        hook_backend=None,
        window_hit_provider: Callable[[int, int], WindowHit | None] | None = None,
        selection_count_provider: Callable[[int], int | None] | None = None,
        foreground_window_provider: Callable[[], int] | None = None,
        hotkey_sender: Callable[[str], None] | None = None,
        recording_provider: Callable[[], bool] | None = None,
        com_initializer: Callable[[], None] | None = None,
        com_uninitializer: Callable[[], None] | None = None,
        double_click_enabled: bool = True,
        middle_click_enabled: bool = True,
    ) -> None:
        self._hook = hook_backend or WindowsMouseHook()
        self._window_hit_provider = window_hit_provider or window_hit_at_point
        self._selection_count_provider = selection_count_provider or selected_item_count
        self._foreground_window_provider = foreground_window_provider or foreground_window
        self._hotkey_sender = hotkey_sender or input_controller.send_hotkey
        self._recording_provider = recording_provider or (lambda: False)
        self._com_initializer = com_initializer or _co_initialize
        self._com_uninitializer = com_uninitializer or _co_uninitialize
        self._double_click_enabled = bool(double_click_enabled)
        self._middle_click_enabled = bool(middle_click_enabled)
        self._middle_button_captured = False
        self._events: queue.Queue = queue.Queue()
        self._hook_ready = threading.Event()
        self._hook_error: Exception | None = None
        self._hook_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._hook_thread is not None:
            return
        self._events = queue.Queue()
        self._hook_ready.clear()
        self._hook_error = None
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="explorer-double-click-worker", daemon=True
        )
        self._hook_thread = threading.Thread(
            target=self._hook_loop, name="explorer-double-click-hook", daemon=True
        )
        self._worker_thread.start()
        self._hook_thread.start()
        if not self._hook_ready.wait(1.0) or self._hook_error is not None:
            detail = self._hook_error or "마우스 갈고리 스레드가 응답하지 않습니다."
            self.stop()
            raise RuntimeError(f"탐색기 더블클릭 감지를 시작할 수 없습니다: {detail}")

    def stop(self) -> None:
        self._hook.stop()
        self._events.put(self._STOP)
        if self._hook_thread is not None:
            self._hook_thread.join(1.0)
        if self._worker_thread is not None:
            self._worker_thread.join(1.0)
        self._hook_thread = None
        self._worker_thread = None

    def handle_double_click(self, x: int, y: int, timestamp: int | float | None = None) -> bool:
        """Evaluate one event synchronously; injectable providers keep this headless."""
        del timestamp
        if self._recording_provider():
            return False
        hit = self._window_hit_provider(int(x), int(y))
        if not is_explorer_file_list(hit):
            return False
        try:
            selected_count = self._selection_count_provider(hit.top_hwnd)
        except Exception:
            return False
        if selected_count is None or int(selected_count) != 0:
            return False
        if self._recording_provider():
            return False
        if int(self._foreground_window_provider() or 0) != hit.top_hwnd:
            return False
        self._hotkey_sender("Alt+Up")
        return True

    def configure_features(
        self, *, double_click_enabled: bool, middle_click_enabled: bool
    ) -> None:
        """Update feature flags without installing a second mouse hook."""
        self._double_click_enabled = bool(double_click_enabled)
        self._middle_click_enabled = bool(middle_click_enabled)

    def handle_middle_click(self) -> bool:
        """Send the queued middle-click action from the worker thread."""
        if not self._middle_click_enabled or self._recording_provider():
            return False
        self._hotkey_sender("Alt+Up")
        return True

    def _handle_hook_event(
        self, message_id: int, x: int, y: int, timestamp: int
    ) -> bool:
        """Return True only when the low-level callback must swallow the event."""
        if message_id == WM_LBUTTONDBLCLK:
            if self._double_click_enabled:
                self._events.put(("double", int(x), int(y), int(timestamp)))
            return False
        if message_id == WM_MBUTTONDOWN:
            self._middle_button_captured = False
            if not self._middle_click_enabled or self._recording_provider():
                return False
            hit = self._window_hit_provider(int(x), int(y))
            if not is_explorer_file_list(hit):
                return False
            self._middle_button_captured = True
            return True
        if message_id == WM_MBUTTONUP:
            if not self._middle_button_captured:
                return False
            self._middle_button_captured = False
            self._events.put(("middle", int(timestamp)))
            return True
        return False

    def _hook_loop(self) -> None:
        self._hook.run(self._handle_hook_event, self._hook_ready, self._set_hook_error)

    def _set_hook_error(self, error: Exception) -> None:
        self._hook_error = error

    def _worker_loop(self) -> None:
        initialized = False
        try:
            while True:
                event = self._events.get()
                if event is self._STOP:
                    return
                try:
                    if event[0] == "middle":
                        self.handle_middle_click()
                    else:
                        if not initialized:
                            self._com_initializer()
                            initialized = True
                        self.handle_double_click(*event[1:])
                except Exception:
                    # A transient Explorer/COM failure must not end monitoring.
                    continue
        finally:
            if initialized:
                self._com_uninitializer()


def is_explorer_file_list(hit: WindowHit | None) -> bool:
    if hit is None or hit.top_class not in EXPLORER_WINDOW_CLASSES:
        return False
    folded_classes = tuple(name.casefold() for name in hit.class_chain)
    try:
        file_list_root_index = folded_classes.index(FILE_LIST_ROOT_CLASS.casefold())
    except ValueError:
        return False
    inner_classes = folded_classes[:file_list_root_index]
    return _EXCLUDED_CONTROL_CLASSES_CASEFOLD.isdisjoint(inner_classes)


def window_hit_at_point(x: int, y: int) -> WindowHit | None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.WindowFromPoint.argtypes = [_Point]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND

    child = int(user32.WindowFromPoint(_Point(int(x), int(y))) or 0)
    if not child:
        return None
    top = int(user32.GetAncestor(child, GA_ROOT) or 0)
    if not top:
        return None
    chain: list[str] = []
    current = child
    seen: set[int] = set()
    while current and current not in seen:
        seen.add(current)
        chain.append(_window_class(user32, current))
        if current == top:
            break
        current = int(user32.GetParent(current) or 0)
    return WindowHit(child, top, _window_class(user32, top), tuple(chain))


def selected_item_count(hwnd: int) -> int | None:
    window = explorer_window_from_hwnd(hwnd)
    if window is None:
        return None
    return int(window.Document.SelectedItems().Count)


def foreground_window() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow() or 0)


def _window_class(user32, hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    return buffer.value if user32.GetClassNameW(hwnd, buffer, len(buffer)) else ""


def _co_initialize() -> None:
    import pythoncom

    pythoncom.CoInitialize()


def _co_uninitialize() -> None:
    import pythoncom

    pythoncom.CoUninitialize()
