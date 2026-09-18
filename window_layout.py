"""Collect and move top-level Windows windows for saved layouts."""

import ctypes
import os
import re
from ctypes import wintypes
from typing import Callable, Iterable

from foreground_app import application_from_window
from window_restore import enumerate_explorer_windows


MONITOR_DEFAULTTONEAREST = 2
MONITORINFOF_PRIMARY = 1
SW_HIDE = 0
SW_SHOW = 5
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_RESTORE = 9
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_ASYNCWINDOWPOS = 0x4000
DWMWA_EXTENDED_FRAME_BOUNDS = 9
RECT_BASIS_VISIBLE = "visible"
RECT_BASIS_WINDOW_RECT_FALLBACK = "window"


class _MonitorInfoEx(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_USER32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
_USER32.EnumWindows.restype = wintypes.BOOL
_USER32.IsWindowVisible.argtypes = [wintypes.HWND]
_USER32.IsWindowVisible.restype = wintypes.BOOL
_USER32.IsIconic.argtypes = [wintypes.HWND]
_USER32.IsIconic.restype = wintypes.BOOL
_USER32.IsZoomed.argtypes = [wintypes.HWND]
_USER32.IsZoomed.restype = wintypes.BOOL
_USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_USER32.GetWindowRect.restype = wintypes.BOOL
_USER32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_USER32.GetWindowTextLengthW.restype = ctypes.c_int
_USER32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_USER32.GetWindowTextW.restype = ctypes.c_int
_USER32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_USER32.GetClassNameW.restype = ctypes.c_int
_USER32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_USER32.MonitorFromWindow.restype = wintypes.HANDLE
_USER32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfoEx)]
_USER32.GetMonitorInfoW.restype = wintypes.BOOL
_USER32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC, ctypes.POINTER(wintypes.RECT), ctypes.c_void_p, wintypes.LPARAM,
]
_USER32.EnumDisplayMonitors.restype = wintypes.BOOL
_USER32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
_USER32.SetWindowPos.restype = wintypes.BOOL
_USER32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_USER32.ShowWindow.restype = wintypes.BOOL
_DWMAPI = ctypes.WinDLL("dwmapi", use_last_error=True)
_DWMAPI.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
]
_DWMAPI.DwmGetWindowAttribute.restype = ctypes.c_long


class _NativeWindowBoundsProvider:
    def get_window_rect(self, hwnd: int):
        rect = wintypes.RECT()
        if not _USER32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
            return None
        return _rect_tuple(rect)

    def get_extended_frame_bounds(self, hwnd: int):
        rect = wintypes.RECT()
        result = _DWMAPI.DwmGetWindowAttribute(
            int(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect), ctypes.sizeof(rect),
        )
        if result != 0:
            return None
        return _rect_tuple(rect)


_WINDOW_BOUNDS = _NativeWindowBoundsProvider()


def relative_rect(window_rect, work_rect) -> list[int]:
    """Convert an absolute (left, top, right, bottom) rect to x, y, width, height."""
    left, top, right, bottom = (int(value) for value in window_rect)
    work_left, work_top, _work_right, _work_bottom = (int(value) for value in work_rect)
    return [left - work_left, top - work_top, max(1, right - left), max(1, bottom - top)]


def scale_size_for_dpi(rect, source_dpi: int, target_dpi: int) -> list[int]:
    """Scale a relative rect's size for a target DPI while preserving its offset."""
    x, y, width, height = (int(round(value)) for value in rect)
    source = max(1, int(source_dpi or 96))
    target = max(1, int(target_dpi or 96))
    ratio = target / source
    return [x, y, max(1, round(width * ratio)), max(1, round(height * ratio))]


def clamp_rect_to_work_area(rect, work_rect) -> list[int]:
    """Keep a relative x, y, width, height rectangle inside a monitor work area."""
    x, y, width, height = (int(round(value)) for value in rect)
    left, top, right, bottom = (int(value) for value in work_rect)
    work_width = max(1, right - left)
    work_height = max(1, bottom - top)
    width = min(max(1, width), work_width)
    height = min(max(1, height), work_height)
    x = min(max(0, x), work_width - width)
    y = min(max(0, y), work_height - height)
    return [x, y, width, height]


