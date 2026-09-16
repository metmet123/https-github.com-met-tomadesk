"""Disposable Windows memo window for pointer and F11 usability checks."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-ms", type=int, default=0)
    parser.add_argument("--capture-dir", type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="tomadesk-character-smoke-") as directory:
        store = NoteReminderStore(Path(directory) / "notes.db", "새 메모")
        note_id = store.create_note("글자 다중 선택 검증", (
            "<html><body><p>첫 번째 글자 범위를 Ctrl+드래그로 선택합니다.</p>"
            "<p>두 번째 글자 범위를 더한 뒤 아래 서식 도구를 누릅니다.</p>"
            '<p><a href="https://example.com">링크 일부만 해제</a>합니다.</p>'
            "<p>F11을 누르면 메모 본문이 더 넓어집니다.</p></body></html>"
        ))
        panel = AlertNotesPanel(store)
        window = QMainWindow()
        window.setWindowTitle("TomaDesk 임시 글자 선택·F11 검증")
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        workspace_bar = QLabel("메모·일정   메모 편집   캘린더   알림내역")
        workspace_bar.setFixedHeight(52)
        workspace_bar.setStyleSheet("background:#f8fafc;padding-left:16px;color:#334155;")
        layout.addWidget(workspace_bar)
        layout.addWidget(panel, 1)
        panel.editor_fullscreen_changed.connect(
            lambda on: workspace_bar.setVisible(not on)
        )
        window.setCentralWidget(host)
        window.resize(1180, 820)
        window.show()
        panel.show_note(note_id)
        app.processEvents()
        if args.capture_dir is not None:
            args.capture_dir.mkdir(parents=True, exist_ok=True)

            def capture() -> None:
                window.grab().save(str(args.capture_dir / "normal.png"))
                panel.toggle_editor_fullscreen(True)
                app.processEvents()
                app.processEvents()
                window.grab().save(str(args.capture_dir / "fullscreen.png"))
                body = panel.editor.content_edit
                for start, end in ((0, 5), (26, 32)):
                    cursor = QTextCursor(body.document())
                    cursor.setPosition(start)
                    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                    body.character_selection.add_cursor(cursor)
                app.processEvents()
                window.grab().save(str(args.capture_dir / "selection.png"))
                app.quit()

            QTimer.singleShot(500, capture)
        if args.timeout_ms > 0:
            QTimer.singleShot(args.timeout_ms, app.quit)
        result = app.exec()
        window.close()
        store.close()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
