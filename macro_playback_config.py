"""Validation and compatibility helpers for repeat-task playback settings."""

MIN_PLAYBACK_SPEED = 0.5
MAX_PLAYBACK_SPEED = 10.0
MIN_REPEAT_COUNT = 1
MAX_REPEAT_COUNT = 999
SUPPORTED_TIMING_MODES = {"recorded", "scaled", "fixed"}


def validate_timing_mode(value, default: str = "scaled") -> str:
    mode = str(value or default)
    if mode not in SUPPORTED_TIMING_MODES:
        raise ValueError("timing_mode 값이 올바르지 않습니다.")
    return mode


def validate_playback_speed(value, default: float = 1.0) -> float:
    try:
        speed = float(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ValueError("재생 속도 형식이 올바르지 않습니다.") from exc
    if not MIN_PLAYBACK_SPEED <= speed <= MAX_PLAYBACK_SPEED:
        raise ValueError("재생 속도는 0.5~10.0배여야 합니다.")
    return speed


def validate_repeat_count(value, default: int = 1) -> int:
    candidate = default if value is None else value
    if isinstance(candidate, bool):
        raise ValueError("반복 횟수는 1~999 사이의 정수여야 합니다.")
    try:
        count = int(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError("반복 횟수는 1~999 사이의 정수여야 합니다.") from exc
    if isinstance(candidate, float) and not candidate.is_integer():
        raise ValueError("반복 횟수는 1~999 사이의 정수여야 합니다.")
    if not MIN_REPEAT_COUNT <= count <= MAX_REPEAT_COUNT:
        raise ValueError("반복 횟수는 1~999회여야 합니다.")
    return count


def editor_playback_speed(payload: dict) -> float:
    """Convert legacy recorded/fixed settings to the always-scaled editor UI."""
    mode = validate_timing_mode(payload.get("timing_mode", "recorded"))
    if mode != "scaled":
        return 1.0
    return validate_playback_speed(payload.get("playback_speed", 1.0))