def absolute_rect(rect, work_rect, source_dpi: int = 96, target_dpi: int = 96) -> list[int]:
    """Convert a saved relative rect to an absolute, work-area-clamped rect."""
    x, y, width, height = clamp_rect_to_work_area(
        scale_size_for_dpi(rect, source_dpi, target_dpi), work_rect,
    )
    left, top, _right, _bottom = (int(value) for value in work_rect)
    return [left + x, top + y, width, height]


def window_bounds(hwnd: int, api_provider=None) -> tuple[tuple[int, int, int, int] | None, str]:
    """Return visible frame bounds, falling back explicitly to the raw window rect."""
    provider = api_provider or _WINDOW_BOUNDS
    raw_rect = provider.get_window_rect(int(hwnd))
    if raw_rect is None:
        return None, RECT_BASIS_WINDOW_RECT_FALLBACK
    visible_rect = provider.get_extended_frame_bounds(int(hwnd))
    if visible_rect is not None:
        return tuple(int(value) for value in visible_rect), RECT_BASIS_VISIBLE
    return tuple(int(value) for value in raw_rect), RECT_BASIS_WINDOW_RECT_FALLBACK


def window_border_thickness(hwnd: int, api_provider=None) -> tuple[int, int, int, int]:
    """Measure the live invisible left, top, right, and bottom window borders."""
    provider = api_provider or _WINDOW_BOUNDS
    raw_rect = provider.get_window_rect(int(hwnd))
    visible_rect = provider.get_extended_frame_bounds(int(hwnd))
    if raw_rect is None or visible_rect is None:
        return (0, 0, 0, 0)
    raw_left, raw_top, raw_right, raw_bottom = (int(value) for value in raw_rect)
    visible_left, visible_top, visible_right, visible_bottom = (
        int(value) for value in visible_rect
    )
    return (
        max(0, visible_left - raw_left),
        max(0, visible_top - raw_top),
        max(0, raw_right - visible_right),
        max(0, raw_bottom - visible_bottom),
    )


def target_window_rect(
    rect,
    work_rect,
    borders=(0, 0, 0, 0),
    *,
    rect_basis: str | None = None,
    source_dpi: int = 96,
    target_dpi: int = 96,
) -> list[int]:
    """Convert saved coordinates to the raw rectangle required by SetWindowPos."""
    scaled = scale_size_for_dpi(rect, source_dpi, target_dpi)
    border_left, border_top, border_right, border_bottom = (
        max(0, int(value)) for value in borders
    )
    if rect_basis != RECT_BASIS_VISIBLE:
        scaled = [
            scaled[0] + border_left,
            scaled[1] + border_top,
            max(1, scaled[2] - border_left - border_right),
            max(1, scaled[3] - border_top - border_bottom),
        ]
    x, y, width, height = clamp_rect_to_work_area(scaled, work_rect)
    work_left, work_top, _work_right, _work_bottom = (int(value) for value in work_rect)
    return [
        work_left + x - border_left,
        work_top + y - border_top,
        width + border_left + border_right,
        height + border_top + border_bottom,
    ]


def enumerate_monitors() -> list[dict]:
    """Return display monitor bounds, work areas, identifiers, and DPI."""
    monitors: list[dict] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )

    @callback_type
    def visit(handle, _hdc, _rect, _lparam):
        info = _MonitorInfoEx()
        info.cbSize = ctypes.sizeof(info)
        if _USER32.GetMonitorInfoW(handle, ctypes.byref(info)):
            device = str(info.szDevice)
            match = re.search(r"(\d+)$", device)
            monitors.append({
                "handle": int(handle),
                "number": int(match.group(1)) if match else len(monitors) + 1,
                "device": device,
                "monitor_rect": _rect_tuple(info.rcMonitor),
                "work_rect": _rect_tuple(info.rcWork),
                "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                "dpi": 96,
            })
        return True

    _USER32.EnumDisplayMonitors(0, None, visit, 0)
    monitors.sort(key=lambda item: (not item["primary"], item["number"], item["device"]))
    return monitors


def enumerate_explorer_window_handles() -> set[int]:
    """Return Explorer top-level handles without invoking Shell COM."""
    handles: set[int] = set()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _lparam):
        buffer = ctypes.create_unicode_buffer(256)
        if _USER32.GetClassNameW(hwnd, buffer, len(buffer)):
            if buffer.value in {"CabinetWClass", "ExploreWClass"}:
                handles.add(int(hwnd))
        return True

    _USER32.EnumWindows(visit, 0)
    return handles


