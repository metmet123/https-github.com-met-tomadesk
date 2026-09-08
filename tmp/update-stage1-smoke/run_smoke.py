from pathlib import Path
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
SMOKE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import app_config


app_config.DATA_DIR = SMOKE_ROOT / "data"
app_config.BACKUP_DIR = SMOKE_ROOT / "backup"

import A_shortcut_launcher as launcher
import main_window


class SmokeGuard:
    def __init__(self, _name):
        pass

    def acquire(self):
        return True

    def release(self):
        pass


class SmokeHotkeys:
    def __init__(self, _window_id):
        self.registered = {}

    def register(self, hotkey_id, hotkey, callback):
        self.registered[hotkey_id] = (hotkey, callback)

    def unregister(self, hotkey_id):
        self.registered.pop(hotkey_id, None)

    def unregister_all(self):
        self.registered.clear()

    def handle_native_event(self, _message):
        return False


launcher.SingleInstanceGuard = SmokeGuard
main_window.HotkeyManager = SmokeHotkeys


original_show = launcher.MainWindow.show_initial_state


def show_then_stop(window):
    original_show(window)
    QTimer.singleShot(6000, QApplication.instance().quit)


launcher.MainWindow.show_initial_state = show_then_stop
raise SystemExit(launcher.main())
