"""Disposable Windows window for Stage D pointer and layout checks."""

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication, QMainWindow

from alert_notes.memo_list import MemoListPanel
from alert_notes.sqlite_store import NoteReminderStore
from ui_theme import scaled_stylesheet


def main() -> int:
    app = QApplication([])
    app.setStyleSheet(scaled_stylesheet(1.0))
    with tempfile.TemporaryDirectory(prefix="tomadesk-stage-d-") as directory:
        store = NoteReminderStore(Path(directory) / "stage-d.db", "새 메모")
        category_id = int(store.categories()[0]["id"])
        first = store.create_note("✨테스트 메모", "첫 번째 본문")
        store.set_note_category(first, category_id)
        store.create_note("✨개발용", "두 번째 본문")
        store.create_note("⚡업무용", "세 번째 본문")
        original = store.create_note("업무일반", "기호 없는 메모")
        conflict = store.create_note("업무일반 (2)", "충돌 사본")
        store.conn.execute(
            "UPDATE notes SET conflict_of_sync_id=? WHERE id=?",
            (str(store.note(original)["sync_id"]), conflict),
        )
        store.conn.commit()

        panel = MemoListPanel(store)

        def refresh():
            panel.set_rows(store.notes())

        def assign(note_ids, selected_category):
            store.set_notes_category(note_ids, selected_category)
            panel._set_all_checked(False)
            panel.action_status.setText(f"{len(note_ids)}개 메모의 카테고리를 저장했습니다.")
            refresh()

        panel.filters_changed.connect(refresh)
        panel.category_assign_requested.connect(assign)
        refresh()
        window = QMainWindow()
        window.setWindowTitle("TomaDesk 단계 D 임시 검증")
        window.setCentralWidget(panel)
        window.resize(480, 720)
        window.show()
        result = app.exec()
        window.close()
        store.close()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
