from __future__ import annotations

from PyQt6.QtCore import QByteArray, QEvent, QPoint, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from .editor import COLORS
from .insert_menu import build_insert_menu
from .deadline import countdown_text, deadline_badge_text, reminder_display_text
from .rich_memo_edit import RichMemoTextEdit
from .rich_text import plain_text_from_content
from .window_geometry import WindowGeometryController


# The translucent window has an 8 px outer gutter, so a resize zone limited to
# less than 8 px misses the visible post-it border itself.  Extend the target a
# few pixels inside the surface while keeping it clear of editor content.
EDGE_MARGIN = 14
CORNER_MARGIN = 18


def _vector_icon(kind: str) -> QIcon:
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#172033"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    if kind == "plus":
        painter.drawLine(5, 10, 15, 10)
        painter.drawLine(10, 5, 10, 15)
    elif kind == "close":
        painter.drawLine(6, 6, 14, 14)
        painter.drawLine(14, 6, 6, 14)
    elif kind == "menu":
        painter.setBrush(QColor("#172033"))
        painter.setPen(Qt.PenStyle.NoPen)
        for x in (5, 10, 15):
            painter.drawEllipse(x - 1, 9, 2, 2)
    elif kind == "pin":
        painter.drawLine(7, 5, 13, 5)
        painter.drawLine(8, 5, 8, 10)
        painter.drawLine(12, 5, 12, 10)
        painter.drawLine(6, 10, 14, 10)
        painter.drawLine(10, 10, 10, 16)
    elif kind == "image":
        painter.drawRoundedRect(3, 4, 14, 12, 2, 2)
        painter.drawEllipse(6, 7, 2, 2)
        painter.drawLine(4, 14, 8, 10)
        painter.drawLine(8, 10, 11, 13)
        painter.drawLine(11, 13, 14, 9)
        painter.drawLine(14, 9, 17, 13)
    elif kind == "bullet":
        painter.setBrush(QColor("#172033"))
        for y in (6, 10, 14):
            painter.drawEllipse(3, y - 1, 2, 2)
            painter.drawLine(8, y, 17, y)
    elif kind == "checklist":
        painter.drawRect(3, 4, 12, 12)
        painter.drawLine(5, 10, 8, 13)
        painter.drawLine(8, 13, 14, 7)
    painter.end()
    return QIcon(pixmap)


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = str(text)
        self.setMinimumWidth(24)
        self._refresh_text()

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._refresh_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        width = max(1, self.width() - 4)
        QLabel.setText(self, self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, width,
        ))


class DragBar(QFrame):
    new_requested = pyqtSignal()
    pin_toggled = pyqtSignal(bool)
    options_requested = pyqtSignal()
    hide_requested = pyqtSignal()
    double_clicked = pyqtSignal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._offset: QPoint | None = None
        self.setObjectName("postitTitleBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 6, 2)
        layout.setSpacing(2)
        self.new_button = self._button("", "새 포스트잇", "plus")
        self.new_button.clicked.connect(self.new_requested)
        layout.addWidget(self.new_button)
        self.label = ElidedLabel(title)
        self.label.setObjectName("postitTitle")
        self.label.setAccessibleName("포스트잇 제목")
        self.label.hide()
        layout.addWidget(self.label, 1)
        self.spacer = QWidget(self)
        self.spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.spacer, 1)
        self.pin_button = self._button("", "항상 위", "pin")
        self.pin_button.setCheckable(True)
        self.pin_button.toggled.connect(self.pin_toggled)
        layout.addWidget(self.pin_button)
        self.options_button = self._button("", "포스트잇 보조 기능", "menu")
        self.options_button.clicked.connect(self.options_requested)
        layout.addWidget(self.options_button)
        self.close_button = self._button("", "포스트잇 숨기기", "close")
        self.close_button.clicked.connect(self.hide_requested)
        layout.addWidget(self.close_button)
        self.control_buttons = (
            self.new_button, self.pin_button, self.options_button, self.close_button,
        )

    @staticmethod
    def _button(text: str, accessible_name: str, icon: str = "") -> QToolButton:
        button = QToolButton()
        button.setObjectName("postitHeaderButton")
        button.setText(text)
        if icon:
            button.setIcon(_vector_icon(icon))
            button.setIconSize(QSize(18, 18))
        button.setAccessibleName(accessible_name)
        button.setToolTip(accessible_name)
        button.setFixedSize(36, 36)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def set_controls_visible(self, visible: bool) -> None:
        for button in self.control_buttons:
            button.setVisible(visible)

    def set_compact_content(self, text: str, visible: bool) -> None:
        self.label.setText(text)
        self.label.setVisible(visible)
        self.spacer.setVisible(not visible)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self._offset = event.globalPosition().toPoint() - self.window().pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class PostitMetaRow(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("postitMetaRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 4)
        layout.setSpacing(4)
        self.deadline = DeadlineMetaWidget(self)
        self.deadline.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.deadline, 1)
        self.reminder = QLabel(self)
        self.reminder.setObjectName("postitReminder")
        self.reminder.setAccessibleName("포스트잇 알림 시간")
        self.reminder.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.reminder, 0, Qt.AlignmentFlag.AlignRight)

    def set_values(self, deadline: str, reminder: str) -> None:
        self.deadline.setText(deadline)
        self.deadline.setVisible(bool(deadline))
        self.reminder.setText(reminder)
        self.reminder.setMinimumWidth(self.reminder.sizeHint().width() if reminder else 0)
        self.reminder.setVisible(bool(reminder))
        self.setVisible(bool(deadline or reminder))


