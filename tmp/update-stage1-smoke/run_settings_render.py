import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from settings_dialog import HOTKEY_DEFAULTS, SettingsDialog


app = QApplication(sys.argv)
smoke_root = Path(__file__).resolve().parent / "settings-render"
dialog = SettingsDialog(HOTKEY_DEFAULTS, "window", smoke_root / "data", smoke_root / "backup")
dialog.show()


def capture():
    target = ROOT / "output" / "update_stage2_settings_1050x700.png"
    dialog.grab().save(str(target))
    builder = dialog.hotkey_builders["new_memo_hotkey"]
    widths = [
        builder.first_modifier.width(), builder.second_modifier.width(),
        builder.third_modifier.width(), builder.key_edit.width(),
    ]
    print(f"SETTINGS size={dialog.width()}x{dialog.height()} widths={widths} value={builder.text()}", flush=True)
    dialog.close()
    app.quit()


QTimer.singleShot(500, capture)
raise SystemExit(app.exec())
