"""Terminal receipts use immutable, minimal files in the opted-in sync folder."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from alert_notes.hub_actions import HubActionStore
from alert_notes.hub_drive_ingress import import_telegram_folder
from alert_notes.hub_folder_sync import HubFolderSync
from alert_notes.hub_telegram_replies import publish_terminal_replies
from alert_notes.sqlite_store import NoteReminderStore


def _record(update_id):
    return {
        "schema_version": 1, "transport": "telegram", "bot_id": 101,
        "update_id": update_id, "received_at_utc": "2026-10-02T01:02:03Z",
        "message": {
            "date": 1790902800, "text": "내일 회신",
            "from": {"id": 202, "is_bot": False},
            "chat": {"id": 303, "type": "private"},
        },
    }


def _sync(store, folder):
    sync = HubFolderSync(store)
    sync.save({"version": 1, "enabled": True, "folder": str(folder),
               "bot_id": 101, "user_id": 202, "chat_id": 303})
    return sync


def test_rejection_exports_once_without_user_text(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "telegram_101_7.json").write_text(json.dumps(_record(7)), encoding="utf-8")
    try:
        sync = _sync(store, folder)
        assert sync.scan()["new"] == 1
        row = store.conn.execute("SELECT action_id FROM hub_actions").fetchone()
        HubActionStore(store).reject(row["action_id"])
        assert sync.scan()["reply_files"] == 1
        reply_path = folder / "reply_101_7_rejected.json"
        reply = json.loads(reply_path.read_text(encoding="utf-8"))
        assert reply["state"] == "rejected"
        assert reply["chat_id"] == 303
        assert "내일 회신" not in reply_path.read_text(encoding="utf-8")
        assert sync.scan()["reply_files"] == 0
        (folder / "sent_reply_101_7_rejected.json").write_bytes(reply_path.read_bytes())
        assert sync.scan()["reply_files"] == 0
    finally:
        store.close()


def test_approval_exports_count_and_existing_conflict_is_not_overwritten(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "telegram_101_8.json").write_text(json.dumps(_record(8)), encoding="utf-8")
    try:
        sync = _sync(store, folder)
        sync.scan()
        hub = HubActionStore(store)
        row = store.conn.execute("SELECT action_id,capture_id FROM hub_actions").fetchone()
        edited = deepcopy(hub.organizer.get_capture(row["capture_id"])["items"])
        hub.apply_review(row["action_id"], edited)
        assert sync.scan()["reply_files"] == 1
        path = folder / "reply_101_8_applied.json"
        assert json.loads(path.read_text(encoding="utf-8"))["applied_count"] == 1
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="충돌"):
            sync.scan()
        assert path.read_text(encoding="utf-8") == "{}"
    finally:
        store.close()


def test_previous_bot_receipt_does_not_block_new_pairing(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    try:
        store.conn.execute(
            "INSERT INTO hub_actions(action_id,source,source_event_id,envelope_hash,action_json,"
            "state,applied_count,processed_at_utc,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?)",
            ("old", "telegram", "bot:99:update:1", "hash", "{}", "rejected", 0,
             "2026-10-02T01:02:03Z", "2026-10-02T01:00:00Z"),
        )
        store.conn.commit()
        assert publish_terminal_replies(store, folder, bot_id=101, user_id=202, chat_id=303) == 0
    finally:
        store.close()


def test_repairing_same_bot_to_another_chat_does_not_leak_old_receipt(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "telegram_101_7.json").write_text(json.dumps(_record(7)), encoding="utf-8")
    try:
        sync = _sync(store, folder)
        sync.scan()
        row = store.conn.execute("SELECT action_id FROM hub_actions").fetchone()
        HubActionStore(store).reject(row["action_id"])
        assert publish_terminal_replies(
            store, folder, bot_id=101, user_id=999, chat_id=999,
        ) == 0
        assert not (folder / "reply_101_7_rejected.json").exists()
    finally:
        store.close()


def test_enabling_replies_does_not_send_historical_terminal_actions(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "telegram_101_7.json").write_text(json.dumps(_record(7)), encoding="utf-8")
    try:
        import_telegram_folder(store, folder, bot_id=101, allowed_user_id=202,
                               allowed_chat_id=303)
        row = store.conn.execute("SELECT action_id FROM hub_actions").fetchone()
        HubActionStore(store).reject(row["action_id"])
        sync = _sync(store, folder)  # Reply feature starts after this old decision.
        started = sync.ensure_replies_started()
        assert sync.scan()["reply_files"] == 0
        assert not (folder / "reply_101_7_rejected.json").exists()
        assert HubFolderSync(store).ensure_replies_started() == started
    finally:
        store.close()


def test_cutoff_failure_does_not_activate_a_new_pairing(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    try:
        sync = _sync(store, folder)
        previous = sync.load()
        changed = dict(previous, chat_id=999)
        with patch.object(sync, "_write_reply_start", side_effect=OSError("disk failure")):
            with pytest.raises(OSError):
                sync.save(changed)
        assert sync.load() == previous
    finally:
        store.close()
