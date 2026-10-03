"""The Drive handoff may be retried without duplicating a PC capture."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from alert_notes.hub_drive_ingress import import_telegram_folder, receive_telegram_record
from alert_notes.sqlite_store import NoteReminderStore


def _record(update_id=1, text="내일 회신"):
    return {
        "schema_version": 1,
        "transport": "telegram",
        "bot_id": 101,
        "update_id": update_id,
        "received_at_utc": "2026-10-02T01:02:03.000Z",
        "message": {
            "date": 1790902800,
            "text": text,
            "from": {"id": 202, "is_bot": False},
            "chat": {"id": 303, "type": "private"},
        },
    }


def _receive(store, record):
    return receive_telegram_record(
        store, record, bot_id=101, allowed_user_id=202, allowed_chat_id=303,
    )


def test_drive_record_retries_and_distinct_messages(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    try:
        first = _receive(store, _record(update_id=0))
        retry = _record(update_id=0)
        retry["received_at_utc"] = "2026-10-02T01:05:00Z"
        assert _receive(store, retry) == first
        second = _receive(store, _record(update_id=1))
        assert second["action_id"] != first["action_id"]
        assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 2
    finally:
        store.close()


@pytest.mark.parametrize("change", [
    lambda r: r.update(bot_id=999),
    lambda r: r["message"]["from"].update(id=999),
    lambda r: r["message"]["chat"].update(id=999),
    lambda r: r["message"]["chat"].update(type="group"),
    lambda r: r.update(received_at_utc="2026-10-02T10:00:00+09:00"),
    lambda r: r.update(extra="unrecognized"),
])
def test_invalid_or_unpaired_drive_record_changes_no_db_rows(tmp_path, change):
    store = NoteReminderStore(tmp_path / "notes.db")
    try:
        record = deepcopy(_record())
        change(record)
        with pytest.raises(ValueError):
            _receive(store, record)
        assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 0
    finally:
        store.close()


def test_synced_folder_scan_is_repeatable_and_preserves_source_files(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "unrelated.txt").write_text("ignore", encoding="utf-8")
    for number in (0, 1):
        (folder / f"telegram_101_{number}.json").write_text(
            json.dumps(_record(update_id=number), ensure_ascii=False), encoding="utf-8",
        )
    store = NoteReminderStore(tmp_path / "notes.db")
    try:
        options = dict(bot_id=101, allowed_user_id=202, allowed_chat_id=303)
        first = import_telegram_folder(store, folder, **options)
        assert len(first) == 2
        assert import_telegram_folder(store, folder, **options) == first
        assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 2
        assert len(list(folder.glob("*.json"))) == 2
    finally:
        store.close()


def test_previous_bot_files_do_not_block_current_bot(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    old = _record(update_id=1)
    old["bot_id"] = 100
    (folder / "telegram_100_1.json").write_text(json.dumps(old), encoding="utf-8")
    (folder / "telegram_101_2.json").write_text(
        json.dumps(_record(update_id=2), ensure_ascii=False), encoding="utf-8",
    )
    store = NoteReminderStore(tmp_path / "notes.db")
    try:
        receipts = import_telegram_folder(
            store, folder, bot_id=101, allowed_user_id=202, allowed_chat_id=303,
        )
        assert len(receipts) == 1
        assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 1
        assert len(list(folder.glob("*.json"))) == 2
    finally:
        store.close()


@pytest.mark.parametrize("content", [
    "{not yet synced",
    json.dumps(_record(update_id=2), ensure_ascii=False),
    "x" * (128 * 1024 + 1),
], ids=["partial-json", "name-mismatch", "oversized"])
def test_bad_synced_file_is_not_acknowledged(tmp_path, content):
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "telegram_101_1.json").write_text(content, encoding="utf-8")
    store = NoteReminderStore(tmp_path / "notes.db")
    try:
        with pytest.raises(ValueError):
            import_telegram_folder(
                store, folder, bot_id=101, allowed_user_id=202, allowed_chat_id=303,
            )
        assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 0
    finally:
        store.close()