class DeadlineMetaWidget(QWidget):
    """Keep the countdown intact while eliding only the optional title."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("postitDeadline")
        self.setAccessibleName("D-Day 남은 시간")
        self._full_text = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.countdown = QLabel(self)
        self.countdown.setObjectName("postitDeadlineCountdown")
        self.countdown.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.countdown)
        self.title = ElidedLabel(parent=self)
        self.title.setObjectName("postitDeadlineTitle")
        self.title.setMinimumWidth(self.title.fontMetrics().horizontalAdvance("…") + 4)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.title, 1)

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        countdown, separator, title = self._full_text.partition(" : ")
        self.countdown.setText(f"{countdown} : " if separator else countdown)
        self.countdown.setMinimumWidth(self.countdown.sizeHint().width())
        self.title.setText(title if separator else "")
        self.title.setVisible(bool(separator and title))
        self.setToolTip(self._full_text)

    def text(self) -> str:
        return self._full_text

class PostitFormatBar(QFrame):
    image_requested = pyqtSignal()
    bullet_requested = pyqtSignal()
    style_requested = pyqtSignal(str)
    checklist_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("postitFormatBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        self.style_buttons: dict[str, QToolButton] = {}
        for key, text, name in (
            ("bold", "B", "굵게"), ("italic", "I", "기울임"),
            ("underline", "U", "밑줄"), ("strike", "S", "취소선"),
        ):
            button = self._button(text, name)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=key: self.style_requested.emit(value))
            self.style_buttons[key] = button
            layout.addWidget(button)
        bullet = self._button("", "글머리표", "bullet")
        bullet.clicked.connect(self.bullet_requested)
        layout.addWidget(bullet)
        checklist = self._button("", "체크리스트", "checklist")
        checklist.setCheckable(True)
        self.checklist_button = checklist
        checklist.clicked.connect(self.checklist_requested)
        layout.addWidget(checklist)
        # 메모 편집창의 서식 막대와 같은 자리, 같은 목록.  켜짐/꺼짐 표시는 없다.
        insert = self._button("", "기능 넣기 (토글 · 페이지 추가)", "plus")
        insert.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.insert_button = insert
        layout.addWidget(insert)
        image = self._button("", "이미지 삽입", "image")
        image.clicked.connect(self.image_requested)
        layout.addWidget(image)

    @staticmethod
    def _button(text: str, accessible_name: str, icon: str = "") -> QToolButton:
        button = QToolButton()
        button.setObjectName("postitFormatButton")
        button.setText(text)
        if icon:
            button.setIcon(_vector_icon(icon))
            button.setIconSize(QSize(18, 18))
        button.setAccessibleName(accessible_name)
        button.setToolTip(accessible_name)
        button.setFixedSize(36, 36)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button


class PostitOptionsWidget(QWidget):
    color_selected = pyqtSignal(str)
    transparency_selected = pyqtSignal(int)
    always_top_toggled = pyqtSignal(bool)
    lock_toggled = pyqtSignal(bool)
    reminder_requested = pyqtSignal()
    quick_reminder_requested = pyqtSignal(int)
    deadline_requested = pyqtSignal()
    title_compact_requested = pyqtSignal()
    badge_compact_requested = pyqtSignal()
    editor_requested = pyqtSignal()
    startup_toggled = pyqtSignal(bool)
    unpin_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("postitOptionsPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        root.addWidget(self._label("색상"))
        colors = QHBoxLayout()
        colors.setSpacing(6)
        self.color_buttons = {}
        for key, (label, color) in COLORS.items():
            button = QPushButton()
            button.setAccessibleName(f"포스트잇 색상 {label}")
            button.setToolTip(label)
            button.setFixedSize(32, 32)
            button.clicked.connect(lambda _checked=False, value=key: self.color_selected.emit(value))
            colors.addWidget(button)
            self.color_buttons[key] = (button, color)
        root.addLayout(colors)
        root.addWidget(self._label("배경 투명도"))
        transparency = QGridLayout()
        transparency.setHorizontalSpacing(4)
        self.transparency_buttons = {}
        for column, value in enumerate((0, 30, 50, 70, 100)):
            button = QPushButton(str(value))
            button.setCheckable(True)
            button.setAccessibleName(f"배경 투명도 {value}퍼센트")
            button.setMinimumSize(38, 34)
            button.clicked.connect(lambda _checked=False, amount=value: self.transparency_selected.emit(amount))
            transparency.addWidget(button, 0, column)
            self.transparency_buttons[value] = button
        root.addLayout(transparency)
        self.always_top = QCheckBox("항상 위")
        self.lock = QCheckBox("입력 잠금")
        self.startup = QCheckBox("시작할 때 표시")
        for checkbox in (self.always_top, self.lock, self.startup):
            checkbox.setMinimumHeight(34)
            root.addWidget(checkbox)
        self.always_top.toggled.connect(self.always_top_toggled)
        self.lock.toggled.connect(self.lock_toggled)
        self.startup.toggled.connect(self.startup_toggled)
        root.addWidget(self._label("빠른 알림"))
        quick = QHBoxLayout()
        quick.setSpacing(4)
        for label, minutes in (("10분", 10), ("30분", 30), ("1시간", 60), ("내일", 1440)):
            button = QPushButton(label)
            button.setMinimumHeight(34)
            button.clicked.connect(
                lambda _checked=False, value=minutes: self.quick_reminder_requested.emit(value)
            )
            quick.addWidget(button)
        root.addLayout(quick)
        actions = QGridLayout()
        actions.setHorizontalSpacing(6)
        actions.setVerticalSpacing(5)
        actions.addWidget(self._action("알림 설정…", self.reminder_requested.emit), 0, 0)
        actions.addWidget(self._action("D-Day 설정…", self.deadline_requested.emit), 0, 1)
        actions.addWidget(self._action("편집기에서 열기", self.editor_requested.emit), 1, 0)
        actions.addWidget(self._action("제목만 접기", self.title_compact_requested.emit), 1, 1)
        actions.addWidget(self._action("색상 배지로 최소화", self.badge_compact_requested.emit), 2, 0, 1, 2)
        root.addLayout(actions)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("postitOptionsSeparator")
        root.addWidget(separator)
        destructive = QHBoxLayout()
        destructive.setSpacing(6)
        destructive.addWidget(self._action("포스트잇 모드 해제", self.unpin_requested.emit))
        delete = self._action("삭제…", self.delete_requested.emit)
        delete.setObjectName("postitDangerAction")
        destructive.addWidget(delete)
        root.addLayout(destructive)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("postitOptionsLabel")
        return label

    @staticmethod
    def _action(text: str, callback) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("postitMenuAction")
        button.setMinimumHeight(36)
        button.clicked.connect(callback)
        return button

    def set_state(self, note) -> None:
        color_key = str(note["color"])
        transparency_value = int(note["background_transparency"])
        for key, (button, color) in self.color_buttons.items():
            border = "3px solid #2563eb" if key == color_key else "1px solid #94a3b8"
            button.setStyleSheet(f"background:{color};border:{border};border-radius:16px;")
        for value, button in self.transparency_buttons.items():
            blocked = button.blockSignals(True)
            button.setChecked(value == transparency_value)
            button.blockSignals(blocked)
        for checkbox, value in (
            (self.always_top, bool(note["always_on_top"])),
            (self.lock, bool(note["input_locked"])),
            (self.startup, bool(note["postit_startup"])),
        ):
            blocked = checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(blocked)


class PostitWindow(QWidget):
    hide_requested = pyqtSignal(int)
    unpin_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    new_requested = pyqtSignal(int)
    editor_requested = pyqtSignal(int)
    reminder_requested = pyqtSignal(int)
    quick_reminder_requested = pyqtSignal(int, int)
    deadline_requested = pyqtSignal(int)
    cycle_requested = pyqtSignal(int, bool)
    content_saved = pyqtSignal(int, str)
    properties_changed = pyqtSignal(int)
    display_mode_changed = pyqtSignal(int)

    def __init__(self, store, note, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.store = store
        self.note_id = int(note["id"])
        self._shutdown = False
        self._always_on_top = None
        self._controls_visible = True
        self._display_mode = "normal"
        self._initialized = False
        self.setObjectName("postitWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(240, 180)
        self.resize(310, 250)
        self.container = QFrame(self)
        self.container.setObjectName("postitSurface")
        surface = QVBoxLayout(self.container)
        surface.setContentsMargins(0, 0, 0, 0)
        surface.setSpacing(0)
        self.bar = DragBar(str(note["title"]), self.container)
        surface.addWidget(self.bar)
        self.meta_row = PostitMetaRow(self.container)
        surface.addWidget(self.meta_row)
        self.deadline_badge = self.meta_row.deadline
        self.reminder_label = self.meta_row.reminder
        self.memo = RichMemoTextEdit(store, self.container)
        self.memo.setObjectName("postitEditor")
        self.memo.setFrameShape(QFrame.Shape.NoFrame)
        self.memo.setPlaceholderText("메모 내용을 입력하세요")
        self.memo.textChanged.connect(self._schedule_save)
        surface.addWidget(self.memo, 1)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(self.container)
        self.badge_button = QPushButton(self)
        self.badge_button.setObjectName("postitCompactBadge")
        self.badge_button.setAccessibleName("포스트잇 펼치기")
        self.badge_button.setToolTip("클릭하여 포스트잇 펼치기")
        self.badge_button.clicked.connect(lambda: self._set_display_mode("normal"))
        self.badge_button.hide()
        root.addWidget(self.badge_button)
        self.format_bar = PostitFormatBar(self.container)
        self.insert_menu = build_insert_menu(self.memo, self.format_bar.insert_button)
        self.format_bar.insert_button.setMenu(self.insert_menu)
        self.format_bar.hide()
        self.options_menu = QMenu(self)
        self.options_menu.setObjectName("postitOptionsMenu")
        self.options_menu.setStyleSheet(
            "QMenu#postitOptionsMenu{background:#ffffff;border:1px solid #cbd5e1;"
            "border-radius:10px;padding:2px;}"
            "QWidget#postitOptionsPanel{background:#ffffff;color:#172033;}"
            "QLabel#postitOptionsLabel{font-weight:700;color:#334155;}"
            "QPushButton#postitMenuAction{background:transparent;border:0;text-align:left;"
            "padding:6px 9px;border-radius:7px;}"
            "QPushButton#postitMenuAction:hover{background:#f1f5f9;}"
            "QPushButton#postitDangerAction{background:transparent;border:0;text-align:left;"
            "padding:6px 9px;color:#dc2626;border-radius:7px;}"
            "QPushButton#postitDangerAction:hover{background:#fff1f2;}"
            "QPushButton:checked{background:#2563eb;color:#ffffff;border-color:#2563eb;}"
            "QFrame#postitOptionsSeparator{color:#e2e8f0;}"
        )
        self.options_panel = PostitOptionsWidget(self.options_menu)
        action = QWidgetAction(self.options_menu)
        action.setDefaultWidget(self.options_panel)
        self.options_menu.addAction(action)
        self.save_error_label = QPushButton("저장 실패 · 다시 시도", self.container)
        self.save_error_label.setObjectName("postitSaveError")
        self.save_error_label.setAccessibleName("포스트잇 저장 다시 시도")
        self.save_error_label.clicked.connect(self._save_content)
        self.save_error_label.hide()
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self._save_content)
        self.controls_timer = QTimer(self)
        self.controls_timer.setSingleShot(True)
        self.controls_timer.setInterval(240)
        self.controls_timer.timeout.connect(self._hide_controls_if_idle)
        self.deadline_timer = QTimer(self)
        self.deadline_timer.setInterval(60_000)
        self.deadline_timer.timeout.connect(self._refresh_deadline_badge)
        self.deadline_timer.start()
        self.geometry_controller = WindowGeometryController(
            self, store.setting, store.set_setting, f"postit_geometry_{self.note_id}",
        )
        self._connect_controls()
        self._install_shortcuts()
        self._install_window_event_filters()
        self.update_note(note)
        self.geometry_controller.restore()
        self._initialized = True
        self._apply_display_mode(str(note["postit_display_mode"] or "normal"), restore_expanded=False)
        self._set_controls_visible(False)

    def _connect_controls(self) -> None:
        self.bar.new_requested.connect(lambda: self.new_requested.emit(self.note_id))
        self.bar.pin_toggled.connect(lambda checked: self._set_property("always_on_top", checked))
        self.bar.options_requested.connect(self._show_options)
        self.bar.hide_requested.connect(lambda: self.hide_requested.emit(self.note_id))
        self.bar.double_clicked.connect(self._toggle_title_compact)
        self.format_bar.style_requested.connect(self.memo.toggle_character_style)
        self.format_bar.bullet_requested.connect(self.memo.toggle_bullet_list)
        self.format_bar.checklist_requested.connect(self.memo.toggle_checklist)
        self.format_bar.image_requested.connect(self.memo.choose_and_insert_image)
        self.memo.currentCharFormatChanged.connect(self._sync_format_buttons)
        self.memo.cursorPositionChanged.connect(lambda: self._sync_format_buttons(self.memo.currentCharFormat()))
        panel = self.options_panel
        panel.color_selected.connect(lambda value: self._set_property("color", value))
        panel.transparency_selected.connect(lambda value: self._set_property("background_transparency", value))
        panel.always_top_toggled.connect(lambda value: self._set_property("always_on_top", value))
        panel.lock_toggled.connect(lambda value: self._set_property("input_locked", value))
        panel.startup_toggled.connect(lambda value: self._set_property("postit_startup", value))
        panel.reminder_requested.connect(lambda: self.reminder_requested.emit(self.note_id))
        panel.quick_reminder_requested.connect(
            lambda minutes: self.quick_reminder_requested.emit(self.note_id, minutes)
        )
        panel.deadline_requested.connect(lambda: self.deadline_requested.emit(self.note_id))
        panel.title_compact_requested.connect(lambda: self._set_display_mode("title"))
        panel.badge_compact_requested.connect(lambda: self._set_display_mode("badge"))
        panel.editor_requested.connect(lambda: self.editor_requested.emit(self.note_id))
        panel.unpin_requested.connect(lambda: self.unpin_requested.emit(self.note_id))
        panel.delete_requested.connect(self._confirm_delete)
        self.options_menu.aboutToShow.connect(lambda: self._set_controls_visible(True))
        self.options_menu.aboutToHide.connect(self._schedule_controls_hide)

    def _install_shortcuts(self) -> None:
        shortcuts = (
            ("Ctrl+N", lambda: self.new_requested.emit(self.note_id)),
            ("Ctrl+W", lambda: self.hide_requested.emit(self.note_id)),
            ("Ctrl+D", self._confirm_delete),
            ("Ctrl+B", lambda: self.memo.toggle_character_style("bold")),
            ("Ctrl+I", lambda: self.memo.toggle_character_style("italic")),
            ("Ctrl+U", lambda: self.memo.toggle_character_style("underline")),
            ("Ctrl+T", lambda: self.memo.toggle_character_style("strike")),
            ("Ctrl+Shift+L", self.memo.toggle_bullet_list),
            ("Ctrl+Tab", lambda: self.cycle_requested.emit(self.note_id, False)),
            ("Ctrl+Shift+Tab", lambda: self.cycle_requested.emit(self.note_id, True)),
            ("Esc", self._close_open_menu),
        )
        self.shortcuts = []
        for sequence, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

    def _install_window_event_filters(self) -> None:
        for widget in (self, *self.findChildren(QWidget)):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        event_type = event.type()
        if event_type in {QEvent.Type.Enter, QEvent.Type.MouseMove, QEvent.Type.FocusIn, QEvent.Type.WindowActivate}:
            self.controls_timer.stop()
            self._set_controls_visible(True)
        elif event_type in {QEvent.Type.Leave, QEvent.Type.FocusOut, QEvent.Type.WindowDeactivate}:
            self._schedule_controls_hide()
        if event_type == QEvent.Type.MouseMove and hasattr(event, "globalPosition"):
            self._update_resize_cursor(event.globalPosition().toPoint())
        elif event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            edges = self._resize_edges(event.globalPosition().toPoint())
            if edges and self.windowHandle() is not None and self.windowHandle().startSystemResize(edges):
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def update_note(self, note) -> None:
        self.memo.set_note_context(self.note_id)
        if not self.save_timer.isActive() and not self.memo.hasFocus():
            content = str(note["content"])
            if self.memo.content() != content:
                blocked = self.memo.blockSignals(True)
                self.memo.set_content(content)
                self.memo.blockSignals(blocked)
        self.memo.setReadOnly(bool(note["input_locked"]))
        self._set_controls_visible(self._controls_visible)
        self._set_check_state(self.bar.pin_button, bool(note["always_on_top"]))
        self.options_panel.set_state(note)
        self._apply_surface_style(str(note["color"]), int(note["background_transparency"]))
        self._deadline_note = note
        self._refresh_deadline_badge()
        self._refresh_compact_content()
        self._apply_top_flag(bool(note["always_on_top"]))
        if self._initialized:
            self._apply_display_mode(str(note["postit_display_mode"] or "normal"), restore_expanded=False)

    def _sync_format_buttons(self, fmt) -> None:
        states = {
            "bold": fmt.fontWeight() >= QFont.Weight.Bold,
            "italic": fmt.fontItalic(),
            "underline": fmt.fontUnderline(),
            "strike": fmt.fontStrikeOut(),
        }
        for key, checked in states.items():
            self._set_check_state(self.format_bar.style_buttons[key], checked)
        self._set_check_state(
            self.format_bar.checklist_button, self.memo.current_block_is_checklist(),
        )

    @staticmethod
    def _set_check_state(button, checked: bool) -> None:
        blocked = button.blockSignals(True)
        button.setChecked(checked)
        button.blockSignals(blocked)

    def _apply_surface_style(self, color_key: str, transparency: int) -> None:
        color = COLORS.get(color_key, COLORS["vanilla"])[1].lstrip("#")
        red, green, blue = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        alpha = round(255 * (100 - max(0, min(100, transparency))) / 100)
        border_alpha = max(70, alpha)
        self.setStyleSheet(
            f"QFrame#postitSurface{{background:rgba({red},{green},{blue},{alpha});"
            f"border:1px solid rgba(100,116,139,{border_alpha});border-radius:10px;}}"
            f"QFrame#postitTitleBar{{background:rgba({red},{green},{blue},{alpha});border:0;}}"
            "QTextEdit#postitEditor{background:transparent;border:0;padding:14px;"
            "font-family:'Segoe UI Variable','Malgun Gothic';font-size:14px;color:#172033;}"
            "QLabel#postitTitle{font-family:'Segoe UI Variable','Malgun Gothic';font-size:14px;"
            "font-weight:600;color:#172033;padding-left:4px;}"
            "QToolButton#postitHeaderButton,QToolButton#postitFormatButton{background:rgba(255,255,255,190);"
            "border:1px solid rgba(100,116,139,80);border-radius:8px;color:#172033;font-size:15px;}"
            "QToolButton#postitHeaderButton:hover,QToolButton#postitFormatButton:hover{"
            "background:rgba(255,255,255,235);border-color:#64748b;}"
            "QToolButton#postitHeaderButton:focus,QToolButton#postitFormatButton:focus{border:2px solid #2563eb;}"
            "QToolButton#postitHeaderButton:checked{background:#2563eb;color:white;}"
            "QFrame#postitFormatBar{background:rgba(255,255,255,224);border:1px solid rgba(100,116,139,90);"
            "border-radius:9px;}"
            "QFrame#postitMetaRow{background:transparent;border:0;}"
            "QWidget#postitDeadline{background:transparent;}"
            "QLabel#postitDeadlineCountdown,QLabel#postitDeadlineTitle{"
            "background:transparent;color:#172033;font-weight:700;}"
            "QLabel#postitReminder{background:transparent;color:#172033;}"
            "QPushButton#postitSaveError{background:#fff1f2;color:#b42318;border:1px solid #fecdd3;"
            "border-radius:7px;padding:5px 8px;}"
            f"QPushButton#postitCompactBadge{{background:rgba({red},{green},{blue},{max(120, alpha)});"
            "border:2px solid #64748b;border-radius:22px;color:#172033;font-weight:700;padding:0;}"
            "QPushButton#postitCompactBadge:hover{border-color:#2563eb;}"
        )

    def _show_options(self) -> None:
        note = self.store.note(self.note_id)
        if note is not None:
            self.options_panel.set_state(note)
        self.options_menu.popup(self.bar.options_button.mapToGlobal(QPoint(0, self.bar.options_button.height())))

    def _close_open_menu(self) -> None:
        if self.options_menu.isVisible():
            self.options_menu.close()

    def _set_property(self, key: str, value) -> None:
        try:
            self.store.update_note(self.note_id, **{key: value})
        except Exception as exc:
            self.show_save_error(str(exc))
            return
        note = self.store.note(self.note_id)
        if note is not None:
            self.update_note(note)
        self.properties_changed.emit(self.note_id)

    def _confirm_delete(self) -> None:
        self.options_menu.close()
        self.delete_requested.emit(self.note_id)

    def _schedule_save(self) -> None:
        if self._initialized and not self.memo.isReadOnly():
            self._refresh_compact_content()
            self.save_error_label.hide()
            self.save_timer.start()

    def _save_content(self) -> None:
        self.content_saved.emit(self.note_id, self.memo.content())

    def show_save_error(self, detail: str = "") -> None:
        self.save_error_label.setToolTip(detail)
        self.save_error_label.show()
        self._set_controls_visible(True)
        self._position_overlays()

    def mark_saved(self) -> None:
        self.save_error_label.hide()
        self.memo.mark_document_saved()

    def _set_controls_visible(self, visible: bool) -> None:
        self._controls_visible = bool(visible)
        self.bar.set_controls_visible(visible)
        self.bar.setVisible(visible or self._display_mode == "title")
        self._refresh_compact_content()
        self.format_bar.setVisible(
            visible and not self.memo.isReadOnly() and self._display_mode == "normal"
        )
        self._update_normal_minimum_width()
        self._position_overlays()

    def _schedule_controls_hide(self) -> None:
        if not self.options_menu.isVisible():
            self.controls_timer.start()

    def _hide_controls_if_idle(self) -> None:
        focus = QApplication.focusWidget()
        owns_focus = focus is not None and (focus is self or self.isAncestorOf(focus))
        if not self.underMouse() and not owns_focus and not self.options_menu.isVisible():
            self._set_controls_visible(False)

    def _position_overlays(self) -> None:
        if self.format_bar.isVisible():
            self.format_bar.adjustSize()
            x = max(10, (self.container.width() - self.format_bar.width()) // 2)
            y = max(self.bar.height() + 8, self.container.height() - self.format_bar.height() - 10)
            self.format_bar.move(x, y)
            self.format_bar.raise_()
        if self.save_error_label.isVisible():
            self.save_error_label.adjustSize()
            self.save_error_label.move(12, max(self.bar.height() + 6, self.container.height() - 86))
            self.save_error_label.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_overlays()

    def _refresh_deadline_badge(self) -> None:
        note = getattr(self, "_deadline_note", None)
        text = deadline_badge_text(note) if note is not None else ""
        reminder = reminder_display_text(str(note["reminder_due_at"] or "")) if note is not None else ""
        if self._display_mode == "normal":
            self.meta_row.set_values(text, reminder)
            self._update_normal_minimum_width()
        else:
            self.meta_row.hide()
        compact_text = countdown_text(str(note["d_day_at"] or "")) if note is not None else ""
        self.badge_button.setText(compact_text if compact_text else "●")
        self.badge_button.setToolTip(text or "클릭하여 포스트잇 펼치기")
        self._position_overlays()

    def _update_normal_minimum_width(self) -> None:
        if self._display_mode != "normal":
            return
        minimum = 240
        if not self.meta_row.isHidden():
            minimum = max(minimum, self.meta_row.minimumSizeHint().width() + 18)
        if not self.format_bar.isHidden():
            self.format_bar.adjustSize()
            minimum = max(minimum, self.format_bar.width() + 36)
        self.setMinimumWidth(minimum)

    def _refresh_compact_content(self) -> None:
        content = plain_text_from_content(self.memo.content())
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "메모")
        if first_line.startswith(("☐ ", "☑ ")):
            first_line = first_line[2:].strip() or "메모"
        self.bar.set_compact_content(first_line, self._display_mode == "title")

    def _toggle_title_compact(self) -> None:
        self._set_display_mode("normal" if self._display_mode == "title" else "title")

    def _set_display_mode(self, mode: str) -> None:
        resolved = mode if mode in {"normal", "title", "badge"} else "normal"
        if resolved == self._display_mode:
            return
        if self._display_mode == "normal" and resolved != "normal":
            self.store.set_setting(
                f"postit_expanded_geometry_{self.note_id}",
                bytes(self.saveGeometry().toBase64()).decode("ascii"),
            )
        self.store.update_note(self.note_id, postit_display_mode=resolved)
        self._apply_display_mode(resolved, restore_expanded=resolved == "normal")
        self.properties_changed.emit(self.note_id)
        self.display_mode_changed.emit(self.note_id)

    def _apply_display_mode(self, mode: str, restore_expanded: bool) -> None:
        resolved = mode if mode in {"normal", "title", "badge"} else "normal"
        self._display_mode = resolved
        self.setMaximumSize(16_777_215, 16_777_215)
        if resolved == "badge":
            self.container.hide()
            self.badge_button.show()
            self.layout().setContentsMargins(3, 3, 3, 3)
            self.setMinimumSize(54, 54)
            self.setMaximumSize(64, 64)
            self.resize(58, 58)
        elif resolved == "title":
            self.badge_button.hide()
            self.container.show()
            self.memo.hide()
            self.meta_row.hide()
            self.format_bar.hide()
            self._refresh_compact_content()
            self.bar.show()
            self.layout().setContentsMargins(6, 6, 6, 6)
            self.setMinimumSize(220, 58)
            self.setMaximumHeight(64)
            self.resize(max(220, self.width()), 60)
        else:
            self.badge_button.hide()
            self.container.show()
            self.memo.show()
            self.setMinimumSize(240, 180)
            self._refresh_deadline_badge()
            self.bar.set_compact_content("", False)
            self.layout().setContentsMargins(8, 8, 8, 8)
            if restore_expanded:
                encoded = self.store.setting(f"postit_expanded_geometry_{self.note_id}", "")
                if encoded:
                    self.restoreGeometry(QByteArray.fromBase64(encoded.encode("ascii")))
                    self.geometry_controller.ensure_visible()
            self._set_controls_visible(self._controls_visible)

    def _resize_edges(self, global_point: QPoint) -> Qt.Edge:
        point = self.mapFromGlobal(global_point)
        right_edge = self.width() - 1
        bottom_edge = self.height() - 1
        left = point.x() <= CORNER_MARGIN
        right = point.x() >= right_edge - CORNER_MARGIN
        top = point.y() <= CORNER_MARGIN
        bottom = point.y() >= bottom_edge - CORNER_MARGIN
        if top and left:
            return Qt.Edge.TopEdge | Qt.Edge.LeftEdge
        if top and right:
            return Qt.Edge.TopEdge | Qt.Edge.RightEdge
        if bottom and left:
            return Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        if bottom and right:
            return Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        edges = Qt.Edge(0)
        if point.x() <= EDGE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif point.x() >= right_edge - EDGE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if point.y() <= EDGE_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif point.y() >= bottom_edge - EDGE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _update_resize_cursor(self, global_point: QPoint) -> None:
        edges = self._resize_edges(global_point)
        cursors = {
            Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeBDiagCursor,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(edges, Qt.CursorShape.ArrowCursor))

    def _apply_top_flag(self, always_on_top: bool) -> None:
        if self._always_on_top is always_on_top:
            return
        self._always_on_top = always_on_top
        visible = self.isVisible()
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if visible:
            self.show()

    def flush_pending_save(self) -> None:
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_content()

    def close_silently(self) -> None:
        self._shutdown = True
        self.deadline_timer.stop()
        self.flush_pending_save()
        self.geometry_controller.save()
        self.close()
        self.deleteLater()

    def closeEvent(self, event) -> None:
        self.flush_pending_save()
        self.geometry_controller.save()
        if self._shutdown:
            event.accept()
            return
        event.ignore()
        self.hide_requested.emit(self.note_id)
