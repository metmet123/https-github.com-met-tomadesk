from PyQt6.QtCore import QByteArray, QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication


class WindowGeometryController(QObject):
    """Persist a Qt window geometry through a string setting interface."""

    def __init__(self, window, load_value, save_value, key: str, delay_ms: int = 400):
        super().__init__(window)
        self.window = window
        self.load_value = load_value
        self.save_value = save_value
        self.key = key
        self.restoring = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(delay_ms)
        self.timer.timeout.connect(self.save)
        window.installEventFilter(self)

    def restore(self) -> None:
        self.restoring = True
        value = self.load_value(self.key, "")
        if value:
            try:
                self.window.restoreGeometry(QByteArray.fromBase64(value.encode("ascii")))
            except (ValueError, UnicodeError):
                pass
        self.ensure_visible()
        self.restoring = False

    def eventFilter(self, watched, event) -> bool:
        if watched is self.window and event.type() in {QEvent.Type.Move, QEvent.Type.Resize} and not self.restoring:
            self.timer.start()
        return super().eventFilter(watched, event)

    def save(self) -> None:
        if self.restoring:
            return
        encoded = bytes(self.window.saveGeometry().toBase64()).decode("ascii")
        self.save_value(self.key, encoded)

    def ensure_visible(self) -> None:
        frame = self.window.frameGeometry()
        if any(frame.intersects(screen.availableGeometry()) for screen in QApplication.screens()):
            return
        screen = self.window.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.window.move(
            area.x() + max(0, (area.width() - self.window.width()) // 2),
            area.y() + max(0, (area.height() - self.window.height()) // 2),
        )
