import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

label = sys.argv[1] if len(sys.argv) > 1 else "100"
scale_factors = {"100": "1.0", "125": "1.25", "150": "1.5"}
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QT_SCALE_FACTOR", scale_factors.get(label, "1.0"))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from alert_notes.schedule_postit import SchedulePostitWindow
from alert_notes.schedule_postit_settings import SchedulePostitPreferences
from alert_notes.sqlite_store import NoteReminderStore
from settings_dialog import HOTKEY_DEFAULTS, SettingsDialog
from ui_theme import scaled_stylesheet


render_root = Path(__file__).resolve().parent / f"data-{label}"
render_root.mkdir(parents=True, exist_ok=True)
store = NoteReminderStore(render_root / "notes.db", "새 메모")
start = datetime.combine(date.today(), datetime.min.time()).replace(hour=9)

if not store.schedules.items_for_range(
    start.strftime("%Y%m%d0000"), (start + timedelta(days=1)).strftime("%Y%m%d0000")
):
    examples = (
        ("예산 집행 마감", "event", 9, 3),
        ("보고서 제출", "task", 10, 2),
        ("중간 확인", "task", 11, 1),
        ("팀 회의", "event", 13, 2),
        ("자료 정리", "task", 14, 0),
        ("일정 공유", "event", 15, 1),
        ("내일 계획", "task", 16, 0),
        ("완료 보고", "task", 17, 2),
        ("마감 점검", "task", 18, 3),
    )
    for title, item_type, hour, priority in examples:
        item_start = start.replace(hour=hour)
        item_id = store.schedules.save_item({
            "title": title,
            "item_type": item_type,
            "start_at": item_start.strftime("%Y%m%d%H%M"),
            "end_at": (item_start + timedelta(minutes=30)).strftime("%Y%m%d%H%M"),
            "priority": priority,
        })
        if title == "중간 확인":
            store.schedules.set_completed(item_id, True)

prefs = SchedulePostitPreferences(max_rows=8)
prefs.save(store)

app = QApplication(sys.argv)
app.setStyleSheet(scaled_stylesheet(1.0))
postit = SchedulePostitWindow(store)
postit.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
postit.show()
settings = SettingsDialog(
    HOTKEY_DEFAULTS,
    "window",
    render_root,
    schedule_postit_options=prefs.__dict__,
)
settings.settings_tabs.setCurrentWidget(settings.schedule_page)
settings.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
settings.show()


def capture() -> None:
    app.processEvents()
    postit_path = ROOT / "output" / f"schedule_postit_actual_{label}.png"
    settings_path = ROOT / "output" / f"schedule_settings_actual_{label}.png"
    postit.grab().save(str(postit_path))
    settings.grab().save(str(settings_path))
    print(
        f"POSTIT label={label} logical={postit.width()}x{postit.height()} "
        f"rows={len(postit.rows)} scroll={postit.scroll.verticalScrollBar().isVisible()}",
        flush=True,
    )
    print(
        f"SETTINGS label={label} logical={settings.width()}x{settings.height()} "
        f"page_hint={settings.schedule_page.sizeHint().width()}x{settings.schedule_page.sizeHint().height()}",
        flush=True,
    )
    postit.shutdown()
    settings.close()
    store.close()
    app.quit()


QTimer.singleShot(450, capture)
raise SystemExit(app.exec())
