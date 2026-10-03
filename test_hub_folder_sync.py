"""Local Drive-folder polling stays off until explicitly paired on this PC."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.hub_folder_sync import HubFolderSync
from alert_notes.hub_folder_dialog import HubFolderDialog
from alert_notes.memo_organizer_panel import OrganizerPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def _config(folder, *, enabled=True):
    return {
        "version": 1, "enabled": enabled, "folder": str(folder),
        "bot_id": 101, "user_id": 202, "chat_id": 303,
    }


def _record(update_id=1):
    return {
        "schema_version": 1, "transport": "telegram", "bot_id": 101,
        "update_id": update_id, "received_at_utc": "2026-10-02T01:02:03Z",
        "message": {
            "date": 1790902800, "text": "내일 회신",
            "from": {"id": 202, "is_bot": False},
            "chat": {"id": 303, "type": "private"},
        },
    }


def test_disabled_until_explicitly_configured_and_retries_are_idempotent(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "telegram_101_1.json").write_text(
        json.dumps(_record(), ensure_ascii=False), encoding="utf-8",
    )
    try:
        sync = HubFolderSync(store)
        assert sync.scan()["state"] == "off"
        assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 0
        sync.save(_config(folder, enabled=False))
        assert sync.scan()["state"] == "off"
        sync.save(_config(folder))
        assert sync.load() == _config(folder)
        assert sync.scan()["new"] == 1
        assert sync.scan()["new"] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 1
        assert (folder / "telegram_101_1.json").exists()
        sync.disable()
        assert sync.load()["enabled"] is False
        assert sync.scan()["state"] == "off"
    finally:
        store.close()


def test_missing_folder_and_bad_file_report_error_without_acknowledging(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    try:
        sync = HubFolderSync(store)
        sync.save(_config(folder))
        folder.rmdir()
        with pytest.raises(ValueError, match="찾을 수 없습니다"):
            sync.scan()
        folder.mkdir()
        (folder / "telegram_101_1.json").write_text("{partial", encoding="utf-8")
        with pytest.raises(ValueError, match="읽을 수 없습니다"):
            sync.scan()
        assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 0
    finally:
        store.close()


def test_invalid_configuration_fails_closed(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    try:
        sync = HubFolderSync(store)
        sync.config_path.write_text("{partial", encoding="utf-8")
        with pytest.raises(ValueError):
            sync.scan()
        assert store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0] == 0
    finally:
        store.close()


def test_organizer_displays_scan_status_and_new_capture(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "telegram_101_1.json").write_text(
        json.dumps(_record(), ensure_ascii=False), encoding="utf-8",
    )
    panel = None
    try:
        panel = OrganizerPanel(store)
        panel.folder_sync.save(_config(folder))
        panel.poll_folder_sync()
        assert "새 입력 1건" in panel.folder_status.text()
        assert panel.captures.count() == 1
        panel.poll_folder_sync()
        assert "새 입력 0건" in panel.folder_status.text()
    finally:
        if panel is not None:
            destroy_widget(panel, app)
        store.close()


def test_organizer_shows_partial_success_before_bad_file(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "telegram_101_0.json").write_text(
        json.dumps(_record(update_id=0), ensure_ascii=False), encoding="utf-8",
    )
    (folder / "telegram_101_1.json").write_text("{partial", encoding="utf-8")
    panel = None
    try:
        panel = OrganizerPanel(store)
        panel.folder_sync.save(_config(folder))
        panel.poll_folder_sync()
        assert "로컬 수신 오류" in panel.folder_status.text()
        assert "새 입력 1건은 보존됨" in panel.folder_status.text()
        assert panel.captures.count() == 1
    finally:
        if panel is not None:
            destroy_widget(panel, app)
        store.close()


def test_timer_imports_new_file_without_manual_refresh(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    panel = None
    try:
        panel = OrganizerPanel(store)
        app.processEvents()  # Drain the initial disabled-state scan.
        panel.folder_sync.save(_config(folder))
        panel.timer.setInterval(10)
        (folder / "telegram_101_1.json").write_text(
            json.dumps(_record(), ensure_ascii=False), encoding="utf-8",
        )
        QTest.qWait(80)
        assert panel.captures.count() == 1
        assert "로컬 폴더 확인 완료" in panel.folder_status.text()
    finally:
        if panel is not None:
            destroy_widget(panel, app)
        store.close()


def test_folder_settings_dialog_accepts_existing_folder_and_ids(tmp_path):
    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "incoming"
    folder.mkdir()
    dialog = HubFolderDialog(None)
    try:
        dialog.folder.setText(str(folder))
        dialog.bot_id.setText("101")
        dialog.user_id.setText("202")
        dialog.chat_id.setText("303")
        dialog._save()
        assert dialog.config == _config(folder)
        assert dialog.result() == dialog.DialogCode.Accepted
    finally:
        destroy_widget(dialog, app)
