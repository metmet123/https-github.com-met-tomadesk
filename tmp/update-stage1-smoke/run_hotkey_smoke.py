import ctypes
import time
from ctypes import wintypes


def send_hotkey(user32):
    for vk in (0x11, 0x12, 0x10, 0x4E):
        user32.keybd_event(vk, 0, 0, 0)
    for vk in (0x4E, 0x10, 0x12, 0x11):
        user32.keybd_event(vk, 0, 2, 0)


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
user32.PeekMessageW.restype = wintypes.BOOL

hotkey_id = 49091
modifiers = 0x0002 | 0x0001 | 0x0004 | 0x4000
if not user32.RegisterHotKey(None, hotkey_id, modifiers, 0x4E):
    raise ctypes.WinError(ctypes.get_last_error())
try:
    send_hotkey(user32)
    message = wintypes.MSG()
    deadline = time.monotonic() + 2.5
    triggered = False
    while time.monotonic() < deadline:
        if user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            if message.message == 0x0312 and int(message.wParam) == hotkey_id:
                triggered = True
                break
        time.sleep(0.01)
finally:
    user32.UnregisterHotKey(None, hotkey_id)

if triggered:
    print("HOTKEY_TRIGGERED Ctrl+Alt+Shift+N", flush=True)
raise SystemExit(0 if triggered else 2)
