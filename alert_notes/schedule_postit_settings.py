from __future__ import annotations

from dataclasses import asdict, dataclass
import json


VIEW_DAY = "day"
VIEW_WEEK = "week"
VIEW_DUE = "due"
VIEW_PRIORITY = "priority"
VALID_VIEWS = {VIEW_DAY, VIEW_WEEK, VIEW_DUE, VIEW_PRIORITY}

COMPLETE_STRIKE = "strike"
COMPLETE_TRASH = "trash"
VALID_COMPLETION_MODES = {COMPLETE_STRIKE, COMPLETE_TRASH}

SETTING_PREFIX = "schedule_postit_"


@dataclass(frozen=True)
class SchedulePostitPreferences:
    view: str = VIEW_DAY
    max_rows: int = 8
    show_events: bool = True
    show_tasks: bool = True
    show_memo_deadlines: bool = False
    completion_mode: str = COMPLETE_STRIKE
    hotkey: str = ""

    @classmethod
    def load(cls, store) -> "SchedulePostitPreferences":
        return cls(
            view=_choice(store.setting(SETTING_PREFIX + "view", VIEW_DAY), VALID_VIEWS, VIEW_DAY),
            max_rows=_bounded_int(store.setting(SETTING_PREFIX + "max_rows", "8"), 8, 3, 15),
            show_events=_bool(store.setting(SETTING_PREFIX + "show_events", "true"), True),
            show_tasks=_bool(store.setting(SETTING_PREFIX + "show_tasks", "true"), True),
            show_memo_deadlines=_bool(
                store.setting(SETTING_PREFIX + "show_memo_deadlines", "false"), False
            ),
            completion_mode=_choice(
                store.setting(SETTING_PREFIX + "completion_mode", COMPLETE_STRIKE),
                VALID_COMPLETION_MODES,
                COMPLETE_STRIKE,
            ),
            hotkey=str(store.setting(SETTING_PREFIX + "hotkey", "") or "").strip(),
        )

    def save(self, store) -> None:
        normalized = self.normalized()
        for key, value in asdict(normalized).items():
            if isinstance(value, bool):
                text = "true" if value else "false"
            else:
                text = str(value)
            store.set_setting(SETTING_PREFIX + key, text)

    def normalized(self) -> "SchedulePostitPreferences":
        show_events = bool(self.show_events)
        show_tasks = bool(self.show_tasks)
        show_deadlines = bool(self.show_memo_deadlines)
        if not (show_events or show_tasks or show_deadlines):
            show_events = True
            show_tasks = True
        return SchedulePostitPreferences(
            view=_choice(self.view, VALID_VIEWS, VIEW_DAY),
            max_rows=_bounded_int(self.max_rows, 8, 3, 15),
            show_events=show_events,
            show_tasks=show_tasks,
            show_memo_deadlines=show_deadlines,
            completion_mode=_choice(
                self.completion_mode, VALID_COMPLETION_MODES, COMPLETE_STRIKE
            ),
            hotkey=str(self.hotkey or "").strip(),
        )


def load_position(store) -> tuple[int, int] | None:
    try:
        values = json.loads(store.setting(SETTING_PREFIX + "position", ""))
        if isinstance(values, list) and len(values) == 2:
            return int(values[0]), int(values[1])
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return None


def save_position(store, x: int, y: int) -> None:
    store.set_setting(SETTING_PREFIX + "position", json.dumps([int(x), int(y)]))


def _bool(value, default: bool) -> bool:
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return bool(default)


def _choice(value, choices: set[str], default: str) -> str:
    text = str(value or "").strip().casefold()
    return text if text in choices else default


def _bounded_int(value, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))
