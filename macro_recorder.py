"""Windows input recording helpers for repeat-action macros."""

import ctypes
import queue
import threading
import time
from ctypes import wintypes


MIN_WAIT_SECONDS = 0.15
GENERIC_SHIFT = 0x10
GENERIC_CONTROL = 0x11
GENERIC_ALT = 0x12
GENERIC_WIN = 0x5B
SHIFT_KEYS = (0x10, 0xA0, 0xA1)
CONTROL_KEYS = (0x11, 0xA2, 0xA3)
ALT_KEYS = (0x12, 0xA4, 0xA5)
WIN_KEYS = (0x5B, 0x5C)
MODIFIER_KEYS = frozenset((*SHIFT_KEYS, *CONTROL_KEYS, *ALT_KEYS, *WIN_KEYS))
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_KEYUP = 0x0101
WM_SYSKEYUP = 0x0105
WM_LBUTTONDOWN = 0x0201
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
WM_QUIT = 0x0012


class MacroRecorder:
    """Collects click/text markers and converts them into macro steps."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self.running = False
        self._events: list[dict] = []
        self._pending_text_at: float | None = None
        self._pending_enter = False
        self._pending_text = ""
        self.ignore_click = None

    def start(self) -> None:
        with self._lock:
            self.running = True
            self._events = []
            self._pending_text_at = None
            self._pending_enter = False
            self._pending_text = ""

    def record_click(self, x: int, y: int, button: str = "left", timestamp: float | None = None) -> None:
        with self._lock:
            if not self.running:
                return
            if self.ignore_click is not None and self.ignore_click(int(x), int(y)):
                return
            now = self._clock() if timestamp is None else timestamp
            self._flush_text()
            event = {"type": "click", "x": int(x), "y": int(y), "at": now}
            if button != "left":
                event["button"] = button
            self._events.append(event)

    def record_drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
                    start_timestamp: float | None = None, end_timestamp: float | None = None) -> None:
        with self._lock:
            if not self.running:
                return
            if self.ignore_click is not None and self.ignore_click(int(start_x), int(start_y)):
                return
            started = self._clock() if start_timestamp is None else start_timestamp
            ended = self._clock() if end_timestamp is None else end_timestamp
            self._flush_text()
            self._events.append({
                "type": "drag", "start_x": int(start_x), "start_y": int(start_y),
                "end_x": int(end_x), "end_y": int(end_y),
                "duration": round(max(0.01, ended - started), 2), "at": started, "end_at": ended,
            })

    def record_wheel(self, delta: int, axis: str = "vertical", x: int = 0, y: int = 0,
                     timestamp: float | None = None) -> None:
        with self._lock:
            if not self.running or not delta:
                return
            now = self._clock() if timestamp is None else timestamp
            self._flush_text()
            self._events.append({
                "type": "wheel", "delta": int(delta), "axis": str(axis),
                "x": int(x), "y": int(y), "at": now,
            })

    def record_key(self, key: str, timestamp: float | None = None, virtual_key: int | None = None,
                   modifier_vks: list[int] | tuple[int, ...] = ()) -> None:
        with self._lock:
            if not self.running:
                return
            now = self._clock() if timestamp is None else timestamp
            self._flush_text()
            event = {"type": "key", "key": key, "at": now}
            if virtual_key is not None:
                event["vk"] = int(virtual_key)
            if modifier_vks:
                event["modifier_vks"] = [int(value) for value in modifier_vks]
            self._events.append(event)

    def record_text_input(self, text: str = "", press_enter: bool = False, backspace: bool = False,
                          timestamp: float | None = None) -> None:
        with self._lock:
            if not self.running:
                return
            if self._pending_text_at is None:
                self._pending_text_at = self._clock() if timestamp is None else timestamp
            if backspace:
                self._pending_text = self._pending_text[:-1]
            else:
                self._pending_text += text
            self._pending_enter = self._pending_enter or press_enter

    def stop(self) -> list[dict]:
        with self._lock:
            self._flush_text()
            self.running = False
            events = list(self._events)
        return self._steps_from_events(events)

    def _flush_text(self) -> None:
        if self._pending_text_at is not None:
            self._events.append({"type": "text", "text": self._pending_text, "press_enter": self._pending_enter,
                                 "at": self._pending_text_at})
        self._pending_text_at = None
        self._pending_enter = False
        self._pending_text = ""

    @staticmethod
    def _steps_from_events(events: list[dict]) -> list[dict]:
        steps: list[dict] = []
        previous_at: float | None = None
        for event in events:
            event_at = float(event["at"])
            if previous_at is not None:
                delay = event_at - previous_at
                if delay >= MIN_WAIT_SECONDS:
                    steps.append({"type": "wait", "seconds": round(delay, 2)})
            steps.append({key: value for key, value in event.items() if key not in {"at", "end_at"}})
            previous_at = float(event.get("end_at", event_at))
        return steps


class WindowsHookRecorder(MacroRecorder):
    """Windows recorder that observes input state without intercepting it.

    Low-level hooks run inside the Windows input path and can make the whole
    desktop unresponsive if a callback stalls.  Polling is deliberately used
    here: it never consumes, delays, or blocks the user's input.
    """

    # Scan all non-mouse virtual keys: Tab, Caps Lock, arrows, function keys,
    # and other non-text keys must be recorded too.
    _RECORDABLE_KEYS = tuple(range(0x08, 0xFF))
    _MODIFIER_KEYS = MODIFIER_KEYS

    def __init__(self, clock=time.monotonic):
        super().__init__(clock)
        self._thread: threading.Thread | None = None
        self._wheel_thread: threading.Thread | None = None
        self._wheel_thread_id = 0
        self._wheel_ready = threading.Event()
        self._wheel_error: Exception | None = None
        self._wheel_events: queue.SimpleQueue = queue.SimpleQueue()
        self._stop_event = threading.Event()

    def start(self) -> None:
        super().start()
        self._stop_event.clear()
        self._wheel_events = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._poll_input, name="macro-recorder", daemon=True)
        self._thread.start()
        self._wheel_ready.clear()
        self._wheel_error = None
        self._wheel_thread = threading.Thread(
            target=self._capture_wheel_messages, name="macro-wheel-recorder", daemon=True
        )
        self._wheel_thread.start()
        if not self._wheel_ready.wait(1.0) or self._wheel_error is not None:
            self._stop_threads()
            super().stop()
            detail = self._wheel_error or "휠 감지 스레드가 응답하지 않습니다."
            raise RuntimeError(f"마우스 휠 녹화를 시작할 수 없습니다: {detail}")

    def stop(self) -> list[dict]:
        self._stop_threads()
        return super().stop()

    def _stop_threads(self) -> None:
        self._stop_event.set()
        if self._wheel_thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._wheel_thread_id, WM_QUIT, 0, 0)
        if self._wheel_thread is not None:
            self._wheel_thread.join(1)
        if self._thread is not None:
            self._thread.join(1)
        self._thread = None
        self._wheel_thread = None
        self._wheel_thread_id = 0

    def _poll_input(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.GetKeyState.argtypes = [ctypes.c_int]
        user32.GetKeyState.restype = ctypes.c_short
        user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        user32.MapVirtualKeyW.restype = wintypes.UINT
        user32.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_byte),
                                       wintypes.LPWSTR, ctypes.c_int, wintypes.UINT, wintypes.HKL]
        user32.ToUnicodeEx.restype = ctypes.c_int
        user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        user32.GetKeyboardLayout.restype = wintypes.HKL
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        left_was_down = False
        left_start: tuple[int, int, float] | None = None
        right_was_down = False
        key_was_down = {key: False for key in self._RECORDABLE_KEYS}
        alt_was_down = False
        while not self._stop_event.wait(0.01):
            self._drain_wheel_events()
            left_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
            if left_down and not left_was_down:
                point = _Point()
                if user32.GetCursorPos(ctypes.byref(point)):
                    left_start = (point.x, point.y, self._clock())
            elif left_was_down and not left_down and left_start is not None:
                point = _Point()
                if user32.GetCursorPos(ctypes.byref(point)):
                    start_x, start_y, started = left_start
                    if abs(point.x - start_x) >= 3 or abs(point.y - start_y) >= 3:
                        self.record_drag(start_x, start_y, point.x, point.y, started, self._clock())
                    else:
                        self.record_click(start_x, start_y, "left", started)
                left_start = None
            left_was_down = left_down

            right_down = bool(user32.GetAsyncKeyState(0x02) & 0x8000)
            if right_down and not right_was_down:
                point = _Point()
                if user32.GetCursorPos(ctypes.byref(point)):
                    self.record_click(point.x, point.y, "right")
            right_was_down = right_down

            key_states = {key: user32.GetAsyncKeyState(key) for key in self._RECORDABLE_KEYS}
            control_down = _any_key_down(key_states, CONTROL_KEYS)
            alt_down = _any_key_down(key_states, ALT_KEYS)
            win_down = _any_key_down(key_states, WIN_KEYS)
            shift_down = _any_key_down(key_states, SHIFT_KEYS)
            for key, state in key_states.items():
                if key in self._MODIFIER_KEYS:
                    continue
                # The low-order bit reports a press since the previous call,
                # while the high-order transition catches Alt+Tab reliably.
                key_down = bool(state & 0x8000)
                pressed = bool(state & 0x0001) or (key_down and not key_was_down[key])
                key_was_down[key] = key_down
                if pressed:
                    if key == 0x09 and (alt_down or alt_was_down or any(key_states[alt] & 0x0001 for alt in ALT_KEYS)):
                        self.record_key("Alt+Tab", virtual_key=key, modifier_vks=[GENERIC_ALT])
                        continue
                    shortcut_down = control_down or alt_down or win_down or (shift_down and not _is_text_key(key))
                    if shortcut_down:
                        combo = _hotkey_for_pressed_key(key, control_down, alt_down, win_down, shift_down)
                        if combo:
                            self.record_key(combo, virtual_key=key,
                                            modifier_vks=_active_modifier_vks(control_down, alt_down,
                                                                            win_down, shift_down))
                    elif _is_text_key(key):
                        if key == 0x08:
                            self.record_key("Backspace", virtual_key=key)
                        elif key == 0x0D:
                            self.record_text_input(press_enter=True)
                        else:
                            text = _unicode_for_key(user32, key, _foreground_layout(user32))
                            if text:
                                self.record_text_input(text)
                            else:
                                self.record_key(_key_label(key), virtual_key=key)
                    else:
                        self.record_key(_key_label(key), virtual_key=key)
            alt_was_down = alt_down
        self._drain_wheel_events()

    def _drain_wheel_events(self) -> None:
        while True:
            try:
                delta, axis, x, y, timestamp = self._wheel_events.get_nowait()
            except queue.Empty:
                return
            self.record_wheel(delta, axis, x, y, timestamp)

    def _capture_wheel_messages(self) -> None:
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
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._wheel_thread_id = int(kernel32.GetCurrentThreadId())
        message = wintypes.MSG()
        # Ensure this thread owns a message queue before another thread can
        # request shutdown with PostThreadMessageW.
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)

        @hook_proc_type
        def callback(code, message, data):
            if code >= 0 and int(message) in {WM_MOUSEWHEEL, WM_MOUSEHWHEEL}:
                event = ctypes.cast(data, ctypes.POINTER(_MouseHookData)).contents
                delta = ctypes.c_short((int(event.mouseData) >> 16) & 0xFFFF).value
                axis = "horizontal" if int(message) == WM_MOUSEHWHEEL else "vertical"
                self._wheel_events.put((delta, axis, event.pt.x, event.pt.y, self._clock()))
            return user32.CallNextHookEx(None, code, message, data)

        hook = user32.SetWindowsHookExW(WH_MOUSE_LL, callback, None, 0)
        if not hook:
            error_code = ctypes.get_last_error()
            self._wheel_error = OSError(error_code, ctypes.FormatError(error_code))
            self._wheel_ready.set()
            return
        self._wheel_ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnhookWindowsHookEx(hook)


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MouseHookData(ctypes.Structure):
    _fields_ = [("pt", _Point), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KeyboardHookData(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


def _is_text_key(vk: int) -> bool:
    # Tab must remain a physical key step so focus movement is replayed,
    # rather than being pasted as a tab character into a text field.
    return (0x30 <= vk <= 0x5A) or vk in {0x08, 0x0D, 0x20} or 0xBA <= vk <= 0xDE


def _key_label(vk: int) -> str:
    labels = {
        0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x14: "CapsLock",
        0x1B: "Esc", 0x20: "Space", 0x21: "PageUp", 0x22: "PageDown",
        0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
        0x2C: "PrintScreen", 0x2D: "Insert", 0x2E: "Delete", 0x90: "NumLock", 0x91: "ScrollLock",
    }
    if vk in labels:
        return labels[vk]
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x70 + 1}"
    if 0x60 <= vk <= 0x69:
        return f"Numpad{vk - 0x60}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    return f"VK_{vk:02X}"


def _hotkey_for_pressed_key(vk: int, control: bool, alt: bool, win: bool, shift: bool) -> str:
    """Return a replayable shortcut for a non-modifier key press."""
    if vk in MODIFIER_KEYS:
        return ""
    parts = []
    if control:
        parts.append("Ctrl")
    if alt:
        parts.append("Alt")
    if win:
        parts.append("Win")
    if shift:
        parts.append("Shift")
    return "+".join([*parts, _key_label(vk)]) if parts else ""


def _any_key_down(key_states: dict[int, int], keys: tuple[int, ...]) -> bool:
    return any(key_states.get(key, 0) & 0x8000 for key in keys)


def _active_modifier_vks(control: bool, alt: bool, win: bool, shift: bool) -> list[int]:
    """Normalize left/right modifier aliases into one replayable key per modifier."""
    values = []
    if control:
        values.append(GENERIC_CONTROL)
    if alt:
        values.append(GENERIC_ALT)
    if win:
        values.append(GENERIC_WIN)
    if shift:
        values.append(GENERIC_SHIFT)
    return values


def _unicode_for_key(user32, vk: int, layout) -> str:
    """Translate a key using the foreground application's keyboard layout."""
    state = _async_keyboard_state(user32)
    buffer = ctypes.create_unicode_buffer(8)
    result = user32.ToUnicodeEx(vk, user32.MapVirtualKeyW(vk, 0), state, buffer, len(buffer), 0,
                                layout)
    return buffer.value[:result] if result > 0 else ""


def _async_keyboard_state(user32):
    """Build ToUnicodeEx state from global key state, not recorder-thread state."""
    state = (ctypes.c_byte * 256)()
    for key in (0x10, 0x11, 0x12):  # Shift, Ctrl, Alt
        value = user32.GetAsyncKeyState(key)
        if value & 0x8000:
            state[key] = 0x80
    # GetAsyncKeyState's low bit may already have been consumed by polling.
    # GetKeyState reliably returns the current Caps Lock toggle state.
    if user32.GetKeyState(0x14) & 0x0001:
        state[0x14] = 0x01
    return state


def _foreground_layout(user32):
    foreground = user32.GetForegroundWindow()
    if foreground:
        process_id = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(foreground, ctypes.byref(process_id))
        if thread_id:
            return user32.GetKeyboardLayout(thread_id)
    return user32.GetKeyboardLayout(0)


def _clipboard_text() -> str:
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
