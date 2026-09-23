"""전역 단축키로 뜨는 한 줄 일정 창.

빠른 메모(``Ctrl+Alt+N``)의 일정 판이다.  어느 프로그램에 있든 한 줄을 치고
Enter를 누르면 일정이 생긴다.  창을 띄우는 비용이 0이어야 하므로 필드는 하나뿐이고,
읽은 결과와 겹치는 일정만 아래에 보여 준다 — 일정을 넣는 진짜 이유가 "겹치나?"이기
때문이다.

같은 한 줄을 D-Day(``D``)나 메모(``M``)로도 돌릴 수 있다.  세 가지가 모두 같은
문장에서 나오므로, 이 창 하나가 캘린더 축 전체의 입구가 된다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
)

from .categories import CATEGORIES, category_name
from . import ko_schedule_parser
from .schedule_recurrence import DATETIME_FMT, normalize_rule
from .schedule_token_edit import ScheduleTokenLineEdit
from .schedule_reminders import reminder_label


REPEAT_NAMES = {"daily": "매일", "weekly": "매주", "monthly": "매월", "yearly": "매년"}
SLOT_MINUTES = 30


class QuickScheduleDialog(QDialog):
    schedule_saved = pyqtSignal(int)
    detail_requested = pyqtSignal(int)
    note_saved = pyqtSignal(int)

    def __init__(self, store, parent=None, hotkey: str = "Ctrl+Alt+A"):
        super().__init__(parent)
        self.store = store
        self._parsed = None
        self._ignored_tokens: set[tuple[int, int, str]] = set()
        self._parse_source = ""
        self.setWindowTitle("빠른 일정")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(540)
        self.setObjectName("quickScheduleDialog")
        self._build_ui(hotkey)

    def _build_ui(self, hotkey: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        heading = QLabel("빠른 일정")
        heading.setObjectName("pageTitle")
        header.addWidget(heading)
        header.addStretch()
        self.hotkey_label = QLabel(hotkey.upper())
        self.hotkey_label.setObjectName("popoverKeyHint")
        header.addWidget(self.hotkey_label)
        root.addLayout(header)

        self.input_edit = ScheduleTokenLineEdit()
        self.input_edit.setObjectName("quickScheduleInput")
        self.input_edit.setPlaceholderText("내일 오후 3시 팀 회의 #업무 !30분전")
        self.input_edit.setAccessibleName("일정 한 줄 입력")
        root.addWidget(self.input_edit)

        self.title_label = QLabel()
        self.title_label.setObjectName("quickScheduleTitle")
        self.title_label.setWordWrap(True)
        root.addWidget(self.title_label)

        self.fields_label = QLabel()
        self.fields_label.setObjectName("quickScheduleFields")
        self.fields_label.setWordWrap(True)
        root.addWidget(self.fields_label)

        # 겹침 한 줄.  이 줄 때문에 창을 열 값어치가 생긴다.
        self.conflict_label = QLabel()
        self.conflict_label.setObjectName("quickScheduleConflict")
        self.conflict_label.setWordWrap(True)
        root.addWidget(self.conflict_label)

        self.hint_label = QLabel("Enter 저장 · Tab 상세 · Ctrl+D D-Day로 · Ctrl+M 메모로 · Esc 취소")
        self.hint_label.setObjectName("mutedLabel")
        root.addWidget(self.hint_label)

        self.input_edit.textChanged.connect(self._refresh_preview)
        self.input_edit.token_double_clicked.connect(self._cancel_parsed_token)
        self.input_edit.returnPressed.connect(self.save)

    # ------------------------------------------------------------------ 열기 --
    def prepare(self, hotkey: str | None = None) -> None:
        if hotkey:
            self.hotkey_label.setText(hotkey.upper())
        self._ignored_tokens.clear()
        self.input_edit.clear()
        self.input_edit.set_token_spans(())
        self._refresh_preview("")
        self.input_edit.setFocus()

    def default_start(self, now: datetime | None = None) -> datetime:
        """다음 30분 칸.  지금이 13:40이면 14:00부터 시작한다."""
        now = (now or datetime.now()).replace(second=0, microsecond=0)
        minutes = (now.minute // SLOT_MINUTES + 1) * SLOT_MINUTES
        return (now.replace(minute=0) + timedelta(minutes=minutes))

    # -------------------------------------------------------------- 미리보기 --
    def parsed(self):
        return self._parsed

    def _refresh_preview(self, text: str | None = None) -> None:
        raw = self.input_edit.text() if text is None else text
        self._ignored_tokens = ko_schedule_parser.remap_ignored_spans(
            self._parse_source, raw, self._ignored_tokens,
        )
        self._parse_source = raw
        base = self.default_start()
        self._parsed = ko_schedule_parser.parse(
            raw, base=base, base_end=base + timedelta(hours=1),
            ignored_spans=tuple(sorted(self._ignored_tokens)),
        )
        parsed = self._parsed
        self.input_edit.set_token_spans(parsed.spans)
        title = parsed.title.strip()
        self.title_label.setText(title or "제목을 적어 주세요")
        self.title_label.setProperty("empty", "true" if not title else "false")
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)

        start, end = self.range_values()
        pieces = [f"{start:%Y-%m-%d} ({'월화수목금토일'[start.weekday()]})"]
        pieces.append("종일" if parsed.all_day else f"{start:%H:%M} – {end:%H:%M}")
        pieces.append(category_name(parsed.category) if parsed.category else "분류 없음")
        pieces.append(
            reminder_label(parsed.reminders[0])
            if parsed.reminders else "알림 없음"
        )
        if parsed.recurrence and parsed.recurrence.get("frequency", "none") != "none":
            pieces.append(REPEAT_NAMES.get(parsed.recurrence["frequency"], "반복"))
        self.fields_label.setText("  ·  ".join(parsed.issues or pieces))
        clashes = self.overlapping(start, end)
        self.conflict_label.setText(self.conflict_text(start, end, clashes))
        # 겹치는 게 있으면 색이 먼저 말한다.  초록은 "비어 있다"는 뜻으로만 쓴다.
        self.conflict_label.setProperty("conflict", "true" if clashes else "false")
        self.conflict_label.style().unpolish(self.conflict_label)
        self.conflict_label.style().polish(self.conflict_label)

    def _cancel_parsed_token(self, start: int, end: int, kind: str) -> None:
        if self._parsed is None:
            return
        if kind == "time":
            targets = [span for span in self._parsed.spans if span.kind == "time"]
        else:
            targets = [
                span for span in self._parsed.spans
                if span.kind == kind and span.start < end and start < span.end
            ]
        self._ignored_tokens.update((span.start, span.end, span.kind) for span in targets)
        self._refresh_preview()

    def range_values(self) -> tuple[datetime, datetime]:
        parsed = self._parsed
        base = self.default_start()
        start = parsed.start if parsed and parsed.start else base
        end = parsed.end if parsed and parsed.end else start + timedelta(hours=1)
        return start, end

    def conflict_text(self, start: datetime, end: datetime, others=None) -> str:
        others = self.overlapping(start, end) if others is None else others
        if not others:
            return "같은 시간대에 다른 일정 없음"
        first = str(others[0]["title"])
        if len(others) == 1:
            return f"‘{first}’ 과(와) 겹칩니다."
        return f"‘{first}’ 외 {len(others) - 1}건과 겹칩니다."

    def overlapping(self, start: datetime, end: datetime) -> list:
        """그날 일정 중 시간이 실제로 포개지는 것만 고른다."""
        day = datetime.combine(start.date(), datetime.min.time())
        try:
            rows = self.store.schedules.items_for_range(
                day.strftime(DATETIME_FMT), (day + timedelta(days=1)).strftime(DATETIME_FMT)
            )
        except Exception:
            return []
        found = []
        for row in rows:
            try:
                other_start = datetime.strptime(str(row["display_start_at"]), DATETIME_FMT)
                other_end = datetime.strptime(str(row["display_end_at"]), DATETIME_FMT)
            except ValueError:
                continue
            if other_start < end and start < other_end:
                found.append(row)
        return found

    # ---------------------------------------------------------------- 저장 --
    def values(self) -> dict:
        parsed = self._parsed
        start, end = self.range_values()
        rule = normalize_rule(parsed.recurrence if parsed else None)
        return {
            "id": None,
            "title": parsed.title.strip() if parsed else self.input_edit.text().strip(),
            "details": "",
            "item_type": "event",
            "start_at": start.strftime(DATETIME_FMT),
            "end_at": end.strftime(DATETIME_FMT),
            "all_day": bool(parsed.all_day) if parsed else False,
            "category": (parsed.category if parsed and parsed.category else CATEGORIES[0][1]),
            "priority": 0,
            "note_id": None,
            "status": "pending",
            "recurrence_rule": rule,
            "reminders": list(parsed.reminders) if parsed else [],
            "hotkey": "",
            "hotkey_action": "open",
        }

    def _has_text(self) -> bool:
        if self._parsed is not None and self._parsed.issues:
            self.fields_label.setText(" · ".join(self._parsed.issues))
            self.input_edit.setFocus()
            return False
        if self.values()["title"].strip():
            return True
        self.title_label.setText("날짜·시간 외에 일정 제목을 입력해 주세요")
        self.input_edit.setFocus()
        return False

    def save(self) -> int | None:
        if not self._has_text():
            return None
        item_id = int(self.store.schedules.save_item(self.values()))
        self.schedule_saved.emit(item_id)
        self.accept()
        return item_id

    def save_and_open(self) -> int | None:
        """Tab — 저장한 다음 그 일정을 캘린더에서 열어 마저 손본다."""
        if not self._has_text():
            return None
        item_id = int(self.store.schedules.save_item(self.values()))
        self.schedule_saved.emit(item_id)
        self.detail_requested.emit(item_id)
        self.accept()
        return item_id

    def save_as_deadline(self) -> int | None:
        """D — 같은 한 줄을 D-Day로 돌린다."""
        if not self._has_text():
            return None
        values = self.values()
        note_id = int(self.store.create_note(values["title"], ""))
        self.store.update_note(
            note_id, d_day_at=values["start_at"], d_day_label=values["title"], d_day_alert=1
        )
        self.note_saved.emit(note_id)
        self.accept()
        return note_id

    def save_as_note(self) -> int | None:
        """M — 시간을 못 정했으면 메모로 남긴다."""
        if not self._has_text():
            return None
        values = self.values()
        note_id = int(self.store.create_note(values["title"], self.input_edit.text().strip()))
        self.note_saved.emit(note_id)
        self.accept()
        return note_id

    # ------------------------------------------------------------- 키 입력 --
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key == Qt.Key.Key_Tab and not event.modifiers():
            self.save_and_open()
            return
        # D·M은 제목에 쓰는 글자이기도 하므로, 수식 키를 함께 눌렀을 때만 전환한다.
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_D:
                self.save_as_deadline()
                return
            if key == Qt.Key.Key_M:
                self.save_as_note()
                return
        super().keyPressEvent(event)
