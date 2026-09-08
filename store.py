import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from app_config import DATA_DIR
from app_utils import now_key
from sqlite_json_backup import export_tables_json, import_tables_json
from storage_config import migrate_legacy_storage
from store_schema import init_schema


TABLES = ("hotkey_actions", "history", "settings")
COLUMNS = {
    "hotkey_actions": ["id", "name", "hotkey", "action_type", "payload", "active", "created_at", "updated_at", "deleted_at"],
    "history": ["id", "action_id", "name", "action_type", "result", "executed_at"],
    "settings": ["key", "value"],
}


class Store:
    def __init__(
        self,
        path: Path | None = None,
        data_dir: Path | None = None,
        backup_dir: Path | None = None,
    ):
        custom_path = Path(path) if path is not None else None
        self.data_dir = Path(data_dir) if data_dir is not None else (
            custom_path.parent if custom_path is not None else DATA_DIR
        )
        # Backups sit beside the databases; the argument stays for older callers.
        self.backup_dir = Path(backup_dir) if backup_dir is not None else self.data_dir
        self.db_path = custom_path or self.data_dir / "hotkeys.db"
        if custom_path is None:
            migrate_legacy_storage(self.data_dir, backup_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def actions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM hotkey_actions WHERE deleted_at='' ORDER BY id"))

    def active_actions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM hotkey_actions WHERE active=1 AND deleted_at='' ORDER BY id"))

    def setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row is not None else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def action(self, action_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM hotkey_actions WHERE id=? AND deleted_at=''", (action_id,)).fetchone()

    def save_action(self, data: dict) -> int:
        payload = json.dumps(data.get("payload", {}), ensure_ascii=False)
        stamp = now_key()
        if data.get("id"):
            self.conn.execute(_UPDATE_ACTION, (data["name"], data["hotkey"], data["action_type"], payload,
                                              int(data["active"]), stamp, data["id"]))
            self.conn.commit()
            return int(data["id"])
        cur = self.conn.execute(_INSERT_ACTION, (data["name"], data["hotkey"], data["action_type"], payload,
                                                 int(data["active"]), stamp, stamp))
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_action(self, action_id: int) -> None:
        self.conn.execute("UPDATE hotkey_actions SET deleted_at=?,active=0 WHERE id=?", (now_key(), action_id))
        self.conn.commit()

    def delete_actions(self, action_ids: list[int]) -> int:
        ids = _unique_action_ids(action_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.conn:
            cursor = self.conn.execute(
                f"UPDATE hotkey_actions SET deleted_at=?,active=0 WHERE id IN ({placeholders})",
                [now_key(), *ids],
            )
        return cursor.rowcount

    def trashed_actions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM hotkey_actions WHERE deleted_at!='' ORDER BY deleted_at DESC,id DESC"
        ))

    def restore_action(self, action_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE hotkey_actions SET deleted_at='',active=0,updated_at=? WHERE id=?", (now_key(), action_id))

    def purge_expired_trash(self, days: int = 7) -> int:
        cutoff = (datetime.now() - timedelta(days=max(1, days))).strftime("%Y%m%d%H%M")
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM hotkey_actions WHERE deleted_at!='' AND deleted_at<?", (cutoff,)
            )
        return cursor.rowcount

    def set_actions_active(self, action_ids: list[int], active: bool) -> int:
        ids = _unique_action_ids(action_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        values = [int(active), now_key(), *ids]
        with self.conn:
            cursor = self.conn.execute(
                f"UPDATE hotkey_actions SET active=?, updated_at=? WHERE id IN ({placeholders})",
                values,
            )
        return cursor.rowcount

    def replace_actions(self, rows: list[dict]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM hotkey_actions")
            for row in rows:
                payload = json.dumps(row.get("payload", {}), ensure_ascii=False)
                stamp = now_key()
                if row.get("id"):
                    self.conn.execute(_INSERT_ACTION_WITH_ID, (
                        row["id"], row["name"], row["hotkey"], row["action_type"],
                        payload, int(row["active"]), stamp, stamp,
                    ))
                else:
                    self.conn.execute(_INSERT_ACTION, (
                        row["name"], row["hotkey"], row["action_type"],
                        payload, int(row["active"]), stamp, stamp,
                    ))

    def add_history(self, row, result: str) -> None:
        self.conn.execute(
            "INSERT INTO history(action_id,name,action_type,result,executed_at) VALUES(?,?,?,?,?)",
            (row["id"], row["name"], row["action_type"], result, now_key()),
        )
        self.conn.commit()

    def export_json(self, path: Path | None = None) -> Path:
        output = path or self.data_dir / f"backup_{now_key()}.json"
        return export_tables_json(self.conn, TABLES, output)

    def import_json(self, path: Path) -> None:
        import_tables_json(self.conn, path, COLUMNS)

    def close(self) -> None:
        self.conn.close()

    def backup_database(self, destination: Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"대상 데이터베이스가 이미 있습니다: {target}")
        handle = tempfile.NamedTemporaryFile(
            prefix=".toma-db-", suffix=".tmp", dir=target.parent, delete=False
        )
        temporary = Path(handle.name)
        handle.close()
        connection = sqlite3.connect(temporary)
        try:
            self.conn.backup(connection)
            connection.close()
            os.replace(temporary, target)
        except Exception:
            connection.close()
            temporary.unlink(missing_ok=True)
            raise
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        return target


_INSERT_ACTION = """
INSERT INTO hotkey_actions(name,hotkey,action_type,payload,active,created_at,updated_at)
VALUES(?,?,?,?,?,?,?)
"""
_INSERT_ACTION_WITH_ID = """
INSERT INTO hotkey_actions(id,name,hotkey,action_type,payload,active,created_at,updated_at)
VALUES(?,?,?,?,?,?,?,?)
"""
_UPDATE_ACTION = """
UPDATE hotkey_actions
SET name=?, hotkey=?, action_type=?, payload=?, active=?, updated_at=?
WHERE id=?
"""


def _unique_action_ids(action_ids: list[int]) -> list[int]:
    return list(dict.fromkeys(int(action_id) for action_id in action_ids if int(action_id) > 0))
