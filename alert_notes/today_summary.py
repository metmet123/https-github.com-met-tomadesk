"""Right-hand summary that fills the space beside the memo editor.

The pane used to be an empty spacer widget, so widening the window only grew a
blank grey column.  It now answers the two questions the memo screen could not:
what is on today's calendar, and which reminders fire next.
"""

from datetime import date, datetime, time

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QStyle, QStyleOptionViewItem, QToolButton, QVBoxLayout,
    QWidget,
)

from .deadline import (
    deadline_chip_text, deadline_days_left, deadline_title, deadline_urgency,
)
from .monthly_rule import describe
from .reminder_choice_dialog import display_due
from .sqlite_store import DATETIME_FMT

TODAY_LIMIT = 3
REMINDER_LIMIT = 8
DEADLINE_LIMIT = 8
# Distance read as colour: far is quiet, this week warms up, today is loud.
URGENCY_COLORS = {
    "today": QColor("#b42318"),
    "past": QColor("#b42318"),
    "soon": QColor("#92400e"),
    "later": QColor("#475569"),
    "done": QColor("#94a3b8"),
}


class SummaryList(QListWidget):
    """한 번 누르면 바로 열리는 요약 목록.

    두 번 눌러야 열리는 규칙은 이 칸에서는 손해였다.  이미 무엇을 열지
    아는 줄들이라 한 번이면 충분하다.  다만 D-Day 줄 왼쪽의 체크칸은
    남은 날짜 세기를 멈추는 자리이므로, 그 자리만은 열지 않는다.
    """

    chosen = pyqtSignal(int)

    def mouseReleaseEvent(self, event) -> None:
        # 체크칸을 누르면 목록을 통째로 다시 그리므로 item 이 사라진다.
        # 눌린 줄의 번호를 먼저 챙겨 두고 나서 기본 동작을 부른다.
        target = None
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            item = self.itemAt(point)
            if item is not None and not self.check_box_rect(item).contains(point):
                value = item.data(Qt.ItemDataRole.UserRole)
                target = None if value is None else int(value)
        super().mouseReleaseEvent(event)
        if target is not None:
            self.chosen.emit(target)

    def check_box_rect(self, item: QListWidgetItem) -> QRect:
        """체크칸이 차지한 자리.  체크칸이 없는 줄이면 빈 자리를 준다."""
        if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            return QRect()
        row = self.visualItemRect(item)
        option = QStyleOptionViewItem()
        try:
            self.initViewItemOption(option)
        except (AttributeError, TypeError):  # Qt 판에 따라 없을 수 있다
            pass
        option.rect = row
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        box = self.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, self
        )
        if box.isEmpty():
            # 스타일이 답을 못 주면 줄 왼쪽 끝을 체크칸으로 본다.
            box = QRect(row.left(), row.top(), 24, row.height())
        return box


