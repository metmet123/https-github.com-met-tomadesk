"""Opt-in snapshot publication keeps private fields and earlier good files safe."""
from datetime import datetime, timedelta, timezone
import json
import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from alert_notes.hub_snapshot import HubSnapshotStore
from alert_notes.hub_snapshot_sync import HubSnapshotSync, SNAPSHOT_NAME
from alert_notes.hub_snapshot_sync_dialog import HubSnapshotSyncDialog
from alert_notes.memo_organizer_panel import OrganizerPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def _schedule(store, title, details):
    return store.schedules.save_item({
        "title": title, "details": details, "item_type": "task",
        "start_at": "202610031500", "end_at": "202610031501",
        "count_as_dday": True,
    })


def _config(folder, enabled=True):
    return {"version": 1, "enabled": enabled, "folder": str(folder)}


def test_default_off_and_explicit_publication_excludes_private_data(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "drive"
    folder.mkdir()
    try:
        store.create_note("내 개인 메모", "비공개 본문")
        visible = _schedule(store, "공개 일정", "비공개 상세")
        _schedule(store, "숨길 일정", "또 비공개")
        sync = HubSnapshotSync(store)
        assert sync.publish_if_due()["state"] == "off"
        sync.save({"version": 1, "enabled": False, "folder": ""})
        assert sync.publish_if_due()["state"] == "off"
        sync.save(_config(folder, enabled=False))
        assert sync.publish_if_due()["state"] == "off"
        assert not (folder / SNAPSHOT_NAME).exists()
        HubSnapshotStore(store).set_schedule_visible(visible, True)
        sync.save(_config(folder))
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        assert sync.publish_if_due(now=now)["published"] is True
        raw = (folder / SNAPSHOT_NAME).read_text(encoding="utf-8")
        assert "공개 일정" in raw
        assert all(private not in raw for private in ("내 개인 메모", "비공개", "숨길 일정"))
        assert len(json.loads(raw)["items"]) == 1
    finally:
        store.close()


def test_same_revision_waits_five_minutes_and_changed_visibility_publishes_immediately(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "drive"
    folder.mkdir()
    try:
        first = _schedule(store, "공개 일정", "상세")
        second = _schedule(store, "나중 일정", "상세")
        HubSnapshotStore(store).set_schedule_visible(first, True)
        sync = HubSnapshotSync(store)
        sync.save(_config(folder))
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        assert sync.publish_if_due(now=now)["published"] is True
        path = folder / SNAPSHOT_NAME
        original = path.read_bytes()
        assert sync.publish_if_due(now=now + timedelta(minutes=1))["published"] is False
        assert path.read_bytes() == original
        HubSnapshotStore(store).set_schedule_visible(second, True)
        assert sync.publish_if_due(now=now + timedelta(minutes=2))["published"] is True
        assert len(json.loads(path.read_text(encoding="utf-8"))["items"]) == 2
        assert sync.publish_if_due(now=now + timedelta(minutes=7))["published"] is True
    finally:
        store.close()


def test_corrupt_or_foreign_file_is_never_overwritten(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "drive"
    folder.mkdir()
    try:
        sync = HubSnapshotSync(store)
        sync.save(_config(folder))
        path = folder / SNAPSHOT_NAME
        path.write_text("{bad", encoding="utf-8")
        with pytest.raises(ValueError, match="기존 Snapshot"):
            sync.publish_if_due()
        assert path.read_text(encoding="utf-8") == "{bad"
        path.write_text(json.dumps({"schema_version": 1, "server_id": "another-pc",
                                    "generated_at_utc": "2026-10-03T00:00:00Z"}), encoding="utf-8")
        with pytest.raises(ValueError, match="식별자"):
            sync.publish_if_due()
    finally:
        store.close()


def test_existing_snapshot_with_unexpected_field_is_rejected(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "drive"
    folder.mkdir()
    try:
        sync = HubSnapshotSync(store)
        sync.save(_config(folder))
        sync.publish_if_due()
        path = folder / SNAPSHOT_NAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["private_note"] = "must not remain published"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError, match="식별자"):
            sync.publish_if_due()
    finally:
        store.close()


def test_write_failure_preserves_previous_success(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "drive"
    folder.mkdir()
    try:
        sync = HubSnapshotSync(store)
        sync.save(_config(folder))
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        sync.publish_if_due(now=now)
        path = folder / SNAPSHOT_NAME
        original = path.read_bytes()
        with patch("alert_notes.hub_snapshot.os.replace", side_effect=OSError("write failed")):
            with pytest.raises(OSError):
                sync.publish_if_due(now=now + timedelta(minutes=5))
        assert path.read_bytes() == original
        assert list(folder.glob(".tomadesk-snapshot-*.tmp")) == []
    finally:
        store.close()


def test_dialog_requires_explicit_enable_and_panel_shows_publication_status(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "drive"
    folder.mkdir()
    dialog = HubSnapshotSyncDialog(None)
    panel = None
    try:
        assert dialog.enabled.isChecked() is False
        dialog.folder.setText(str(folder))
        dialog.enabled.setChecked(True)
        dialog._save()
        assert dialog.config == _config(folder)
        panel = OrganizerPanel(store)
        panel.snapshot_sync.save(dialog.config)
        panel.poll_snapshot_sync()
        assert "게시 완료" in panel.snapshot_sync_status.text()
        assert (folder / SNAPSHOT_NAME).exists()
    finally:
        if panel is not None:
            destroy_widget(panel, app)
        destroy_widget(dialog, app)
        store.close()
