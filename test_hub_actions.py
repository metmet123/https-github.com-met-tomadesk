"""Action/Receipt v1 tests use disposable SQLite databases only."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from alert_notes.hub_actions import ActionConflictError, HubActionStore
from alert_notes.memo_organizer_panel import OrganizerPanel
from alert_notes.memo_organizer_store import OrganizerStore
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


@pytest.fixture
def store(tmp_path):
    value = NoteReminderStore(tmp_path / "hub-test.db")
    yield value
    value.close()


def action(event="100", action_id="tg-100", raw="내일 회신"):
    return {
        "schema_version": 1,
        "action_id": action_id,
        "source": "telegram",
        "source_event_id": event,
        "source_sent_at_utc": "2026-10-01T16:00:00Z",
        "received_at_utc": "2026-10-01T16:01:00Z",
        "base_timezone": "Asia/Seoul",
        "kind": "capture_text",
        "payload": {"text": raw},
    }


def test_same_event_retries_once_but_two_identical_messages_stay_distinct(store):
    hub = HubActionStore(store)
    first = hub.receive(action())
    assert first["state"] == "awaiting_review"
    assert hub.receive(action()) == first
    retry = action(action_id="tg-retry")
    retry["received_at_utc"] = "2026-10-01T16:10:00Z"
    retry["source_sent_at_utc"] = "2026-10-01T16:00:00.000+00:00"
    assert hub.receive(retry) == first
    second = hub.receive(action(event="101", action_id="tg-101"))
    assert second["capture_id"] != first["capture_id"]
    captures = OrganizerStore(store).load()["captures"]
    assert len(captures) == 2
    assert captures[0]["external"]["source_event_id"] == "100"
    assert captures[1]["external"]["source_event_id"] == "101"
    # A local click must not accidentally reuse an external capture.
    assert OrganizerStore(store).capture("내일 회신") not in {first["capture_id"], second["capture_id"]}


def test_utc_sender_day_is_used_for_relative_korean_date(store):
    receipt = HubActionStore(store).receive(action())
    captured = OrganizerStore(store).get_capture(receipt["capture_id"])
    assert captured["base"] == "2026-10-02"
    assert captured["items"][0]["day"] == "2026-10-03"


def test_reused_action_or_event_id_with_changed_content_is_rejected(store):
    hub = HubActionStore(store)
    hub.receive(action())
    with pytest.raises(ActionConflictError):
        hub.receive(action(raw="모레 회신"))
    with pytest.raises(ActionConflictError):
        hub.receive(action(action_id="tg-other", raw="모레 회신"))
    with pytest.raises(ActionConflictError):
        hub.receive(action(event="102", raw="모레 회신"))
    assert len(OrganizerStore(store).load()["captures"]) == 1


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2),
    ("action_id", ""), ("source_event_id", "bad id"),
    ("source_sent_at_utc", "2026-10-01T16:00:00"),
    ("received_at_utc", "2026-10-01T16:01:00+09:00"),
    ("base_timezone", "UTC"), ("kind", "complete_task"),
    ("payload", {"text": "  "}), ("payload", {"text": "valid", "ignored": True}),
])
def test_invalid_envelope_never_creates_action_or_capture(store, field, value):
    request = action()
    request[field] = value
    with pytest.raises(ValueError):
        HubActionStore(store).receive(request)
    assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 0
    assert OrganizerStore(store).load()["captures"] == []


def test_capture_and_receipt_roll_back_together(store):
    hub = HubActionStore(store)
    with patch.object(hub.organizer, "_write", side_effect=RuntimeError("disk failure")):
        with pytest.raises(RuntimeError):
            hub.receive(action())
    assert OrganizerStore(store).load()["captures"] == []
    assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 0
    assert hub.receive(action())["state"] == "awaiting_review"


def test_approval_receipt_and_schedule_commit_exactly_once(store, tmp_path):
    hub = HubActionStore(store)
    captured = hub.receive(action())
    edited = deepcopy(hub.organizer.get_capture(captured["capture_id"])["items"])
    applied = hub.apply_review(captured["action_id"], edited)
    assert applied["state"] == "applied"
    assert applied["result_ref"] == "capture:" + captured["capture_id"]
    assert applied["processed_at_utc"]
    assert hub.apply_review(captured["action_id"], edited) == applied
    assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 1
    assert hub.receive(action()) == applied
    copy = store.backup_database(tmp_path / "restored.db")
    restored = NoteReminderStore(copy)
    try:
        assert HubActionStore(restored).receive(action()) == applied
        assert restored.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 1
    finally:
        restored.close()


def test_approval_failure_rolls_back_schedule_capture_and_receipt(store):
    hub = HubActionStore(store)
    captured = hub.receive(action())
    edited = deepcopy(hub.organizer.get_capture(captured["capture_id"])["items"])
    with patch.object(hub, "receipt", side_effect=RuntimeError("receipt failure")):
        with pytest.raises(RuntimeError):
            hub.apply_review(captured["action_id"], edited)
    assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 0
    assert hub.receipt(captured["action_id"])["state"] == "awaiting_review"
    assert not hub.organizer.get_capture(captured["capture_id"])["items"][0]["applied"]
    assert hub.apply_review(captured["action_id"], edited)["state"] == "applied"


def test_tampered_capture_link_cannot_be_approved(store):
    hub = HubActionStore(store)
    captured = hub.receive(action())
    state = hub.organizer.load()
    state["captures"][0]["external"]["action_id"] = "wrong-action"
    with store.conn:
        hub.organizer._write(state)
    edited = hub.organizer.get_capture(captured["capture_id"])["items"]
    with pytest.raises(ActionConflictError, match="연결"):
        hub.apply_review(captured["action_id"], edited)
    assert hub.receipt(captured["action_id"])["state"] == "awaiting_review"
    assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 0


def test_ambiguous_external_item_needs_explicit_kind_before_final_receipt(store):
    hub = HubActionStore(store)
    captured = hub.receive(action(raw="다음달 말 회신"))
    edited = deepcopy(hub.organizer.get_capture(captured["capture_id"])["items"])
    assert edited[0]["kind"] == "review"
    with pytest.raises(ValueError, match="종류"):
        hub.apply_review(captured["action_id"], edited)
    assert hub.receipt(captured["action_id"])["state"] == "awaiting_review"
    edited[0].update(kind="info", day="", clock="", end_clock="")
    assert hub.apply_review(captured["action_id"], edited)["state"] == "applied"


def test_external_information_creates_one_native_note_with_safe_original(store, tmp_path):
    hub = HubActionStore(store)
    captured = hub.receive(action(raw="정보: <script>개인 기록</script>"))
    edited = deepcopy(hub.organizer.get_capture(captured["capture_id"])["items"])
    applied = hub.apply_review(captured["action_id"], edited)
    assert applied["state"] == "applied"
    row = hub.organizer.get_capture(captured["capture_id"])["items"][0]
    note = store.note(row["note_id"])
    assert note is not None
    assert note["sync_id"] and note["revision"] == 1
    assert "&lt;script&gt;" in note["content"] and "<script>" not in note["content"]
    assert hub.receive(action(raw="정보: <script>개인 기록</script>")) == applied
    assert store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
    copy = store.backup_database(tmp_path / "info-copy.db")
    restored = NoteReminderStore(copy)
    try:
        assert restored.note(row["note_id"])["content"] == note["content"]
    finally:
        restored.close()
    store.update_note(row["note_id"], title="수정된 일반 메모")
    assert hub.organizer.rows()[0]["title"] == "수정된 일반 메모"
    store.delete_note(row["note_id"])
    assert hub.organizer.rows() == []
    assert hub.organizer.get_capture(captured["capture_id"])["raw"] == "정보: <script>개인 기록</script>"


def test_existing_local_idea_flow_is_unchanged(store):
    organizer = OrganizerStore(store)
    capture_id = organizer.capture("아이디어: 로컬 정리", base=date(2026, 10, 2))
    assert organizer.apply(capture_id, organizer.get_capture(capture_id)["items"]) == 1
    assert store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert organizer.rows()[0]["kind"] == "idea"


def test_native_note_and_receipt_roll_back_together(store):
    hub = HubActionStore(store)
    captured = hub.receive(action(raw="아이디어: 새 정리 방식"))
    edited = deepcopy(hub.organizer.get_capture(captured["capture_id"])["items"])
    with patch.object(hub.organizer, "_write", side_effect=RuntimeError("disk failure")):
        with pytest.raises(RuntimeError):
            hub.apply_review(captured["action_id"], edited)
    assert store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert hub.receipt(captured["action_id"])["state"] == "awaiting_review"


def test_mixed_schedule_and_note_roll_back_when_note_creation_fails(store):
    hub = HubActionStore(store)
    captured = hub.receive(action(raw="내일 회신\n아이디어: 새 정리 방식"))
    edited = deepcopy(hub.organizer.get_capture(captured["capture_id"])["items"])
    with patch.object(store, "create_note", side_effect=RuntimeError("note failure")):
        with pytest.raises(RuntimeError):
            hub.apply_review(captured["action_id"], edited)
    assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert not any(item["applied"] for item in hub.organizer.get_capture(captured["capture_id"])["items"])
    assert hub.receipt(captured["action_id"])["state"] == "awaiting_review"
    assert hub.apply_review(captured["action_id"], edited)["state"] == "applied"
    assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 1
    assert store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1


def test_reject_is_idempotent_and_cannot_follow_approval(store):
    hub = HubActionStore(store)
    captured = hub.receive(action())
    rejected = hub.reject(captured["action_id"])
    assert rejected["state"] == "rejected"
    assert rejected["error_code"] == "user_rejected"
    assert hub.reject(captured["action_id"]) == rejected
    assert hub.receive(action()) == rejected
    with pytest.raises(ActionConflictError):
        hub.apply_review(captured["action_id"], hub.organizer.get_capture(captured["capture_id"])["items"])
    with pytest.raises(ValueError, match="종료"):
        hub.organizer.save_review(captured["capture_id"], hub.organizer.get_capture(captured["capture_id"])["items"])
    assert hub.organizer.rows() == []


def test_rejection_failure_rolls_back_receipt_state(store):
    hub = HubActionStore(store)
    captured = hub.receive(action())
    with patch.object(hub, "receipt", side_effect=RuntimeError("receipt failure")):
        with pytest.raises(RuntimeError):
            hub.reject(captured["action_id"])
    assert hub.receipt(captured["action_id"])["state"] == "awaiting_review"


def test_rejected_receipt_survives_backup_and_retry(store, tmp_path):
    hub = HubActionStore(store)
    rejected = hub.reject(hub.receive(action())["action_id"])
    copy = store.backup_database(tmp_path / "rejected-copy.db")
    restored = NoteReminderStore(copy)
    try:
        assert HubActionStore(restored).receive(action()) == rejected
        assert OrganizerStore(restored).rows() == []
    finally:
        restored.close()


def test_external_capture_cannot_bypass_receipt_in_ordinary_apply(store):
    hub = HubActionStore(store)
    captured = hub.receive(action())
    edited = hub.organizer.get_capture(captured["capture_id"])["items"]
    with pytest.raises(ValueError, match="영수증"):
        hub.organizer.apply(captured["capture_id"], edited)
    assert hub.receipt(captured["action_id"])["state"] == "awaiting_review"


def test_nested_writes_require_an_active_outer_transaction(store):
    organizer = OrganizerStore(store)
    with pytest.raises(ValueError, match="트랜잭션"):
        organizer.capture_external(
            "내일 회신", date(2026, 10, 2), action_id="x", source="telegram",
            source_event_id="bot:7:update:1",
        )
    local_id = organizer.capture("내일 회신", date(2026, 10, 2))
    with pytest.raises(ValueError, match="트랜잭션"):
        organizer.apply(local_id, organizer.get_capture(local_id)["items"], manage_transaction=False)
    with pytest.raises(ValueError, match="트랜잭션"):
        store.create_note("일반 메모", "내용", manage_transaction=False, sync_alarms=False)
    assert store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


def test_organizer_panel_applies_external_action_with_receipt(store):
    app = QApplication.instance() or QApplication([])
    hub = HubActionStore(store)
    captured = hub.receive(action())
    panel = OrganizerPanel(store)
    try:
        assert panel.capture_id == captured["capture_id"]
        assert "텔레그램" in panel.captures.currentText()
        panel.apply_selected()
        assert hub.receipt(captured["action_id"])["state"] == "applied"
        assert "반영됨" in panel.captures.currentText()
        assert not panel.apply_button.isEnabled()
        assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 1
    finally:
        destroy_widget(panel, app)


def test_organizer_panel_applies_external_information_to_native_notes(store):
    app = QApplication.instance() or QApplication([])
    hub = HubActionStore(store)
    captured = hub.receive(action(raw="정보: 회의록 정리 방식"))
    panel = OrganizerPanel(store)
    try:
        panel.apply_selected()
        assert hub.receipt(captured["action_id"])["state"] == "applied"
        assert store.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
        assert panel.overview.rowCount() == 1
        assert "메모에서 수정" in panel.review.item(0, 8).text()
    finally:
        destroy_widget(panel, app)


def test_open_organizer_panel_can_refresh_new_external_capture(store):
    app = QApplication.instance() or QApplication([])
    panel = OrganizerPanel(store)
    try:
        assert panel.captures.count() == 0
        captured = HubActionStore(store).receive(action())
        panel.capture_refresh_button.click()
        assert panel.captures.currentData() == captured["capture_id"]
        assert "검토 대기" in panel.captures.currentText()
        assert panel.apply_button.isEnabled() and panel.reject_button.isEnabled()
    finally:
        destroy_widget(panel, app)


def test_organizer_exposes_local_snapshot_visibility_chooser(store):
    app = QApplication.instance() or QApplication([])
    panel = OrganizerPanel(store)
    try:
        with patch("alert_notes.memo_organizer_panel.HubSnapshotVisibilityDialog.exec",
                   return_value=QDialog.DialogCode.Accepted):
            panel.visibility_button.click()
        assert "외부로 전송하지 않습니다" in panel.status.text()
    finally:
        destroy_widget(panel, app)


def test_organizer_panel_reject_requires_confirmation_and_preserves_original(store):
    app = QApplication.instance() or QApplication([])
    hub = HubActionStore(store)
    captured = hub.receive(action())
    panel = OrganizerPanel(store)
    try:
        assert panel.reject_button.isEnabled()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            panel.reject_external()
        assert hub.receipt(captured["action_id"])["state"] == "awaiting_review"
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            panel.reject_external()
        assert hub.receipt(captured["action_id"])["state"] == "rejected"
        assert not panel.reject_button.isEnabled()
        assert not panel.apply_button.isEnabled()
        assert "원문만 보존" in panel.review.item(0, 8).text()
        assert hub.organizer.get_capture(captured["capture_id"])["raw"] == "내일 회신"
        assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 0
    finally:
        destroy_widget(panel, app)


@pytest.mark.parametrize("missing_table", ["hub_actions", "hub_visible_schedule"])
def test_old_database_gets_backup_before_hub_table_creation(tmp_path, missing_table):
    path = tmp_path / "legacy.db"
    initial = NoteReminderStore(path)
    initial.conn.execute(f"DROP TABLE {missing_table}")
    initial.conn.commit()
    initial.close()
    upgraded = NoteReminderStore(path)
    try:
        assert upgraded.upgrade_backup_path is not None
        assert upgraded.upgrade_backup_path.exists()
        assert upgraded.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 0
    finally:
        upgraded.close()


def test_separate_schema_upgrades_do_not_overwrite_prior_backup(tmp_path):
    path = tmp_path / "legacy-twice.db"
    first = NoteReminderStore(path)
    first.conn.execute("DROP TABLE hub_actions")
    first.conn.commit()
    first.close()
    second = NoteReminderStore(path)
    earlier = second.upgrade_backup_path
    second.conn.execute("DROP TABLE hub_visible_schedule")
    second.conn.commit()
    second.close()
    third = NoteReminderStore(path)
    try:
        assert earlier is not None and earlier.exists()
        assert third.upgrade_backup_path is not None
        assert third.upgrade_backup_path != earlier
        assert third.upgrade_backup_path.exists()
    finally:
        third.close()
