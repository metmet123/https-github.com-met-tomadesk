import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

label = sys.argv[1] if len(sys.argv) > 1 else "100"
scale_factors = {"100": "1.0", "125": "1.25", "150": "1.5"}
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QT_SCALE_FACTOR", scale_factors.get(label, "1.0"))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLayout, QVBoxLayout, QWidget


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from alert_notes.calendar import CalendarPanel
from alert_notes.schedule_editor import ScheduleEditor
from alert_notes.sqlite_store import NoteReminderStore
from ui_theme import scaled_stylesheet


render_root = Path(__file__).resolve().parent / f"data-{label}"
render_root.mkdir(parents=True, exist_ok=True)
store = NoteReminderStore(render_root / "notes.db", "새 메모")
app = QApplication(sys.argv)
app.setStyleSheet(scaled_stylesheet(1.0))


def prepare(widget, width: int, height: int) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(width, height)
    widget.show()
    app.processEvents()
    app.processEvents()


def editor_host(editor: ScheduleEditor) -> QWidget:
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(editor)
    return host


start = datetime(2026, 9, 8, 18, 0)
event_editor = ScheduleEditor(store)
event_editor.new_item(start, start + timedelta(hours=1), item_type="event")
event_editor.title_edit.setText("주간 회의")
event_host = editor_host(event_editor)
prepare(event_host, 400, 760)
event_host.grab().save(str(ROOT / "output" / f"schedule_editor_event_actual_{label}.png"))

task_editor = ScheduleEditor(store)
task_editor.new_item(start, start + timedelta(hours=1), item_type="task")
task_editor.title_edit.setText("보고서 제출")
task_editor.count_as_dday_check.setChecked(True)
task_host = editor_host(task_editor)
prepare(task_host, 400, 760)
task_host.grab().save(str(ROOT / "output" / f"schedule_editor_task_actual_{label}.png"))

panel = CalendarPanel(store)
prepare(panel, 1200, 760)
panel.grab().save(str(ROOT / "output" / f"schedule_editor_entries_actual_{label}.png"))
host = QWidget()
host_layout = QVBoxLayout(host)
host_layout.setContentsMargins(0, 0, 0, 0)
host_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
host_layout.addWidget(panel)
host.setMinimumSize(0, 0)
prepare(host, 680, 760)
panel.update_responsive_layout(680)
app.processEvents()
app.processEvents()
panel.new_task_button.click()
app.processEvents()
app.processEvents()
host.grab().save(str(ROOT / "output" / f"schedule_editor_task_narrow_actual_{label}.png"))

print(
    f"EVENT label={label} end_visible={event_editor.form.isRowVisible(event_editor.end_edit)} "
    f"hint={event_editor.sizeHint().width()}x{event_editor.sizeHint().height()}",
    flush=True,
)
print(
    f"TASK label={label} end_visible={task_editor.form.isRowVisible(task_editor.end_edit)} "
    f"dday_hidden={task_editor.count_as_dday_check.isHidden()}",
    flush=True,
)
print(
    f"NARROW label={label} drawer={panel._drawer_open} size={host.width()}x{host.height()} "
    f"horizontal_max={panel.side_scroll.horizontalScrollBar().maximum()}",
    flush=True,
)

for widget in (event_host, task_host, host):
    widget.close()
store.close()
app.quit()
