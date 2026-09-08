import ctypes
import time
from ctypes import wintypes

from hotkey_defs import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN
from hotkey_parser import parse_hotkey, parse_key


INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

_MODIFIER_VIRTUAL_KEYS = (0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5)


# Navigation-cluster keys must carry KEYEVENTF_EXTENDEDKEY when they are
# injected with virtual-key input.  Without it, applications can interpret
# keys such as Home as their numpad equivalents, so Shift+Home fails to make a
# selection.
EXTENDED_VIRTUAL_KEYS = {
    0x21,  # PageUp
    0x22,  # PageDown
    0x23,  # End
    0x24,  # Home
    0x25,  # Left
    0x26,  # Up
    0x27,  # Right
    0x28,  # Down
    0x2D,  # Insert
    0x2E,  # Delete
}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


def send_hotkey(text: str) -> None:
    parsed = parse_hotkey(text) if "+" in text else _single_key(text)
    mods = _modifier_vks(parsed.modifiers)
    for vk in mods:
        _send_key(vk, False)
    extended = parsed.vk in EXTENDED_VIRTUAL_KEYS
    _send_key(parsed.vk, False, extended)
    _send_key(parsed.vk, True, extended)
    for vk in reversed(mods):
        _send_key(vk, True)
    time.sleep(0.05)


def send_virtual_key(vk: int, modifier_vks: list[int] | tuple[int, ...] = ()) -> None:
    """Send a virtual key and its modifiers captured from Windows input state."""
    for modifier_vk in modifier_vks:
        _send_key(int(modifier_vk), False)
    extended = int(vk) in EXTENDED_VIRTUAL_KEYS
    _send_key(int(vk), False, extended)
    _send_key(int(vk), True, extended)
    for modifier_vk in reversed(modifier_vks):
        _send_key(int(modifier_vk), True)
    time.sleep(0.05)


def send_unicode_text(text: str) -> None:
    """Type recorded text without changing the clipboard or sending Ctrl+V."""
    utf16 = str(text).encode("utf-16-le")
    for index in range(0, len(utf16), 2):
        unit = int.from_bytes(utf16[index:index + 2], "little")
        _send_unicode_unit(unit, False)
        _send_unicode_unit(unit, True)


def clipboard_sequence_number() -> int:
    """Return the current clipboard change sequence, or zero when unavailable."""
    try:
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except (AttributeError, OSError):
        return 0


def wait_for_clipboard_change(previous: int, timeout: float = 0.75) -> bool:
    """Allow an external application to finish a recorded Ctrl+C operation."""
    if not previous:
        return False
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if clipboard_sequence_number() != previous:
            return True
        time.sleep(0.01)
    return clipboard_sequence_number() != previous


def send_alt_tab() -> None:
    """Switch to the previous window using Windows' Alt+Tab input sequence."""
    _send_key(0x12, False)  # Alt down
    time.sleep(0.03)
    _send_key(0x09, False)  # Tab down
    _send_key(0x09, True)   # Tab up
    time.sleep(0.03)
    _send_key(0x12, True)   # Alt up: commit the selected window
    time.sleep(0.05)


def wait_for_modifier_release(timeout: float = 0.75) -> bool:
    """Wait briefly for the physical shortcut modifiers to be released."""
    deadline = time.monotonic() + max(0.0, timeout)
    user32 = ctypes.windll.user32
    while any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIER_VIRTUAL_KEYS):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def click(x: int, y: int, button: str = "left") -> None:
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    down, up = _mouse_button_flags(button)
    _send_mouse(down)
    _send_mouse(up)
    time.sleep(0.05)


def scroll(delta: int, axis: str = "vertical", x: int | None = None, y: int | None = None) -> None:
    """Replay a recorded vertical or horizontal mouse-wheel message."""
    if x is not None and y is not None:
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
    flag = MOUSEEVENTF_HWHEEL if str(axis).lower() == "horizontal" else MOUSEEVENTF_WHEEL
    _send_mouse(flag, int(delta))
    time.sleep(0.02)


def drag(start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.2,
         cancel_requested=None) -> bool:
    """Perform a smooth, time-bounded drag with a safe event cadence."""
    ctypes.windll.user32.SetCursorPos(int(start_x), int(start_y))
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    duration = max(0.01, min(float(duration), 60.0))
    move_count = max(2, min(120, round(duration * 60)))
    started = time.perf_counter()
    timer_started = _begin_high_resolution_timer()
    try:
        for index in range(1, move_count + 1):
            if cancel_requested is not None and cancel_requested():
                return False
            deadline = started + duration * index / move_count
            remaining = deadline - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            ratio = index / move_count
            x = round(start_x + (end_x - start_x) * ratio)
            y = round(start_y + (end_y - start_y) * ratio)
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
        # Browsers and desktop grids can process pointer moves asynchronously.
        # Hold the final position briefly before releasing the mouse button so
        # the full selected range is observed.
        time.sleep(0.02)
    finally:
        _send_mouse(MOUSEEVENTF_LEFTUP)
        if timer_started:
            ctypes.windll.winmm.timeEndPeriod(1)
    # A following macro wait provides any longer target-application settle
    # time; keep only a minimal pause after mouse-up here.
    time.sleep(0.02)
    return True


def _single_key(text: str):
    vk, display = parse_key(text)
    return type("SingleKey", (), {"vk": vk, "modifiers": 0, "text": display})


def _modifier_vks(modifiers: int) -> list[int]:
    pairs = [(MOD_CONTROL, 0x11), (MOD_ALT, 0x12), (MOD_SHIFT, 0x10), (MOD_WIN, 0x5B)]
    return [vk for flag, vk in pairs if modifiers & flag]


def _send_key(vk: int, keyup: bool, extended: bool = False) -> None:
    flags = KEYEVENTF_KEYUP if keyup else 0
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    item = INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(vk, 0, flags, 0, None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))


def _send_unicode_unit(unit: int, keyup: bool) -> None:
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if keyup else 0)
    item = INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(0, unit, flags, 0, None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))


def _send_mouse(flags: int, mouse_data: int = 0) -> None:
    item = INPUT(INPUT_MOUSE, INPUTUNION(mi=MOUSEINPUT(0, 0, mouse_data & 0xFFFFFFFF, flags, 0, None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))


def _begin_high_resolution_timer() -> bool:
    """Request 1 ms scheduling only while replaying a drag."""
    try:
        return ctypes.windll.winmm.timeBeginPeriod(1) == 0
    except (AttributeError, OSError):
        return False


def _mouse_button_flags(button: str) -> tuple[int, int]:
    if str(button).lower() == "right":
        return MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    if str(button).lower() != "left":
        raise ValueError(f"Unsupported mouse button: {button}")
    return MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
