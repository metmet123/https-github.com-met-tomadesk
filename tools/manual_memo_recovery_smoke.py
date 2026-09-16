"""Open a disposable TomaDesk memo panel for real Windows pointer checks."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow

from alert_notes.editor import MemoEditor
from alert_notes.sqlite_store import NoteReminderStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-ms", type=int, default=0)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="tomadesk-memo-smoke-") as directory:
        store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
        parent = store.create_note("메모 편집 오류 검증")
        first = store.create_child_note(parent, "페이지 하나", embedded=True)
        second = store.create_child_note(parent, "페이지 둘", embedded=True)
        store.update_note(parent, content=(
            "<html><body>"
            "<p>글자 선택을 확인하는 첫 번째 문장입니다.</p>"
            f'<p><a href="toma-note://{first}">📄 페이지 하나</a></p>'
            "<p>블록 선택을 확인하는 가운데 문장입니다.</p>"
            f'<p><a href="toma-note://{second}">📄 페이지 둘</a></p>'
            "<p>제목과 접기를 확인하는 마지막 문장입니다.</p>"
            "</body></html>"
        ))
        editor = MemoEditor(store)
        window = QMainWindow()
        window.setWindowTitle("TomaDesk 임시 메모 검증")
        window.setCentralWidget(editor)
        window.resize(1140, 800)
        editor.note_open_requested.connect(lambda note_id: editor.set_note(store.note(note_id)))
        window.show()
        editor.set_note(store.note(parent))
        app.processEvents()
        if args.timeout_ms > 0:
            QTimer.singleShot(args.timeout_ms, app.quit)
        result = app.exec()
        window.close()
        store.close()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
