"""Prevent accidental wheel and drag changes on settings value controls."""

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractSlider, QAbstractSpinBox, QComboBox


class ValueInputGuard(QObject):
    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Wheel:
            event.accept()
            return True
        if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
            return True
        return super().eventFilter(watched, event)


def install_value_input_guard(root) -> ValueInputGuard:
    guard = ValueInputGuard(root)
    for control in root.findChildren((QComboBox, QAbstractSpinBox, QAbstractSlider)):
        control.installEventFilter(guard)
        if isinstance(control, QComboBox):
            control.view().viewport().installEventFilter(guard)
    return guard
