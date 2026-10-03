"""Exercise a full JSON restore using read-only snapshots of real app databases.

The input databases are never opened for writing. All snapshots, JSON, and
restored databases live in an automatically removed temporary directory.
Only table counts and pass/fail are printed, never memo contents.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from alert_notes.database_bundle import (
    LEGACY_OPTIONAL_TABLES, export_database_bundle, full_database_schema,
    import_database_bundle,
)
from alert_notes.sqlite_store import NoteReminderStore
from store import Store


def _snapshot(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    original = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    try:
        original.backup(copy)
    finally:
        copy.close()
        original.close()


def _rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    cursor = conn.execute(f"SELECT * FROM {table}")
    columns = [item[0] for item in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor]
    if table == "settings":
        # Import deliberately resets this capability to false.
        rows = [row for row in rows if row.get("key") != "external_ai_allowed"]
    return sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))


def audit(hotkeys_path: Path, notes_path: Path) -> dict[str, dict[str, int]]:
    with tempfile.TemporaryDirectory(prefix="tomadesk-backup-audit-") as temporary:
        root = Path(temporary)
        _snapshot(Path(hotkeys_path), root / "source_hotkeys.db")
        _snapshot(Path(notes_path), root / "source_notes.db")
        sources = {
            "hotkeys": sqlite3.connect(root / "source_hotkeys.db"),
            "alert_notes": sqlite3.connect(root / "source_notes.db"),
        }
        target_hotkeys = None
        target_notes = None
        try:
            for name, conn in sources.items():
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError(f"{name}: 원본 스냅샷 무결성 검사 실패")
            source_schema = {name: full_database_schema(conn) for name, conn in sources.items()}
            bundle = root / "full.json"
            export_database_bundle(
                {name: (conn, source_schema[name]) for name, conn in sources.items()}, bundle,
            )
            target_hotkeys = Store(root / "target_hotkeys.db", data_dir=root, backup_dir=root)
            target_notes = NoteReminderStore(root / "target_notes.db")
            targets = {"hotkeys": target_hotkeys.conn, "alert_notes": target_notes.conn}
            restored = import_database_bundle(
                {name: (conn, full_database_schema(conn)) for name, conn in targets.items()},
                bundle,
                optional_missing_tables=LEGACY_OPTIONAL_TABLES,
                reject_unknown_tables=True,
            )
            if restored != set(sources):
                raise RuntimeError("두 데이터베이스가 모두 복원되지 않았습니다.")
            counts: dict[str, dict[str, int]] = {}
            for name, source in sources.items():
                target = targets[name]
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError(f"{name}: 복원 DB 무결성 검사 실패")
                if target.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError(f"{name}: 복원 DB 참조 관계 검사 실패")
                counts[name] = {}
                for table in source_schema[name]:
                    before = _rows(source, table)
                    after = _rows(target, table)
                    if before != after:
                        raise RuntimeError(f"{name}.{table}: 복원 후 데이터가 다릅니다.")
                    counts[name][table] = len(before)
            return counts
        finally:
            if target_notes is not None:
                target_notes.close()
            if target_hotkeys is not None:
                target_hotkeys.close()
            for conn in sources.values():
                conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hotkeys", type=Path)
    parser.add_argument("notes", type=Path)
    args = parser.parse_args()
    summary = audit(args.hotkeys, args.notes)
    print("전체 JSON 백업·복원 검증 통과")
    for database, tables in summary.items():
        print(f"{database}: {len(tables)}개 테이블, {sum(tables.values())}개 행 비교")
