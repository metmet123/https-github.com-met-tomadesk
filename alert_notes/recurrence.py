import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


RULE_NONE = "none"
RULE_DAILY = "daily"
RULE_WEEKDAYS = "weekdays"
RULE_WEEKLY = "weekly"
RULE_MONTHLY = "monthly"


@dataclass(frozen=True)
class RecurrenceRule:
    rule_type: str = RULE_NONE
    weekdays: tuple[int, ...] = ()
    month_day: int | None = None
    end_type: str = "never"
    end_date: str | None = None
    max_occurrences: int | None = None


def next_occurrence(after: datetime, rule: RecurrenceRule) -> datetime | None:
    if rule.rule_type == RULE_NONE:
        return None
    return datetime.combine(_next_date(after.date(), rule), time(after.hour, after.minute))


def is_allowed(value: datetime, rule: RecurrenceRule, occurrence_number: int) -> bool:
    if rule.end_type == "date" and rule.end_date:
        if value.date() > datetime.strptime(rule.end_date, "%Y%m%d").date():
            return False
    if rule.end_type == "count" and rule.max_occurrences:
        return occurrence_number <= rule.max_occurrences
    return True


def repeat_summary(rule: RecurrenceRule) -> str:
    base = {
        RULE_NONE: "반복 없음", RULE_DAILY: "매일", RULE_WEEKDAYS: "평일",
        RULE_MONTHLY: f"매월 {rule.month_day or 1}일",
    }.get(rule.rule_type)
    if rule.rule_type == RULE_WEEKLY:
        names = "·".join("월화수목금토일"[day] for day in rule.weekdays)
        base = f"매주 {names}"
    if rule.end_type == "date" and rule.end_date:
        end = datetime.strptime(rule.end_date, "%Y%m%d").strftime("%Y-%m-%d")
        return f"{base} · {end}까지"
    if rule.end_type == "count" and rule.max_occurrences:
        return f"{base} · {rule.max_occurrences}회"
    return base or "반복 없음"


def _next_date(after: date, rule: RecurrenceRule) -> date:
    if rule.rule_type == RULE_DAILY:
        return after + timedelta(days=1)
    if rule.rule_type == RULE_WEEKDAYS:
        candidate = after + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate
    if rule.rule_type == RULE_WEEKLY:
        days = set(rule.weekdays or (after.weekday(),))
        candidate = after + timedelta(days=1)
        while candidate.weekday() not in days:
            candidate += timedelta(days=1)
        return candidate
    year, month = ((after.year + 1, 1) if after.month == 12 else (after.year, after.month + 1))
    day = min(rule.month_day or after.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
