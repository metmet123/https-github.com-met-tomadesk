"""메모 본문 안의 `@ 내일 오후 3시` 알림.

줄 맨 앞이나 공백 뒤의 ``@``부터 줄 끝까지를 시간 구절로 읽는다.  읽는 일은
빠른 일정 창과 같은 :mod:`ko_schedule_parser`가 맡는다.  확정하면 구절은
``⏰ 10/2(금) 15:00`` 칩(링크 서식)으로 바뀌고, 칩의 주소에 알림 값이 들어간다.

본문이 저장될 때마다 :func:`sync_note_alarms`가 칩과 알림 목록을 맞춘다.
칩이 사라지면 알림도 지우고, 새 칩은 알림을 만든다.  ☑로 바꾼 줄의 알림은
쉬게 하고(``checked``), 다시 ☐로 돌리면 깨운다.  알림 하나는 ``inline_key``로
칩 하나와 이어진다.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, quote, urlencode

from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument

from . import ko_schedule_parser
from .recurrence import (
    RULE_DAILY, RULE_MONTHLY, RULE_NONE, RULE_WEEKDAYS, RULE_WEEKLY,
    RecurrenceRule, next_occurrence, repeat_summary,
)
from .schedule_recurrence import DATETIME_FMT


ALARM_SCHEME = "toma-alarm:"
UNCHECKED_PREFIX = "☐ "
CHECKED_PREFIX = "☑ "
CODE_PREFIX = "⌗ "
CHIP_MARK = "⏰ "
WEEKDAYS = "월화수목금토일"
CHIP_BACKGROUND = QColor("#fdecc8")
CHIP_FOREGROUND = QColor("#6b4400")
EXAMPLE_HINT = "예: 내일 오후 3시 · 30분 후 · 매주 월 9시 · 금 5시 !30분전"

# `@`는 줄 맨 앞이나 공백 뒤에 있을 때만 구분자다.  메일 주소의 @는 건너뛴다.
_RE_AT = re.compile(r"(?:(?<=\s)|^)@")
_RE_MONTH_DAY = re.compile(r"^([ \t]*매(?:월|달)[ \t]*)(\d{1,2})일")


@dataclass(frozen=True)
class AlarmSpec:
    """칩 하나가 뜻하는 알림."""

    at: datetime
    offsets: tuple[int, ...] = ()
    rule: RecurrenceRule = field(default_factory=RecurrenceRule)
    source: str = ""

    def dues(self) -> list[datetime]:
        """실제로 울릴 시각들.  `!30분전`처럼 적었으면 그만큼 당긴다."""
        if not self.offsets:
            return [self.at]
        return [self.at - timedelta(minutes=value) for value in self.offsets]

    @property
    def repeats(self) -> bool:
        return self.rule.rule_type != RULE_NONE

    def signature(self) -> str:
        """값이 바뀌면 알림도 새로 만든다.  같은 칩인지 가리는 지문이다."""
        return f"{self.at:%Y%m%d%H%M}-{_offsets_text(self.offsets)}-{_rule_text(self.rule)}"


@dataclass(frozen=True)
class AlarmPhrase:
    """한 줄에서 찾은 `@` 구절.  위치는 모두 줄 글자(파이썬 문자열) 기준이다."""

    at_index: int
    end: int
    source: str
    spans: tuple[ko_schedule_parser.Span, ...]
    spec: AlarmSpec | None
    issue: str = ""
    leftover: str = ""

    @property
    def valid(self) -> bool:
        return self.spec is not None and not self.issue


@dataclass(frozen=True)
class ChipEntry:
    key: str
    spec: AlarmSpec
    memo: str
    checked: bool


# ------------------------------------------------------------------ 읽기 --
def find_phrase(
    line: str, now: datetime | None = None,
    ignored: tuple[tuple[int, int, str], ...] = (),
) -> AlarmPhrase | None:
    """줄에서 마지막 `@` 구절을 읽는다.  `@` 뒤가 비어 있으면 None."""
    text = str(line or "")
    matches = list(_RE_AT.finditer(text))
    if not matches:
        return None
    at_index = matches[-1].start()
    rest = text[at_index + 1:]
    if not rest.strip():
        return None
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    offset = at_index + 1
    month_day = None
    day_match = _RE_MONTH_DAY.match(rest)
    extra_spans: list[ko_schedule_parser.Span] = []
    if day_match is not None and 1 <= int(day_match.group(2)) <= 31:
        month_day = int(day_match.group(2))
        start = day_match.start(2)
        extra_spans.append(ko_schedule_parser.Span(start, day_match.end(), "date", day_match.group(0)[start:]))
    parsed = ko_schedule_parser.parse(
        rest, now=now, base=now, ignored_spans=ignored, category_keys={},
    )
    spans = [span for span in parsed.spans if span.kind != "category"]
    if month_day is not None:
        # "매월 25일"의 25일은 파서가 날짜로 읽지 않는다.  여기서 덧붙인다.
        spans = [span for span in spans if not _overlaps(span, extra_spans[0])] + extra_spans
    spans.sort(key=lambda span: span.start)
    line_spans = tuple(
        ko_schedule_parser.Span(span.start + offset, span.end + offset, span.kind, span.text)
        for span in spans
    )
    if not spans or parsed.start is None:
        return AlarmPhrase(at_index, len(text), rest, line_spans, None, "", "")
    end = max(span.end for span in spans)
    leftover = _leftover(rest[:end], spans)
    if parsed.issues:
        return AlarmPhrase(at_index, offset + end, rest, line_spans, None, parsed.issues[0], leftover)
    start = parsed.start
    if parsed.all_day or parsed.time_mode is None:
        # 날짜만 적었으면 그날의 지금 시각에 알린다.
        start = datetime.combine(start.date(), now.time())
    rule, issue = _rule_from(parsed.recurrence, start, month_day)
    if issue:
        return AlarmPhrase(at_index, offset + end, rest, line_spans, None, issue, leftover)
    if month_day is not None and rule.rule_type == RULE_MONTHLY:
        start = _first_month_day(start, month_day, now)
    offsets = tuple(int(value) for value in parsed.reminders)
    spec = AlarmSpec(start, offsets, rule, rest[:end].strip())
    if spec.repeats:
        spec = _advance(spec, now)
    elif max(spec.dues()) <= now:
        return AlarmPhrase(
            at_index, offset + end, rest, line_spans, spec, "이미 지난 시간입니다.", leftover,
        )
    return AlarmPhrase(at_index, offset + end, rest, line_spans, spec, "", leftover)


def _rule_from(recurrence, start: datetime, month_day: int | None) -> tuple[RecurrenceRule, str]:
    if not recurrence or recurrence.get("frequency", "none") == "none":
        return RecurrenceRule(), ""
    frequency = recurrence["frequency"]
    if frequency == "daily":
        return RecurrenceRule(RULE_DAILY), ""
    if frequency == "weekly":
        weekdays = tuple(sorted({int(day) for day in recurrence.get("weekdays") or ()}))
        return RecurrenceRule(RULE_WEEKLY, weekdays or (start.weekday(),)), ""
    if frequency == "monthly":
        return RecurrenceRule(RULE_MONTHLY, month_day=month_day or start.day), ""
    return RecurrenceRule(), "매년 반복은 메모 알림에서 쓸 수 없습니다. 매일·매주·매월을 써 주세요."


def _first_month_day(start: datetime, day: int, now: datetime) -> datetime:
    candidate = start.date().replace(day=1)
    for _ in range(14):
        last = _month_last_day(candidate)
        value = datetime.combine(candidate.replace(day=min(day, last)), start.time())
        if value > now:
            return value
        candidate = (candidate.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start


def _month_last_day(value: date) -> int:
    following = (value.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (following - timedelta(days=1)).day


def _advance(spec: AlarmSpec, now: datetime) -> AlarmSpec:
    """반복 알림의 첫 회차가 이미 지났으면 다음 회차로 옮긴다."""
    at = spec.at
    if spec.rule.rule_type == RULE_WEEKLY and at.weekday() not in spec.rule.weekdays:
        at = next_occurrence(at, spec.rule) or at
    if spec.rule.rule_type == RULE_WEEKDAYS and at.weekday() >= 5:
        at = next_occurrence(at, spec.rule) or at
    for _ in range(800):
        if min(AlarmSpec(at, spec.offsets).dues()) > now:
            break
        following = next_occurrence(at, spec.rule)
        if following is None:
            break
        at = following
    return AlarmSpec(at, spec.offsets, spec.rule, spec.source)


def _overlaps(left, right) -> bool:
    return left.start < right.end and right.start < left.end


def _leftover(text: str, spans) -> str:
    kept = []
    cursor = 0
    for span in sorted(spans, key=lambda value: value.start):
        if span.start > cursor:
            kept.append(text[cursor:span.start])
        cursor = max(cursor, span.end)
    kept.append(text[cursor:])
    words = " ".join("".join(kept).split())
    return words.strip(" ,.·/~-")


# -------------------------------------------------------------- 칩 주소 --
def new_key() -> str:
    return uuid.uuid4().hex[:12]


def chip_href(key: str, spec: AlarmSpec) -> str:
    values = {"at": spec.at.strftime(DATETIME_FMT)}
    if spec.offsets:
        values["before"] = _offsets_text(spec.offsets)
    if spec.repeats:
        values["repeat"] = _rule_text(spec.rule)
    if spec.source:
        values["src"] = spec.source
    return f"{ALARM_SCHEME}{key}?{urlencode(values, quote_via=quote)}"


def parse_chip_href(href: str) -> tuple[str, AlarmSpec] | None:
    value = str(href or "")
    if not value.startswith(ALARM_SCHEME):
        return None
    body = value[len(ALARM_SCHEME):]
    key, _sep, query = body.partition("?")
    if not re.fullmatch(r"[0-9a-f]{6,32}", key):
        return None
    params = {name: items[-1] for name, items in parse_qs(query, keep_blank_values=True).items()}
    try:
        at = datetime.strptime(params.get("at", ""), DATETIME_FMT)
    except ValueError:
        return None
    offsets = tuple(
        int(item) for item in params.get("before", "").split(",")
        if re.fullmatch(r"-?\d{1,6}", item.strip())
    )
    rule = _rule_from_text(params.get("repeat", ""))
    return key, AlarmSpec(at, offsets[:5], rule, params.get("src", ""))


def _offsets_text(offsets) -> str:
    return ",".join(str(int(value)) for value in offsets)


def _rule_text(rule: RecurrenceRule) -> str:
    if rule.rule_type == RULE_WEEKLY:
        return "weekly:" + ",".join(str(day) for day in rule.weekdays)
    if rule.rule_type == RULE_MONTHLY:
        return f"monthly:{rule.month_day or 1}"
    return rule.rule_type


def _rule_from_text(text: str) -> RecurrenceRule:
    kind, _sep, value = str(text or "").partition(":")
    if kind == RULE_DAILY:
        return RecurrenceRule(RULE_DAILY)
    if kind == RULE_WEEKDAYS:
        return RecurrenceRule(RULE_WEEKDAYS)
    if kind == RULE_WEEKLY:
        days = tuple(sorted({int(day) for day in value.split(",") if day.isdigit() and int(day) <= 6}))
        return RecurrenceRule(RULE_WEEKLY, days) if days else RecurrenceRule()
    if kind == RULE_MONTHLY and value.isdigit() and 1 <= int(value) <= 31:
        return RecurrenceRule(RULE_MONTHLY, month_day=int(value))
    return RecurrenceRule()


# ------------------------------------------------------------------ 글자 --
def chip_label(spec: AlarmSpec, now: datetime | None = None) -> str:
    now = now or datetime.now()
    clock = f"{spec.at:%H:%M}"
    rule = spec.rule
    if rule.rule_type == RULE_DAILY:
        when = f"매일 {clock}"
    elif rule.rule_type == RULE_WEEKDAYS:
        when = f"평일 {clock}"
    elif rule.rule_type == RULE_WEEKLY:
        when = f"매주 {'·'.join(WEEKDAYS[day] for day in rule.weekdays)} {clock}"
    elif rule.rule_type == RULE_MONTHLY:
        when = f"매월 {rule.month_day or spec.at.day}일 {clock}"
    else:
        day = (
            f"{spec.at.month}/{spec.at.day}" if spec.at.year == now.year
            else f"{spec.at.year}/{spec.at.month}/{spec.at.day}"
        )
        when = f"{day}({WEEKDAYS[spec.at.weekday()]}) {clock}"
    if spec.offsets:
        when += " · " + ", ".join(offset_label(value) for value in spec.offsets)
    return CHIP_MARK + when


def offset_label(minutes: int) -> str:
    value = abs(int(minutes))
    direction = "전" if int(minutes) >= 0 else "후"
    if value == 0:
        return "정각"
    if value % 1440 == 0:
        amount = f"{value // 1440}일"
    elif value % 60 == 0:
        amount = f"{value // 60}시간"
    else:
        amount = f"{value}분"
    return f"{amount} {direction}"


def preview_text(phrase: AlarmPhrase, now: datetime | None = None) -> str:
    """구절을 쓰는 동안 커서 아래에 띄울 한 줄."""
    if phrase.spec is None and not phrase.issue:
        return f"@ 뒤에 언제 알릴지 적어 주세요 · {EXAMPLE_HINT}"
    if phrase.issue:
        return f"{phrase.issue} · Esc 그냥 글자로"
    spec = phrase.spec
    label = chip_label(spec, now)[len(CHIP_MARK):]
    dues = spec.dues()
    if spec.offsets:
        first = min(dues)
        label += f" → 첫 알림 {first.month}/{first.day} {first:%H:%M}"
    return f"⏰ {label} 알림 · Enter 확정 · 색 칸 더블클릭 = 인식 취소 · Esc 그냥 글자로"


def chip_tooltip(spec: AlarmSpec) -> str:
    lines = [chip_label(spec)[len(CHIP_MARK):] + " 알림"]
    if spec.source:
        lines.append(f"적은 말: {spec.source}")
    lines.append("클릭하면 고치기·지우기·일정으로 옮기기")
    return "\n".join(lines)


# ----------------------------------------------------------- 문서 다루기 --
def utf16_len(text: str) -> int:
    return len(str(text).encode("utf-16-le")) // 2


def chip_format(key: str, spec: AlarmSpec) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setAnchor(True)
    fmt.setAnchorHref(chip_href(key, spec))
    fmt.setBackground(CHIP_BACKGROUND)
    fmt.setForeground(CHIP_FOREGROUND)
    fmt.setFontUnderline(False)
    fmt.setToolTip(chip_tooltip(spec))
    return fmt


def phrase_allowed(block) -> bool:
    """표 안·코드 줄의 @는 알림으로 읽지 않는다."""
    if not block.isValid():
        return False
    if block.text().startswith(CODE_PREFIX):
        return False
    return QTextCursor(block).currentTable() is None


def insert_chip(cursor: QTextCursor, spec: AlarmSpec, key: str | None = None) -> str:
    """커서 자리에 칩을 넣고 뒤에 맨 서식 공백 하나를 둔다."""
    key = key or new_key()
    cursor.insertText(chip_label(spec), chip_format(key, spec))
    plain = QTextCharFormat()
    if cursor.document().characterAt(cursor.position()) == " ":
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
    else:
        cursor.insertText(" ", plain)
    cursor.setCharFormat(plain)
    return key


def apply_phrase(block, phrase: AlarmPhrase, key: str | None = None) -> tuple[int, str] | None:
    """줄의 구절을 칩으로 바꾼다.  바꾼 뒤 커서를 둘 위치와 키를 돌려준다."""
    if not phrase.valid or not block.isValid():
        return None
    text = block.text()
    start = block.position() + utf16_len(text[:phrase.at_index])
    end = block.position() + utf16_len(text[:phrase.end])
    cursor = QTextCursor(block.document())
    cursor.beginEditBlock()
    try:
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        key = insert_chip(cursor, phrase.spec, key)
        if phrase.leftover:
            cursor.insertText(phrase.leftover + " ", QTextCharFormat())
        position = cursor.position()
    finally:
        cursor.endEditBlock()
    return position, key


def utf16_offset_to_index(text: str, offset: int) -> int:
    count = 0
    for index, char in enumerate(text):
        if count >= offset:
            return index
        count += 2 if ord(char) > 0xFFFF else 1
    return len(text)


def chip_runs(block) -> list[tuple[int, int, str]]:
    """줄 안의 칩 구간(문서 위치)과 주소."""
    runs: list[list] = []
    iterator = block.begin()
    while not iterator.atEnd():
        fragment = iterator.fragment()
        iterator += 1
        if not fragment.isValid():
            continue
        href = str(fragment.charFormat().anchorHref() or "")
        if not href.startswith(ALARM_SCHEME):
            continue
        start = fragment.position()
        end = start + fragment.length()
        if runs and runs[-1][1] == start and runs[-1][2] == href:
            runs[-1][1] = end
        else:
            runs.append([start, end, href])
    return [(start, end, href) for start, end, href in runs]


def chip_at(document, position: int) -> tuple[int, int, str, AlarmSpec] | None:
    block = document.findBlock(max(0, int(position)))
    for start, end, href in chip_runs(block):
        if start <= position <= end:
            parsed = parse_chip_href(href)
            if parsed is not None:
                return start, end, parsed[0], parsed[1]
    return None


def collect_chips(document) -> list[ChipEntry]:
    entries: list[ChipEntry] = []
    seen: set[str] = set()
    block = document.begin()
    while block.isValid():
        runs = chip_runs(block)
        if runs:
            text = block.text()
            checked = text.startswith(CHECKED_PREFIX)
            memo = _memo_text(block, runs)
            for _start, _end, href in runs:
                parsed = parse_chip_href(href)
                if parsed is None or parsed[0] in seen:
                    continue
                seen.add(parsed[0])
                entries.append(ChipEntry(parsed[0], parsed[1], memo, checked))
        block = block.next()
    return entries


def _memo_text(block, runs) -> str:
    text = block.text()
    base = block.position()
    pieces = []
    cursor = 0
    for start, end, _href in runs:
        left = utf16_offset_to_index(text, start - base)
        right = utf16_offset_to_index(text, end - base)
        pieces.append(text[cursor:left])
        cursor = right
    pieces.append(text[cursor:])
    joined = "".join(pieces)
    for prefix in (UNCHECKED_PREFIX, CHECKED_PREFIX):
        if joined.startswith(prefix):
            joined = joined[len(prefix):]
    joined = joined.replace("￼", " ")
    return " ".join(joined.split())[:200]


def collect_chips_from_content(content: str) -> list[ChipEntry]:
    value = str(content or "")
    if ALARM_SCHEME not in value:
        return []
    document = QTextDocument()
    document.setHtml(value)
    return collect_chips(document)


def plain_text_with_chips(title: str, content: str, now: datetime | None = None) -> tuple[str, str, int]:
    """빠른 메모 창용.  제목·내용의 @ 구절을 칩으로 바꾼 (제목, 본문 HTML, 칩 수).

    칩이 하나도 없으면 본문은 받은 글자 그대로 돌려준다.
    """
    now = now or datetime.now()
    document = QTextDocument()
    document.setPlainText(str(content or ""))
    count = 0
    block = document.begin()
    while block.isValid():
        phrase = find_phrase(block.text(), now)
        if phrase is not None and phrase.valid and apply_phrase(block, phrase) is not None:
            count += 1
        block = block.next()
    resolved_title = str(title or "")
    title_phrase = find_phrase(resolved_title, now)
    if title_phrase is not None and title_phrase.valid:
        head = resolved_title[:title_phrase.at_index].rstrip()
        tail = resolved_title[title_phrase.end:].strip()
        resolved_title = " ".join(part for part in (head, title_phrase.leftover, tail) if part)
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        if document.toPlainText():
            cursor.insertBlock()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
        insert_chip(cursor, title_phrase.spec)
        count += 1
    if not count:
        return resolved_title, str(content or ""), 0
    return resolved_title, document.toHtml(), count


# ------------------------------------------------------------- 저장 맞추기 --
def sync_note_alarms(store, note_id: int, content: str, now: datetime | None = None) -> bool:
    """본문의 칩과 알림 목록을 맞춘다.  무엇이든 바꿨으면 True."""
    value = str(content or "")
    conn = store.conn
    existing = list(conn.execute(
        "SELECT id,status,inline_key,series_id,due_at,scheduled_at,memo FROM reminders "
        "WHERE note_id=? AND inline_key<>''", (int(note_id),),
    ))
    if ALARM_SCHEME not in value and not existing:
        return False
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    note = conn.execute("SELECT title FROM notes WHERE id=?", (int(note_id),)).fetchone()
    fallback = str(note["title"]) if note is not None else ""
    desired: dict[str, tuple[datetime, RecurrenceRule, str, bool]] = {}
    for entry in collect_chips_from_content(value):
        memo = entry.memo or fallback
        for index, due in enumerate(entry.spec.dues()):
            desired[f"{entry.key}:{index}:{entry.spec.signature()}"] = (
                due, entry.spec.rule, memo, entry.checked,
            )
    rows_by_key: dict[str, list] = {}
    for row in existing:
        rows_by_key.setdefault(str(row["inline_key"]), []).append(row)
    changed = False
    removed: list[int] = []
    touched: list[int] = []
    with conn:
        for key, rows in rows_by_key.items():
            if key in desired:
                continue
            for row in rows:
                if row["status"] in ("pending", "checked"):
                    conn.execute("DELETE FROM reminders WHERE id=?", (int(row["id"]),))
                    _retire_series(store, row)
                    removed.append(int(row["id"]))
                    changed = True
        for key, (due, rule, memo, checked) in desired.items():
            rows = rows_by_key.get(key, [])
            pending = [row for row in rows if row["status"] == "pending"]
            parked = [row for row in rows if row["status"] == "checked"]
            if checked:
                for row in pending:
                    conn.execute("UPDATE reminders SET status='checked' WHERE id=?", (int(row["id"]),))
                    removed.append(int(row["id"]))
                    changed = True
                continue
            if parked and not pending:
                for row in parked:
                    revived = _revive_due(row, rule, now)
                    if revived is None:
                        continue
                    conn.execute(
                        "UPDATE reminders SET status='pending',due_at=?,scheduled_at=? WHERE id=?",
                        (revived, revived, int(row["id"])),
                    )
                    touched.append(int(row["id"]))
                    changed = True
                continue
            if pending:
                for row in pending:
                    if str(row["memo"]) != memo:
                        conn.execute("UPDATE reminders SET memo=? WHERE id=?", (memo, int(row["id"])))
                        if row["series_id"] is not None:
                            conn.execute(
                                "UPDATE reminder_series SET memo=? WHERE id=?", (memo, int(row["series_id"])),
                            )
                        changed = True
                continue
            if rows:
                # 이미 울렸거나 사용자가 알림 목록에서 지운 알림은 되살리지 않는다.
                continue
            if rule.rule_type == RULE_NONE and due <= now:
                continue
            touched.append(_create(store, int(note_id), key, due, rule, memo, now))
            changed = True
    known = getattr(store, "inline_alarm_note_ids", None)
    if known is not None:
        notes = known()
        if desired or conn.execute(
            "SELECT 1 FROM reminders WHERE note_id=? AND inline_key<>'' LIMIT 1", (int(note_id),),
        ).fetchone():
            notes.add(int(note_id))
        else:
            notes.discard(int(note_id))
    for reminder_id in removed:
        store._remove_synced_reminder(reminder_id)
    for reminder_id in touched:
        store._sync_reminder(reminder_id)
    return changed


def _retire_series(store, row) -> None:
    if row["series_id"] is None:
        return
    store.conn.execute(
        "UPDATE reminder_series SET active=0,updated_at=? WHERE id=?",
        (store._now_key(), int(row["series_id"])),
    )


def _revive_due(row, rule: RecurrenceRule, now: datetime) -> str | None:
    try:
        due = datetime.strptime(str(row["scheduled_at"] or row["due_at"]), DATETIME_FMT)
    except ValueError:
        return None
    if due > now:
        return due.strftime(DATETIME_FMT)
    if row["series_id"] is None or rule.rule_type == RULE_NONE:
        return None
    for _ in range(800):
        following = next_occurrence(due, rule)
        if following is None:
            return None
        due = following
        if due > now:
            return due.strftime(DATETIME_FMT)
    return None


def _create(store, note_id: int, key: str, due: datetime, rule: RecurrenceRule, memo: str, now: datetime) -> int:
    stamp = store._now_key()
    if rule.rule_type != RULE_NONE:
        for _ in range(800):
            if due > now:
                break
            following = next_occurrence(due, rule)
            if following is None:
                break
            due = following
        cursor = store.conn.execute(
            "INSERT INTO reminder_series(note_id,memo,rule_type,weekdays,month_day,end_type,end_date,"
            "max_occurrences,generated_count,active,summary,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,1,1,?,?,?)",
            (note_id, memo, rule.rule_type, json.dumps(list(rule.weekdays)), rule.month_day,
             rule.end_type, rule.end_date, rule.max_occurrences, repeat_summary(rule), stamp, stamp),
        )
        series_id = int(cursor.lastrowid)
    else:
        series_id = None
    due_text = due.strftime(DATETIME_FMT)
    cursor = store.conn.execute(
        "INSERT INTO reminders(note_id,due_at,memo,status,created_at,series_id,occurrence_kind,"
        "scheduled_at,inline_key) VALUES(?,?,?,'pending',?,?,'regular',?,?)",
        (note_id, due_text, memo, stamp, series_id, due_text, key),
    )
    return int(cursor.lastrowid)
