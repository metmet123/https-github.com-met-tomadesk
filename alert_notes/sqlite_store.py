from __future__ import annotations

import os
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .reminder_recurrence_store import ReminderRecurrenceStoreMixin
from .reminder_store import REMINDER_SELECT, ReminderStoreMixin
from .monthly_rule import dump_rule, parse_rule
from .schedule_store import ScheduleStore
from .sync_identity import new_sync_id, utc_now_ms
from .memo_data_service import MemoDataService


DATETIME_FMT = "%Y%m%d%H%M"
NOTE_COLUMNS = (
    "id", "title", "content", "postit", "postit_visible", "postit_startup",
    "postit_display_mode", "always_on_top", "color", "opacity",
    "background_transparency",
    "input_locked", "d_day_at", "d_day_label", "d_day_alert", "d_day_done_at",
    "monthly_rule", "monthly_shown_for",
    "hotkey", "hotkey_action", "created_at", "updated_at", "deleted_at",
    "parent_id", "sort_order", "embedded", "pinned",
    "sync_id", "revision", "modified_at_utc", "origin_device_id", "category_id",
    "conflict_of_sync_id",
)
# 부모가 없는 메모.  지금까지의 모든 메모가 여기에 해당한다.
TOP_LEVEL_PARENT = 0
ATTACHMENT_COLUMNS = (
    "id", "note_id", "mime_type", "data_base64", "width", "height", "created_at",
    "sync_id", "revision", "modified_at_utc", "origin_device_id",
)
CATEGORY_COLUMNS = (
    "id", "sync_id", "name", "color", "sort_order", "revision",
    "created_at_utc", "modified_at_utc", "origin_device_id",
)
REMINDER_COLUMNS = (
    "id", "note_id", "due_at", "memo", "status", "created_at", "series_id",
    "occurrence_kind", "scheduled_at",
)
SERIES_COLUMNS = (
    "id", "note_id", "memo", "rule_type", "weekdays", "month_day", "end_type",
    "end_date", "max_occurrences", "generated_count", "active", "summary", "created_at", "updated_at",
)
HISTORY_COLUMNS = (
    "id", "note_id", "memo", "fired_at", "action", "series_id", "repeat_summary", "occurrence_kind",
)
SETTING_COLUMNS = ("key", "value")


