"""Visual tokens and scalable Qt stylesheet for the shortcut launcher."""

import re


COLOR_TOKENS = {
    "@canvas": "#f5f7fb",
    "@panel": "#f7f9fc",
    "@surface": "#ffffff",
    "@surface-muted": "#f8fafc",
    "@ink": "#172033",
    "@muted": "#64748b",
    "@line": "#dce3ec",
    "@blue": "#4263eb",
    "@blue-dark": "#3451c7",
    "@blue-soft": "#eaf2ff",
    "@green": "#0f766e",
    "@green-soft": "#ecfdf5",
    "@red": "#b42318",
    "@red-soft": "#fff1f2",
    "@amber": "#92400e",
    "@amber-soft": "#fffbeb",
    "@title": "#0f172a",
}


BASE_STYLESHEET = """
QMainWindow { background: @canvas; }
QWidget { color: @ink; font-family: "Malgun Gothic"; font-size: 13px; }
QWidget#tablePanel, QWidget#formPanel { background: @panel; }
QWidget#tablePanel { border-right: 1px solid @line; }
QWidget#workspaceModeBar { background: @panel; border-bottom: 1px solid @line; }
QPushButton#workspaceModeButton {
    min-width: 0px; min-height: 36px; padding: 0 18px; background: @surface;
    border: 1px solid #cbd5e1; border-radius: 9px; color: #334155; font-weight: 700;
}
QPushButton#workspaceModeButton:hover { background: #f1f5f9; border-color: #94a3b8; }
QPushButton#workspaceModeButton:checked {
    background: @blue; border-color: @blue; color: white;
}
QFrame#workspaceSubnavSeparator {
    border: 0; border-left: 1px solid @line; background: transparent;
    max-width: 1px; min-width: 1px; margin: 6px 10px;
}
QPushButton#workspaceSubTabButton {
    min-width: 82px; min-height: 34px; padding: 0 10px; background: transparent;
    border: 1px solid transparent; border-radius: 8px; color: #334155; font-weight: 700;
}
QPushButton#workspaceSubTabButton:hover { background: #f1f5f9; border-color: #cbd5e1; }
QPushButton#workspaceSubTabButton:checked {
    background: #e7efff; border-color: #9eb8ff; color: @blue-dark;
}
QPushButton#calendarModeButton {
    min-width: 62px; padding: 0 14px; background: @surface; color: #334155;
    border: 1px solid @line; border-radius: 0; font-weight: 600;
}
QPushButton#calendarModeButton[segment="first"] {
    border-top-left-radius: 9px; border-bottom-left-radius: 9px;
}
QPushButton#calendarModeButton[segment="last"] {
    border-top-right-radius: 9px; border-bottom-right-radius: 9px;
}
QPushButton#calendarModeButton[segment="middle"] { border-left-width: 0; border-right-width: 0; }
QPushButton#calendarModeButton[segment="last"] { border-left-width: 0; }
QPushButton#calendarModeButton:hover { background: #f1f5f9; }
QPushButton#calendarModeButton:checked {
    background: @blue; border-color: @blue; color: white;
}
QPushButton#workspaceUtilityButton {
    min-height: 34px; padding: 0 9px; background: @surface; color: #334155;
    border: 1px solid #cbd5e1; border-radius: 8px;
}
QPushButton#workspaceUtilityButton:hover { background: #f1f5f9; border-color: #94a3b8; }
QPushButton#deadlineChip {
    min-height: 26px; padding: 2px 11px; border-radius: 999px; font-weight: 700;
    font-size: 12px; margin-left: 10px; border: 1px solid @line;
    background: @surface-muted; color: @muted;
}
QPushButton#deadlineChip[urgency="later"] { background: @surface-muted; color: @muted; }
QPushButton#deadlineChip[urgency="soon"] {
    background: @amber-soft; color: @amber; border-color: #e3bb72;
}
QPushButton#deadlineChip[urgency="today"], QPushButton#deadlineChip[urgency="past"] {
    background: @red-soft; color: @red; border-color: #f0a3a3;
}
QPushButton#deadlineChip:hover { border-color: @blue; }
QLabel#workspaceSwitchHint {
    background: @surface-muted; border: 1px solid @line; border-bottom-width: 2px;
    border-radius: 6px; color: @muted; font-weight: 500; padding: 3px 8px;
    margin-left: 10px;
}
QWidget#memoListPanel { background: @panel; border-right: 1px solid @line; }
QListWidget#memoList {
    background: @surface; border: 1px solid @line; border-radius: 10px;
    outline: 0; padding: 5px;
}
QListWidget#memoList::item {
    border: 1px solid #e2e8f0; border-radius: 9px; margin: 4px; padding: 8px 12px;
}
QListWidget#memoList::item:hover { background: #f1f6ff; border-color: #bfdbfe; }
QListWidget#memoList::item:selected { background: @blue-soft; border: 2px solid @blue; color: #173b6c; }
QListWidget#scheduleAgendaList {
    background: @surface; border: 1px solid @line; border-radius: 10px;
    outline: 0; padding: 5px;
}
QListWidget#scheduleAgendaList::item {
    min-height: 40px; border-left: 4px solid @blue; border-bottom: 1px solid #eef2f7;
    padding: 8px 12px; margin: 2px 3px;
}
QListWidget#scheduleAgendaList::item:hover { background: #f1f6ff; }
QListWidget#scheduleAgendaList::item:selected {
    background: @blue-soft; color: #173b6c; border-left-color: @blue-dark;
}
QCalendarWidget QWidget#qt_calendar_navigationbar { background: #eef4ff; }
QCalendarWidget QToolButton {
    min-height: 36px; background: transparent; border: 0; color: @title; font-weight: 700;
}
QCalendarWidget QAbstractItemView {
    background: @surface; selection-background-color: @blue; selection-color: white;
    alternate-background-color: #f8fafc; outline: 0;
}
QFrame#calendarNavigation {
    background: @surface; border: 1px solid @line; border-radius: 12px;
}
QPushButton#calendarNavButton {
    text-align: left; min-height: 40px; border-color: transparent; background: transparent;
}
QPushButton#calendarNavButton:hover { background: @blue-soft; color: @blue-dark; }
QPushButton#calendarNavButton:checked {
    background: @blue-soft; color: @blue-dark; font-weight: 700;
}
QLabel#calendarCategoryLabel { color: #475569; padding: 5px 8px; }
QFrame#scheduleDrawer {
    background: @surface; border: 1px solid @line; border-radius: 12px;
}
QFrame#scheduleAdditionalCard {
    background: #f8fafc; border: 1px solid @line; border-radius: 10px;
}
QFrame#scheduleSubCard { background: transparent; border: 0; }
/* 클릭한 자리에서 끝내는 일정 입력 팝오버. */
QFrame#schedulePopover {
    background: @surface; border: 1px solid #c7d2e4; border-radius: 14px;
}
QLabel#popoverHeading { font-size: 14px; font-weight: 700; color: @title; }
QLabel#popoverRange { color: @muted; }
QLabel#popoverFieldLabel { color: @muted; font-size: 12px; }
QLabel#popoverHint { color: @muted; font-size: 12px; }
QLabel#popoverParse {
    color: @green; background: @green-soft; border: 1px solid #a7f3d0;
    border-radius: 7px; padding: 4px 9px; font-size: 12px; font-weight: 600;
}
QLabel#popoverKeyHint {
    color: @muted; font-size: 11px; border: 1px solid @line;
    border-radius: 5px; padding: 2px 6px;
}
QFrame#popoverDivider { color: @line; }
/* 본문 스크롤 영역이 제 바탕을 칠하면 팝오버 가운데만 회색 띠가 생긴다. */
QFrame#schedulePopover QScrollArea { background: transparent; border: 0; }
QFrame#schedulePopover QScrollArea > QWidget > QWidget { background: transparent; }
/* 날짜·시각도 칩과 같은 말투로.  네이티브 스핀 상자는 이 폭에서 오른쪽을 넘긴다. */
QDateEdit#popoverDateField, QTimeEdit#popoverTimeField {
    background: @surface-muted; border: 1px solid @line; border-radius: 9px;
    min-height: 28px; padding: 2px 8px; color: @ink; font-weight: 600;
}
QDateEdit#popoverDateField:focus, QTimeEdit#popoverTimeField:focus {
    background: @surface; border: 1px solid @blue; padding: 2px 8px;
}
/* 스핀·달력 버튼은 네이티브 그대로 둔다.  QSS로 하위 컨트롤을 다시 그리면
   화살표 그림이 사라져 빈 상자만 남는다. */
QLineEdit#popoverTitleEdit {
    border: 0; border-bottom: 2px solid @line; border-radius: 0;
    padding: 6px 2px; font-size: 15px; background: transparent;
}
QLineEdit#popoverTitleEdit:focus { border-bottom: 2px solid @blue; }
QPushButton#popoverEscButton, QPushButton#popoverLinkButton {
    min-height: 26px; padding: 2px 8px; border: 0; background: transparent; color: @muted;
}
QPushButton#popoverEscButton:hover, QPushButton#popoverLinkButton:hover {
    color: @blue-dark; background: @blue-soft; border-radius: 6px;
}
QPushButton#popoverTimeChip {
    min-height: 26px; padding: 2px 10px; border-radius: 11px;
    background: @green-soft; border: 1px solid #a7f3d0; color: @green; font-weight: 700;
}
QPushButton#popoverTimeChip:checked { background: #d1fae5; border-color: @green; }
QPushButton#popoverDurationChip, QPushButton#popoverAddChip {
    min-height: 26px; padding: 2px 7px; border-radius: 11px;
    background: @surface-muted; border: 1px solid @line; color: #475569;
}
QPushButton#popoverAddChip:checked {
    background: @blue-soft; border-color: @blue; color: @blue-dark; font-weight: 700;
}
QLineEdit#quickScheduleInput {
    min-height: 42px; font-size: 17px; padding: 6px 12px; border-radius: 10px;
}
QLabel#quickScheduleTitle { font-size: 16px; font-weight: 700; color: @title; }
QLabel#quickScheduleTitle[empty="true"] { color: @muted; font-weight: 400; }
QLabel#quickScheduleFields { color: @muted; }
QLabel#quickScheduleConflict {
    color: @green; background: @green-soft; border: 1px solid #a7f3d0;
    border-radius: 7px; padding: 5px 10px; font-weight: 600;
}
QLabel#quickScheduleConflict[conflict="true"] {
    color: @amber; background: @amber-soft; border-color: #fcd34d;
}
QFrame#calendarMoveStatus {
    background: #172033; border-radius: 9px; color: white;
}
QFrame#calendarMoveStatus QLabel { color: white; font-weight: 600; }
QFrame#calendarMoveStatus QPushButton {
    min-height: 32px; background: #ffffff; color: #172033; border-color: #ffffff;
}
QTableWidget#scheduleTimeline, QTableWidget#scheduleMonthGrid {
    background: @surface; border: 1px solid @line; border-radius: 10px;
    gridline-color: transparent; outline: 0;
}
QTableWidget#scheduleTimeline::item { padding: 8px; }
QTableWidget#scheduleMonthGrid::item { padding: 9px; border: 2px solid @surface; }
QTableWidget#scheduleMonthGrid::item:selected {
    border: 2px solid @blue; background: @blue-soft; color: #173b6c;
}
QFrame#monthDayCell { background: @surface; border: 1px solid #edf1f5; }
QFrame#monthDayCell[outside="true"] QLabel#monthDayNumber { color: #a7b0bf; }
QFrame#monthDayCell[today="true"] QLabel#monthDayNumber {
    background: @blue; color: white; border-radius: 9px; padding: 1px 5px; font-weight: 700;
}
QFrame#monthDayCell[selected="true"] { border: 2px solid @blue; background: #fbfdff; }
QLabel#monthDayNumber { color: @ink; font-family: "Segoe UI", "Malgun Gothic"; }
QLabel#monthEventChip { min-height: 18px; border-radius: 5px; padding: 2px 5px; color: #234f9a; background: #e7f0ff; }
QLabel#monthEventChip[category="mint"] { color: #176448; background: #e4f8ee; }
QLabel#monthEventChip[category="peach"] { color: #9c3d37; background: #ffe9e7; }
QLabel#monthEventChip[category="vanilla"] { color: #815b10; background: #fff4d6; }
QLabel#monthEventChip[category="lavender"] { color: #6042a6; background: #f0eafe; }
QLabel#monthEventChip[completed="true"] { color: @muted; background: #f1f5f9; }
QLabel#monthMoreLabel { color: @blue-dark; font-weight: 700; padding-left: 4px; }
QLabel#monthDayNumber[weekday="sat"] { color: #2563eb; }
QLabel#monthDayNumber[weekday="sun"] { color: #dc2626; }
QLabel#monthEventChip[past="true"] { color: #94a3b8; }
QLabel#monthDeadlineChip {
    min-height: 18px; border: 1px solid #f0a3a3; border-radius: 5px;
    padding: 1px 5px; color: @red; background: transparent; font-weight: 700;
}
QTabWidget#scheduleSideTabs::pane {
    background: @surface; border: 1px solid #dce3eb; border-radius: 12px;
    top: -1px;
}
QLabel#memoEmptyState {
    background: @surface; border: 1px dashed #94a3b8; border-radius: 10px;
    color: @muted; padding: 18px;
}
QWidget#memoEmptyState {
    background: @surface; border: 1px dashed #94a3b8; border-radius: 10px;
}
QLabel#emptyStateTitle { color: @ink; font-weight: 700; font-size: 15px; }
QLabel#emptyStateHint { color: @muted; }
QPushButton#linkButton {
    background: transparent; border: 0; color: @blue; font-size: 12px;
    font-weight: 600; padding: 0 2px; min-height: 18px; min-width: 0;
}
QPushButton#linkButton:hover { color: @blue-dark; text-decoration: underline; }
QLabel#hotkeyConflictLabel { color: @red; font-size: 12px; padding: 0 2px; }
QFrame#memoSectionCard {
    background: @surface; border: 1px solid #dce3eb; border-radius: 10px; padding: 4px;
}
QWidget#memoEditorPane { background: @panel; }
QTextEdit#memoBodyEditor { background: @surface; min-height: 320px; }
QWidget#memoEditorRemainder { background: @panel; border-left: 1px solid @line; }
QLabel#summarySectionTitle {
    color: @muted; font-weight: 600; padding: 6px 2px 0 2px;
}
QListWidget#summaryList {
    background: @surface; border: 1px solid @line; border-radius: 10px;
    outline: 0; padding: 4px;
}
QListWidget#summaryList::item { padding: 6px 8px; border-radius: 6px; }
QListWidget#summaryList::item:selected { background: @blue-soft; color: @ink; }
QLabel#recurrenceStatus {
    background: @surface-muted; color: @muted; border-bottom: 1px solid @line;
    min-height: 18px; padding: 2px 5px;
}
QPushButton#memoColorButton { min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; padding: 0; }
/* A status readout, not a button: no border, so it stops reading as disabled. */
QLabel#memoStatus {
    background: transparent; border: 0; color: @muted; padding: 2px 4px;
}
QLabel#memoStatus[level="success"] { color: #166534; }
QTabWidget::pane { border: 0; background: @panel; }
/* 위쪽 작업공간 단추(36px, 글자에 맞춘 폭)와 같은 비율로.  120×40 은 위쪽
   단추보다 커서 아래위가 따로 놀았다. */
QTabBar::tab {
    min-width: 0px; min-height: 32px; padding: 0 18px;
    background: @surface; border: 1px solid #cbd5e1; color: #334155; font-weight: 700;
}
QTabBar::tab:first { border-top-left-radius: 9px; border-bottom-left-radius: 9px; }
QTabBar::tab:last { border-top-right-radius: 9px; border-bottom-right-radius: 9px; }
QTabBar::tab:selected { background: @blue; border-color: @blue; color: white; }
QDateEdit[invalid="true"], QTimeEdit[invalid="true"] { border: 2px solid @red; background: @red-soft; }
QLabel#reminderSummary {
    background: transparent; border: 0;
    color: @blue-dark; font-weight: 700; padding: 0 2px;
}
QLabel#reminderSummary[invalid="true"] { color: @red; }
QToolButton#memoHotkeyToggle { border: 0; background: transparent; font-weight: 700; text-align: left; padding: 2px; }
QToolButton#memoHotkeyToggle:hover { background: @surface-muted; }
QToolButton#memoReminderToggle { border: 0; background: transparent; font-weight: 700; text-align: left; padding: 2px; }
QToolButton#memoReminderToggle:hover { background: @surface-muted; }
QLabel#secondaryText { color: @muted; font-size: 12px; }
QLabel#pageTitle { font-size: 20px; font-weight: 700; color: @title; }
QLabel#sectionTitle { font-size: 14px; font-weight: 700; color: @ink; }
QLabel#journeyCardTitle { font-size: 18px; font-weight: 700; color: @title; padding: 2px 0 6px 0; }
QLabel#mutedLabel, QLabel#workspaceSubtitle { color: @muted; font-size: 12px; }
QLabel#deadlineBadge {
    background: #172033; color: white; border-radius: 8px; padding: 4px 8px;
    font-size: 12px; font-weight: 700;
}
QLabel#workspaceSubtitle { padding-top: 1px; }
/* 등록에 실패한 것이 있을 때만 뜨는 한 줄. */
QLabel#registrationNotice {
    background: #fff8e1; border: 1px solid #f4d58a; border-radius: 9px;
    color: #815B10; font-size: 12px; font-weight: 700; padding: 4px 10px;
}
QLabel#recordingBadge {
    background: @surface-muted; border: 1px solid #cbd5e1; border-radius: 10px;
    color: #475569; font-weight: 700; padding: 5px 10px;
}
QLabel#recordingBadge[recording="true"] {
    background: @red-soft; border-color: #fda4af; color: #be123c;
}
QLabel#hotkeyChip {
    background: @surface; border: 1px solid #dbe3ec; border-radius: 7px;
    color: #334155; padding: 5px 8px;
}
QFrame#recordingDeck {
    background: @surface-muted; border: 1px solid #dbe3ec; border-radius: 12px;
}
QFrame#recordingDeck[recording="true"] {
    background: #fff7f7; border-color: #fda4af;
}
QFrame#hotkeyBar {
    background: #f1f5f9; border: 1px solid #dbe3ec; border-radius: 10px;
}
QLabel#macroSummary {
    background: @surface-muted; border: 1px solid #dbe3ec; border-radius: 8px;
    color: #475569; padding: 9px 11px;
}
QLabel#macroSummary[valid="false"] {
    background: @red-soft; border-color: #fecaca; color: @red;
}
QPushButton#speedResetButton {
    background: @blue-soft; border: 1px solid #bfdbfe; border-radius: 7px;
    color: @blue-dark; font-weight: 700; padding: 5px 8px;
}
QPushButton#speedResetButton:hover { background: #dbeafe; border-color: #60a5fa; }
QLabel#infoCard {
    background: #eef6ff; border: 1px solid #bfdbfe; border-radius: 9px;
    color: #1e3a5f; padding: 12px;
}
QPushButton#helpDisclosureButton {
    background: transparent; border: 0; color: #475569; font-weight: 600;
    text-align: left; padding: 5px 2px;
}
QPushButton#helpDisclosureButton:hover { color: @blue-dark; background: transparent; }
QFrame#helpDisclosurePanel {
    background: @surface-muted; border: 1px solid #e2e8f0; border-radius: 8px;
    color: #475569;
}
QGroupBox#macroSectionCard {
    background: @surface; border: 1px solid #d6dee8; border-radius: 12px;
    margin-top: 15px; font-size: 15px; font-weight: 700;
}
QGroupBox#macroSectionCard::title {
    subcontrol-origin: margin; left: 14px; padding: 0 6px; color: @ink;
}
QFrame#repeatControls { background: transparent; border: 0; }
QLabel#repeatLabel { color: #334155; font-weight: 700; }
QSpinBox#repeatCountSpin {
    min-width: 88px; max-width: 116px; font-weight: 700; color: @ink;
}
QLabel#statusLabel {
    background: @surface-muted; border: 1px solid #dbe3ec; border-radius: 8px;
    color: #475569; padding: 9px 11px;
}
QLabel#statusLabel[level="success"] {
    background: @green-soft; border-color: #86efac; color: #166534;
}
QLabel#statusLabel[level="warning"] {
    background: @amber-soft; border-color: #fcd34d; color: @amber;
}
QLabel#statusLabel[level="error"] {
    background: #fef2f2; border-color: #fca5a5; color: #b91c1c;
}
QLabel#emptySearch {
    background: @surface; border: 1px dashed #94a3b8; border-radius: 10px;
    color: @muted; padding: 14px;
}
QLabel#helpHero {
    background: @blue-soft; border: 1px solid #93c5fd; border-radius: 12px;
    color: #173b6c; padding: 18px; font-size: 16px; font-weight: 700;
}
QLabel#helpStep { font-size: 15px; font-weight: 700; color: @blue-dark; }
QFrame#helpCard, QFrame#editorCard {
    background: @surface; border: 1px solid #dce3eb; border-radius: 12px;
}
QFrame#settingsDialogCard {
    background: @surface; border: 1px solid #dce3eb; border-radius: 12px;
}
QLabel#settingsPathTitle { color: #334155; font-weight: 700; }
QLabel#settingsPath {
    background: @surface-muted; border: 1px solid #dbe3ec; border-radius: 7px;
    color: @muted; padding: 8px 10px;
}
QGroupBox#settingsCard {
    background: @surface; border: 1px solid #d6dee8; border-radius: 12px;
    margin-top: 15px; font-size: 15px; font-weight: 700;
}
QGroupBox#settingsCard::title {
    subcontrol-origin: margin; left: 14px; padding: 0 6px; color: @ink;
}
QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox, QSpinBox, QDateTimeEdit, QDateEdit, QTimeEdit {
    background: @surface; border: 1px solid #cbd5e1; border-radius: 7px;
    min-height: 30px; padding: 5px 9px; selection-background-color: @blue;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QDateTimeEdit:focus, QDateEdit:focus, QTimeEdit:focus {
    border: 2px solid #3b82f6; padding: 4px 8px;
}
/* 설정창 단축키 줄은 열 줄이 늘어서므로 한 줄을 낮게 잡는다. */
QWidget#settingsHotkeyBuilder QComboBox, QWidget#settingsHotkeyBuilder QLineEdit {
    min-height: 24px; padding: 3px 8px;
}
QWidget#settingsHotkeyBuilder QComboBox:focus, QWidget#settingsHotkeyBuilder QLineEdit:focus {
    min-height: 24px; padding: 2px 7px;
}
QLineEdit#compactEditorInput, QComboBox#compactEditorInput {
    min-height: 24px; padding: 3px 7px;
}
QLineEdit#compactEditorInput:focus, QComboBox#compactEditorInput:focus {
    min-height: 24px; padding: 2px 6px;
}
QTextEdit#macroEditor {
    background: #fbfcfe; font-family: Consolas, "D2Coding"; font-size: 12px;
}
QPushButton {
    min-height: 34px; background: @surface; border: 1px solid #cbd5e1;
    border-radius: 7px; padding: 3px 12px;
}
QPushButton:hover { background: #f1f5f9; border-color: #94a3b8; }
QPushButton:pressed { background: #e2e8f0; padding-top: 4px; padding-bottom: 2px; }
QPushButton#primaryButton {
    background: @blue; border-color: @blue; color: white; font-weight: 700;
}
QPushButton#primaryButton:hover { background: @blue-dark; }
QPushButton#toolbarButton { background: @surface-muted; color: #334155; }
/* A disabled button has to look disabled, or "no target selected" is invisible. */
QPushButton:disabled { background: #f1f5f9; border-color: #e2e8f0; color: #94a3b8; }
QPushButton#primaryButton:disabled {
    background: #cbd5e1; border-color: #cbd5e1; color: #f8fafc;
}
QPushButton#dangerButton:disabled { background: #f8fafc; border-color: #e2e8f0; color: #b6bfcb; }
QPushButton#compactUtilityButton {
    min-height: 28px; padding: 2px 9px; background: @surface-muted; color: #334155;
}
QPushButton#dangerButton { color: @red; border-color: #fecaca; background: #fffafa; }
QPushButton#dangerButton:hover { background: @red-soft; border-color: #fda4af; }
QPushButton#recordButton {
    background: @blue-soft; border: 1px solid #60a5fa; color: @blue-dark;
    font-size: 14px; font-weight: 700;
}
QPushButton#stopButton {
    background: @red-soft; border: 1px solid #fda4af; color: @red;
    font-size: 14px; font-weight: 700;
}
QPushButton#testButton {
    background: @green-soft; border: 1px solid #5eead4; color: @green;
    font-weight: 700;
}
QPushButton:disabled { background: #f3f4f6; border-color: #e5e7eb; color: #a3aab5; }
QTableWidget {
    background: @surface; alternate-background-color: #f8fbff;
    border: 1px solid @line; border-radius: 10px; gridline-color: #edf1f5;
}
QTableWidget::item { padding: 7px; }
QTableWidget::item:hover { background: #f1f6ff; }
QTableWidget::item:selected { background: #dfeaff; color: #173b6c; }
/* 메모 목록은 표가 아니라 트리다.  위 규칙이 걸리지 않아 Qt 기본 선택색(짙은
   청록)이 그대로 나왔다.  같은 옅은 파랑으로 맞춘다.
   펼침 화살표 자리(::branch)에는 손대지 않는다 — 배경을 주는 순간 Qt 가
   화살표 그림을 통째로 지운다. */
QTreeWidget#memoListTable {
    background: @surface; alternate-background-color: #f8fbff;
    border: 1px solid @line; border-radius: 10px;
}
QTreeWidget#memoListTable::item { padding: 4px; border: 0; }
/* 목록 칸의 단추와 검색칸은 낮게.  기본 min-height 는 setFixedHeight 보다
   세므로, 여기서 풀어 주지 않으면 위쪽 여백이 그대로 남는다. */
QWidget#memoListPanel QPushButton, QWidget#memoListPanel QLineEdit,
QWidget#memoListPanel QComboBox {
    min-height: 0px; padding: 2px 10px;
}
QPushButton#memoCategoryFilterChip:checked,
QPushButton#memoTitleSymbolFilter:checked,
QPushButton#memoMoreCategoriesButton:checked {
    background: #dbeafe; border-color: #3b82f6; color: #173b6c;
}
QLabel#selectedMemoCountChip {
    background: #e8efff; border: 1px solid #bfd0f5; border-radius: 10px;
    color: #294f94; font-weight: 600; padding: 2px 9px;
}
QLabel#memoListTitle { font-size: 15px; font-weight: 700; color: @title; }
/* 최근 본 메모 칩.  목록의 한 줄이 아니라 눌러서 옮겨 가는 단추로 보이게 한다. */
QPushButton#recentNoteChip {
    background: #eef3fe; color: #35507f; border: 1px solid #d3e0f7;
    border-radius: 11px; padding: 1px 10px; font-size: 12px;
}
QPushButton#recentNoteChip:hover { background: #e0eaff; border-color: #b9cdf0; }
QPushButton#recentNoteChip:pressed { background: #d2e0fb; }
/* 본문 찾기 줄.  본문 바로 아래에 얇게 붙는다. */
QWidget#memoFindBar {
    background: #f4f7fd; border: 1px solid #dbe4f3; border-radius: 8px;
}
QWidget#memoFindBar QLineEdit { min-height: 0px; padding: 3px 8px; }
QPushButton#findBarButton {
    min-height: 0px; min-width: 0px; padding: 2px 0px;
    background: transparent; border: 1px solid transparent;
    border-radius: 6px; color: #45526b; font-size: 12px;
}
QPushButton#findBarButton:hover { background: #e3ebfa; border-color: #ccd9ef; }
QLabel#memoFindCount { color: #5a6679; font-size: 12px; }
QLabel#memoFindCount[empty="true"] { color: #b4442f; }
QTreeWidget#memoListTable::item:hover { background: #f1f6ff; }
QTreeWidget#memoListTable::item:selected { background: #dfeaff; color: #173b6c; }
/* 편집창 맨 위의 위치 표시줄.  제목보다 조용해야 한다. */
QLabel#memoBreadcrumb { color: #64748b; font-size: 12px; padding: 1px 2px; }
QHeaderView::section {
    background: #f1f5f9; color: #334155; border: 0;
    border-right: 1px solid #e2e8f0; border-bottom: 1px solid @line;
    padding: 9px 5px; font-weight: 700;
}
QRadioButton, QCheckBox { spacing: 7px; min-height: 24px; }
QSlider::groove:horizontal { height: 5px; background: #dbe3ec; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @blue; border-radius: 2px; }
QSlider::handle:horizontal {
    background: @surface; border: 2px solid @blue; width: 16px;
    margin: -6px 0; border-radius: 8px;
}
QSplitter::handle { background: #d8dee8; width: 3px; height: 3px; }
QSplitter#memoEditorSplitter::handle:horizontal {
    width: 7px; background: #cbd5e1; border-left: 1px solid #f8fafc; border-right: 1px solid #94a3b8;
}
QSplitter#memoEditorSplitter::handle:horizontal:hover,
QSplitter#memoEditorSplitter::handle:horizontal:pressed { background: #93c5fd; }
#memoEditorPane QLineEdit, #memoEditorPane QComboBox, #memoEditorPane QSpinBox,
#memoEditorPane QDateEdit, #memoEditorPane QTimeEdit {
    min-height: 24px; max-height: 24px; padding: 3px 7px;
}
#memoEditorPane QPushButton, #memoEditorPane QToolButton {
    min-height: 28px; max-height: 32px; padding: 4px 9px;
}
/* 서식 두 번째 줄.  단추마다 테두리를 두르면 무엇이 중요한지 알 수 없고 줄이
   둘로 늘어난다.  테두리를 걷고 묶음만 가는 세로선으로 나눈다. */
QPushButton#formatToggleButton, QPushButton#formatInsertButton,
QPushButton#formatToolButton, QPushButton#formatTextButton {
    background: transparent; border: 0; border-radius: 6px; color: #334155;
}
/* 서식의 min-* 는 setFixedSize 로 잡은 최소 크기를 지운다.  크기는 여기서
   한 번에 정한다.  그러지 않으면 단추가 글자 폭까지 쪼그라든다. */
QPushButton#formatToggleButton, QPushButton#formatInsertButton,
QPushButton#formatToolButton {
    min-width: 28px; min-height: 28px; padding: 0;
}
QPushButton#formatToggleButton { font-weight: 700; }
QPushButton#formatToggleButton:hover, QPushButton#formatInsertButton:hover,
QPushButton#formatToolButton:hover, QPushButton#formatTextButton:hover {
    background: #f1f5f9;
}
QPushButton#formatToggleButton:pressed, QPushButton#formatInsertButton:pressed,
QPushButton#formatToolButton:pressed, QPushButton#formatTextButton:pressed {
    background: #e2e8f0;
}
/* 켜져 있는 서식은 옅은 파랑으로.  네모 단추를 통째로 파랗게 칠하면 두 줄짜리
   단추 벽이 다시 생긴다. */
QPushButton#formatToggleButton:checked {
    background: #e7efff; color: @blue-dark;
}
QToolButton#formatPresetSample:checked {
    background: #e7efff; border: 1px solid @blue; color: @blue-dark;
}
QPushButton#formatTextButton { font-weight: 500; padding: 0 11px; min-height: 28px; }
QFrame#formatGroupLine {
    border: 0; border-left: 1px solid #e8edf4; background: transparent;
    max-width: 1px; min-width: 1px; margin: 5px 4px;
}
/* 기능 펼침 단추.  켜짐/꺼짐이 없는 동작이라 눌린 표시를 남기지 않는다. */
QPushButton#formatInsertButton::menu-indicator { image: none; width: 0px; }
QToolButton#postitFormatButton::menu-indicator { image: none; width: 0px; }
QWidget#insertPreferencesPanel { background: @surface; color: @text; }
QTabWidget#insertPreferencesTabs::pane {
    border: 1px solid #dbe3ef; border-radius: 8px; background: @surface;
}
QTabWidget#insertPreferencesTabs QTabBar::tab {
    min-width: 72px; min-height: 30px; padding: 2px 10px;
}
QLabel#insertPanelHint { color: #64748b; font-size: 11px; }
QLabel#insertPanelError { color: #b91c1c; font-weight: 600; }
QLineEdit[invalid="true"] { border: 2px solid #dc2626; background: #fff7f7; }
QListWidget#insertFeatureList::item { min-height: 30px; padding: 2px 6px; }
QListWidget#insertFeatureList::item:selected { background: #e7efff; color: @blue-dark; }
QToolButton#formatPresetSample {
    min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;
    background: @surface; border: 1px solid #cbd5e1; border-radius: 5px;
    color: #334155; padding: 0;
}
QToolButton#formatPresetSample:hover { background: #f1f5f9; border-color: #94a3b8; }
QToolButton#formatPresetSample::menu-indicator { image: none; width: 0; }
QToolButton#formatPresetSettings {
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
    background: transparent; border: 0; border-radius: 6px; color: #334155; padding: 0;
}
QToolButton#formatPresetSettings:hover { background: #f1f5f9; }
QToolButton#formatPresetSettings:pressed { background: #e2e8f0; }
QToolButton#formatPresetSettings::menu-indicator { image: none; width: 0; }
QPushButton#textColorPickerButton {
    min-width: 30px; max-width: 30px; padding: 1px; border-radius: 7px;
}
QPushButton#quickTextColorButton {
    min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; padding: 0;
}
QMenu#textColorPalette { padding: 0; }
QToolButton#textColorPaletteSwatch {
    min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; padding: 0;
}
QPushButton#recurrenceRuleButton {
    min-width: 0; padding: 2px 8px; font-size: 11px; border-radius: 0;
    background: @surface; color: #334155;
}
QPushButton#recurrenceRuleButton[segmentPosition="first"] { border-top-left-radius: 7px; border-bottom-left-radius: 7px; }
QPushButton#recurrenceRuleButton[segmentPosition="middle"],
QPushButton#recurrenceRuleButton[segmentPosition="last"] { border-left: 0; }
QPushButton#recurrenceRuleButton[segmentPosition="last"] { border-top-right-radius: 7px; border-bottom-right-radius: 7px; }
QPushButton#recurrenceRuleButton:checked {
    background: @blue; border-color: @blue; color: white; font-weight: 700;
}
QPushButton#quickReminderButton {
    min-height: 34px; max-height: 38px; padding: 1px 4px; font-size: 11px; line-height: 13px;
}
#memoEditorPane QSpinBox, #memoEditorPane QTimeEdit { padding-right: 23px; }
#memoEditorPane QSpinBox::up-button, #memoEditorPane QTimeEdit::up-button {
    subcontrol-origin: border; subcontrol-position: top right; width: 19px;
    border-left: 1px solid #cbd5e1; border-bottom: 1px solid #cbd5e1; border-top-right-radius: 6px;
}
#memoEditorPane QSpinBox::down-button, #memoEditorPane QTimeEdit::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right; width: 19px;
    border-left: 1px solid #cbd5e1; border-bottom-right-radius: 6px;
}
#memoEditorPane QSpinBox::up-button:hover, #memoEditorPane QSpinBox::down-button:hover,
#memoEditorPane QTimeEdit::up-button:hover, #memoEditorPane QTimeEdit::down-button:hover { background: #e2e8f0; }
QScrollArea { border: 0; background: @panel; }
QScrollArea > QWidget > QWidget { background: @panel; }
QFrame#customTitleBar { background: @title; border-bottom: 1px solid #1e293b; }
QLabel#titleBarIcon { font-size: 15px; padding-right: 7px; }
QLabel#titleBarText { color: #e2e8f0; font-size: 12px; font-weight: 700; }
QPushButton#windowControlButton, QPushButton#closeWindowButton {
    min-width: 46px; max-width: 46px; min-height: 34px; max-height: 34px;
    border: 0; border-radius: 0; padding: 0; background: transparent;
    color: #e2e8f0; font-size: 16px;
}
QPushButton#windowControlButton:hover { background: #1e293b; }
QPushButton#closeWindowButton:hover { background: #dc2626; color: white; }

QFrame#suggestionBar {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
}
QLabel#suggestionText {
    color: #1e3a5f;
    font-size: 12px;
}
QToolButton#suggestionClose {
    border: none;
    background: transparent;
    color: #64748b;
    padding: 0 4px;
    font-size: 13px;
}
QToolButton#suggestionClose:hover {
    color: #1e3a5f;
}
QFrame#suggestionBar QPushButton {
    padding: 4px 10px;
    font-size: 12px;
}
"""


def _resolve_tokens(stylesheet: str) -> str:
    for name in sorted(COLOR_TOKENS, key=len, reverse=True):
        stylesheet = stylesheet.replace(name, COLOR_TOKENS[name])
    return stylesheet


APP_STYLESHEET = _resolve_tokens(BASE_STYLESHEET)


def scaled_stylesheet(scale: float) -> str:
    """Scale every pixel-based metric in the application stylesheet."""

    def replace(match) -> str:
        value = max(1, round(float(match.group(1)) * scale))
        return f"{value}px"

    return re.sub(r"(\d+(?:\.\d+)?)px", replace, APP_STYLESHEET)
