from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QMessageBox

from hotkey_builder import HotkeyBuilder
from hotkey_parser import parse_hotkey

from .note_shortcuts import (
    DEFAULT_MODIFIER, FORMAT_SHORTCUTS, SETTING_MODIFIER, TIME_SHORTCUTS, VALID_MODIFIERS,
    shortcut_text,
)


SETTING_ALWAYS_TOP = "hotkey_always_on_top"
SETTING_POSTIT = "hotkey_simple_mode"
DEFAULT_ALWAYS_TOP = "Ctrl+Alt+Num0"
DEFAULT_POSTIT = "Ctrl+H"


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
        self.always_top = self._builder(store.setting(SETTING_ALWAYS_TOP, DEFAULT_ALWAYS_TOP))
        self.postit = self._builder(store.setting(SETTING_POSTIT, DEFAULT_POSTIT))
        layout.addRow("항상 위", self.always_top)
        layout.addRow("포스트잇 모드", self.postit)
        self.format_builders = {}
        for action, (label, setting, default) in FORMAT_SHORTCUTS.items():
            builder = self._builder(store.setting(setting, default))
            self.format_builders[action] = builder
            layout.addRow(label, builder)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @staticmethod
    def _builder(text: str) -> HotkeyBuilder:
        builder = HotkeyBuilder()
        builder.setText(text)
        return builder

    def _save(self) -> None:
        raw = [self.always_top.text(), self.postit.text()]
        raw.extend(builder.text() for builder in self.format_builders.values())
        raw.extend(shortcut_text(self.modifier.currentText(), key) for key, _label, _minutes in TIME_SHORTCUTS)
        try:
            normalized = [parse_hotkey(text).text for text in raw]
        except ValueError as exc:
            QMessageBox.warning(self, "단축키 설정", str(exc))
            return
        if len(normalized) != len(set(normalized)):
            QMessageBox.warning(self, "단축키 설정", "서로 중복되는 단축키가 있습니다.")
            return
        self.store.set_setting(SETTING_MODIFIER, self.modifier.currentText())
        self.store.set_setting(SETTING_ALWAYS_TOP, self.always_top.text())
        self.store.set_setting(SETTING_POSTIT, self.postit.text())
        for action, builder in self.format_builders.items():
            self.store.set_setting(FORMAT_SHORTCUTS[action][1], builder.text())
        QMessageBox.information(self, "설정 저장", "설정이 저장되었습니다.")
        self.accept()
