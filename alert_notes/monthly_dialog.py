"""Pick the day of the month a recurring memo should come back."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCalendarWidget, QComboBox, QDialog, QDialogButtonBox, QLabel, QPushButton,
    QHBoxLayout, QRadioButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .monthly_rule import (
    KIND_DAY, KIND_LAST, KIND_WEEKDAY, ORDINAL_NAMES, WEEKDAY_NAMES,
    describe, make_rule, next_occurrence, parse_rule,
)


class MonthlyRuleDialog(QDialog):
    def __init__(self, note, parent=None):
        super().__init__(parent)
        self.setWindowTitle("매달 반복")
        self.setModal(True)
        self.setMinimumWidth(430)
        current = parse_rule(str(note["monthly_rule"] or "")) if note is not None else None
        self._had_rule = current is not None
        root = QVBoxLayout(self)
        title = QLabel("매달 반복되는 업무")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        description = QLabel(
            "정한 날이 되면 이 메모가 포스트잇으로 뜨고 체크가 모두 풀립니다. "
            "그 달에 한 번만 뜹니다."
        )
        description.setObjectName("mutedLabel")
        description.setWordWrap(True)
        root.addWidget(description)

        self.day_radio = QRadioButton("매달 지정한 날짜")
        self.last_radio = QRadioButton("매달 말일")
        self.weekday_radio = QRadioButton("매달 n째 주 n요일")
        for radio in (self.day_radio, self.last_radio, self.weekday_radio):
            root.addWidget(radio)
            radio.toggled.connect(self._sync)

        self.pages = QStackedWidget()
        # 날짜는 달력에서 고른다.
        self.calendar = QCalendarWidget()
        self.calendar.setObjectName("monthlyRuleCalendar")
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.calendar.setMaximumHeight(210)
        self.calendar.setAccessibleName("반복 날짜 선택")
        self.calendar.clicked.connect(lambda _d: self._sync())
        self.pages.addWidget(self.calendar)
        self.pages.addWidget(QWidget())

        weekday_page = QWidget()
        weekday_layout = QVBoxLayout(weekday_page)
        weekday_layout.setContentsMargins(0, 0, 0, 0)
        self.ordinal_combo = QComboBox()
        for value in (1, 2, 3, 4, -1):
            self.ordinal_combo.addItem(f"{ORDINAL_NAMES[value]} 주", value)
        self.weekday_combo = QComboBox()
        for index, name in enumerate(WEEKDAY_NAMES):
            self.weekday_combo.addItem(f"{name}요일", index)
        # Side by side and top-aligned: the page shares its height with the
        # calendar page, and stretched combos left a gap in the middle.
        picker = QHBoxLayout()
        picker.setSpacing(8)
        picker.addWidget(self.ordinal_combo)
        picker.addWidget(self.weekday_combo)
        picker.addStretch(1)
        weekday_layout.addLayout(picker)
        weekday_layout.addStretch(1)
        self.ordinal_combo.currentIndexChanged.connect(lambda _i: self._sync())
        self.weekday_combo.currentIndexChanged.connect(lambda _i: self._sync())
        self.pages.addWidget(weekday_page)
        root.addWidget(self.pages)

        self.preview = QLabel()
        self.preview.setObjectName("mutedLabel")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._clear_requested = False
        if self._had_rule:
            self.clear_button = QPushButton("반복 해제")
            self.clear_button.setObjectName("dangerButton")
            self.clear_button.clicked.connect(self._clear)
            buttons.addButton(self.clear_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        root.addWidget(buttons)

        rule = current or make_rule(KIND_DAY, day=date.today().day)
        kind = rule["kind"]
        self.day_radio.setChecked(kind == KIND_DAY)
        self.last_radio.setChecked(kind == KIND_LAST)
        self.weekday_radio.setChecked(kind == KIND_WEEKDAY)
        today = date.today()
        self.calendar.setSelectedDate(QDate(today.year, today.month, min(rule["day"], 28)))
        self.ordinal_combo.setCurrentIndex(max(0, self.ordinal_combo.findData(rule["ordinal"])))
        self.weekday_combo.setCurrentIndex(max(0, self.weekday_combo.findData(rule["weekday"])))
        self._sync()

    def _clear(self) -> None:
        self._clear_requested = True
        self.accept()

    @property
    def clear_requested(self) -> bool:
        return self._clear_requested

    def _fit_pages(self) -> None:
        """Only the visible page claims height, so the two short modes stay short."""
        current = self.pages.currentIndex()
        for index in range(self.pages.count()):
            page = self.pages.widget(index)
            policy = (
                QSizePolicy.Policy.Preferred if index == current
                else QSizePolicy.Policy.Ignored
            )
            page.setSizePolicy(policy, policy)
        self.pages.adjustSize()
        self.adjustSize()

    def _sync(self, *_args) -> None:
        self.pages.setCurrentIndex(
            0 if self.day_radio.isChecked() else 1 if self.last_radio.isChecked() else 2
        )
        self._fit_pages()
        rule = self.rule()
        upcoming = next_occurrence(rule, date.today())
        self.preview.setText(f"{describe(rule)} · 다음 표시 {upcoming:%Y-%m-%d}")

    def rule(self) -> dict:
        if self.last_radio.isChecked():
            return make_rule(KIND_LAST)
        if self.weekday_radio.isChecked():
            return make_rule(
                KIND_WEEKDAY,
                ordinal=self.ordinal_combo.currentData(),
                weekday=self.weekday_combo.currentData(),
            )
        return make_rule(KIND_DAY, day=self.calendar.selectedDate().day())
