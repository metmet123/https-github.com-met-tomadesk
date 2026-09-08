"""다른 창의 개편 뒤에도 이 세션에서 넣은 기능이 살아 있는지 한 번에 확인한다."""
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = r"D:\251210-백업\백업_251121\폴더 모음\이현주\155._codex\35_단축키 프로그램"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6.QtCore import QDate, QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication
import main_window
from store import Store
from ui_theme import APP_STYLESHEET
from alert_notes import deadline as dl
from alert_notes.calendar import CalendarPanel
from alert_notes.datetime_input import CompactDateEdit
from alert_notes.memo_list import MemoListPanel, list_datetime
from alert_notes.schedule_editor import REPEAT_UNITS, ScheduleEditor
from alert_notes.today_summary import TodaySummaryPanel
from alert_notes.sqlite_store import DATETIME_FMT, NoteReminderStore


class FakeHK:
    def __init__(self, _w):
        pass

    def register(self, *a):
        pass

    def unregister_all(self):
        pass

    def handle_native_event(self, m):
        return False


class FakeRec:
    ignore_click = None

    def stop(self):
        return []


results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    line = ("PASS " if ok else "FAIL ") + name + ("  " + detail if detail else "")
    print(line.encode("utf-8", "replace").decode("utf-8"))


def stamp(days):
    return (datetime.now() + timedelta(days=days)).strftime(DATETIME_FMT)


app = QApplication([])
app.setStyleSheet(APP_STYLESHEET)
temp = tempfile.TemporaryDirectory()
notes = NoteReminderStore(Path(temp.name) / "n.db")

# ---------- 1단계 · 캘린더 라벨과 빠른 메모 ----------
cal = CalendarPanel(notes)
cal.resize(1300, 820)
cal.show()
cal.update_responsive_layout(1300)
app.processEvents()

cal._set_mode("day")
app.processEvents()
check("일간 라벨이 짧음", "년" not in cal.period_label.text(), cal.period_label.text())

cal._set_mode("week")
app.processEvents()
check("주간 라벨에 연도가 없음", "년" not in cal.period_label.text(), cal.period_label.text())

cal._set_mode("month")
app.processEvents()
sizes = [int(v) for v in re.findall(r"font-size:(\d+)px", cal.period_label.text())]
check("월간은 두 줄 · 크기 1:3", len(sizes) == 2 and sizes[1] == sizes[0] * 3, str(sizes))

check("넓으면 헤더 빠른메모 숨김", cal.header_quick_memo_button.isHidden())
cal.update_responsive_layout(1000)
app.processEvents()
check("좁으면 헤더 빠른메모 나타남", not cal.header_quick_memo_button.isHidden())
cal.update_responsive_layout(1300)
app.processEvents()

# ---------- 4단계 · 월간 클릭이 새 일정을 따라감 ----------
cal._set_mode("month")
app.processEvents()
today = date.today()
cal._new_schedule(datetime.combine(today, datetime.min.time().replace(hour=9)))
app.processEvents()
pop = cal.schedule_popover
pop.title_edit.setText("초안")
target = today.replace(day=1) + timedelta(days=17)
for row in range(cal.month_calendar.rowCount()):
    for column in range(cal.month_calendar.columnCount()):
        cell = cal.month_calendar.item(row, column)
        if cell is not None and cell.data(Qt.ItemDataRole.UserRole) == target:
            cal.month_calendar._select_cell(row, column)
app.processEvents()
start, end = pop.current_range()
check("월간 클릭이 새 일정 날짜를 옮김", start.date() == target, str(start))
check("시간·길이·제목은 그대로",
      start.hour == 9 and (end - start) == timedelta(hours=1) and pop.title_edit.text() == "초안")
pop.dismiss()

# ---------- 5-2 · 사이드바 선택 상태 ----------
cal._set_mode("day")
cal.anchor = today
cal.refresh()
app.processEvents()
check("사이드바 '오늘'이 선택됨",
      cal.nav_today_button.isChecked() and not cal.nav_week_button.isChecked())
check("월간 뷰에 지난 일정 흐리기 설정", hasattr(cal.month_calendar, "set_dim_past"))
cal.close()

# ---------- S2 · S3 반복 항목 ----------
editor = ScheduleEditor(notes)
editor.resize(420, 760)
editor.show()
editor.new_item(None)
editor.additional_button.setChecked(True)
app.processEvents()
editor.repeat_combo.setCurrentIndex(editor.repeat_combo.findData("none"))
app.processEvents()
left = [w for w in (editor.repeat_interval, editor.weekdays_edit, editor.repeat_end_combo)
        if w.isVisibleTo(editor)]
check("S2 반복 안 하면 관련 줄이 사라짐", not left, "남은 것 %d" % len(left))
editor.repeat_combo.setCurrentIndex(editor.repeat_combo.findData("weekly"))
app.processEvents()
check("S3 '주마다'로 읽힘", editor.repeat_interval.suffix() == REPEAT_UNITS["weekly"],
      editor.repeat_interval.suffix())
editor.close()

