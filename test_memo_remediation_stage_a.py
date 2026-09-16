from __future__ import annotations

import ast
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QListWidgetItem

import A_shortcut_launcher
from alert_notes.panel import AlertNotesPanel
from alert_notes.rich_memo_edit import RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.version_dialog import VersionHistoryDialog
from qt_test_support import close_alert_panel, destroy_widget


class RemediationStageATest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = NoteReminderStore(self.root / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_template_json_loads_and_invalid_choice_warns_without_raising(self):
        note_id = self.store.create_note("템플릿", "")
        template_id = self.store.memo_data.save_template(
            "회의", "meeting",
            {"version": 1, "kind": "blocks", "html": "<p>회의</p>", "text": "회의", "blocks": []},
        )
        editor = RichMemoTextEdit(self.store)
        editor.set_note_context(note_id)
        try:
            self.assertTrue(editor._insert_template(template_id))
            self.assertIn("회의", editor.toPlainText())
            item = QListWidgetItem("깨진 템플릿")
            item.setData(Qt.ItemDataRole.UserRole, "template:999999")
            with patch("alert_notes.rich_memo_edit.QMessageBox.warning") as warning:
                self.assertFalse(editor._run_insert_item(item))
            warning.assert_called_once()
        finally:
            destroy_widget(editor, self.app)

    def test_bulk_category_assignment_reports_success(self):
        first = self.store.create_note("첫 메모")
        second = self.store.create_note("둘째 메모")
        category_id = int(self.store.categories()[0]["id"])
        panel = AlertNotesPanel(self.store)
        try:
            panel.assign_note_categories([first, second], category_id)
            self.assertEqual(self.store.note(first)["category_id"], category_id)
            self.assertEqual(self.store.note(second)["category_id"], category_id)
            self.assertEqual(panel.list_panel.action_status.property("level"), "success")
            self.assertIn("2개 메모", panel.list_panel.action_status.text())
        finally:
            close_alert_panel(panel, self.app)

    def test_every_panel_status_call_supplies_a_level(self):
        source = Path("alert_notes/panel.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        missing = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "_status":
                continue
            has_level_keyword = any(keyword.arg == "level" for keyword in node.keywords)
            if len(node.args) < 2 and not has_level_keyword:
                missing.append(node.lineno)
        self.assertEqual(missing, [])

    def test_version_slot_value_error_is_shown_and_dialog_stays_alive(self):
        service = MagicMock()
        service.versions.return_value = []
        service.create_version.side_effect = ValueError("버전 오류")
        dialog = VersionHistoryDialog(service, 1)
        try:
            dialog.show()
            self.app.processEvents()
            with patch("alert_notes.version_dialog.QMessageBox.warning") as warning:
                dialog._create()
            warning.assert_called_once()
            self.assertFalse(dialog.isHidden())
        finally:
            destroy_widget(dialog, self.app)

    def test_uncaught_exception_hook_writes_log_and_shows_warning(self):
        log_path = self.root / "logs" / "tomadesk_error.log"
        previous = sys.excepthook
        try:
            A_shortcut_launcher._install_exception_hook(log_path)
            try:
                raise RuntimeError("슬롯 실패")
            except RuntimeError:
                exc_type, exc_value, exc_traceback = sys.exc_info()
            with patch("A_shortcut_launcher.QMessageBox.critical") as critical:
                sys.excepthook(exc_type, exc_value, exc_traceback)
            critical.assert_called_once()
            self.assertIn("RuntimeError: 슬롯 실패", log_path.read_text(encoding="utf-8"))
        finally:
            sys.excepthook = previous


if __name__ == "__main__":
    unittest.main()
