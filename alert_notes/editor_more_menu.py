"""Searchable editor commands; the popup stays within the document area."""

from dataclasses import dataclass
from collections.abc import Callable

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QToolButton, QVBoxLayout, QWidget,
)


@dataclass
class EditorCommand:
    key: str
    group: str
    label: str
    callback: Callable
    enabled: Callable = lambda: True


class EditorMoreMenu(QFrame):
    pins_changed = pyqtSignal(list)

    def __init__(self, editor, commands, pins=()):
        super().__init__(editor, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.editor = editor
        self.commands = commands
        self.pins = [key for key in pins if isinstance(key, str) and key in {c.key for c in commands}]
        self.setObjectName("editorMoreMenu")
        self.setAccessibleName("메모 더보기")
        self.setStyleSheet(
            "QFrame#editorMoreMenu{background:#ffffff;border:1px solid #cbd5e1;border-radius:8px;}"
            "QPushButton{border:0;text-align:left;padding:4px;color:#334155;background:transparent;}"
            "QPushButton:hover{background:#eff6ff;}"
            "QPushButton:disabled{color:#94a3b8;}"
            "QToolButton{padding:0;border:0;border-radius:4px;}"
            "QToolButton:checked{background:#dbeafe;color:#1d4ed8;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("기능 찾기")
        self.search.setAccessibleName("더보기 기능 검색")
        root.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)
        body = QWidget()
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(2)
        self.headers = {}
        self.rows = {}
        self.action_buttons = {}
        self.pin_buttons = {}
        for command in commands:
            if command.group not in self.headers:
                label = QLabel(command.group)
                label.setStyleSheet("color:#64748b;font-weight:600;padding-top:5px;")
                rows.addWidget(label)
                self.headers[command.group] = label
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)
            button = QPushButton(command.label)
            button.setMinimumHeight(28)
            button.setAccessibleName(command.label)
            button.clicked.connect(lambda _=False, c=command: self.run(c))
            layout.addWidget(button, 1)
            pin = QToolButton()
            pin.setText("☆")
            pin.setFixedSize(26, 26)
            pin.setCheckable(True)
            pin.setChecked(command.key in self.pins)
            pin.toggled.connect(lambda checked, c=command: self.set_pinned(c.key, checked))
            layout.addWidget(pin)
            self.rows[command.key] = row
            self.action_buttons[command.key] = button
            self.pin_buttons[command.key] = pin
            self._sync_pin(command)
            rows.addWidget(row)
        self.empty = QLabel("일치하는 기능이 없습니다")
        rows.addWidget(self.empty)
        rows.addStretch(1)
        self.scroll.setWidget(body)
        hint = QLabel("☆ 도구 모음에 고정 · Esc 닫기")
        hint.setStyleSheet("color:#64748b;font-size:11px;")
        root.addWidget(hint)
        self.search.textChanged.connect(self.filter)
        self.search.returnPressed.connect(self.run_first)
        self.escape = QShortcut(QKeySequence("Esc"), self)
        self.escape.activated.connect(self.close)
        self._anchor = None
        self.filter("")

    def _sync_pin(self, command):
        pin = self.pin_buttons[command.key]
        pinned = command.key in self.pins
        pin.setText("★" if pinned else "☆")
        label = f"{command.label} 고정 {'해제' if pinned else '하기'}"
        pin.setAccessibleName(label)
        pin.setToolTip(label)

    def set_pinned(self, key, checked):
        if checked and key not in self.pins:
            self.pins.append(key)
        elif not checked and key in self.pins:
            self.pins.remove(key)
        for command in self.commands:
            self._sync_pin(command)
        self.pins_changed.emit(list(self.pins))

    def filter(self, text):
        query = text.strip().casefold()
        groups = set()
        for command in self.commands:
            visible = query in f"{command.group} {command.label}".casefold()
            self.rows[command.key].setVisible(visible)
            self.action_buttons[command.key].setEnabled(bool(command.enabled()))
            if visible:
                groups.add(command.group)
        for group, header in self.headers.items():
            header.setVisible(group in groups)
        self.empty.setVisible(not groups)

    def run_first(self):
        for command in self.commands:
            if not self.rows[command.key].isHidden() and command.enabled():
                self.run(command)
                break

    def run(self, command):
        if not command.enabled():
            return
        self.close()
        self.editor.content_edit.setFocus()
        QTimer.singleShot(0, command.callback)

    def open_at(self, anchor):
        if self.isVisible():
            self.close()
            return
        self._anchor = anchor
        self.search.clear()
        self.filter("")
        # Both the outline and the outer summary are outside these bounds.
        bounds = self.editor.content_edit.rect()
        top = self.editor.content_edit.mapToGlobal(bounds.topLeft())
        width = min(340, bounds.width())
        height = min(530, bounds.height())
        self.setFixedSize(width, height)
        self.move(top + QPoint(max(0, bounds.width() - width), 0))
        self.show()
        self.search.setFocus()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._anchor is not None:
            self._anchor.setFocus()


class PinnedCommandBar(QWidget):
    """One bounded row; overflow remains accessible in the same More menu."""

    def __init__(self, commands, run, parent=None):
        super().__init__(parent)
        self.commands = {c.key: c for c in commands}
        self.run = run
        self.buttons = []
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.setMinimumWidth(0)
        self.overflow = QLabel("나머지는 더보기에서")
        self.overflow.setStyleSheet("color:#64748b;")
        self.row.addWidget(self.overflow)
        self.row.addStretch(1)
        self.hide()

    def minimumSizeHint(self):
        return QSize(0, 28)

    def set_pins(self, pins):
        for button in self.buttons:
            self.row.removeWidget(button)
            button.deleteLater()
        self.buttons = []
        for key in pins:
            if key not in self.commands:
                continue
            command = self.commands[key]
            button = QToolButton()
            button.setText(command.label)
            button.setToolTip(command.label)
            button.setFixedHeight(28)
            button.clicked.connect(lambda _=False, c=command: self.run(c))
            self.row.insertWidget(len(self.buttons), button)
            self.buttons.append(button)
        self.setVisible(bool(self.buttons))
        self.fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def fit(self):
        widths = [b.sizeHint().width() + 4 for b in self.buttons]
        overflow = sum(widths) > self.width()
        remaining = self.width() - (self.overflow.sizeHint().width() + 4 if overflow else 0)
        exhausted = False
        for button, width in zip(self.buttons, widths):
            exhausted = exhausted or width > remaining
            button.setVisible(not exhausted)
            if not exhausted:
                remaining -= width
        self.overflow.setVisible(overflow)
