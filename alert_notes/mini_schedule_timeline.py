"""Read-only day context and draft selection, sharing the calendar's time axis."""
from datetime import datetime, time, timedelta

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import QGraphicsRectItem, QLabel, QVBoxLayout, QWidget

from .calendar_canvas import CalendarCanvas
from .sqlite_store import DATETIME_FMT


class MiniScheduleTimeline(QWidget):
    rangeSelected = pyqtSignal(datetime, datetime)
    rangePreview = pyqtSignal(datetime, datetime)
    selectionStarted = pyqtSignal()
    selectionCanceled = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._day = None
        self._draft = None
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(3)
        self.caption = QLabel("드래그로 시간 선택", self)
        self.caption.setToolTip("15분 단위 · Alt: 1분 · Esc: 선택 취소\n옅은 일정은 읽기 전용이며 겹쳐서 선택할 수 있습니다.")
        layout.addWidget(self.caption)
        self.canvas = CalendarCanvas(self)
        self.canvas.selection_only = True
        self.canvas.set_working_hours(True)
        self.canvas.header.hide()
        self.canvas._scrolled_once = True
        layout.addWidget(self.canvas, 1)
        self.canvas.rangeSelected.connect(self.rangeSelected)
        self.canvas.rangePreview.connect(self.rangePreview)
        self.canvas.selectionStarted.connect(self.selectionStarted)
        self.canvas.selectionCanceled.connect(self.selectionCanceled)
        self.overlay = QGraphicsRectItem()
        self.overlay.setPen(QPen(QColor("#4263EB"), 1.5))
        self.overlay.setBrush(QColor(66, 99, 235, 35))
        self.overlay.setZValue(20)
        self.overlay.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.canvas.view.scene().addItem(self.overlay)
        self.canvas.layoutChanged.connect(self._place_draft)

    def set_draft(self, start, end, *, point=False, all_day=False, refresh=False):
        changed_day = start.date() != self._day
        changed_range = self._draft is None or self._draft[:2] != (start, end)
        if changed_day or refresh:
            self._day = start.date()
            midnight = datetime.combine(self._day, time.min)
            try:
                items = self.store.schedules.items_for_range(midnight.strftime(DATETIME_FMT), (midnight + timedelta(days=1)).strftime(DATETIME_FMT))
                self.caption.setText("드래그로 시간 선택")
            except Exception:
                # A context-read failure must not discard or block the draft.
                items = []
                self.caption.setText("기존 일정 조회 실패")
            self.canvas.render_range(self._day, self._day + timedelta(days=1), items)
            for button in self.canvas._all_day_buttons:
                button.setEnabled(False)
        self._draft = start, end, point, all_day
        self._place_draft()
        if changed_day or (changed_range and self.canvas.view._band_origin is None):
            self.center_draft()

    def _place_draft(self):
        if self._draft is None:
            return
        start, end, point, all_day = self._draft
        minute = start.hour * 60 + start.minute
        top = self.canvas.minute_to_y(minute)
        end_minute = min(1440, minute + (end - start).total_seconds() / 60)
        height = 3 if point else max(3, self.canvas.minute_to_y(end_minute) - top)
        self.overlay.setRect(QRectF(self.canvas.column_left(0) + 2, top, self.canvas.column_width() - 4, height))
        self.overlay.setVisible(not all_day)
        self.overlay.setToolTip(f"작성 중 · {start:%H:%M}–{end:%H:%M}")

    def center_draft(self):
        if self._draft is not None:
            self.canvas.view.centerOn(self.overlay.rect().center())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_draft()

    def showEvent(self, event):
        super().showEvent(event)
        self.center_draft()
