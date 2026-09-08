from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from .schedule_recurrence import DATETIME_FMT


@dataclass(frozen=True)
class DayContextItem:
    item_id: int
    title: str
    item_type: str
    start: datetime
    end: datetime
    overlaps: bool

    @property
    def label(self) -> str:
        kind = "할 일" if self.item_type == "task" else "일정"
        marker = "겹침 · " if self.overlaps else ""
        return f"{marker}{self.start:%H:%M}–{self.end:%H:%M} · {kind} · {self.title}"


def same_day_context(
    store,
    start: datetime,
    end: datetime,
    *,
    current_id: int | None = None,
) -> list[DayContextItem]:
    """편집 중인 날의 다른 항목과 시간 겹침을 UI 밖에서 계산한다."""
    day_start = datetime.combine(start.date(), time.min)
    day_end = day_start + timedelta(days=1)
    result: list[DayContextItem] = []
    for row in store.schedules.items_for_range(
        day_start.strftime(DATETIME_FMT),
        day_end.strftime(DATETIME_FMT),
        include_completed=True,
    ):
        item_id = int(row["id"])
        if current_id is not None and item_id == int(current_id):
            continue
        other_start = datetime.strptime(
            str(row.get("display_start_at") or row.get("start_at")), DATETIME_FMT
        )
        other_end = datetime.strptime(
            str(row.get("display_end_at") or row.get("end_at")), DATETIME_FMT
        )
        result.append(
            DayContextItem(
                item_id=item_id,
                title=str(row.get("title") or "제목 없음"),
                item_type=str(row.get("item_type") or "event"),
                start=other_start,
                end=other_end,
                overlaps=other_start < end and other_end > start,
            )
        )
    return sorted(result, key=lambda item: (item.start, item.end, item.item_id))
