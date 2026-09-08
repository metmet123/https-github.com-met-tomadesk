import json
from datetime import datetime

from .recurrence import RecurrenceRule, is_allowed, next_occurrence, repeat_summary
from .schedule_recurrence import DATETIME_FMT


class ReminderRecurrenceStoreMixin:
    def add_recurring_reminder(
        self, note_id: int, due_at: str, memo: str, rule: RecurrenceRule,
    ) -> int:
        self._require_note(note_id)
        stamp = self._now_key()
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO reminder_series(note_id,memo,rule_type,weekdays,month_day,end_type,end_date,"
                "max_occurrences,generated_count,active,summary,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,1,1,?,?,?)",
                (note_id, memo, rule.rule_type, json.dumps(rule.weekdays), rule.month_day,
                 rule.end_type, rule.end_date, rule.max_occurrences, repeat_summary(rule), stamp, stamp),
            )
            series_id = int(cursor.lastrowid)
            reminder_id = self._insert_occurrence(note_id, due_at, memo, series_id, "regular")
        self._sync_reminder(reminder_id)
        return reminder_id

    def recurrence_rule(self, row) -> RecurrenceRule:
        return RecurrenceRule(
            row["rule_type"] or "none", tuple(json.loads(row["weekdays"] or "[]")),
            row["month_day"], row["end_type"] or "never", row["end_date"], row["max_occurrences"],
        )

    def update_series_from_reminder(
        self, reminder_id: int, due_at: str, memo: str, rule: RecurrenceRule,
    ) -> None:
        row = self.reminder(reminder_id)
        if row is None or row["series_id"] is None:
            self.update_reminder(reminder_id, due_at, memo)
            return
        with self.conn:
            self.conn.execute(
                "UPDATE reminder_series SET memo=?,rule_type=?,weekdays=?,month_day=?,end_type=?,"
                "end_date=?,max_occurrences=?,summary=?,updated_at=? WHERE id=?",
                (memo, rule.rule_type, json.dumps(rule.weekdays), rule.month_day, rule.end_type,
                 rule.end_date, rule.max_occurrences, repeat_summary(rule), self._now_key(), row["series_id"]),
            )
            self.conn.execute(
                "UPDATE reminders SET due_at=?,scheduled_at=?,memo=? WHERE id=? AND status='pending'",
                (due_at, due_at, memo, reminder_id),
            )
        self._sync_reminder(reminder_id)

    def stop_series(self, series_id: int) -> None:
        rows = self.conn.execute(
            "SELECT id FROM reminders WHERE series_id=? AND status='pending'", (series_id,),
        ).fetchall()
        with self.conn:
            self.conn.execute(
                "UPDATE reminder_series SET active=0,updated_at=? WHERE id=?", (self._now_key(), series_id),
            )
            self.conn.execute("DELETE FROM reminders WHERE series_id=? AND status='pending'", (series_id,))
        for row in rows:
            self._remove_synced_reminder(int(row["id"]))

    def cancel_series_keep_reminder(self, reminder_id: int, due_at: str, memo: str) -> None:
        row = self.reminder(reminder_id)
        if row is None or row["series_id"] is None:
            self.update_reminder(reminder_id, due_at, memo)
            return
        other_rows = self.conn.execute(
            "SELECT id FROM reminders WHERE series_id=? AND status='pending' AND id<>?",
            (row["series_id"], reminder_id),
        ).fetchall()
        with self.conn:
            self.conn.execute(
                "UPDATE reminder_series SET active=0,updated_at=? WHERE id=?",
                (self._now_key(), row["series_id"]),
            )
            self.conn.execute(
                "DELETE FROM reminders WHERE series_id=? AND status='pending' AND id<>?",
                (row["series_id"], reminder_id),
            )
            self.conn.execute(
                "UPDATE reminders SET series_id=NULL,occurrence_kind='regular',due_at=?,"
                "scheduled_at=?,memo=? WHERE id=?", (due_at, due_at, memo, reminder_id),
            )
        for other in other_rows:
            self._remove_synced_reminder(int(other["id"]))
        self._sync_reminder(reminder_id)

    def generate_next_occurrence(self, row) -> int | None:
        if row["series_id"] is None or row["occurrence_kind"] != "regular":
            return None
        series = self.conn.execute(
            "SELECT * FROM reminder_series WHERE id=? AND active=1", (row["series_id"],),
        ).fetchone()
        if series is None or self._has_regular_pending(int(series["id"])):
            return None
        rule = self.recurrence_rule(series)
        candidate = next_occurrence(datetime.strptime(row["scheduled_at"] or row["due_at"], DATETIME_FMT), rule)
        count = int(series["generated_count"])
        now = datetime.now()
        while candidate is not None:
            count += 1
            if not is_allowed(candidate, rule, count):
                self.conn.execute(
                    "UPDATE reminder_series SET active=0,generated_count=? WHERE id=?", (count - 1, series["id"]),
                )
                return None
            if candidate > now:
                break
            candidate = next_occurrence(candidate, rule)
        if candidate is None:
            return None
        self.conn.execute(
            "UPDATE reminder_series SET generated_count=?,updated_at=? WHERE id=?",
            (count, self._now_key(), series["id"]),
        )
        return self._insert_occurrence(
            series["note_id"], candidate.strftime(DATETIME_FMT), series["memo"], series["id"], "regular",
        )

    def next_repeat_due(self, reminder_id: int) -> str | None:
        row = self.reminder(reminder_id)
        if row is None or row["series_id"] is None:
            return None
        if row["occurrence_kind"] == "snoozed":
            next_row = self.conn.execute(
                "SELECT due_at FROM reminders WHERE series_id=? AND occurrence_kind='regular' "
                "AND status='pending' ORDER BY due_at LIMIT 1", (row["series_id"],),
            ).fetchone()
            return str(next_row["due_at"]) if next_row else None
        rule = self.recurrence_rule(row)
        candidate = next_occurrence(datetime.strptime(row["scheduled_at"] or row["due_at"], DATETIME_FMT), rule)
        if candidate and not is_allowed(candidate, rule, int(row["generated_count"] or 1) + 1):
            return None
        return candidate.strftime(DATETIME_FMT) if candidate else None

    def _has_regular_pending(self, series_id: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM reminders WHERE series_id=? AND occurrence_kind='regular' AND status='pending'",
            (series_id,),
        ).fetchone() is not None

    def _insert_occurrence(self, note_id, due_at: str, memo: str, series_id, kind: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO reminders(note_id,due_at,memo,status,created_at,series_id,occurrence_kind,scheduled_at) "
            "VALUES(?,?,?,'pending',?,?,?,?)",
            (note_id, due_at, memo, self._now_key(), series_id, kind, due_at),
        )
        return int(cursor.lastrowid)
