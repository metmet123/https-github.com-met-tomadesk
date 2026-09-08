import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from alert_notes.calendar import CalendarPanel
from alert_notes.schedule_editor import ScheduleEditor
from alert_notes.schedule_recurrence import DATETIME_FMT
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.today_summary import TodaySummaryPanel
from ui_theme import scaled_stylesheet


def key(moment: datetime) -> str:
    return moment.strftime(DATETIME_FMT)


def prepare(widget, width: int, height: int) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(width, height)
    widget.show()
    app.processEvents()
    app.processEvents()


render_root = Path(__file__).resolve().parent / "data"
render_root.mkdir(parents=True, exist_ok=True)
store = NoteReminderStore(render_root / "notes.db", "새 메모")
today = date.today()
if not store.notes():
    for title, offset, hour in (
        ("세금 자료 제출", -3, 16),
        ("예산 집행 마감", -1, 18),
        ("주간 보고", 0, 17),
        ("월말 정리", 4, 15),
    ):
        note_id = store.create_note(title, "")
        store.set_deadline(
            note_id,
            key(datetime.combine(today + timedelta(days=offset), time(hour=hour))),
            title,
            False,
        )
    for title, item_type, hour, dday in (
        ("팀 회의", "event", 10, False),
        ("보고서 제출", "task", 10, True),
        ("자료 점검", "task", 14, False),
    ):
        start = datetime.combine(today, time(hour=hour))
        store.schedules.save_item({
            "title": title,
            "item_type": item_type,
            "start_at": key(start),
            "end_at": key(start + timedelta(hours=1)),
            "count_as_dday": dday,
        })

app = QApplication(sys.argv)
app.setStyleSheet(scaled_stylesheet(1.0))

summary = TodaySummaryPanel(store)
prepare(summary, 380, 700)
summary.past_deadline_toggle.click()
app.processEvents()
app.processEvents()
summary.grab().save(str(ROOT / "output" / "past_dday_summary_actual.png"))

calendar = CalendarPanel(store)
calendar.anchor = today
prepare(calendar, 1200, 760)
calendar.dday_only_button.click()
app.processEvents()
app.processEvents()
calendar.grab().save(str(ROOT / "output" / "calendar_dday_filter_actual.png"))

editor = ScheduleEditor(store)
start = datetime.combine(today, time(hour=10, minute=30))
editor.new_item(start, start + timedelta(hours=1), item_type="event")
prepare(editor, 400, 760)
editor.grab().save(str(ROOT / "output" / "schedule_overlap_actual.png"))

print(
    f"SUMMARY past={summary.past_deadline_list.count()} "
    f"expanded={summary.past_deadline_list.isVisible()} horizontal="
    f"{summary.past_deadline_list.horizontalScrollBar().maximum()}",
    flush=True,
)
print(
    f"CALENDAR only_dday={calendar.calendar_filter_checks['dday'].isChecked()} "
    f"events={calendar.calendar_filter_checks['events'].isChecked()} "
    f"tasks={calendar.calendar_filter_checks['tasks'].isChecked()}",
    flush=True,
)
print(
    f"OVERLAP rows={editor.day_context_list.count()} horizontal="
    f"{editor.day_context_list.horizontalScrollBar().maximum()}",
    flush=True,
)

for widget in (summary, calendar, editor):
    widget.close()
store.close()
app.quit()
