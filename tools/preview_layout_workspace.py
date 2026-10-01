"""Render the actual favorites panel at supported UI scales, without a DB."""

import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from layout_favorites_panel import FavoritesPanel
from layout_workspace import workspace_payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    for name in ("malgun.ttf", "malgunbd.ttf"):
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Malgun Gothic", 10))
    payload = workspace_payload({"windows": [
        {"path": "D:/다운로드", "monitor": 1, "rect": [280, 0, 620, 900]},
        {"path": "D:/업무/제출", "monitor": 1, "rect": [900, 0, 1000, 900]},
    ], "workspace": {"enabled": True, "favorites": [
        {"path": "D:/" + name, "name": name}
        for name in ("다운로드", "제출", "예산 관련", "시간외수당", "여비", "매월", "2027년 본예산", "긴 폴더 이름도 전체 경로를 툴팁으로 확인할 수 있습니다")
    ]}})
    panel = FavoritesPanel()
    for scale in (1.0, 1.25, 1.5):
        panel.apply_scale(scale)
        panel.configure("다운로드 · 제출", payload)
        panel.resize(round(280 * scale), round(650 * scale))
        panel.show()
        panel.list.setCurrentRow(1)
        app.processEvents()
        path = args.output / f"layout-favorites-{round(scale * 100)}.png"
        if not panel.grab().save(str(path)):
            raise RuntimeError("PNG 저장 실패")
        print(path)
    panel.hide()
    panel.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    main()
