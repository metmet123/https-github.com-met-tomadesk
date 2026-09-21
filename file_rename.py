"""Read-only file loading and name preview for the batch rename window."""
from pathlib import Path
import os
import csv
import io


def parse_clipboard(text):
    """TSV with spreadsheet quoting. Keep whitespace, empty cells and zeros."""
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t", strict=True))
    except csv.Error as exc:
        raise ValueError("붙여넣기 따옴표 형식이 올바르지 않습니다.") from exc
    rows = [row or [""] for row in rows]
    if not rows:
        return [[""]]
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("행마다 열 개수가 다릅니다. 직사각형 범위를 복사하세요.")
    return rows


def format_clipboard(rows):
    stream = io.StringIO(newline="")
    csv.writer(stream, delimiter="\t", lineterminator="\r\n").writerows(rows)
    return stream.getvalue()


def compose_name(path, parts, separator=""):
    values = [part for part in parts if part != ""]
    return separator.join(values) + Path(path).suffix if values else None


def mark_edge_spaces(name):
    left = len(name) - len(name.lstrip(" "))
    right = len(name) - len(name.rstrip(" "))
    if left == len(name):
        return "·" * left
    return "·" * left + name[left:len(name) - right if right else len(name)] + "·" * right


def load_files(paths, existing=(), is_file=None):
    """Preserve input order, deduplicate and report skipped non-file paths."""
    is_file = is_file or (lambda path: path.is_file())
    key = lambda path: os.path.normcase(os.path.abspath(path))
    seen = {key(path) for path in existing}
    accepted, skipped = [], []
    for value in paths:
        path = Path(value).absolute()
        if key(path) in seen:
            continue
        try:
            valid = is_file(path)
        except OSError:
            valid = False
        if not valid:
            skipped.append(str(path))
            continue
        seen.add(key(path))
        accepted.append(path)
    return accepted, skipped


def explorer_selection(hwnd=None, windows=None):
    """Read the foreground Explorer selection before activating our window.

    SVGIO_FLAG_VIEWORDER requests visible order instead of focus-item-first order.
    Virtual items and folders are filtered by load_files at the UI boundary.
    """
    import win32gui
    if hwnd is None:
        hwnd = win32gui.GetForegroundWindow()
    if win32gui.GetClassName(hwnd) not in {"CabinetWClass", "ExploreWClass"}:
        return []
    if windows is not None:
        return _selection_from_windows(hwnd, windows)
    import pythoncom
    from win32com.client import Dispatch
    pythoncom.CoInitialize()
    try:
        return _selection_from_windows(hwnd, Dispatch("Shell.Application").Windows())
    finally:
        pythoncom.CoUninitialize()


def _selection_from_windows(hwnd, windows):
    import pythoncom
    import win32con
    from win32com.shell import shell
    for window in windows:
        if int(window.HWND) == hwnd:
            if not window.Document.SelectedItems().Count:
                return []
            provider = window._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
            browser = provider.QueryService(shell.SID_STopLevelBrowser, shell.IID_IShellBrowser)
            view = browser.QueryActiveShellView()
            # Microsoft: GetItemObject SVGIO_SELECTION | SVGIO_FLAG_VIEWORDER.
            data = view.GetItemObject(0x80000001, pythoncom.IID_IDataObject)
            medium = data.GetData((win32con.CF_HDROP, None, pythoncom.DVASPECT_CONTENT,
                                   -1, pythoncom.TYMED_HGLOBAL))
            return [shell.DragQueryFileW(medium.data_handle, i)
                    for i in range(shell.DragQueryFileW(medium.data_handle, -1))]
    return []
