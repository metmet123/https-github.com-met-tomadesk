"""Default-private Snapshot v1 tests use disposable databases only."""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest

from alert_notes.hub_snapshot import HubSnapshotStore
from alert_notes.sqlite_store import NoteReminderStore


@pytest.fixture
def store(tmp_path):
    value = NoteReminderStore(tmp_path / "snapshot-test.db")
    yield value
    value.close()


def schedule(store, title, details):
    return store.schedules.save_item({
        "title": title, "details": details, "item_type": "task",
        "start_at": "202610031500", "end_at": "202610031501",
        "count_as_dday": True,
    })


def test_default_snapshot_exports_nothing_and_never_leaks_note_or_details(store):
    store.create_note("내 개인 메모", "비공개 본문과 첨부 정보")
    schedule(store, "비공개 일정", "민감한 상세 설명")
    result = HubSnapshotStore(store).build(generated_at_utc="2026-10-02T00:00:00Z")
    assert result["schema_version"] == 1
    assert result["visibility"] == "explicit_allowlist_v1"
    assert result["items"] == []
    encoded = json.dumps(result, ensure_ascii=False)
    assert "비공개" not in encoded and "민감한" not in encoded


def test_only_explicitly_enabled_schedule_is_exported_with_minimal_fields(store):
    first = schedule(store, "공개 허용 일정", "내부 검토 메모")
    schedule(store, "숨길 일정", "비밀 정보")
    snapshot = HubSnapshotStore(store)
    opaque_id = snapshot.set_schedule_visible(first, True)
    before = store.conn.total_changes
    result = snapshot.build(generated_at_utc="2026-10-02T00:00:00Z")
    assert store.conn.total_changes == before
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["id"] == opaque_id and item["id"] != str(first)
    assert item["title"] == "공개 허용 일정"
    assert item["status"] == "pending" and item["count_as_dday"]
    assert set(item) == {"id", "title", "kind", "start_at", "end_at", "all_day", "status", "count_as_dday", "revision"}
    encoded = json.dumps(result, ensure_ascii=False)
    assert "내부 검토" not in encoded and "숨길 일정" not in encoded and "비밀 정보" not in encoded
    assert result["source_revision"] == snapshot.build(generated_at_utc="2026-10-02T00:01:00Z")["source_revision"]


def test_visibility_and_revision_survive_restart_and_backup(store, tmp_path):
    item_id = schedule(store, "원래 제목", "비공개")
    snapshot = HubSnapshotStore(store)
    public_id = snapshot.set_schedule_visible(item_id, True)
    first = snapshot.build()["items"][0]
    updated = dict(store.schedules.item(item_id))
    updated["title"] = "변경된 제목"
    store.schedules.save_item(updated)
    second = snapshot.build()["items"][0]
    assert second["id"] == first["id"] == public_id
    assert second["revision"] != first["revision"]
    copy = store.backup_database(tmp_path / "snapshot-copy.db")
    restored = NoteReminderStore(copy)
    try:
        assert HubSnapshotStore(restored).build()["items"] == [second]
    finally:
        restored.close()
    assert snapshot.set_schedule_visible(item_id, False) == public_id
    assert snapshot.build()["items"] == []
    assert snapshot.set_schedule_visible(item_id, True) == public_id
    assert snapshot.build()["items"][0]["id"] == public_id
    store.schedules.delete_item(item_id)
    assert snapshot.build()["items"] == []


@pytest.mark.parametrize("item_id, visible", [(0, True), (-1, True), (True, True), (1, 1)])
def test_invalid_visibility_changes_fail_closed(store, item_id, visible):
    with pytest.raises(ValueError):
        HubSnapshotStore(store).set_schedule_visible(item_id, visible)
    assert HubSnapshotStore(store).build()["items"] == []


@pytest.mark.parametrize("stamp", ["later", "2026-10-02T09:00:00+09:00", "2026-10-02T00:00:00", 123])
def test_invalid_snapshot_timestamp_is_rejected(store, stamp):
    with pytest.raises(ValueError):
        HubSnapshotStore(store).build(generated_at_utc=stamp)


@pytest.mark.parametrize("failure", ["os.replace", "os.fsync"])
def test_local_publish_keeps_previous_success_when_write_fails(store, tmp_path, failure):
    first = schedule(store, "공개 일정", "숨긴 상세")
    snapshot = HubSnapshotStore(store)
    snapshot.set_schedule_visible(first, True)
    destination = tmp_path / "snapshot.json"
    published = snapshot.publish_local(destination, generated_at_utc="2026-10-02T00:00:00Z")
    original = destination.read_bytes()
    assert json.loads(original)["items"] == published["items"]
    snapshot.set_schedule_visible(first, False)
    with patch(f"alert_notes.hub_snapshot.{failure}", side_effect=OSError("publish failed")):
        with pytest.raises(OSError):
            snapshot.publish_local(destination, generated_at_utc="2026-10-02T00:01:00Z")
    assert destination.read_bytes() == original
    assert list(tmp_path.glob(".tomadesk-snapshot-*.tmp")) == []
    assert snapshot.publish_local(destination, generated_at_utc="2026-10-02T00:02:00Z")["items"] == []
    assert json.loads(destination.read_text(encoding="utf-8"))["items"] == []


def test_visibility_change_never_commits_unrelated_pending_write(store):
    item_id = schedule(store, "공개 검토", "비공개")
    store.conn.execute("INSERT INTO settings(key,value) VALUES('unrelated_pending','yes')")
    with pytest.raises(sqlite3.OperationalError):
        HubSnapshotStore(store).set_schedule_visible(item_id, True)
    store.conn.rollback()
    assert store.setting("unrelated_pending", "") == ""
    assert HubSnapshotStore(store).build()["items"] == []


def test_publish_rejects_uncommitted_data_and_keeps_previous_file(store, tmp_path):
    item_id = schedule(store, "공개 일정", "상세")
    snapshot = HubSnapshotStore(store)
    snapshot.set_schedule_visible(item_id, True)
    destination = tmp_path / "snapshot.json"
    snapshot.publish_local(destination)
    earlier = destination.read_bytes()
    store.conn.execute("UPDATE schedule_items SET title='아직 저장하지 않은 제목' WHERE id=?", (item_id,))
    with pytest.raises(ValueError, match="저장 중"):
        snapshot.publish_local(destination)
    assert destination.read_bytes() == earlier
    store.conn.rollback()


def test_batch_visibility_is_atomic_and_choices_are_local_only(store):
    first = schedule(store, "허용할 일정", "비공개")
    second = schedule(store, "숨길 일정", "비공개")
    snapshot = HubSnapshotStore(store)
    choices = snapshot.list_schedule_choices()
    assert {row["id"] for row in choices} == {first, second}
    assert not any(row["visible"] for row in choices)
    with pytest.raises(ValueError):
        snapshot.set_visible_many({first: True, 999999: True})
    assert snapshot.build()["items"] == []
    ids = snapshot.set_visible_many({first: True, second: False})
    assert set(ids) == {first, second}
    assert {row["id"]: row["visible"] for row in snapshot.list_schedule_choices()} == {
        first: True, second: False,
    }
    assert [item["id"] for item in snapshot.build()["items"]] == [ids[first]]
