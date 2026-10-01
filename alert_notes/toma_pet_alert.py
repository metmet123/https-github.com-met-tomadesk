"""Toma pet alert bubble using the current Codex GPT pet runtime contract."""

from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QVBoxLayout,
)

from .deadline import countdown_text
from .note_shortcuts import TIME_SHORTCUTS, shortcut_text
from .rich_text import plain_text_from_content
from .schedule_popover import UNTITLED_SCHEDULE, SchedulePopover, StandaloneSchedulePopover
from .schedule_token_edit import ScheduleTokenLineEdit
from .toma_pet_assets import TomaSpriteAtlas
from .toma_pet_motion import TomaMotionPlayer
from .toma_pet_window import TomaSpriteLabel


def _row_value(row, key: str, default=""):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


class TomaSpeechBubble(QFrame):
    """Warm speech bubble with a painted tail directed at Toma."""

    def __init__(self, parent=None, *, external_pet: bool = False):
        super().__init__(parent)
        self.external_pet = external_pet
        self.setObjectName("tomaPetBubble")
        self.setAccessibleName("토마펫 알림 말풍선")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(26, 34, 58, 55))
        self.setGraphicsEffect(shadow)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tail = 22.0
        rect = QRectF(7, 7, max(1, self.width() - tail - 14), max(1, self.height() - 14))
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        join_y = rect.bottom() - (34 if self.external_pet else 44)
        path.moveTo(rect.right() - 2, join_y - 10)
        path.lineTo(self.width() - 5, join_y + 3)
        path.lineTo(rect.right() - 2, join_y + 12)
        path.closeSubpath()
        painter.setPen(QPen(QColor("#2f3555"), 1.3))
        painter.setBrush(QColor("#fff9f0"))
        painter.drawPath(path)
        super().paintEvent(event)