def explorer_window_paths(handles) -> list[dict]:
    """Query Shell COM paths only for the requested Explorer handles."""
    wanted = {int(hwnd) for hwnd in handles if int(hwnd or 0)}
    if not wanted:
        return []
    try:
        import pythoncom
        from win32com.client import Dispatch
    except ImportError:
        return []

    windows: list[dict] = []
    initialized = False
    try:
        pythoncom.CoInitialize()
        initialized = True
        shell = Dispatch("Shell.Application")
        for window in shell.Windows():
            try:
                hwnd = int(window.HWND)
                if hwnd not in wanted:
                    continue
                folder_path = str(window.Document.Folder.Self.Path or "")
                title = str(getattr(window, "LocationName", "") or "")
            except Exception:
                continue
            if folder_path:
                windows.append({"hwnd": hwnd, "path": folder_path, "title": title})
    except Exception:
        return []
    finally:
        if initialized:
            pythoncom.CoUninitialize()
    return windows


def is_window_visible(hwnd: int) -> bool:
    """Return whether Windows currently considers the window visible."""
    return bool(hwnd and _USER32.IsWindowVisible(int(hwnd)))


def is_verified_explorer_window(
    hwnd: int,
    expected_path: str,
    *,
    handle_provider: Callable[[], Iterable[int]] | None = None,
    path_provider: Callable[[Iterable[int]], Iterable[dict]] | None = None,
) -> bool:
    """Verify a persisted handle is still the recorded top-level Explorer folder."""
    hwnd = int(hwnd or 0)
    if not hwnd or not expected_path:
        return False
    handles = {
        int(value) for value in (handle_provider or enumerate_explorer_window_handles)()
        if int(value or 0)
    }
    if hwnd not in handles:
        return False
    windows = list((path_provider or explorer_window_paths)({hwnd}))
    wanted = _normalized_path(expected_path)
    return any(
        isinstance(window, dict)
        and int(window.get("hwnd", 0) or 0) == hwnd
        and _normalized_path(window.get("path", "")) == wanted
        for window in windows
    )


def hide_explorer_window(
    hwnd: int,
    expected_path: str,
    *,
    handle_provider: Callable[[], Iterable[int]] | None = None,
    path_provider: Callable[[Iterable[int]], Iterable[dict]] | None = None,
) -> bool:
    """Hide only a re-verified top-level Explorer window."""
    if not is_verified_explorer_window(
        hwnd, expected_path, handle_provider=handle_provider, path_provider=path_provider,
    ):
        return False
    _USER32.ShowWindow(int(hwnd), SW_HIDE)
    return not is_window_visible(int(hwnd))


def show_explorer_window(
    hwnd: int,
    expected_path: str,
    *,
    handle_provider: Callable[[], Iterable[int]] | None = None,
    path_provider: Callable[[Iterable[int]], Iterable[dict]] | None = None,
) -> bool:
    """Show only a persisted handle that still matches its Explorer folder."""
    if not is_verified_explorer_window(
        hwnd, expected_path, handle_provider=handle_provider, path_provider=path_provider,
    ):
        return False
    _USER32.ShowWindow(int(hwnd), SW_SHOW)
    return is_window_visible(int(hwnd))


def collect_open_windows(
    window_provider: Callable[[], Iterable[dict]] | None = None,
    monitor_provider: Callable[[], Iterable[dict]] | None = None,
    explorer_provider: Callable[[], Iterable[dict]] | None = None,
) -> list[dict]:
    """Collect visible top-level windows using injectable operating-system providers."""
    windows = list((window_provider or _native_visible_windows)())
    monitors = list((monitor_provider or enumerate_monitors)())
    explorers = list((explorer_provider or enumerate_explorer_windows)())
    return describe_windows(windows, monitors, explorers)


