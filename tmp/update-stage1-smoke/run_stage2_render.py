import sys
from datetime import date
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import main_window
from store import Store


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


main_window.HotkeyManager = SmokeHotkeys
main_window.foreground_application = lambda: None

smoke_root = Path(__file__).resolve().parent / "stage2-render"
store = Store(smoke_root / "hotkeys.db")
if not store.actions():
    store.save_action({
        "name": "보고서 문구 입력", "hotkey": "Ctrl+Alt+1", "action_type": "text",
        "payload": {"text": "보고서 초안", "press_enter": False}, "active": True,
    })

app = QApplication(sys.argv)
window = main_window.MainWindow(store)
window.resize(1247, 849)
window.show()


def capture_shortcuts():
    window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    app.processEvents()
    target = ROOT / "output" / "update_stage2_shortcuts_1247x849.png"
    window.grab().save(str(target))
    print(
        f"SHORTCUTS toolbar={window.bulk_action_toolbar.isVisible()} "
        f"columns={window.table.columnCount()} width={window.width()}x{window.height()}",
        flush=True,
    )
    QTimer.singleShot(200, capture_calendar)


def capture_calendar():
    schedules = window.note_store.schedules
    if not schedules.items_for_range("202608310000", "202609010000"):
        schedules.save_item({
            "title": "새벽 일정", "item_type": "event",
            "start_at": "202608310630", "end_at": "202608310730",
        })
    window._switch_workspace(1)
    window.alert_panel.tabs.setCurrentIndex(1)
    calendar = window.alert_panel.calendar
    calendar.anchor = date(2026, 8, 31)
    calendar._set_mode("day")
    app.processEvents()
    target = ROOT / "output" / "update_stage2_calendar_1247x849.png"
    window.grab().save(str(target))
    print(
        f"CALENDAR rows={calendar.table.rowCount()} "
        f"early_visible={bool(calendar.table.item(6, 1))} "
        f"scroll={calendar.table.verticalScrollBar().value()}",
        flush=True,
    )
    window._set_action_form_baseline()
    window.close()
    app.quit()


QTimer.singleShot(500, capture_shortcuts)
exit_code = app.exec()
store.close()
raise SystemExit(exit_code)
