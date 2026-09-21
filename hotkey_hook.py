"""전역 단축키를 다른 프로그램보다 먼저 잡는 낮은 수준 키보드 갈고리.

RegisterHotKey 는 먼저 잡은 프로그램이 임자다.  다른 프로그램이 이미 같은
조합을 쓰고 있으면 우리 것은 등록조차 되지 않고, 눌러도 그쪽이 먼저 받는다.
낮은 수준 갈고리(WH_KEYBOARD_LL)는 Windows 가 단축키를 나눠 주기 전에 키를
보므로, 우리가 먼저 가져가고 그 뒤로는 넘기지 않을 수 있다.

갈고리 안에서 오래 머물면 컴퓨터 전체의 입력이 멈춘다.  그래서 이 안에서는
표를 한 번 찾고 메시지 하나를 보내는 일만 한다.  실제 처리는 창이 자기 차례에
한다.  갈고리는 오로지 메시지만 도는 제 스레드에 걸어, 창이 바빠도 키 입력이
밀리지 않게 한다.

Windows 가 우리보다 아래에서 처리하는 조합(Ctrl+Alt+Del, Win+L 등)은 어떤
방법으로도 가져올 수 없고, 가져오면 안 되는 조합(Ctrl+C 등)은 hotkey_defs 의
UNSAFE_TO_INTERCEPT 가 막는다.
"""

import ctypes
import os
import threading
from ctypes import wintypes

from hotkey_defs import (
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, WM_HOTKEY,
)

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_KEYUP = 0x0101
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
# 왼쪽·오른쪽을 가리지 않는 대표 키.  GetAsyncKeyState 는 이 값으로 양쪽을 다 본다.
MODIFIER_PROBES = (
    (0x11, MOD_CONTROL), (0x12, MOD_ALT), (0x10, MOD_SHIFT),
    (0x5B, MOD_WIN), (0x5C, MOD_WIN),
)
MODIFIER_KEYS = frozenset({0x10, 0x11, 0x12, 0x5B, 0x5C,
                           0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5})
_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_USER32.GetForegroundWindow.restype = wintypes.HWND
_USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def foreground_is_this_process() -> bool:
    """Check the actual foreground owner at key-down, not a polling snapshot."""
    try:
        hwnd = _USER32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == os.getpid()
    except OSError:
        return False


class HotkeyMatcher:
    """어떤 키를 우리가 가져갈지 정하는 표.  창(Windows)과 상관없는 부분."""

    def __init__(self):
        self._claims: dict[int, tuple[int, int, bool]] = {}
        self._lock = threading.Lock()

    def claim(self, hotkey_id: int, modifiers: int, vk: int, *, focus_only: bool = False) -> None:
        with self._lock:
            self._claims[int(hotkey_id)] = (int(modifiers) & ~MOD_NOREPEAT, int(vk), bool(focus_only))

    def release(self, hotkey_id: int) -> None:
        with self._lock:
            self._claims.pop(int(hotkey_id), None)

    def clear(self) -> None:
        with self._lock:
            self._claims.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._claims)

    def match(self, vk: int, modifiers: int) -> int | None:
        """누른 키가 맡아 둔 조합과 꼭 맞으면 그 번호를 준다.

        수식키가 하나라도 더 눌려 있으면 맞지 않는 것으로 본다.  Ctrl+Alt+N 을
        맡아 뒀는데 Ctrl+Alt+Shift+N 까지 가져가면 남의 단축키를 먹는다.
        """
        wanted = (int(modifiers) & ~MOD_NOREPEAT, int(vk))
        with self._lock:
            for hotkey_id, claim in self._claims.items():
                if claim[:2] == wanted:
                    return hotkey_id
        return None

    def focus_only(self, hotkey_id: int) -> bool:
        with self._lock:
            claim = self._claims.get(int(hotkey_id))
            return bool(claim and claim[2])


class _KeyboardHookData(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class KeyboardHook:
    """맡아 둔 조합을 가로채 창에 WM_HOTKEY 로 알려 주는 갈고리."""

    def __init__(self, hwnd: int, matcher: HotkeyMatcher | None = None,
                 foreground_checker=None):
        self.hwnd = int(hwnd)
        self.matcher = matcher or HotkeyMatcher()
        self.foreground_checker = foreground_checker or foreground_is_this_process
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._swallowed: set[int] = set()
        self.error: Exception | None = None

    # ------------------------------------------------------------- 시작 --
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 1.0) -> bool:
        """갈고리를 건다.  걸지 못하면 False 를 주고 조용히 물러난다."""
        if self.running:
            return True
        self.error = None
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._pump, name="hotkey-priority-hook", daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout) or self.error is not None:
            self.stop()
            return False
        return True

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(1)
        self._thread_id = 0
        self._swallowed.clear()

    # ------------------------------------------------------------ 알맹이 --
    def _pump(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        hook_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, hook_proc_type, wintypes.HINSTANCE, wintypes.DWORD
        ]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._thread_id = int(kernel32.GetCurrentThreadId())
        message = wintypes.MSG()
        # 다른 스레드가 WM_QUIT 을 보내기 전에 이 스레드가 큐를 갖게 한다.
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)

        def modifiers_now() -> int:
            state = 0
            for vk, flag in MODIFIER_PROBES:
                if user32.GetAsyncKeyState(vk) & 0x8000:
                    state |= flag
            return state

        @hook_proc_type
        def callback(code, message_id, data):
            try:
                if code >= 0:
                    verdict = self._decide(int(message_id), data, modifiers_now)
                    if verdict is not None:
                        user32.PostMessageW(self.hwnd, WM_HOTKEY, verdict, 0)
                        return 1
                    if self._swallow_release(int(message_id), data):
                        return 1
            except Exception:
                # 갈고리 안에서 터지면 컴퓨터 전체의 입력이 막힌다.  무슨 일이
                # 있어도 키는 흘려보낸다.
                pass
            return user32.CallNextHookEx(None, code, message_id, data)

        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, callback, None, 0)
        if not hook:
            code = ctypes.get_last_error()
            self.error = OSError(code, ctypes.FormatError(code))
            self._ready.set()
            return
        self._callback = callback  # 파이썬이 거둬 가면 갈고리가 무너진다
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnhookWindowsHookEx(hook)

    def _decide(self, message_id: int, data, modifiers_now) -> int | None:
        if message_id not in (WM_KEYDOWN, WM_SYSKEYDOWN):
            return None
        event = ctypes.cast(data, ctypes.POINTER(_KeyboardHookData)).contents
        if event.flags & LLKHF_INJECTED:
            # 반복작업이 스스로 눌러 만든 키다.  이걸 잡으면 제 꼬리를 문다.
            return None
        vk = int(event.vkCode)
        if vk in MODIFIER_KEYS:
            return None
        hotkey_id = self.matcher.match(vk, modifiers_now())
        if hotkey_id is None:
            return None
        if self.matcher.focus_only(hotkey_id) and not self.foreground_checker():
            return None
        self._swallowed.add(vk)
        return hotkey_id

    def _swallow_release(self, message_id: int, data) -> bool:
        """가로챈 키의 뗌까지 삼킨다.  누름 없는 뗌만 받은 프로그램이 없도록."""
        if message_id not in (WM_KEYUP, WM_SYSKEYUP) or not self._swallowed:
            return False
        event = ctypes.cast(data, ctypes.POINTER(_KeyboardHookData)).contents
        vk = int(event.vkCode)
        if vk in self._swallowed:
            self._swallowed.discard(vk)
            return True
        return False
