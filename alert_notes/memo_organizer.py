"""Offline, conservative memo extraction. Original text is always preserved."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import re
import unicodedata

KINDS = {"task": "할 일", "event": "일정", "idea": "아이디어", "info": "정보", "review": "확인 필요"}
DATE_RE = re.compile(
    r"(?<![\d가-힣])(?:\d{4}년\s*\d{1,2}월\s*\d{1,2}일|"
    r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}|\d{1,2}월\s*\d{1,2}일|"
    r"(?:다다음|다음|이번|지난)\s*(?:달|개월)\s*\d{1,2}일|"
    r"(?:다다음\s*주|다음\s*주|이번\s*주|지난\s*주)\s*[월화수목금토일](?:요일)?|"
    r"(?:\d+일|하루|이틀|사흘|나흘)\s*(?:뒤|후|전)|[월화수목금토일]요일|그저께|어제|오늘|내일|모레|글피)(?!\d)"
)
TIME_RE = re.compile(r"(?<!\d)(?:(오전|오후)\s*)?(\d{1,2})(?::(\d{2})|시(?:\s*(\d{1,2})분|\s*(반))?)(?!\d)")
ACTION_RE = re.compile(r"회신|제출|초안|알아보기|주문(?!\s*번호)|구매|갱신|해야|보내기|전화|확인|방문|할\s*일\s*[:：]|TODO\s*[:：]", re.I)
STATE_RE = re.compile(r"취소|완료|보류|불필요|미정|고민|안\s*해도|하지\s*(?:말|않)|\[[xX✓]\]|✅")
VAGUE_RE = re.compile(r"\d{1,2}월\s*(?:말|초|중순|하순|상순)|(?:이달|이번달|다음달)\s*말|월말|쯤|언젠가|조만간|[가-힣]+면|매\s*(?:주|달|월|일|년)|격주")

@dataclass
class Candidate:
    raw: str
    title: str
    kind: str = "info"
    day: str = ""
    clock: str = ""
    end_clock: str = ""
    category: str = "미분류"
    reason: str = ""
    def to_dict(self):
        return asdict(self)

def normalized_title(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"^\s*(?:[-*•]\s+|\d+[.)]\s+|\[\s*\]\s*)", "", text)
    return " ".join(text.split())

def _day(token: str, base: date) -> date:
    token = re.sub(r"\s", "", token)
    offsets = {"그저께": -2, "어제": -1, "오늘": 0, "내일": 1, "모레": 2, "글피": 3}
    if token in offsets:
        return base + timedelta(days=offsets[token])
    if re.fullmatch(r"\d{4}년\d{1,2}월\d{1,2}일|\d{4}[-./]\d{1,2}[-./]\d{1,2}", token):
        return date(*map(int, re.findall(r"\d+", token)))
    relative = re.fullmatch(r"(다다음|다음|이번|지난)(?:달|개월)(\d{1,2})일", token)
    if relative:
        month = base.year * 12 + base.month - 1 + {"지난": -1, "이번": 0, "다음": 1, "다다음": 2}[relative[1]]
        return date(month // 12, month % 12 + 1, int(relative[2]))
    relative = re.fullmatch(r"(\d+일|하루|이틀|사흘|나흘)(뒤|후|전)", token)
    if relative:
        count = int(relative[1][:-1]) if relative[1][0].isdigit() else {"하루": 1,"이틀": 2,"사흘": 3,"나흘": 4}[relative[1]]
        return base + timedelta(days=count * (-1 if relative[2] == "전" else 1))
    if token[0].isdigit():
        month, day = map(int, re.findall(r"\d+", token))
        return date(base.year, month, day)
    prefix = next((p for p in ("다다음주", "다음주", "이번주", "지난주") if token.startswith(p)), "")
    weekday = "월화수목금토일".index(token[len(prefix)])
    result = base - timedelta(days=base.weekday()) + timedelta(days=weekday + {"":0,"이번주":0,"다음주":7,"다다음주":14,"지난주":-7}[prefix])
    return result + timedelta(days=7) if not prefix and result < base else result

def _clock(match) -> str:
    meridiem, hour, colon_minute, minute, half = match.groups()
    hour = int(hour)
    minute = int(colon_minute or minute or (30 if half else 0))
    if minute > 59 or hour > 23 or (meridiem and not 1 <= hour <= 12):
        raise ValueError("시간 범위를 확인해 주세요.")
    if not meridiem and 1 <= hour <= 12 and colon_minute is None:
        raise ValueError("오전·오후를 확인해 주세요.")
    if meridiem:
        hour = hour % 12 + (12 if meridiem == "오후" else 0)
    return f"{hour:02d}:{minute:02d}"

def analyze(text: str, base: date | None = None) -> list[Candidate]:
    base = base or date.today()
    lines = [line for line in text.splitlines() if line.strip()]
    if len(text) > 20000 or len(lines) > 200:
        raise ValueError("한 번에 20,000자·200줄까지 정리할 수 있습니다.")
    results = []
    for raw in lines:
        title = re.sub(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)", "", raw).strip()
        item = Candidate(raw=raw, title=title)
        tag = re.search(r"#([가-힣A-Za-z0-9_]+)", title)
        if tag: item.category = tag[1]
        issues = []
        mixed = bool(re.search(r"하고|그리고|[;；]|\s및\s", title)) or any(
            ACTION_RE.search(part) and not re.fullmatch(r"\s*주문\s*(?:번호\s*)?\d+\s*", part)
            for part in title.split(',')[1:])
        idea = bool(re.match(r"(?:아이디어\s*[:：-]|💡)", title) or re.search(r"하면 좋을|어떨까", title))
        info = bool(re.match(r"정보\s*[:：]", title))
        if (idea or info) and not mixed:
            item.kind = "idea" if idea else "info"
            results.append(item)
            continue
        if mixed: issues.append("한 줄에 여러 내용이 있습니다. 원문을 나누어 수집하거나 각 항목을 확인해 주세요.")
        if STATE_RE.search(title): issues.append("취소·완료·보류 또는 부정 표현이 있습니다. 새 할 일인지 확인해 주세요.")
        if VAGUE_RE.search(title): issues.append("조건·대략적인 날짜·반복 여부를 확인해 주세요.")
        dates = list(DATE_RE.finditer(title))
        # Special time words are converted only in the analysis copy.
        time_text = re.sub(r"정오", "12:00", title)
        time_text = re.sub(r"자정", "00:00", time_text)
        times = list(TIME_RE.finditer(time_text))
        if ACTION_RE.search(title): item.kind = "task"
        elif re.search(r"예약|회의|미팅|약속|워크숍", title) and dates: item.kind = "event"
        parsed = None
        try:
            explicit = [m for m in dates if not re.fullmatch(r"[월화수목금토일]요일", m.group())]
            main = explicit if explicit else dates
            values = [_day(m.group(), base) for m in main]
            if len(set(values)) > 1:
                issues.append("여러 날짜가 있습니다. 항목을 나누거나 날짜를 지정해 주세요.")
            elif values:
                parsed = values[0]; item.day = parsed.isoformat()
                if parsed < base: issues.append("기준일보다 이전입니다. 연도·날짜를 확인해 주세요.")
                weekdays = [m.group()[0] for m in dates if m not in main]
                weekdays += re.findall(r"\(([월화수목금토일])(?:요일)?\)", title)
                if any("월화수목금토일".index(w) != parsed.weekday() for w in weekdays):
                    issues.append("날짜와 요일이 일치하지 않습니다.")
        except (ValueError, OverflowError): issues.append("유효하지 않은 날짜입니다.")
        leftover = DATE_RE.sub("", title)
        if re.search(r"\d{2,4}년|\d{1,2}월|\d{1,2}일|[-./]\d{2,4}|(?:이번|다음|지난|다다음)\s*(?:주|달)|월말|이달|주말", leftover):
            issues.append("해석하지 못한 날짜 표현이 있습니다. 정확한 날짜를 확인해 주세요.")
        if times:
            try:
                if len(times) > 2: raise ValueError("여러 시간이 있습니다. 항목을 나누어 주세요.")
                item.clock = _clock(times[0])
                if len(times) == 2: item.end_clock = _clock(times[1])
                if item.end_clock and item.end_clock <= item.clock:
                    issues.append("종료 시각은 시작보다 늦어야 합니다. 다음 날 일정은 나누어 주세요.")
            except ValueError as exc: issues.append(str(exc))
            if not item.day: issues.append("시간에 해당하는 날짜를 지정해 주세요.")
        if re.search(r"오전|오후|\d+\s*시|\d+:\d+|정오|자정|아침|저녁|밤", TIME_RE.sub("", time_text)):
            issues.append("해석하지 못한 시각 표현이 있습니다. 시각을 확인해 주세요.")
        if item.kind == "event" and (not item.clock or not item.end_clock): issues.append("일정의 시작·종료 시각을 확인해 주세요.")
        if item.kind == "info" and (dates or times): issues.append("일정인지 정보인지 확인해 주세요.")
        if re.search(r"떨어짐|부족함|고장", title): issues.append("상태 메모입니다. 필요한 행동을 직접 정해 주세요.")
        item.reason = " ".join(dict.fromkeys(issues))
        if issues: item.kind = "review"
        results.append(item)
    return results


def validate(item: dict) -> None:
    if item.get("kind") not in KINDS or not str(item.get("title", "")).strip():
        raise ValueError("내용과 종류를 확인해 주세요.")
    day, clock, end = item.get("day", ""), item.get("clock", ""), item.get("end_clock", "")
    if day:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("날짜는 YYYY-MM-DD 형식으로 입력해 주세요.")
        date.fromisoformat(day)
    for value in (clock, end):
        if value:
            if not re.fullmatch(r"\d{2}:\d{2}", value):
                raise ValueError("시간은 HH:MM 형식으로 입력해 주세요.")
            datetime.strptime(value, "%H:%M")
    if (clock or end) and not day:
        raise ValueError("시각을 지정하려면 날짜가 필요합니다.")
    if end and (not clock or end <= clock):
        raise ValueError("종료 시각은 시작 시각보다 늦어야 합니다. 다음 날 일정은 나누어 등록해 주세요.")
    if item["kind"] == "event" and not (day and clock and end):
        raise ValueError("일정에는 날짜와 시작·종료 시각이 필요합니다.")
    if item["kind"] in ("idea", "info") and (day or clock or end):
        raise ValueError("아이디어·정보의 날짜는 원문에 보관합니다. 날짜·시각 칸을 비워 주세요.")


def dday(day: str, today: date | None = None, count_today_as_one: bool = False) -> str:
    if not day:
        return ""
    try:
        days = (date.fromisoformat(day) - (today or date.today())).days
    except ValueError:
        return "날짜 확인"
    if count_today_as_one and days >= 0:
        return f"D-{days + 1}"
    return "D-DAY" if days == 0 else (f"D-{days}" if days > 0 else f"D+{abs(days)}")
