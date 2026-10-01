"""The full JSON backup must retain memo metadata, including old-bundle behavior."""
from __future__ import annotations

import json

import pytest

from alert_notes.database_bundle import (
    export_database_bundle, full_database_schema, import_database_bundle,
)
from alert_notes.sqlite_store import (
    ANNOTATION_COLUMNS, CATEGORY_COLUMNS, NOTE_COLUMNS, SYNC_TOMBSTONE_COLUMNS,
    TEMPLATE_COLUMNS, VERSION_COLUMNS, NoteReminderStore,
)


TABLES = (
    "memo_categories", "notes", "memo_annotations", "memo_versions",
    "memo_templates", "sync_tombstones",
)
COLUMNS = {
    "memo_categories": CATEGORY_COLUMNS,
    "notes": NOTE_COLUMNS,
    "memo_annotations": ANNOTATION_COLUMNS,
    "memo_versions": VERSION_COLUMNS,
    "memo_templates": TEMPLATE_COLUMNS,
    "sync_tombstones": SYNC_TOMBSTONE_COLUMNS,
}
OPTIONAL = {"alert_notes": set(TABLES) - {"notes"}}


def _seed(store):
    category_id = store.create_category("보존할 분류", "#123456")
    note_id = store.create_note("보존할 메모", "본문")
    store.set_note_category(note_id, category_id)
    store.conn.execute(
        "INSERT INTO memo_annotations(sync_id,memo_id,comment,created_at_utc,modified_at_utc) "
        "VALUES('annotation-1',?,'보존할 주석','2026-10-02','2026-10-02')", (note_id,),
    )
    store.conn.execute(
        "INSERT INTO memo_versions(sync_id,memo_id,payload_hash,payload_json,created_at_utc) "
        "VALUES('version-1',?,'abc','{}','2026-10-02')", (note_id,),
    )
    store.conn.execute(
        "INSERT INTO memo_templates(sync_id,name,trigger,payload_json,created_at_utc,modified_at_utc) "
        "VALUES('template-1','보존할 템플릿','saved','{}','2026-10-02','2026-10-02')",
    )
    store.conn.execute(
        "INSERT INTO sync_tombstones(entity_type,sync_id,revision,deleted_at_utc) "
        "VALUES('annotation','removed-1',2,'2026-10-02')",
    )
    store.conn.commit()
    return note_id, category_id


def test_full_bundle_roundtrip_preserves_all_memo_metadata(tmp_path):
    source = NoteReminderStore(tmp_path / "source.db")
    target = NoteReminderStore(tmp_path / "target.db")
    try:
        note_id, category_id = _seed(source)
        path = export_database_bundle({"alert_notes": (source.conn, TABLES)}, tmp_path / "full.json")
        data = json.loads(path.read_text(encoding="utf-8"))["databases"]["alert_notes"]
        assert set(data) == set(TABLES)
        assert import_database_bundle({"alert_notes": (target.conn, COLUMNS)}, path) == {"alert_notes"}
        assert target.note(note_id)["category_id"] == category_id
        for table in TABLES:
            assert [tuple(row) for row in target.conn.execute(f"SELECT * FROM {table} ORDER BY 1")] == [
                tuple(row) for row in source.conn.execute(f"SELECT * FROM {table} ORDER BY 1")
            ]
        assert target.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        source.close()
        target.close()


def test_old_bundle_restores_notes_and_clears_unavailable_memo_metadata(tmp_path):
    old = NoteReminderStore(tmp_path / "old.db")
    target = NoteReminderStore(tmp_path / "target.db")
    try:
        old_note = old.create_note("예전 메모", "예전 본문")
        old_category = old.create_category("백업에 빠진 분류")
        old.set_note_category(old_note, old_category)
        _seed(target)
        path = export_database_bundle({"alert_notes": (old.conn, ("notes",))}, tmp_path / "old.json")
        assert import_database_bundle(
            {"alert_notes": (target.conn, COLUMNS)}, path, optional_missing_tables=OPTIONAL,
        ) == {"alert_notes"}
        assert [row["title"] for row in target.notes()] == ["예전 메모"]
        assert target.note(old_note)["category_id"] is None
        for table in set(TABLES) - {"notes"}:
            assert target.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        old.close()
        target.close()


