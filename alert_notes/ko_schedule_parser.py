"""한 줄로 적은 일정을 읽는 한국어 규칙 파서.

``dateparser``에 한국어를 넣어 보면 "다음주 화요일 10시"는 ``None``, "내일 오후
3시"는 시각을 통째로 버린다.  한국어 일정 표현은 어휘가 좁고(오늘·내일·요일·N시·
오전/오후·매주) 어순이 안정적이라, 정규식 층을 앞에서부터 벗겨 내는 쪽이 훨씬
정확하다.  외부 의존성은 쓰지 않는다.

안전한 쪽으로 설계했다.  날짜·시간은 명확한 단위(``일``·``시``·``:``)나 완성된
구분 표기만 읽고, 일반 숫자는 건드리지 않는다.  "9월 매출 정리"처럼 달만 있고
날짜가 없는 표현은 패턴에 없으므로 제목 그대로 남는다.  분류(``#업무``)와
알림(``!30분전``)은 사람이 일부러 찍은 표시이므로 위치와 상관없이 읽는다.

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
    "다다음주": 2,
    "이번주": 0, "금주": 0,
    "다음주": 1, "담주": 1, "차주": 1, "낼주": 1,
    "저번주": -1, "지난주": -1, "전주": -1,
}
MERIDIEM = ("오전", "오후", "아침", "점심", "저녁", "밤", "새벽")
CATEGORY_KEYS = {name: key for name, key in CATEGORIES}

_SPACE = r"[ \t]*"
_MERIDIEM_GROUP = f"({'|'.join(MERIDIEM)})?"

_RE_CATEGORY = re.compile(r"#([가-힣A-Za-z0-9]+)")
_RE_REMINDER = re.compile(r"!(\d{1,3})\s*(시간|분)?\s*([전후])?")
_RE_NATURAL_REMINDER = re.compile(
    r"(?<![!\d])(?:(\d{1,5})\s*분\s*([전후])\s*알(?:람|림)|"
    r"알(?:람|림)\s*(\d{1,5})\s*분\s*([전후])|"
    r"알(?:람|림)|"
    r"(\d{1,5})\s*분\s*([전후]))(?![가-힣A-Za-z0-9])"
)
_RE_REPEAT_WEEKDAY = re.compile(rf"매주{_SPACE}([{WEEKDAY_LETTERS}])요일?")
_RE_REPEAT = re.compile(r"매(일|주|달|월|년)")
_RE_ABS_YMD = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
_RE_ABS_MD_KO = re.compile(rf"(\d{{1,2}})월{_SPACE}(\d{{1,2}})일")
_RE_ABS_MD_SLASH = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)")
_RE_ABS_MD_DOT = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(?!\d)")
_RE_REL_DAY = re.compile(rf"(\d{{1,2}})일{_SPACE}(?:뒤|후)")
_RE_KO_REL_DAY = re.compile(r"(하루|이틀|사흘|나흘)\s*(?:뒤|후)(?![가-힣A-Za-z0-9])")
_RE_REL_WEEK = re.compile(rf"(\d{{1,2}})주{_SPACE}(?:뒤|후)")
_RE_WEEK_WORD = re.compile(rf"(?<![가-힣A-Za-z0-9])(다다음{_SPACE}주|다음{_SPACE}주)(?![가-힣A-Za-z0-9])")
_RE_REL_TIME = re.compile(
    rf"(?:(\d{{1,3}}){_SPACE}시간(?:{_SPACE}(\d{{1,2}}){_SPACE}분)?|"
    rf"(\d{{1,3}}){_SPACE}분){_SPACE}(?:뒤|후)"
)
_RE_WEEKDAY = re.compile(
    rf"(이번{_SPACE}주|다다음{_SPACE}주|다음{_SPACE}주|담주|차주|낼주|금주|저번{_SPACE}주|지난{_SPACE}주|전주)?"
    rf"{_SPACE}([{WEEKDAY_LETTERS}])요일"
)
_RE_DAY_WORD = re.compile(rf"({'|'.join(sorted(DAY_WORDS, key=len, reverse=True))})")
_RE_TIME_COLON = re.compile(rf"{_MERIDIEM_GROUP}{_SPACE}(\d{{1,2}}):(\d{{2}})")
# "16시 30분"의 분과 "16시 30분간"의 길이는 같은 글자로 시작한다.  뒤에 간·동안이
# 붙으면 분이 아니라 길이이므로 여기서 넘긴다.
_RE_TIME_HOUR = re.compile(
    rf"{_MERIDIEM_GROUP}{_SPACE}(\d{{1,2}}){_SPACE}시(?!간){_SPACE}"
    rf"(?:(반)|(\d{{1,2}}){_SPACE}분(?!{_SPACE}(?:간|동안|전|후)))?"
)
_RE_RANGE_MARK = re.compile(rf"(?:~|-|–|—|부터){_SPACE}")
_RE_BARE_HOUR = re.compile(r"(\d{1,2})(?=$|[\s,.;!?~\-–—]|까지)")
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
    time_mode: str | None = None
    category: str | None = None
    reminders: tuple[int, ...] = ()
    recurrence: dict | None = None
    spans: tuple[Span, ...] = field(default=())
    issues: tuple[str, ...] = field(default=())

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
    relative_base: datetime | None = None,
    ignored_spans: tuple[tuple[int, int, str], ...] = (),
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
    relative_base = (relative_base or now).replace(second=0, microsecond=0)
    kept_span = (base_end - base) if base_end and base_end > base else timedelta(hours=1)
    spans: list[Span] = []

    ignored = tuple(ignored_spans or ())
    category = _take_category(raw, spans)
    reminders = _take_reminders(raw, spans, ignored)
    cursor = _skip_space(raw, 0)
    recurrence, cursor = _take_recurrence(raw, cursor, spans)
    parsed_date, parsed_time, end_time, duration, all_day, offset, cursor = _take_datetime(
        raw, cursor, spans, now, ignored
    )
    if parsed_date is None:
        found = _find_explicit_date(raw, now, spans, ignored)
        if found is not None:
            parsed_date, match = found
            spans.append(Span(match.start(), match.end(), "date", match.group(0)))
    issues = []
    if parsed_date is not None:
        checked_spans = list(spans)
        while (extra := _find_explicit_date(raw, now, checked_spans, ignored)) is not None:
            extra_date, match = extra
            checked_spans.append(Span(match.start(), match.end(), "date", match.group(0)))
            if extra_date != parsed_date:
                issues.append("날짜가 서로 다릅니다. 사용할 날짜 하나만 남겨 주세요.")
                spans[:] = [span for span in spans if span.kind != "date"]
                parsed_date = None
                break
    if parsed_time is None and offset is None and not all_day:
        found_time = _find_explicit_time(raw, spans, ignored)
        if found_time is not None:
            parsed_time, end_time, duration, found_spans = found_time
            spans.extend(found_spans)
        else:
            # 상대시간도 제목 뒤에 입력할 수 있다. 취소한 알림을 상대시간으로
            # 재해석하지 않도록 종류와 관계없이 제외 범위를 검사한다.
            for match in _RE_REL_TIME.finditer(raw):
                if _overlaps_spans(match.start(), match.end(), spans):
                    continue
                if any(a < match.end() and match.start() < b for a, b, _ in ignored):
                    continue
                offset = _relative_offset(match)
                if offset is not None:
                    spans.append(Span(match.start(), match.end(), "time", match.group(0)))
                    break

    start = end = None
    if parsed_date is not None or parsed_time is not None or all_day or offset is not None:
        day = parsed_date or base.date()
        if all_day:
            start = datetime.combine(day, time.min)
            end = datetime.combine(day, time(23, 59))
        elif offset is not None and parsed_time is None:
            reference = (
                datetime.combine(parsed_date, relative_base.time())
                if parsed_date is not None else relative_base
            )
            start = reference + offset
            end = start + kept_span
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
    time_mode = (
        "range" if all_day or end_time is not None or duration is not None
        else "point" if parsed_time is not None or offset is not None
        else None
    )
    return ParsedSchedule(
        title=title, start=start, end=end, all_day=all_day, category=category,
        time_mode=time_mode,
        reminders=tuple(reminders), recurrence=recurrence,
        spans=tuple(sorted(spans, key=lambda span: span.start)),
        issues=tuple(issues),
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


def _take_reminders(
    raw: str, spans: list[Span], ignored: tuple[tuple[int, int, str], ...]
) -> list[int]:
    values: list[int] = []
    # 알림은 날짜를 분리하기 전에 읽는다. ISO 날짜의 `10-02` 등을
    # 시각 범위로 오인해 상대시간을 알림으로 바꾸지 않도록 가린다.
    clock_exclusions = [
        Span(m.start(), m.end(), "context", m.group(0))
        for pattern in (_RE_ABS_YMD, _RE_ABS_MD_KO, _RE_ABS_MD_SLASH, _RE_ABS_MD_DOT, _RE_REL_TIME)
        for m in pattern.finditer(raw)
    ]
    for match in _RE_REMINDER.finditer(raw):
        if _is_ignored(match.start(), match.end(), "reminder", ignored):
            continue
        amount = int(match.group(1))
        minutes = amount * 60 if match.group(2) == "시간" else amount
        if 0 < minutes <= 60 * 24 * 7 and len(values) < 5:
            if match.group(3) == "후":
                minutes = -minutes
            values.append(minutes)
            spans.append(Span(match.start(), match.end(), "reminder", match.group(0)))
    for match in _RE_NATURAL_REMINDER.finditer(raw):
        if _overlaps_spans(match.start(), match.end(), spans):
            continue
        if _is_ignored(match.start(), match.end(), "reminder", ignored):
            continue
        if match.group(5) is not None and match.group(6) == "후":
            # `1시간 30분 후`의 뒤쪽만 알림으로 떼지 않는다.
            if any(m.start() < match.start() < m.end() for m in _RE_REL_TIME.finditer(raw)):
                continue
            # 원문 시각을 기준으로 분류한다. 시간 칩을 취소한 경우에도
            # 남은 알림이 상대시간으로 바뀌어 일정 시각을 이동시키면 안 된다.
            if _find_explicit_time(raw, spans + clock_exclusions, ()) is None:
                continue
        pairs = list(zip(match.groups()[::2], match.groups()[1::2]))
        amount, direction = next(((int(a), d) for a, d in pairs if a is not None), (0, "전"))
        if 0 <= amount <= 60 * 24 * 7 and len(values) < 5:
            values.append(-amount if direction == "후" else amount)
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
def _take_datetime(
    raw: str, cursor: int, spans: list[Span], now: datetime,
    ignored: tuple[tuple[int, int, str], ...],
):
    """맨 앞에서부터 날짜·시각 조각을 더 이상 안 읽힐 때까지 벗겨 낸다."""
    parsed_date: date | None = None
    parsed_time: time | None = None
    end_time: time | None = None
    duration: timedelta | None = None
    offset: timedelta | None = None
    all_day = False

    while cursor < len(raw):
        cursor = _skip_space(raw, cursor)
        occupied = [span.end for span in spans if span.start <= cursor < span.end]
        if occupied:
            cursor = max(occupied)
            continue
        ignored_end = _ignored_end_at(cursor, ignored)
        if ignored_end is not None:
            cursor = ignored_end
            continue
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
        if offset is None and parsed_time is None and not all_day:
            match = _RE_REL_TIME.match(raw, cursor)
            if match:
                offset = _relative_offset(match)
                if offset is not None:
                    spans.append(Span(match.start(), match.end(), "time", match.group(0)))
                    cursor = match.end()
                    continue
        if parsed_time is None and not all_day:
            found = _match_time(raw, cursor)
            if found is None:
                bare = _match_bare_hour(raw, cursor)
                if bare is not None:
                    mark = _RE_RANGE_MARK.match(raw, _skip_space(raw, bare[1].end()))
                    if mark and (_match_time(raw, mark.end()) or _match_bare_hour(raw, mark.end())):
                        found = bare
            if found is not None:
                parsed_time, match = found
                spans.append(Span(match.start(), match.end(), "time", match.group(0)))
                cursor = match.end()
                continue
        if parsed_time is not None and end_time is None and duration is None:
            after = _skip_space(raw, cursor)
            mark = _RE_RANGE_MARK.match(raw, after)
            if mark:
                found = _match_time(raw, mark.end()) or _match_bare_hour(raw, mark.end())
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
    return parsed_date, parsed_time, end_time, duration, all_day, offset, cursor


def _match_date(raw: str, cursor: int, now: datetime):
    match = _RE_ABS_YMD.match(raw, cursor)
    if match:
        value = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return (value, match) if value else None
    match = _RE_ABS_MD_KO.match(raw, cursor)
    if match:
        value = _month_day(now, int(match.group(1)), int(match.group(2)))
        return (value, match) if value else None
    for pattern in (_RE_ABS_MD_SLASH, _RE_ABS_MD_DOT):
        match = pattern.match(raw, cursor)
        if match:
            value = _month_day(now, int(match.group(1)), int(match.group(2)))
            return (value, match) if value else None
    match = _RE_REL_DAY.match(raw, cursor)
    if match:
        return now.date() + timedelta(days=int(match.group(1))), match
    match = _RE_KO_REL_DAY.match(raw, cursor)
    if match:
        days = {"하루": 1, "이틀": 2, "사흘": 3, "나흘": 4}[match.group(1)]
        return now.date() + timedelta(days=days), match
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
    match = _RE_WEEK_WORD.match(raw, cursor)
    if match:
        return now.date() + timedelta(weeks=WEEK_OFFSETS[re.sub(r"\s+", "", match.group(1))]), match
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


def _find_explicit_date(
    raw: str, now: datetime, spans: list[Span],
    ignored: tuple[tuple[int, int, str], ...],
):
    """제목 뒤에 둔 명확한 월/일 표기도 날짜로 읽는다."""
    for pattern in (_RE_ABS_YMD, _RE_ABS_MD_KO, _RE_ABS_MD_SLASH, _RE_ABS_MD_DOT, _RE_WEEKDAY,
                    _RE_DAY_WORD, _RE_KO_REL_DAY, _RE_REL_DAY, _RE_REL_WEEK, _RE_WEEK_WORD):
        for match in pattern.finditer(raw):
            if _overlaps_spans(match.start(), match.end(), spans):
                continue
            if _is_ignored(match.start(), match.end(), "date", ignored):
                continue
            if pattern in (_RE_DAY_WORD, _RE_KO_REL_DAY, _RE_REL_DAY, _RE_REL_WEEK, _RE_WEEK_WORD):
                if match.start() and raw[match.start() - 1].isalnum():
                    continue
                if match.end() < len(raw) and raw[match.end()].isalnum():
                    continue
                found = _match_date(raw, match.start(), now)
                value = found[0] if found else None
            elif pattern is _RE_WEEKDAY:
                prefix = re.sub(r"\s+", "", match.group(1) or "") or None
                value = _resolve_weekday(
                    now.date(), WEEKDAY_LETTERS.index(match.group(2)),
                    WEEK_OFFSETS.get(prefix), prefix is not None,
                )
            elif pattern is _RE_ABS_YMD:
                value = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            else:
                value = _month_day(now, int(match.group(1)), int(match.group(2)))
            if value is not None:
                return value, match
    return None


def _find_explicit_time(
    raw: str, spans: list[Span], ignored: tuple[tuple[int, int, str], ...],
):
    """문장 중간·끝의 명확한 시각 또는 시각 범위를 찾는다."""
    for cursor in range(len(raw)):
        found = _match_time(raw, cursor)
        if found is None:
            bare = _match_bare_hour(raw, cursor)
            if bare is not None:
                mark = _RE_RANGE_MARK.match(raw, _skip_space(raw, bare[1].end()))
                if mark and (_match_time(raw, mark.end()) or _match_bare_hour(raw, mark.end())):
                    found = bare
        if found is None:
            continue
        start_time, first = found
        if first.start() > 0 and raw[first.start() - 1].isdigit():
            continue
        if _overlaps_spans(first.start(), first.end(), spans):
            continue
        if _is_ignored(first.start(), first.end(), "time", ignored):
            continue
        found_spans = [Span(first.start(), first.end(), "time", first.group(0))]
        end_time = None
        duration = None
        after = _skip_space(raw, first.end())
        mark = _RE_RANGE_MARK.match(raw, after)
        if mark:
            second = _match_time(raw, mark.end()) or _match_bare_hour(raw, mark.end())
            if second is not None:
                end_time, match = second
                stop = _skip_trailing(raw, match.end(), "까지")
                if not _is_ignored(mark.start(), stop, "time", ignored):
                    found_spans.append(Span(mark.start(), stop, "time", raw[mark.start():stop]))
                else:
                    end_time = None
        if end_time is None:
            length = _RE_DURATION.match(raw, after)
            if length and not _is_ignored(length.start(), length.end(), "time", ignored):
                duration = _duration_of(length)
                found_spans.append(Span(length.start(), length.end(), "time", length.group(0)))
        return start_time, end_time, duration, found_spans
    return None


def _match_bare_hour(raw: str, cursor: int):
    match = _RE_BARE_HOUR.match(raw, _skip_space(raw, cursor))
    if match:
        hour = _apply_meridiem(int(match.group(1)), None)
        if hour is not None:
            return time(hour), match
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


def _relative_offset(match: re.Match) -> timedelta | None:
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or match.group(3) or 0)
    if match.group(2) is not None and minutes >= 60:
        return None
    return timedelta(hours=hours, minutes=minutes) if hours or minutes else None


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


def _is_ignored(
    start: int, end: int, kind: str,
    ignored: tuple[tuple[int, int, str], ...],
) -> bool:
    return any(
        ignored_kind == kind and ignored_start < end and start < ignored_end
        for ignored_start, ignored_end, ignored_kind in ignored
    )


def _ignored_end_at(
    cursor: int, ignored: tuple[tuple[int, int, str], ...]
) -> int | None:
    ends = [end for start, end, kind in ignored if start <= cursor < end]
    return max(ends) if ends else None


def _overlaps_spans(start: int, end: int, spans: list[Span]) -> bool:
    return any(span.start < end and start < span.end for span in spans)


def remap_ignored_spans(old: str, new: str, spans) -> set[tuple[int, int, str]]:
    """주변 글자 편집은 취소 위치만 이동시키고, 표현 자체의 수정만 취소를 푼다."""
    if old == new:
        return set(spans)
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < min(len(old), len(new)) - prefix
           and old[len(old) - suffix - 1] == new[len(new) - suffix - 1]):
        suffix += 1
    old_end = len(old) - suffix
    delta = len(new) - len(old)
    kept = set()
    for start, end, kind in spans:
        if end <= prefix:
            kept.add((start, end, kind))
        elif start >= old_end:
            kept.add((start + delta, end + delta, kind))
    return kept
