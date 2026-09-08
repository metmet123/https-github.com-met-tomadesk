from __future__ import annotations

from datetime import datetime, timedelta
import json
import sqlite3

from .schedule_recurrence import DATETIME_FMT, expand_occurrences, normalize_rule


ITEM_COLUMNS = (
    "id", "title", "details", "item_type", "note_id", "start_at", "end_at",
    "all_day", "category", "priority", "status", "recurrence_rule", "hotkey",
    "hotkey_action", "count_as_dday", "source_reminder_id", "created_at", "updated_at",
    "deleted_at",
)
NOTIFICATION_COLUMNS = ("id", "item_id", "minutes_before")
NOTIFICATION_LOG_COLUMNS = ("notification_id", "occurrence_at", "state", "due_at")
EXCEPTION_COLUMNS = ("id", "item_id", "occurrence_at", "action", "new_start_at", "new_end_at")


class ScheduleStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._init_schema()
        self.migrate_legacy_reminders()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schedule_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                item_type TEXT NOT NULL DEFAULT 'event',
                note_id INTEGER,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                all_day INTEGER NOT NULL DEFAULT 0,
                category TEXT NOT NULL DEFAULT 'sky',
                priority INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                recurrence_rule TEXT NOT NULL DEFAULT '{}',
                hotkey TEXT NOT NULL DEFAULT '',
                hotkey_action TEXT NOT NULL DEFAULT 'open',
                count_as_dday INTEGER NOT NULL DEFAULT 0,
                source_reminder_id INTEGER UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS schedule_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                minutes_before INTEGER NOT NULL DEFAULT 0,
                UNIQUE(item_id, minutes_before),
                FOREIGN KEY(item_id) REFERENCES schedule_items(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS schedule_notification_log (
                notification_id INTEGER NOT NULL,
                occurrence_at TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'done',
                due_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(notification_id, occurrence_at),
                FOREIGN KEY(notification_id) REFERENCES schedule_notifications(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS schedule_occurrence_exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                occurrence_at TEXT NOT NULL,
                action TEXT NOT NULL,
                new_start_at TEXT NOT NULL DEFAULT '',
                new_end_at TEXT NOT NULL DEFAULT '',
                UNIQUE(item_id, occurrence_at),
                FOREIGN KEY(item_id) REFERENCES schedule_items(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_schedule_range ON schedule_items(start_at, end_at);
            CREATE INDEX IF NOT EXISTS idx_schedule_note ON schedule_items(note_id);
            CREATE INDEX IF NOT EXISTS idx_schedule_hotkey ON schedule_items(hotkey);
            """
        )
        columns = {str(row[1]) for row in self.conn.execute("PRAGMA table_info(schedule_items)")}
        if "deleted_at" not in columns:
            self.conn.execute("ALTER TABLE schedule_items ADD COLUMN deleted_at TEXT NOT NULL DEFAULT ''")
        if "count_as_dday" not in columns:
            self.conn.execute(
                "ALTER TABLE schedule_items ADD COLUMN count_as_dday INTEGER NOT NULL DEFAULT 0"
            )
        self.conn.commit()

    def migrate_legacy_reminders(self) -> None:
        stamp = _now_key()
        rows = self.conn.execute(
            "SELECT reminders.id, reminders.note_id, reminders.due_at, reminders.memo, notes.title "
            "FROM reminders JOIN notes ON notes.id=reminders.note_id "
            "WHERE reminders.status='pending' AND notes.deleted_at=''"
        ).fetchall()
        with self.conn:
            for row in rows:
                end_at = (datetime.strptime(row["due_at"], DATETIME_FMT) + timedelta(minutes=30)).strftime(DATETIME_FMT)
                self.conn.execute(
                    "INSERT OR IGNORE INTO schedule_items(title,details,item_type,note_id,start_at,end_at,"
                    "category,source_reminder_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (row["title"], row["memo"], "event", row["note_id"], row["due_at"], end_at,
                     "sky", row["id"], stamp, stamp),
                )

    def sync_legacy_reminder(self, reminder_id: int) -> None:
        row = self.conn.execute(
            "SELECT reminders.id,reminders.note_id,reminders.due_at,reminders.memo,notes.title "
            "FROM reminders JOIN notes ON notes.id=reminders.note_id "
            "WHERE reminders.id=? AND reminders.status='pending' AND notes.deleted_at=''",
            (int(reminder_id),),
        ).fetchone()
        if row is None:
            self.remove_legacy_reminder(reminder_id)
            return
        stamp = _now_key()
        end_at = (datetime.strptime(row["due_at"], DATETIME_FMT) + timedelta(minutes=30)).strftime(DATETIME_FMT)
        with self.conn:
            existing = self.conn.execute(
                "SELECT id FROM schedule_items WHERE source_reminder_id=?", (int(reminder_id),)
            ).fetchone()
            if existing is None:
                self.conn.execute(
                    "INSERT INTO schedule_items(title,details,item_type,note_id,start_at,end_at,"
                    "category,source_reminder_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (row["title"], row["memo"], "event", row["note_id"], row["due_at"], end_at,
                     "sky", row["id"], stamp, stamp),
                )
            else:
                self.conn.execute(
                    "UPDATE schedule_items SET title=?,details=?,note_id=?,start_at=?,end_at=?,"
                    "updated_at=?,deleted_at='' WHERE source_reminder_id=?",
                    (row["title"], row["memo"], row["note_id"], row["due_at"], end_at,
                     stamp, int(reminder_id)),
                )

    def remove_legacy_reminder(self, reminder_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM schedule_items WHERE source_reminder_id=?", (reminder_id,))

    def save_item(self, values: dict) -> int:
        item_id = values.get("id")
        if item_id:
            source = self.conn.execute(
                "SELECT source_reminder_id FROM schedule_items WHERE id=?", (int(item_id),)
            ).fetchone()
            if source is not None and source["source_reminder_id"] is not None:
                raise ValueError("메모 알림에서 만들어진 일정은 메모의 알림 설정에서 변경해 주세요.")
        data = _normalized_item(values)
        stamp = _now_key()
        rule = json.dumps(normalize_rule(data["recurrence_rule"]), ensure_ascii=False)
        columns = (
            "title", "details", "item_type", "note_id", "start_at", "end_at", "all_day",
            "category", "priority", "status", "recurrence_rule", "hotkey", "hotkey_action",
            "count_as_dday",
        )
        payload = [data[key] for key in columns]
        payload[6] = int(bool(payload[6]))
        payload[10] = rule
        payload[13] = int(bool(payload[13]))
        with self.conn:
            if item_id:
                assignments = ",".join(f"{key}=?" for key in columns)
                self.conn.execute(f"UPDATE schedule_items SET {assignments},updated_at=? WHERE id=?", (*payload, stamp, item_id))
            else:
                markers = ",".join("?" for _ in columns)
                cursor = self.conn.execute(
                    f"INSERT INTO schedule_items({','.join(columns)},created_at,updated_at) VALUES({markers},?,?)",
                    (*payload, stamp, stamp),
                )
                item_id = int(cursor.lastrowid)
            self.conn.execute("DELETE FROM schedule_notifications WHERE item_id=?", (item_id,))
            for minutes in data["reminders"]:
                self.conn.execute(
                    "INSERT INTO schedule_notifications(item_id,minutes_before) VALUES(?,?)",
                    (item_id, minutes),
                )
        return int(item_id)

    def item(self, item_id: int):
        return self.conn.execute("SELECT * FROM schedule_items WHERE id=? AND deleted_at=''", (item_id,)).fetchone()

    def notifications(self, item_id: int) -> list[int]:
        return [int(row[0]) for row in self.conn.execute(
            "SELECT minutes_before FROM schedule_notifications WHERE item_id=? ORDER BY minutes_before", (item_id,)
        )]

    def delete_item(self, item_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE schedule_items SET deleted_at=?,updated_at=? WHERE id=? AND source_reminder_id IS NULL",
                (_now_key(), _now_key(), item_id),
            )

    def trashed_items(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM schedule_items WHERE deleted_at!='' AND source_reminder_id IS NULL "
            "ORDER BY deleted_at DESC,id DESC"
        ))

    def restore_item(self, item_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE schedule_items SET deleted_at='',updated_at=? WHERE id=?", (_now_key(), item_id))

    def purge_expired_trash(self, days: int = 7) -> int:
        cutoff = (datetime.now() - timedelta(days=max(1, days))).strftime(DATETIME_FMT)
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM schedule_items WHERE deleted_at!='' AND deleted_at<?", (cutoff,)
            )
        return cursor.rowcount

    def set_completed(self, item_id: int, completed: bool) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE schedule_items SET status=?,updated_at=? WHERE id=?",
                ("completed" if completed else "pending", _now_key(), item_id),
            )

    def items_for_range(self, start_at: str, end_at: str, include_completed: bool = True) -> list[dict]:
        range_start = datetime.strptime(start_at, DATETIME_FMT)
        range_end = datetime.strptime(end_at, DATETIME_FMT)
        where = " WHERE deleted_at=''" + ("" if include_completed else " AND status!='completed'")
        rows = self.conn.execute("SELECT * FROM schedule_items" + where + " ORDER BY start_at,id").fetchall()
        result = []
        for row in rows:
            exceptions = {
                str(item["occurrence_at"]): item
                for item in self.conn.execute(
                    "SELECT * FROM schedule_occurrence_exceptions WHERE item_id=?", (row["id"],)
                )
            }
            for occurrence in expand_occurrences(row, range_start, range_end):
                exception = exceptions.get(occurrence.key)
                if exception is not None and exception["action"] == "skip":
                    continue
                item = dict(row)
                item["occurrence_at"] = occurrence.key
                item["display_start_at"] = (
                    str(exception["new_start_at"]) if exception is not None and exception["action"] == "move"
                    else occurrence.start.strftime(DATETIME_FMT)
                )
                item["display_end_at"] = (
                    str(exception["new_end_at"]) if exception is not None and exception["action"] == "move"
                    else occurrence.end.strftime(DATETIME_FMT)
                )
                moved_start = datetime.strptime(item["display_start_at"], DATETIME_FMT)
                moved_end = datetime.strptime(item["display_end_at"], DATETIME_FMT)
                if moved_start >= range_end or moved_end <= range_start:
                    continue
                if exception is not None and exception["action"] == "complete":
                    item["status"] = "completed"
                item["reminders"] = self.notifications(int(row["id"]))
                result.append(item)
        return sorted(result, key=lambda item: (item["display_start_at"], item["id"]))

    def skip_occurrence(self, item_id: int, occurrence_at: str) -> None:
        self._save_exception(item_id, occurrence_at, "skip", "", "")

    def set_occurrence_completed(
        self, item_id: int, occurrence_at: str, completed: bool
    ) -> None:
        if completed:
            self._save_exception(item_id, occurrence_at, "complete", "", "")
        else:
            self.clear_occurrence_exception(item_id, occurrence_at)

    def move_occurrence(self, item_id: int, occurrence_at: str, start_at: str, end_at: str) -> None:
        if datetime.strptime(end_at, DATETIME_FMT) <= datetime.strptime(start_at, DATETIME_FMT):
            raise ValueError("종료 시간은 시작 시간보다 뒤여야 합니다.")
        self._save_exception(item_id, occurrence_at, "move", start_at, end_at)

    def clear_occurrence_exception(self, item_id: int, occurrence_at: str) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM schedule_occurrence_exceptions WHERE item_id=? AND occurrence_at=?",
                (item_id, occurrence_at),
            )

    def _save_exception(self, item_id: int, occurrence_at: str, action: str, start_at: str, end_at: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO schedule_occurrence_exceptions(item_id,occurrence_at,action,new_start_at,new_end_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(item_id,occurrence_at) DO UPDATE SET "
                "action=excluded.action,new_start_at=excluded.new_start_at,new_end_at=excluded.new_end_at",
                (item_id, occurrence_at, action, start_at, end_at),
            )

    def search(self, text: str, limit: int = 100) -> list[sqlite3.Row]:
        like = f"%{text.strip()}%"
        return list(self.conn.execute(
            "SELECT * FROM schedule_items WHERE deleted_at='' AND (title LIKE ? OR details LIKE ?) ORDER BY start_at LIMIT ?",
            (like, like, limit),
        ))

    def hotkey_items(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM schedule_items WHERE deleted_at='' AND hotkey!='' ORDER BY id"
        ))

    def due_notifications(self, current: datetime | None = None) -> list[dict]:
        now = current or datetime.now()
        rows = self.conn.execute(
            "SELECT schedule_items.*, schedule_notifications.id AS notification_id, "
            "schedule_notifications.minutes_before FROM schedule_items "
            "JOIN schedule_notifications ON schedule_notifications.item_id=schedule_items.id "
            "WHERE schedule_items.deleted_at='' AND schedule_items.status!='completed' ORDER BY schedule_items.id"
        ).fetchall()
        due = []
        for row in rows:
            minutes = int(row["minutes_before"])
            range_start = now - timedelta(days=7)
            range_end = now + timedelta(minutes=minutes + 2)
            for occurrence in expand_occurrences(row, range_start, range_end):
                exception = self.conn.execute(
                    "SELECT * FROM schedule_occurrence_exceptions WHERE item_id=? AND occurrence_at=?",
                    (row["id"], occurrence.key),
                ).fetchone()
                if exception is not None and exception["action"] == "skip":
                    continue
                occurrence_start = (
                    datetime.strptime(exception["new_start_at"], DATETIME_FMT)
                    if exception is not None and exception["action"] == "move" else occurrence.start
                )
                notify_at = occurrence_start - timedelta(minutes=minutes)
                created_at = datetime.strptime(str(row["created_at"]), DATETIME_FMT)
                if notify_at < created_at:
                    continue
                if notify_at > now or notify_at < now - timedelta(days=7):
                    continue
                log = self.conn.execute(
                    "SELECT state,due_at FROM schedule_notification_log "
                    "WHERE notification_id=? AND occurrence_at=?",
                    (row["notification_id"], occurrence.key),
                ).fetchone()
                if log is not None:
                    if log["state"] == "done":
                        continue
                    if log["state"] == "snoozed" and str(log["due_at"]) > now.strftime(DATETIME_FMT):
                        continue
                due.append({
                    "kind": "schedule", "notification_id": int(row["notification_id"]),
                    "occurrence_at": occurrence.key, "item_id": int(row["id"]),
                    "note_id": int(row["note_id"]) if row["note_id"] else None,
                    "title": str(row["title"]), "details": str(row["details"]),
                    "start_at": occurrence_start.strftime(DATETIME_FMT), "item_type": str(row["item_type"]),
                })
        return due

    def notification_overview(self, start: datetime | None = None, days: int = 90) -> list[dict]:
        """Return upcoming schedule-notification occurrences for the shared alert centre."""
        range_start = start or datetime.now()
        range_end = range_start + timedelta(days=max(1, int(days)))
        rows = self.conn.execute(
            "SELECT schedule_items.*, schedule_notifications.id AS notification_id, "
            "schedule_notifications.minutes_before FROM schedule_items "
            "JOIN schedule_notifications ON schedule_notifications.item_id=schedule_items.id "
            "WHERE schedule_items.deleted_at='' AND schedule_items.status!='completed' "
            "ORDER BY schedule_items.start_at,schedule_items.id"
        ).fetchall()
        result = []
        for row in rows:
            for occurrence in expand_occurrences(row, range_start, range_end):
                exception = self.conn.execute(
                    "SELECT * FROM schedule_occurrence_exceptions WHERE item_id=? AND occurrence_at=?",
                    (row["id"], occurrence.key),
                ).fetchone()
                if exception is not None and exception["action"] == "skip":
                    continue
                event_at = (
                    datetime.strptime(exception["new_start_at"], DATETIME_FMT)
                    if exception is not None and exception["action"] == "move" else occurrence.start
                )
                notify_at = event_at - timedelta(minutes=int(row["minutes_before"]))
                log = self.conn.execute(
                    "SELECT state,due_at FROM schedule_notification_log "
                    "WHERE notification_id=? AND occurrence_at=?",
                    (row["notification_id"], occurrence.key),
                ).fetchone()
                if log is not None and log["state"] == "done":
                    continue
                if log is not None and log["state"] == "snoozed":
                    notify_at = datetime.strptime(str(log["due_at"]), DATETIME_FMT)
                result.append({
                    "source": "schedule", "id": int(row["notification_id"]), "item_id": int(row["id"]),
                    "occurrence_at": occurrence.key, "note_id": row["note_id"], "title": str(row["title"]),
                    "memo": str(row["details"]), "due_at": notify_at.strftime(DATETIME_FMT),
                    "event_at": event_at.strftime(DATETIME_FMT), "category": str(row["category"]),
                    "repeat_summary": "일정 알림",
                })
        return sorted(result, key=lambda item: (item["due_at"], item["item_id"], item["id"]))

    def notification_history(self, search: str = "") -> list[dict]:
        """Finished/snoozed schedule notification records for the shared history view."""
        rows = self.conn.execute(
            "SELECT schedule_notification_log.*, schedule_notifications.item_id, "
            "schedule_items.title,schedule_items.details,schedule_items.note_id,schedule_items.category "
            "FROM schedule_notification_log JOIN schedule_notifications "
            "ON schedule_notifications.id=schedule_notification_log.notification_id "
            "JOIN schedule_items ON schedule_items.id=schedule_notifications.item_id "
            "WHERE schedule_items.deleted_at='' ORDER BY schedule_notification_log.occurrence_at DESC"
        ).fetchall()
        text = search.strip().lower()
        result = []
        for row in rows:
            title, memo = str(row["title"]), str(row["details"])
            if text and text not in title.lower() and text not in memo.lower():
                continue
            result.append({
                "source": "schedule", "id": int(row["notification_id"]), "item_id": int(row["item_id"]),
                "occurrence_at": str(row["occurrence_at"]), "note_id": row["note_id"], "title": title,
                "memo": memo, "fired_at": str(row["occurrence_at"]), "action": str(row["state"]),
                "repeat_summary": "일정 알림", "category": str(row["category"]),
            })
        return result

    def complete_notification(self, notification_id: int, occurrence_at: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO schedule_notification_log(notification_id,occurrence_at,state,due_at) "
                "VALUES(?,?,'done','') ON CONFLICT(notification_id,occurrence_at) "
                "DO UPDATE SET state='done',due_at=''",
                (notification_id, occurrence_at),
            )

    def snooze_notification(self, notification_id: int, occurrence_at: str, minutes: int) -> None:
        due_at = (datetime.now() + timedelta(minutes=max(1, minutes))).strftime(DATETIME_FMT)
        with self.conn:
            self.conn.execute(
                "INSERT INTO schedule_notification_log(notification_id,occurrence_at,state,due_at) "
                "VALUES(?,?,'snoozed',?) ON CONFLICT(notification_id,occurrence_at) "
                "DO UPDATE SET state='snoozed',due_at=excluded.due_at",
                (notification_id, occurrence_at, due_at),
            )


def _normalized_item(values: dict) -> dict:
    start_at = str(values.get("start_at", ""))
    end_at = str(values.get("end_at", ""))
    start = datetime.strptime(start_at, DATETIME_FMT)
    end = datetime.strptime(end_at, DATETIME_FMT)
    if end <= start:
        raise ValueError("종료 시간은 시작 시간보다 뒤여야 합니다.")
    item_type = str(values.get("item_type", "event"))
    if item_type not in {"event", "task"}:
        raise ValueError("일정 종류를 확인해 주세요.")
    reminders = sorted({max(0, min(525600, int(value))) for value in values.get("reminders", [])})[:5]
    return {
        "title": str(values.get("title", "")).strip() or "새 일정",
        "details": str(values.get("details", "")), "item_type": item_type,
        "note_id": values.get("note_id") or None, "start_at": start_at, "end_at": end_at,
        "all_day": bool(values.get("all_day", False)), "category": str(values.get("category", "sky")),
        "priority": max(0, min(3, int(values.get("priority", 0)))),
        "status": "completed" if values.get("status") == "completed" else "pending",
        "recurrence_rule": values.get("recurrence_rule", {}), "hotkey": str(values.get("hotkey", "")).strip(),
        "hotkey_action": "postit" if values.get("hotkey_action") == "postit" else "open",
        "count_as_dday": bool(values.get("count_as_dday", False)) if item_type == "task" else False,
        "reminders": reminders,
    }


def _now_key() -> str:
    return datetime.now().strftime(DATETIME_FMT)
