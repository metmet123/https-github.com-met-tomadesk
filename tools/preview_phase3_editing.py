"""Capture Phase 3 memo controls on a disposable Windows Qt window."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication

from alert_notes.editor import MemoEditor
from alert_notes.sqlite_store import NoteReminderStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--width", type=int, default=1100)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        store = NoteReminderStore(Path(directory) / "preview.db", "새 메모")
        window = MemoEditor(store)
        window.setWindowTitle("TomaDesk Phase 3 편집 검증")
        window.resize(args.width, 760)
        body = window.content_edit
        body.setPlainText("프로젝트 제목\n개요와 일정\n세부 항목\n후속 작업")
        body.setTextCursor(QTextCursor(body.document().findBlockByNumber(0)))
        body.apply_heading1()
        body.setTextCursor(QTextCursor(body.document().findBlockByNumber(2)))
        body.apply_heading2()
        body.fold_heading(body.document().findBlockByNumber(2))
        window.show()
        app.processEvents()
        app.processEvents()
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        saved = window.grab().save(str(output))
        window.close()
        app.processEvents()
        store.close()
        return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
