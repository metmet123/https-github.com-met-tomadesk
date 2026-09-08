from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def export_database_bundle(sources: dict, path: Path) -> Path:
    """Export named SQLite connections and selected tables to one JSON file."""
    payload = {"format": "sqlite-database-bundle", "version": 1, "exported_at": _timestamp(), "databases": {}}
    for name, (conn, tables) in sources.items():
        payload["databases"][name] = {table: _table_rows(conn, table) for table in tables}
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def import_database_bundle(targets: dict, path: Path, legacy_name: str | None = None) -> set[str]:
    """Restore present databases; omitted databases are intentionally preserved."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    databases = payload.get("databases")
    if databases is None:
        databases = {legacy_name: payload.get("tables", payload)} if legacy_name else {}
    restored: set[str] = set()
    for name, (conn, table_columns) in targets.items():
        tables = databases.get(name)
        if tables is None:
            continue
        entries = list(table_columns.items())
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("BEGIN IMMEDIATE")
            for table, _columns in reversed(entries):
                _validate_identifier(table)
                conn.execute(f"DELETE FROM {table}")
            for table, columns in entries:
                for column in columns:
                    _validate_identifier(column)
                _insert_rows(conn, table, columns, tables.get(table, []))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
        restored.add(name)
    return restored


def _table_rows(conn, table: str) -> list[dict]:
    _validate_identifier(table)
    cursor = conn.execute(f"SELECT * FROM {table}")
    columns = [item[0] for item in cursor.description]
    return [dict(row) if hasattr(row, "keys") else dict(zip(columns, row)) for row in cursor]


def _insert_rows(conn, table: str, columns, rows) -> None:
    schema = _schema_defaults(conn, table)
    column_sql = ", ".join(columns)
    placeholders = ", ".join(f":{column}" for column in columns)
    sql = f"INSERT INTO {table}({column_sql}) VALUES({placeholders})"
    for row in rows:
        values = {
            column: row.get(column, _column_default(table, column, schema))
            for column in columns
        }
        if table == "notes":
            if "postit_visible" not in row:
                values["postit_visible"] = int(bool(row.get("postit", 0)))
            if "postit_startup" not in row:
                values["postit_startup"] = int(bool(row.get("postit", 0)))
            if "background_transparency" not in row:
                values["background_transparency"] = max(0, min(100, 100 - int(row.get("opacity", 100))))
        if table == "reminders" and values.get("scheduled_at") is None:
            values["scheduled_at"] = row.get("due_at")
        conn.execute(sql, values)


def _schema_defaults(conn, table: str) -> dict:
    """Defaults straight from the table, so a new column never breaks restore."""
    defaults: dict = {}
    try:
        rows = list(conn.execute(f"PRAGMA table_info({table})"))
    except Exception:
        return defaults
    for row in rows:
        name, column_type, not_null, raw_default = row[1], row[2], row[3], row[4]
        if not not_null:
            continue
        if raw_default is None:
            defaults[name] = 0 if "INT" in str(column_type).upper() else ""
            continue
        text = str(raw_default).strip()
        if text.startswith("'") and text.endswith("'"):
            defaults[name] = text[1:-1]
        else:
            try:
                defaults[name] = int(text)
            except ValueError:
                defaults[name] = text
    return defaults


def _column_default(table: str, column: str, schema: dict | None = None):
    defaults = {
        ("notes", "hotkey"): "",
        ("notes", "hotkey_action"): "open",
        ("notes", "postit_visible"): 0,
        ("notes", "postit_startup"): 0,
        ("notes", "postit_display_mode"): "normal",
        ("notes", "background_transparency"): 0,
        ("notes", "d_day_at"): "",
        ("notes", "d_day_label"): "",
        ("notes", "d_day_alert"): 0,
        ("notes", "deleted_at"): "",
        ("reminders", "series_id"): None,
        ("reminders", "occurrence_kind"): "regular",
        ("reminders", "scheduled_at"): None,
        ("schedule_items", "details"): "",
        ("schedule_items", "recurrence_rule"): "{}",
        ("schedule_items", "hotkey"): "",
        ("schedule_items", "hotkey_action"): "open",
        ("schedule_items", "count_as_dday"): 0,
        ("schedule_items", "deleted_at"): "",
        ("hotkey_actions", "deleted_at"): "",
    }
    known = defaults.get((table, column))
    if known is not None or (table, column) in defaults:
        return known
    return (schema or {}).get(column)


def _validate_identifier(value: str) -> None:
    if not value or not value.replace("_", "").isalnum() or value[0].isdigit():
        raise ValueError(f"Unsafe SQLite identifier: {value}")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")
