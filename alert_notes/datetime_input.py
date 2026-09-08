from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import QDate, QTime, QEvent, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication, QDateEdit, QHBoxLayout, QLabel, QPushButton, QTimeEdit, QVBoxLayout, QWidget

from ui_polish import apply_numeric_font, polish_button, refresh_property
from .compact_datetime import parse_compact_date, parse_compact_time


def _qdate(text: str) -> QDate:
    value = parse_compact_date(text)
    return QDate(value.year, value.month, value.day) if value else QDate()


def _qtime(text: str) -> QTime:
    value = parse_compact_time(text)
    return QTime(value.hour, value.minute) if value else QTime()


class _WheelGuard:
    def wheelEvent(self, event):
        if self.hasFocus() or self.lineEdit().hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class CompactDateEdit(_WheelGuard, QDateEdit):
    value_invalid = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")
        # A shortcut nobody is told about may as well not exist.
        self.setToolTip(
            "20260910 · 2026-09-11 처럼 입력하거나 붙여넣을 수 있습니다.\n"
            "Ctrl+1 오늘 · Ctrl+2 내일 · Ctrl+3 다음 주"
        )
        self.setKeyboardTracking(False)
        self.setMinimumHeight(32)
        apply_numeric_font(self)
        self.lineEdit().setValidator(None)
        self.lineEdit().installEventFilter(self)
        self._snapshot = self.date()
        self.lineEdit().editingFinished.connect(self._parse)

    # Typing a full date is the slow path for the dates people pick most.  These
    # cost nothing to add and cover the common cases without a language parser.
    DATE_PRESETS = {
        Qt.Key.Key_1: ("오늘", 0),
        Qt.Key.Key_2: ("내일", 1),
        Qt.Key.Key_3: ("다음 주", 7),
    }

    def _apply_preset(self, key) -> bool:
        preset = self.DATE_PRESETS.get(key)
        if preset is None:
            return False
        self.setDate(QDate.currentDate().addDays(preset[1]))
        self.lineEdit().selectAll()
        return True

    def keyPressEvent(self, event) -> None:
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if self._apply_preset(event.key()):
                return
        if event.matches(QKeySequence.StandardKey.Paste):
            self._set_text_value(QApplication.clipboard().text().strip())
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._parse()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._restore_snapshot()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.lineEdit():
            if event.type() == QEvent.Type.FocusIn:
                self._snapshot = self.date()
            elif event.type() == QEvent.Type.MouseButtonPress:
                # Let QDateEdit place the cursor first, then select the complete
                # value so typing can replace the date in one pass.
                QTimer.singleShot(0, self.lineEdit().selectAll)
            elif event.type() == QEvent.Type.KeyPress:
                if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    if self._apply_preset(event.key()):
                        return True
                if event.matches(QKeySequence.StandardKey.Paste):
                    self._set_text_value(QApplication.clipboard().text().strip())
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._parse()
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    self._restore_snapshot()
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                self._parse()
        return super().eventFilter(watched, event)

    def _set_text_value(self, text: str) -> bool:
        value = _qdate(text)
        valid = value.isValid()
        refresh_property(self, "invalid", not valid)
        self.value_invalid.emit(not valid)
        if valid:
            self.setDate(value)
            self.lineEdit().selectAll()
        else:
            self.lineEdit().setText(text)
        return valid

    def _restore_snapshot(self) -> None:
        self.setDate(self._snapshot)
        refresh_property(self, "invalid", False)
        self.value_invalid.emit(False)

    def _parse(self) -> bool:
        return self._set_text_value(self.lineEdit().text().strip())


class CompactTimeEdit(_WheelGuard, QTimeEdit):
    value_invalid = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat("HH:mm")
        self.setKeyboardTracking(False)
        self.setMinimumHeight(32)
        apply_numeric_font(self)
        self.lineEdit().setValidator(None)
        self.lineEdit().installEventFilter(self)
        self._snapshot = self.time()
        self.lineEdit().editingFinished.connect(self._parse)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            self._set_text_value(QApplication.clipboard().text().strip())
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._parse()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._restore_snapshot()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.lineEdit():
            if event.type() == QEvent.Type.FocusIn:
                self._snapshot = self.time()
            elif event.type() == QEvent.Type.KeyPress:
                if event.matches(QKeySequence.StandardKey.Paste):
                    self._set_text_value(QApplication.clipboard().text().strip())
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._parse()
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    self._restore_snapshot()
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                self._parse()
        return super().eventFilter(watched, event)

    def _set_text_value(self, text: str) -> bool:
        value = _qtime(text)
        valid = value.isValid()
        refresh_property(self, "invalid", not valid)
        self.value_invalid.emit(not valid)
        if valid:
            self.setTime(value)
            self.lineEdit().selectAll()
        else:
            self.lineEdit().setText(text)
        return valid

    def _restore_snapshot(self) -> None:
        self.setTime(self._snapshot)
        refresh_property(self, "invalid", False)
        self.value_invalid.emit(False)

    def stepBy(self, steps: int) -> None:
        """Keep the visible time arrows on one predictable ten-minute step."""
        self.setTime(self.time().addSecs(int(steps) * 600))

    @staticmethod
    def _time_from_digits(text: str) -> QTime:
        return _qtime(text)

    def _parse(self) -> bool:
        return self._set_text_value(self.lineEdit().text().strip())


