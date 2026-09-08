"""Toma pet alert bubble using the current Codex GPT pet runtime contract."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QVBoxLayout,
)

from .deadline import countdown_text
from .note_shortcuts import TIME_SHORTCUTS, shortcut_text
from .rich_text import plain_text_from_content
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

    def __init__(self, reminder, is_schedule: bool, parent=None, *, persistent_pet=None, modifier="Alt"):
        super().__init__(parent)
        self.reminder = reminder
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
        done.setMinimumHeight(36)
        done.clicked.connect(self._complete)
        actions.addWidget(done, 1)
        edit_label = "일정편집" if self.is_schedule and self.note_id is None else "메모편집"
        edit = QPushButton(edit_label)
        edit.setObjectName("tomaAlertSecondaryButton")
        edit.setAccessibleName(edit_label)
        edit.setMinimumHeight(36)
        edit.clicked.connect(self._open)
        actions.addWidget(edit)
        bubble_layout.addLayout(actions)
        root.addWidget(self.bubble)
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
            "QPushButton#tomaQuickSnoozeButton { font-size: 11px; padding: 2px 7px; }"
        )

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
