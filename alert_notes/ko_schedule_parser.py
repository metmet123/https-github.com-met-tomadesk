"""한 줄로 적은 일정을 읽는 한국어 규칙 파서.

``dateparser``에 한국어를 넣어 보면 "다음주 화요일 10시"는 ``None``, "내일 오후
3시"는 시각을 통째로 버린다.  한국어 일정 표현은 어휘가 좁고(오늘·내일·요일·N시·
오전/오후·매주) 어순이 안정적이라, 정규식 층을 앞에서부터 벗겨 내는 쪽이 훨씬
정확하다.  외부 의존성은 쓰지 않는다.

안전한 쪽으로 설계했다.  날짜·시간은 **문장 맨 앞에서만** 읽고, 뒤에 나오는
숫자는 건드리지 않는다.  "9월 매출 정리"처럼 달만 있고 날짜가 없는 표현은 아예
패턴에 없으므로 제목 그대로 남는다.  분류(``#업무``)와 알림(``!30분전``)은 사람이
일부러 찍은 표시이므로 위치와 상관없이 읽는다.

인식한 구간은 ``spans``로 함께 돌려준다.  입력창에 밑줄을 긋고 클릭으로 인식을
취소하려면 결과값이 아니라 위치가 필요하기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import re

from .categories import CATEGORIES


WEEKDAY_LETTERS = "월화수목금토일"
DAY_WORDS = {
    "그제": -2, "어제": -1, "오늘": 0, "금일": 0,
    "내일": 1, "낼": 1, "명일": 1, "모레": 2, "글피": 3,
}
WEEK_OFFSETS = {
    "이번주": 0, "금주": 0,
    "다음주": 1, "담주": 1, "차주": 1, "낼주": 1,
    "저번주": -1, "지난주": -1, "전주": -1,
}
MERIDIEM = ("오전", "오후", "아침", "점심", "저녁", "밤", "새벽")
CATEGORY_KEYS = {name: key for name, key in CATEGORIES}

_SPACE = r"[ \t]*"
_MERIDIEM_GROUP = f"({'|'.join(MERIDIEM)})?"

_RE_CATEGORY = re.compile(r"#([가-힣A-Za-z0-9]+)")
_RE_REMINDER = re.compile(r"!(\d{1,3})\s*(시간|분)?\s*(?:전)?")
_RE_REPEAT_WEEKDAY = re.compile(rf"매주{_SPACE}([{WEEKDAY_LETTERS}])요일?")
_RE_REPEAT = re.compile(r"매(일|주|달|월|년)")
_RE_ABS_YMD = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
_RE_ABS_MD_KO = re.compile(rf"(\d{{1,2}})월{_SPACE}(\d{{1,2}})일")
_RE_ABS_MD_SLASH = re.compile(r"(\d{1,2})/(\d{1,2})")
_RE_REL_DAY = re.compile(rf"(\d{{1,2}})일{_SPACE}(?:뒤|후)")
_RE_REL_WEEK = re.compile(rf"(\d{{1,2}})주{_SPACE}(?:뒤|후)")
_RE_WEEKDAY = re.compile(
    rf"(이번{_SPACE}주|다음{_SPACE}주|담주|차주|낼주|금주|저번{_SPACE}주|지난{_SPACE}주|전주)?"
    rf"{_SPACE}([{WEEKDAY_LETTERS}])요일"
)
_RE_DAY_WORD = re.compile(rf"({'|'.join(sorted(DAY_WORDS, key=len, reverse=True))})")
_RE_TIME_COLON = re.compile(rf"{_MERIDIEM_GROUP}{_SPACE}(\d{{1,2}}):(\d{{2}})")
# "16시 30분"의 분과 "16시 30분간"의 길이는 같은 글자로 시작한다.  뒤에 간·동안이
# 붙으면 분이 아니라 길이이므로 여기서 넘긴다.
_RE_TIME_HOUR = re.compile(
    rf"{_MERIDIEM_GROUP}{_SPACE}(\d{{1,2}}){_SPACE}시{_SPACE}"
    rf"(?:(반)|(\d{{1,2}}){_SPACE}분(?!{_SPACE}(?:간|동안)))?"
)
_RE_RANGE_MARK = re.compile(rf"(?:~|-|–|—|부터){_SPACE}")
_RE_DURATION = re.compile(
    rf"(?:(\d{{1,2}}){_SPACE}시간{_SPACE}(?:(\d{{1,2}}){_SPACE}분)?|(\d{{1,3}}){_SPACE}분{_SPACE}(?:간|동안))"
)
_RE_ALL_DAY = re.compile(rf"(?:하루{_SPACE})?종일")
# 인식한 자리를 지운 뒤 제목 앞뒤에 남는 조사·기호.
_RE_TITLE_HEAD = re.compile(r"^[\s·,./~\-–—]*(?:에|에서|부터|까지|쯤|경|즈음)?[\s·,./~\-–—]*")
_RE_TITLE_TAIL = re.compile(r"[\s·,./~\-–—]+$")


@dataclass(frozen=True)
class Span:
    """원문에서 인식한 구간.  클릭 취소·밑줄이 이 인덱스를 쓴다."""

    start: int
    end: int
    kind: str
    text: str


@dataclass(frozen=True)
class ParsedSchedule:
    title: str
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    category: str | None = None
    reminders: tuple[int, ...] = ()
    recurrence: dict | None = None
    spans: tuple[Span, ...] = field(default=())

    @property
    def has_datetime(self) -> bool:
        return self.start is not None

    @property
    def is_empty(self) -> bool:
        """무엇도 못 읽었으면 파서가 끼어들지 않는다."""
        return not self.spans


def parse(
    text: str, now: datetime | None = None,
    base: datetime | None = None, base_end: datetime | None = None,
) -> ParsedSchedule:
    """한 줄을 일정 값으로 나눈다.

    ``now``는 "내일"·"금요일"의 기준 시각, ``base``/``base_end``는 사용자가 이미
    정해 둔 범위(드래그한 칸)다.  날짜만 말하고 시각을 말하지 않았을 때 그 시각과
    길이를 그대로 쓴다 — 14시부터 한 시간 반을 끌고 "내일 회의"라고 적으면
    내일 14:00–15:30이다.
    """
    raw = str(text or "")
    now = now or datetime.now()
    base = (base or now).replace(second=0, microsecond=0)
    kept_span = (base_end - base) if base_end and base_end > base else timedelta(hours=1)
    spans: list[Span] = []

    category = _take_category(raw, spans)
    reminders = _take_reminders(raw, spans)
    cursor = _skip_space(raw, 0)
    recurrence, cursor = _take_recurrence(raw, cursor, spans)
    parsed_date, parsed_time, end_time, duration, all_day, cursor = _take_datetime(
        raw, cursor, spans, now
    )

    start = end = None
    if parsed_date is not None or parsed_time is not None or all_day:
        day = parsed_date or base.date()
        if all_day:
            start = datetime.combine(day, time.min)
            end = datetime.combine(day, time(23, 59))
        else:
            clock = parsed_time or base.time().replace(second=0, microsecond=0)
            start = datetime.combine(day, clock)
            if end_time is not None:
                end = datetime.combine(day, end_time)
                if end <= start:
                    end += timedelta(days=1)
            elif duration is not None:
                end = start + duration
            else:
                end = start + (kept_span if parsed_time is None else timedelta(hours=1))

    if recurrence is not None and start is not None and recurrence.get("weekdays"):
        # 매주 월요일이라고 했으면 첫 회차도 그 요일이어야 한다.
        start, end = _align_to_weekday(start, end, recurrence["weekdays"][0])

    title = _remaining_title(raw, spans)
    return ParsedSchedule(
        title=title, start=start, end=end, all_day=all_day, category=category,
        reminders=tuple(reminders), recurrence=recurrence,
        spans=tuple(sorted(spans, key=lambda span: span.start)),
    )


# ------------------------------------------------------------------ 표시자 --
def _take_category(raw: str, spans: list[Span]) -> str | None:
    for match in _RE_CATEGORY.finditer(raw):
        key = CATEGORY_KEYS.get(match.group(1))
        if key is None:
            # 모르는 태그는 제목의 일부다.  임의로 지우지 않는다.
            continue
        spans.append(Span(match.start(), match.end(), "category", match.group(0)))
        return key
    return None


def _take_reminders(raw: str, spans: list[Span]) -> list[int]:
    values: list[int] = []
    for match in _RE_REMINDER.finditer(raw):
        amount = int(match.group(1))
        minutes = amount * 60 if match.group(2) == "시간" else amount
        if 0 < minutes <= 60 * 24 * 7 and len(values) < 5:
            values.append(minutes)
            spans.append(Span(match.start(), match.end(), "reminder", match.group(0)))
    return values


# -------------------------------------------------------------------- 반복 --
def _take_recurrence(raw: str, cursor: int, spans: list[Span]) -> tuple[dict | None, int]:
    match = _RE_REPEAT_WEEKDAY.match(raw, cursor)
    if match:
        spans.append(Span(match.start(), match.end(), "repeat", match.group(0)))
        weekday = WEEKDAY_LETTERS.index(match.group(1))
        rule = {"frequency": "weekly", "interval": 1, "weekdays": [weekday], "until": "", "count": 0}
        return rule, _skip_space(raw, match.end())
    match = _RE_REPEAT.match(raw, cursor)
    if match:
        frequency = {"일": "daily", "주": "weekly", "달": "monthly", "월": "monthly", "년": "yearly"}[match.group(1)]
        spans.append(Span(match.start(), match.end(), "repeat", match.group(0)))
        rule = {"frequency": frequency, "interval": 1, "weekdays": [], "until": "", "count": 0}
        return rule, _skip_space(raw, match.end())
    return None, cursor


# --------------------------------------------------------------- 날짜·시각 --
def _take_datetime(raw: str, cursor: int, spans: list[Span], now: datetime):
    """맨 앞에서부터 날짜·시각 조각을 더 이상 안 읽힐 때까지 벗겨 낸다."""
    parsed_date: date | None = None
    parsed_time: time | None = None
    end_time: time | None = None
    duration: timedelta | None = None
    all_day = False

    while cursor < len(raw):
        cursor = _skip_space(raw, cursor)
        if all_day is False:
            match = _RE_ALL_DAY.match(raw, cursor)
            if match:
                all_day = True
                spans.append(Span(match.start(), match.end(), "time", match.group(0)))
                cursor = match.end()
                continue
        if parsed_date is None:
            found = _match_date(raw, cursor, now)
            if found is not None:
                parsed_date, match = found
                spans.append(Span(match.start(), match.end(), "date", match.group(0)))
                cursor = match.end()
                continue
        if parsed_time is None and not all_day:
            found = _match_time(raw, cursor)
            if found is not None:
                parsed_time, match = found
                spans.append(Span(match.start(), match.end(), "time", match.group(0)))
                cursor = match.end()
                continue
        if parsed_time is not None and end_time is None and duration is None:
            after = _skip_space(raw, cursor)
            mark = _RE_RANGE_MARK.match(raw, after)
            if mark:
                found = _match_time(raw, mark.end())
                if found is not None:
                    end_time, match = found
                    stop = _skip_trailing(raw, match.end(), "까지")
                    spans.append(Span(mark.start(), stop, "time", raw[mark.start():stop]))
                    cursor = stop
                    continue
            match = _RE_DURATION.match(raw, after)
            if match:
                duration = _duration_of(match)
                spans.append(Span(match.start(), match.end(), "time", match.group(0)))
                cursor = match.end()
                continue
        break
    return parsed_date, parsed_time, end_time, duration, all_day, cursor


def _match_date(raw: str, cursor: int, now: datetime):
    match = _RE_ABS_YMD.match(raw, cursor)
    if match:
        value = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return (value, match) if value else None
    match = _RE_ABS_MD_KO.match(raw, cursor)
    if match:
        value = _month_day(now, int(match.group(1)), int(match.group(2)))
        return (value, match) if value else None
    match = _RE_ABS_MD_SLASH.match(raw, cursor)
    if match:
        value = _month_day(now, int(match.group(1)), int(match.group(2)))
        return (value, match) if value else None
    match = _RE_REL_DAY.match(raw, cursor)
    if match:
        return now.date() + timedelta(days=int(match.group(1))), match
    match = _RE_REL_WEEK.match(raw, cursor)
    if match:
        return now.date() + timedelta(weeks=int(match.group(1))), match
    match = _RE_WEEKDAY.match(raw, cursor)
    if match:
        prefix = re.sub(r"\s+", "", match.group(1) or "") or None
        index = WEEKDAY_LETTERS.index(match.group(2))
        return _resolve_weekday(now.date(), index, WEEK_OFFSETS.get(prefix), prefix is not None), match
    match = _RE_DAY_WORD.match(raw, cursor)
    if match:
        return now.date() + timedelta(days=DAY_WORDS[match.group(1)]), match
    return None


def _match_time(raw: str, cursor: int):
    cursor = _skip_space(raw, cursor)
    match = _RE_TIME_COLON.match(raw, cursor)
    if match:
        hour = _apply_meridiem(int(match.group(2)), match.group(1))
        minute = int(match.group(3))
        if hour is None or minute > 59:
            return None
        return time(hour, minute), match
    match = _RE_TIME_HOUR.match(raw, cursor)
    if match:
        hour = _apply_meridiem(int(match.group(2)), match.group(1))
        if hour is None:
            return None
        minute = 30 if match.group(3) else int(match.group(4) or 0)
        if minute > 59:
            return None
        return time(hour, minute), match
    return None


def _apply_meridiem(hour: int, meridiem: str | None) -> int | None:
    if hour > 23:
        return None
    if meridiem in ("오전", "아침"):
        return 0 if hour == 12 else hour
    if meridiem == "새벽":
        return hour if hour < 12 else None
    if meridiem in ("오후", "점심", "저녁", "밤"):
        return hour if hour >= 12 else hour + 12
    if hour >= 13:
        return hour
    # 표시가 없는 1~6시는 업무 관례대로 오후로 본다.  7~12시는 적은 그대로.
    return hour + 12 if 1 <= hour <= 6 else hour


def _duration_of(match: re.Match) -> timedelta:
    if match.group(1):
        return timedelta(hours=int(match.group(1)), minutes=int(match.group(2) or 0))
    return timedelta(minutes=int(match.group(3)))


def _resolve_weekday(today: date, index: int, offset: int | None, explicit: bool) -> date:
    monday = today - timedelta(days=today.weekday())
    if not explicit:
        target = monday + timedelta(days=index)
        # 요일만 말했는데 이미 지났으면 다음 주로 넘긴다.
        return target if target >= today else target + timedelta(days=7)
    return monday + timedelta(days=(offset or 0) * 7 + index)


def _align_to_weekday(start: datetime, end: datetime | None, weekday: int):
    shift = (weekday - start.weekday()) % 7
    if not shift:
        return start, end
    moved = start + timedelta(days=shift)
    return moved, (end + timedelta(days=shift)) if end else None


def _month_day(now: datetime, month: int, day: int) -> date | None:
    value = _safe_date(now.year, month, day)
    if value is None:
        return None
    # 이미 지난 달·날짜를 말했으면 내년으로 본다.
    return value if value >= now.date() - timedelta(days=1) else _safe_date(now.year + 1, month, day)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


# -------------------------------------------------------------------- 제목 --
def _remaining_title(raw: str, spans: list[Span]) -> str:
    masked = list(raw)
    for span in spans:
        for index in range(span.start, min(span.end, len(masked))):
            masked[index] = "\x00"
    text = "".join(masked).replace("\x00", " ")
    text = _RE_TITLE_HEAD.sub("", text)
    text = _RE_TITLE_TAIL.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _skip_space(raw: str, cursor: int) -> int:
    while cursor < len(raw) and raw[cursor] in " \t":
        cursor += 1
    return cursor


def _skip_trailing(raw: str, cursor: int, word: str) -> int:
    cursor = _skip_space(raw, cursor)
    return cursor + len(word) if raw.startswith(word, cursor) else cursor
