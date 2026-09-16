"""Disposable real Windows window for Stage F pointer checks."""

import argparse
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QMainWindow

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from ui_theme import scaled_stylesheet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, choices=(1.0, 1.25, 1.5), default=1.0)
    parser.add_argument("--timeout-ms", type=int, default=90000)
    options = parser.parse_args()
    app = QApplication([])
    app.setFont(QFont("Segoe UI Variable", 9))
    app.setStyleSheet(scaled_stylesheet(options.scale))
    with tempfile.TemporaryDirectory(prefix="tomadesk-stage-f-") as directory:
        store = NoteReminderStore(Path(directory) / "stage-f.db", "새 메모")
        first = store.create_note("단계 F 검증 메모", "첫 문장입니다. 중요한 결정 사항.\n\n/템플릿")
        second = store.create_note("✨개발용", "오늘 마감 테스트")
        store.set_deadline(second, datetime.now().strftime("%Y-%m-%d 23:59"), "오늘 마감 테스트")
        child = store.create_child_note(first, "[TD] 하위 메모")
        store.set_note_category(first, int(store.categories()[1]["id"]))
        window = QMainWindow()
        window.setWindowTitle(f"TomaDesk 단계 F 임시 검증 {round(options.scale * 100)}%")
        panel = AlertNotesPanel(store)
        window.setCentralWidget(panel)
        window.resize(1330, 900)
        window.show()
        panel.show_note(first)
        if options.scale != 1.0:
            QTimer.singleShot(0, lambda: panel.apply_ui_scale(options.scale))
        QTimer.singleShot(max(1000, options.timeout_ms), app.quit)
        app.processEvents()
        print(f"STAGE_F_READY scale={options.scale} temp={directory} notes={first},{second},{child}", flush=True)
        result = app.exec()
        panel.shutdown()
        window.close()
        store.close()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
