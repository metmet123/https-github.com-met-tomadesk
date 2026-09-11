"""설명서 각 장을 PNG로 뽑아 마커 위치를 눈으로 확인하는 도구."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QFontDatabase  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from user_manual import UserManualDialog  # noqa: E402

OUT = ROOT / "tmp" / "manual_preview"


def main() -> int:
    app = QApplication.instance() or QApplication([])
    font_path = Path(r"C:\Windows\Fonts\malgun.ttf")
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    OUT.mkdir(parents=True, exist_ok=True)
    dialog = UserManualDialog()
    dialog.resize(1120, 900)
    dialog.show()
    app.processEvents()
    for index in range(len(dialog._slides)):
        dialog._go(index)
        app.processEvents()
        page = dialog.scroll.widget()
        page.grab().save(str(OUT / f"slide_{index + 1:02d}.png"), "PNG")
        print(f"  slide_{index + 1:02d}.png")
    dialog.hide()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
