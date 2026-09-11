"""Regenerate the screenshots used by the in-app user manual.

The manual shows real screens, not drawings, so the pictures must be rebuilt
whenever the UI moves.  This script opens the app against a throwaway data
folder, fills it with the sample data the manual talks about, and saves one PNG
per screen into ``assets/manual``.

    python tools/capture_manual_shots.py

Nothing here touches the user's own database: every write goes to a temporary
folder that is deleted when the script ends.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QFontDatabase  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import main_window  # noqa: E402
from store import Store  # noqa: E402
from ui_theme import APP_STYLESHEET  # noqa: E402

OUT_DIR = ROOT / "assets" / "manual"
WINDOW_SIZE = (1360, 860)
SETTINGS_SIZE = (1020, 560)


class _FakeHotkeyManager:
    def __init__(self, _window_id):
        pass

    def register(self, *_args):
        pass

    def unregister_all(self):
        pass

    def handle_native_event(self, _message):
        return False


class _FakeRecorder:
    ignore_click = None

    def stop(self):
        return []


def _seed_actions(store: Store) -> None:
    store.save_action({
        "name": "회사 주소 입력", "hotkey": "Ctrl+Alt+1", "action_type": "text",
        "payload": {"text": "서울특별시 중구 세종대로 110", "enter": False}, "active": True,
    })
    store.save_action({
        "name": "메일 서명", "hotkey": "Ctrl+Alt+2", "action_type": "text",
        "payload": {"text": "감사합니다.\n이현주 드림", "enter": False}, "active": True,
    })
    store.save_action({
        "name": "사내 포털 열기", "hotkey": "Ctrl+Alt+3", "action_type": "url",
        "payload": {"url": "https://portal.example.com"}, "active": True,
    })
    store.save_action({
        "name": "작업 폴더 열기", "hotkey": "Ctrl+Alt+4", "action_type": "path",
        "payload": {"path": "D:\작업"}, "active": True,
    })
    store.save_action({
        "name": "일일보고 자동 입력", "hotkey": "Ctrl+Alt+5", "action_type": "macro",
        "payload": {"steps": [
            {"type": "click", "x": 640, "y": 380, "button": "left", "delay": 0.4},
            {"type": "text", "text": "일일 업무 보고", "delay": 0.2},
            {"type": "key", "key": "enter", "delay": 0.3},
        ], "repeat": 1, "speed": 1.0}, "active": False,
    })


def _html(body: str) -> str:
    """메모 본문은 HTML 문서로 저장해야 서식 있는 글로 열린다."""
    return "<!DOCTYPE HTML><html><body>" + body + "</body></html>"


def _seed_notes(notes) -> int:
    parent = notes.create_note("업무 정리", "")
    notes.update_note(parent, content=_html(
        "<h2>이번 주 할 일</h2>"
        "<ul><li>월요일 회의 자료 정리</li>"
        "<li>견적서 초안 보내기</li>"
        "<li>거래처 회신 확인</li></ul>"
        "<p>회의는 매주 월요일 10시, 3층 회의실에서 진행한다.</p>"
        "<p>견적 단가는 <b>지난 분기 기준</b>으로 먼저 계산하고, "
        "확정 전에 박과장 확인을 받는다.</p>"
    ))
    child = notes.create_child_note(parent, "회의록 2026-09-14")
    notes.update_note(child, content=_html(
        "<p><b>참석</b> 이현주, 김대리, 박과장</p>"
        "<p>· 9월 일정 확정</p><p>· 견적 단가 재확인</p>"
    ))
    second = notes.create_note("자주 쓰는 문구", "")
    notes.update_note(second, content=_html("<p>안내 문구와 서식을 모아 둔 메모.</p>"))
    third = notes.create_note("거래처 연락처", "")
    notes.update_note(third, content=_html("<p>담당자 전화번호 목록.</p>"))
    due = (datetime.now() + timedelta(days=3)).strftime("%Y%m%d0900")
    notes.set_deadline(second, due, label="자료 제출", alert=True)
    return parent


def _seed_schedules(notes) -> None:
    schedules = notes.schedules
    today = datetime.now().replace(minute=0, second=0, microsecond=0)
    rows = [
        ("주간 회의", today.replace(hour=10), today.replace(hour=11), "event", "업무"),
        ("견적서 보내기", today.replace(hour=14), today.replace(hour=15), "task", "업무"),
        ("거래처 방문", today.replace(hour=16), today.replace(hour=17), "event", "외근"),
        ("치과 예약", (today + timedelta(days=1)).replace(hour=18),
         (today + timedelta(days=1)).replace(hour=19), "event", "개인"),
    ]
    for title, start, end, kind, category in rows:
        schedules.save_item({
            "title": title,
            "start_at": start.strftime("%Y%m%d%H%M"),
            "end_at": end.strftime("%Y%m%d%H%M"),
            "item_type": kind,
            "category": category,
            "reminders": [10],
        })


def _save(widget, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    path = OUT_DIR / f"{name}.png"
    pixmap.save(str(path), "PNG")
    print(f"  {path.relative_to(ROOT)}  {pixmap.width()}x{pixmap.height()}")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLESHEET)
    font_path = Path(r"C:\Windows\Fonts\malgun.ttf")
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))

    temp_dir = tempfile.TemporaryDirectory()
    data_dir = Path(temp_dir.name)
    store = Store(data_dir / "hotkeys.db")
    _seed_actions(store)

    # 창을 만들기 전에 먼저 채워야 목록·요약이 처음부터 내용을 보여준다.
    from alert_notes.sqlite_store import NoteReminderStore
    seed_notes = NoteReminderStore(data_dir / "alert_notes.db", default_title="새 메모")
    memo_id = _seed_notes(seed_notes)
    _seed_schedules(seed_notes)
    seed_notes.close()

    patches = [
        patch.object(main_window, "Store", return_value=store),
        patch.object(main_window, "HotkeyManager", _FakeHotkeyManager),
        patch.object(main_window, "WindowsHookRecorder", _FakeRecorder),
    ]
    for item in patches:
        item.start()
    window = main_window.MainWindow(store)
    window.resize(*WINDOW_SIZE)
    window.show()
    app.processEvents()

    print("캡처 시작")

    # 1. 단축키 목록 화면
    window._switch_workspace(0)
    if window.table.rowCount():
        window.table.selectRow(0)
        window.load_selected()
    app.processEvents()
    _save(window, "01_shortcut_list")

    # 2. 반복작업 편집 화면
    if window.table.rowCount() >= 5:
        window.table.selectRow(4)
        window.load_selected()
    app.processEvents()
    _save(window, "02_macro_editor")

    # 3. 메모 편집 화면
    window._switch_workspace(1)
    panel = window.alert_panel
    panel.tabs.setCurrentIndex(0)
    panel.list_panel.toggle_all_folds()
    panel.select_note(memo_id)
    panel.list_panel.select_id(memo_id)
    app.processEvents()
    _save(window, "03_memo_editor")

    # 4. 캘린더 화면 (주간 보기가 한 주 흐름을 가장 잘 보여준다)
    panel.tabs.setCurrentIndex(1)
    panel.calendar._set_mode("week")
    app.processEvents()
    _save(window, "04_calendar")

    # 5. 알림내역 화면
    panel.tabs.setCurrentIndex(2)
    app.processEvents()
    _save(window, "05_reminder_history")

    # 6. 설정 창
    from settings_dialog import SettingsDialog
    dialog = SettingsDialog(
        hotkeys={
            "main_open": window.main_open_hotkey,
            "tray_hide": window.tray_hide_hotkey,
            "exit": window.exit_hotkey,
            "quick_memo": window.quick_memo_hotkey,
            "new_memo": window.new_memo_hotkey,
            "today_view": window.today_view_hotkey,
            "memo_search": window.memo_search_hotkey,
            "quick_schedule": window.quick_schedule_hotkey,
            "record_stop": window.record_stop_hotkey,
            "playback_stop": window.playback_stop_hotkey,
        },
        startup_mode=window.startup_mode,
        # 설명서 그림에 임시 폴더 경로가 박히지 않도록 보기 좋은 예시 경로를 쓴다.
        data_dir=Path(r"D:\TomaDesk\data"),
        parent=window,
    )
    dialog.resize(1020, 560)
    dialog.show()
    app.processEvents()
    _save(dialog, "06_settings")
    dialog.settings_tabs.setCurrentIndex(3)
    app.processEvents()
    _save(dialog, "09_settings_data")
    dialog.close()

    # 7. 포스트잇
    note = window.note_store.note(memo_id)
    from alert_notes.postit import PostitWindow
    postit = PostitWindow(window.note_store, note)
    postit.resize(340, 300)
    postit.show()
    app.processEvents()
    _save(postit, "07_postit")
    postit.hide()

    # 8. 빠른 메모
    from alert_notes.quick_capture import QuickMemoDialog
    quick = QuickMemoDialog(window.note_store, parent=window)
    quick.title_edit.setText("거래처 회신 확인")
    quick.content_edit.setPlainText("내일 오전까지 답 메일 확인하고 결과를 업무 정리 메모에 옮기기")
    quick.resize(560, 330)
    quick.show()
    app.processEvents()
    _save(quick, "08_quick_memo")
    quick.close()

    print("캡처 완료")
    window.hide()
    for item in reversed(patches):
        item.stop()
    store.conn.close()
    try:
        temp_dir.cleanup()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
