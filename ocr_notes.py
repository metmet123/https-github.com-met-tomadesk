"""Explicit OCR-to-note review; parsing never writes data."""
from dataclasses import dataclass
from datetime import datetime

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import (QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
                            QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout)

from alert_notes.ko_schedule_parser import parse
from alert_notes.rich_text import is_rich_text_content


@dataclass(frozen=True)
class DeadlineCandidate:
    due: datetime
    source: str
    has_time: bool


def deadline_candidates(text, anchor):
    """Conservative line-leading parser; time-only and recurring input excluded.

    Analysis is bounded, but saved text is never truncated. Relative dates keep
    the original recognition anchor even after editing or crossing midnight.
    """
    results, seen = [], set()
    for line in text[:20_000].splitlines()[:200]:
        source = line.strip()
        raw = source
        for prefix in ("마감일:", "마감일 :", "마감:", "마감 :", "날짜:", "날짜 :", "일시:", "일시 :"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):].strip()
                break
        if not raw or len(raw) > 1000:
            continue
        try:
            parsed = parse(raw, now=anchor, base=anchor.replace(hour=0, minute=0, second=0, microsecond=0))
        except (ValueError, OverflowError):
            continue
        if parsed.start is None or parsed.recurrence or not any(s.kind == "date" for s in parsed.spans):
            continue
        has_time = not parsed.all_day and any(s.kind == "time" for s in parsed.spans)
        due = parsed.start.replace(second=0, microsecond=0)
        if due not in seen:
            results.append(DeadlineCandidate(due, source, has_time))
            seen.add(due)
        if len(results) == 10:
            break
    return results


def note_content(text):
    # OCR is always literal text, including a captured HTML source listing.
    if is_rich_text_content(text):
        document = QTextDocument()
        document.setPlainText(text)
        return document.toHtml()
    return text


class OcrNoteReview(QDialog):
    def __init__(self, text, candidates=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("OCR 결과로 D-Day 만들기" if candidates else "OCR 결과로 새 메모 만들기")
        self.resize(580, 470)
        self._candidates = tuple(candidates)
        layout = QVBoxLayout(self)
        notice = QLabel("새 메모만 만듭니다. 기존 메모는 변경하지 않으며 개별 알림은 꺼짐입니다. 기존 ‘당일 알림’ 설정은 유지됩니다.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        self.title_edit = QLineEdit(next((line.strip()[:120] for line in text.splitlines() if line.strip()), "OCR 메모"))
        form.addRow("제목", self.title_edit)
        self.candidate_combo = QComboBox()
        self.candidate_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.candidate_combo.setMinimumContentsLength(20)
        self.due_edit = QDateTimeEdit()
        self.due_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setMinimumDateTime(QDateTime(datetime(1, 1, 1)))
        self.due_edit.setMaximumDateTime(QDateTime(datetime(9999, 12, 31, 23, 59)))
        self.date_notice = QLabel()
        self.date_notice.setWordWrap(True)
        if candidates:
            self.candidate_combo.addItem("날짜 후보를 선택해 주세요", None)
            for candidate in candidates:
                self.candidate_combo.addItem(candidate.due.strftime("%Y-%m-%d %H:%M") + " · " + candidate.source[:100], candidate)
            form.addRow("인식 후보", self.candidate_combo)
            form.addRow("확정 날짜·시간", self.due_edit)
            form.addRow(self.date_notice)
        layout.addLayout(form)
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlainText(text)
        self.body_edit.setReadOnly(True)
        layout.addWidget(QLabel("저장할 본문 (수정하려면 취소 후 OCR 결과창에서 편집)"))
        layout.addWidget(self.body_edit)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("확인한 내용으로 새로 만들기")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        # Enter alone must not accidentally accept an OCR date.
        for button in self.buttons.buttons():
            button.setAutoDefault(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.candidate_combo.currentIndexChanged.connect(self._choose_candidate)
        self.title_edit.textChanged.connect(self._validate)
        if len(candidates) == 1:
            self.candidate_combo.setCurrentIndex(1)
        self._choose_candidate()

    def _choose_candidate(self):
        candidate = self.candidate_combo.currentData()
        self.due_edit.setEnabled(candidate is not None)
        if candidate is not None:
            self.due_edit.setDateTime(QDateTime(candidate.due))
            detail = "인식한 날짜·시간을 확인하고 필요하면 수정하세요."
            if not candidate.has_time:
                detail = "시간은 인식되지 않았습니다. 00:00을 초기값으로 표시하니 원하는 시간인지 확인하세요."
            self.date_notice.setText(detail + " 상대 날짜와 연도 없는 날짜는 인식 시점을 기준으로 해석합니다. 시간 지정 알림은 꺼짐입니다.")
        else:
            self.date_notice.setText("여러 날짜 중 하나를 직접 선택하세요. 자동으로 저장하지 않습니다.")
        self._validate()

    def _validate(self):
        valid = bool(self.title_edit.text().strip()) and (not self._candidates or self.candidate_combo.currentData() is not None)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(valid)

    def accept(self):
        if self.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled():
            super().accept()

    def values(self):
        due = self.due_edit.dateTime().toString("yyyyMMddHHmm") if self._candidates else ""
        return self.title_edit.text().strip(), self.body_edit.toPlainText(), due
