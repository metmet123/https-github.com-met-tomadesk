"""Small capture ledger stored in settings, included in the existing full-app backup.

Applied dated items reference schedule_items; completion/time edits remain authoritative there.
The ledger and schedule inserts are committed in one transaction, without a schema migration.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from html import escape
import json
from uuid import uuid4

from .categories import CATEGORIES, category_name
from .memo_organizer import KINDS, analyze, dday, validate, normalized_title
from .sqlite_store import DATETIME_FMT

STATE_KEY = "memo_organizer_state_v1"
DRAFT_KEY = "memo_organizer_input_draft_v1"

class DuplicateMemoError(ValueError):
    pass


class OrganizerStore:
    def __init__(self, store):
        self.store = store

    def load(self):
        try:
            state = json.loads(self.store.setting(STATE_KEY, '{"version":1,"captures":[]}'))
            if state.get("version") != 1 or not isinstance(state["captures"], list):
                raise ValueError()
            for capture in state["captures"]:
                if not all(key in capture for key in ("id", "raw", "base", "items")):
                    raise ValueError()
                for item in capture["items"]:
                    if not isinstance(item, dict) or item.get("kind") not in KINDS:
                        raise ValueError()
                    if not all(key in item for key in ("id", "raw", "title", "kind", "day", "clock", "end_clock", "category", "reason")):
                        raise ValueError()
                    if not all(isinstance(item[key], str) for key in ("id", "raw", "title", "day", "clock", "end_clock", "category", "reason")):
                        raise ValueError()
            return state
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError("수집함 데이터를 읽을 수 없습니다. 원본을 보존했으니 전체 백업을 확인해 주세요.") from exc

    def _write(self, state):
        self.store.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (STATE_KEY, json.dumps(state, ensure_ascii=False)),
        )

    def capture(self, raw: str, base: date | None = None):
        base = base or date.today()
        candidates = analyze(raw, base)
        if not candidates:
            raise ValueError("정리할 메모를 입력해 주세요.")
        state = self.load()
        # Repeated clicks/reopening the same capture do not create duplicate schedules.
        for capture in state["captures"]:
            if capture["raw"] == raw and capture["base"] == base.isoformat() and capture.get('parser_version') == 2:
                return capture["id"]
        capture = {"id": uuid4().hex, "raw": raw, "base": base.isoformat(), "items": [], "parser_version": 2}
        for candidate in candidates:
            item = candidate.to_dict()
            item.update(id=uuid4().hex, applied=False, completed=False, schedule_id=None, notify=False)
            capture["items"].append(item)
        state["captures"].append(capture)
        with self.store.conn:
            self._write(state)
        return capture["id"]

    def get_capture(self, capture_id):
        return next(c for c in self.load()["captures"] if c["id"] == capture_id)

    def save_review(self, capture_id, edited):
        state = self.load()
        capture = next(c for c in state["captures"] if c["id"] == capture_id)
        by_id = {item["id"]: item for item in capture["items"]}
        for values in edited:
            item = by_id[values["id"]]
            if not item.get("schedule_id"):
                for key in ("title", "kind", "day", "clock", "end_clock", "category", "notify"):
                    item[key] = values[key]
                # Edited local items are reviewed again before appearing as confirmed.
                item["applied"] = False
        with self.store.conn:
            self._write(state)

    @staticmethod
    def _duplicate_key(item):
        return (normalized_title(item['title']), item['kind'], item['day'],
                item['clock'], item['end_clock'], item['category'])

    def duplicate_titles(self, edited):
        existing = {self._duplicate_key(i): i['id'] for i in self.rows() if i['applied']}
        duplicates = []
        for item in edited:
            if item.get('schedule_id') or item['kind'] == 'review':
                continue
            key = self._duplicate_key(item)
            if key in existing and existing[key] != item['id']:
                duplicates.append(item['title'])
            existing[key] = item['id']
        return list(dict.fromkeys(duplicates))

    def apply(self, capture_id: str, edited: list[dict], *, allow_duplicates=False):
        state = self.load()
        capture = next(c for c in state["captures"] if c["id"] == capture_id)
        by_id = {item["id"]: item for item in capture["items"]}
        selected = []
        seen = set()
        for values in edited:
            identifier = values["id"]
            if identifier not in by_id or identifier in seen:
                raise ValueError("수집함 항목이 변경되었습니다. 다시 열어 주세요.")
            seen.add(identifier)
            old = by_id[identifier]
            if old.get("schedule_id"):
                continue  # Native calendar is authoritative after registration.
            item = deepcopy(old)
            for key in ("title", "kind", "day", "clock", "end_clock", "category", "notify"):
                item[key] = values.get(key, item.get(key))
            validate(item)
            if item["notify"] and (item["kind"] not in ("task", "event") or not item["day"] or not item["clock"]):
                raise ValueError("알림은 날짜·시각이 정해진 일정이나 할 일에만 설정할 수 있습니다.")
            selected.append(item)
        if not allow_duplicates and self.duplicate_titles(selected):
            raise DuplicateMemoError("같은 내용·날짜·시각·분류의 항목이 이미 있습니다. 중복 여부를 확인해 주세요.")
        with self.store.conn:
            for item in selected:
                if item["kind"] in ("task", "event") and item["day"]:
                    day = date.fromisoformat(item["day"])
                    start = datetime.combine(day, time.fromisoformat(item["clock"]) if item["clock"] else time.min)
                    # Date-only tasks are all-day; timed tasks are deadline markers, not durations.
                    end = (datetime.combine(day, time.fromisoformat(item["end_clock"])) if item["end_clock"]
                           else start + timedelta(minutes=1) if item["clock"] else datetime.combine(day, time(23, 59)))
                    details = f"메모 수집함 원문\n{item['raw']}\n분류: {item['category']}\n기준일: {capture['base']}"
                    item["schedule_id"] = self.store.schedules.save_item({
                        "title": item["title"], "details": details, "item_type": item["kind"],
                        "start_at": start.strftime(DATETIME_FMT), "end_at": end.strftime(DATETIME_FMT),
                        "all_day": not bool(item["clock"]), "category": dict(CATEGORIES).get(item["category"], "lavender"),
                        "count_as_dday": item["kind"] == "task", "reminders": [0] if item["notify"] else [],
                    }, manage_transaction=False)
                item["applied"] = True
                by_id[item["id"]].update(item)
            self._write(state)
        return len(selected)

    def rows(self):
        rows = []
        for capture in self.load()["captures"]:
            for source in capture["items"]:
                item = dict(source, capture_id=capture["id"], base=capture["base"])
                if item.get("schedule_id"):
                    schedule = self.store.schedules.item(item["schedule_id"])
                    if schedule is None:
                        continue  # Trashed/deleted schedules must not reappear or be recreated.
                    item["title"] = schedule["title"]
                    item["kind"] = schedule["item_type"]
                    item["completed"] = schedule["status"] == "completed"
                    dt = datetime.strptime(schedule["start_at"], DATETIME_FMT)
                    item["day"] = dt.date().isoformat()
                    item["clock"] = "" if schedule["all_day"] else dt.strftime("%H:%M")
                    if item['kind'] == 'event':
                        item['end_clock'] = datetime.strptime(schedule['end_at'], DATETIME_FMT).strftime('%H:%M')
                    native_category = category_name(schedule["category"])
                    if native_category != "기타" or item["category"] in dict(CATEGORIES):
                        item["category"] = native_category
                rows.append(item)
        return sorted(rows, key=lambda r: (r["completed"], r["day"] or "9999", r["clock"], r["title"]))

    def complete(self, identifier: str, completed: bool):
        state = self.load()
        item = next(i for c in state["captures"] for i in c["items"] if i["id"] == identifier)
        if not item["applied"] or item["kind"] not in ("task", "event"):
            raise ValueError("반영한 일정·할 일만 완료 처리할 수 있습니다.")
        if item.get("schedule_id"):
            self.store.schedules.set_completed(item["schedule_id"], completed)
        else:
            item["completed"] = completed
            with self.store.conn:
                self._write(state)

    def dday(self, day, today=None):
        return dday(day, today, self.store.setting("deadline_count_today_as_one", "false") == "true")

    def summary_html(self, today=None):
        today = today or date.today()
        rows = [r for r in self.rows() if not r["completed"]]
        sections = {}
        urgent = []
        for row in rows:
            section = ("확인 필요" if not row["applied"] or row["kind"] == "review" else
                       "일정·마감" if row["day"] else KINDS[row["kind"]])
            text = escape(row["title"])
            if row["day"]:
                label = f"{row['day']} {row['clock']} · {self.dday(row['day'], today)}"
                text += " — " + escape(label)
                days = None
                try:
                    days = (date.fromisoformat(row["day"]) - today).days
                except ValueError:
                    pass
                if section == "일정·마감" and days is not None and days <= 3:
                    text = f"<b>{text}</b>"
                    urgent.append(text)
            text += " · " + escape(row["category"])
            sections.setdefault(section, []).append(text)
        html = f"<h2>메모 정리 · {today:%Y-%m-%d}</h2>"
        if urgent:
            html += "<p><b>가장 급한 것</b><br>" + "<br>".join(urgent[:3]) + "</p>"
        for title in ("일정·마감", "할 일", "아이디어", "정보", "확인 필요"):
            if title in sections:
                html += f"<h3>{title}</h3><ul>" + "".join(f"<li>{text}</li>" for text in sections[title]) + "</ul>"
        return "<html><body>" + html + "</body></html>"