def describe_windows(windows, monitors, explorer_windows=()) -> list[dict]:
    """Build serializable layout entries from raw window and monitor information."""
    explorer_by_hwnd = {
        int(item.get("hwnd", 0) or 0): item
        for item in explorer_windows
        if int(item.get("hwnd", 0) or 0)
    }
    result: list[dict] = []
    for window in windows:
        hwnd = int(window.get("hwnd", 0) or 0)
        if not hwnd or not window.get("visible", True):
            continue
        monitor = _monitor_for_window(window, monitors)
        if not monitor:
            continue
        explorer = explorer_by_hwnd.get(hwnd, {})
        state = "minimized" if window.get("minimized") else (
            "maximized" if window.get("maximized") else "normal"
        )
        result.append({
            "hwnd": hwnd,
            "program_path": str(window.get("program_path", "") or ""),
            "title": str(window.get("title", "") or explorer.get("title", "") or ""),
            "explorer_path": str(explorer.get("path", "") or ""),
            "monitor": int(monitor.get("number", 0) or 0),
            "monitor_device": str(monitor.get("device", "") or ""),
            "rect": relative_rect(window["rect"], monitor["work_rect"]),
            "rect_basis": str(
                window.get("rect_basis", RECT_BASIS_WINDOW_RECT_FALLBACK)
                or RECT_BASIS_WINDOW_RECT_FALLBACK
            ),
            "state": state,
            "dpi": int(window.get("dpi", monitor.get("dpi", 96)) or 96),
        })
    return result


def move_window(
    hwnd: int,
    rect,
    monitor: dict,
    state: str = "normal",
    source_dpi: int = 96,
    rect_basis: str | None = None,
    api_provider=None,
) -> bool:
    """Move a window to a monitor-relative rectangle and apply its window state."""
    if not hwnd or not monitor:
        return False
    borders = window_border_thickness(hwnd, api_provider=api_provider)
    x, y, width, height = target_window_rect(
        rect,
        monitor["work_rect"],
        borders,
        rect_basis=rect_basis,
        source_dpi=source_dpi,
        target_dpi=int(monitor.get("dpi", 96) or 96),
    )
    _USER32.ShowWindow(hwnd, SW_RESTORE)
    accepted = bool(_USER32.SetWindowPos(
        hwnd, 0, x, y, width, height,
        SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS,
    ))
    # With SWP_ASYNCWINDOWPOS, TRUE means Windows accepted or queued the request.
    # Keep the existing failure contract without waiting for visual completion.
    if not accepted:
        return False
    command = {
        "normal": SW_SHOWNORMAL,
        "maximized": SW_SHOWMAXIMIZED,
        "minimized": SW_SHOWMINIMIZED,
    }.get(state, SW_SHOWNORMAL)
    _USER32.ShowWindow(hwnd, command)
    return True


def _native_visible_windows() -> list[dict]:
    windows: list[dict] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    get_dpi = getattr(_USER32, "GetDpiForWindow", None)
    if get_dpi:
        get_dpi.argtypes = [wintypes.HWND]
        get_dpi.restype = wintypes.UINT

    @callback_type
    def visit(hwnd, _lparam):
        if not _USER32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title:
            return True
        rect, rect_basis = window_bounds(int(hwnd))
        if rect is None:
            return True
        app = application_from_window(hwnd) or {}
        monitor_handle = _USER32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        dpi = int(get_dpi(hwnd) or 96) if get_dpi else 96
        windows.append({
            "hwnd": int(hwnd),
            "visible": True,
            "title": title,
            "program_path": str(app.get("path", "") or ""),
            "rect": rect,
            "rect_basis": rect_basis,
            "monitor_handle": int(monitor_handle or 0),
            "minimized": bool(_USER32.IsIconic(hwnd)),
            "maximized": bool(_USER32.IsZoomed(hwnd)),
            "dpi": dpi,
        })
        return True

    _USER32.EnumWindows(visit, 0)
    return windows


def _monitor_for_window(window: dict, monitors) -> dict | None:
    handle = int(window.get("monitor_handle", 0) or 0)
    for monitor in monitors:
        if handle and int(monitor.get("handle", 0) or 0) == handle:
            return monitor
    rect = window.get("rect")
    if not rect:
        return next(iter(monitors), None)
    return max(monitors, key=lambda monitor: _intersection_area(rect, monitor["monitor_rect"]), default=None)


def _intersection_area(first, second) -> int:
    left = max(int(first[0]), int(second[0]))
    top = max(int(first[1]), int(second[1]))
    right = min(int(first[2]), int(second[2]))
    bottom = min(int(first[3]), int(second[3]))
    return max(0, right - left) * max(0, bottom - top)


def _window_title(hwnd) -> str:
    length = _USER32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _USER32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _rect_tuple(rect) -> tuple[int, int, int, int]:
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _normalized_path(path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path)))) if path else ""
