"""Google Drive auto-download remains inert before explicit local setup."""
import hashlib
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.hub_folder_sync import HubFolderSync
from alert_notes.hub_google_dialog import HubGoogleDialog
from alert_notes.hub_google_drive import DriveAuthorizationRequired
from alert_notes.hub_google_sync import HubGoogleSync
from alert_notes.memo_organizer_panel import OrganizerPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def _local(folder):
    return {"version": 1, "enabled": True, "folder": str(folder),
            "bot_id": 101, "user_id": 202, "chat_id": 303}


def _drive(client):
    return {"version": 1, "enabled": True, "folder_id": "folder_id_101",
            "oauth_client_file": str(client)}


def _content():
    return json.dumps({
        "schema_version": 1, "transport": "telegram", "bot_id": 101,
        "update_id": 1, "received_at_utc": "2026-10-02T01:02:03Z",
        "message": {"date": 1790902800, "text": "내일 회신",
                    "from": {"id": 202, "is_bot": False},
                    "chat": {"id": 303, "type": "private"}},
    }, ensure_ascii=False).encode("utf-8")


class _Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class _Files:
    def __init__(self):
        self.content = _content()

    def list(self, **_kwargs):
        return _Request({"files": [{
            "id": "file_id_0001", "name": "telegram_101_1.json",
            "mimeType": "text/plain", "size": str(len(self.content)),
            "md5Checksum": hashlib.md5(self.content).hexdigest(),
        }]})

    def get_media(self, **_kwargs):
        return _Request(self.content)


class _Service:
    def files(self):
        return _Files()


def test_config_off_by_default_then_download_to_local_handoff(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    client = tmp_path / "oauth-client.json"
    client.write_text("{}", encoding="utf-8")
    try:
        sync = HubGoogleSync(store)
        assert sync.scan()["state"] == "off"
        HubFolderSync(store).save(_local(folder))
        sync.save(_drive(client))
        with pytest.raises(DriveAuthorizationRequired):
            sync.scan()
        assert not sync.token_path.exists()
        assert sync.scan(service=_Service()) == {"state": "ok", "listed": 1, "downloaded": 1}
        assert sync.scan(service=_Service()) == {"state": "ok", "listed": 1, "downloaded": 0}
        assert HubFolderSync(store).scan()["new"] == 1
        sync.disable()
        assert sync.scan()["state"] == "off"
    finally:
        store.close()


def test_drive_dialog_saves_settings_without_starting_oauth(tmp_path):
    app = QApplication.instance() or QApplication([])
    client = tmp_path / "oauth-client.json"
    client.write_text("{}", encoding="utf-8")
    dialog = HubGoogleDialog(None)
    try:
        dialog.folder_id.setText("folder_id_101")
        dialog.client_file.setText(str(client))
        dialog.enabled.setChecked(True)
        dialog._save()
        assert dialog.config == _drive(client)
        assert dialog.result() == dialog.DialogCode.Accepted
    finally:
        destroy_widget(dialog, app)


def test_background_download_updates_ui_and_ingests_record(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "notes.db")
    folder = tmp_path / "incoming"
    folder.mkdir()
    client = tmp_path / "oauth-client.json"
    client.write_text("{}", encoding="utf-8")
    panel = None
    try:
        panel = OrganizerPanel(store)
        app.processEvents()
        panel.folder_sync.save(_local(folder))
        panel.google_sync.save(_drive(client))
        original_scan = panel.google_sync.scan
        panel.google_sync.scan = lambda: original_scan(service=_Service())
        panel._start_drive_poll()
        QTest.qWait(500)
        assert "새 다운로드 1개" in panel.drive_status.text()
        assert panel.captures.count() == 1
    finally:
        if panel is not None:
            destroy_widget(panel, app)
        store.close()
