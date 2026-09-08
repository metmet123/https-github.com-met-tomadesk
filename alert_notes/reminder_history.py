from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ui_polish import polish_button

from .datetime_input import DateTimeInput
from .excel_export import export_table_xlsx
from .reminder_choice_dialog import display_due
from .sqlite_store import DATETIME_FMT


ACTION_LABELS = {"completed": "완료", "snoozed": "미룸", "skipped": "건너뜀"}


class ReminderHistoryPanel(QWidget):
    reminder_edit_requested = pyqtSignal(int)
    note_open_requested = pyqtSignal(int)
    memo_tab_requested = pyqtSignal()
    changed = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        title = QLabel("알림내역")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._pending_page(), "예정 알림")
        self.tabs.addTab(self._history_page(), "처리 내역")
        root.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(lambda _index: self.refresh())
        self.refresh()

    def _pending_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.pending_search = QLineEdit()
        self.pending_search.setPlaceholderText("예정 알림 검색")
        self.pending_search.setClearButtonEnabled(True)
        self.pending_search.textChanged.connect(self.refresh_pending)
        layout.addWidget(self.pending_search)
        self.pending_table = self._table(["선택", "ID", "예정 시간", "노트", "메모", "반복", "상태"])
        self.pending_table.cellDoubleClicked.connect(lambda row, _col: self._edit_row(row))
        self.pending_table.itemChanged.connect(self._update_action_buttons)
        self.pending_table.itemSelectionChanged.connect(self._update_action_buttons)
        layout.addWidget(self.pending_table, 1)
        self.pending_empty = self._empty(
            "예정된 알림이 없습니다.",
            "메모를 열고 ‘알림 예약’에서 시간을 정하면 여기에 표시됩니다.",
            ("메모에서 알림 예약하기", self.memo_tab_requested.emit),
        )
        layout.addWidget(self.pending_empty, 1)
        actions = QHBoxLayout()
        self.pending_toggle_button = self._button("전체 선택/해제", lambda: self._toggle_all(self.pending_table))
        self.pending_export_button = self._button("Excel 내보내기", self._export_pending)
        actions.addWidget(self.pending_toggle_button)
        actions.addWidget(self.pending_export_button)
        # Buttons that need a target stay disabled until there is one.
        self.pending_row_buttons = []
        for label, callback, object_name in (
            ("메모 열기", self._open_note, ""), ("수정", self._edit, ""),
            ("완료", self._complete, "primaryButton"), ("미루기", self._snooze, ""),
            ("건너뛰기", self._skip, ""),
        ):
            button = self._button(label, callback, object_name)
            self.pending_row_buttons.append(button)
            actions.addWidget(button)
        self.pending_delete_button = self._button("선택 삭제", self._delete_pending, "dangerButton")
        actions.addWidget(self.pending_delete_button)
        actions.addStretch()
        layout.addLayout(actions)
        return page

    def _history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("처리 내역 검색")
        self.history_search.setClearButtonEnabled(True)
        self.history_search.textChanged.connect(self.refresh_history)
        layout.addWidget(self.history_search)
        self.history_table = self._table(["선택", "ID", "처리 시간", "노트", "메모", "반복", "처리"])
        self.history_table.cellDoubleClicked.connect(lambda _row, _col: self._reschedule())
        self.history_table.itemChanged.connect(self._update_action_buttons)
        self.history_table.itemSelectionChanged.connect(self._update_action_buttons)
        layout.addWidget(self.history_table, 1)
        self.history_empty = self._empty(
            "처리된 알림 내역이 없습니다.",
            "알림을 완료·미루기·건너뛰기로 처리하면 여기에 기록이 쌓입니다.",
        )
        layout.addWidget(self.history_empty, 1)
        actions = QHBoxLayout()
        self.history_toggle_button = self._button("전체 선택/해제", lambda: self._toggle_all(self.history_table))
        self.history_export_button = self._button("Excel 내보내기", self._export_history)
        self.history_reschedule_button = self._button("재예약", self._reschedule, "primaryButton")
        self.history_delete_button = self._button("선택 삭제", self._delete_history, "dangerButton")
        self.history_clear_button = self._button("전체 삭제", self._clear_history, "dangerButton")
        for button in (
            self.history_toggle_button, self.history_export_button, self.history_reschedule_button,
            self.history_delete_button, self.history_clear_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        return page

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 48)
        table.setColumnWidth(1, 54)
        table.setColumnWidth(2, 145)
        table.setColumnWidth(3, 150)
        table.setColumnWidth(4, 260)
        table.setColumnWidth(5, 150)
        return table

    def _empty(self, text: str, description: str = "", action: tuple[str, object] | None = None) -> QWidget:
        """An empty screen should say what to do next, not just that it is empty."""
        host = QWidget()
        host.setObjectName("memoEmptyState")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        layout.addStretch()
        title = QLabel(text)
        title.setObjectName("emptyStateTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        if description:
            hint = QLabel(description)
            hint.setObjectName("emptyStateHint")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setWordWrap(True)
            layout.addWidget(hint)
        if action is not None:
            label, callback = action
            row = QHBoxLayout()
            row.addStretch()
            button = QPushButton(label)
            button.setObjectName("primaryButton")
            button.setMinimumHeight(38)
            polish_button(button)
            button.clicked.connect(callback)
            row.addWidget(button)
            row.addStretch()
            layout.addSpacing(6)
            layout.addLayout(row)
        layout.addStretch()
        return host

    @staticmethod
    def _button(label: str, callback, object_name: str = "") -> QPushButton:
        button = QPushButton(label)
        button.setMinimumHeight(40)
        if object_name:
            button.setObjectName(object_name)
        polish_button(button)
        button.clicked.connect(callback)
        return button

    def refresh(self, *_args) -> None:
        self.refresh_pending()
        self.refresh_history()
        self._update_action_buttons()

    def _update_action_buttons(self, *_args) -> None:
        if not hasattr(self, "pending_delete_button") or not hasattr(self, "history_clear_button"):
            return
        pending_rows = self.pending_table.rowCount()
        pending_target = bool(self._selected_ids(self.pending_table))
        pending_checked = bool(self._checked_ids(self.pending_table))
        self.pending_toggle_button.setEnabled(pending_rows > 0)
        self.pending_export_button.setEnabled(pending_rows > 0)
        for button in self.pending_row_buttons:
            button.setEnabled(pending_target)
        self.pending_delete_button.setEnabled(pending_checked)
        self.pending_delete_button.setText(
            f"선택 삭제 ({len(self._checked_ids(self.pending_table))})" if pending_checked else "선택 삭제"
        )
        history_rows = self.history_table.rowCount()
        history_checked = self._checked_ids(self.history_table)
        self.history_toggle_button.setEnabled(history_rows > 0)
        self.history_export_button.setEnabled(history_rows > 0)
        self.history_reschedule_button.setEnabled(bool(self._selected_ids(self.history_table)))
        self.history_delete_button.setEnabled(bool(history_checked))
        self.history_delete_button.setText(
            f"선택 삭제 ({len(history_checked)})" if history_checked else "선택 삭제"
        )
        self.history_clear_button.setEnabled(history_rows > 0)

    def refresh_pending(self, *_args) -> None:
        rows = self.store.pending_reminders(self.pending_search.text())
        self.pending_rows = rows
        self.pending_table.blockSignals(True)
        self.pending_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            checkbox.setCheckState(Qt.CheckState.Unchecked)
            values = [
                None, str(row["id"]), display_due(row["due_at"]), str(row["note_title"] or "삭제된 메모"),
                str(row["memo"]), str(row["repeat_summary"]), "예정",
            ]
            self.pending_table.setItem(index, 0, checkbox)
            for column, value in enumerate(values[1:], 1):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                if row["note_id"] is not None:
                    item.setData(Qt.ItemDataRole.UserRole + 1, int(row["note_id"]))
                self.pending_table.setItem(index, column, item)
        self.pending_table.blockSignals(False)
        self.pending_table.setVisible(bool(rows))
        self.pending_empty.setVisible(not rows)
        self._update_action_buttons()

    def refresh_history(self, *_args) -> None:
        rows = self.store.history(self.history_search.text())
        self.history_rows = rows
        self.history_table.blockSignals(True)
        self.history_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            checkbox.setCheckState(Qt.CheckState.Unchecked)
            values = [
                None, str(row["id"]), display_due(row["fired_at"]), str(row["note_title"] or "삭제된 메모"),
                str(row["memo"]), str(row["repeat_summary"]), ACTION_LABELS.get(str(row["action"]), str(row["action"])),
            ]
            self.history_table.setItem(index, 0, checkbox)
            for column, value in enumerate(values[1:], 1):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                self.history_table.setItem(index, column, item)
        self.history_table.blockSignals(False)
        self.history_table.setVisible(bool(rows))
        self.history_empty.setVisible(not rows)
        self._update_action_buttons()

    @staticmethod
    def _row_id(table: QTableWidget, row: int) -> int | None:
        """Rows are read while the table is being filled, so cells can be missing."""
        item = table.item(row, 1)
        value = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        return None if value is None else int(value)

    @classmethod
    def _selected_ids(cls, table: QTableWidget) -> list[int]:
        checked = cls._checked_ids(table)
        if checked:
            return checked
        row = table.currentRow()
        if row < 0:
            return []
        value = cls._row_id(table, row)
        return [] if value is None else [value]

    @classmethod
    def _checked_ids(cls, table: QTableWidget) -> list[int]:
        ids = []
        for row in range(table.rowCount()):
            state_item = table.item(row, 0)
            if state_item is None or state_item.checkState() != Qt.CheckState.Checked:
                continue
            value = cls._row_id(table, row)
            if value is not None:
                ids.append(value)
        return ids

    @staticmethod
    def _toggle_all(table: QTableWidget) -> None:
        items = [table.item(row, 0) for row in range(table.rowCount())]
        checked = not items or not all(item.checkState() == Qt.CheckState.Checked for item in items)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item in items:
            item.setCheckState(state)

    def _export_pending(self) -> None:
        self._export_rows("예정알림", self.pending_table, self.pending_rows, pending=True)

    def _export_history(self) -> None:
        self._export_rows("처리내역", self.history_table, self.history_rows, pending=False)

    def _export_rows(self, sheet_name: str, table: QTableWidget, source_rows, pending: bool) -> None:
        checked = set(self._checked_ids(table))
        rows = [row for row in source_rows if not checked or int(row["id"]) in checked]
        if not rows:
            QMessageBox.information(self, "Excel 내보내기", "내보낼 항목이 없습니다.")
            return
        default = self.store.path.parent / f"{sheet_name}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, f"{sheet_name} Excel 내보내기", str(default), "Excel (*.xlsx)")
        if not path:
            return
        if pending:
            headers = ["ID", "예정 시간", "노트", "메모", "반복", "상태"]
            values = [
                [row["id"], display_due(row["due_at"]), row["note_title"] or "삭제된 메모",
                 row["memo"], row["repeat_summary"], "예정"]
                for row in rows
            ]
        else:
            headers = ["ID", "처리 시간", "노트", "메모", "반복", "처리"]
            values = [
                [row["id"], display_due(row["fired_at"]), row["note_title"] or "삭제된 메모",
                 row["memo"], row["repeat_summary"], ACTION_LABELS.get(str(row["action"]), str(row["action"]))]
                for row in rows
            ]
        try:
            output = export_table_xlsx(sheet_name, headers, values, path)
        except Exception as exc:
            QMessageBox.warning(self, "Excel 내보내기 실패", str(exc))
            return
        QMessageBox.information(self, "Excel 내보내기 완료", str(output))

    def _edit_row(self, row: int) -> None:
        self.pending_table.selectRow(row)
        self._edit()

    def _edit(self) -> None:
        ids = self._selected_ids(self.pending_table)
        if ids:
            self.reminder_edit_requested.emit(ids[0])

    def _open_note(self) -> None:
        ids = self._selected_ids(self.pending_table)
        if not ids:
            return
        row = self.store.reminder(ids[0])
        if row is not None and row["note_id"] is not None:
            self.note_open_requested.emit(int(row["note_id"]))

    def _complete(self) -> None:
        for reminder_id in self._selected_ids(self.pending_table):
            self.store.complete_reminder(reminder_id)
        self._changed()

    def _snooze(self) -> None:
        ids = self._selected_ids(self.pending_table)
        if not ids:
            return
        dialog = SnoozeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for reminder_id in ids:
            self.store.snooze_reminder(reminder_id, dialog.minutes.value())
        self._changed()

    def _skip(self) -> None:
        for reminder_id in self._selected_ids(self.pending_table):
            self.store.skip_reminder(reminder_id)
        self._changed()

    def _delete_pending(self) -> None:
        ids = self._checked_ids(self.pending_table)
        if not ids or QMessageBox.question(self, "알림 삭제", f"선택한 알림 {len(ids)}건을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        for reminder_id in ids:
            self.store.delete_reminder(reminder_id)
        self._changed()

    def _reschedule(self) -> None:
        ids = self._selected_ids(self.history_table)
        if not ids:
            return
        row = self.store.history_item(ids[0])
        if row is None or row["note_id"] is None:
            QMessageBox.information(self, "재예약", "연결된 메모가 없어 재예약할 수 없습니다.")
            return
        dialog = RescheduleDialog(str(row["memo"]), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        created = self.store.reschedule_history(ids[0], dialog.due_key(), dialog.memo.text().strip())
        if created is None:
            QMessageBox.information(self, "재예약", "연결된 메모가 없어 재예약할 수 없습니다.")
            return
        self._changed()

    def _delete_history(self) -> None:
        ids = self._checked_ids(self.history_table)
        if not ids or QMessageBox.question(self, "내역 삭제", f"선택한 내역 {len(ids)}건을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_history(ids)
        self._changed()

    def _clear_history(self) -> None:
        if QMessageBox.question(self, "내역 전체 삭제", "모든 처리 내역을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        self.store.clear_history()
        self._changed()

    def _changed(self) -> None:
        self.refresh()
        self.changed.emit()


class SnoozeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("알림 미루기")
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("미룰 시간"))
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 1440)
        self.minutes.setValue(10)
        self.minutes.setSuffix("분")
        row.addWidget(self.minutes)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class RescheduleDialog(QDialog):
    def __init__(self, memo: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("알림 재예약")
        layout = QVBoxLayout(self)
        self.memo = QLineEdit(memo)
        self.due = DateTimeInput()
        self.due.set_datetime(datetime.now() + timedelta(minutes=10))
        layout.addWidget(self.memo)
        layout.addWidget(self.due)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def due_key(self) -> str:
        return self.due.datetime().strftime(DATETIME_FMT)

    def _accept_if_valid(self) -> None:
        if not self.memo.text().strip():
            QMessageBox.information(self, "재예약", "알림 내용을 입력해 주세요.")
            return
        if not self.due.is_valid() or self.due.datetime() <= datetime.now():
            QMessageBox.information(self, "재예약", "현재보다 이후 시간을 입력해 주세요.")
            return
        self.accept()
