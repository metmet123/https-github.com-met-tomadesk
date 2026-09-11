import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

from alert_notes.rich_memo_edit import RichMemoTextEdit, TOGGLE_OPEN_PREFIX


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--width", type=int, default=680)
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    editor = RichMemoTextEdit()
    editor.setWindowTitle("TomaDesk Phase 2 블록 선택 검증")
    editor.resize(args.width, 420)
    editor.setPlainText(
        "회의 준비\n"
        f"{TOGGLE_OPEN_PREFIX}자료 확인\n"
        "발표 자료 초안\n"
        "예산표 검토\n"
        "담당자에게 공유\n"
        "마감 일정 확인"
    )
    editor.block_selection.toggle(editor.document().findBlockByNumber(0), include_family=False)
    editor.block_selection.toggle(editor.document().findBlockByNumber(3), include_family=False)
    editor.block_selection.toggle(editor.document().findBlockByNumber(5), include_family=False)
    editor.show()
    app.processEvents()
    app.processEvents()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not editor.grab().save(str(target)):
        return 1
    if args.hold:
        return app.exec()
    editor.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
