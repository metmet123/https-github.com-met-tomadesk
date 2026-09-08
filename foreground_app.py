"""Windows helpers for identifying foreground and visible applications."""

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

_USER32.GetForegroundWindow.restype = wintypes.HWND
_USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
_USER32.IsWindowVisible.argtypes = [wintypes.HWND]
_USER32.IsWindowVisible.restype = wintypes.BOOL
_USER32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_USER32.GetWindowTextLengthW.restype = ctypes.c_int
_USER32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_USER32.GetWindowTextW.restype = ctypes.c_int
_KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_KERNEL32.OpenProcess.restype = wintypes.HANDLE
_KERNEL32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
_KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
_KERNEL32.CloseHandle.restype = wintypes.BOOL
_KERNEL32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_KERNEL32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_KERNEL32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
_KERNEL32.Process32FirstW.restype = wintypes.BOOL
_KERNEL32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
_KERNEL32.Process32NextW.restype = wintypes.BOOL


def normalize_app(app: dict) -> dict:
    path = str(app.get("path", "") or "").strip()
    name = str(app.get("name", "") or "").strip()
    title = str(app.get("title", "") or "").strip()
    if path:
        path = os.path.normpath(path)
        name = name or Path(path).name
    return {"name": name, "path": path, "title": title}


def normalize_app_list(apps) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for value in apps if isinstance(apps, list) else []:
        if not isinstance(value, dict):
            continue
        app = normalize_app(value)
        if not app["name"] and not app["path"]:
            continue
        key = _app_key(app)
        if key in seen:
            continue
        seen.add(key)
        result.append(app)
    return result


def persisted_app_list(apps) -> list[dict]:
    return [
        {"name": app["name"], "path": app["path"]}
        for app in normalize_app_list(apps)
    ]


def foreground_application() -> dict | None:
    hwnd = _USER32.GetForegroundWindow()
    return application_from_window(hwnd) if hwnd else None


def visible_applications() -> list[dict]:
    windows: list[dict] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _lparam):
        if _USER32.IsWindowVisible(hwnd) and _USER32.GetWindowTextLengthW(hwnd) > 0:
            app = application_from_window(hwnd)
            if app and app.get("path"):
                windows.append(app)
        return True

    _USER32.EnumWindows(visit, 0)
    unique: dict[tuple[str, str], dict] = {}
    for app in windows:
        key = _app_key(app)
        if key not in unique or (not unique[key].get("title") and app.get("title")):
            unique[key] = app
    return sorted(unique.values(), key=lambda app: (app["name"].casefold(), app["title"].casefold()))


def application_from_window(hwnd) -> dict | None:
    if not hwnd:
        return None
    process_id = wintypes.DWORD()
    _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    if not process_id.value:
        return None
    path = _process_path(process_id.value)
    title = _window_title(hwnd)
    name = Path(path).name if path else _process_name(process_id.value)
    if not name:
        return None
    return normalize_app({"name": name, "path": path, "title": title})


def is_app_excluded(current: dict | None, excluded_apps) -> bool:
    if not current:
        return False
    current = normalize_app(current)
    current_path = _normalized_path(current["path"])
    current_name = current["name"].casefold()
    for excluded in normalize_app_list(excluded_apps):
        excluded_path = _normalized_path(excluded["path"])
        if current_path and excluded_path:
            if current_path == excluded_path:
                return True
            continue
        if current_name and current_name == excluded["name"].casefold():
            return True
    return False


def _process_path(process_id: int) -> str:
    handle = _KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _KERNEL32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        _KERNEL32.CloseHandle(handle)


def _window_title(hwnd) -> str:
    length = _USER32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _USER32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _process_name(process_id: int) -> str:
    snapshot = _KERNEL32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return ""
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = _KERNEL32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32ProcessID == process_id:
                return entry.szExeFile
            found = _KERNEL32.Process32NextW(snapshot, ctypes.byref(entry))
        return ""
    finally:
        _KERNEL32.CloseHandle(snapshot)


def _normalized_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


def _app_key(app: dict) -> tuple[str, str]:
    path = _normalized_path(app.get("path", ""))
    return ("path", path) if path else ("name", str(app.get("name", "")).casefold())
