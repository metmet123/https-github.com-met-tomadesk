from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QMessageBox

from hotkey_builder import HotkeyBuilder
from hotkey_parser import parse_hotkey

from .note_shortcuts import (
    DEFAULT_MODIFIER, FORMAT_SHORTCUTS, STRUCTURE_SHORTCUTS, SETTING_MODIFIER, TIME_SHORTCUTS, VALID_MODIFIERS,
    shortcut_text,
)
from .value_input_guard import install_value_input_guard
from .insert_menu import HEADING_ITEMS


SETTING_ALWAYS_TOP = "hotkey_always_on_top"
SETTING_POSTIT = "hotkey_simple_mode"
DEFAULT_ALWAYS_TOP = "Ctrl+Alt+Num0"
DEFAULT_POSTIT = "Ctrl+H"
LAYOUT_SETTING = "memo_editor_layout"
NEW_NOTE_FOCUS_SETTING = "memo_new_note_focus_mode"


class EditorShortcutSettingsDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("노트 단축키 설정")
        layout = QFormLayout(self)
        self.modifier = QComboBox()
        self.modifier.addItems(VALID_MODIFIERS)
        self.modifier.setCurrentText(store.setting(SETTING_MODIFIER, DEFAULT_MODIFIER))
        layout.addRow("알림 시간 보조키", self.modifier)
        self.layout_mode = QComboBox()
        self.layout_mode.addItem("간결한 편집 화면", "compact")
        self.layout_mode.addItem("이전 편집 화면", "classic")
        self.layout_mode.setCurrentIndex(
            max(0, self.layout_mode.findData(store.setting(LAYOUT_SETTING, "compact")))
        )
        layout.addRow("메모 화면 배치", self.layout_mode)
        layout.addRow("", QLabel("배치 변경은 프로그램을 다시 열면 적용됩니다."))
        self.new_note_focus = QCheckBox("새 메모를 만들면 집중 모드로 열기")
        self.new_note_focus.setChecked(
            store.setting(NEW_NOTE_FOCUS_SETTING, "false").lower() == "true"
        )
        layout.addRow("새 메모", self.new_note_focus)
        self.always_top = self._builder(store.setting(SETTING_ALWAYS_TOP, DEFAULT_ALWAYS_TOP))
        self.postit = self._builder(store.setting(SETTING_POSTIT, DEFAULT_POSTIT))
        layout.addRow("항상 위", self.always_top)
        layout.addRow("포스트잇 모드", self.postit)
        self.format_builders = {}
        for action, (label, setting, default) in FORMAT_SHORTCUTS.items():
            builder = self._builder(store.setting(setting, default))
            self.format_builders[action] = builder
            layout.addRow(label, builder)
        self.structure_builders = {}
        for action, (label, setting, default) in STRUCTURE_SHORTCUTS.items():
            builder = self._builder(store.setting(setting, default))
            self.structure_builders[action] = builder
            layout.addRow(label, builder)
        for item in HEADING_ITEMS:
            if item[5]:
                fixed = QLabel(item[5])
                fixed.setEnabled(False)
                fixed.setAccessibleName(f"{item[1]} 고정 단축키 {item[5]}")
                layout.addRow(f"{item[1]} (고정)", fixed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self._value_input_guard = install_value_input_guard(self)

    @staticmethod
    def _builder(text: str) -> HotkeyBuilder:
        builder = HotkeyBuilder()
        builder.setText(text)
        return builder

    def _save(self) -> None:
        raw = [self.always_top.text(), self.postit.text()]
        raw.extend(builder.text() for builder in self.format_builders.values())
        raw.extend(builder.text() for builder in self.structure_builders.values())
        raw.extend(shortcut_text(self.modifier.currentText(), key) for key, _label, _minutes in TIME_SHORTCUTS)
        try:
            normalized = [parse_hotkey(text).text for text in raw]
        except ValueError as exc:
            QMessageBox.warning(self, "단축키 설정", str(exc))
            return
        if len(normalized) != len(set(normalized)):
            QMessageBox.warning(self, "단축키 설정", "서로 중복되는 단축키가 있습니다.")
            return
        reserved = {
            parse_hotkey(value).text for value in (
                "Ctrl+Enter", "Ctrl+Shift+E", "Ctrl+S", "Ctrl+F",
                "Ctrl+V", "Ctrl+Shift+V", "Alt+Up", "Alt+Down",
                *(item[5] for item in HEADING_ITEMS if item[5]),
            )
        }
        if any(value in reserved for value in normalized):
            QMessageBox.warning(self, "단축키 설정", "편집·알림 기본 단축키와 겹칩니다.")
            return
        self.store.set_setting(SETTING_MODIFIER, self.modifier.currentText())
        self.store.set_setting(LAYOUT_SETTING, str(self.layout_mode.currentData()))
        self.store.set_setting(
            NEW_NOTE_FOCUS_SETTING, "true" if self.new_note_focus.isChecked() else "false"
        )
        self.store.set_setting(SETTING_ALWAYS_TOP, self.always_top.text())
        self.store.set_setting(SETTING_POSTIT, self.postit.text())
        for action, builder in self.format_builders.items():
            self.store.set_setting(FORMAT_SHORTCUTS[action][1], builder.text())
        for action, builder in self.structure_builders.items():
            self.store.set_setting(STRUCTURE_SHORTCUTS[action][1], builder.text())
        QMessageBox.information(self, "설정 저장", "설정이 저장되었습니다.")
        self.accept()
