"""Full-bundle roundtrips for the new Hub tables, including older backups."""
from __future__ import annotations

import pytest

from alert_notes.database_bundle import export_database_bundle, import_database_bundle
from alert_notes.hub_actions import HubActionStore
from alert_notes.hub_snapshot import HubSnapshotStore
from alert_notes.schedule_store import ITEM_COLUMNS
from alert_notes.sqlite_store import (
    HUB_ACTION_COLUMNS, HUB_VISIBLE_SCHEDULE_COLUMNS, NOTE_COLUMNS, SETTING_COLUMNS,
    NoteReminderStore,
)


TABLES = ("notes", "settings", "schedule_items", "hub_actions", "hub_visible_schedule")
COLUMNS = {
    "notes": NOTE_COLUMNS,
    "settings": SETTING_COLUMNS,
    "schedule_items": ITEM_COLUMNS,
    "hub_actions": HUB_ACTION_COLUMNS,
    "hub_visible_schedule": HUB_VISIBLE_SCHEDULE_COLUMNS,
}
OPTIONAL = {"alert_notes": {"hub_actions", "hub_visible_schedule"}}


def _action(raw="내일 회신"):
    return {
        "schema_version": 1,
        "action_id": "bundle-action",
        "source": "telegram",
        "source_event_id": "bot:7:update:1",
        "source_sent_at_utc": "2026-10-01T16:00:00Z",
        "received_at_utc": "2026-10-01T16:01:00Z",
        "base_timezone": "Asia/Seoul",
        "kind": "capture_text",
        "payload": {"text": raw},
    }


def _schedule(store):
    return store.schedules.save_item({
        "title": "조회 허용", "item_type": "task", "start_at": "202610031500",
        "end_at": "202610031501", "count_as_dday": True,
    })


def test_full_bundle_preserves_receipt_and_visibility(tmp_path):
    source = NoteReminderStore(tmp_path / "source.db")
    target = NoteReminderStore(tmp_path / "target.db")
    try:
        action = _action("정보: 휴대폰 메모 정리")
        hub = HubActionStore(source)
        pending = hub.receive(action)
        receipt = hub.apply_review(
            pending["action_id"], hub.organizer.get_capture(pending["capture_id"])["items"],
        )
        note_id = hub.organizer.get_capture(pending["capture_id"])["items"][0]["note_id"]
        public_id = HubSnapshotStore(source).set_schedule_visible(_schedule(source), True)
        path = export_database_bundle({"alert_notes": (source.conn, TABLES)}, tmp_path / "full.json")
        assert import_database_bundle({"alert_notes": (target.conn, COLUMNS)}, path) == {"alert_notes"}
        assert HubActionStore(target).receive(action) == receipt
        assert target.note(note_id)["title"] == "정보: 휴대폰 메모 정리"
        assert HubSnapshotStore(target).build()["items"][0]["id"] == public_id
        assert target.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 1
    finally:
        source.close()
        target.close()


def test_old_bundle_clears_current_hub_state_without_rejecting_old_format(tmp_path):
    old = NoteReminderStore(tmp_path / "old.db")
    target = NoteReminderStore(tmp_path / "current.db")
    try:
        old.create_note("오래된 백업의 메모", "본문")
        path = export_database_bundle(
            {"alert_notes": (old.conn, ("notes", "settings", "schedule_items"))},
            tmp_path / "old.json",
        )
        HubActionStore(target).receive(_action())
        HubSnapshotStore(target).set_schedule_visible(_schedule(target), True)
        assert import_database_bundle(
            {"alert_notes": (target.conn, COLUMNS)}, path,
            optional_missing_tables=OPTIONAL,
        ) == {"alert_notes"}
        assert target.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 0
        assert target.conn.execute("SELECT COUNT(*) FROM hub_visible_schedule").fetchone()[0] == 0
        assert target.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 0
        assert [row["title"] for row in target.notes()] == ["오래된 백업의 메모"]
    finally:
        old.close()
        target.close()


def test_optional_hub_tables_do_not_make_core_tables_optional(tmp_path):
    target = NoteReminderStore(tmp_path / "current.db")
    try:
        before = HubActionStore(target).receive(_action())
        path = export_database_bundle(
            {"alert_notes": (target.conn, ("settings",))}, tmp_path / "incomplete.json",
        )
        with pytest.raises(ValueError, match="필수 테이블"):
            import_database_bundle(
                {"alert_notes": (target.conn, COLUMNS)}, path,
                optional_missing_tables=OPTIONAL,
            )
        assert HubActionStore(target).receipt(before["action_id"]) == before
    finally:
        target.close()