class TomaPetAlertDialog(QDialog):
    """Non-modal alert with one Toma pet and a two-row snooze grid."""

    completed = pyqtSignal(int)
    snoozed = pyqtSignal(int, int)
    skipped = pyqtSignal(int)
    note_open_requested = pyqtSignal(int)
    schedule_open_requested = pyqtSignal(int)
    quick_schedule_saved = pyqtSignal(int)

    def __init__(self, reminder, is_schedule: bool, parent=None, *, persistent_pet=None, modifier="Alt", store=None):
        super().__init__(parent)
        self.reminder = reminder
        self.store = store
        # 화면에 띄우지 않는 빠른 일정 창.  자연어 해석·기본 알림·저장을 그대로 빌려 쓴다.
        self._quick_engine: SchedulePopover | None = None
        self._quick_popover: StandaloneSchedulePopover | None = None
        self.is_schedule = bool(is_schedule)
        self.persistent_pet = persistent_pet
        self.modifier = modifier
        if self.is_schedule:
            self.notification_id = int(reminder["notification_id"])
            self.occurrence_at = str(reminder["occurrence_at"])
            self.item_id = int(reminder["item_id"])
            note_id = _row_value(reminder, "note_id")
            self.note_id = int(note_id) if note_id not in (None, "") else None
        else:
            self.reminder_id = int(reminder["id"])
            self.note_id = int(reminder["note_id"])
        self.pet = None
        self.motion = None
        self._drag_origin: QPoint | None = None
        self.quick_snooze_buttons: dict[int, QPushButton] = {}
        self._build_ui()
        if self.persistent_pet is not None:
            self.persistent_pet.play_alert_completion()
        else:
            self.motion.play("reviewing")

    def _build_ui(self) -> None:
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName("토마펫 알림")
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(4)
        self.bubble = TomaSpeechBubble(self, external_pet=self.persistent_pet is not None)
        self.bubble.setMaximumWidth(520)
        bubble_layout = QVBoxLayout(self.bubble)
        bubble_layout.setContentsMargins(18, 15, 34, 15)
        bubble_layout.setSpacing(8)
        alert_label = QLabel("알림")
        alert_label.setObjectName("tomaAlertEyebrow")
        bubble_layout.addWidget(alert_label)
        title_text = _row_value(self.reminder, "title") if self.is_schedule else _row_value(self.reminder, "note_title")
        title = QLabel(str(title_text or "알림"))
        title.setObjectName("tomaAlertTitle")
        title.setWordWrap(True)
        title.setAccessibleName("알림 제목")
        bubble_layout.addWidget(title)
        if not self.is_schedule and str(_row_value(self.reminder, "occurrence_kind") or "") == "deadline":
            deadline = QLabel(f"D-Day 알림 · {countdown_text(str(_row_value(self.reminder, 'due_at')))}")
            deadline.setObjectName("deadlineBadge")
            bubble_layout.addWidget(deadline, 0, Qt.AlignmentFlag.AlignLeft)
        detail = _row_value(self.reminder, "details") if self.is_schedule else plain_text_from_content(
            str(_row_value(self.reminder, "note_content") or _row_value(self.reminder, "memo"))
        )
        content = QLabel(str(detail or "등록한 알림 시간이 되었습니다."))
        content.setObjectName("tomaAlertContent")
        content.setWordWrap(True)
        content.setMaximumWidth(440)
        content.setAccessibleName("알림 내용")
        bubble_layout.addWidget(content)
        snooze_label = QLabel("빠른 재알림")
        snooze_label.setObjectName("tomaAlertSection")
        bubble_layout.addWidget(snooze_label)
        quick_grid = QGridLayout()
        quick_grid.setHorizontalSpacing(7)
        quick_grid.setVerticalSpacing(6)
        quick_grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
        for index, (key, label, minutes) in enumerate(TIME_SHORTCUTS):
            button = QPushButton(f"{label}\n{shortcut_text(self.modifier, key)}")
            button.setObjectName("tomaQuickSnoozeButton")
            button.setAccessibleName(f"{label} 후 다시 알림")
            button.setMinimumHeight(38)
            button.setMaximumHeight(38)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, value=minutes: self._snooze(value))
            row, column = (0, index) if index < 5 else (1, index - 5)
            quick_grid.addWidget(button, row, column)
            self.quick_snooze_buttons[minutes] = button
        bubble_layout.addLayout(quick_grid)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        done = QPushButton("확인")
        done.setObjectName("tomaAlertPrimaryButton")
        done.setAccessibleName("알림 확인")
        done.setFixedHeight(30)
        done.clicked.connect(self._complete)
        actions.addWidget(done, 1)
        edit_label = "일정편집" if self.is_schedule and self.note_id is None else "메모편집"
        edit = QPushButton(edit_label)
        edit.setObjectName("tomaAlertSecondaryButton")
        edit.setAccessibleName(edit_label)
        edit.setFixedHeight(30)
        edit.clicked.connect(self._open)
        actions.addWidget(edit)
        bubble_layout.addLayout(actions)
        if self.store is not None:
            self._build_quick_schedule(bubble_layout)
        root.addWidget(self.bubble)
        # 빠른 일정 칸에서 Enter를 누르면 ‘확인’이 함께 눌려 알림이 닫히지 않게 한다.
        for button in self.bubble.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        if self.persistent_pet is None:
            self.pet = TomaSpriteLabel(self)
            self.motion = TomaMotionPlayer(self.pet, TomaSpriteAtlas(), self)
            self.pet.action_requested.connect(self.play_action)
            self.pet.menu_requested.connect(self.pet._menu.exec)
            self.pet.drag_started.connect(self._start_drag)
            self.pet.dragged.connect(self._drag)
            self.pet.drag_finished.connect(self._finish_drag)
            self.finished.connect(lambda _result: self.motion.stop())
            root.addWidget(self.pet, 0, Qt.AlignmentFlag.AlignBottom)
        self.setStyleSheet(
            "QLabel#tomaAlertEyebrow { color: #d4462f; font-size: 12px; font-weight: 700; }"
            "QLabel#tomaAlertTitle { color: #19213f; font-size: 17px; font-weight: 700; }"
            "QLabel#tomaAlertContent { color: #303754; font-size: 13px; }"
            "QLabel#tomaAlertSection { color: #2f3555; font-size: 12px; font-weight: 700; }"
            "QLabel#deadlineBadge { color: white; background: #2f3555; border-radius: 7px; padding: 3px 7px; }"
            "QPushButton { border: 1px solid #c9cde0; border-radius: 8px; background: #fffdf8; color: #2f3555; padding: 4px 9px; }"
            "QPushButton:hover { background: #f2f4ff; border-color: #6671d9; }"
            "QPushButton:focus { border: 2px solid #4556d9; }"
            "QPushButton#tomaAlertPrimaryButton { background: #4556d9; border-color: #4556d9; color: white; font-weight: 700; }"
            "QPushButton#tomaAlertPrimaryButton:hover { background: #3545bd; }"
            "QPushButton#tomaQuickSnoozeButton { font-size: 11px; padding: 0px 7px; min-height: 36px; max-height: 36px; }"
            # 앱 공통 버튼 높이(배율에 따라 커짐)를 따르지 않고 글자 높이만큼만 쓴다.
            "QPushButton#tomaAlertPrimaryButton, QPushButton#tomaAlertSecondaryButton {"
            " padding: 0px 12px; min-height: 28px; max-height: 28px; }"
            "QLineEdit#tomaQuickScheduleInput { border: 1px solid #c9cde0; border-radius: 9px;"
            " background: #ffffff; color: #19213f; padding: 0px 9px; min-height: 28px; max-height: 28px; }"
            "QLineEdit#tomaQuickScheduleInput:focus { border: 2px solid #4556d9; }"
            "QPushButton#tomaQuickScheduleTime { background: #4263eb; border-color: #4263eb; color: white;"
            " font-weight: 700; border-radius: 9px; padding: 0px 10px; min-height: 28px; max-height: 28px; }"
            "QPushButton#tomaQuickScheduleTime:hover { background: #3451c7; }"
            "QLabel#tomaQuickScheduleDuration, QLabel#tomaQuickScheduleStatus { color: #5b6380; font-size: 11px; }"
        )

    # ------------------------------------------------------------ 빠른 일정 --
    def _build_quick_schedule(self, bubble_layout) -> None:
        heading = QLabel("빠른 일정")
        heading.setObjectName("tomaAlertSection")
        bubble_layout.addWidget(heading)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.quick_input = ScheduleTokenLineEdit()
        self.quick_input.setObjectName("tomaQuickScheduleInput")
        self.quick_input.setPlaceholderText("제목 추가 · 예: 내일 3시 회의")
        self.quick_input.setAccessibleName("빠른 일정 입력")
        self.quick_input.setFixedHeight(30)
        self.quick_input.setMinimumWidth(150)
        row.addWidget(self.quick_input, 1)
        self.quick_time_button = QPushButton()
        self.quick_time_button.setObjectName("tomaQuickScheduleTime")
        self.quick_time_button.setAccessibleName("빠른 일정 시간 · 자세히 편집")
        self.quick_time_button.setToolTip("누르면 빠른 일정 창에서 시간·알림·분류를 고칩니다.")
        self.quick_time_button.setFixedHeight(30)
        row.addWidget(self.quick_time_button)
        self.quick_duration_label = QLabel()
        self.quick_duration_label.setObjectName("tomaQuickScheduleDuration")
        row.addWidget(self.quick_duration_label)
        bubble_layout.addLayout(row)
        self.quick_status = QLabel()
        self.quick_status.setObjectName("tomaQuickScheduleStatus")
        self.quick_status.setWordWrap(True)
        self.quick_status.hide()
        bubble_layout.addWidget(self.quick_status)
        self._quick_engine = SchedulePopover(self.store)
        self._quick_engine.hide()
        self._quick_engine.saved.connect(self._quick_saved)
        self._reset_quick_engine()
        self.quick_input.textChanged.connect(self._quick_text_changed)
        # 빠른 일정 칸의 Enter는 저장만 하고 알림 창의 ‘확인’으로 넘기지 않는다.
        self.quick_input.installEventFilter(self)
        self.quick_input.token_double_clicked.connect(self._quick_cancel_token)
        self.quick_time_button.clicked.connect(self._open_quick_popover)
        self.finished.connect(lambda _result: self._close_quick_windows())

    def _reset_quick_engine(self) -> None:
        now = datetime.now().replace(second=0, microsecond=0)
        self._quick_engine.open_new(now, now + timedelta(hours=1), relative_base=now, time_given=False)
        self._quick_engine.hide()
        self._sync_quick_view()

    def _quick_text_changed(self, text: str) -> None:
        self._quick_engine.title_edit.setText(text)
        self.quick_status.hide()
        self._sync_quick_view()

    def _quick_cancel_token(self, start: int, end: int, kind: str) -> None:
        self._quick_engine._cancel_parsed_token(start, end, kind)
        self._sync_quick_view()

    def _sync_quick_view(self) -> None:
        engine = self._quick_engine
        parsed = engine._parsed
        self.quick_input.set_token_spans(parsed.spans if parsed is not None else ())
        summary = engine.time_summary_button.text().replace("▾", "").replace("▴", "").strip()
        self.quick_time_button.setText(f"{summary} ▾")
        self.quick_duration_label.setText(engine.duration_label.text())
        tooltip = engine.title_edit.toolTip()
        self.quick_input.setToolTip(tooltip or "날짜·시간·알림을 적으면 함께 읽습니다. Enter로 저장합니다.")

    def _quick_message(self, text: str) -> None:
        self.quick_status.setText(text)
        self.quick_status.show()

    def save_quick_schedule(self) -> int | None:
        """입력한 한 줄을 빠른 일정 창과 같은 규칙으로 저장한다.  알림 창은 닫지 않는다."""
        engine = self._quick_engine
        if engine is None:
            return None
        parsed = engine._parsed
        if parsed is not None and parsed.issues:
            self._quick_message(" · ".join(parsed.issues))
            return None
        title = engine.parsed_title().strip()
        start = engine._start
        if not title:
            # 시간만 적으면 ‘제목없음’ 일정으로 그 시각에 알린다.
            kinds = {span.kind for span in parsed.spans} if parsed is not None else set()
            if not kinds & {"date", "time"}:
                self._quick_message("일정 제목이나 시간을 입력해 주세요.")
                return None
            title = UNTITLED_SCHEDULE
            values = engine.values()
            values["title"] = title
            if not values["reminders"] and not values["all_day"]:
                values["reminders"] = [0]
            try:
                item_id = self.store.schedules.save_item(values)
            except Exception as exc:
                self._quick_message(f"일정을 저장하지 못했습니다. {exc}")
                return None
            self.quick_schedule_saved.emit(int(item_id))
        else:
            if not engine.save():
                self._quick_message("일정을 저장하지 못했습니다. 시간을 눌러 자세히 확인해 주세요.")
                return None
            item_id = engine.item_id
        self.quick_input.blockSignals(True)
        self.quick_input.clear()
        self.quick_input.blockSignals(False)
        self._reset_quick_engine()
        self._quick_message(f"저장했습니다 · {title} · {start:%m/%d %H:%M}")
        return item_id

    def _quick_saved(self, item_id: int) -> None:
        self.quick_schedule_saved.emit(int(item_id))

    def _open_quick_popover(self) -> None:
        if self._quick_popover is None:
            self._quick_popover = StandaloneSchedulePopover(self.store)
            self._quick_popover.saved.connect(self._quick_popover_saved)
        self._quick_popover.open_at_current_time()
        self._quick_popover.title_edit.setText(self.quick_input.text())

    def _quick_popover_saved(self, item_id: int) -> None:
        self.quick_input.clear()
        self._reset_quick_engine()
        self._quick_message("저장했습니다.")
        self.quick_schedule_saved.emit(int(item_id))

    def _close_quick_windows(self) -> None:
        for window in (self._quick_engine, self._quick_popover):
            if window is not None:
                window.hide()
                window.deleteLater()
        self._quick_engine = None
        self._quick_popover = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.property("placed"):
            return
        self.adjustSize()
        if self.persistent_pet is not None and self.persistent_pet.isVisible():
            pet_rect = self.persistent_pet.frameGeometry()
            point = QPoint(pet_rect.left() - self.width() + 20, pet_rect.bottom() - self.height() + 12)
            screen = self.persistent_pet.screen()
        else:
            screen = self.screen()
            area = screen.availableGeometry() if screen is not None else self.geometry()
            point = QPoint(area.right() - self.width() - 28, area.bottom() - self.height() - 36)
        if screen is not None:
            area = screen.availableGeometry()
            point.setX(max(area.left(), min(point.x(), area.right() - self.width() + 1)))
            point.setY(max(area.top(), min(point.y(), area.bottom() - self.height() + 1)))
        self.move(point)
        self.setProperty("placed", True)
        if getattr(self, "quick_input", None) is not None:
            # 알림이 뜨면 바로 빠른 일정을 적을 수 있게 입력칸에 커서를 둔다.
            QTimer.singleShot(0, self._focus_quick_input)

    def _focus_quick_input(self) -> None:
        if sip.isdeleted(self) or not self.isVisible() or getattr(self, "quick_input", None) is None:
            return
        self.raise_()
        self.activateWindow()
        self.quick_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def keyPressEvent(self, event) -> None:
        # 알림 창에서 Enter는 ‘확인’이다.  빠른 일정 칸의 Enter는 일정 저장이라 따로 둔다.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            self._complete()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is getattr(self, "quick_input", None)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            # 비어 있으면 ‘확인’과 같다.  적었으면 저장하고, 저장되면 알림도 닫는다.
            if not self.quick_input.text().strip():
                self._complete()
            elif self.save_quick_schedule() is not None:
                self._complete()
            return True
        return super().eventFilter(watched, event)

    def _emit_complete(self) -> None:
        self.completed.emit(self.notification_id if self.is_schedule else self.reminder_id)

    @property
    def current_action(self) -> str:
        if self.motion is not None:
            return self.motion.current_action
        if self.persistent_pet is not None:
            return self.persistent_pet.motion.current_action
        return "idle"

    def play_action(self, action: str) -> None:
        if self.motion is not None:
            self.motion.play(action)
        elif self.persistent_pet is not None:
            self.persistent_pet.motion.play(action, override_pause=True)

    def _start_drag(self, point: QPoint) -> None:
        self._drag_origin = point - self.pos()

    def _drag(self, point: QPoint, direction: str) -> None:
        if self._drag_origin is None or self.motion is None:
            return
        if not self.motion.dragging:
            self.motion.begin_drag(direction)
        else:
            self.motion.update_drag_direction(direction)
        self.move(point - self._drag_origin)

    def _finish_drag(self) -> None:
        self._drag_origin = None
        if self.motion is not None:
            self.motion.end_drag()

    def _complete(self) -> None:
        self._emit_complete()
        self.accept()

    def _snooze(self, minutes: int) -> None:
        target_id = self.notification_id if self.is_schedule else self.reminder_id
        self.snoozed.emit(target_id, minutes)
        self.accept()

    def _open(self) -> None:
        self._emit_complete()
        if self.note_id is not None:
            self.note_open_requested.emit(self.note_id)
        else:
            self.schedule_open_requested.emit(self.item_id)
        self.accept()

    def _skip(self) -> None:
        """Compatibility action retained for existing callers; not shown in the new bubble."""
        if not self.is_schedule:
            self.skipped.emit(self.reminder_id)
            self.accept()
