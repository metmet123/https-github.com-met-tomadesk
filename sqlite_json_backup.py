import json
from datetime import datetime
from pathlib import Path
from typing import Iterable


def table_rows(conn, table: str) -> list[dict]:
    _validate_identifier(table)
    cursor = conn.execute(f"SELECT * FROM {table}")
    columns = [item[0] for item in cursor.description]
    return [dict(row) if hasattr(row, "keys") else dict(zip(columns, row)) for row in cursor]


def export_tables_json(conn, tables: Iterable[str], path) -> Path:
    output = Path(path)
    data = {"exported_at": _timestamp(), "tables": {}}
    for table in tables:
        _validate_identifier(table)
        data["tables"][table] = table_rows(conn, table)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def import_tables_json(conn, path, table_columns: dict[str, list[str]]) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tables = data.get("tables", data)
    with conn:
        for table, columns in table_columns.items():
            _validate_identifier(table)
            _validate_columns(columns)
            conn.execute(f"DELETE FROM {table}")
            _insert_rows(conn, table, columns, tables.get(table, []))


def _insert_rows(conn, table: str, columns: list[str], rows: list[dict]) -> None:
    col_sql = ", ".join(columns)
    placeholders = ", ".join(f":{column}" for column in columns)
    sql = f"INSERT INTO {table}({col_sql}) VALUES({placeholders})"
    fallbacks = _column_defaults(conn, table)
    for row in rows:
        values = {}
        for column in columns:
            value = row.get(column)
            # A backup written before a column existed has no key for it; use
            # the schema default so old files keep restoring as the app grows.
            values[column] = fallbacks.get(column) if value is None else value
        conn.execute(sql, values)


def _column_defaults(conn, table: str) -> dict:
    """Declared default per NOT NULL column, so missing keys do not break."""
    defaults: dict = {}
    for row in conn.execute(f"PRAGMA table_info({table})"):
        name, column_type, not_null, raw_default = row[1], row[2], row[3], row[4]
        if not not_null:
            continue
        if raw_default is not None:
            text = str(raw_default).strip()
            if text.startswith("'") and text.endswith("'"):
                defaults[name] = text[1:-1]
            else:
                try:
                    defaults[name] = int(text)
                except ValueError:
                    defaults[name] = text
        else:
            defaults[name] = 0 if "INT" in str(column_type).upper() else ""
    return defaults


def _validate_columns(columns: list[str]) -> None:
    if not columns:
        raise ValueError("At least one column is required.")
    for column in columns:
        _validate_identifier(column)


def _validate_identifier(value: str) -> None:
    if not value or not value.replace("_", "").isalnum() or value[0].isdigit():
        raise ValueError(f"Unsafe SQLite identifier: {value}")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")
