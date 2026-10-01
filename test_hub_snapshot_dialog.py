"""Privacy chooser tests use an offscreen widget and a disposable database."""
from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from alert_notes.hub_snapshot import HubSnapshotStore
from alert_notes.hub_snapshot_dialog import HubSnapshotVisibilityDialog
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def _schedule(store, title, *, all_day=False):
    return store.schedules.save_item({
        "title": title, "item_type": "task", "start_at": "202610031500",
        "end_at": "202610031501", "all_day": all_day,
    })


def test_chooser_is_private_until_saved_and_never_lists_notes(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "chooser.db")
    store.create_note("개인 메모", "절대 외부로 보내지 않음")
    _schedule(store, "조회 후보", all_day=True)
    dialog = HubSnapshotVisibilityDialog(store)
    try:
        assert dialog.table.rowCount() == 1
        assert dialog.table.item(0, 1).text() == "조회 후보"
        assert "종일" in dialog.table.item(0, 3).text()
        assert dialog.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
        assert "개인 메모" not in dialog.table.item(0, 1).text()
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        assert HubSnapshotStore(store).build()["items"] == []
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).click()
        assert HubSnapshotStore(store).build()["items"] == []
    finally:
        destroy_widget(dialog, app)
        store.close()


def test_chooser_saves_only_checked_schedule(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "chooser-save.db")
    first = _schedule(store, "공개 허용")
    _schedule(store, "비공개 유지")
    dialog = HubSnapshotVisibilityDialog(store)
    try:
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert [row["title"] for row in HubSnapshotStore(store).build()["items"]] == ["공개 허용"]
        assert {row["id"]: row["visible"] for row in HubSnapshotStore(store).list_schedule_choices()}[first]
    finally:
        destroy_widget(dialog, app)
        store.close()


def test_chooser_rejects_stale_deleted_selection_without_partial_publish(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "chooser-stale.db")
    item_id = _schedule(store, "삭제된 일정")
    dialog = HubSnapshotVisibilityDialog(store)
    try:
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        store.schedules.delete_item(item_id)
        with patch.object(QMessageBox, "warning") as warning:
            dialog.save_selection()
        warning.assert_called_once()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert HubSnapshotStore(store).build()["items"] == []
    finally:
        destroy_widget(dialog, app)
        store.close()
