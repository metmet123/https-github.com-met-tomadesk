from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QFrame, QMainWindow, QScrollArea

from .editor import MemoEditor
from .text_format_toolbar import TextFormatToolbar
from .window_geometry import WindowGeometryController


class StandaloneMemoEditorWindow(QMainWindow):
    """Native resizable window containing only the memo editor pane."""

    GEOMETRY_KEY = "standalone_memo_editor_geometry"
    WIDTH_MIGRATION_KEY = "standalone_memo_editor_compact_width_v1"
    DEFAULT_WIDTH = 680 - TextFormatToolbar.WIDTH_REDUCTION
    MINIMUM_WIDTH = 560 - TextFormatToolbar.WIDTH_REDUCTION

    def __init__(self, store, owner):
        super().__init__(None, Qt.WindowType.Window)
        self.store = store
        self.owner = owner
        self.note_id: int | None = None
        self._shutting_down = False
        self.setWindowTitle("메모 편집")
        icon = QGuiApplication.instance().windowIcon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.setMinimumSize(self.MINIMUM_WIDTH, 640)
        self._set_default_geometry()
        had_saved_geometry = bool(store.setting(self.GEOMETRY_KEY, ""))

        self.editor = MemoEditor(store)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("standaloneMemoEditorScroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setWidget(self.editor)
        self.setCentralWidget(self.scroll)
        self.editor.save_requested.connect(self._save)
        self.editor.delete_requested.connect(self._delete)
        self.editor.reminder_save_requested.connect(self._save_reminder)
        self.editor.reminder_clear_requested.connect(self._clear_reminder)
        self.editor.deadline_requested.connect(
            lambda: self.owner.edit_deadline(self.note_id, self)
        )
        self.geometry_controller = WindowGeometryController(
            self, store.setting, store.set_setting, self.GEOMETRY_KEY,
        )
        self.geometry_controller.restore()
        self._migrate_saved_width(had_saved_geometry)

    def open_note(self, note_id: int) -> None:
        row = self.store.note(int(note_id))
        if row is None:
            return
        source_window = self.owner.window()
        if source_window is not self and source_window.styleSheet():
            self.setStyleSheet(source_window.styleSheet())
        if self.note_id is not None and self.note_id != int(note_id):
            self.editor.flush_pending_save()
        self.note_id = int(note_id)
        self.editor.set_note(row)
        self.setWindowTitle(f"메모 편집 · {row['title']}")
        state = self.windowState() & ~Qt.WindowState.WindowMinimized
        self.setWindowState(state | Qt.WindowState.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()
        self.editor.content_edit.setFocus()

    def closeEvent(self, event) -> None:
        self.editor.flush_pending_save()
        self.geometry_controller.save()
        if self._shutting_down:
            event.accept()
            return
        event.ignore()
        self.hide()

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self.editor.flush_pending_save()
        self.geometry_controller.save()
        self.editor.shutdown()
        self.close()
        self.deleteLater()

    def _save(self, values: dict) -> None:
        if self.note_id is not None:
            self.owner.save_editor_values(self.note_id, values, self.editor)

    def _save_reminder(self, values: dict) -> None:
        if self.note_id is not None:
            self.owner.save_reminder_for(self.note_id, self.editor, values, self)

    def _clear_reminder(self, reminder_id) -> None:
        if self.note_id is not None:
            self.owner.clear_reminder_for(self.note_id, reminder_id, self)

    def _delete(self) -> None:
        if self.note_id is not None and self.owner.delete_note_by_id(self.note_id, self):
            self.note_id = None
            self.hide()

    def _set_default_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(self.DEFAULT_WIDTH, 880)
            return
        available = screen.availableGeometry()
        width = min(self.DEFAULT_WIDTH, available.width())
        height = min(880, available.height())
        self.resize(width, height)
        self.move(
            available.x() + max(0, (available.width() - width) // 2),
            available.y() + max(0, (available.height() - height) // 2),
        )

    def _migrate_saved_width(self, had_saved_geometry: bool) -> None:
        if self.store.setting(self.WIDTH_MIGRATION_KEY, "") == "1":
            return
        if had_saved_geometry:
            self.resize(max(self.MINIMUM_WIDTH, self.width() - TextFormatToolbar.WIDTH_REDUCTION), self.height())
        self.store.set_setting(self.WIDTH_MIGRATION_KEY, "1")
