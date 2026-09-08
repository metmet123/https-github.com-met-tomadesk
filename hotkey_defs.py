WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

HOTKEY_ID_START = 1000
HOTKEY_ID_STOP = 999


# 우리가 다른 프로그램보다 먼저 가져가면 안 되는 조합.
#
# 앞쪽은 어느 프로그램에서나 뜻이 정해진 편집 단축키다.  이걸 삼키면 복사·
# 붙여넣기가 컴퓨터 전체에서 멈춘다.  뒤쪽은 Windows 가 우리보다 아래에서
# 처리해 애초에 가져올 수 없는 것들이다.  둘 다 예전처럼 Windows 에 맡긴다.
UNCHANGEABLE_EDIT_KEYS = ("C", "V", "X", "Z", "Y", "A", "S", "P", "F", "N", "O", "W", "T")
SYSTEM_OWNED_COMBINATIONS = frozenset({
    (frozenset({"Ctrl", "Shift"}), "ESC"),
    (frozenset({"Ctrl", "Alt"}), "DELETE"),
    (frozenset({"Win"}), "L"),
    (frozenset({"Alt"}), "TAB"),
    (frozenset({"Alt"}), "F4"),
})
UNSAFE_TO_INTERCEPT = frozenset(
    {(frozenset({"Ctrl"}), key) for key in UNCHANGEABLE_EDIT_KEYS}
) | SYSTEM_OWNED_COMBINATIONS


class HotkeyError(ValueError):
    pass