# ---------- 날짜 프리셋 단축키 ----------
field = CompactDateEdit()
field.show()
app.processEvents()
field.setDate(QDate.currentDate().addDays(100))
app.sendEvent(field, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_2,
                               Qt.KeyboardModifier.ControlModifier))
app.processEvents()
check("Ctrl+2 → 내일", field.date() == QDate.currentDate().addDays(1),
      field.date().toString("yyyy-MM-dd"))
check("툴팁에 단축키 안내", "Ctrl+1" in field.toolTip())
field.close()

# ---------- D-Day 셈법 ----------
dl.set_count_today_as_one(False)
check("기본 · 이틀 뒤 D-2", dl.countdown_text(stamp(2)) == "D-2", dl.countdown_text(stamp(2)))
dl.set_count_today_as_one(True)
check("포함 · 이틀 뒤 D-3", dl.countdown_text(stamp(2)) == "D-3", dl.countdown_text(stamp(2)))
dl.set_count_today_as_one(False)

# ---------- 요약 패널 ----------
for index in range(5):
    note_id = notes.create_note("마감 %d" % (index + 1), "")
    notes.set_deadline(note_id, stamp(index + 1), "마감 %d" % (index + 1), False)
summary = TodaySummaryPanel(notes)
summary.resize(300, 700)
summary.show()
summary.refresh()
app.processEvents()
heights = [w.height() for w in summary._sections]
check("요약 · D-Day 가 늘고 빈 구역은 접힘",
      heights[0] > heights[1] and heights[1] == heights[2], str(heights))
check("요약 · 스크롤이 안 생김", summary.deadline_list.verticalScrollBar().maximum() == 0)
check("요약 · 구역 간격이 좁아짐", summary.layout().spacing() <= 5,
      str(summary.layout().spacing()))
lean = TodaySummaryPanel(notes, show_reminders=False)
check("요약 · 예정알림만 빼는 옵션", lean.reminder_list.isHidden())
lean.shutdown()
lean.deleteLater()
summary.shutdown()
summary.close()

# ---------- 메모 목록 ----------
panel = MemoListPanel(notes)
panel.resize(560, 600)
panel.show()
pinned = notes.create_note("띄운 메모", "본문")
notes.update_note(pinned, postit=True)
panel.set_rows(notes.notes(""))
app.processEvents()
titles = []


def walk(item):
    titles.append(item.text(panel.TITLE_COLUMN))
    for index in range(item.childCount()):
        walk(item.child(index))


root = panel.table.invisibleRootItem()
for index in range(root.childCount()):
    walk(root.child(index))
check("메모 목록 · 포스트잇에 📌",
      any(t.startswith(panel.POSTIT_MARK) for t in titles), str(titles[:4]))
check("메모 목록 · Delete 대상 고르기", hasattr(panel, "deletion_ids"))
narrow, wide = panel.column_minimums(400), panel.column_minimums(1000)
check("메모 목록 · 최소 너비가 폭을 따라감",
      all(w >= n for w, n in zip(wide, narrow)) and wide != narrow,
      "%s / %s" % (narrow, wide))
check("수정시간 표기가 짧음", len(list_datetime("202609071530")) <= 14,
      list_datetime("202609071530"))
panel.close()

# ---------- 상단 칩 · 저장 상태 · 설정 ----------
store = Store(Path(temp.name) / "h.db")
patches = [
    patch.object(main_window, "Store", return_value=store),
    patch.object(main_window, "HotkeyManager", FakeHK),
    patch.object(main_window, "WindowsHookRecorder", FakeRec),
]
for item in patches:
    item.start()
window = main_window.MainWindow()
window.resize(1440, 900)
window.show()
app.processEvents()
bar = window.deadline_chip.parentWidget().layout()
order = [bar.itemAt(i).widget() for i in range(bar.count())]
chip_index = order.index(window.deadline_chip)
hint_index = order.index(window.subtab_switch_hint)
tools_index = min(order.index(b) for b in window.workspace_utility_buttons)
check("칩이 탭 줄 밖 · 도구 앞", hint_index < chip_index < tools_index,
      "힌트=%d 칩=%d 도구=%d" % (hint_index, chip_index, tools_index))

first = window.note_store.create_note("예산안", "")
window.note_store.set_deadline(first, stamp(1), "예산안", False)
second = window.note_store.create_note("보고서", "")
window.note_store.set_deadline(second, stamp(3), "보고서", False)
window.refresh_deadline_indicators()
app.processEvents()
check("칩에 나머지 개수", window.deadline_chip.text().endswith("+1"),
      window.deadline_chip.text())

memo_editor = window.alert_panel.editor
actions = [memo_editor.actions_layout.itemAt(i).widget()
           for i in range(memo_editor.actions_layout.count())]
check("저장 상태가 동작 줄에 있음", memo_editor.saved_status in actions)
options = window.deadline_options()
check("설정에 새 항목 둘",
      "deadline_count_today_as_one" in options and "calendar_dim_past" in options)
window.close()
for item in reversed(patches):
    item.stop()
store.conn.close()
notes.close()

failed = [name for name, ok in results if not ok]
print("\n--- %d checks, %d failed ---" % (len(results), len(failed)))
for name in failed:
    print("  FAILED:", name)
sys.exit(1 if failed else 0)
