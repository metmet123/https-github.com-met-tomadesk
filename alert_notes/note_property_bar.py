"""Compact, keyboard-accessible memo properties without covering the document."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QMenu, QToolButton, QVBoxLayout, QWidget


class PropertyChipBar(QWidget):
    page_changed = pyqtSignal(str)
    ORDER = ("format", "reminder", "deadline", "hotkey", "other")
    LABELS = {
        "reminder": "🔔\u2009알림", "deadline": "📌\u2009D-Day", "hotkey": "⌨\u2009단축키",
        "format": "서식 ▾", "other": "⋯",
    }
    # 값이 들어가도 좁은 폭에서 이름으로 돌아가지 않는 칩.
    ALWAYS_SUMMARY = ("format", "deadline")
    CHIP_STYLE = (
        "QToolButton#memoPropertyChip{border:1px solid #cbd5e1;border-radius:7px;"
        "background:#f8fafc;color:#334155;padding:0 6px;margin:0;"
        "min-width:0px;min-height:26px;max-height:26px;}"
        "QToolButton#memoPropertyChip:checked{background:#dbeafe;border-color:#60a5fa;color:#1d4ed8;}"
        "QToolButton#memoPropertyChip:focus{border:2px solid #2563eb;}"
        'QToolButton#memoPropertyChip[deadlineState="soon"]{background:#fff7e6;border-color:#e3bb72;color:#8a5a00;font-weight:600;}'
        'QToolButton#memoPropertyChip[deadlineState="today"],'
        'QToolButton#memoPropertyChip[deadlineState="past"]{background:#fff5f5;border-color:#fca5a5;color:#b91c1c;font-weight:600;}'
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("memoPropertyChipBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self._narrow = False
        self._summaries = {}
        self.buttons = {}
        for name in self.ORDER:
            button = QToolButton(self)
            button.setObjectName("memoPropertyChip")
            # 칩마다 직접 건다.  편집기 전체 규칙(좌우 9px)보다 항상 우선한다.
            button.setStyleSheet(self.CHIP_STYLE)
            button.setText(self.LABELS[name])
            button.setAccessibleName(f"{self.LABELS[name]} 설정 열기")
            button.setCheckable(True)
            button.setAutoRaise(False)
            button.setFixedHeight(28)
            button.clicked.connect(lambda _checked=False, key=name: self.page_changed.emit(key))
            row.addWidget(button)
            self.buttons[name] = button
            if name == "format":
                self.format_separator = QFrame(self)
                self.format_separator.setObjectName("memoChipSeparator")
                self.format_separator.setFrameShape(QFrame.Shape.NoFrame)
                self.format_separator.setFixedSize(1, 16)
                self.format_separator.setStyleSheet(
                    "QFrame#memoChipSeparator{border:0;background:#dbe2ea;}"
                )
                row.addWidget(self.format_separator)
        self.buttons["other"].setFixedWidth(26)
        row.addStretch(1)
        # Compatibility alias for existing callers/tests; the visible ⋯ button
        # is now the real final property entry rather than a narrow-only clone.
        self.more_button = self.buttons["other"]

    def set_active(self, name: str | None) -> None:
        for key, button in self.buttons.items():
            button.setChecked(key == name)

    def set_narrow(self, narrow: bool) -> None:
        self._narrow = bool(narrow)
        for key, button in self.buttons.items():
            summary = self._summaries.get(key, (self.LABELS[key], False))[0]
            button.setText(summary if key in self.ALWAYS_SUMMARY else self.LABELS[key] if self._narrow else summary)
            button.show()
        self._fit_button_widths()

    def _fit_button_widths(self) -> None:
        # QToolButton's native sizeHint reserves substantially more horizontal
        # space than this text-only chip paints.  Keep the narrow row within its
        # width budget while allowing the label, 6px padding and border to fit.
        for key, button in self.buttons.items():
            if key == "other":
                button.setFixedWidth(max(26, button.fontMetrics().horizontalAdvance(button.text()) + 14))
                continue
            if self._narrow:
                button.setFixedWidth(button.fontMetrics().horizontalAdvance(button.text()) + 14)
            else:
                button.setMinimumWidth(0)
                button.setMaximumWidth(16777215)

    def set_deadline_state(self, state: str, tooltip: str = "") -> None:
        """past/today/soon 이면 칩 색으로 급한 정도를 보여 준다."""
        button = self.buttons["deadline"]
        button.setProperty("deadlineState", state or "normal")
        button.setToolTip(tooltip)
        button.style().unpolish(button)
        button.style().polish(button)

    def set_summary(self, name: str, text: str, active: bool = False) -> None:
        button = self.buttons[name]
        self._summaries[name] = (text, active)
        button.setText(text if name in self.ALWAYS_SUMMARY else self.LABELS[name] if self._narrow else text)
        button.setToolTip(text if text != self.LABELS[name] else "")
        button.setProperty("hasValue", active)
        button.setAccessibleName(
            ("서식 도구 접기" if active else "서식 도구 펼치기")
            if name == "format" else f"{text} 설정 열기"
        )
        button.style().unpolish(button)
        button.style().polish(button)
        self._fit_button_widths()


class PropertyPanel(QFrame):
    """In-flow child panel: opening it moves the document, never covers text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("memoPropertyPanel")
        self.setStyleSheet(
            "QFrame#memoPropertyPanel{background:#f8fafc;border:1px solid #cbd5e1;"
            "border-radius:8px;}"
        )
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 7, 8, 7)
        self._layout.setSpacing(0)
        self.pages = {}
        self.active_page = None
        self.hide()

    def add_page(self, name: str, widget: QWidget) -> None:
        self._layout.addWidget(widget)
        self.pages[name] = widget
        widget.hide()

    def open_page(self, name: str) -> None:
        for key, widget in self.pages.items():
            widget.setVisible(key == name)
        self.active_page = name
        self.show()

    def close_page(self) -> bool:
        if self.active_page is None:
            return False
        self.active_page = None
        self.hide()
        for widget in self.pages.values():
            widget.hide()
        return True
