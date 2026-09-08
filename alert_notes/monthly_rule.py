"""Monthly repeat rules for the recurring-work postit.

Three shapes cover what monthly office work actually looks like:

* ``day``     — the 5th of every month
* ``last``    — the last day of every month, whatever length it is
* ``weekday`` — the third Tuesday, and "last Friday" via ``ordinal = -1``

The rule is stored as JSON on the note so it survives export and restore.
"""

from __future__ import annotations

import calendar
import json
from datetime import date

KIND_DAY = "day"
KIND_LAST = "last"
KIND_WEEKDAY = "weekday"
KINDS = (KIND_DAY, KIND_LAST, KIND_WEEKDAY)

WEEKDAY_NAMES = ("월", "화", "수", "목", "금", "토", "일")
ORDINAL_NAMES = {1: "첫째", 2: "둘째", 3: "셋째", 4: "넷째", -1: "마지막"}


def make_rule(kind: str, day: int = 1, ordinal: int = 1, weekday: int = 0) -> dict:
    kind = kind if kind in KINDS else KIND_DAY
    return {
        "kind": kind,
        "day": max(1, min(31, int(day))),
        "ordinal": int(ordinal) if int(ordinal) in ORDINAL_NAMES else 1,
        "weekday": max(0, min(6, int(weekday))),
    }


def parse_rule(raw) -> dict | None:
    """Return a normalised rule, or None when the note has no monthly repeat."""
    if isinstance(raw, dict):
        values = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            values = json.loads(text)
        except (TypeError, ValueError):
            return None
    if not isinstance(values, dict) or values.get("kind") not in KINDS:
        return None
    return make_rule(
        str(values.get("kind")),
        values.get("day", 1),
        values.get("ordinal", 1),
        values.get("weekday", 0),
    )


def dump_rule(rule: dict | None) -> str:
    return "" if rule is None else json.dumps(make_rule(**{
        "kind": rule.get("kind", KIND_DAY),
        "day": rule.get("day", 1),
        "ordinal": rule.get("ordinal", 1),
        "weekday": rule.get("weekday", 0),
    }), ensure_ascii=False)


def occurrence_in(rule: dict, year: int, month: int) -> date:
    """The single date this rule lands on in the given month."""
    rule = make_rule(**rule) if not isinstance(rule, dict) or "kind" not in rule else rule
    last_day = calendar.monthrange(year, month)[1]
    kind = rule.get("kind", KIND_DAY)
    if kind == KIND_LAST:
        return date(year, month, last_day)
    if kind == KIND_WEEKDAY:
        wanted = int(rule.get("weekday", 0))
        ordinal = int(rule.get("ordinal", 1))
        matches = [
            day for day in range(1, last_day + 1)
            if date(year, month, day).weekday() == wanted
        ]
        if not matches:
            return date(year, month, last_day)
        index = ordinal - 1 if ordinal > 0 else len(matches) - 1
        index = max(0, min(len(matches) - 1, index))
        return date(year, month, matches[index])
    # A 31st in a 30-day month falls back to that month's last day.
    return date(year, month, min(int(rule.get("day", 1)), last_day))


def next_occurrence(rule: dict, after: date) -> date:
    """First landing date strictly on or after `after`."""
    current = occurrence_in(rule, after.year, after.month)
    if current >= after:
        return current
    year, month = (after.year + 1, 1) if after.month == 12 else (after.year, after.month + 1)
    return occurrence_in(rule, year, month)


def is_due(rule: dict, today: date) -> bool:
    """True once this month's date has arrived, so a late start still shows."""
    return occurrence_in(rule, today.year, today.month) <= today


def month_key(value: date) -> str:
    return f"{value.year:04d}{value.month:02d}"


def describe(rule: dict | None) -> str:
    if rule is None:
        return "반복 없음"
    kind = rule.get("kind", KIND_DAY)
    if kind == KIND_LAST:
        return "매달 말일"
    if kind == KIND_WEEKDAY:
        ordinal = ORDINAL_NAMES.get(int(rule.get("ordinal", 1)), "첫째")
        weekday = WEEKDAY_NAMES[max(0, min(6, int(rule.get("weekday", 0))))]
        return f"매달 {ordinal} 주 {weekday}요일"
    return f"매달 {int(rule.get('day', 1))}일"


UNCHECKED_PREFIX = "☐ "
CHECKED_PREFIX = "☑ "


def reset_checklist(content: str) -> str:
    """Start the new month with every checklist line unticked."""
    return str(content or "").replace(CHECKED_PREFIX, UNCHECKED_PREFIX).replace("☑", "☐")


SUGGEST_MIN_MONTHS = 3


def suggest_rules(rows, today: date, minimum: int = SUGGEST_MIN_MONTHS) -> list[dict]:
    """Titles that keep coming back on the same day of the month.

    Only a suggestion: the program never creates the repeat itself, because a
    wrong guess is impossible for the user to explain.  `rows` is any sequence
    of (title, date) pairs — schedules or notes.
    """
    buckets: dict[tuple[str, int], set[str]] = {}
    for title, when in rows:
        name = str(title or "").strip()
        if not name or when is None or when > today:
            continue
        buckets.setdefault((name, when.day), set()).add(month_key(when))
    found = []
    for (name, day), months in buckets.items():
        if len(months) < minimum:
            continue
        found.append({
            "title": name,
            "months": len(months),
            "rule": make_rule(KIND_DAY, day=day),
        })
    return sorted(found, key=lambda item: (-item["months"], item["title"]))
