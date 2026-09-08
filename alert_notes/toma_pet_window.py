"""Persistent Codex-style Toma pet window and interaction menu."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import QDialog, QLabel, QMenu, QVBoxLayout

from .toma_pet_assets import TomaSpriteAtlas
from .toma_pet_motion import TomaMotionPlayer


ACTION_LABELS = {
    "idle": "기본",
    "waving": "인사",
    "jumping": "점프",
    "waiting": "기다리기",
    "working": "작업 중",
    "reviewing": "완료",
    "failed": "실패",
}


class TomaSpriteLabel(QLabel):
    action_requested = pyqtSignal(str)
    drag_started = pyqtSignal(QPoint)
    dragged = pyqtSignal(QPoint, str)
    drag_finished = pyqtSignal()
    menu_requested = pyqtSignal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(144, 156)
        self.setAccessibleName("토마펫")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._menu = QMenu(self)
        menu_actions = {
            "idle": "기본", "running_right": "오른쪽 이동", "running_left": "왼쪽 이동",
            "waving": "인사", "jumping": "점프", "failed": "실패",
            "waiting": "기다리기", "working": "작업 중", "reviewing": "완료",
        }
        for action, label in menu_actions.items():
            item = QAction(label, self._menu)
            item.triggered.connect(lambda _checked=False, value=action: self.action_requested.emit(value))
            self._menu.addAction(item)
        self._press_global: QPoint | None = None
        self._last_global: QPoint | None = None
        self._drag_active = False

    def contextMenuEvent(self, event) -> None:
        self.menu_requested.emit(event.globalPos())
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.globalPosition().toPoint()
            self._press_global = point
            self._last_global = point
            self._drag_active = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._press_global is not None:
            point = event.globalPosition().toPoint()
            delta = point - self._press_global
            if not self._drag_active and max(abs(delta.x()), abs(delta.y())) >= 4:
                self._drag_active = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.drag_started.emit(self._press_global)
            if self._drag_active:
                previous = self._last_global or point
                direction = "right" if point.x() >= previous.x() else "left"
                self.dragged.emit(point, direction)
            self._last_global = point
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press_global is not None:
            if self._drag_active:
                self.drag_finished.emit()
            self._press_global = None
            self._last_global = None
            self._drag_active = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class TomaPetWindow(QDialog):
    hidden_by_user = pyqtSignal()

    def __init__(self, setting_getter, setting_setter, open_calendar, open_quick_memo):
        super().__init__(None)
        self._setting = setting_getter
        self._set_setting = setting_setter
        self._open_calendar = open_calendar
        self._open_quick_memo = open_quick_memo
        self._drag_origin: QPoint | None = None
        self._restoring_position = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_position)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setAccessibleName("상시 토마펫")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pet = TomaSpriteLabel(self)
        layout.addWidget(self.pet)
        self.motion = TomaMotionPlayer(self.pet, TomaSpriteAtlas(), self)
        self.pet.drag_started.connect(self._start_drag)
        self.pet.dragged.connect(self._drag)
        self.pet.drag_finished.connect(self._finish_drag)
        self.pet.menu_requested.connect(self._show_menu)

    @property
    def paused(self) -> bool:
        return self.motion.paused

    def show_persistent(self) -> None:
        self._restore_position()
        self.show()
        self.raise_()

    def play_alert_completion(self) -> None:
        self.motion.play("reviewing", override_pause=True)

    def reset_position(self) -> None:
        self._set_setting("toma_pet_position", "")
        self._move_to_default()

    def stop(self) -> None:
        self._save_timer.stop()
        self._save_position()
        self.motion.stop()
        # Hide and defer deletion instead of closing a second top-level tool
        # window during MainWindow.closeEvent; this avoids an unintended
        # lastWindowClosed quit while Qt is still draining shutdown events.
        self.hide()
        self.deleteLater()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self.isVisible() and not self._restoring_position:
            self._save_timer.start()

    def _start_drag(self, point: QPoint) -> None:
        self._drag_origin = point - self.pos()

    def _drag(self, point: QPoint, direction: str) -> None:
        if self._drag_origin is None:
            return
        if not self.motion.dragging:
            self.motion.begin_drag(direction)
        else:
            self.motion.update_drag_direction(direction)
        self.move(point - self._drag_origin)

    def _finish_drag(self) -> None:
        self._drag_origin = None
        self.motion.end_drag()
        self._save_position()

    def _show_menu(self, global_point: QPoint) -> None:
        menu = QMenu(self)
        pause = menu.addAction("다시 시작" if self.paused else "일시정지")
        pause.triggered.connect(lambda: self.motion.set_paused(not self.paused))
        actions_menu = menu.addMenu("행동 재생")
        for action, label in ACTION_LABELS.items():
            item = QAction(label, actions_menu)
            item.triggered.connect(lambda _checked=False, value=action: self.motion.play(value))
            actions_menu.addAction(item)
        menu.addSeparator()
        calendar = menu.addAction("캘린더 열기")
        calendar.triggered.connect(self._open_calendar)
        quick_memo = menu.addAction("빠른 메모")
        quick_memo.triggered.connect(self._open_quick_memo)
        menu.addSeparator()
        reset = menu.addAction("위치 초기화")
        reset.triggered.connect(self.reset_position)
        hide = menu.addAction("토마펫 숨기기")
        hide.triggered.connect(self._hide_from_menu)
        menu.exec(global_point)

    def _hide_from_menu(self) -> None:
        self._set_setting("toma_pet_persistent_enabled", "false")
        self.hide()
        self.hidden_by_user.emit()

    def _restore_position(self) -> None:
        raw = self._setting("toma_pet_position", "")
        try:
            x_text, y_text = str(raw).split(",", 1)
            point = QPoint(int(x_text), int(y_text))
        except (TypeError, ValueError):
            self._move_to_default()
            return
        self._move_clamped(point)

    def _move_to_default(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self._move_clamped(QPoint(area.right() - self.width() - 28, area.bottom() - self.height() - 36))

    def _move_clamped(self, point: QPoint) -> None:
        screens = QGuiApplication.screens()
        target = next((screen.availableGeometry() for screen in screens if screen.availableGeometry().contains(point)), None)
        if target is None:
            primary = QGuiApplication.primaryScreen()
            target = primary.availableGeometry() if primary is not None else None
        if target is None:
            return
        x = max(target.left(), min(point.x(), target.right() - self.width() + 1))
        y = max(target.top(), min(point.y(), target.bottom() - self.height() + 1))
        self._restoring_position = True
        self.move(x, y)
        self._restoring_position = False

    def _save_position(self) -> None:
        if self.isVisible():
            self._set_setting("toma_pet_position", f"{self.x()},{self.y()}")


class TomaPetController:
    ALERT_SETTING = "toma_pet_alert_enabled"
    PERSISTENT_SETTING = "toma_pet_persistent_enabled"

    def __init__(self, store, open_calendar, open_quick_memo):
        self.store = store
        self._open_calendar = open_calendar
        self._open_quick_memo = open_quick_memo
        self.window: TomaPetWindow | None = None

    @staticmethod
    def _bool(value: str, default: bool) -> bool:
        normalized = str(value).strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        return default

    @property
    def alert_enabled(self) -> bool:
        return self._bool(self.store.setting(self.ALERT_SETTING, "true"), True)

    @property
    def persistent_enabled(self) -> bool:
        return self._bool(self.store.setting(self.PERSISTENT_SETTING, "false"), False)

    @property
    def visible_window(self):
        return self.window if self.window is not None and self.window.isVisible() else None

    def start(self) -> None:
        self.apply_settings()

    def apply_settings(self) -> None:
        if self.persistent_enabled:
            self._ensure_window().show_persistent()
        elif self.window is not None:
            self.window.hide()

    def set_preferences(self, alert_enabled: bool, persistent_enabled: bool, *, reset_position: bool = False) -> None:
        self.store.set_setting(self.ALERT_SETTING, "true" if alert_enabled else "false")
        self.store.set_setting(self.PERSISTENT_SETTING, "true" if persistent_enabled else "false")
        if reset_position:
            self.store.set_setting("toma_pet_position", "")
            if self.window is not None:
                self.window.reset_position()
        self.apply_settings()

    def stop(self) -> None:
        if self.window is not None:
            self.window.stop()
            self.window = None

    def _ensure_window(self) -> TomaPetWindow:
        if self.window is None:
            self.window = TomaPetWindow(
                self.store.setting, self.store.set_setting,
                self._open_calendar, self._open_quick_memo,
            )
        return self.window
