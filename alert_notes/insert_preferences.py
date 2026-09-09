"""Shared insert-menu order and typing-trigger preferences."""

from __future__ import annotations

import json

from PyQt6.QtCore import QObject, pyqtSignal

from .insert_menu import INSERT_ITEMS, InsertItem


ORDER_KEY = "memo_insert_order_v1"
TRIGGERS_KEY = "memo_typing_triggers_v1"
FIXED_ALIASES = {
    "bullet": ("* ",),
    "checklist": ("[ ] ",),
    "quote": ("| ",),
}


def _item_id(item: InsertItem) -> str:
    return item.item_id or item.method


def default_order() -> list[str]:
    return [_item_id(item) for item in INSERT_ITEMS]


def default_triggers() -> dict[str, str]:
    return {_item_id(item): item.typing for item in INSERT_ITEMS if item.typing}


def normalize_order(value) -> list[str]:
    known = default_order()
    result: list[str] = []
    if isinstance(value, (list, tuple)):
        for raw in value:
            item_id = str(raw)
            if item_id in known and item_id not in result:
                result.append(item_id)
    result.extend(item_id for item_id in known if item_id not in result)
    return result


def normalize_triggers(value) -> dict[str, str]:
    defaults = default_triggers()
    if not isinstance(value, dict):
        return defaults
    return {
        item_id: str(value.get(item_id, trigger))
        for item_id, trigger in defaults.items()
    }


def validate_triggers(triggers: dict[str, str]) -> dict[str, str]:
    errors: dict[str, str] = {}
    seen: dict[str, str] = {
        alias.casefold(): item_id
        for item_id, aliases in FIXED_ALIASES.items()
        for alias in aliases
    }
    for item_id, raw in triggers.items():
        trigger = str(raw)
        if not trigger.strip():
            errors[item_id] = "줄앞 입력은 비워 둘 수 없습니다."
            continue
        folded = trigger.casefold()
        if folded in seen and seen[folded] != item_id:
            errors[item_id] = "다른 기능과 같은 줄앞 입력입니다."
            errors.setdefault(seen[folded], "다른 기능과 같은 줄앞 입력입니다.")
        else:
            seen[folded] = item_id
    values = list(seen.items())
    for left, left_id in values:
        for right, right_id in values:
            if left_id == right_id:
                continue
            # '# ' and '## ' are not prefixes of each other; exact spaces matter.
            if right.startswith(left):
                errors.setdefault(left_id, "다른 입력의 접두어라 먼저 실행될 수 있습니다.")
                errors.setdefault(right_id, "다른 입력과 접두어가 겹칩니다.")
    return errors


class InsertPreferences(QObject):
    changed = pyqtSignal()

    def __init__(self, store=None):
        super().__init__()
        self.store = store
        self.order = self._load_json(ORDER_KEY, default_order())
        self.order = normalize_order(self.order)
        self.triggers = normalize_triggers(self._load_json(TRIGGERS_KEY, default_triggers()))

    def _load_json(self, key: str, fallback):
        if self.store is None:
            return fallback
        try:
            getter = getattr(self.store, "setting", None)
            if callable(getter):
                return json.loads(getter(key, ""))
            return fallback
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback

    def ordered_items(self) -> tuple[InsertItem, ...]:
        by_id = {_item_id(item): item for item in INSERT_ITEMS}
        return tuple(by_id[item_id] for item_id in self.order if item_id in by_id)

    def typing_rules(self) -> tuple[tuple[str, bool, str], ...]:
        by_id = {_item_id(item): item for item in INSERT_ITEMS}
        rules = []
        for item_id in self.order:
            item = by_id.get(item_id)
            trigger = self.triggers.get(item_id, "")
            if item is None or not trigger:
                continue
            rules.append((trigger.rstrip() if trigger.endswith(" ") else trigger,
                          trigger.endswith(" "), item.method))
            for alias in FIXED_ALIASES.get(item_id, ()):
                rules.append((alias.rstrip(), alias.endswith(" "), item.method))
        return tuple(rules)

    def save(self, order, triggers) -> dict[str, str]:
        normalized_order = normalize_order(order)
        normalized_triggers = normalize_triggers(triggers)
        errors = validate_triggers(normalized_triggers)
        if errors:
            return errors
        self.order = normalized_order
        self.triggers = normalized_triggers
        if self.store is not None:
            self.store.set_setting(ORDER_KEY, json.dumps(self.order, ensure_ascii=False))
            self.store.set_setting(TRIGGERS_KEY, json.dumps(self.triggers, ensure_ascii=False))
        self.changed.emit()
        return {}

    def reset_order(self) -> None:
        self.save(default_order(), self.triggers)

    def reset_triggers(self) -> None:
        self.save(self.order, default_triggers())


def get_insert_preferences(store=None) -> InsertPreferences:
    if store is None:
        return InsertPreferences()
    preferences = getattr(store, "_insert_preferences", None)
    if preferences is None:
        preferences = InsertPreferences(store)
        setattr(store, "_insert_preferences", preferences)
    return preferences
