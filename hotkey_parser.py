from dataclasses import dataclass

from hotkey_defs import (
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, UNSAFE_TO_INTERCEPT,
    HotkeyError,
)


@dataclass(frozen=True)
class ParsedHotkey:
    text: str
    modifiers: int
    vk: int


NAMED_KEYS = {
    "SPACE": 0x20, "ESC": 0x1B, "ESCAPE": 0x1B, "ENTER": 0x0D, "RETURN": 0x0D,
    "TAB": 0x09, "BACKSPACE": 0x08, "DELETE": 0x2E, "DEL": 0x2E,
    "INSERT": 0x2D, "INS": 0x2D, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "UP": 0x26, "DOWN": 0x28,
    "LEFT": 0x25, "RIGHT": 0x27,
    "CAPSLOCK": 0x14, "CAPS": 0x14, "NUMLOCK": 0x90, "SCROLLLOCK": 0x91,
    "PRINTSCREEN": 0x2C, "PRTSC": 0x2C,
    "`": 0xC0, "BACKTICK": 0xC0,
}
NAMED_KEYS |= {f"NUMPAD{i}": 0x60 + i for i in range(10)}
NAMED_KEYS |= {f"NUM{i}": 0x60 + i for i in range(10)}
NAMED_KEYS |= {"NUMPADADD": 0x6B, "NUMPADSUB": 0x6D, "NUMPADSUBTRACT": 0x6D}


def parse_hotkey(value: str) -> ParsedHotkey:
    parts = [part.strip() for part in value.split("+") if part.strip()]
    if len(parts) < 2:
        raise HotkeyError("단축키는 수식키와 실행키가 필요합니다.")
    modifiers, keys, display_modifiers = _parse_parts(parts)
    _validate_modifiers(display_modifiers)
    if not modifiers or len(keys) != 1:
        raise HotkeyError("실행키는 하나만 지정할 수 있습니다.")
    vk, display_key = parse_key(keys[0])
    _validate_reserved(display_modifiers, display_key)
    return ParsedHotkey("+".join([*display_modifiers, display_key]), modifiers | MOD_NOREPEAT, vk)


def can_intercept(parsed: ParsedHotkey) -> bool:
    """이 조합을 다른 프로그램보다 먼저 가져가도 되는가.

    아니라고 답하면 예전처럼 Windows 의 RegisterHotKey 에 맡긴다.  먼저 잡은
    프로그램이 임자가 되지만, 적어도 남의 복사·붙여넣기를 막지는 않는다.
    """
    parts = parsed.text.split("+")
    return (frozenset(parts[:-1]), parts[-1].upper()) not in UNSAFE_TO_INTERCEPT


def parse_key(key: str) -> tuple[int, str]:
    upper = key.upper()
    if len(upper) == 1 and ("A" <= upper <= "Z" or "0" <= upper <= "9"):
        return ord(upper), upper
    if upper in NAMED_KEYS:
        return NAMED_KEYS[upper], _display_key(upper)
    if upper.startswith("F") and upper[1:].isdigit() and 1 <= int(upper[1:]) <= 24:
        return 0x70 + int(upper[1:]) - 1, f"F{int(upper[1:])}"
    raise HotkeyError(f"지원하지 않는 키입니다: {key}")


def _parse_parts(parts: list[str]) -> tuple[int, list[str], list[str]]:
    modifiers = 0
    keys: list[str] = []
    display: list[str] = []
    for part in parts:
        modifiers, handled = _apply_modifier(part, modifiers, display)
        if not handled:
            keys.append(part)
    return modifiers, keys, display


def _apply_modifier(part: str, modifiers: int, display: list[str]) -> tuple[int, bool]:
    names = {"CTRL": ("Ctrl", MOD_CONTROL), "CONTROL": ("Ctrl", MOD_CONTROL), "ALT": ("Alt", MOD_ALT)}
    names |= {"SHIFT": ("Shift", MOD_SHIFT), "WIN": ("Win", MOD_WIN), "WINDOWS": ("Win", MOD_WIN)}
    item = names.get(part.upper())
    if item is None:
        return modifiers, False
    label, flag = item
    display.append(label)
    return modifiers | flag, True


def _display_key(key: str) -> str:
    if key in {"`", "BACKTICK"}:
        return "`"
    if key.startswith("NUMPAD"):
        suffix = {"ADD": "Add", "SUB": "Sub", "SUBTRACT": "Sub"}.get(key[6:], key[6:])
        return f"Numpad{suffix}"
    return {"ESC": "Esc", "ESCAPE": "Esc", "PAGEUP": "PageUp", "PAGEDOWN": "PageDown"}.get(key, key.title())


def _validate_modifiers(display: list[str]) -> None:
    if len(display) != len(set(display)):
        raise HotkeyError("같은 수식키를 중복 지정할 수 없습니다.")
    if len(display) > 3:
        raise HotkeyError("수식키는 최대 3개까지만 사용할 수 있습니다.")


def _validate_reserved(display: list[str], key: str) -> None:
    reserved = {
        (frozenset({"Alt"}), "TAB"), (frozenset({"Alt"}), "F4"),
        (frozenset({"Ctrl", "Alt"}), "DELETE"), (frozenset({"Win"}), "L"),
        (frozenset({"Win"}), "D"), (frozenset({"Win"}), "E"), (frozenset({"Win"}), "R"),
    }
    if (frozenset(display), key.upper()) in reserved:
        raise HotkeyError("Windows 예약 단축키는 사용할 수 없습니다.")
