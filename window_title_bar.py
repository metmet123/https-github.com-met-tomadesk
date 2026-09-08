from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class WindowTitleBar(QFrame):
    """Frameless-window title bar with native-feeling move/maximize behavior."""

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self.setObjectName("customTitleBar")
        self.setFixedHeight(34)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)
        icon = QLabel()
        icon.setObjectName("titleBarIcon")
        icon.setPixmap(window.windowIcon().pixmap(QSize(18, 18)))
        layout.addWidget(icon)
        title = QLabel(window.windowTitle())
        title.setObjectName("titleBarText")
        layout.addWidget(title)
        layout.addStretch()
        self.hide_button = self._add_button(layout, "↓", "트레이로 숨기기")
        self.minimize_button = self._add_button(layout, "—", "최소화")
        self.maximize_button = self._add_button(layout, "□", "최대화 또는 이전 크기로 복원")
        self.close_button = self._add_button(layout, "×", "프로그램 종료", destructive=True)
        self.hide_button.clicked.connect(window.hide_to_tray)
        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button.clicked.connect(window.toggle_maximized)
        self.close_button.clicked.connect(window.exit_application)

    def _add_button(self, layout, text: str, tooltip: str = "", destructive: bool = False) -> QPushButton:
        button = QPushButton(text, self)
        button.setObjectName("closeWindowButton" if destructive else "windowControlButton")
        button.setFixedSize(46, 34)
        if tooltip:
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
        layout.addWidget(button)
        return button

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._window.isMaximized():
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
