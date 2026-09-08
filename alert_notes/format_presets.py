import json


PRESET_COUNT = 4
PRESET_PREFIX = "text_format_preset_"
PRESET_NAME_PREFIX = "text_format_preset_name_"


def preset_key(slot: int) -> str:
    return f"{PRESET_PREFIX}{slot}"


def preset_name_key(slot: int) -> str:
    return f"{PRESET_NAME_PREFIX}{slot}"


def load_preset_name(store, slot: int) -> str:
    """A saved label, or "" when the slot still uses its number."""
    return str(store.setting(preset_name_key(slot), "")).strip()


def save_preset_name(store, slot: int, name: str) -> None:
    store.set_setting(preset_name_key(slot), str(name).strip())


def preset_summary(data: dict | None) -> str:
    """One-line description of what a slot applies, for the button tooltip."""
    if data is None:
        return "저장된 서식이 없습니다. 메뉴에서 현재 서식을 저장해 주세요."
    styles = [
        label for key, label in
        (("bold", "굵게"), ("italic", "기울임"), ("underline", "밑줄"), ("strike", "취소선"))
        if data.get(key)
    ]
    parts = [str(data.get("family", "")), f"{round(float(data.get('size', 0)))}pt"]
    parts.append(str(data.get("color", "")).upper())
    if styles:
        parts.append("·".join(styles))
    return " · ".join(part for part in parts if part)


def load_preset(store, slot: int) -> dict | None:
    raw = store.setting(preset_key(slot), "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    required = {"family", "size", "color", "bold", "italic", "underline", "strike"}
    return data if required.issubset(data) else None


def save_preset(store, slot: int, data: dict) -> None:
    store.set_setting(preset_key(slot), json.dumps(data, ensure_ascii=False))


def clear_preset(store, slot: int) -> None:
    store.set_setting(preset_key(slot), "")
    store.set_setting(preset_name_key(slot), "")


def ensure_first_preset(store, family: str) -> None:
    if store.setting(preset_key(1), ""):
        return
    save_preset(store, 1, {
        "family": family, "size": 10, "color": "#000000",
        "bold": False, "italic": False, "underline": False, "strike": False,
    })
