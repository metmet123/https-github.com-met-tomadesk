from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QGraphicsDropShadowEffect, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .schedule_postit_model import SchedulePostitItem, SchedulePostitModel
from .schedule_postit_settings import (
    SchedulePostitPreferences, VIEW_DAY, VIEW_DUE, VIEW_PRIORITY, VIEW_WEEK,
    load_position, save_position,
)


VIEW_LABELS = (
    (VIEW_DAY, "당일"), (VIEW_WEEK, "이번 주"),
    (VIEW_DUE, "임박순"), (VIEW_PRIORITY, "우선도순"),
)
WEEKDAYS = "월화수목금토일"


class SchedulePostitRow(QFrame):
    toggled = pyqtSignal(object, bool)

    def __init__(self, item: SchedulePostitItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("schedulePostitRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(7)
        self.check = QCheckBox()
        self.check.setChecked(item.completed)
        self.check.setAccessibleName(f"{item.title} 완료")
        self.check.toggled.connect(lambda on: self.toggled.emit(self.item, bool(on)))
        layout.addWidget(self.check)
        self.badge = QLabel(item.badge)
        self.badge.setObjectName("schedulePostitBadge")
        self.badge.setProperty("kind", _badge_kind(item))
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.badge)
        self.title = QLabel(item.title)
        self.title.setObjectName("schedulePostitTitle")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        font = QFont(self.title.font())
        font.setStrikeOut(item.completed)
        self.title.setFont(font)
        self.title.setProperty("completed", item.completed)
        layout.addWidget(self.title, 1)
        self.time = QLabel(item.time_text)
        self.time.setObjectName("schedulePostitTime")
        layout.addWidget(self.time)
        self.setToolTip(f"{item.target_at:%Y-%m-%d %H:%M} · {item.title}")


class SchedulePostitWindow(QWidget):
    changed = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.store = store
        self.model = SchedulePostitModel(store)
        self.preferences = SchedulePostitPreferences.load(store)
        self.selected_date = date.today()
        self.rows: list[SchedulePostitRow] = []
        self._restored_position = False
        self._shutdown = False
        self._drag_offset: QPoint | None = None
        self.setObjectName("schedulePostitWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(340)
        self.resize(340, 210)
        self._build_ui()
        self._apply_style()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        self.card = QFrame()
        self.card.setObjectName("schedulePostitCard")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(27, 43, 75, 38))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)
        card = QVBoxLayout(self.card)
        card.setContentsMargins(0, 0, 0, 0)
        card.setSpacing(0)

        header = QFrame()
        header.setObjectName("schedulePostitHeader")
        head = QHBoxLayout(header)
        head.setContentsMargins(13, 13, 13, 10)
        head.setSpacing(8)
        self.previous_button = QPushButton("‹")
        self.previous_button.setAccessibleName("이전날")
        self.previous_button.clicked.connect(lambda: self.move_date(-1))
        head.addWidget(self.previous_button)
        self.today_button = QPushButton()
        self.today_button.setObjectName("schedulePostitDate")
        self.today_button.setAccessibleName("오늘로 이동")
        self.today_button.clicked.connect(self.go_today)
        head.addWidget(self.today_button, 1)
        self.next_button = QPushButton("›")
        self.next_button.setAccessibleName("다음날")
        self.next_button.clicked.connect(lambda: self.move_date(1))
        head.addWidget(self.next_button)
        card.addWidget(header)

        view_frame = QFrame()
        views = QHBoxLayout(view_frame)
        views.setContentsMargins(13, 0, 13, 10)
        views.setSpacing(5)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_buttons: dict[str, QPushButton] = {}
        for key, label in VIEW_LABELS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setAccessibleName(f"{label} 보기")
            button.clicked.connect(lambda _checked=False, value=key: self.set_view(value))
            views.addWidget(button, 1)
            self.view_group.addButton(button)
            self.view_buttons[key] = button
        card.addWidget(view_frame)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("schedulePostitScroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.scroll.setWidget(self.rows_host)
        card.addWidget(self.scroll)

        self.footer = QFrame()
        self.footer.setObjectName("schedulePostitFooter")
        self.footer.setCursor(Qt.CursorShape.SizeAllCursor)
        self.footer.setToolTip("이 부분을 끌어서 창을 옮길 수 있습니다.")
        self.footer.installEventFilter(self)
        foot = QHBoxLayout(self.footer)
        foot.setContentsMargins(13, 10, 13, 11)
        self.help_label = QLabel("체크하면 삭선 · 설정에서 휴지통으로 바꿀 수 있음")
        self.help_label.setObjectName("schedulePostitHelp")
        foot.addWidget(self.help_label, 1)
        self.count_label = QLabel()
        self.count_label.setObjectName("schedulePostitCount")
        foot.addWidget(self.count_label)
        card.addWidget(self.footer)

        self.hide_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.hide_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.hide_shortcut.activated.connect(self.hide)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            #schedulePostitCard { background: white; border: 1px solid #d8e0ec; border-radius: 11px; }
            #schedulePostitHeader QPushButton { min-width: 30px; min-height: 32px; max-height: 32px; border: 1px solid #d8e0ec; border-radius: 6px; background: white; color: #24314b; }
            #schedulePostitHeader #schedulePostitDate { background: #2f69ec; border-color: #2f69ec; color: white; font-weight: 700; }
            #schedulePostitHeader QPushButton:focus { border: 2px solid #244fc4; }
            #schedulePostitWindow QPushButton[checkable="true"] { min-height: 26px; padding: 0 3px; border: 1px solid #d8e0ec; border-radius: 6px; background: #f8fafe; color: #59657d; font-size: 11px; }
            #schedulePostitWindow QPushButton[checkable="true"]:checked { background: #edf2ff; border-color: #9bb4f2; color: #2455c4; font-weight: 700; }
            #schedulePostitScroll { border-top: 1px solid #e4e9f1; background: white; }
            #schedulePostitRow { background: white; border: 0; }
            #schedulePostitBadge { min-width: 34px; padding: 2px 4px; border-radius: 4px; font-size: 10px; font-weight: 700; }
            #schedulePostitBadge[kind="event"] { background: #eef3ff; color: #3155d8; }
            #schedulePostitBadge[kind="task"] { background: #fff1df; color: #a06010; }
            #schedulePostitBadge[kind="deadline"] { background: #fff0f1; color: #c43a48; }
            #schedulePostitTitle { color: #24314b; }
            #schedulePostitTitle[completed="true"] { color: #a9b2c3; }
            #schedulePostitTime, #schedulePostitHelp, #schedulePostitCount { color: #91a0ba; font-size: 11px; }
            #schedulePostitFooter { border-top: 1px solid #e4e9f1; background: white; }
        """)

    def apply_preferences(self, preferences: SchedulePostitPreferences) -> None:
        self.preferences = preferences.normalized()
        self.preferences.save(self.store)
        self.refresh()

    def set_view(self, view: str) -> None:
        self.preferences = SchedulePostitPreferences(
            **{**self.preferences.__dict__, "view": view}
        ).normalized()
        self.preferences.save(self.store)
        self.refresh()

    def move_date(self, days: int) -> None:
        self.selected_date += timedelta(days=int(days))
        self.refresh()

    def go_today(self) -> None:
        self.selected_date = date.today()
        self.refresh()

    def refresh(self) -> None:
        if self._shutdown:
            return
        self.today_button.setText(
            f"{'오늘 · ' if self.selected_date == date.today() else ''}"
            f"{self.selected_date.month}월 {self.selected_date.day}일 "
            f"({WEEKDAYS[self.selected_date.weekday()]})"
        )
        for key, button in self.view_buttons.items():
            button.setChecked(key == self.preferences.view)
        while self.rows_layout.count():
            child = self.rows_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self.rows.clear()
        items = self.model.items(self.selected_date, self.preferences)
        if not items:
            empty = QLabel("표시할 일정이나 할 일이 없습니다.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("schedulePostitHelp")
            empty.setMinimumHeight(42)
            self.rows_layout.addWidget(empty)
        else:
            for item in items:
                row = SchedulePostitRow(item)
                row.toggled.connect(self._set_completed)
                self.rows_layout.addWidget(row)
                self.rows.append(row)
        self._resize_for_rows(len(items))

    def _resize_for_rows(self, total: int) -> None:
        visible_rows = max(1, min(total, self.preferences.max_rows))
        row_heights = [max(1, row.sizeHint().height()) for row in self.rows[:visible_rows]]
        content_height = sum(row_heights) if row_heights else 42
        self.scroll.setFixedHeight(content_height + 2)
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if total > self.preferences.max_rows
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setVerticalScrollBarPolicy(policy)
        self.count_label.setText(f"{total}건 · 최대 {self.preferences.max_rows}줄")
        self.adjustSize()

    def _set_completed(self, item: SchedulePostitItem, completed: bool) -> None:
        self.model.set_completed(item, completed, self.preferences.completion_mode)
        self.changed.emit()
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._restored_position:
            return
        self._restored_position = True
        position = load_position(self.store)
        if position is not None:
            self.move(*position)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self._restored_position and not self._shutdown:
            save_position(self.store, self.x(), self.y())

    def eventFilter(self, watched, event) -> bool:
        if watched is self.footer:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                return True
        return super().eventFilter(watched, event)

    def shutdown(self) -> None:
        self._shutdown = True
        self.close()


def _badge_kind(item: SchedulePostitItem) -> str:
    if item.source == "deadline":
        return "deadline"
    return "event" if item.badge == "일정" else "task"
