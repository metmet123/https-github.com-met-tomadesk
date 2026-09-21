"""Read-only memo templates and insertion-time placeholder formatting."""

from __future__ import annotations

from datetime import datetime
from html import escape
from html.parser import HTMLParser


DATE_FORMAT_SETTING = "memo_template_date_format"
TIME_FORMAT_SETTING = "memo_template_time_format"
DEFAULT_DATE_FORMAT = "iso"
DEFAULT_TIME_FORMAT = "24h"
DATE_FORMAT_OPTIONS = (
    ("iso", "2026-01-05"),
    ("dots", "2026.1.5."),
    ("korean", "2026년 1월 5일"),
)
TIME_FORMAT_OPTIONS = (
    ("24h", "14:30 (24시간)"),
    ("12h", "오후 2:30 (12시간)"),
)


def selected_template_formats(store) -> tuple[str, str]:
    """Keep unknown/older setting values on the known, compatible defaults."""
    if store is None:
        return DEFAULT_DATE_FORMAT, DEFAULT_TIME_FORMAT
    date = store.setting(DATE_FORMAT_SETTING, DEFAULT_DATE_FORMAT)
    time = store.setting(TIME_FORMAT_SETTING, DEFAULT_TIME_FORMAT)
    if date not in {key for key, _label in DATE_FORMAT_OPTIONS}:
        date = DEFAULT_DATE_FORMAT
    if time not in {key for key, _label in TIME_FORMAT_OPTIONS}:
        time = DEFAULT_TIME_FORMAT
    return date, time


def format_template_date(moment: datetime, choice: str) -> str:
    if choice == "dots":
        return f"{moment.year}.{moment.month}.{moment.day}."
    if choice == "korean":
        return f"{moment.year}년 {moment.month}월 {moment.day}일"
    return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"


def format_template_time(moment: datetime, choice: str) -> str:
    if choice == "12h":
        period = "오전" if moment.hour < 12 else "오후"
        return f"{period} {moment.hour % 12 or 12}:{moment.minute:02d}"
    return f"{moment.hour:02d}:{moment.minute:02d}"


# Negative identifiers cannot collide with SQLite template ids.
BUILTIN_TEMPLATES = (
    ("빠른 메모", "빠른메모", """{{title}}
작성: {{date}} {{time}}

[내용을 바로 입력]

▾ 참고·관련 자료
링크:
첨부:"""),
    ("오늘 업무", "오늘업무", """오늘 업무 · {{date}}

오늘 꼭 할 일
☐
☐
☐

진행할 일
☐

▾ 대기·확인 요청
내용 / 확인할 사람 / 확인 날짜

▾ 업무 기록
시간 / 처리 내용

마무리
완료한 일:
다음 날 이어 할 일:"""),
    ("회의록", "회의록", """{{title}}
일시: {{date}} {{time}}
참석자:
목적:

결정 사항
•

후속 업무
할 일 | 담당자 | 기한 | 완료
      |        |      | ☐

▾ 논의 내용
안건 1:
안건 2:

▾ 참고 자료
관련 메모:
링크·첨부:"""),
    ("업무·프로젝트 관리", "프로젝트", """{{title}}
시작일: {{date}}
목표:
완료 기준:
목표 기한:

현재 상태
진행 상황:
바로 다음 행동:

진행 체크리스트
☐
☐
☐

▾ 진행 기록
날짜 | 진행 내용 | 다음 조치

▾ 문제·결정 사항
문제:
선택한 방법:
선택 이유:

▾ 관련 자료
메모·파일·링크:"""),
    ("자료 정리", "자료정리", """{{title}}
정리일: {{date}}
출처:
자료 날짜:

핵심 요약
1.
2.
3.

내 업무에 적용할 점
•

▾ 상세 내용·발췌
[원문 발췌와 내 의견을 구분해 기록]

▾ 확인이 필요한 내용
☐

▾ 관련 자료
메모·링크·첨부:"""),
    ("문제 해결·오류 기록", "문제해결", """{{title}}
발견: {{date}} {{time}}
상태: 확인 중

증상
기대한 동작:
실제 동작:
발생 조건:

▾ 재현 순서
1.
2.
3.

▾ 시도한 방법
방법 | 결과

해결 내용
확인된 원인:
조치:
검증 결과:

☐ 같은 조건에서 재발하지 않는지 확인

▾ 화면·로그·참고 자료"""),
    ("전화·상담 기록", "상담기록", """{{title}}
일시: {{date}} {{time}}
상대방·소속:

문의 내용

답변·안내

약속한 조치·기한

▾ 후속 확인"""),
    ("아이디어·개선 제안", "개선제안", """{{title}}
기록일: {{date}}

불편한 점

제안

사용 예시

기대 효과

▾ 검토할 제약

다음 행동:"""),
    ("반복 업무 체크리스트", "반복업무", """{{title}}
작성: {{date}}
적용 대상·주기:

시작 전 준비
☐

수행 순서
☐
☐
☐

완료 확인
☐

▾ 예외 상황·주의사항"""),
)


def builtin_rows() -> list[dict]:
    return [
        {"id": -index, "name": name, "trigger": trigger, "builtin": True}
        for index, (name, trigger, _body) in enumerate(BUILTIN_TEMPLATES, 1)
    ]


def builtin_payload(template_id: int) -> dict | None:
    index = -int(template_id) - 1
    if index < 0 or index >= len(BUILTIN_TEMPLATES):
        return None
    body = BUILTIN_TEMPLATES[index][2]
    lines = ["☐ 할 일" if line == "☐" else line for line in body.splitlines()]
    html = "".join(f"<p>{escape(line) if line else '<br />'}</p>" for line in lines)
    metadata = []
    inside_toggle = False
    for line in lines:
        if line.startswith("▾ "):
            inside_toggle = True
            depth = 0
        elif inside_toggle and line:
            depth = 1
        else:
            if not line:
                inside_toggle = False
            depth = 0
        metadata.append({"indent": depth, "heading": 0, "user_state": -1})
    return {"version": 1, "kind": "blocks", "html": html, "text": "\n".join(lines), "blocks": metadata}


class _TextOnlySubstitution(HTMLParser):
    def __init__(self, values: dict[str, str]):
        super().__init__(convert_charrefs=False)
        self.values = values
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        for token, value in self.values.items():
            data = data.replace(token, escape(value))
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def handle_comment(self, data):
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.parts.append(f"<!{decl}>")


def fill_template_payload(
    payload: dict, *, title: str, now: datetime | None = None,
    date_format: str = DEFAULT_DATE_FORMAT, time_format: str = DEFAULT_TIME_FORMAT,
) -> dict:
    moment = now or datetime.now()
    values = {
        "{{date}}": format_template_date(moment, date_format),
        "{{time}}": format_template_time(moment, time_format),
        "{{title}}": str(title),
    }
    rendered = dict(payload)
    parser = _TextOnlySubstitution(values)
    parser.feed(str(payload.get("html") or ""))
    parser.close()
    rendered["html"] = "".join(parser.parts)
    plain = str(payload.get("text") or "")
    for token, value in values.items():
        plain = plain.replace(token, value)
    rendered["text"] = plain
    return rendered