class DateTimeInput(QWidget):
    changed = pyqtSignal()
    commit_requested = pyqtSignal()

    def __init__(self, parent=None, *, show_quick=True, show_hint=True, show_summary=True):
        super().__init__(parent)
        self._building = False
        self._snapshot: datetime | None = None
        self._build_ui(show_quick=show_quick, show_hint=show_hint, show_summary=show_summary)
        self.set_datetime(datetime.now() + timedelta(minutes=10))

    def _build_ui(self, *, show_quick: bool, show_hint: bool, show_summary: bool) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        fields = QHBoxLayout()
        fields.setSpacing(6)
        fields.addWidget(QLabel("날짜"))
        self.date_edit = CompactDateEdit()
        self.date_edit.setAccessibleName("알림 날짜")
        self.date_edit.lineEdit().installEventFilter(self)
        fields.addWidget(self.date_edit, 3)
        fields.addWidget(QLabel("시간"))
        self.time_edit = CompactTimeEdit()
        self.time_edit.setAccessibleName("알림 시간")
        self.time_edit.lineEdit().installEventFilter(self)
        fields.addWidget(self.time_edit, 2)
        root.addLayout(fields)
        self.quick_buttons = []
        if show_quick:
            quick = QHBoxLayout()
            quick.setSpacing(5)
            for label, minutes in (("오늘", None), ("내일", "tomorrow"), ("+10분", 10), ("+30분", 30), ("+1시간", 60)):
                button = QPushButton(label)
                button.setMinimumHeight(30)
                polish_button(button)
                button.clicked.connect(lambda _checked=False, value=minutes: self._quick(value))
                quick.addWidget(button)
                self.quick_buttons.append(button)
            root.addLayout(quick)
        self.hint = QLabel("숫자만 입력: 20260804 · 930", self)
        self.hint.setObjectName("secondaryText")
        if show_hint:
            root.addWidget(self.hint)
        else:
            self.hint.hide()
        self.summary = QLabel(self)
        self.summary.setObjectName("reminderSummary")
        if show_summary:
            root.addWidget(self.summary)
        else:
            self.summary.hide()
        self.date_edit.dateChanged.connect(self._changed)
        self.time_edit.timeChanged.connect(self._changed)
        self.date_edit.value_invalid.connect(self._changed)
        self.time_edit.value_invalid.connect(self._changed)

    def _changed(self, *_args) -> None:
        if not self._building:
            invalid_or_past = not self.is_valid() or self.datetime() <= datetime.now()
            refresh_property(self.summary, "invalid", invalid_or_past)
            self.summary.setText(self.summary_text())
            self.changed.emit()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.date_edit._parse()
                self.time_edit._parse()
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier and self.is_valid():
                    self.commit_requested.emit()
                return True
            if event.key() == Qt.Key.Key_Escape and self._snapshot is not None:
                self.set_datetime(self._snapshot)
                return True
        return super().eventFilter(watched, event)

    def _quick(self, value) -> None:
        current = self.datetime()
        if current <= datetime.now():
            current = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=10)
        if value == "tomorrow":
            current = current + timedelta(days=1)
        elif value is None:
            current = current.replace(year=datetime.now().year, month=datetime.now().month, day=datetime.now().day)
        else:
            current += timedelta(minutes=int(value))
        self.set_datetime(current)

    def set_datetime(self, value: datetime) -> None:
        self._building = True
        self.date_edit.setDate(QDate(value.year, value.month, value.day))
        self.time_edit.setTime(QTime(value.hour, value.minute))
        self._building = False
        self._snapshot = value
        self._changed()

    def datetime(self) -> datetime:
        return datetime(
            self.date_edit.date().year(), self.date_edit.date().month(), self.date_edit.date().day(),
            self.time_edit.time().hour(), self.time_edit.time().minute(),
        )

    def is_valid(self) -> bool:
        return not bool(self.date_edit.property("invalid") or self.time_edit.property("invalid"))

    def set_scheduled(self, scheduled) -> None:
        """Say whether this value is already booked or only typed in.

        Collapsed, the summary read like a live reservation even when nothing
        was saved, which contradicted the "예약된 알림이 없습니다" panel.
        """
        self._scheduled = None if scheduled is None else bool(scheduled)
        self.summary.setText(self.summary_text())

    def summary_text(self) -> str:
        if not self.is_valid():
            return "날짜 또는 시간이 올바르지 않습니다."
        value = self.datetime()
        if value <= datetime.now():
            return "현재보다 이후 시간을 선택하세요"
        minutes = max(1, int((value - datetime.now()).total_seconds() // 60))
        if minutes < 60:
            remaining = f"{minutes}분 후"
        else:
            hours, rest = divmod(minutes, 60)
            remaining = f"{hours}시간" + (f" {rest}분" if rest else "") + " 후"
        today = datetime.now().date()
        if value.date() == today:
            stamp = f"오늘 {value:%H:%M}"
        elif value.date() == today + timedelta(days=1):
            stamp = f"내일 {value:%H:%M}"
        else:
            weekdays = "월화수목금토일"
            stamp = value.strftime("%Y년 %m월 %d일") + f"({weekdays[value.weekday()]}) {value:%H:%M}"
        state = getattr(self, "_scheduled", None)
        if state is None:
            # Standalone pickers already sit under an explicit 예약 button, so
            # only the collapsed memo row opts into the booked/typed wording.
            return f"{stamp} · {remaining}"
        return f"{stamp} 예약됨 · {remaining}" if state else f"예약하면 {stamp} · {remaining}"