class NoteReminderStore(ReminderStoreMixin, ReminderRecurrenceStoreMixin):
    """SQLite repository for notes, multiple reminders, recurrence, and history."""

    def __init__(self, path: Path, default_title: str = "New note"):
        self.path = Path(path)
        self.default_title = str(default_title).strip() or "New note"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.upgrade_backup_path = self._backup_before_upgrade()
        self._init_schema()
        self.schedules = ScheduleStore(self.conn)
        self.memo_data = MemoDataService(self)

    def _backup_before_upgrade(self) -> Path | None:
        tables = {
            str(row[0]) for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "notes" not in tables:
            return None
        needs_schedule = "schedule_items" not in tables
        schedule_columns = (
            {str(row[1]) for row in self.conn.execute("PRAGMA table_info(schedule_items)")}
            if "schedule_items" in tables else set()
        )
        needs_schedule_shape = bool(schedule_columns) and not {
            "count_as_dday", "time_mode"
        }.issubset(schedule_columns)
        note_columns = {str(row[1]) for row in self.conn.execute("PRAGMA table_info(notes)")}
        needs_notes = not {
            "postit_visible", "postit_startup", "postit_display_mode", "background_transparency",
            "d_day_at", "d_day_label", "d_day_alert", "parent_id", "sort_order",
            "embedded", "pinned", "sync_id", "revision", "modified_at_utc",
            "origin_device_id", "category_id", "conflict_of_sync_id",
        }.issubset(note_columns)
        attachment_columns = (
            {str(row[1]) for row in self.conn.execute("PRAGMA table_info(note_attachments)")}
            if "note_attachments" in tables else set()
        )
        needs_attachments = "note_attachments" not in tables or not {
            "sync_id", "revision", "modified_at_utc", "origin_device_id",
        }.issubset(attachment_columns)
        needs_sync = not {
            "memo_categories", "sync_tombstones", "memo_annotations",
            "memo_templates", "memo_versions",
        }.issubset(tables)
        needs_reminders = "reminders" in tables and self._reminders_need_rebuild()
        needs_support = "reminders" in tables and not {"reminder_series", "reminder_history"}.issubset(tables)
        if not (
            needs_schedule or needs_schedule_shape or needs_notes or needs_attachments
            or needs_reminders or needs_support or needs_sync
        ):
            return None
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        target = self.path.with_name(f"alert_notes_before_upgrade_{stamp}.db")
        target_conn = sqlite3.connect(target)
        try:
            self.conn.backup(target_conn)
        finally:
            target_conn.close()
        return target

    def _reminders_need_rebuild(self) -> bool:
        columns = {str(row[1]) for row in self.conn.execute("PRAGMA table_info(reminders)")}
        required = {"series_id", "occurrence_kind", "scheduled_at"}
        if not required.issubset(columns):
            return True
        for index in self.conn.execute("PRAGMA index_list(reminders)"):
            if not int(index[2]):
                continue
            names = [str(row[2]) for row in self.conn.execute(f"PRAGMA index_info('{index[1]}')")]
            if names == ["note_id"]:
                return True
        return False

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT 'New note', content TEXT NOT NULL DEFAULT '',
                postit INTEGER NOT NULL DEFAULT 0, postit_visible INTEGER NOT NULL DEFAULT 0,
                postit_startup INTEGER NOT NULL DEFAULT 0,
                postit_display_mode TEXT NOT NULL DEFAULT 'normal',
                always_on_top INTEGER NOT NULL DEFAULT 1,
                color TEXT NOT NULL DEFAULT 'vanilla', opacity INTEGER NOT NULL DEFAULT 100,
                background_transparency INTEGER NOT NULL DEFAULT 0,
                input_locked INTEGER NOT NULL DEFAULT 0,
                d_day_at TEXT NOT NULL DEFAULT '', d_day_label TEXT NOT NULL DEFAULT '',
                d_day_alert INTEGER NOT NULL DEFAULT 0,
                d_day_done_at TEXT NOT NULL DEFAULT '',
                monthly_rule TEXT NOT NULL DEFAULT '',
                monthly_shown_for TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                deleted_at TEXT NOT NULL DEFAULT '',
                parent_id INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                embedded INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0,
                sync_id TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1,
                modified_at_utc TEXT NOT NULL DEFAULT '', origin_device_id TEXT NOT NULL DEFAULT '',
                category_id INTEGER, conflict_of_sync_id TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS note_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, note_id INTEGER NOT NULL,
                mime_type TEXT NOT NULL, data_base64 TEXT NOT NULL,
                width INTEGER NOT NULL, height INTEGER NOT NULL, created_at TEXT NOT NULL,
                sync_id TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1,
                modified_at_utc TEXT NOT NULL DEFAULT '', origin_device_id TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_note_attachments_note ON note_attachments(note_id);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memo_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sync_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE, color TEXT NOT NULL DEFAULT '#64748b',
                sort_order INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
                created_at_utc TEXT NOT NULL, modified_at_utc TEXT NOT NULL,
                origin_device_id TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS sync_tombstones (
                entity_type TEXT NOT NULL, sync_id TEXT NOT NULL, revision INTEGER NOT NULL,
                deleted_at_utc TEXT NOT NULL, origin_device_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(entity_type,sync_id)
            );
            CREATE TABLE IF NOT EXISTS memo_annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sync_id TEXT NOT NULL UNIQUE,
                memo_id INTEGER NOT NULL, block_id TEXT NOT NULL DEFAULT '',
                start_offset INTEGER NOT NULL DEFAULT 0, end_offset INTEGER NOT NULL DEFAULT 0,
                quote TEXT NOT NULL DEFAULT '', context_before TEXT NOT NULL DEFAULT '',
                context_after TEXT NOT NULL DEFAULT '', comment TEXT NOT NULL,
                location_status TEXT NOT NULL DEFAULT 'resolved', revision INTEGER NOT NULL DEFAULT 1,
                created_at_utc TEXT NOT NULL, modified_at_utc TEXT NOT NULL,
                origin_device_id TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(memo_id) REFERENCES notes(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_memo_annotations_memo ON memo_annotations(memo_id);
            CREATE TABLE IF NOT EXISTS memo_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sync_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE, trigger TEXT NOT NULL COLLATE NOCASE UNIQUE,
                sort_order INTEGER NOT NULL DEFAULT 0, payload_version INTEGER NOT NULL DEFAULT 1,
                payload_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                created_at_utc TEXT NOT NULL, modified_at_utc TEXT NOT NULL,
                origin_device_id TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS memo_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sync_id TEXT NOT NULL UNIQUE,
                memo_id INTEGER NOT NULL, payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'auto', important INTEGER NOT NULL DEFAULT 0,
                created_at_utc TEXT NOT NULL, origin_device_id TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(memo_id) REFERENCES notes(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_memo_versions_memo_created
                ON memo_versions(memo_id,created_at_utc DESC,id DESC);
            CREATE TABLE IF NOT EXISTS reminder_series (
                id INTEGER PRIMARY KEY AUTOINCREMENT, note_id INTEGER, memo TEXT NOT NULL,
                rule_type TEXT NOT NULL, weekdays TEXT NOT NULL DEFAULT '[]', month_day INTEGER,
                end_type TEXT NOT NULL DEFAULT 'never', end_date TEXT, max_occurrences INTEGER,
                generated_count INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1,
                summary TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL
            );
            """
        )
        self._ensure_note_columns()
        self._ensure_attachment_columns()
        self._ensure_sync_rows()
        if not self._table_exists("reminders"):
            self._create_reminders_table()
        elif self._reminders_need_rebuild():
            self._rebuild_reminders_table()
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reminder_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, note_id INTEGER, memo TEXT NOT NULL,
                fired_at TEXT NOT NULL, action TEXT NOT NULL DEFAULT 'completed', series_id INTEGER,
                repeat_summary TEXT NOT NULL DEFAULT '', occurrence_kind TEXT NOT NULL DEFAULT 'regular',
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_note_status ON reminders(note_id,status);
            CREATE INDEX IF NOT EXISTS idx_reminders_due_status ON reminders(due_at,status);
            CREATE INDEX IF NOT EXISTS idx_history_fired ON reminder_history(fired_at);
            """
        )
        self.conn.commit()

    def _create_reminders_table(self, name: str = "reminders") -> None:
        self.conn.execute(
            f"""CREATE TABLE {name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT, note_id INTEGER NOT NULL, due_at TEXT NOT NULL,
                memo TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
                series_id INTEGER, occurrence_kind TEXT NOT NULL DEFAULT 'regular', scheduled_at TEXT,
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY(series_id) REFERENCES reminder_series(id) ON DELETE SET NULL
            )"""
        )

    def _rebuild_reminders_table(self) -> None:
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self._create_reminders_table("reminders_new")
            old_columns = {str(row[1]) for row in self.conn.execute("PRAGMA table_info(reminders)")}
            series = "series_id" if "series_id" in old_columns else "NULL"
            kind = "occurrence_kind" if "occurrence_kind" in old_columns else "'regular'"
            scheduled = "COALESCE(scheduled_at,due_at)" if "scheduled_at" in old_columns else "due_at"
            self.conn.execute(
                "INSERT INTO reminders_new(id,note_id,due_at,memo,status,created_at,series_id,"
                f"occurrence_kind,scheduled_at) SELECT id,note_id,due_at,memo,status,created_at,{series},"
                f"{kind},{scheduled} FROM reminders"
            )
            self.conn.execute("DROP TABLE reminders")
            self.conn.execute("ALTER TABLE reminders_new RENAME TO reminders")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            self.conn.execute("PRAGMA foreign_keys = ON")

    def _ensure_note_columns(self) -> None:
        columns = {str(row[1]) for row in self.conn.execute("PRAGMA table_info(notes)")}
        if "postit_visible" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN postit_visible INTEGER NOT NULL DEFAULT 0")
            self.conn.execute("UPDATE notes SET postit_visible=postit")
        if "postit_startup" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN postit_startup INTEGER NOT NULL DEFAULT 0")
            self.conn.execute("UPDATE notes SET postit_startup=postit")
        if "postit_display_mode" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN postit_display_mode TEXT NOT NULL DEFAULT 'normal'")
        if "background_transparency" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN background_transparency INTEGER NOT NULL DEFAULT 0")
            self.conn.execute(
                "UPDATE notes SET background_transparency=MAX(0,MIN(100,100-opacity))"
            )
        if "d_day_at" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN d_day_at TEXT NOT NULL DEFAULT ''")
        if "d_day_label" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN d_day_label TEXT NOT NULL DEFAULT ''")
        if "d_day_alert" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN d_day_alert INTEGER NOT NULL DEFAULT 0")
        if "d_day_done_at" not in columns:
            # When the user stops the countdown; the D-Day itself is never removed.
            self.conn.execute("ALTER TABLE notes ADD COLUMN d_day_done_at TEXT NOT NULL DEFAULT ''")
        if "monthly_rule" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN monthly_rule TEXT NOT NULL DEFAULT ''")
        if "monthly_shown_for" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN monthly_shown_for TEXT NOT NULL DEFAULT ''")
        if "hotkey" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN hotkey TEXT NOT NULL DEFAULT ''")
        if "hotkey_action" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN hotkey_action TEXT NOT NULL DEFAULT 'open'")
        if "deleted_at" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN deleted_at TEXT NOT NULL DEFAULT ''")
        if "parent_id" not in columns:
            # 0 은 부모 없음.  지금까지의 메모는 모두 그대로 맨 위층에 남는다.
            self.conn.execute("ALTER TABLE notes ADD COLUMN parent_id INTEGER NOT NULL DEFAULT 0")
        if "sort_order" not in columns:
            # 0 은 "직접 끌어 옮긴 적 없음".  그때는 수정 시간 순으로 놓인다.
            self.conn.execute("ALTER TABLE notes ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        if "embedded" not in columns:
            # 1 은 "본문 안에만 사는 페이지".  메모 목록에는 내놓지 않는다.
            self.conn.execute("ALTER TABLE notes ADD COLUMN embedded INTEGER NOT NULL DEFAULT 0")
        if "pinned" not in columns:
            # 1 은 "목록 맨 위에 고정".  형제들 가운데 늘 먼저 놓인다.
            self.conn.execute("ALTER TABLE notes ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        if "sync_id" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN sync_id TEXT NOT NULL DEFAULT ''")
        if "revision" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
        if "modified_at_utc" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN modified_at_utc TEXT NOT NULL DEFAULT ''")
        if "origin_device_id" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN origin_device_id TEXT NOT NULL DEFAULT ''")
        if "category_id" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN category_id INTEGER")
        if "conflict_of_sync_id" not in columns:
            self.conn.execute("ALTER TABLE notes ADD COLUMN conflict_of_sync_id TEXT NOT NULL DEFAULT ''")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_parent ON notes(parent_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(category_id)")

    def _ensure_attachment_columns(self) -> None:
        columns = {str(row[1]) for row in self.conn.execute("PRAGMA table_info(note_attachments)")}
        additions = {
            "sync_id": "TEXT NOT NULL DEFAULT ''",
            "revision": "INTEGER NOT NULL DEFAULT 1",
            "modified_at_utc": "TEXT NOT NULL DEFAULT ''",
            "origin_device_id": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.conn.execute(f"ALTER TABLE note_attachments ADD COLUMN {name} {definition}")

    def _ensure_sync_rows(self) -> None:
        device_id = self.setting("sync_device_id", "").strip()
        if not device_id:
            device_id = new_sync_id()
            self.conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('sync_device_id',?)", (device_id,))
        stamp = utc_now_ms()
        for table in ("notes", "note_attachments"):
            rows = self.conn.execute(f"SELECT id FROM {table} WHERE sync_id='' OR sync_id IS NULL").fetchall()
            self.conn.executemany(
                f"UPDATE {table} SET sync_id=?,modified_at_utc=CASE WHEN modified_at_utc='' THEN ? ELSE modified_at_utc END,"
                "origin_device_id=CASE WHEN origin_device_id='' THEN ? ELSE origin_device_id END WHERE id=?",
                ((new_sync_id(), stamp, device_id, int(row["id"])) for row in rows),
            )
            self.conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_sync_id ON {table}(sync_id)")
        if not self.conn.execute("SELECT 1 FROM memo_categories LIMIT 1").fetchone():
            for index, (name, color) in enumerate((('업무', '#3b82f6'), ('개발', '#8b5cf6'), ('자료', '#10b981')), 1):
                self.conn.execute(
                    "INSERT INTO memo_categories(sync_id,name,color,sort_order,revision,created_at_utc,modified_at_utc,origin_device_id) "
                    "VALUES(?,?,?,?,1,?,?,?)",
                    (new_sync_id(), name, color, index, stamp, stamp, device_id),
                )

    def _table_exists(self, name: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
        ).fetchone() is not None

    def create_note(self, title: str | None = None, content: str = "", *, d_day_at: str = "") -> int:
        # Optional, silent D-Day is inserted with the note in one transaction.
        # This avoids an orphan note if the second half of an OCR save fails.
        due = str(d_day_at or "")
        if due and (len(due) != 12 or not due.isascii() or not due.isdigit()):
            raise ValueError("올바른 D-Day 날짜·시간이 필요합니다.")
        if due:
            datetime.strptime(due, DATETIME_FMT)
        stamp = self._now_key()
        sync_stamp = utc_now_ms()
        resolved_title = str(title or "").strip() or self.default_title
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO notes(title,content,created_at,updated_at,sync_id,revision,modified_at_utc,origin_device_id,d_day_at,d_day_label,d_day_alert) "
                "VALUES(?,?,?,?,?,1,?,?,?,?,0)",
                (resolved_title, content, stamp, stamp,
                 new_sync_id(), sync_stamp, self.device_id, due, resolved_title if due else ""),
            )
        return int(cursor.lastrowid)

    def note(self, note_id: int):
        return self.conn.execute(_NOTE_SELECT + " WHERE notes.id=? AND notes.deleted_at=''", (note_id,)).fetchone()

    def notes(self, search: str = "") -> list[sqlite3.Row]:
        text = search.strip()
        if not text:
            return list(self.conn.execute(_NOTE_SELECT + " WHERE notes.deleted_at='' ORDER BY notes.updated_at DESC,notes.id DESC"))
        like = f"%{text}%"
        return list(self.conn.execute(
            _NOTE_SELECT + " WHERE notes.deleted_at='' AND (notes.title LIKE ? OR notes.content LIKE ?) "
            "ORDER BY notes.updated_at DESC,notes.id DESC", (like, like),
        ))

    # ------------------------------------------------------------- 메모 층 --
    def child_notes(self, parent_id: int = TOP_LEVEL_PARENT) -> list[sqlite3.Row]:
        """한 메모 바로 아래의 메모들.

        직접 끌어 옮긴 것(sort_order 가 0 이 아닌 것)이 먼저, 그 안에서는 놓은
        차례대로.  나머지는 지금까지처럼 수정 시간 최신순이다.
        """
        return list(self.conn.execute(
            _NOTE_SELECT + " WHERE notes.deleted_at='' AND notes.parent_id=? "
            "ORDER BY notes.pinned DESC,"
            "CASE WHEN notes.sort_order=0 THEN 1 ELSE 0 END,"
            "notes.sort_order,notes.updated_at DESC,notes.id DESC",
            (int(parent_id),),
        ))

    def note_descendants(self, note_id: int, include_trashed: bool = False) -> list[int]:
        """그 메모 안에 든 모든 메모의 번호.  자기 자신은 빼고 위에서부터."""
        found: list[int] = []
        seen = {int(note_id)}
        frontier = [int(note_id)]
        where = "" if include_trashed else " AND deleted_at=''"
        while frontier:
            rows = self.conn.execute(
                f"SELECT id FROM notes WHERE parent_id=?{where} ORDER BY sort_order,id",
                (frontier.pop(0),),
            ).fetchall()
            for row in rows:
                child = int(row["id"])
                # 어쩌다 고리가 생기더라도 여기서 멈춘다.  무한히 돌지 않는다.
                if child in seen:
                    continue
                seen.add(child)
                found.append(child)
                frontier.append(child)
        return found

    def note_path(self, note_id: int) -> list[sqlite3.Row]:
        """맨 위층부터 이 메모까지.  편집창의 위치 표시줄이 쓴다."""
        chain: list[sqlite3.Row] = []
        seen: set[int] = set()
        current = int(note_id)
        while current and current not in seen:
            seen.add(current)
            row = self.conn.execute(
                _NOTE_SELECT + " WHERE notes.id=? AND notes.deleted_at=''", (current,),
            ).fetchone()
            if row is None:
                break
            chain.append(row)
            current = int(row["parent_id"] or TOP_LEVEL_PARENT)
        chain.reverse()
        return chain

    def create_child_note(
        self, parent_id: int, title: str | None = None, embedded: bool = False,
    ) -> int:
        """메모 안에 사는 메모를 만든다.  형제들 끝에 붙는다.

        `embedded` 는 본문에 넣은 페이지다.  목록에는 내놓지 않고 본문의 줄로만
        오간다.  목록의 + 로 만든 하위 메모는 목록에 그대로 보인다.
        """
        note_id = self.create_note(title)
        if int(parent_id) != TOP_LEVEL_PARENT:
            self.set_note_parent(note_id, int(parent_id))
            parent = self.conn.execute("SELECT category_id FROM notes WHERE id=?", (int(parent_id),)).fetchone()
            if parent is not None and parent["category_id"] is not None:
                self._touch_note(note_id, {"category_id": int(parent["category_id"])})
                self.conn.commit()
        if embedded:
            self._touch_note(note_id, {"embedded": 1})
            self.conn.commit()
        return note_id

    def set_note_embedded(self, note_id: int, embedded: bool) -> None:
        """Switch page/list visibility without changing ownership or content."""
        with self.conn:
            self._touch_note(note_id, {"embedded": int(bool(embedded))})

    def can_reparent(self, note_id: int, parent_id: int) -> bool:
        """A 를 A 안으로, 또는 자기 안의 메모 밑으로 넣으려는 것을 막는다."""
        note_id, parent_id = int(note_id), int(parent_id)
        if parent_id == TOP_LEVEL_PARENT:
            return True
        if parent_id == note_id:
            return False
        if self.conn.execute("SELECT 1 FROM notes WHERE id=?", (parent_id,)).fetchone() is None:
            return False
        return parent_id not in self.note_descendants(note_id, include_trashed=True)

    def set_note_parent(self, note_id: int, parent_id: int, position: int | None = None) -> bool:
        """메모를 다른 메모 안으로 옮긴다.  고리가 생기면 옮기지 않는다."""
        note_id, parent_id = int(note_id), int(parent_id)
        if not self.can_reparent(note_id, parent_id):
            return False
        siblings = [
            int(row["id"]) for row in self.child_notes(parent_id) if int(row["id"]) != note_id
        ]
        index = len(siblings) if position is None else max(0, min(int(position), len(siblings)))
        siblings.insert(index, note_id)
        with self.conn:
            self._touch_note(note_id, {"parent_id": parent_id, "updated_at": self._now_key()})
            self._write_sort_order(siblings)
        return True

    def group_notes(self, note_ids, title: str = "새 묶음", parent_id: int | None = None) -> int:
        """선택 메모를 새 부모 아래로 묶고 새 부모 ID를 돌려준다.

        부모와 그 자식이 함께 선택된 경우 부모만 이동한다. 같은 부모 아래의
        메모들이면 그 자리에 묶음을 만들고, 서로 다른 층이면 위치를 지정해야 한다.
        """
        ordered = list(dict.fromkeys(int(value) for value in note_ids))
        hierarchy = {
            int(row["id"]): int(row["parent_id"] or TOP_LEVEL_PARENT)
            for row in self.conn.execute("SELECT id,parent_id FROM notes WHERE deleted_at='' ")
        }
        selected = {value for value in ordered if value in hierarchy}
        roots = []
        for note_id in ordered:
            if note_id not in selected:
                continue
            parent = hierarchy.get(note_id, TOP_LEVEL_PARENT)
            seen = {note_id}
            nested = False
            while parent and parent not in seen:
                if parent in selected:
                    nested = True
                    break
                seen.add(parent)
                parent = hierarchy.get(parent, TOP_LEVEL_PARENT)
            if not nested:
                roots.append(note_id)
        if len(roots) < 2:
            raise ValueError("서로 독립된 메모를 2개 이상 선택해 주세요.")

        rows = [self.note(note_id) for note_id in roots]
        if any(row is None for row in rows):
            raise ValueError("선택한 메모를 찾을 수 없습니다.")
        parent_ids = {int(row["parent_id"] or TOP_LEVEL_PARENT) for row in rows}
        if parent_id is None:
            if len(parent_ids) != 1:
                raise ValueError("서로 다른 부모의 메모입니다. 묶을 위치를 선택해 주세요.")
            parent_id = next(iter(parent_ids))
        parent_id = int(parent_id)
        if parent_id != TOP_LEVEL_PARENT and parent_id not in hierarchy:
            raise ValueError("묶을 위치를 찾을 수 없습니다.")
        if any(not self.can_reparent(note_id, parent_id) for note_id in roots):
            raise ValueError("선택 메모 자신이나 그 하위에는 묶을 수 없습니다.")
        category_ids = {row["category_id"] for row in rows}
        category_id = category_ids.pop() if len(category_ids) == 1 else None
        siblings = [int(row["id"]) for row in self.child_notes(parent_id)]
        positions = [siblings.index(note_id) for note_id in roots if note_id in siblings]
        insert_at = min(positions) if positions else len(siblings)
        remaining = [note_id for note_id in siblings if note_id not in set(roots)]

        stamp = self._now_key()
        sync_stamp = utc_now_ms()
        resolved_title = str(title or "").strip() or "새 묶음"
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO notes(title,content,created_at,updated_at,parent_id,category_id,"
                "sync_id,revision,modified_at_utc,origin_device_id) "
                "VALUES(?,'',?,?,?,?,?,1,?,?)",
                (
                    resolved_title, stamp, stamp, int(parent_id), category_id,
                    new_sync_id(), sync_stamp, self.device_id,
                ),
            )
            group_id = int(cursor.lastrowid)
            for note_id in roots:
                self._touch_note(note_id, {"parent_id": group_id})
            self._write_sort_order(roots)
            remaining.insert(max(0, min(insert_at, len(remaining))), group_id)
            self._write_sort_order(remaining)
        return group_id

    def reorder_notes(self, parent_id: int, ordered_ids) -> None:
        """끌어 놓은 차례를 그대로 굳힌다."""
        wanted = [int(value) for value in ordered_ids]
        actual = {int(row["id"]) for row in self.child_notes(parent_id)}
        with self.conn:
            self._write_sort_order([value for value in wanted if value in actual])

    def _write_sort_order(self, ordered_ids) -> None:
        # 1 부터 매긴다.  0 은 "아직 직접 옮긴 적 없음" 이라는 뜻으로 남겨 둔다.
        for index, value in enumerate(ordered_ids, start=1):
            self._touch_note(int(value), {"sort_order": index})

    @property
    def device_id(self) -> str:
        return self.setting("sync_device_id", "")

    def _touch_note(self, note_id: int, values: dict | None = None) -> None:
        updates = dict(values or {})
        updates.update(modified_at_utc=utc_now_ms(), origin_device_id=self.device_id)
        fields = ",".join(f"{key}=?" for key in updates)
        self.conn.execute(
            f"UPDATE notes SET {fields},revision=revision+1 WHERE id=?",
            [*updates.values(), int(note_id)],
        )

    def note_by_sync_id(self, sync_id: str, include_trashed: bool = False):
        deleted = "" if include_trashed else " AND deleted_at=''"
        return self.conn.execute(
            f"SELECT * FROM notes WHERE sync_id=?{deleted}", (str(sync_id),),
        ).fetchone()

    # ------------------------------------------------------- 카테고리 --
    def categories(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM memo_categories ORDER BY sort_order,name COLLATE NOCASE,id"
        ))

    def category(self, category_id: int):
        return self.conn.execute(
            "SELECT * FROM memo_categories WHERE id=?", (int(category_id),),
        ).fetchone()

    def create_category(self, name: str, color: str = "#64748b") -> int:
        clean = str(name or "").strip()
        if not clean:
            raise ValueError("카테고리 이름을 입력하세요.")
        stamp = utc_now_ms()
        position = int(self.conn.execute(
            "SELECT COALESCE(MAX(sort_order),0)+1 FROM memo_categories"
        ).fetchone()[0])
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO memo_categories(sync_id,name,color,sort_order,revision,created_at_utc,modified_at_utc,origin_device_id) "
                "VALUES(?,?,?,?,1,?,?,?)",
                (new_sync_id(), clean, str(color or "#64748b"), position, stamp, stamp, self.device_id),
            )
        return int(cursor.lastrowid)

    def update_category(self, category_id: int, *, name: str | None = None, color: str | None = None) -> None:
        updates: dict[str, object] = {}
        if name is not None:
            clean = str(name).strip()
            if not clean:
                raise ValueError("카테고리 이름을 입력하세요.")
            updates["name"] = clean
        if color is not None:
            updates["color"] = str(color or "#64748b")
        if not updates:
            return
        updates.update(modified_at_utc=utc_now_ms(), origin_device_id=self.device_id)
        fields = ",".join(f"{key}=?" for key in updates)
        with self.conn:
            self.conn.execute(
                f"UPDATE memo_categories SET {fields},revision=revision+1 WHERE id=?",
                [*updates.values(), int(category_id)],
            )

    def reorder_categories(self, ordered_ids) -> None:
        actual = {int(row["id"]) for row in self.categories()}
        ordered = [int(value) for value in ordered_ids if int(value) in actual]
        ordered.extend(sorted(actual - set(ordered)))
        stamp = utc_now_ms()
        with self.conn:
            for position, category_id in enumerate(ordered, 1):
                self.conn.execute(
                    "UPDATE memo_categories SET sort_order=?,revision=revision+1,modified_at_utc=?,origin_device_id=? WHERE id=?",
                    (position, stamp, self.device_id, category_id),
                )

    def set_note_category(self, note_id: int, category_id: int | None) -> None:
        if category_id is not None and self.category(int(category_id)) is None:
            raise ValueError("카테고리를 찾을 수 없습니다.")
        with self.conn:
            self._touch_note(int(note_id), {"category_id": None if category_id is None else int(category_id)})

    def set_notes_category(self, note_ids, category_id: int | None) -> None:
        if category_id is not None and self.category(int(category_id)) is None:
            raise ValueError("카테고리를 찾을 수 없습니다.")
        with self.conn:
            for note_id in {int(value) for value in note_ids}:
                self._touch_note(note_id, {"category_id": None if category_id is None else int(category_id)})

    def delete_category(self, category_id: int) -> None:
        row = self.category(category_id)
        if row is None:
            return
        stamp = utc_now_ms()
        with self.conn:
            note_ids = [int(item["id"]) for item in self.conn.execute(
                "SELECT id FROM notes WHERE category_id=?", (int(category_id),)
            )]
            for note_id in note_ids:
                self._touch_note(note_id, {"category_id": None})
            self._write_tombstone("memo_category", str(row["sync_id"]), int(row["revision"]) + 1, stamp)
            self.conn.execute("DELETE FROM memo_categories WHERE id=?", (int(category_id),))

    def _write_tombstone(self, entity_type: str, sync_id: str, revision: int, stamp: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO sync_tombstones(entity_type,sync_id,revision,deleted_at_utc,origin_device_id) "
            "VALUES(?,?,?,?,?) ON CONFLICT(entity_type,sync_id) DO UPDATE SET "
            "revision=MAX(revision,excluded.revision),deleted_at_utc=excluded.deleted_at_utc,"
            "origin_device_id=excluded.origin_device_id",
            (str(entity_type), str(sync_id), int(revision), stamp or utc_now_ms(), self.device_id),
        )

    def deadline_notes(self, search: str = "") -> list[sqlite3.Row]:
        """Active D-Day notes, closest deadline first, for the calendar navigator."""
        where = "WHERE notes.deleted_at='' AND notes.d_day_at!=''"
        args: tuple = ()
        if search.strip():
            like = f"%{search.strip()}%"
            where += " AND (notes.title LIKE ? OR notes.d_day_label LIKE ?)"
            args = (like, like)
        return list(self.conn.execute(
            _NOTE_SELECT + where + " ORDER BY notes.d_day_at,notes.id", args,
        ))

    def update_note(self, note_id: int, **values) -> None:
        allowed = {
            "title", "content", "postit", "postit_visible", "postit_startup", "postit_display_mode",
            "always_on_top", "color", "opacity",
            "background_transparency",
            "input_locked", "d_day_at", "d_day_label", "d_day_alert", "hotkey", "hotkey_action",
            "pinned",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        if "title" in updates:
            updates["title"] = str(updates["title"]).strip() or self.default_title
        for key in (
            "postit", "postit_visible", "postit_startup", "always_on_top", "input_locked",
            "d_day_alert", "pinned",
        ):
            if key in updates:
                updates[key] = int(bool(updates[key]))
        if "opacity" in updates:
            updates["opacity"] = max(50, min(100, int(updates["opacity"])))
        if "background_transparency" in updates:
            updates["background_transparency"] = max(0, min(100, int(updates["background_transparency"])))
        if "hotkey" in updates:
            updates["hotkey"] = str(updates["hotkey"]).strip()
        if "hotkey_action" in updates:
            updates["hotkey_action"] = "postit" if updates["hotkey_action"] == "postit" else "open"
        if "postit_display_mode" in updates:
            updates["postit_display_mode"] = (
                updates["postit_display_mode"] if updates["postit_display_mode"] in {"normal", "title", "badge"}
                else "normal"
            )
        for key in ("d_day_at", "d_day_label"):
            if key in updates:
                updates[key] = str(updates[key] or "").strip()
        if set(updates) != {"pinned"}:
            # 고정만 켜고 끄는 것은 메모를 고친 것이 아니다.  손댄 시각을 올리면
            # 목록에서 맨 위로 튀어 올라 순서가 흐트러진다.
            updates["updated_at"] = self._now_key()
        self._touch_note(note_id, updates)
        self.conn.commit()

    def add_attachment(
        self, note_id: int, mime_type: str, data_base64: str, width: int, height: int,
    ) -> int:
        cursor = self.conn.execute(
            "INSERT INTO note_attachments(note_id,mime_type,data_base64,width,height,created_at,sync_id,revision,modified_at_utc,origin_device_id) "
            "VALUES(?,?,?,?,?,?,?,1,?,?)",
            (int(note_id), str(mime_type), str(data_base64), int(width), int(height), self._now_key(),
             new_sync_id(), utc_now_ms(), self.device_id),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def attachment(self, attachment_id: int):
        return self.conn.execute(
            "SELECT * FROM note_attachments WHERE id=?", (int(attachment_id),),
        ).fetchone()

    def note_attachments(self, note_id: int) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM note_attachments WHERE note_id=? ORDER BY id", (int(note_id),),
        ))

    def delete_attachment(self, attachment_id: int) -> None:
        with self.conn:
            row = self.attachment(attachment_id)
            if row is not None:
                self._write_tombstone("attachment", row["sync_id"], int(row["revision"]) + 1)
            self.conn.execute("DELETE FROM note_attachments WHERE id=?", (int(attachment_id),))

    def prune_note_attachments(self, note_id: int, referenced_ids: set[int]) -> None:
        rows = self.note_attachments(note_id)
        stale = [int(row["id"]) for row in rows if int(row["id"]) not in referenced_ids]
        if not stale:
            return
        with self.conn:
            for value in stale:
                row = self.attachment(value)
                if row is not None:
                    self._write_tombstone("attachment", row["sync_id"], int(row["revision"]) + 1)
                self.conn.execute("DELETE FROM note_attachments WHERE id=?", (value,))

    def set_deadline(self, note_id: int, due_at: str, label: str = "", alert: bool = False) -> None:
        self._require_note(note_id)
        due = str(due_at or "").strip()
        if not due:
            self.clear_deadline(note_id)
            return
        memo = str(label or "").strip() or "D-Day"
        current = self.conn.execute(
            "SELECT id FROM reminders WHERE note_id=? AND occurrence_kind='deadline' "
            "AND status='pending' ORDER BY id LIMIT 1", (int(note_id),),
        ).fetchone()
        reminder_id = int(current["id"]) if current is not None else None
        with self.conn:
            self._touch_note(note_id, {
                "d_day_at": due, "d_day_label": memo, "d_day_alert": int(bool(alert)),
                "d_day_done_at": "", "updated_at": self._now_key(),
            })
            self._sync_day_before_reminder(note_id, due, memo, alert)
            if alert and reminder_id is None:
                cursor = self.conn.execute(
                    "INSERT INTO reminders(note_id,due_at,memo,status,created_at,occurrence_kind,scheduled_at) "
                    "VALUES(?,?,?,'pending',?,'deadline',?)",
                    (int(note_id), due, memo, self._now_key(), due),
                )
                reminder_id = int(cursor.lastrowid)
            elif alert:
                self.conn.execute(
                    "UPDATE reminders SET due_at=?,scheduled_at=?,memo=? WHERE id=?",
                    (due, due, memo, reminder_id),
                )
            elif reminder_id is not None:
                self.conn.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
        if alert and reminder_id is not None:
            self._sync_reminder(reminder_id)
        elif reminder_id is not None:
            self._remove_synced_reminder(reminder_id)

    def _sync_day_before_reminder(self, note_id: int, due: str, memo: str, alert: bool) -> None:
        """Optional heads-up 24h earlier, so the day itself is not the first warning."""
        self.conn.execute(
            "DELETE FROM reminders WHERE note_id=? AND occurrence_kind='deadline_prior' "
            "AND status='pending'", (int(note_id),),
        )
        wanted = alert and str(
            self.setting("deadline_notify_day_before", "true")
        ).lower() == "true"
        if not wanted:
            return
        try:
            earlier = datetime.strptime(due, DATETIME_FMT) - timedelta(days=1)
        except ValueError:
            return
        if earlier <= datetime.now():
            return
        stamp = earlier.strftime(DATETIME_FMT)
        self.conn.execute(
            "INSERT INTO reminders(note_id,due_at,memo,status,created_at,occurrence_kind,scheduled_at) "
            "VALUES(?,?,?,'pending',?,'deadline_prior',?)",
            (int(note_id), stamp, f"내일 {memo}", self._now_key(), stamp),
        )

    def set_monthly_rule(self, note_id: int, rule) -> None:
        """Attach or clear a monthly repeat; clearing also forgets the history."""
        self._require_note(note_id)
        text = dump_rule(parse_rule(rule)) if rule else ""
        with self.conn:
            self._touch_note(note_id, {
                "monthly_rule": text,
                "monthly_shown_for": "" if not text else self.note(note_id)["monthly_shown_for"],
                "updated_at": self._now_key(),
            })

    def monthly_notes(self) -> list:
        return list(self.conn.execute(
            _NOTE_SELECT + "WHERE notes.deleted_at='' AND notes.monthly_rule!='' "
            "ORDER BY notes.id"
        ))

    def mark_monthly_shown(self, note_id: int, month: str) -> None:
        with self.conn:
            self._touch_note(note_id, {"monthly_shown_for": str(month)})

    def finish_deadline(self, note_id: int, done: bool = True) -> None:
        """Stop counting without deleting the D-Day; it stays on the list."""
        self._require_note(note_id)
        stamp = self._now_key() if done else ""
        with self.conn:
            self._touch_note(note_id, {"d_day_done_at": stamp, "updated_at": self._now_key()})

    def clear_deadline(self, note_id: int) -> None:
        rows = list(self.conn.execute(
            "SELECT id FROM reminders WHERE note_id=? AND occurrence_kind='deadline' AND status='pending'",
            (int(note_id),),
        ))
        with self.conn:
            self._touch_note(note_id, {
                "d_day_at": "", "d_day_label": "", "d_day_alert": 0,
                "d_day_done_at": "", "updated_at": self._now_key(),
            })
            self.conn.execute(
                "DELETE FROM reminders WHERE note_id=? AND occurrence_kind IN ('deadline','deadline_prior') "
                "AND status='pending'",
                (int(note_id),),
            )
        for row in rows:
            self._remove_synced_reminder(int(row["id"]))

    def delete_note(self, note_id: int) -> None:
        """부모를 지우면 그 안의 메모도 한 덩어리로 휴지통에 들어간다."""
        stamp = self._now_key()
        targets = [int(note_id)] + self.note_descendants(note_id)
        with self.conn:
            for target in targets:
                self._touch_note(target, {"deleted_at": stamp, "postit_visible": 0, "updated_at": stamp})
                self.conn.execute(
                    "UPDATE schedule_items SET deleted_at=? WHERE note_id=? AND deleted_at=''",
                    (stamp, target),
                )

    def trashed_notes(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM notes WHERE deleted_at!='' ORDER BY deleted_at DESC,id DESC"
        ))

    def restore_note(self, note_id: int) -> None:
        """같이 버려진 하위 메모까지 함께 되살린다."""
        row = self.conn.execute(
            "SELECT deleted_at,parent_id FROM notes WHERE id=?", (note_id,),
        ).fetchone()
        if row is None:
            return
        stamp = str(row["deleted_at"] or "")
        # 함께 버려진 것만 되살린다.  따로 버렸던 하위 메모는 휴지통에 남는다.
        targets = [int(note_id)] + [
            child for child in self.note_descendants(note_id, include_trashed=True)
            if str((self.conn.execute(
                "SELECT deleted_at FROM notes WHERE id=?", (child,),
            ).fetchone() or {"deleted_at": ""})["deleted_at"] or "") == stamp
        ]
        parent_gone = bool(int(row["parent_id"] or 0)) and self.conn.execute(
            "SELECT 1 FROM notes WHERE id=? AND deleted_at=''", (int(row["parent_id"]),),
        ).fetchone() is None
        now = self._now_key()
        with self.conn:
            for target in targets:
                self._touch_note(target, {"deleted_at": "", "updated_at": now})
                self.conn.execute(
                    "UPDATE schedule_items SET deleted_at='' WHERE note_id=? AND deleted_at=?",
                    (target, stamp),
                )
            if parent_gone:
                # 부모가 아직 휴지통에 있으면 되살려도 보이지 않는다.  맨 위로 올린다.
                self._touch_note(int(note_id), {"parent_id": TOP_LEVEL_PARENT, "sort_order": 0})

    def purge_expired_trash(self, days: int = 7) -> int:
        cutoff = (datetime.now() - timedelta(days=max(1, days))).strftime(DATETIME_FMT)
        rows = self.conn.execute(
            "SELECT id,sync_id,revision FROM notes WHERE deleted_at!='' AND deleted_at<?", (cutoff,)
        ).fetchall()
        with self.conn:
            for row in rows:
                attachments = self.conn.execute(
                    "SELECT sync_id,revision FROM note_attachments WHERE note_id=?", (int(row["id"]),)
                ).fetchall()
                for attachment in attachments:
                    self._write_tombstone("attachment", attachment["sync_id"], int(attachment["revision"]) + 1)
                self._write_tombstone("note", row["sync_id"], int(row["revision"]) + 1)
                self.conn.execute("DELETE FROM notes WHERE id=?", (int(row["id"]),))
            # 부모가 영구 삭제된 메모가 사라진 번호를 붙들고 있으면 어디에도
            # 뜨지 않는다.  맨 위층으로 올려 둔다.
            self.conn.execute(
                "UPDATE notes SET parent_id=?,sort_order=0 WHERE parent_id!=? "
                "AND parent_id NOT IN (SELECT id FROM notes)",
                (TOP_LEVEL_PARENT, TOP_LEVEL_PARENT),
            )
        return len(rows)

    def create_note_with_reminder(self, title: str, content: str, due_at: str) -> int:
        note_id = self.create_note(title, content)
        self.add_reminder(note_id, due_at, content.strip() or title.strip())
        return note_id

    def list_schedule_items(self, start_at: str, end_at: str) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            REMINDER_SELECT + " WHERE reminders.status='pending' AND reminders.due_at>=? "
            "AND reminders.due_at<? ORDER BY reminders.due_at,reminders.id", (start_at, end_at),
        ))

    def setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row is not None else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def delete_setting(self, key: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM settings WHERE key=?", (key,))

    def purge_expired_memo_drafts(self, retention_days: int = 7) -> int:
        """Remove malformed or expired manual-save drafts from settings."""
        cutoff = datetime.now() - timedelta(days=max(1, int(retention_days)))
        expired: list[str] = []
        rows = self.conn.execute(
            "SELECT key,value FROM settings WHERE key LIKE 'memo_draft_%'"
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["value"]))
                saved_at = datetime.strptime(str(payload["saved_at"]), DATETIME_FMT)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                expired.append(str(row["key"]))
                continue
            if saved_at < cutoff:
                expired.append(str(row["key"]))
        if expired:
            with self.conn:
                self.conn.executemany("DELETE FROM settings WHERE key=?", ((key,) for key in expired))
        return len(expired)

    def backup_database(self, destination: Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"대상 데이터베이스가 이미 있습니다: {target}")
        handle = tempfile.NamedTemporaryFile(prefix=".notes-db-", suffix=".tmp", dir=target.parent, delete=False)
        temporary = Path(handle.name)
        handle.close()
        target_conn = sqlite3.connect(temporary)
        try:
            self.conn.backup(target_conn)
            target_conn.close()
            os.replace(temporary, target)
        finally:
            target_conn.close()
            temporary.unlink(missing_ok=True)
        return target

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def _now_key() -> str:
        return datetime.now().strftime(DATETIME_FMT)


def now_key() -> str:
    return datetime.now().strftime(DATETIME_FMT)


_NOTE_SELECT = """
SELECT notes.*,
       (SELECT id FROM reminders r WHERE r.note_id=notes.id AND r.status='pending'
        ORDER BY r.due_at,r.id LIMIT 1) AS reminder_id,
       (SELECT due_at FROM reminders r WHERE r.note_id=notes.id AND r.status='pending'
        ORDER BY r.due_at,r.id LIMIT 1) AS reminder_due_at,
       (SELECT memo FROM reminders r WHERE r.note_id=notes.id AND r.status='pending'
        ORDER BY r.due_at,r.id LIMIT 1) AS reminder_memo
FROM notes
"""
