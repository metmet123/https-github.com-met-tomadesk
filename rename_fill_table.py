"""Viewport fill handle. Dragging previews a range; only release emits a commit."""
from PyQt6.QtCore import Qt, QRect, QPoint, QTimer, pyqtSignal, QEvent
from PyQt6.QtGui import QPainter, QPen, QColor
from PyQt6.QtWidgets import QTableWidget, QAbstractItemView


class FillTable(QTableWidget):
    fillRequested = pyqtSignal(int, int, int, int, int)

    def __init__(self, rows, columns, allowed, parent=None):
        super().__init__(rows, columns, parent)
        self.allowed = allowed
        self._fill_area = None
        self._fill_target = -1
        self._pointer = QPoint()
        self.setMouseTracking(True)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(60)
        self._scroll_timer.timeout.connect(self._scroll_fill)
        self.itemSelectionChanged.connect(self.viewport().update)
        for signal in (self.model().dataChanged, self.model().rowsInserted,
                       self.model().rowsRemoved, self.model().columnsInserted,
                       self.model().columnsRemoved, self.model().modelReset):
            signal.connect(self._model_changed)

    def _seed_area(self):
        ranges = self.selectedRanges()
        if (not self.isEnabled() or not self.allowed() or len(ranges) != 1
                or self.state() == QAbstractItemView.State.EditingState):
            return None
        area = ranges[0]
        if not (1 <= area.leftColumn() <= area.rightColumn() <= self.columnCount() - 2):
            return None
        if any(self.isRowHidden(r) for r in range(self.rowCount())):
            return None
        return (area.topRow(), area.bottomRow(), area.leftColumn(), area.rightColumn())

    def handle_rect(self):
        area = self._fill_area or self._seed_area()
        if area is None:
            return QRect()
        rect = self.visualRect(self.model().index(area[1], area[3]))
        handle = QRect(rect.right() - 8, rect.bottom() - 8, 8, 8)
        return handle if self.viewport().rect().contains(handle) else QRect()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setClipRect(self.viewport().rect())
        if self._fill_area and self._fill_target > self._fill_area[1]:
            _, bottom, left, right = self._fill_area
            first = self.visualRect(self.model().index(bottom + 1, left))
            last = self.visualRect(self.model().index(self._fill_target, right))
            region = first.united(last).intersected(self.viewport().rect())
            painter.fillRect(region, QColor(37, 99, 235, 35))
            painter.setPen(QPen(QColor("#2563eb"), 2, Qt.PenStyle.DashLine))
            painter.drawRect(region.adjusted(1, 1, -1, -1))
        handle = self.handle_rect()
        if not handle.isEmpty():
            painter.fillRect(handle, QColor("#2563eb"))
            painter.setPen(QColor("white"))
            painter.drawRect(handle.adjusted(0, 0, -1, -1))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.handle_rect().contains(event.position().toPoint()):
            self.setFocus()
            self._fill_area = self._seed_area()
            self._fill_target = self._fill_area[1]
            self._pointer = event.position().toPoint()
            self._scroll_timer.start()
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def _update_target(self, point):
        self._pointer = point
        bounds = self.viewport().rect()
        # Outside the horizontal bounds cancels the proposed extension. At the
        # bottom edge keep tracking for autoscroll, but outside release cancels.
        if not bounds.left() <= point.x() <= bounds.right() or point.y() < 0:
            self._fill_target = self._fill_area[1]
        else:
            row = self.rowAt(min(point.y(), bounds.bottom()))
            if row < 0:
                row = self.rowCount() - 1
            self._fill_target = max(self._fill_area[1], row)
        self.viewport().update()

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        if self._fill_area:
            self._update_target(point)
            event.accept()
            return
        if self.handle_rect().contains(point):
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def _scroll_fill(self):
        if not self._fill_area:
            return
        bounds = self.viewport().rect()
        if not bounds.left() <= self._pointer.x() <= bounds.right():
            return
        bar = self.verticalScrollBar()
        if self._pointer.y() >= bounds.bottom() - 16:
            bar.setValue(bar.value() + bar.singleStep())
        elif self._pointer.y() <= 16:
            bar.setValue(bar.value() - bar.singleStep())
        self._update_target(self._pointer)

    def mouseReleaseEvent(self, event):
        if self._fill_area:
            self._update_target(event.position().toPoint())
            area, target = self._fill_area, self._fill_target
            commit = event.button() == Qt.MouseButton.LeftButton and self.viewport().rect().contains(event.position().toPoint())
            self.cancel_fill()
            if commit and target > area[1] and self.allowed():
                self.fillRequested.emit(*area, target)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def cancel_fill(self):
        self._fill_area = None
        self._fill_target = -1
        self._scroll_timer.stop()
        self.viewport().unsetCursor()
        self.viewport().update()

    def _model_changed(self, *_):
        if self._fill_area:
            self.cancel_fill()

    def keyPressEvent(self, event):
        if self._fill_area:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_fill()
            event.accept()  # Prevent editing/Undo while a drag is pending.
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self.cancel_fill()
        super().focusOutEvent(event)

    def hideEvent(self, event):
        self.cancel_fill()
        super().hideEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.cancel_fill()
        super().changeEvent(event)
