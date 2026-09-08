from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
import json


DATETIME_FMT = "%Y%m%d%H%M"


@dataclass(frozen=True)
class Occurrence:
    item_id: int
    start: datetime
    end: datetime

    @property
    def key(self) -> str:
        return self.start.strftime(DATETIME_FMT)


def normalize_rule(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except (TypeError, ValueError):
            value = {}
    value = value if isinstance(value, dict) else {}
    frequency = str(value.get("frequency", "none")).casefold()
    if frequency not in {"none", "daily", "weekly", "monthly", "yearly"}:
        frequency = "none"
    weekdays = sorted({int(day) for day in value.get("weekdays", []) if str(day).isdigit() and 0 <= int(day) <= 6})
    return {
        "frequency": frequency,
        "interval": max(1, min(365, int(value.get("interval", 1) or 1))),
        "weekdays": weekdays,
        "until": str(value.get("until", "") or ""),
        "count": max(0, min(9999, int(value.get("count", 0) or 0))),
    }


def expand_occurrences(item, range_start: datetime, range_end: datetime) -> list[Occurrence]:
    start = datetime.strptime(str(item["start_at"]), DATETIME_FMT)
    end = datetime.strptime(str(item["end_at"]), DATETIME_FMT)
    duration = max(timedelta(minutes=1), end - start)
    rule = normalize_rule(item["recurrence_rule"])
    item_id = int(item["id"])
    if rule["frequency"] == "none":
        return [Occurrence(item_id, start, start + duration)] if start < range_end and start + duration > range_start else []

    until = _parse_optional(rule["until"])
    limit = rule["count"]
    occurrences: list[Occurrence] = []
    generated = 0
    current = start
    for _ in range(20000):
        candidates = _period_candidates(current, start, rule)
        for candidate in candidates:
            if candidate < start:
                continue
            generated += 1
            if limit and generated > limit:
                return occurrences
            if until and candidate > until:
                return occurrences
            candidate_end = candidate + duration
            if candidate >= range_end:
                return occurrences
            if candidate_end > range_start:
                occurrences.append(Occurrence(item_id, candidate, candidate_end))
        current = _advance_period(current, rule)
        if current >= range_end and not rule["weekdays"]:
            break
    return occurrences


def _period_candidates(current: datetime, anchor: datetime, rule: dict) -> list[datetime]:
    if rule["frequency"] != "weekly" or not rule["weekdays"]:
        return [current]
    week_start = (current - timedelta(days=current.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return [week_start + timedelta(days=day, hours=anchor.hour, minutes=anchor.minute) for day in rule["weekdays"]]


def _advance_period(value: datetime, rule: dict) -> datetime:
    interval = rule["interval"]
    frequency = rule["frequency"]
    if frequency == "daily":
        return value + timedelta(days=interval)
    if frequency == "weekly":
        return value + timedelta(days=7 * interval)
    if frequency == "monthly":
        month_index = value.year * 12 + value.month - 1 + interval
        year, month = divmod(month_index, 12)
        day = min(value.day, calendar.monthrange(year, month + 1)[1])
        return value.replace(year=year, month=month + 1, day=day)
    return value.replace(year=value.year + interval, day=min(value.day, 28) if value.month == 2 else value.day)


def _parse_optional(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, DATETIME_FMT) if value else None
    except ValueError:
        return None
