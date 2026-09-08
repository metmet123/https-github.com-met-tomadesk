from PyQt6.QtWidgets import QDialog, QVBoxLayout

from .calendar import CalendarPanel


class CalendarDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("알림 캘린더")
        self.resize(1280, 760)
        self.calendar = CalendarPanel(store)
        self.calendar.fullscreen_button.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.calendar)
