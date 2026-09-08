from __future__ import annotations

from datetime import date, time


def parse_compact_date(text: str) -> date | None:
    value = str(text).strip()
    normalized = value.replace("-", "").replace("/", "").replace(".", "")
    if not normalized.isdigit() or len(normalized) != 8:
        return None
    try:
        return date(int(normalized[:4]), int(normalized[4:6]), int(normalized[6:8]))
    except ValueError:
        return None


def parse_compact_time(text: str) -> time | None:
    value = str(text).strip()
    normalized = value.replace(":", "")
    if not normalized.isdigit() or not 1 <= len(normalized) <= 4:
        return None
    hour = int(normalized) if len(normalized) <= 2 else int(normalized[:-2])
    minute = 0 if len(normalized) <= 2 else int(normalized[-2:])
    try:
        return time(hour, minute)
    except ValueError:
        return None