class TodaySummaryPanel(QWidget):
    note_open_requested = pyqtSignal(int)
    schedule_open_requested = pyqtSignal(int)
    deadline_changed = pyqtSignal()
    monthly_suggestion_accepted = pyqtSignal(dict)
    monthly_suggestion_dismissed = pyqtSignal(str)

    def __init__(self, store, parent=None, show_reminders: bool = True):
        super().__init__(parent)
        self.store = store
        self._shutdown = False
        self._headings: dict[str, QLabel] = {}
        self._sections: list = []
        self.setObjectName("memoSummaryPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        # 여백이 목록보다 넓어 패널의 절반이 빈칸이었다.  간격을 좁혀
        # 실제로 읽는 부분에 자리를 돌려준다.
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(4)
        self._body_layout = layout

        self.date_label = QLabel()
        self.date_label.setObjectName("pageTitle")
        layout.addWidget(self.date_label)

        # Offered, never applied: the program spots a repeat the user keeps
        # making by hand and asks once.  Dismissing it is permanent.
        self._suggestion = None
        self.suggestion_bar = QFrame()
        self.suggestion_bar.setObjectName("suggestionBar")
        self.suggestion_bar.setVisible(False)
        bar = QVBoxLayout(self.suggestion_bar)
        bar.setContentsMargins(12, 10, 10, 10)
        bar.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.suggestion_label = QLabel()
        self.suggestion_label.setObjectName("suggestionText")
        self.suggestion_label.setWordWrap(True)
        top.addWidget(self.suggestion_label, 1)
        self.suggestion_close = QToolButton()
        self.suggestion_close.setText("✕")
        self.suggestion_close.setObjectName("suggestionClose")
        self.suggestion_close.setToolTip("이 제안 숨기기")
        self.suggestion_close.setAccessibleName("반복 제안 숨기기")
        self.suggestion_close.clicked.connect(self._dismiss_suggestion)
        top.addWidget(self.suggestion_close, 0, Qt.AlignmentFlag.AlignTop)
        bar.addLayout(top)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addStretch()
        self.suggestion_skip = QPushButton("괜찮아요")
        self.suggestion_skip.clicked.connect(self._dismiss_suggestion)
        buttons.addWidget(self.suggestion_skip)
        self.suggestion_accept = QPushButton("포스트잇 만들기")
        self.suggestion_accept.setObjectName("primaryButton")
        self.suggestion_accept.setDefault(True)
        self.suggestion_accept.clicked.connect(self._accept_suggestion)
        buttons.addWidget(self.suggestion_accept)
        bar.addLayout(buttons)
        layout.addWidget(self.suggestion_bar)

        self.past_deadline_header = QFrame()
        self.past_deadline_header.setObjectName("scheduleSubCard")
        past_header_layout = QHBoxLayout(self.past_deadline_header)
        past_header_layout.setContentsMargins(6, 3, 4, 3)
        past_header_layout.setSpacing(6)
        self.past_deadline_toggle = QToolButton()
        self.past_deadline_toggle.setObjectName("helpDisclosureButton")
        self.past_deadline_toggle.setCheckable(True)
        self.past_deadline_toggle.setChecked(
            self._option("past_deadlines_expanded", False)
        )
        self.past_deadline_toggle.setAccessibleName("지난 D-Day 펼치기")
        self.past_deadline_toggle.toggled.connect(self._toggle_past_deadlines)
        past_header_layout.addWidget(self.past_deadline_toggle, 1)
        self.complete_past_deadlines_button = QPushButton("전체 완료")
        self.complete_past_deadlines_button.setAccessibleName("지난 D-Day 전체 완료")
        self.complete_past_deadlines_button.clicked.connect(self._complete_past_deadlines)
        past_header_layout.addWidget(self.complete_past_deadlines_button)
        layout.addWidget(self.past_deadline_header)
        self.past_deadline_list = SummaryList()
        self.past_deadline_list.setObjectName("summaryList")
        self.past_deadline_list.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.past_deadline_list.setFrameShape(QFrame.Shape.NoFrame)
        self.past_deadline_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.past_deadline_list.setWordWrap(True)
        self.past_deadline_list.itemChanged.connect(self._deadline_toggled)
        self.past_deadline_list.chosen.connect(self.note_open_requested)
        layout.addWidget(self.past_deadline_list, 1)
        self._sections.append(self.past_deadline_list)
        self._past_deadline_ids: list[int] = []

        # D-Day sits above today's schedule: it is the thing you must not forget,
        # and a passed one stays here until the user ends the count themselves.
        self.deadline_list = self._section(layout, "D-Day")
        self.deadline_list.itemChanged.connect(self._deadline_toggled)
        self.deadline_list.itemActivated.connect(self._open_note)
        self.deadline_list.chosen.connect(self.note_open_requested)

        self.schedule_list = self._section(layout, "오늘 일정")
        self.schedule_list.itemActivated.connect(self._open_schedule)
        self.schedule_list.chosen.connect(self.schedule_open_requested)

        self.reminder_list = self._section(layout, "예정 알림")
        self.reminder_list.itemActivated.connect(self._open_note)
        self.reminder_list.chosen.connect(self.note_open_requested)
        # The shortcut tab wants the two deadline sections only; hiding the
        # heading with the list keeps the pane from ending in a stray title.
        self._show_reminders = bool(show_reminders)
        if not self._show_reminders:
            self.reminder_list.hide()
            self._headings["예정 알림"].hide()

        layout.addStretch()
        self.refresh()

    def set_suggestion(self, suggestion: dict | None) -> None:
        """Show one repeat worth turning into a monthly postit, or hide the bar."""
        self._suggestion = suggestion or None
        if self._suggestion is None:
            self.suggestion_bar.setVisible(False)
            return
        title = str(self._suggestion.get("title") or "")
        months = int(self._suggestion.get("months") or 0)
        when = describe(self._suggestion.get("rule"))
        self.suggestion_label.setText(
            f"‘{title}’을(를) {months}개월째 {when}에 하고 계세요.\n"
            "매달 체크리스트 포스트잇으로 띄울까요?"
        )
        self.suggestion_bar.setVisible(True)

    def _accept_suggestion(self) -> None:
        suggestion = self._suggestion
        if suggestion is None:
            return
        self.set_suggestion(None)
        self.monthly_suggestion_accepted.emit(dict(suggestion))

    def _dismiss_suggestion(self) -> None:
        suggestion = self._suggestion
        if suggestion is None:
            return
        self.set_suggestion(None)
        self.monthly_suggestion_dismissed.emit(str(suggestion.get("title") or ""))

    def _section(self, layout: QVBoxLayout, title: str) -> SummaryList:
        heading = QLabel(title)
        heading.setObjectName("summarySectionTitle")
        layout.addWidget(heading)
        self._headings[title] = heading
        widget = SummaryList()
        widget.setObjectName("summaryList")
        # 한 번 누르면 열리는 목록이니 손 모양으로 미리 알린다.
        widget.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        widget.setFrameShape(QFrame.Shape.NoFrame)
        widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setWordWrap(True)
        widget.setSpacing(0)
        widget.setUniformItemSizes(False)
        heading.setContentsMargins(2, 4, 0, 0)
        layout.addWidget(widget, 1)
        self._sections.append(widget)
        return widget

    def shutdown(self) -> None:
        """Stop querying once the owning panel is tearing its store down."""
        self._shutdown = True

    def refresh(self) -> None:
        if self._shutdown:
            return
        today = date.today()
        self.date_label.setText(f"{today:%m월 %d일} 요약")
        self._fill_deadlines()
        self._fill_schedules(today)
        self._fill_reminders()
        self._rebalance()

    # 빈 구역도 가득 찬 구역과 같은 높이를 차지해서, D-Day 가 다섯 건이어도
    # 세 칸으로 잘려 보였다.  가진 줄 수만큼만 가져가게 한다.
    ROW_HEIGHT = 26
    LIST_CHROME = 8

    def _rebalance(self) -> None:
        layout = getattr(self, "_body_layout", None)
        if layout is None:
            return
        for widget in self._sections:
            if widget.isHidden():
                continue
            rows = max(1, widget.count())
            # 줄 높이는 글꼴·여백에 따라 달라지므로 상수로 두면 몇 px 이 모자라
            # 다 들어가는데도 스크롤막대가 생긴다.  위젯에게 직접 묻는다.
            row_height = self.ROW_HEIGHT
            if widget.count():
                measured = widget.sizeHintForRow(0)
                if measured > 0:
                    row_height = measured
            chrome = 2 * widget.frameWidth() + self.LIST_CHROME
            wanted = rows * row_height + chrome
            widget.setMinimumHeight(row_height + chrome)
            widget.setMaximumHeight(wanted)
            index = layout.indexOf(widget)
            if index >= 0:
                # 넘칠 때만 쓰이는 비율 — 줄이 많은 쪽이 더 많이 갖는다.
                layout.setStretch(index, rows)

    def _option(self, key: str, default: bool) -> bool:
        try:
            return str(self.store.setting(key, "true" if default else "false")).lower() == "true"
        except Exception:
            return default

    def _fill_deadlines(self) -> None:
        """Closest first, finished ones last — nothing is ever dropped."""
        self.past_deadline_list.blockSignals(True)
        self.past_deadline_list.clear()
        self.deadline_list.blockSignals(True)
        self.deadline_list.clear()
        try:
            rows = self.store.deadline_notes()
        except Exception:
            rows = []
        past_rows = [row for row in rows if deadline_urgency(row) == "past"]
        rows = [row for row in rows if deadline_urgency(row) != "past"]
        self._past_deadline_ids = [int(row["id"]) for row in past_rows]
        self.past_deadline_header.setVisible(bool(past_rows))
        expanded = bool(past_rows) and self.past_deadline_toggle.isChecked()
        self.past_deadline_list.setVisible(expanded)
        self.past_deadline_toggle.setText(
            f"{'▾' if expanded else '▸'}  지난 D-Day {len(past_rows)}건"
        )
        self.past_deadline_toggle.setAccessibleName(
            f"지난 D-Day {len(past_rows)}건 {'접기' if expanded else '펼치기'}"
        )
        for row in past_rows[:DEADLINE_LIMIT]:
            self._add_deadline_entry(self.past_deadline_list, row)
        if len(past_rows) > DEADLINE_LIMIT:
            self._add_placeholder(
                self.past_deadline_list, f"외 {len(past_rows) - DEADLINE_LIMIT}건"
            )
        self.past_deadline_list.blockSignals(False)
        if not rows:
            self._add_placeholder(self.deadline_list, "오늘 또는 앞으로의 D-Day가 없습니다.")
            self.deadline_list.blockSignals(False)
            return
        if self._option("deadline_hide_finished", False):
            rows = [row for row in rows if deadline_urgency(row) != "done"]
            if not rows:
                self._add_placeholder(self.deadline_list, "진행 중인 D-Day가 없습니다.")
                self.deadline_list.blockSignals(False)
                return
        order = {"today": 0, "past": 1, "soon": 2, "later": 3, "done": 4}
        rows = sorted(
            rows,
            key=lambda row: (
                order.get(deadline_urgency(row), 5),
                abs(deadline_days_left(str(row["d_day_at"] or "")) or 0),
            ),
        )
        for row in rows[:DEADLINE_LIMIT]:
            self._add_deadline_entry(self.deadline_list, row)
        if len(rows) > DEADLINE_LIMIT:
            self._add_placeholder(self.deadline_list, f"외 {len(rows) - DEADLINE_LIMIT}건")
        self.deadline_list.blockSignals(False)

    def _add_deadline_entry(self, widget: SummaryList, row) -> None:
        urgency = deadline_urgency(row)
        raw = str(row["d_day_at"] or "")
        target = self._deadline_target_text(raw)
        entry = QListWidgetItem(
            f"{deadline_chip_text(row)}   {deadline_title(row)}   {target}"
        )
        entry.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
        entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        entry.setCheckState(
            Qt.CheckState.Checked if urgency == "done" else Qt.CheckState.Unchecked
        )
        color = URGENCY_COLORS.get(urgency)
        if color is not None:
            entry.setForeground(color)
        font = entry.font()
        font.setBold(urgency in ("today", "past"))
        font.setStrikeOut(urgency == "done")
        entry.setFont(font)
        entry.setToolTip(
            f"{display_due(raw)}\n"
            "체크하면 남은 날짜 세기를 멈춥니다. 목록에는 그대로 남습니다."
        )
        widget.addItem(entry)

    @staticmethod
    def _deadline_target_text(raw: str) -> str:
        try:
            target = datetime.strptime(raw, DATETIME_FMT)
        except ValueError:
            return ""
        return (
            f"오늘 {target:%H:%M}"
            if target.date() == date.today()
            else f"{target:%m/%d %H:%M}"
        )

    def _toggle_past_deadlines(self, expanded: bool) -> None:
        try:
            self.store.set_setting(
                "past_deadlines_expanded", "true" if expanded else "false"
            )
        except Exception:
            pass
        self.past_deadline_list.setVisible(bool(expanded) and bool(self._past_deadline_ids))
        self._fill_deadlines()
        self._rebalance()

    def _complete_past_deadlines(self) -> None:
        changed = False
        for note_id in list(self._past_deadline_ids):
            try:
                self.store.finish_deadline(note_id, True)
                changed = True
            except Exception:
                continue
        if changed:
            self.deadline_changed.emit()
        self.refresh()

    def _deadline_toggled(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id is None or self._shutdown:
            return
        try:
            self.store.finish_deadline(int(note_id), item.checkState() == Qt.CheckState.Checked)
        except Exception:
            return
        self.deadline_changed.emit()
        self.refresh()

    def _fill_schedules(self, today: date) -> None:
        self.schedule_list.clear()
        try:
            items = self.store.schedules.items_for_range(
                datetime.combine(today, time.min).strftime(DATETIME_FMT),
                datetime.combine(today, time.max).strftime(DATETIME_FMT),
            )
        except Exception:
            items = []
        if not items:
            self._add_placeholder(self.schedule_list, "오늘 등록된 일정이 없습니다.")
            return
        for item in items[:TODAY_LIMIT]:
            start = str(item.get("display_start_at") or item.get("start_at") or "")
            label = f"{start[8:10]}:{start[10:12]}  {item.get('title') or '제목 없음'}"
            entry = QListWidgetItem(label.strip())
            entry.setData(Qt.ItemDataRole.UserRole, int(item["id"]))
            entry.setToolTip(f"{display_due(start)} · {item.get('title') or '제목 없음'}")
            self.schedule_list.addItem(entry)
        if len(items) > TODAY_LIMIT:
            self._add_placeholder(
                self.schedule_list,
                f"외 {len(items) - TODAY_LIMIT}건 · 일정 포스트잇에서 체크 가능",
            )

    def _fill_reminders(self) -> None:
        if not getattr(self, "_show_reminders", True):
            return
        self.reminder_list.clear()
        try:
            rows = self.store.pending_reminders()
        except Exception:
            rows = []
        if not rows:
            self._add_placeholder(self.reminder_list, "예약된 알림이 없습니다.")
            return
        for row in rows[:REMINDER_LIMIT]:
            title = str(row["note_title"] or "삭제된 메모")
            entry = QListWidgetItem(f"{display_due(row['due_at'])}  {title}")
            if row["note_id"] is not None:
                entry.setData(Qt.ItemDataRole.UserRole, int(row["note_id"]))
            entry.setToolTip(str(row["memo"] or title))
            self.reminder_list.addItem(entry)
        if len(rows) > REMINDER_LIMIT:
            self._add_placeholder(self.reminder_list, f"외 {len(rows) - REMINDER_LIMIT}건")

    @staticmethod
    def _add_placeholder(widget: QListWidget, text: str) -> None:
        entry = QListWidgetItem(text)
        entry.setFlags(Qt.ItemFlag.NoItemFlags)
        entry.setForeground(Qt.GlobalColor.gray)
        widget.addItem(entry)

    def _open_schedule(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        if value is not None:
            self.schedule_open_requested.emit(int(value))

    def _open_note(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        if value is not None:
            self.note_open_requested.emit(int(value))
