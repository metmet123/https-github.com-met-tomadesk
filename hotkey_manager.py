"""전역 단축키 등록.  될 수 있으면 다른 프로그램보다 먼저 가져온다."""

import ctypes
from ctypes import wintypes

from hotkey_defs import WM_HOTKEY, HotkeyError
from hotkey_hook import KeyboardHook
from hotkey_parser import can_intercept, parse_hotkey


class HotkeyManager:
    """두 가지 길로 단축키를 잡는다.

    1순위는 낮은 수준 갈고리다.  Windows 가 단축키를 나눠 주기 전에 키를 보므로
    다른 프로그램이 같은 조합을 쓰고 있어도 우리가 먼저 가져온다.
    가로채면 안 되는 조합(Ctrl+C 등)과 갈고리를 걸지 못한 경우에만 예전처럼
    RegisterHotKey 에 맡긴다.  이때는 먼저 잡은 프로그램이 임자다.
    """

    def __init__(self, hwnd: int, hook_factory=KeyboardHook):
        self.hwnd = hwnd
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        self._registered: dict[int, str] = {}
        self._callbacks: dict[int, callable] = {}
        self._priority: set[int] = set()
        self._hook_factory = hook_factory
        self._hook = None
        self._hook_failed = False

    # ------------------------------------------------------------ 갈고리 --
    @property
    def hook(self):
        return self._hook

    def priority_ids(self) -> set[int]:
        """다른 프로그램보다 먼저 가져오고 있는 단축키 번호."""
        return set(self._priority)

    def _ensure_hook(self):
        if self._hook is not None or self._hook_failed:
            return self._hook
        try:
            hook = self._hook_factory(self.hwnd)
            started = bool(hook.start())
        except Exception:
            hook, started = None, False
        if not started:
            # 한 번 실패하면 다시 시도하지 않는다.  단축키를 등록할 때마다
            # 스레드를 새로 띄웠다 접으면 그것대로 부담이다.
            self._hook_failed = True
            self._hook = None
            return None
        self._hook = hook
        return hook

    # -------------------------------------------------------------- 등록 --
    def register(self, hotkey_id: int, hotkey_text: str, callback) -> str:
        parsed = parse_hotkey(hotkey_text)
        self.unregister(hotkey_id)
        if can_intercept(parsed):
            hook = self._ensure_hook()
            if hook is not None:
                hook.matcher.claim(hotkey_id, parsed.modifiers, parsed.vk)
                self._priority.add(hotkey_id)
                self._registered[hotkey_id] = parsed.text
                self._callbacks[hotkey_id] = callback
                return parsed.text
        ctypes.set_last_error(0)
        ok = self._user32.RegisterHotKey(self.hwnd, hotkey_id, parsed.modifiers, parsed.vk)
        if not ok:
            error_code = ctypes.get_last_error()
            reason = ctypes.FormatError(error_code).strip() if error_code else "다른 프로그램에서 사용 중"
            raise HotkeyError(f"{hotkey_text}: {reason}")
        self._registered[hotkey_id] = parsed.text
        self._callbacks[hotkey_id] = callback
        return parsed.text

    def unregister(self, hotkey_id: int) -> None:
        if hotkey_id not in self._registered:
            return
        if hotkey_id in self._priority:
            self._priority.discard(hotkey_id)
            if self._hook is not None:
                self._hook.matcher.release(hotkey_id)
        else:
            self._user32.UnregisterHotKey(self.hwnd, hotkey_id)
        self._registered.pop(hotkey_id, None)
        self._callbacks.pop(hotkey_id, None)

    def unregister_all(self) -> None:
        for hotkey_id in list(self._registered):
            self.unregister(hotkey_id)

    def shutdown(self) -> None:
        """프로그램을 닫을 때.  갈고리를 반드시 풀고 나간다."""
        self.unregister_all()
        hook, self._hook = self._hook, None
        if hook is not None:
            hook.stop()

    # ------------------------------------------------------------ 알림받기 --
    def handle_native_event(self, message) -> bool:
        msg = wintypes.MSG.from_address(int(message))
        if msg.message != WM_HOTKEY:
            return False
        callback = self._callbacks.get(int(msg.wParam))
        if callback is None:
            return False
        callback()
        return True
