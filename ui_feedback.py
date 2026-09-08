from __future__ import annotations

from collections.abc import Iterable


STATUS_LEVELS = {"info", "success", "warning", "error"}


def apply_status(label, message: str, level: str = "info") -> None:
    """Update status text and refresh its semantic color."""
    normalized = level if level in STATUS_LEVELS else "info"
    label.setProperty("level", normalized)
    label.setText(message)
    style = label.style()
    style.unpolish(label)
    style.polish(label)
    label.update()


def parse_splitter_sizes(raw_value: str, fallback: Iterable[int]) -> list[int]:
    """Return two positive splitter sizes from a persisted comma string."""
    try:
        sizes = [int(value) for value in raw_value.split(",")]
    except (AttributeError, TypeError, ValueError):
        sizes = []
    if len(sizes) == 2 and all(size > 0 for size in sizes):
        return sizes
    return list(fallback)


def serialize_splitter_sizes(sizes: Iterable[int]) -> str:
    return ",".join(str(max(1, int(size))) for size in sizes)
