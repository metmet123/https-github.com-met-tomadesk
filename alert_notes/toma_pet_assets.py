"""Load the bundled v2 Toma spritesheet without changing the original asset."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtGui import QPixmap


FRAME_WIDTH = 192
FRAME_HEIGHT = 208
ROW_FRAME_COUNTS = (6, 8, 8, 4, 5, 8, 6, 6, 6)
ACTION_ROWS = {
    "idle": 0,
    "running_right": 1,
    "running_left": 2,
    "waving": 3,
    "jumping": 4,
    "failed": 5,
    "waiting": 6,
    "working": 7,
    "reviewing": 8,
}


def asset_directory() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "alert_notes" / "toma_pet_assets" if getattr(sys, "_MEIPASS", None) else Path(__file__).resolve().parent / "toma_pet_assets"


@dataclass(frozen=True)
class TomaPetMetadata:
    display_name: str
    description: str


class TomaSpriteAtlas:
    """A validated, immutable view of Toma's 8 x 11 v2 spritesheet."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory or asset_directory()
        metadata_path = self.directory / "pet.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"토마펫 설정을 읽을 수 없습니다: {exc}") from exc
        if metadata.get("spriteVersionNumber") != 2:
            raise RuntimeError("토마펫 v2 스프라이트가 필요합니다.")
        self.metadata = TomaPetMetadata(str(metadata.get("displayName", "Toma")), str(metadata.get("description", "")))
        sheet_path = self.directory / str(metadata.get("spritesheetPath", "spritesheet.webp"))
        self.sheet = QPixmap(str(sheet_path))
        if self.sheet.isNull() or self.sheet.size().width() != FRAME_WIDTH * 8 or self.sheet.size().height() != FRAME_HEIGHT * 11:
            raise RuntimeError("토마펫 스프라이트 크기(1536x2288)가 올바르지 않습니다.")

    def action_frame(self, action: str, frame_index: int) -> QPixmap:
        row = ACTION_ROWS.get(action, 0)
        count = ROW_FRAME_COUNTS[row]
        column = frame_index % count
        return self.sheet.copy(column * FRAME_WIDTH, row * FRAME_HEIGHT, FRAME_WIDTH, FRAME_HEIGHT)

    def look_frame(self, direction_index: int) -> QPixmap:
        direction_index %= 16
        row, column = (9, direction_index) if direction_index < 8 else (10, direction_index - 8)
        return self.sheet.copy(column * FRAME_WIDTH, row * FRAME_HEIGHT, FRAME_WIDTH, FRAME_HEIGHT)

    def neutral_frame(self) -> QPixmap:
        """Return Codex v2's dedicated neutral/default frame (idle column 7)."""
        return self.sheet.copy(6 * FRAME_WIDTH, 0, FRAME_WIDTH, FRAME_HEIGHT)
