from datetime import datetime, timedelta

from .schedule_recurrence import DATETIME_FMT


REMINDER_SELECT = """
SELECT reminders.*, notes.title AS note_title, notes.content AS note_content, notes.color AS note_color,
       reminder_series.rule_type, reminder_series.weekdays, reminder_series.month_day,
       reminder_series.end_type, reminder_series.end_date, reminder_series.max_occurrences,
       reminder_series.generated_count, reminder_series.active,
       CASE
         WHEN reminders.occurrence_kind='snoozed' AND reminder_series.summary IS NOT NULL
           THEN '미룬 알림 · ' || reminder_series.summary
         WHEN reminders.occurrence_kind='snoozed' THEN '미룬 알림'
         ELSE COALESCE(reminder_series.summary, '반복 없음')
       END AS repeat_summary
FROM reminders
LEFT JOIN notes ON notes.id=reminders.note_id
LEFT JOIN reminder_series ON reminder_series.id=reminders.series_id
"""


class ReminderStoreMixin:
    def _require_note(self, note_id: int) -> None:
        if self.conn.execute("SELECT 1 FROM notes WHERE id=? AND deleted_at=''", (note_id,)).fetchone() is None:
            raise ValueError("The note does not exist.")

    def reminder(self, reminder_id: int):
        return self.conn.execute(
            f"{REMINDER_SELECT} WHERE reminders.id=? AND COALESCE(notes.deleted_at,'')=''", (reminder_id,)
        ).fetchone()

    def add_reminder(self, note_id: int, due_at: str, memo: str = "") -> int:
        self._require_note(note_id)
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO reminders(note_id,due_at,memo,status,created_at,scheduled_at) "
                "VALUES(?,?,?,'pending',?,?)", (note_id, due_at, memo, self._now_key(), due_at),
            )
        reminder_id = int(cursor.lastrowid)
        self._sync_reminder(reminder_id)
        return reminder_id

    def set_reminder(self, note_id: int, due_at: str, memo: str = "") -> int:
        """Compatibility API: replace the earliest pending reminder, or create one."""
        row = self.conn.execute(
            "SELECT id FROM reminders WHERE note_id=? AND status='pending' ORDER BY due_at,id LIMIT 1",
            (note_id,),
        ).fetchone()
        if row is None:
            return self.add_reminder(note_id, due_at, memo)
        self.update_reminder(int(row["id"]), due_at, memo)
        return int(row["id"])

    def update_reminder(self, reminder_id: int, due_at: str, memo: str) -> None:
        row = self.reminder(reminder_id)
        if row is None:
            return
        scheduled_at = row["scheduled_at"] if row["series_id"] is not None else due_at
        with self.conn:
            self.conn.execute(
                "UPDATE reminders SET due_at=?,scheduled_at=?,memo=? WHERE id=? AND status='pending'",
                (due_at, scheduled_at, memo, reminder_id),
            )
        self._sync_reminder(reminder_id)

    def pending_reminders(self, search: str = "") -> list:
        where = "WHERE reminders.status='pending' AND COALESCE(notes.deleted_at,'')=''"
        args: tuple = ()
        if search.strip():
            like = f"%{search.strip()}%"
            where += " AND (reminders.memo LIKE ? OR notes.title LIKE ? OR reminder_series.summary LIKE ?)"
            args = (like, like, like)
        return list(self.conn.execute(f"{REMINDER_SELECT} {where} ORDER BY reminders.due_at,id", args))

    def pending_reminders_for_note(self, note_id: int) -> list:
        return list(self.conn.execute(
            f"{REMINDER_SELECT} WHERE reminders.note_id=? AND reminders.status='pending' "
            "AND COALESCE(notes.deleted_at,'')='' "
            "ORDER BY reminders.due_at,reminders.id", (note_id,),
        ))

    def due_reminders(self, current: str | None = None) -> list:
        return list(self.conn.execute(
            f"{REMINDER_SELECT} WHERE reminders.status='pending' AND reminders.due_at<=? "
            "AND COALESCE(notes.deleted_at,'')='' "
            "ORDER BY reminders.due_at,reminders.id", (current or self._now_key(),),
        ))

    def complete_reminder(self, reminder_id: int, action: str = "completed") -> None:
        row = self.reminder(reminder_id)
        if row is None or row["status"] != "pending":
            return
        with self.conn:
            self._record_history(row, action)
            self.conn.execute("UPDATE reminders SET status=? WHERE id=?", (action, reminder_id))
            self._disable_deadline_alert(row)
            next_id = self.generate_next_occurrence(row)
        self._remove_synced_reminder(reminder_id)
        self._remove_retired_siblings()
        if next_id is not None:
            self._sync_reminder(next_id)

    def snooze_reminder(self, reminder_id: int, minutes: int = 10) -> None:
        row = self.reminder(reminder_id)
        if row is None or row["status"] != "pending":
            return
        snoozed_due = (datetime.now() + timedelta(minutes=max(1, minutes))).strftime(DATETIME_FMT)
        if row["series_id"] is None:
            with self.conn:
                self._record_history(row, "snoozed")
                self.conn.execute(
                    "UPDATE reminders SET due_at=?,scheduled_at=?,occurrence_kind='snoozed' "
                    "WHERE id=?", (snoozed_due, snoozed_due, reminder_id),
                )
            self._sync_reminder(reminder_id)
            return
        with self.conn:
            self._record_history(row, "snoozed")
            self.conn.execute("UPDATE reminders SET status='snoozed' WHERE id=?", (reminder_id,))
            snoozed_id = self._insert_occurrence(
                row["note_id"], snoozed_due, row["memo"], row["series_id"], "snoozed",
            )
            next_id = self.generate_next_occurrence(row)
        self._remove_synced_reminder(reminder_id)
        self._sync_reminder(snoozed_id)
        if next_id is not None:
            self._sync_reminder(next_id)

    def skip_reminder(self, reminder_id: int) -> None:
        row = self.reminder(reminder_id)
        if row is None or row["status"] != "pending":
            return
        with self.conn:
            self._record_history(row, "skipped")
            self.conn.execute("UPDATE reminders SET status='skipped' WHERE id=?", (reminder_id,))
            next_id = self.generate_next_occurrence(row)
        self._remove_synced_reminder(reminder_id)
        if next_id is not None:
            self._sync_reminder(next_id)

    def delete_reminder(self, reminder_id: int) -> None:
        row = self.reminder(reminder_id)
        if row is None:
            return
        with self.conn:
            self.conn.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
            self._disable_deadline_alert(row)
            next_id = self.generate_next_occurrence(row)
        self._remove_synced_reminder(reminder_id)
        self._remove_retired_siblings()
        if next_id is not None:
            self._sync_reminder(next_id)

    def clear_reminder(self, note_id: int) -> None:
        rows = self.pending_reminders_for_note(note_id)
        series_ids = {int(row["series_id"]) for row in rows if row["series_id"] is not None}
        with self.conn:
            self.conn.execute("DELETE FROM reminders WHERE note_id=? AND status='pending'", (note_id,))
            if any(str(row["occurrence_kind"]) == "deadline" for row in rows):
                self.conn.execute(
                    "UPDATE notes SET d_day_alert=0,updated_at=? WHERE id=?",
                    (self._now_key(), note_id),
                )
            for series_id in series_ids:
                self.conn.execute(
                    "UPDATE reminder_series SET active=0,updated_at=? WHERE id=?",
                    (self._now_key(), series_id),
                )
        for row in rows:
            self._remove_synced_reminder(int(row["id"]))

    def _remove_retired_siblings(self) -> None:
        for sibling_id in getattr(self, "_pending_sibling_ids", []):
            self._remove_synced_reminder(sibling_id)
        self._pending_sibling_ids = []

    def _disable_deadline_alert(self, row) -> None:
        """The day-before heads-up is part of the same D-Day alert, not its own."""
        if str(row["occurrence_kind"]) not in ("deadline", "deadline_prior"):
            return
        if row["note_id"] is None:
            return
        note_id = int(row["note_id"])
        self.conn.execute(
            "UPDATE notes SET d_day_alert=0,updated_at=? WHERE id=?",
            (self._now_key(), note_id),
        )
        # Handling either half retires the other, so no orphan alert is left.
        siblings = list(self.conn.execute(
            "SELECT id FROM reminders WHERE note_id=? AND id!=? AND status='pending' "
            "AND occurrence_kind IN ('deadline','deadline_prior')",
            (note_id, int(row["id"])),
        ))
        if siblings:
            self.conn.execute(
                "DELETE FROM reminders WHERE note_id=? AND id!=? AND status='pending' "
                "AND occurrence_kind IN ('deadline','deadline_prior')",
                (note_id, int(row["id"])),
            )
        self._pending_sibling_ids = [int(item["id"]) for item in siblings]

    def history(self, search: str = "") -> list:
        sql = """
        SELECT reminder_history.*, notes.title AS note_title FROM reminder_history
        LEFT JOIN notes ON notes.id=reminder_history.note_id
        """
        args: tuple = ()
        if search.strip():
            like = f"%{search.strip()}%"
            sql += " WHERE reminder_history.memo LIKE ? OR notes.title LIKE ?"
            args = (like, like)
        return list(self.conn.execute(sql + " ORDER BY reminder_history.fired_at DESC,id DESC", args))

    def history_item(self, history_id: int):
        return self.conn.execute("SELECT * FROM reminder_history WHERE id=?", (history_id,)).fetchone()

    def reschedule_history(self, history_id: int, due_at: str, memo: str) -> int | None:
        row = self.history_item(history_id)
        if row is None or row["note_id"] is None or self.note(int(row["note_id"])) is None:
            return None
        return self.add_reminder(int(row["note_id"]), due_at, memo)

    def delete_history(self, history_ids: list[int]) -> None:
        ids = sorted({int(value) for value in history_ids})
        if not ids:
            return
        with self.conn:
            self.conn.execute(
                f"DELETE FROM reminder_history WHERE id IN ({','.join('?' for _ in ids)})", ids,
            )

    def clear_history(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM reminder_history")

    def _record_history(self, row, action: str) -> None:
        self.conn.execute(
            "INSERT INTO reminder_history(note_id,memo,fired_at,action,series_id,repeat_summary,occurrence_kind) "
            "VALUES(?,?,?,?,?,?,?)",
            (row["note_id"], row["memo"], self._now_key(), action, row["series_id"],
             row["repeat_summary"] or "", row["occurrence_kind"]),
        )

    def _sync_reminder(self, reminder_id: int) -> None:
        if hasattr(self, "schedules"):
            self.schedules.sync_legacy_reminder(reminder_id)

    def _remove_synced_reminder(self, reminder_id: int) -> None:
        if hasattr(self, "schedules"):
            self.schedules.remove_legacy_reminder(reminder_id)
