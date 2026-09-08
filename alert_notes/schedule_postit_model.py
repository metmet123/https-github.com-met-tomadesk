from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .deadline import deadline_chip_text, deadline_title, deadline_urgency
from .schedule_postit_settings import (
    COMPLETE_TRASH,
    SchedulePostitPreferences,
    VIEW_DAY,
    VIEW_DUE,
    VIEW_PRIORITY,
    VIEW_WEEK,
)
from .schedule_recurrence import DATETIME_FMT, normalize_rule


@dataclass(frozen=True)
class SchedulePostitItem:
    source: str
    item_id: int
    occurrence_at: str
    title: str
    badge: str
    target_at: datetime
    completed: bool
    priority: int = 0
    recurring: bool = False

    @property
    def time_text(self) -> str:
        return self.target_at.strftime("%H:%M")


class SchedulePostitModel:
    """UI와 분리된 일정 포스트잇 조회·정렬·완료 규칙."""

    def __init__(self, store):
        self.store = store

    def items(
        self,
        selected: date,
        preferences: SchedulePostitPreferences,
        *,
        today: date | None = None,
    ) -> list[SchedulePostitItem]:
        prefs = preferences.normalized()
        actual_today = today or date.today()
        start, end = _range_for_view(selected, prefs.view)
        result: list[SchedulePostitItem] = []
        for row in self.store.schedules.items_for_range(
            start.strftime(DATETIME_FMT), end.strftime(DATETIME_FMT), include_completed=True
        ):
            kind = str(row.get("item_type") or "event")
            if kind == "event" and not prefs.show_events:
                continue
            if kind == "task" and not prefs.show_tasks:
                continue
            target = datetime.strptime(
                str(row.get("display_start_at") or row.get("start_at")), DATETIME_FMT
            )
            result.append(
                SchedulePostitItem(
                    source="schedule",
                    item_id=int(row["id"]),
                    occurrence_at=str(row.get("occurrence_at") or row.get("start_at") or ""),
                    title=str(row.get("title") or "제목 없음"),
                    badge="일정" if kind == "event" else "할 일",
                    target_at=target,
                    completed=str(row.get("status") or "pending") == "completed",
                    priority=int(row.get("priority") or 0),
                    recurring=normalize_rule(row.get("recurrence_rule"))["frequency"] != "none",
                )
            )
        if prefs.show_memo_deadlines:
            result.extend(self._memo_deadlines(start, end, actual_today))
        if prefs.view == VIEW_PRIORITY:
            return sorted(result, key=lambda item: (-item.priority, item.target_at, item.item_id))
        return sorted(result, key=lambda item: (item.target_at, -item.priority, item.item_id))

    def set_completed(
        self,
        item: SchedulePostitItem,
        completed: bool,
        completion_mode: str,
    ) -> None:
        if item.source == "deadline":
            self.store.finish_deadline(item.item_id, completed)
            return
        if item.recurring:
            self.store.schedules.set_occurrence_completed(
                item.item_id, item.occurrence_at, completed
            )
            return
        if completed and completion_mode == COMPLETE_TRASH:
            self.store.schedules.delete_item(item.item_id)
            return
        self.store.schedules.set_completed(item.item_id, completed)

    def _memo_deadlines(
        self, start: datetime, end: datetime, today: date
    ) -> list[SchedulePostitItem]:
        result: list[SchedulePostitItem] = []
        for row in self.store.deadline_notes():
            raw = str(row["d_day_at"] or "")
            try:
                target = datetime.strptime(raw, DATETIME_FMT)
            except ValueError:
                continue
            # 지난 D-Day는 오늘 요약의 별도 묶음이 전담한다.
            if target.date() < today or not (start <= target < end):
                continue
            urgency = deadline_urgency(row)
            result.append(
                SchedulePostitItem(
                    source="deadline",
                    item_id=int(row["id"]),
                    occurrence_at=raw,
                    title=deadline_title(row),
                    badge=deadline_chip_text(row),
                    target_at=target,
                    completed=urgency == "done",
                    priority=3 if urgency == "today" else 0,
                )
            )
        return result


def _range_for_view(selected: date, view: str) -> tuple[datetime, datetime]:
    if view == VIEW_DAY:
        start_date = selected
        days = 1
    elif view in {VIEW_WEEK, VIEW_PRIORITY}:
        start_date = selected - timedelta(days=selected.weekday())
        days = 7
    elif view == VIEW_DUE:
        start_date = selected
        days = 90
    else:
        start_date = selected
        days = 1
    return (
        datetime.combine(start_date, time.min),
        datetime.combine(start_date + timedelta(days=days), time.min),
    )
