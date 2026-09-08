from datetime import datetime


def now_key() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def display_time(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value or ""
