"""Disposable real-window smoke harness for the memo editor.

Uses only the database path supplied on the command line and never opens the
normal TomaDesk data directory.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication, QMainWindow

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: manual_memo_mobile_smoke.py <temporary-db>")
    app = QApplication(sys.argv)
    store = NoteReminderStore(Path(sys.argv[1]), "새 메모")
    if not store.notes():
        first = store.create_note("모바일 연동 확인", "# 제목 1\n\n1~4 범위와 `inline code`\n\n| A | B |\n|---|---|\n| 1 | 2 |")
        store.set_note_category(first, int(store.categories()[0]["id"]))
        store.create_child_note(first, "하위 메모")
        store.create_note("일괄 지정 확인", "카테고리 지정 대상")
    if not store.memo_data.templates():
        store.memo_data.save_template(
            "회의", "meeting",
            {"version": 1, "kind": "blocks", "html": "<p>회의 템플릿</p>", "text": "회의 템플릿", "blocks": []},
        )
    window = QMainWindow()
    window.setWindowTitle("TomaDesk 메모 구현 검증")
    panel = AlertNotesPanel(store)
    window.setCentralWidget(panel)
    window.resize(1080, 760)
    window.show()
    app.aboutToQuit.connect(panel.shutdown)
    app.aboutToQuit.connect(store.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
