import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from datetime import date, datetime, timedelta

from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QLabel, QMessageBox, QScrollArea, QSizePolicy, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

from .editor import MemoEditor
from .deadline import DeadlineDialog
from .excel_export import display_datetime, export_table_xlsx
from .memo_list import MemoListPanel
from .monthly_dialog import MonthlyRuleDialog
from .monthly_rule import (
    UNCHECKED_PREFIX, describe, is_due, month_key, parse_rule, reset_checklist,
    suggest_rules,
)

# Titles the user declined; kept so a spotted repeat is offered only once.
SUGGEST_DISMISSED_SETTING = "monthly_suggest_dismissed"
from .postit import PostitWindow
from .schedule_postit import SchedulePostitWindow
from .calendar import CalendarPanel
from .calendar_dialog import CalendarDialog
from .reminder_history import ReminderHistoryPanel
from .rich_text import plain_text_from_content
from .standalone_editor import StandaloneMemoEditorWindow
from .text_format_toolbar import TextFormatToolbar
from .today_summary import TodaySummaryPanel
from .panel_reminder_actions import PanelReminderActionsMixin


class AlertNotesPanel(PanelReminderActionsMixin, QWidget):
    shortcuts_changed = pyqtSignal()
    HORIZONTAL_BREAKPOINT = 1080
    LIST_MINIMUM_WIDTH = 480
    EDITOR_MINIMUM_WIDTH = 560 - TextFormatToolbar.WIDTH_REDUCTION
    SPLITTER_RATIO_SETTING = "memo_editor_splitter_horizontal_ratios"
    STACKED_LIST_ROWS = 4
    STACKED_LIST_MAX_SHARE = 0.55
    VISIT_HISTORY_LIMIT = 30
    # 최근 본 메모.  목록 위 칩으로 세 개까지 보이고, 프로그램을 껐다 켜도 남는다.
    RECENT_SETTING = "memo_recent_notes"
    RECENT_LIMIT = 12
    # 상태 한 줄의 높이.  38px 은 글자 위아래로 빈 자리가 너무 넓었다.
    STATUS_HEIGHT = 22
    TAB_STATUS_HINTS = (
        "메모를 선택하거나 새 메모를 만들어 주세요.",
        "날짜를 클릭하면 일정을 추가하고, 일정을 클릭하면 편집합니다.",
        "예정된 알림을 확인하고 완료·미루기·건너뛰기를 처리할 수 있습니다.",
    )

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._restoring_splitter = False
        self._horizontal_splitter_restored = False
        self.hotkey_validator = None
        self.current_id: int | None = None
        # Esc 로 돌아갈 길.  페이지를 타고 들어간 만큼만 얕게 쌓는다.
        self.visit_history: list[int] = []
        self.postits: dict[int, PostitWindow] = {}
        self.standalone_window: StandaloneMemoEditorWindow | None = None
        self.splitter = QSplitter()
        self.splitter.setObjectName("memoEditorSplitter")
        self.splitter.setHandleWidth(7)
        self.list_panel = MemoListPanel(store)
        self.editor = MemoEditor(self.store)
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setObjectName("memoEditorScroll")
        self.editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor_scroll.setWidget(self.editor)
        # The third pane used to be an empty spacer; it now carries the day summary
        # so extra window width shows something instead of grey.
        self.editor_remainder = TodaySummaryPanel(self.store)
        self.editor_remainder.setObjectName("memoEditorRemainder")
        self.editor_remainder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.summary = self.editor_remainder
        self.schedule_postit = SchedulePostitWindow(self.store, self)
        self.editor_remainder.monthly_suggestion_accepted.connect(self.accept_monthly_suggestion)
        self.editor_remainder.monthly_suggestion_dismissed.connect(self.dismiss_monthly_suggestion)
        self.splitter.addWidget(self.list_panel)
        self.splitter.addWidget(self.editor_scroll)
        self.splitter.addWidget(self.editor_remainder)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setStretchFactor(2, 1)
        self.list_panel.setMinimumWidth(self._list_minimum_width())
        self.editor_scroll.setMinimumWidth(self.EDITOR_MINIMUM_WIDTH)
        self.splitter.setSizes([700, 640, 560])
        self.splitter.handle(1).setAccessibleName("메모 목록과 편집 영역 너비 조절선")
        self.splitter.handle(2).setAccessibleName("메모 편집 영역 너비 조절선")
        self.calendar = CalendarPanel(self.store)
        self.reminder_history = ReminderHistoryPanel(self.store)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("alertNotesTabs")
        self.tabs.addTab(self.splitter, "메모 편집")
        self.tabs.addTab(self.calendar, "캘린더")
        self.tabs.addTab(self.reminder_history, "알림내역")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # 아래쪽은 상태 한 줄이면 된다.  남는 자리는 모두 탭 안 내용에 준다.
        layout.setSpacing(2)
        layout.addWidget(self.tabs, 1)
        self.status_label = QLabel(self.TAB_STATUS_HINTS[0])
        self.status_label.setObjectName("memoStatus")
        self.status_label.setProperty("level", "info")
        self.status_label.setFixedHeight(self.STATUS_HEIGHT)
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self.status_label)
        # 편집만 크게 보는 모드.  목록과 오늘 요약을 잠시 접는다.
        self.editor_fullscreen = False
        self.fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self.fullscreen_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.fullscreen_shortcut.activated.connect(self.toggle_editor_fullscreen)
        self.editor.fullscreen_requested.connect(self.toggle_editor_fullscreen)
        self.editor.sidebar_requested.connect(self.toggle_memo_list)
        self.sidebar_shortcut = QShortcut(QKeySequence("Ctrl+\\"), self)
        self.sidebar_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.sidebar_shortcut.activated.connect(self.toggle_memo_list)
        self.memo_list_hidden = False
        # Esc 로 왔던 메모로 돌아간다.  메모 편집 구역 안에서만 듣는다.
        self.back_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.editor)
        self.back_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.back_shortcut.activated.connect(self.go_back)
        self._connect()
        self.refresh()
        self.restore_postits()

    def _connect(self) -> None:
        self.list_panel.search.textChanged.connect(self.refresh)
        self.list_panel.note_selected.connect(self.select_note)
        self.list_panel.new_requested.connect(self.create_note)
        self.list_panel.export_requested.connect(self.export_memos)
        self.list_panel.delete_requested.connect(self.delete_selected_notes)
        self.list_panel.note_moved.connect(self.move_note)
        self.list_panel.child_requested.connect(self.create_child_note)
        self.list_panel.pin_toggled.connect(self.set_note_pinned)
        self.list_panel.recent_chosen.connect(self.show_note)
        self.editor.note_open_requested.connect(self.show_note)
        self.editor.page_created.connect(self._page_created)
        self.editor.page_removed.connect(self._page_removed)
        self.editor.save_requested.connect(self.save_note)
        self.editor.delete_requested.connect(self.delete_note)
        self.editor.reminder_save_requested.connect(self.save_reminder)
        self.editor.reminder_clear_requested.connect(self.clear_reminder)
        self.editor.deadline_requested.connect(lambda: self.edit_deadline(self.current_id, self.editor))
        self.editor.monthly_requested.connect(lambda: self.edit_monthly_rule(self.current_id, self.editor))
        self.calendar.note_open_requested.connect(self.show_note)
        self.calendar.note_created.connect(self._calendar_note_created)
        self.calendar.schedule_changed.connect(self.shortcuts_changed)
        self.calendar.fullscreen_button.clicked.connect(self._open_calendar_dialog)
        self.reminder_history.reminder_edit_requested.connect(self.show_reminder)
        self.reminder_history.note_open_requested.connect(self._open_note_from_history)
        self.reminder_history.changed.connect(self._history_changed)
        self.reminder_history.memo_tab_requested.connect(lambda: self.tabs.setCurrentIndex(0))
        self.splitter.splitterMoved.connect(self._save_horizontal_splitter_ratios)
        self.tabs.currentChanged.connect(self._show_tab_status_hint)
        self.summary.note_open_requested.connect(self.show_note)
        self.summary.schedule_open_requested.connect(self.show_schedule)
        self.schedule_postit.changed.connect(self._schedule_postit_changed)

    def _schedule_postit_changed(self) -> None:
        self.refresh()
        self.calendar.refresh()

    def toggle_schedule_postit(self) -> None:
        if self.schedule_postit.isVisible():
            self.schedule_postit.hide()
            return
        self.schedule_postit.refresh()
        self.schedule_postit.show()
        self.schedule_postit.raise_()
        self.schedule_postit.activateWindow()

    def apply_schedule_postit_preferences(self, preferences) -> None:
        self.schedule_postit.apply_preferences(preferences)

    def _horizontal_splitter_ratios(self) -> list[float]:
        raw_value = self.store.setting(self.SPLITTER_RATIO_SETTING, "")
        try:
            values = [float(value) for value in json.loads(raw_value)]
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        if len(values) != 3 or any(value < 0 for value in values) or sum(values) <= 0:
            values = [700.0, 640.0, 560.0]
        total = sum(values)
        return [value / total for value in values]

    def _restore_horizontal_splitter_ratios(self) -> None:
        if self.splitter.orientation() != Qt.Orientation.Horizontal:
            return
        ratios = self._horizontal_splitter_ratios()
        available = self.splitter.width() - (self.splitter.handleWidth() * 2)
        if available < self.LIST_MINIMUM_WIDTH + self.EDITOR_MINIMUM_WIDTH:
            return
        self._restoring_splitter = True
        try:
            self.splitter.setSizes([max(1, round(ratio * available)) for ratio in ratios])
        finally:
            self._restoring_splitter = False
        self._horizontal_splitter_restored = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._horizontal_splitter_restored:
            self._restore_horizontal_splitter_ratios()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._horizontal_splitter_restored:
            self._restore_horizontal_splitter_ratios()

    def _save_horizontal_splitter_ratios(self, *_args) -> None:
        if self._restoring_splitter or self.splitter.orientation() != Qt.Orientation.Horizontal:
            return
        sizes = self.splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        self.store.set_setting(
            self.SPLITTER_RATIO_SETTING,
            json.dumps([round(size / total, 6) for size in sizes]),
        )

    def _open_calendar_dialog(self) -> None:
        dialog = CalendarDialog(self.store, self)
        dialog.calendar.note_open_requested.connect(lambda note_id: (dialog.accept(), self.show_note(note_id)))
        dialog.calendar.note_created.connect(lambda note_id: (dialog.accept(), self._calendar_note_created(note_id)))
        dialog.setWindowState(dialog.windowState() | Qt.WindowState.WindowMaximized)
        dialog.exec()
        self.calendar.refresh()

    def refresh(self, *_args) -> None:
        rows = self.store.notes(self.list_panel.search.text())
        ids = {int(row["id"]) for row in rows}
        if self.current_id not in ids:
            self.current_id = int(rows[0]["id"]) if rows else None
        self.list_panel.set_rows(rows, self.current_id)
        if self.current_id is None:
            self.editor.set_note(None)
        else:
            self.list_panel.select_id(self.current_id)
            self.editor.set_note(self.store.note(self.current_id))
        self.calendar.refresh()
        self.reminder_history.refresh()
        self.summary.refresh()
        self.refresh_recent_chips()
        self.refresh_monthly_suggestion()

    def _open_note_from_history(self, note_id: int) -> None:
        self.tabs.setCurrentIndex(0)
        self.show_note(note_id)

    def _history_changed(self) -> None:
        self.refresh()
        self.shortcuts_changed.emit()

    def _calendar_note_created(self, note_id: int) -> None:
        self.current_id = int(note_id)
        self.refresh()
        self.tabs.setCurrentIndex(0)
        self.show_note(note_id)

    def create_note(self) -> None:
        self.current_id = self.store.create_note()
        self.list_panel.search.clear()
        self.refresh()
        self.calendar.refresh()
        self.editor.title_edit.setFocus()
        self.editor.title_edit.selectAll()

    def select_note(self, note_id: int) -> None:
        self._remember_visit(int(note_id))
        self._remember_recent(int(note_id))
        self.current_id = note_id
        self.editor.set_note(self.store.note(note_id))
        self.refresh_recent_chips()

    def show_note(self, note_id: int) -> None:
        self.list_panel.search.clear()
        self._remember_visit(int(note_id))
        self._remember_recent(int(note_id))
        self.current_id = int(note_id)
        self.refresh()
        self.calendar.refresh()
        self.editor.content_edit.setFocus()

    def show_schedule(self, item_id: int) -> None:
        self.tabs.setCurrentIndex(1)
        self.calendar._open_schedule(item_id)

    def show_today(self) -> None:
        self.tabs.setCurrentIndex(1)
        self.calendar._set_mode("day")
        self.calendar._today()

    def toggle_note_postit(self, note_id: int) -> None:
        window = self.postits.get(note_id)
        if window is not None and window.isVisible():
            self._hide_postit(note_id)
            return
        note = self.store.note(note_id)
        if note is None:
            return
        if not note["postit"]:
            self.store.update_note(note_id, postit=True, postit_visible=True)
            note = self.store.note(note_id)
        else:
            self.store.update_note(note_id, postit_visible=True)
            note = self.store.note(note_id)
        self._open_postit(note, show=True)

    def save_note(self, values: dict | None = None) -> None:
        try:
            resolved = values or self.editor.values()
        except Exception as exc:
            QMessageBox.warning(self, "메모 단축키", str(exc))
            self.editor.mark_saved(False)
            return
        self.save_editor_values(self.current_id, resolved, self.editor, allow_create=True)

    def save_editor_values(
        self, note_id: int | None, values: dict, editor: MemoEditor, allow_create: bool = False,
    ) -> int | None:
        target_id = note_id
        try:
            if values.get("hotkey") and self.hotkey_validator is not None:
                self.hotkey_validator(values["hotkey"], note_id=target_id)
        except Exception as exc:
            QMessageBox.warning(editor, "메모 저장", str(exc))
            editor.mark_saved(False)
            return None
        if target_id is None:
            if not allow_create or not editor.has_meaningful_content():
                editor.mark_draft()
                return None
            resolved_title = str(values.get("title") or "").strip() or "새 메모"
            values = dict(values)
            values["title"] = resolved_title
            target_id = self.store.create_note(resolved_title, str(values.get("content") or ""))
            self.current_id = target_id
            blocked = self.list_panel.search.blockSignals(True)
            self.list_panel.search.clear()
            self.list_panel.search.blockSignals(blocked)
            editor.bind_note_id(target_id, resolved_title)
        existing = self.store.note(target_id)
        previous_hotkey = str(existing["hotkey"] or "") if existing is not None else ""
        previous_hotkey_action = str(existing["hotkey_action"] or "") if existing is not None else ""
        was_postit = bool(existing["postit"]) if existing is not None else False
        values = dict(values)
        wants_postit = bool(values.get("postit", was_postit))
        if wants_postit and not was_postit:
            values.update(postit_visible=True, postit_startup=True)
        elif not wants_postit:
            values.update(postit_visible=False, postit_startup=False)
        try:
            self.store.update_note(target_id, **values)
        except Exception as exc:
            QMessageBox.warning(editor, "메모 저장", str(exc))
            editor.mark_saved(False)
            return None
        self._sync_postit(target_id)
        rows = self.store.notes(self.list_panel.search.text())
        self.list_panel.set_rows(rows, self.current_id)
        editor.mark_saved(True)
        if (
            editor is not self.editor and self.current_id == target_id
            and not self.editor.save_timer.isActive()
            and not self.editor.title_edit.hasFocus() and not self.editor.content_edit.hasFocus()
        ):
            self.editor.set_note(self.store.note(target_id))
        self._status("메모를 저장했습니다.", "success")
        if (
            str(values.get("hotkey") or "") != previous_hotkey
            or str(values.get("hotkey_action") or "") != previous_hotkey_action
        ):
            self.shortcuts_changed.emit()
        return target_id

    def delete_note(self) -> None:
        self.delete_note_by_id(self.current_id, self)

    def delete_note_by_id(self, note_id: int | None, parent=None) -> bool:
        if note_id is None:
            return False
        if QMessageBox.question(
            parent or self, "메모 삭제", "선택한 메모와 연결된 알림을 삭제할까요?",
        ) != QMessageBox.StandardButton.Yes:
            return False
        self._close_postit(note_id)
        self.store.delete_note(note_id)
        if self.current_id == note_id:
            self.current_id = None
        self.refresh()
        self._status("메모를 삭제했습니다.", "success")
        self.shortcuts_changed.emit()
        return True

    def toggle_memo_list(self, on: bool | None = None) -> bool:
        """메모 목록만 접었다 편다.  오늘 요약은 그대로 둔다."""
        wanted = (not self.memo_list_hidden) if on is None else bool(on)
        if wanted == self.memo_list_hidden:
            return self.memo_list_hidden
        self.memo_list_hidden = wanted
        if wanted:
            self._sizes_before_hiding = self.splitter.sizes()
        self.list_panel.setVisible(not wanted)
        self.editor.set_wide_body(wanted)
        if wanted:
            # 나눔선은 감춘 칸의 폭을 스스로 나눠 주지 않는다.  비운 자리를
            # 편집 구역에 그대로 얹는다.
            sizes = list(self._sizes_before_hiding)
            self.splitter.setSizes([0, sizes[1] + sizes[0], sizes[2]])
        elif getattr(self, "_sizes_before_hiding", None):
            self.splitter.setSizes(self._sizes_before_hiding)
        self._status(
            "메모 목록을 접었습니다.  Ctrl+백슬래시 로 다시 폅니다." if wanted
            else "메모 목록을 폈습니다.",
            "info",
        )
        return self.memo_list_hidden

    def toggle_editor_fullscreen(self, on: bool | None = None) -> bool:
        """편집 구역만 크게 본다.  다시 부르면 원래대로 돌아온다."""
        wanted = (not self.editor_fullscreen) if on is None else bool(on)
        if wanted == self.editor_fullscreen:
            return self.editor_fullscreen
        self.editor_fullscreen = wanted
        if wanted:
            self._saved_splitter_sizes = self.splitter.sizes()
        self.list_panel.setVisible(not wanted)
        self.editor_remainder.setVisible(not wanted)
        self.tabs.tabBar().setVisible(not wanted)
        self.editor.set_fullscreen(wanted)
        if not wanted and getattr(self, "_saved_splitter_sizes", None):
            self.splitter.setSizes(self._saved_splitter_sizes)
        self._status(
            "편집 구역만 크게 봅니다.  F11 로 돌아옵니다." if wanted
            else "원래 화면으로 돌아왔습니다.",
            "info",
        )
        self.editor.content_edit.setFocus()
        return self.editor_fullscreen

    def _recent_ids(self) -> list[int]:
        raw = self.store.setting(self.RECENT_SETTING, "")
        found = []
        for piece in str(raw).split(","):
            piece = piece.strip()
            if piece.isdigit() and int(piece) not in found:
                found.append(int(piece))
        return found

    def _remember_recent(self, note_id: int | None) -> None:
        """방금 본 메모를 맨 앞으로 올린다.  본문에 넣은 페이지는 빼 둔다."""
        if note_id is None:
            return
        row = self.store.note(int(note_id))
        if row is None or bool(row["embedded"]):
            return
        found = [value for value in self._recent_ids() if value != int(note_id)]
        found.insert(0, int(note_id))
        del found[self.RECENT_LIMIT:]
        self.store.set_setting(self.RECENT_SETTING, ",".join(str(value) for value in found))

    def refresh_recent_chips(self) -> None:
        """지금 보고 있는 메모를 뺀 최근 목록을 칩으로 넘긴다."""
        chips = []
        for note_id in self._recent_ids():
            if self.current_id is not None and note_id == int(self.current_id):
                continue
            row = self.store.note(note_id)
            if row is None or bool(row["embedded"]):
                continue
            chips.append((note_id, str(row["title"] or "")))
            if len(chips) >= self.list_panel.RECENT_CHIPS:
                break
        self.list_panel.set_recent(chips)

    def _remember_visit(self, note_id: int | None) -> None:
        """지금 보던 메모를 되돌아갈 자리로 쌓아 둔다."""
        current = self.current_id
        if current is None or current == note_id:
            return
        if self.visit_history and self.visit_history[-1] == current:
            return
        self.visit_history.append(int(current))
        del self.visit_history[:-self.VISIT_HISTORY_LIMIT]

    def go_back(self) -> bool:
        """Esc.  페이지에서 왔던 메모로 돌아간다.

        온 길이 없으면 한 층 위 메모로 올라간다.  둘 다 없으면 아무 일도 없다.
        """
        if self.editor.content_edit.close_insert_popup():
            # 삽입 메뉴가 떠 있었다.  Esc 는 그 메뉴를 닫는 것으로 끝난다.
            return False
        while self.visit_history:
            note_id = self.visit_history.pop()
            if self.store.note(note_id) is not None:
                self._open_without_history(note_id)
                return True
        parent = None
        if self.current_id is not None:
            row = self.store.note(self.current_id)
            parent = int(row["parent_id"] or 0) if row is not None else 0
        if parent and self.store.note(parent) is not None:
            self._open_without_history(parent)
            return True
        return False

    def _open_without_history(self, note_id: int) -> None:
        self.current_id = int(note_id)
        self._remember_recent(int(note_id))
        self.refresh()
        self.calendar.refresh()
        self.editor.content_edit.setFocus()

    def set_note_pinned(self, note_id: int, pinned: bool) -> None:
        """목록에서 오른쪽 단추로 고정을 켜고 끈다."""
        self.store.update_note(int(note_id), pinned=bool(pinned))
        self.refresh()
        self.list_panel.select_id(int(note_id))
        self._status(
            "메모를 목록 맨 위에 고정했습니다." if pinned else "고정을 풀었습니다.",
            "success",
        )

    def create_child_note(self, parent_id: int) -> None:
        """목록에서 + 를 누르면 그 메모 안에 새 메모를 만든다."""
        note_id = self.store.create_child_note(int(parent_id))
        self.current_id = note_id
        self.list_panel.search.clear()
        self.refresh()
        self.list_panel.expand_to(note_id)
        self.list_panel.select_id(note_id)
        self.editor.title_edit.setFocus()
        self.editor.title_edit.selectAll()
        self._status("메모 안에 새 메모를 만들었습니다. 제목을 적어 주세요.", "success")
        self.shortcuts_changed.emit()

    def _page_removed(self, _note_id: int) -> None:
        """본문에서 페이지 줄을 지웠을 때.  그 페이지도 휴지통으로 갔다."""
        self._status("페이지를 휴지통으로 옮겼습니다. 되돌리기로 되살릴 수 있습니다.", "info")
        self.shortcuts_changed.emit()

    def _page_created(self, _note_id: int) -> None:
        """본문에 페이지 줄을 넣었을 때.

        본문 페이지는 목록에 내놓지 않으므로 목록은 그대로 두고, 본문만 저장한다.
        """
        self.editor.flush_pending_save()
        self._status("메모 안에 페이지를 넣었습니다. 줄을 누르면 열립니다.", "success")
        self.shortcuts_changed.emit()

    def move_note(self, note_id: int, parent_id: int, position: int) -> None:
        """목록에서 끌어 놓은 자리로 메모를 옮긴다."""
        if not self.store.set_note_parent(note_id, parent_id, position):
            self._status("메모를 자기 자신이나 그 안의 메모 밑으로는 옮길 수 없습니다.", "warning")
            return
        self.refresh()
        if parent_id:
            self.list_panel.expand_to(note_id)
        self.list_panel.select_id(note_id)
        self._status("메모를 옮겼습니다.", "success")
        self.shortcuts_changed.emit()

    def delete_selected_notes(self) -> None:
        # Delete works on the checked rows, or on the row in hand when none are
        # checked, so the Delete key does what the selection looks like it means.
        ids = self.list_panel.deletion_ids()
        if not ids:
            QMessageBox.information(self, "메모 삭제", "삭제할 메모를 체크하거나 선택해 주세요.")
            return
        # 부모를 지우면 그 안의 메모도 함께 간다.  몇 건인지 먼저 알려 준다.
        bundle = set(ids)
        for note_id in ids:
            bundle.update(self.store.note_descendants(note_id))
        extra = len(bundle) - len(ids)
        question = f"메모 {len(ids)}건과 연결된 알림을 휴지통으로 옮길까요?"
        if extra > 0:
            question = (
                f"메모 {len(ids)}건과 그 안의 메모 {extra}건, 연결된 알림을 "
                "휴지통으로 옮길까요?\n안의 메모도 함께 되살릴 수 있습니다."
            )
        if QMessageBox.question(self, "메모 삭제", question) != QMessageBox.StandardButton.Yes:
            return
        for note_id in ids:
            self._close_postit(note_id)
            self.store.delete_note(note_id)
        if self.current_id in ids:
            self.current_id = None
        if self.standalone_window is not None and self.standalone_window.note_id in ids:
            self.standalone_window.note_id = None
            self.standalone_window.hide()
        self.refresh()
        self._status(f"메모 {len(ids)}건을 휴지통으로 옮겼습니다.", "success")
        self.shortcuts_changed.emit()

    def export_memos(self) -> None:
        ids = self.list_panel.export_ids()
        if not ids:
            QMessageBox.information(self, "Excel 내보내기", "내보낼 메모가 없습니다.")
            return
        rows = [self.list_panel.rows_by_id[note_id] for note_id in ids if note_id in self.list_panel.rows_by_id]
        default = self.store.path.parent / f"메모목록_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "메모 목록 Excel 내보내기", str(default), "Excel (*.xlsx)")
        if not path:
            return
        output_rows = [
            [
                index, "포스트잇" if row["postit"] else "일반", str(row["title"]),
                display_datetime(row["updated_at"]), plain_text_from_content(str(row["content"])),
            ]
            for index, row in enumerate(rows, start=1)
        ]
        try:
            output = export_table_xlsx(
                "메모목록", ["번호", "표시", "제목", "수정 시간", "내용"], output_rows, path,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Excel 내보내기 실패", str(exc))
            return
        QMessageBox.information(self, "Excel 내보내기 완료", str(output))

    def open_standalone_note(self, note_id: int) -> None:
        self.editor.flush_pending_save()
        if self.standalone_window is None:
            self.standalone_window = StandaloneMemoEditorWindow(self.store, self)
        self.standalone_window.open_note(note_id)

    def set_auto_save_enabled(self, enabled: bool) -> None:
        """Apply the global memo save mode to every open full memo editor."""
        self.editor.set_auto_save_enabled(enabled)
        if self.standalone_window is not None:
            self.standalone_window.editor.set_auto_save_enabled(enabled)

    def edit_monthly_rule(self, note_id: int | None, parent=None) -> None:
        if note_id is None:
            QMessageBox.information(parent or self, "매달 반복", "메모를 먼저 저장해 주세요.")
            return
        note = self.store.note(note_id)
        if note is None:
            return
        dialog = MonthlyRuleDialog(note, parent or self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        if dialog.clear_requested:
            self.store.set_monthly_rule(note_id, None)
            message = "매달 반복을 해제했습니다."
        else:
            rule = dialog.rule()
            self.store.set_monthly_rule(note_id, rule)
            message = f"{describe(rule)}에 포스트잇으로 띄웁니다."
        self.refresh()
        self._status(message, "success")

    def monthly_suggestions(self, today: date | None = None) -> list[dict]:
        """Repeats the user already makes by hand, offered — never applied."""
        today = today or date.today()
        rows = []
        try:
            items = self.store.schedules.items_for_range(
                (today.replace(year=today.year - 1)).strftime("%Y%m%d0000"),
                today.strftime("%Y%m%d2359"),
            )
        except Exception:
            items = []
        for item in items:
            stamp = str(item.get("display_start_at") or item.get("start_at") or "")
            if len(stamp) >= 8:
                try:
                    rows.append((item.get("title"), date(
                        int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])
                    )))
                except ValueError:
                    continue
        known = {
            str(row["title"] or "").strip()
            for row in self.store.monthly_notes()
        }
        known |= self._dismissed_suggestions()
        return [
            item for item in suggest_rules(rows, today) if item["title"] not in known
        ]

    def _dismissed_suggestions(self) -> set:
        """Titles the user waved off; asking again would just be nagging."""
        try:
            raw = json.loads(str(self.store.setting(SUGGEST_DISMISSED_SETTING, "[]")))
        except (TypeError, ValueError):
            return set()
        return {str(item).strip() for item in raw} if isinstance(raw, list) else set()

    def dismiss_monthly_suggestion(self, title: str) -> None:
        title = str(title or "").strip()
        if not title:
            return
        titles = sorted(self._dismissed_suggestions() | {title})
        self.store.set_setting(SUGGEST_DISMISSED_SETTING, json.dumps(titles, ensure_ascii=False))
        self.refresh_monthly_suggestion()
        self._status("이 제안은 다시 띄우지 않습니다.", "info")

    def accept_monthly_suggestion(self, suggestion: dict) -> int | None:
        """Turn the spotted repeat into a monthly checklist memo, ready to edit."""
        title = str((suggestion or {}).get("title") or "").strip()
        rule = parse_rule((suggestion or {}).get("rule"))
        if not title or rule is None:
            return None
        note_id = self.store.create_note(title, f"{UNCHECKED_PREFIX}{title}")
        self.store.set_monthly_rule(note_id, rule)
        self.current_id = int(note_id)
        self.refresh()
        self.tabs.setCurrentIndex(0)
        self.show_note(note_id)
        self._status(f"{describe(rule)}에 ‘{title}’ 포스트잇을 띄웁니다.", "success")
        return int(note_id)

    def refresh_monthly_suggestion(self) -> None:
        try:
            found = self.monthly_suggestions()
        except Exception:
            found = []
        self.summary.set_suggestion(found[0] if found else None)

    def apply_monthly_postits(self, today: date | None = None) -> list[int]:
        """Raise this month's recurring work as a fresh, unticked postit.

        Runs once per note per month: the checklist is reset and the note is
        pinned so the month's routine is on screen without being retyped.
        """
        today = today or date.today()
        month = month_key(today)
        raised: list[int] = []
        for row in self.store.monthly_notes():
            rule = parse_rule(str(row["monthly_rule"] or ""))
            if rule is None or not is_due(rule, today):
                continue
            if str(row["monthly_shown_for"] or "") == month:
                continue
            note_id = int(row["id"])
            self.store.update_note(
                note_id,
                content=reset_checklist(str(row["content"] or "")),
                postit=True, postit_visible=True, postit_startup=True,
            )
            self.store.mark_monthly_shown(note_id, month)
            self._open_postit(self.store.note(note_id), show=True)
            raised.append(note_id)
        if raised:
            self._arrange_compact_badges()
            self.refresh()
        return raised

    def restore_postits(self) -> None:
        for row in self.store.notes():
            if row["postit"] and row["postit_startup"]:
                self.store.update_note(int(row["id"]), postit_visible=True)
                self._open_postit(self.store.note(int(row["id"])), show=True)
        self._arrange_compact_badges()
        self.apply_monthly_postits()

    def _sync_postit(self, note_id: int) -> None:
        note = self.store.note(note_id)
        if note is None or not note["postit"]:
            self._close_postit(note_id)
        else:
            self._open_postit(note, show=bool(note["postit_visible"]))

    def _open_postit(self, note, show: bool = True) -> None:
        note_id = int(note["id"])
        window = self.postits.get(note_id)
        if window is None:
            window = PostitWindow(self.store, note)
            window.hide_requested.connect(self._hide_postit)
            window.unpin_requested.connect(self._unpin_postit)
            window.delete_requested.connect(lambda value: self.delete_note_by_id(value, window))
            window.new_requested.connect(self._create_postit_near)
            window.editor_requested.connect(self._open_postit_in_editor)
            window.reminder_requested.connect(self._open_postit_reminder)
            window.quick_reminder_requested.connect(self._set_postit_quick_reminder)
            window.deadline_requested.connect(lambda value: self.edit_deadline(value, window))
            window.cycle_requested.connect(self._cycle_postits)
            window.content_saved.connect(self._save_postit_content)
            window.properties_changed.connect(self._postit_properties_changed)
            window.display_mode_changed.connect(lambda _value: self._arrange_compact_badges())
            self.postits[note_id] = window
        else:
            window.update_note(note)
        if show:
            window.show()
            window.raise_()

    def _hide_postit(self, note_id: int) -> None:
        window = self.postits.get(note_id)
        if window is not None:
            window.flush_pending_save()
            window.hide()
        self.store.update_note(note_id, postit_visible=False)
        self.refresh()

    def _create_postit_near(self, source_id: int) -> None:
        source = self.postits.get(source_id)
        note_id = self.store.create_note("새 메모", "")
        self.store.update_note(
            note_id, postit=True, postit_visible=True, postit_startup=True,
        )
        self.current_id = note_id
        note = self.store.note(note_id)
        self._open_postit(note, show=True)
        target = self.postits.get(note_id)
        if source is not None and target is not None:
            target.move(source.x() + 28, source.y() + 28)
            target.geometry_controller.ensure_visible()
        if target is not None:
            target.memo.setFocus()
        self.refresh()

    def _open_postit_in_editor(self, note_id: int) -> None:
        self.tabs.setCurrentIndex(0)
        self.show_note(note_id)
        self.window().show()
        self.window().raise_()
        self.window().activateWindow()

    def _open_postit_reminder(self, note_id: int) -> None:
        self._open_postit_in_editor(note_id)
        self.editor.datetime_input.setFocus()

    def _set_postit_quick_reminder(self, note_id: int, minutes: int) -> None:
        note = self.store.note(note_id)
        if note is None:
            return
        due = (datetime.now() + timedelta(minutes=int(minutes))).strftime("%Y%m%d%H%M")
        memo = plain_text_from_content(str(note["content"])).strip() or str(note["title"])
        self.store.add_reminder(note_id, due, memo)
        self._sync_postit(note_id)
        self.refresh()
        self._status(f"{minutes}분 후 알림을 설정했습니다.", "success")

    def edit_deadline(self, note_id: int | None, parent=None) -> None:
        if note_id is None:
            QMessageBox.information(parent or self, "D-Day", "메모를 먼저 저장해 주세요.")
            return
        note = self.store.note(note_id)
        if note is None:
            return
        dialog = DeadlineDialog(note, parent or self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        if dialog.clear_requested:
            self.store.clear_deadline(note_id)
            message = "D-Day를 해제했습니다."
        else:
            values = dialog.values()
            self.store.set_deadline(note_id, values["due_at"], values["label"], values["alert"])
            # Finishing stops the countdown; the D-Day itself stays on the list.
            self.store.finish_deadline(note_id, values.get("done", False))
            message = "D-Day 카운트를 끝냈습니다." if values.get("done") else "D-Day를 저장했습니다."
        self._sync_postit(note_id)
        if self.current_id == note_id:
            self.editor.set_note(self.store.note(note_id))
        if self.standalone_window is not None and self.standalone_window.note_id == note_id:
            self.standalone_window.editor.set_note(self.store.note(note_id))
        self.refresh()
        self._status(message, "success")

    def _cycle_postits(self, current_id: int, backwards: bool) -> None:
        visible = [window for window in self.postits.values() if window.isVisible()]
        visible.sort(key=lambda window: window.note_id)
        if len(visible) < 2:
            return
        ids = [window.note_id for window in visible]
        try:
            index = ids.index(current_id)
        except ValueError:
            index = 0
        step = -1 if backwards else 1
        target = visible[(index + step) % len(visible)]
        target.show()
        target.raise_()
        target.activateWindow()
        target.memo.setFocus()

    def _postit_properties_changed(self, note_id: int) -> None:
        if self.current_id == note_id and not self.editor.save_timer.isActive():
            self.editor.set_note(self.store.note(note_id))
        self.refresh()

    def _arrange_compact_badges(self) -> None:
        badges = [
            window for window in self.postits.values()
            if window.isVisible() and window._display_mode == "badge"
        ]
        badges.sort(key=lambda window: window.note_id)
        for index, window in enumerate(badges):
            screen = window.screen()
            if screen is None:
                continue
            area = screen.availableGeometry()
            x = area.right() - window.width() - 12
            y = area.bottom() - ((index + 1) * (window.height() + 10))
            window.move(x, max(area.top() + 10, y))

    def _unpin_postit(self, note_id: int) -> None:
        window = self.postits.pop(note_id, None)
        if window is not None:
            window.close_silently()
        self.store.update_note(note_id, postit=False, postit_visible=False, postit_startup=False)
        if self.current_id == note_id:
            self.editor.postit_check.setChecked(False)
        self.refresh()

    def _save_postit_content(self, note_id: int, content: str) -> None:
        window = self.postits.get(note_id)
        try:
            self.store.update_note(note_id, content=content)
        except Exception as exc:
            if window is not None:
                window.show_save_error(str(exc))
            return
        if window is not None:
            window.mark_saved()
        if (
            self.current_id == note_id and not self.editor.save_timer.isActive()
            and not self.editor.content_edit.hasFocus()
        ):
            self.editor.content_edit.set_content(content)
        rows = self.store.notes(self.list_panel.search.text())
        self.list_panel.set_rows(rows, self.current_id)

    def _close_postit(self, note_id: int) -> None:
        window = self.postits.pop(note_id, None)
        if window is not None:
            window.close_silently()

    def _list_minimum_width(self) -> int:
        """Never let the divider hide a column header."""
        return max(self.LIST_MINIMUM_WIDTH, self.list_panel.minimum_table_width())

    def _stacked_list_height(self) -> int:
        needed = self.list_panel.height_for_rows(self.STACKED_LIST_ROWS)
        available = self.splitter.height()
        if available <= 0:
            return max(210, needed)
        ceiling = round(available * self.STACKED_LIST_MAX_SHARE)
        return max(210, min(needed, ceiling))

    def update_responsive_layout(self, width: int) -> None:
        desired = (
            Qt.Orientation.Vertical
            if width < self.HORIZONTAL_BREAKPOINT
            else Qt.Orientation.Horizontal
        )
        if desired == Qt.Orientation.Vertical:
            # Keep the stacked list tall enough to actually show rows; the old
            # fixed 210px left only the header visible.
            self.list_panel.setMinimumHeight(self._stacked_list_height())
        if self.splitter.orientation() != desired:
            self.splitter.setOrientation(desired)
            if desired == Qt.Orientation.Vertical:
                self.editor_remainder.hide()
                self.list_panel.setMinimumWidth(0)
                self.editor_scroll.setMinimumWidth(0)
                list_height = self._stacked_list_height()
                self.list_panel.setMinimumHeight(list_height)
                self.editor.setMinimumHeight(320)
                available = self.splitter.height() or (list_height + 410)
                self.splitter.setSizes([list_height, max(1, available - list_height), 0])
            else:
                self.editor_remainder.show()
                self.list_panel.setMinimumHeight(0)
                self.editor.setMinimumHeight(0)
                self.list_panel.setMinimumWidth(self._list_minimum_width())
                self.editor_scroll.setMinimumWidth(self.EDITOR_MINIMUM_WIDTH)
                self._horizontal_splitter_restored = False
                self._restore_horizontal_splitter_ratios()
        self.calendar.update_responsive_layout(width)

    def shutdown(self) -> None:
        if self.standalone_window is not None:
            self.standalone_window.shutdown()
        self.editor.shutdown()
        for note_id in list(self.postits):
            self._close_postit(note_id)
        self.schedule_postit.shutdown()
        self.calendar.shutdown()
        self.summary.shutdown()

    def _show_tab_status_hint(self, index: int) -> None:
        if 0 <= index < len(self.TAB_STATUS_HINTS):
            self._status(self.TAB_STATUS_HINTS[index], "info")

    def _status(self, message: str, level: str) -> None:
        self.status_label.setText(message)
        self.status_label.setProperty("level", level)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
