"""Compact overlay showing only active, successfully registered shortcuts."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


GROUP_COMMON = "공통 단축키"
GROUP_CONTENT = "메모·일정"
GROUP_ACTIONS = "내가 만든 작업"
GROUPS = (GROUP_COMMON, GROUP_CONTENT, GROUP_ACTIONS)


@dataclass(frozen=True)
class ShortcutOverlayEntry:
    group: str
    label: str
    hotkey: str
    registered: bool = True
    active: bool = True
    target_kind: str = ""
    target_id: int | str | None = None


class ShortcutOverlay(QWidget):
    """Frameless popup with a scrollable, two-column shortcut summary."""

    item_activated = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("shortcutOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._listed_entries: list[ShortcutOverlayEntry] = []
        self.item_buttons: list[QPushButton] = []
        self._drag_offset: QPoint | None = None
        self._user_position: QPoint | None = None

        shell = QVBoxLayout(self)
        shell.setContentsMargins(12, 12, 12, 12)
        self.surface = QFrame()
        self.surface.setObjectName("shortcutOverlaySurface")
        shell.addWidget(self.surface)

        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(22, 18, 22, 16)
        surface_layout.setSpacing(12)
        self.header = QWidget()
        title_row = QHBoxLayout(self.header)
        title_row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("단축키 안내")
        title.setObjectName("shortcutOverlayTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_hint = QLabel("Esc로 닫기")
        close_hint.setObjectName("shortcutOverlayHint")
        title_row.addWidget(close_hint)
        surface_layout.addWidget(self.header)
        self._drag_widgets = (self.header, title, close_hint)
        for widget in self._drag_widgets:
            widget.setCursor(Qt.CursorShape.OpenHandCursor)
            widget.installEventFilter(self)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("shortcutOverlayScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.group_grid = QGridLayout(self.content)
        self.group_grid.setContentsMargins(0, 0, 0, 0)
        self.group_grid.setHorizontalSpacing(12)
        self.group_grid.setVerticalSpacing(12)
        self.group_grid.setColumnStretch(0, 1)
        self.group_grid.setColumnStretch(1, 1)
        self.scroll.setWidget(self.content)
        surface_layout.addWidget(self.scroll, 1)

        self.failure_label = QLabel("")
        self.failure_label.setObjectName("shortcutOverlayFailure")
        self.failure_label.setVisible(False)
        surface_layout.addWidget(self.failure_label)

        self.setStyleSheet("""
            QFrame#shortcutOverlaySurface {
                background: rgba(248, 250, 252, 244);
                border: 1px solid rgba(148, 163, 184, 180);
                border-radius: 14px;
            }
            QLabel#shortcutOverlayTitle {
                color: #172033; font-size: 19px; font-weight: 700;
            }
            QLabel#shortcutOverlayHint { color: #64748b; font-size: 11px; }
            QScrollArea#shortcutOverlayScroll { background: transparent; }
            QScrollArea#shortcutOverlayScroll > QWidget > QWidget { background: transparent; }
            QFrame#shortcutGroupCard {
                background: rgba(255, 255, 255, 228);
                border: 1px solid #dbe3ef; border-radius: 10px;
            }
            QLabel#shortcutGroupTitle {
                color: #334155; font-size: 13px; font-weight: 700;
            }
            QLabel#shortcutEmpty { color: #94a3b8; padding: 7px 6px; }
            QPushButton#shortcutOverlayItem {
                min-height: 30px; padding: 4px 8px; text-align: left;
                color: #172033; background: transparent; border: 0;
                border-radius: 6px;
            }
            QPushButton#shortcutOverlayItem:hover { background: #eef4ff; }
            QLabel#shortcutOverlayFailure {
                color: #b45309; background: #fff7ed; border: 1px solid #fed7aa;
                border-radius: 7px; padding: 7px 10px;
            }
        """)

    @property
    def listed_entries(self) -> tuple[ShortcutOverlayEntry, ...]:
        return tuple(self._listed_entries)

    def set_entries(
        self,
        entries,
        *,
        failure_count: int | None = None,
    ) -> None:
        all_entries = [entry for entry in entries if isinstance(entry, ShortcutOverlayEntry)]
        self._listed_entries = [
            entry for entry in all_entries
            if entry.active and entry.registered and bool(entry.hotkey)
        ]
        failed = (
            sum(1 for entry in all_entries if entry.active and not entry.registered)
            if failure_count is None else max(0, int(failure_count))
        )
        self._clear_group_grid()
        self.item_buttons = []
        for index, group in enumerate(GROUPS):
            card = self._group_card(
                group,
                [entry for entry in self._listed_entries if entry.group == group],
            )
            self.group_grid.addWidget(card, index // 2, index % 2)
        self.group_grid.setRowStretch(2, 1)
        self.failure_label.setText(f"등록 실패 {failed}개" if failed else "")
        self.failure_label.setVisible(bool(failed))

    def open_overlay(
        self,
        entries,
        *,
        failure_count: int | None = None,
        excluded_app: bool = False,
        recording: bool = False,
        playback: bool = False,
        available_geometry: QRect | None = None,
    ) -> bool:
        if self.isVisible() or excluded_app or recording or playback:
            return False
        self.set_entries(entries, failure_count=failure_count)
        self._show_centered(available_geometry)
        return True

    def _show_centered(self, available_geometry: QRect | None = None) -> None:
        geometry = available_geometry
        if geometry is None:
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            geometry = screen.availableGeometry() if screen is not None else QRect(0, 0, 900, 650)
        margin = 24
        width = min(900, max(320, geometry.width() - margin * 2))
        height = min(650, max(260, geometry.height() - margin * 2))
        width = min(width, geometry.width())
        height = min(height, geometry.height())
        self.resize(width, height)
        centered = QPoint(
            geometry.left() + (geometry.width() - width) // 2,
            geometry.top() + (geometry.height() - height) // 2,
        )
        self.move(self._bounded_position(self._user_position or centered, geometry))
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _bounded_position(self, position: QPoint, bounds: QRect) -> QPoint:
        return QPoint(
            max(bounds.left(), min(position.x(), bounds.right() - self.width() + 1)),
            max(bounds.top(), min(position.y(), bounds.bottom() - self.height() + 1)),
        )

    def eventFilter(self, watched, event) -> bool:
        if watched in self._drag_widgets:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                screen = QGuiApplication.screenAt(event.globalPosition().toPoint()) or self.screen()
                bounds = screen.availableGeometry() if screen else QRect(0, 0, 900, 650)
                self.move(self._bounded_position(event.globalPosition().toPoint() - self._drag_offset, bounds))
                self._user_position = self.pos()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._drag_offset is not None:
                self._drag_offset = None
                self._user_position = self.pos()
                return True
        return super().eventFilter(watched, event)

    def _group_card(self, group: str, entries: list[ShortcutOverlayEntry]) -> QFrame:
        card = QFrame()
        card.setObjectName("shortcutGroupCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(3)
        title = QLabel(group)
        title.setObjectName("shortcutGroupTitle")
        layout.addWidget(title)
        if not entries:
            empty = QLabel("등록된 단축키 없음")
            empty.setObjectName("shortcutEmpty")
            layout.addWidget(empty)
        for entry in entries:
            button = QPushButton(f"{entry.label}    {entry.hotkey}")
            button.setObjectName("shortcutOverlayItem")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setProperty("shortcutGroup", group)
            button.clicked.connect(lambda _checked=False, item=entry: self._choose(item))
            layout.addWidget(button)
            self.item_buttons.append(button)
        layout.addStretch(1)
        return card

    def _choose(self, entry: ShortcutOverlayEntry) -> None:
        self.hide()
        self.item_activated.emit(entry)

    def _clear_group_grid(self) -> None:
        while self.group_grid.count():
            item = self.group_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            self.hide()
        return super().event(event)
