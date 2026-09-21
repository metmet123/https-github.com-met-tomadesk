from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path


def export_database_bundle(sources: dict, path: Path) -> Path:
    """Export named SQLite connections and selected tables to one JSON file."""
    payload = {"format": "sqlite-database-bundle", "version": 1, "exported_at": _timestamp(), "databases": {}}
    for name, (conn, tables) in sources.items():
        payload["databases"][name] = {table: _table_rows(conn, table) for table in tables}
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # A failed write must not truncate an existing safety backup.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                                         prefix='.bundle-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output


def import_database_bundle(targets: dict, path: Path, legacy_name: str | None = None) -> set[str]:
    """Validate first, then restore all file databases in one SQLite transaction.

    Attached rollback-journal databases participate in SQLite's super-journal.
    WAL, in-memory databases and pending caller transactions are rejected rather
    than silently weakening the all-database commit guarantee.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError('백업 최상위 형식이 올바르지 않습니다.')
    databases = payload.get("databases")
    if 'databases' in payload:
        if payload.get('format') != 'sqlite-database-bundle' or type(payload.get('version')) is not int or payload['version'] != 1:
            raise ValueError('지원하지 않는 백업 형식 또는 버전입니다.')
    elif legacy_name:
        databases = {legacy_name: payload.get('tables', payload)}
    if not isinstance(databases, dict) or not databases:
        raise ValueError('복원할 데이터베이스가 없습니다.')
    plans = []
    seen_paths = set()
    for name, (conn, table_columns) in targets.items():
        if name not in databases:
            continue
        tables = databases[name]
        if not isinstance(tables, dict) or not table_columns or not set(table_columns).issubset(tables):
            raise ValueError(f'{name}: 필수 테이블이 빠진 백업입니다. 기존 데이터는 변경하지 않습니다.')
        if conn.in_transaction:
            raise ValueError('저장 중인 변경이 있습니다. 저장을 마친 뒤 복원해 주세요.')
        if conn.execute('PRAGMA query_only').fetchone()[0]:
            raise ValueError('읽기 전용 데이터베이스에는 복원할 수 없습니다.')
        dbpath = next((row[2] for row in conn.execute('PRAGMA database_list') if row[1] == 'main'), '')
        if not dbpath:
            raise ValueError('파일 데이터베이스만 전체 복원할 수 있습니다.')
        dbpath = Path(dbpath).resolve()
        identity = os.path.normcase(str(dbpath))
        if identity in seen_paths:
            raise ValueError('동일한 데이터베이스가 복원 대상으로 중복 지정됐습니다.')
        seen_paths.add(identity)
        cleaned = {}
        for table, columns in table_columns.items():
            _validate_identifier(table)
            for column in columns:
                _validate_identifier(column)
            rows = tables[table]
            if not isinstance(rows, list):
                raise ValueError(f'{table}: 행 목록이 올바르지 않습니다.')
            primary = [r[1] for r in conn.execute(f'PRAGMA table_info({table})') if r[5]]
            for row in rows:
                if not isinstance(row, dict) or any(not isinstance(k, str) for k in row):
                    raise ValueError(f'{table}: 행 형식이 올바르지 않습니다.')
                if any(k not in row or row[k] is None for k in primary):
                    raise ValueError(f'{table}: 행 식별자가 빠졌습니다.')
                if any(isinstance(v, (list, dict)) for v in row.values()):
                    raise ValueError(f'{table}: 지원하지 않는 값 형식입니다.')
                if table == 'settings' and 'value' not in row:
                    raise ValueError('설정 값이 빠졌습니다.')
            cleaned[table] = [dict(row) for row in rows]
            # Permission is a current user decision, never a capability granted
            # by an imported file. Reset it only when this setting exists locally
            # or in the backup; generic settings tables remain untouched.
            if table == 'settings' and {'key', 'value'}.issubset(columns):
                had_permission = conn.execute("SELECT 1 FROM settings WHERE key='external_ai_allowed'").fetchone()
                has_permission = any(r.get('key') == 'external_ai_allowed' for r in rows)
                if had_permission or has_permission:
                    cleaned[table] = [r for r in cleaned[table] if r.get('key') != 'external_ai_allowed']
                    cleaned[table].append({'key': 'external_ai_allowed', 'value': 'false'})
        plans.append((name, dbpath, table_columns, cleaned))
    if not plans:
        raise ValueError('이 프로그램에서 복원할 수 있는 데이터베이스가 없습니다.')
    coordinator = sqlite3.connect(plans[0][1].as_uri() + '?mode=rw', uri=True, isolation_level=None)
    try:
        aliases = ['main']
        for index, (_, dbpath, _, _) in enumerate(plans[1:], 1):
            alias = f'restore_{index}'
            coordinator.execute(f'ATTACH DATABASE ? AS {alias}', (dbpath.as_uri() + '?mode=rw',))
            aliases.append(alias)
        coordinator.execute('PRAGMA foreign_keys=OFF')
        for alias in aliases:
            mode = coordinator.execute(f'PRAGMA {alias}.journal_mode').fetchone()[0].lower()
            if mode not in ('delete', 'truncate', 'persist'):
                raise ValueError('전체 복원에는 롤백 저널 모드가 필요합니다. 현재 저장 모드에서는 복원을 진행하지 않습니다.')
            coordinator.execute(f'PRAGMA {alias}.synchronous=FULL')
        coordinator.execute('BEGIN IMMEDIATE')
        for alias, (_, _, columns_by_table, tables) in zip(aliases, plans):
            for table in reversed(list(columns_by_table)):
                coordinator.execute(f'DELETE FROM {alias}.{table}')
            for table, columns in columns_by_table.items():
                _insert_rows(coordinator, table, columns, tables[table], database=alias)
        for alias in aliases:
            if coordinator.execute(f'PRAGMA {alias}.foreign_key_check').fetchone():
                raise ValueError('백업의 데이터 참조 관계가 올바르지 않습니다. 복원을 취소했습니다.')
        coordinator.commit()
    except Exception:
        coordinator.rollback()
        raise
    finally:
        coordinator.close()
    return {p[0] for p in plans}


def _table_rows(conn, table: str) -> list[dict]:
    _validate_identifier(table)
    cursor = conn.execute(f"SELECT * FROM {table}")
    columns = [item[0] for item in cursor.description]
    return [dict(row) if hasattr(row, "keys") else dict(zip(columns, row)) for row in cursor]


def _insert_rows(conn, table: str, columns, rows, database='main') -> None:
    schema = _schema_defaults(conn, table, database)
    column_sql = ", ".join(columns)
    placeholders = ", ".join(f":{column}" for column in columns)
    sql = f"INSERT INTO {database}.{table}({column_sql}) VALUES({placeholders})"
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


def _schema_defaults(conn, table: str, database='main') -> dict:
    """Defaults straight from the table, so a new column never breaks restore."""
    defaults: dict = {}
    try:
        rows = list(conn.execute(f"PRAGMA {database}.table_info({table})"))
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
