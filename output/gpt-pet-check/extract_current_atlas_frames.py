from pathlib import Path

from PIL import Image


ATLAS = Path(r"C:\Users\user\.codex\pets\toma\spritesheet.webp")
OUTPUT = Path(__file__).resolve().parent / "frames"
CELL_WIDTH = 192
CELL_HEIGHT = 208
STATES = {
    "idle": (0, 6),
    "running-right": (1, 8),
    "running-left": (2, 8),
    "waving": (3, 4),
    "jumping": (4, 5),
    "failed": (5, 8),
    "waiting": (6, 6),
    "running": (7, 6),
    "review": (8, 6),
}


with Image.open(ATLAS) as source:
    atlas = source.convert("RGBA")

for state, (row, count) in STATES.items():
    state_dir = OUTPUT / state
    state_dir.mkdir(parents=True, exist_ok=True)
    for column in range(count):
        frame = atlas.crop(
            (
                column * CELL_WIDTH,
                row * CELL_HEIGHT,
                (column + 1) * CELL_WIDTH,
                (row + 1) * CELL_HEIGHT,
            )
        )
        frame.save(state_dir / f"{column:02d}.png")
