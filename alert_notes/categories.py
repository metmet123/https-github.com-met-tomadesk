"""Schedule category defaults and user-customizable metadata."""

from __future__ import annotations

import json
import re
import unicodedata
from uuid import uuid4

CATEGORIES = (
    ("업무", "sky"),
    ("개인", "mint"),
    ("중요", "peach"),
    ("학습", "vanilla"),
    ("기타", "lavender"),
)

# 키에서 이름으로.  dict(CATEGORIES)는 이름에서 키로 가는 반대 방향이라,
# category_name('sky')가 '일정'을 돌려주고 있었다.
CATEGORY_NAMES = {key: name for name, key in CATEGORIES}
CATEGORY_COLORS = {
    "sky": ("#E7F0FF", "#234F9A"),
    "mint": ("#E4F8EE", "#176448"),
    "peach": ("#FFE9E7", "#9C3D37"),
    "vanilla": ("#FFF4D6", "#815B10"),
    "lavender": ("#F0EAFE", "#6042A6"),
}

SCHEDULE_CATEGORY_SETTING = "schedule_categories_v1"


def default_schedule_categories() -> list[dict]:
    return [
        {"id": key, "name": name, "color": key, "aliases": []}
        for name, key in CATEGORIES
    ]


def schedule_categories(store) -> list[dict]:
    """Read independent schedule categories without changing legacy item keys."""
    raw = store.setting(SCHEDULE_CATEGORY_SETTING, "")
    if not raw:
        return default_schedule_categories()
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list) or not rows:
            raise ValueError("empty category list")
        return _validated_categories(rows)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return default_schedule_categories()


def save_schedule_categories(store, rows: list[dict]) -> list[dict]:
    categories = _validated_categories(rows)
    store.set_setting(SCHEDULE_CATEGORY_SETTING, json.dumps(categories, ensure_ascii=False))
    return categories


def new_schedule_category(name: str, color: str = "sky", aliases=()) -> dict:
    return {"id": f"user_{uuid4().hex}", "name": str(name).strip(),
            "color": color, "aliases": list(aliases)}


def _validated_categories(rows: list[dict]) -> list[dict]:
    if not rows or len(rows) > 100:
        raise ValueError("일정 분류는 1~100개로 설정해 주세요.")
    result = []
    ids = set()
    names = set()
    for row in rows:
        key = str(row["id"]).strip()
        name = str(row["name"]).strip()
        color = str(row.get("color") or "sky")
        aliases = row.get("aliases") or []
        if (not re.fullmatch(r"[A-Za-z0-9_]{1,64}", key) or not name
                or len(name) > 30 or color not in CATEGORY_COLORS
                or not isinstance(aliases, list) or len(aliases) > 30):
            raise ValueError("분류 이름·색상·연관어를 확인해 주세요.")
        folded = name.casefold()
        if key in ids or folded in names:
            raise ValueError("분류 이름은 중복할 수 없습니다.")
        ids.add(key)
        names.add(folded)
        clean_aliases = []
        for alias in aliases:
            alias = str(alias).strip()
            if not alias or len(alias) > 30:
                raise ValueError("연관어는 1~30자로 입력해 주세요.")
            if alias.casefold() not in {value.casefold() for value in clean_aliases}:
                clean_aliases.append(alias)
        result.append({"id": key, "name": name, "color": color,
                       "aliases": clean_aliases})
    return result


def category_spec(categories: list[dict], key: object) -> dict | None:
    return next((row for row in categories if row["id"] == str(key)), None)


def schedule_category_name(categories: list[dict], key: object) -> str:
    row = category_spec(categories, key)
    return row["name"] if row is not None else category_name(key)


def schedule_category_colors(categories: list[dict], key: object) -> tuple[str, str]:
    row = category_spec(categories, key)
    color_key = row["color"] if row is not None else str(key)
    return CATEGORY_COLORS.get(color_key, ("#E7F0FF", "#234F9A"))


def recommend_schedule_category(title: str, categories: list[dict]) -> str | None:
    """Recommend only a unique, explicit title word; never guess broad meaning."""
    title = unicodedata.normalize("NFC", str(title)).casefold()
    for field in ("name", "aliases"):
        hits = []
        for row in categories:
            terms = [row["name"]] if field == "name" else row.get("aliases", [])
            for term in terms:
                term = unicodedata.normalize("NFC", term.strip()).casefold()
                if not term:
                    continue
                pattern = r"(?<![가-힣a-z0-9])" + re.escape(term).replace(r"\ ", r"\s+") + r"(?![가-힣a-z0-9])"
                if re.search(pattern, title):
                    hits.append(row["id"])
                    break
        unique = set(hits)
        if len(unique) == 1:
            return hits[0]
        if unique:
            return None
    return None


def category_name(value: object) -> str:
    return CATEGORY_NAMES.get(str(value), "일정")

