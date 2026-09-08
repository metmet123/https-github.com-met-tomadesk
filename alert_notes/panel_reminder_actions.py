from datetime import datetime

from PyQt6.QtWidgets import QMessageBox

from .recurrence import RULE_NONE
from .reminder_choice_dialog import ExistingReminderDialog
from .sqlite_store import DATETIME_FMT, now_key


class PanelReminderActionsMixin:
    def set_reminder(self, due_at: str) -> None:
        """Compatibility entry point used by quick calendar creation and older callers."""
        if self.current_id is None:
            return
        if due_at <= now_key():
            QMessageBox.information(self, "알림 설정", "현재보다 이후 시간을 선택해 주세요.")
            return
        self.store.update_note(self.current_id, **self.editor.values())
        memo = self.editor.content_edit.toPlainText().strip() or self.editor.title_edit.text().strip()
        self.store.set_reminder(self.current_id, due_at, memo)
        self._sync_postit(self.current_id)
        self.refresh()
        due = datetime.strptime(due_at, DATETIME_FMT).strftime("%Y-%m-%d %H:%M")
        self._status(f"{due}에 알림을 설정했습니다.", "success")

    def save_reminder(self, values: dict) -> None:
        self.save_reminder_for(self.current_id, self.editor, values, self)

    def save_reminder_for(self, note_id: int | None, editor, values: dict, parent=None) -> None:
        if note_id is None:
            return
        due_at = str(values["due_at"])
        if due_at <= now_key():
            QMessageBox.information(parent or self, "알림 설정", "현재보다 이후 시간을 선택해 주세요.")
            return
        reminder_id = values.get("id")
        rule = values["rule"]
        memo = str(values["memo"])
        if reminder_id is None:
            pending = self.store.pending_reminders_for_note(note_id)
            if pending:
                choice, selected_id = ExistingReminderDialog(pending, parent or self).result_choice()
                if choice is None:
                    return
                if choice == "change":
                    reminder_id = selected_id
        if reminder_id is None:
            if rule.rule_type == RULE_NONE:
                reminder_id = self.store.add_reminder(note_id, due_at, memo)
            else:
                reminder_id = self.store.add_recurring_reminder(note_id, due_at, memo, rule)
        else:
            row = self.store.reminder(int(reminder_id))
            if row is None:
                return
            recurring = row["series_id"] is not None and row["occurrence_kind"] == "regular"
            scope = self._choose_recurrence_scope(parent) if recurring else "current"
            if scope is None:
                return
            if scope == "current":
                self.store.update_reminder(int(reminder_id), due_at, memo)
            elif rule.rule_type == RULE_NONE:
                self.store.cancel_series_keep_reminder(int(reminder_id), due_at, memo)
            else:
                self.store.update_series_from_reminder(int(reminder_id), due_at, memo, rule)
        self._sync_postit(note_id)
        self.refresh()
        editor.set_reminder(self.store.reminder(int(reminder_id)))
        due = datetime.strptime(due_at, DATETIME_FMT).strftime("%Y-%m-%d %H:%M")
        self._status(f"{due}에 알림을 저장했습니다.", "success")
        editor.show_action_feedback(f"알림을 저장했습니다 · {due}", "success")

    def _choose_recurrence_scope(self, parent=None) -> str | None:
        box = QMessageBox(parent or self)
        box.setWindowTitle("반복 알림 변경")
        box.setText("변경 범위를 선택해 주세요.")
        current = box.addButton("이번 알림만", QMessageBox.ButtonRole.AcceptRole)
        entire = box.addButton("전체 반복", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is current:
            return "current"
        if box.clickedButton() is entire:
            return "all"
        return None

    def clear_reminder(self, reminder_id=None) -> None:
        self.clear_reminder_for(self.current_id, reminder_id, self)

    def clear_reminder_for(self, note_id: int | None, reminder_id=None, parent=None) -> None:
        if note_id is None:
            return
        if reminder_id is None:
            pending = self.store.pending_reminders_for_note(note_id)
            if not pending:
                return
            if len(pending) == 1:
                reminder_id = int(pending[0]["id"])
            else:
                choice, reminder_id = ExistingReminderDialog(
                    pending, parent or self, allow_add=False,
                ).result_choice()
                if choice is None:
                    return
        self.store.delete_reminder(int(reminder_id))
        self._sync_postit(note_id)
        self.refresh()
        self._status("선택한 알림을 해제했습니다.", "success")
        editor = getattr(parent, "editor", None) if parent is not None else None
        target_editor = editor or getattr(self, "editor", None)
        if target_editor is not None:
            target_editor.set_reminder(None)
            target_editor.show_action_feedback("알림을 해제했습니다.", "success")

    def show_reminder(self, reminder_id: int) -> None:
        row = self.store.reminder(reminder_id)
        if row is None or row["note_id"] is None:
            return
        self.tabs.setCurrentIndex(0)
        self.show_note(int(row["note_id"]))
        self.editor.set_reminder(row)
