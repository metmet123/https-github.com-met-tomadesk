from PyQt6.QtCore import QDate, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QDateEdit, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .recurrence import (
    RULE_DAILY, RULE_MONTHLY, RULE_NONE, RULE_WEEKDAYS, RULE_WEEKLY,
    RecurrenceRule, is_allowed, next_occurrence, repeat_summary,
)


class RecurrenceControls(QWidget):
    changed = pyqtSignal()

    def __init__(self, due_input, parent=None):
        super().__init__(parent)
        self.due_input = due_input
        self.day_buttons: list[QPushButton] = []
        self.occurrence_number = 1
        self._build_ui()
        self._bind()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("반복"))
        self.rule_combo = QComboBox(self)
        for label, value in (("반복 안 함", RULE_NONE), ("매일", RULE_DAILY), ("평일", RULE_WEEKDAYS),
                             ("매주", RULE_WEEKLY), ("매월", RULE_MONTHLY)):
            self.rule_combo.addItem(label, value)
        self.rule_combo.setAccessibleName("반복 설정")
        self.rule_combo.hide()
        self.rule_button_group = QButtonGroup(self)
        self.rule_button_group.setExclusive(True)
        self.rule_buttons: dict[str, QPushButton] = {}
        segments_host = QWidget(self)
        segments_layout = QHBoxLayout(segments_host)
        segments_layout.setContentsMargins(0, 0, 0, 0)
        segments_layout.setSpacing(0)
        rule_options = (("반복 안 함", RULE_NONE), ("매일", RULE_DAILY), ("평일", RULE_WEEKDAYS),
                        ("매주", RULE_WEEKLY), ("매월", RULE_MONTHLY))
        for index, (label, value) in enumerate(rule_options):
            button = QPushButton(label)
            button.setObjectName("recurrenceRuleButton")
            button.setCheckable(True)
            button.setProperty(
                "segmentPosition",
                "first" if index == 0 else "last" if index == len(rule_options) - 1 else "middle",
            )
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.setAccessibleName(f"반복 {label}")
            button.clicked.connect(lambda _checked=False, rule_type=value: self._select_rule(rule_type))
            self.rule_button_group.addButton(button)
            self.rule_buttons[value] = button
            segments_layout.addWidget(button)
        row.addWidget(segments_host)
        row.addStretch(1)
        root.addLayout(row)

        self.end_controls = QWidget()
        end_row = QHBoxLayout(self.end_controls)
        end_row.setContentsMargins(0, 0, 0, 0)
        end_row.setSpacing(6)
        self.end_combo = QComboBox(self.end_controls)
        self.end_combo.addItem("계속 반복", "never")
        self.end_combo.addItem("날짜까지", "date")
        self.end_combo.addItem("횟수 지정", "count")
        self.end_combo.hide()
        self.end_button_group = QButtonGroup(self.end_controls)
        self.end_button_group.setExclusive(True)
        self.end_buttons: dict[str, QRadioButton] = {}
        self.end_date = QDateEdit(QDate.currentDate().addYears(1))
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_count = QSpinBox()
        self.end_count.setRange(1, 999)
        self.end_count.setValue(10)
        end_row.addWidget(QLabel("반복 종료"))
        for label, value in (("계속 반복", "never"), ("날짜까지", "date"), ("횟수 지정", "count")):
            button = QRadioButton(label)
            button.setAccessibleName(f"반복 종료 {label}")
            button.toggled.connect(
                lambda checked, end_type=value: self._select_end_type(end_type) if checked else None
            )
            self.end_button_group.addButton(button)
            self.end_buttons[value] = button
            end_row.addWidget(button)
            if value == "date":
                end_row.addWidget(self.end_date)
            elif value == "count":
                end_row.addWidget(self.end_count)
        end_row.addStretch(1)
        root.addWidget(self.end_controls)
        self.details_widget = QWidget()
        details = QHBoxLayout(self.details_widget)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(6)
        self.weekly_widget = QWidget()
        weekly = QHBoxLayout(self.weekly_widget)
        weekly.setContentsMargins(0, 0, 0, 0)
        weekly.setSpacing(4)
        for index, name in enumerate("월화수목금토일"):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setFixedSize(30, 30)
            weekly.addWidget(button)
            self.day_buttons.append(button)
        weekly.addStretch()
        details.addWidget(self.weekly_widget)
        self.monthly_widget = QWidget()
        monthly = QHBoxLayout(self.monthly_widget)
        monthly.setContentsMargins(0, 0, 0, 0)
        monthly.setSpacing(6)
        self.month_day = QSpinBox()
        self.month_day.setRange(1, 31)
        monthly.addWidget(QLabel("매월 날짜"))
        monthly.addWidget(self.month_day)
        monthly.addStretch()
        details.addWidget(self.monthly_widget)
        details.addStretch()
        root.addWidget(self.details_widget)
        self.summary_label = QLabel(self)
        self.summary_label.setObjectName("recurrenceStatus")
        self.summary_label.hide()
        self.next_label = QLabel(self)
        self.next_label.setObjectName("recurrenceStatus")
        self.next_label.hide()
        root.addWidget(self.summary_label)
        root.addWidget(self.next_label)

    def _bind(self) -> None:
        self.rule_combo.currentIndexChanged.connect(self.refresh)
        self.end_combo.currentIndexChanged.connect(self.refresh)
        self.month_day.valueChanged.connect(self.refresh)
        self.end_date.dateChanged.connect(self.refresh)
        self.end_count.valueChanged.connect(self.refresh)
        self.due_input.changed.connect(self.refresh)
        for button in self.day_buttons:
            button.toggled.connect(self.refresh)

    def _select_rule(self, rule_type: str) -> None:
        index = self.rule_combo.findData(rule_type)
        if index >= 0:
            self.rule_combo.setCurrentIndex(index)

    def _select_end_type(self, end_type: str) -> None:
        index = self.end_combo.findData(end_type)
        if index >= 0:
            self.end_combo.setCurrentIndex(index)

    def rule(self) -> RecurrenceRule:
        weekdays = tuple(index for index, button in enumerate(self.day_buttons) if button.isChecked())
        if self.rule_combo.currentData() == RULE_WEEKLY and not weekdays:
            weekdays = (self.due_input.datetime().weekday(),)
        return RecurrenceRule(
            str(self.rule_combo.currentData()), weekdays, self.month_day.value(),
            str(self.end_combo.currentData()),
            self.end_date.date().toString("yyyyMMdd") if self.end_combo.currentData() == "date" else None,
            self.end_count.value() if self.end_combo.currentData() == "count" else None,
        )

    def set_rule(self, rule: RecurrenceRule | None, occurrence_number: int = 1) -> None:
        rule = rule or RecurrenceRule()
        self.occurrence_number = max(1, int(occurrence_number))
        controls = [self.rule_combo, self.end_combo, self.month_day, self.end_date, self.end_count, *self.day_buttons]
        for control in controls:
            control.blockSignals(True)
        try:
            self.rule_combo.setCurrentIndex(max(0, self.rule_combo.findData(rule.rule_type)))
            for index, button in enumerate(self.day_buttons):
                button.setChecked(index in set(rule.weekdays))
            self.month_day.setValue(rule.month_day or self.due_input.datetime().day)
            self.end_combo.setCurrentIndex(max(0, self.end_combo.findData(rule.end_type)))
            if rule.end_date:
                self.end_date.setDate(QDate.fromString(rule.end_date, "yyyyMMdd"))
            if rule.max_occurrences:
                self.end_count.setValue(int(rule.max_occurrences))
        finally:
            for control in controls:
                control.blockSignals(False)
        self.refresh()

    def refresh(self, *_args) -> None:
        if not self.due_input.is_valid():
            self.summary_label.clear()
            self.next_label.clear()
            self.summary_label.hide()
            self.next_label.hide()
            return
        rule_type = self.rule_combo.currentData()
        for value, button in self.rule_buttons.items():
            button.blockSignals(True)
            button.setChecked(value == rule_type)
            button.blockSignals(False)
        end_type = str(self.end_combo.currentData() or "never")
        for value, button in self.end_buttons.items():
            button.blockSignals(True)
            button.setChecked(value == end_type)
            button.blockSignals(False)
        recurring = rule_type != RULE_NONE
        if rule_type == RULE_WEEKLY and not any(button.isChecked() for button in self.day_buttons):
            button = self.day_buttons[self.due_input.datetime().weekday()]
            button.blockSignals(True)
            button.setChecked(True)
            button.blockSignals(False)
        self.weekly_widget.setVisible(rule_type == RULE_WEEKLY)
        self.monthly_widget.setVisible(rule_type == RULE_MONTHLY)
        self.details_widget.setVisible(rule_type in (RULE_WEEKLY, RULE_MONTHLY))
        self.end_controls.setVisible(recurring)
        self.end_date.setVisible(recurring and end_type == "date")
        self.end_count.setVisible(recurring and end_type == "count")
        rule = self.rule()
        self.summary_label.setText(repeat_summary(rule) if recurring else "")
        next_dt = next_occurrence(self.due_input.datetime(), rule)
        if next_dt and not is_allowed(next_dt, rule, self.occurrence_number + 1):
            next_dt = None
        self.next_label.setText(f"다음 알림: {next_dt:%Y-%m-%d %H:%M}" if next_dt else "")
        self.summary_label.setVisible(bool(self.summary_label.text()))
        self.next_label.setVisible(bool(self.next_label.text()))
        self.changed.emit()

    def is_valid(self) -> bool:
        if not self.due_input.is_valid():
            return False
        rule = self.rule()
        if rule.rule_type == RULE_NONE:
            return True
        if rule.end_type == "date" and rule.end_date:
            return rule.end_date >= self.due_input.datetime().strftime("%Y%m%d")
        return rule.end_type != "count" or bool(rule.max_occurrences and rule.max_occurrences >= 1)
