"""일정 시작 기준 알림: 양수는 전, 음수는 후, 0은 정각."""

import re


def reminder_label(minutes: int) -> str:
    minutes = int(minutes)
    if minutes == 0:
        return "정각 알림"
    return f"{abs(minutes)}분 {'전' if minutes > 0 else '후'}"


def parse_reminder_value(text: str) -> int:
    """기존 숫자 입력을 보존하면서 `5분 후`도 편집/재열기한다."""
    match = re.fullmatch(r"\s*(-?\d+)\s*(?:분\s*([전후]))?\s*", text)
    if not match:
        raise ValueError("알림은 숫자 또는 ‘5분 전’, ‘5분 후’로 입력하세요.")
    value = int(match.group(1))
    if match.group(2):
        if value < 0:
            raise ValueError("분 전/후에는 음수를 사용할 수 없습니다.")
        value *= -1 if match.group(2) == "후" else 1
    if abs(value) > 525600:
        raise ValueError("알림은 시작 시각 전후 365일 이내로 입력하세요.")
    return value


def reminder_input_value(minutes: int) -> str:
    return reminder_label(minutes) if minutes < 0 else str(minutes)
