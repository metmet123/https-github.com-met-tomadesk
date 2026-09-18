import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QMessageBox

import A_shortcut_launcher as launcher
import storage_config
from settings_dialog import HOTKEY_DEFAULTS, SettingsDialog


class StoragePathProtectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        storage_config.consume_ignored_temporary_storage_path()

    def tearDown(self):
        storage_config.consume_ignored_temporary_storage_path()
        self.temp.cleanup()

    def test_bootstrap_save_rejects_system_temporary_path(self):
        config = self.root / "isolated-config" / "storage_paths.json"
        with patch.object(storage_config, "bootstrap_config_file", return_value=config):
            with self.assertRaisesRegex(OSError, "Windows 임시 폴더"):
                storage_config.save_storage_paths(self.root / "unsafe-data")
        self.assertFalse(config.exists())

    def test_bootstrap_load_ignores_temporary_path_and_reports_it_once(self):
        config = self.root / "isolated-config" / "storage_paths.json"
        unsafe = self.root / "old-data"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"data_dir": str(unsafe)}), encoding="utf-8")
        application = Path.home() / "TomaDeskProtectionTest"
        expected = storage_config.default_storage_paths(application)
        with patch.object(storage_config, "bootstrap_config_file", return_value=config):
            self.assertEqual(storage_config.load_storage_paths(application), expected)
        self.assertEqual(storage_config.consume_ignored_temporary_storage_path(), unsafe)
        self.assertIsNone(storage_config.consume_ignored_temporary_storage_path())

    def test_bootstrap_load_keeps_normal_path(self):
        config = self.root / "isolated-config" / "storage_paths.json"
        safe = Path.home() / "TomaDeskProtectionTest" / "data"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"data_dir": str(safe)}), encoding="utf-8")
        with patch.object(storage_config, "bootstrap_config_file", return_value=config):
            self.assertEqual(storage_config.load_storage_paths(self.root), (safe, safe))
        self.assertIsNone(storage_config.consume_ignored_temporary_storage_path())

    def test_explicit_config_file_keeps_isolated_temporary_paths_working(self):
        config = self.root / "storage_paths.json"
        data = self.root / "data"
        storage_config.save_storage_paths(data, config_file=config)
        self.assertEqual(
            storage_config.load_storage_paths(self.root / "unused", config_file=config),
            (data.resolve(), data.resolve()),
        )

    def test_default_legacy_migration_cannot_bypass_temporary_path_guard(self):
        config = self.root / "isolated-config" / "storage_paths.json"
        config.parent.mkdir(parents=True)
        original = {"backup_dir": str(Path.home() / "old-backups")}
        config.write_text(json.dumps(original), encoding="utf-8")
        with patch.object(storage_config, "bootstrap_config_file", return_value=config):
            with self.assertRaisesRegex(OSError, "Windows 임시 폴더"):
                storage_config.migrate_legacy_storage(self.root / "unsafe-data")
        self.assertEqual(json.loads(config.read_text(encoding="utf-8")), original)


class StoragePathProtectionUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_rejects_new_temporary_folder_and_explains_why(self):
        safe = Path.home() / "TomaDeskProtectionTest" / "data"
        dialog = SettingsDialog(HOTKEY_DEFAULTS, "window", safe)
        selected = Path(tempfile.gettempdir()) / "unsafe-selection"
        try:
            with (
                patch.object(
                    launcher.QFileDialog,
                    "getExistingDirectory",
                    return_value=str(selected),
                ),
                patch.object(QMessageBox, "warning") as warning,
            ):
                dialog._select_folder("data_dir", "데이터 폴더")
            self.assertEqual(dialog.data_dir, safe)
            warning.assert_called_once()
            message = warning.call_args.args[2]
            self.assertIn("임시 폴더", message)
            self.assertIn(str(selected), message)
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_startup_warning_shows_the_ignored_path_once(self):
        ignored = Path(tempfile.gettempdir()) / "old-tomadesk-data"
        with (
            patch.object(
                launcher,
                "consume_ignored_temporary_storage_path",
                side_effect=[ignored, None],
            ),
            patch.object(launcher.QMessageBox, "warning") as warning,
        ):
            launcher._show_ignored_storage_path_warning()
            launcher._show_ignored_storage_path_warning()
        warning.assert_called_once()
        self.assertIn(str(ignored), warning.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