def test_invalid_memo_reference_rolls_back_entire_restore(tmp_path):
    source = NoteReminderStore(tmp_path / "source.db")
    target = NoteReminderStore(tmp_path / "target.db")
    try:
        _seed(source)
        target.create_note("현재 메모", "유지")
        path = export_database_bundle({"alert_notes": (source.conn, TABLES)}, tmp_path / "broken.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["databases"]["alert_notes"]["memo_annotations"][0]["memo_id"] = 999999
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError, match="참조 관계"):
            import_database_bundle({"alert_notes": (target.conn, COLUMNS)}, path)
        assert [row["title"] for row in target.notes()] == ["현재 메모"]
    finally:
        source.close()
        target.close()


def test_future_table_is_discovered_and_roundtrips_without_updating_a_list(tmp_path):
    source = NoteReminderStore(tmp_path / "source.db")
    target = NoteReminderStore(tmp_path / "target.db")
    try:
        ddl = (
            "CREATE TABLE future_entries (id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL, "
            "value TEXT NOT NULL, FOREIGN KEY(note_id) REFERENCES notes(id))"
        )
        source.conn.execute(ddl)
        target.conn.execute(ddl)
        note_id = source.create_note("새 테이블의 메모")
        source.conn.execute(
            "INSERT INTO future_entries(note_id,value) VALUES(?,?)", (note_id, "잃어서는 안 될 값"),
        )
        source.conn.commit()
        source_schema = full_database_schema(source.conn)
        target_schema = full_database_schema(target.conn)
        assert "future_entries" in source_schema
        assert list(source_schema).index("notes") < list(source_schema).index("future_entries")
        path = export_database_bundle(
            {"alert_notes": (source.conn, source_schema)}, tmp_path / "future.json",
        )
        assert import_database_bundle(
            {"alert_notes": (target.conn, target_schema)}, path,
            reject_unknown_tables=True,
        ) == {"alert_notes"}
        assert target.conn.execute("SELECT value FROM future_entries").fetchone()[0] == "잃어서는 안 될 값"
    finally:
        source.close()
        target.close()


def test_future_table_missing_from_old_backup_fails_without_changing_current_data(tmp_path):
    old = NoteReminderStore(tmp_path / "old.db")
    target = NoteReminderStore(tmp_path / "target.db")
    try:
        old.create_note("예전 백업")
        current_id = target.create_note("현재 메모")
        target.conn.execute(
            "CREATE TABLE future_entries (id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL, "
            "value TEXT NOT NULL, FOREIGN KEY(note_id) REFERENCES notes(id))"
        )
        target.conn.execute(
            "INSERT INTO future_entries(note_id,value) VALUES(?,?)", (current_id, "현재 값"),
        )
        target.conn.commit()
        path = export_database_bundle(
            {"alert_notes": (old.conn, full_database_schema(old.conn))}, tmp_path / "old.json",
        )
        with pytest.raises(ValueError, match="필수 테이블"):
            import_database_bundle(
                {"alert_notes": (target.conn, full_database_schema(target.conn))}, path,
                optional_missing_tables=OPTIONAL, reject_unknown_tables=True,
            )
        assert target.note(current_id)["title"] == "현재 메모"
        assert target.conn.execute("SELECT value FROM future_entries").fetchone()[0] == "현재 값"
    finally:
        old.close()
        target.close()


def test_unknown_table_in_backup_is_rejected_in_strict_restore(tmp_path):
    store = NoteReminderStore(tmp_path / "target.db")
    try:
        path = export_database_bundle(
            {"alert_notes": (store.conn, full_database_schema(store.conn))}, tmp_path / "newer.json",
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["databases"]["alert_notes"]["unknown_future_table"] = [{"id": 1}]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="없는 테이블"):
            import_database_bundle(
                {"alert_notes": (store.conn, full_database_schema(store.conn))}, path,
                reject_unknown_tables=True,
            )
    finally:
        store.close()
