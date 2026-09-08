"""Physical-key cancellation checks for synchronous macro playback."""

import ctypes

from hotkey_defs import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN
from hotkey_parser import parse_hotkey


_MODIFIER_KEYS = {
    MOD_CONTROL: (0x11, 0xA2, 0xA3),
    MOD_ALT: (0x12, 0xA4, 0xA5),
    MOD_SHIFT: (0x10, 0xA0, 0xA1),
    MOD_WIN: (0x5B, 0x5C),
}


class StopHotkeyMonitor:
    """Checks the configured stop shortcut without depending on Qt events."""

    def __init__(self, hotkey: str):
        self.set_hotkey(hotkey)

    def set_hotkey(self, hotkey: str) -> None:
        self.hotkey = parse_hotkey(hotkey)

    def pressed(self) -> bool:
        try:
            user32 = ctypes.windll.user32
            if not _is_down(user32, self.hotkey.vk):
                return False
            return all(
                any(_is_down(user32, vk) for vk in virtual_keys)
                for flag, virtual_keys in _MODIFIER_KEYS.items()
                if self.hotkey.modifiers & flag
            )
        except (AttributeError, OSError):
            return False


def _is_down(user32, vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)
