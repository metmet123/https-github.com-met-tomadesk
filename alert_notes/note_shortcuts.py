from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut


TIME_SHORTCUTS = (
    ("Q", "5분", 5), ("`", "30분", 30), ("1", "1시간", 60),
    ("2", "2시간", 120), ("3", "3시간", 180), ("4", "4시간", 240),
    ("5", "5시간", 300), ("6", "6시간", 360), ("W", "1일", 1440),
)
VALID_MODIFIERS = ("Alt", "Shift", "Ctrl+Shift")
DEFAULT_MODIFIER = "Alt"
SETTING_MODIFIER = "reminder_time_hotkey_modifier"

FORMAT_SHORTCUTS = {
    "bold": ("굵게", "hotkey_format_bold", "Ctrl+B"),
    "italic": ("기울임", "hotkey_format_italic", "Ctrl+I"),
    "underline": ("밑줄", "hotkey_format_underline", "Ctrl+U"),
    "strike": ("취소선", "hotkey_format_strike", "Ctrl+Shift+X"),
    "black": ("검정", "hotkey_format_black", "Alt+7"),
    "red": ("빨강", "hotkey_format_red", "Alt+8"),
    "blue": ("파랑", "hotkey_format_blue", "Alt+9"),
}

STRUCTURE_SHORTCUTS = {
    "open_link": ("현재 페이지·메모 링크 열기", "hotkey_editor_open_link", "Ctrl+Alt+Enter"),
    "toggle_fold": ("현재 제목·토글 접기/펴기", "hotkey_editor_toggle_fold", "Ctrl+Shift"),
}


def structure_shortcut_value(store, action: str) -> str:
    """Treat the former fold default as the new default without rewriting settings."""
    _label, setting, default = STRUCTURE_SHORTCUTS[action]
    value = store.setting(setting, default)
    if action == "toggle_fold" and value in {"Ctrl+Alt+Space", "Ctrl+Enter"}:
        return default
    return value


def modifier_setting(store) -> str:
    value = store.setting(SETTING_MODIFIER, DEFAULT_MODIFIER)
    return value if value in VALID_MODIFIERS else DEFAULT_MODIFIER


def shortcut_text(modifier: str, key: str) -> str:
    safe = modifier if modifier in VALID_MODIFIERS else DEFAULT_MODIFIER
    return f"{safe}+{key}"


def bind_time_shortcuts(owner, store, callback) -> list[QShortcut]:
    shortcuts = []
    modifier = modifier_setting(store)
    for key, label, minutes in TIME_SHORTCUTS:
        shortcut = QShortcut(QKeySequence(shortcut_text(modifier, key)), owner)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(lambda m=minutes, text=label: callback(m, text))
        shortcuts.append(shortcut)
    return shortcuts
