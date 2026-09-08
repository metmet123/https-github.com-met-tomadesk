"""Restore minimized application or Explorer windows for saved path actions."""

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from foreground_app import application_from_window


SW_RESTORE = 9

_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_USER32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
_USER32.EnumWindows.restype = wintypes.BOOL
_USER32.IsIconic.argtypes = [wintypes.HWND]
_USER32.IsIconic.restype = wintypes.BOOL
_USER32.IsWindowVisible.argtypes = [wintypes.HWND]
_USER32.IsWindowVisible.restype = wintypes.BOOL
_USER32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
_USER32.ShowWindowAsync.restype = wintypes.BOOL
_USER32.SetForegroundWindow.argtypes = [wintypes.HWND]
_USER32.SetForegroundWindow.restype = wintypes.BOOL


def restore_minimized_target(target: str) -> bool:
    """Restore a matching minimized window, returning whether one was found."""
    path = Path(target)
    try:
        if path.is_dir():
            hwnd = _find_minimized_explorer_window(path)
        else:
            hwnd = _find_minimized_program_window(path)
    except Exception:
        return False
    if not hwnd:
        return False
    return _restore_window(hwnd)


def _find_minimized_program_window(target: Path) -> int:
    wanted = _normalized_path(target)
    found = 0
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _lparam):
        nonlocal found
        if not _USER32.IsWindowVisible(hwnd) or not _USER32.IsIconic(hwnd):
            return True
        app = application_from_window(hwnd)
        if app and _normalized_path(app.get("path", "")) == wanted:
            found = int(hwnd)
            return False
        return True

    _USER32.EnumWindows(visit, 0)
    return found


def _find_minimized_explorer_window(target: Path) -> int:
    """Find an Explorer window whose current folder exactly matches target."""
    try:
        import pythoncom
        from win32com.client import Dispatch
    except ImportError:
        return 0

    wanted = _normalized_path(target)
    initialized = False
    try:
        pythoncom.CoInitialize()
        initialized = True
        shell = Dispatch("Shell.Application")
        for window in shell.Windows():
            try:
                hwnd = int(window.HWND)
                folder_path = str(window.Document.Folder.Self.Path or "")
            except Exception:
                continue
            if (
                hwnd
                and _USER32.IsWindowVisible(hwnd)
                and _USER32.IsIconic(hwnd)
                and _normalized_path(folder_path) == wanted
            ):
                return hwnd
    except Exception:
        return 0
    finally:
        if initialized:
            pythoncom.CoUninitialize()
    return 0


def _restore_window(hwnd: int) -> bool:
    if not hwnd:
        return False
    _USER32.ShowWindowAsync(hwnd, SW_RESTORE)
    _USER32.SetForegroundWindow(hwnd)
    return True


def _normalized_path(path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path)))) if path else ""
