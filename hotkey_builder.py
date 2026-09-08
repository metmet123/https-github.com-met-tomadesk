from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget


MODIFIERS = ("Ctrl", "Alt", "Win", "Shift")
NO_MODIFIER = "지정안함"


class HotkeyCaptureEdit(QLineEdit):
    combination_captured = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("원하는 조합을 한 번에 누르세요")

    def keyPressEvent(self, event) -> None:
        label = key_event_label(event)
        if label:
            modifiers = []
            active = event.modifiers()
            for flag, name in (
                (Qt.KeyboardModifier.ControlModifier, "Ctrl"),
                (Qt.KeyboardModifier.AltModifier, "Alt"),
                (Qt.KeyboardModifier.MetaModifier, "Win"),
                (Qt.KeyboardModifier.ShiftModifier, "Shift"),
            ):
                if active & flag:
                    modifiers.append(name)
            combination = "+".join([*modifiers[:3], label])
            self.combination_captured.emit(combination)
        event.accept()


class HotkeyBuilder(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._allow_empty = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.first_modifier = QComboBox()
        self.second_modifier = QComboBox()
        self.third_modifier = QComboBox()
        self.key_edit = HotkeyCaptureEdit()
        self.first_modifier.setAccessibleName("첫 번째 보조키")
        self.second_modifier.setAccessibleName("두 번째 보조키")
        self.third_modifier.setAccessibleName("세 번째 보조키")
        self.key_edit.setAccessibleName("단축키 조합 입력")
        self.first_modifier.addItems(MODIFIERS)
        self.second_modifier.addItem(NO_MODIFIER)
        self.second_modifier.addItems(MODIFIERS)
        self.third_modifier.addItem(NO_MODIFIER)
        self.third_modifier.addItems(MODIFIERS)
        # Long key names (Backspace, PageDown) were being clipped to "ace"/"nter".
        self.key_edit.setMinimumWidth(self.key_edit.fontMetrics().horizontalAdvance("Backspace") + 26)
        layout.addWidget(self.first_modifier)
        layout.addWidget(self.second_modifier)
        layout.addWidget(self.third_modifier)
        layout.addWidget(self.key_edit, 1)
        self.key_edit.combination_captured.connect(self.setText)
        self.first_modifier.currentIndexChanged.connect(self._emit_changed)
        self.second_modifier.currentIndexChanged.connect(self._emit_changed)
        self.third_modifier.currentIndexChanged.connect(self._emit_changed)
        self.key_edit.textChanged.connect(self._emit_changed)

    def _emit_changed(self, *_args) -> None:
        self.changed.emit(self.text())

    def text(self) -> str:
        first = self.first_modifier.currentText()
        parts = [] if first == NO_MODIFIER else [first]
        second = self.second_modifier.currentText()
        if second != NO_MODIFIER:
            parts.append(second)
        third = self.third_modifier.currentText()
        if third != NO_MODIFIER:
            parts.append(third)
        key = self.key_edit.text().strip()
        if key:
            parts.append(key)
        return "+".join(parts)

    def setAllowEmpty(self, allowed: bool) -> None:
        allowed = bool(allowed)
        if allowed == self._allow_empty:
            return
        self._allow_empty = allowed
        if allowed:
            self.first_modifier.insertItem(0, NO_MODIFIER)
        else:
            index = self.first_modifier.findText(NO_MODIFIER)
            if index >= 0:
                self.first_modifier.removeItem(index)

    def setText(self, value: str) -> None:
        modifiers, key = split_hotkey_text(value)
        self.first_modifier.setCurrentText(
            modifiers[0] if modifiers else (NO_MODIFIER if self._allow_empty else "Ctrl")
        )
        self.second_modifier.setCurrentText(modifiers[1] if len(modifiers) > 1 else NO_MODIFIER)
        self.third_modifier.setCurrentText(modifiers[2] if len(modifiers) > 2 else NO_MODIFIER)
        self.key_edit.setText(key)


def split_hotkey_text(value: str) -> tuple[list[str], str]:
    modifiers: list[str] = []
    key = ""
    for part in [item.strip() for item in value.split("+") if item.strip()]:
        normalized = normalized_modifier(part)
        if normalized:
            modifiers.append(normalized)
        else:
            key = display_key(part)
    return modifiers[:3], key


def normalized_modifier(part: str) -> str:
    names = {"CONTROL": "Ctrl", "CTRL": "Ctrl", "ALT": "Alt", "WIN": "Win", "WINDOWS": "Win"}
    names |= {"META": "Win", "SHIFT": "Shift"}
    return names.get(part.upper(), "")


def key_event_label(event) -> str:
    key = event.key()
    if key in _MODIFIER_KEYS:
        return ""
    if event.modifiers() & Qt.KeyboardModifier.KeypadModifier:
        keypad = _KEYPAD_LABELS.get(key)
        if keypad:
            return keypad
    if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:
        return chr(key)
    if Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
        return chr(key)
    if Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F24.value:
        return f"F{key - Qt.Key.Key_F1.value + 1}"
    return _NAMED_LABELS.get(key, "")


def display_key(part: str) -> str:
    upper = part.upper()
    if upper.startswith("NUMPAD"):
        return "Numpad" + upper[6:].title()
    labels = {"ESCAPE": "Esc", "ESC": "Esc", "PAGEUP": "PageUp", "PAGEDOWN": "PageDown"}
    return labels.get(upper, part[:1].upper() + part[1:])


_MODIFIER_KEYS = {Qt.Key.Key_Control.value, Qt.Key.Key_Alt.value, Qt.Key.Key_Shift.value, Qt.Key.Key_Meta.value}
_KEYPAD_LABELS = {**{getattr(Qt.Key, f"Key_{i}").value: f"Numpad{i}" for i in range(10)}}
_KEYPAD_LABELS |= {Qt.Key.Key_Plus.value: "NumpadAdd", Qt.Key.Key_Minus.value: "NumpadSub"}
_NAMED_LABELS = {
    Qt.Key.Key_Space.value: "Space", Qt.Key.Key_Escape.value: "Esc",
    Qt.Key.Key_Return.value: "Enter", Qt.Key.Key_Enter.value: "Enter",
    Qt.Key.Key_Tab.value: "Tab", Qt.Key.Key_Backspace.value: "Backspace",
    Qt.Key.Key_Delete.value: "Delete", Qt.Key.Key_Insert.value: "Insert",
    Qt.Key.Key_Home.value: "Home", Qt.Key.Key_End.value: "End",
    Qt.Key.Key_PageUp.value: "PageUp", Qt.Key.Key_PageDown.value: "PageDown",
    Qt.Key.Key_Up.value: "Up", Qt.Key.Key_Down.value: "Down",
    Qt.Key.Key_Left.value: "Left", Qt.Key.Key_Right.value: "Right",
}
