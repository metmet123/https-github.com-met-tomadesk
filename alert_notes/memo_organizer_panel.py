"""Offline capture, editable review, and a live view of accepted items."""
from datetime import date
import sqlite3

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .categories import CATEGORIES, schedule_categories
from .external_ai_policy import ExternalAIPolicy
from .hub_actions import HubActionStore
from .hub_snapshot_dialog import HubSnapshotVisibilityDialog
from .memo_organizer import KINDS, validate
from .memo_organizer_store import DRAFT_KEY, OrganizerStore, DuplicateMemoError


class OrganizerPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.repo = OrganizerStore(store)
        self.policy = ExternalAIPolicy(store)
        self.capture_id = None
        self._loading = False
        self._items = []
        root = QVBoxLayout(self)
        self.policy_label = QLabel(self.policy.status)
        root.addWidget(self.policy_label)
        self.views = QTabWidget()
        root.addWidget(self.views)
        capture_page = QWidget()
        box = QVBoxLayout(capture_page)
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("날짜 해석 기준일"))
        self.base = QDateEdit()
        self.base.setCalendarPopup(True)
        self.base.setDisplayFormat("yyyy-MM-dd")
        try:
            saved_base = date.fromisoformat(store.setting(DRAFT_KEY + "_base", "")) if store.setting(DRAFT_KEY, "") else date.today()
        except ValueError:
            saved_base = date.today()
        self.base.setDate(saved_base)
        input_row.addWidget(self.base)
        self.analyze_button = QPushButton("저장하고 로컬 정리")
        self.analyze_button.clicked.connect(self.capture_input)
        input_row.addWidget(self.analyze_button)
        self.ai_button = QPushButton("AI 정리 · 추후 제공")
        self.ai_button.setEnabled(False)
        self.ai_button.setToolTip("현재 버전은 외부 AI에 연결하지 않습니다. 연결 허용은 설정에서 선택할 수 있습니다.")
        input_row.addWidget(self.ai_button)
        input_row.addStretch()
        box.addLayout(input_row)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("거친 메모를 한 줄씩 적어 주세요. 예: 내일 견적서 회신 #업무\n아이디어: 고객 온보딩 체크리스트 자동화")
        self.input.setAccessibleName("빠른 메모 수집함 입력")
        self.input.setPlainText(store.setting(DRAFT_KEY, ""))
        self.input.setMaximumHeight(100)
        self.input.textChanged.connect(self._save_input)
        self.base.dateChanged.connect(self._save_input)
        box.addWidget(self.input)
        saved_row = QHBoxLayout()
        saved_row.addWidget(QLabel("저장한 원문"))
        self.captures = QComboBox()
        self.captures.currentIndexChanged.connect(self._load_capture)
        saved_row.addWidget(self.captures, 1)
        self.capture_refresh_button = QPushButton("새로고침")
        self.capture_refresh_button.clicked.connect(self.reload_captures)
        saved_row.addWidget(self.capture_refresh_button)
        self.raw_toggle = QPushButton("원문 보기")
        self.raw_toggle.setCheckable(True)
        saved_row.addWidget(self.raw_toggle)
        box.addLayout(saved_row)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setMaximumHeight(85)
        self.raw.setAccessibleName("보존된 입력 원문")
        self.raw.setVisible(False)
        self.raw_toggle.toggled.connect(self.raw.setVisible)
        box.addWidget(self.raw)
        help_label = QLabel("종류·날짜·시각을 수정한 뒤 선택 항목을 반영하세요. 수정 내용은 자동 보관됩니다.\n"
                            "날짜: YYYY-MM-DD / 시각: HH:MM. 미분류는 직접 지정하세요. 캘린더 등록 후에는 캘린더에서 수정합니다.")
        help_label.setWordWrap(True)
        box.addWidget(help_label)
        self.review = QTableWidget(0, 9)
        self.review.setHorizontalHeaderLabels(["선택", "원문 / 내용", "종류", "날짜", "시작·마감", "종료", "분류", "시각 알림", "확인 사항"])
        self.review.setAccessibleName("메모 정리 검토표")
        self.review.verticalHeader().setDefaultSectionSize(46)
        self.review.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((45, 270, 110, 110, 95, 85, 100, 70, 250)):
            self.review.setColumnWidth(column, width)
        self.review.itemChanged.connect(self._review_changed)
        box.addWidget(self.review, 1)
        self.apply_button = QPushButton("선택 항목 반영")
        self.apply_button.clicked.connect(self.apply_selected)
        action_row = QHBoxLayout()
        action_row.addWidget(self.apply_button, 1)
        self.reject_button = QPushButton("외부 요청 거부")
        self.reject_button.setToolTip("수집된 외부 요청을 반영하지 않고 종료합니다. 원문과 영수증은 보존됩니다.")
        self.reject_button.clicked.connect(self.reject_external)
        action_row.addWidget(self.reject_button)
        box.addLayout(action_row)
        self.views.addTab(capture_page, "수집함·검토")
        overview = QWidget()
        over = QVBoxLayout(overview)
        filters = QHBoxLayout()
        self.category_filter = QComboBox()
        self.category_filter.addItem("전체 분류")
        self.category_filter.currentTextChanged.connect(self.refresh_overview)
        self.sort = QComboBox()
        self.sort.addItems(["날짜순", "카테고리순"])
        self.sort.currentIndexChanged.connect(self.refresh_overview)
        self.show_completed = QCheckBox("완료 포함")
        self.show_completed.toggled.connect(self.refresh_overview)
        for widget in (self.category_filter, self.sort, self.show_completed):
            filters.addWidget(widget)
        refresh = QPushButton("새로고침")
        refresh.clicked.connect(self.refresh_overview)
        filters.addWidget(refresh)
        snapshot = QPushButton("전체 요약을 메모로 저장")
        snapshot.clicked.connect(self.save_snapshot)
        filters.addWidget(snapshot)
        self.visibility_button = QPushButton("조회 공개 선택")
        self.visibility_button.setToolTip("외부로 전송하지 않고, 향후 읽기 전용 조회에 포함할 일정만 선택합니다.")
        self.visibility_button.clicked.connect(self.choose_snapshot_visibility)
        over.addLayout(filters)
        visibility_row = QHBoxLayout()
        visibility_row.addStretch()
        visibility_row.addWidget(self.visibility_button)
        over.addLayout(visibility_row)
        split = QSplitter(Qt.Orientation.Vertical)
        self.overview = QTableWidget(0, 6)
        self.overview.setHorizontalHeaderLabels(["완료", "내용", "종류", "날짜·D-day", "분류", "상태"])
        self.overview.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.overview.setColumnWidth(3, 210)
        for column, width in ((0, 55), (2, 90), (4, 100), (5, 90)):
            self.overview.setColumnWidth(column, width)
        self.overview.itemChanged.connect(self._complete)
        self.overview.cellDoubleClicked.connect(self._open_review)
        split.addWidget(self.overview)
        self.summary = QTextBrowser()
        self.summary.setToolTip("모든 분류의 미완료 항목을 모은 요약입니다. 위 표의 필터와는 별개입니다.")
        self.summary.setOpenExternalLinks(False)
        split.addWidget(self.summary)
        split.setSizes([300, 240])
        over.addWidget(split)
        self.views.addTab(overview, "모아보기·요약")
        self.status = QLabel("로컬에서 정리합니다. 원문과 수집함은 앱 전체 백업에 포함됩니다.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.views.currentChanged.connect(self.refresh_overview)
        self.timer = QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.reload_captures()
        self.refresh_overview()

    def _error(self, exc):
        self.status.setText(str(exc))
        QMessageBox.warning(self, "메모 정리 확인", str(exc))

    def _save_input(self):
        text = self.input.toPlainText()
        if len(text) <= 20000:
            try:
                self.store.set_setting(DRAFT_KEY, text)
                self.store.set_setting(DRAFT_KEY + "_base", self.base.date().toPyDate().isoformat())
            except sqlite3.Error:
                self.status.setText("입력을 저장하지 못했습니다. 입력창의 내용을 보존하고 저장 위치를 확인해 주세요.")
        else:
            self.status.setText("20,000자를 넘은 입력은 자동 저장되지 않습니다. 나누어 입력해 주세요.")

    def capture_input(self):
        try:
            self.capture_id = self.repo.capture(self.input.toPlainText(), self.base.date().toPyDate())
            self.reload_captures()
            self.status.setText("원문과 기준일을 보존했습니다. 확인 후 선택 항목을 반영하세요.")
        except (ValueError, sqlite3.Error) as exc:
            self._error(exc)

    def reload_captures(self):
        self.captures.blockSignals(True)
        self.captures.clear()
        try:
            captures = self.repo.load()["captures"]
            for capture in reversed(captures):
                label = capture["raw"].splitlines()[0][:55]
                if capture.get("external"):
                    source = capture["external"]["source"]
                    try:
                        state = HubActionStore(self.store).receipt(capture["external"]["action_id"])["state"]
                    except KeyError:
                        state = "missing"
                    source_label = "텔레그램" if source == "telegram" else source
                    state_label = {
                        "awaiting_review": "검토 대기", "applied": "반영됨",
                        "rejected": "거부됨", "missing": "영수증 없음",
                    }.get(state, state)
                    label = f"{source_label} · {state_label} · {label}"
                self.captures.addItem(f"{capture['base']} · {label}", capture["id"])
            index = self.captures.findData(self.capture_id)
            self.captures.setCurrentIndex(index if index >= 0 else (0 if captures else -1))
        except ValueError as exc:
            self.status.setText(str(exc))
        finally:
            self.captures.blockSignals(False)
        self._load_capture()

    def _load_capture(self, *_):
        self.capture_id = self.captures.currentData()
        if not self.capture_id:
            self.apply_button.setEnabled(False)
            self.reject_button.setEnabled(False)
            return
        self._loading = True
        capture = self.repo.get_capture(self.capture_id)
        external_state = None
        if capture.get("external"):
            try:
                external_state = HubActionStore(self.store).receipt(capture["external"]["action_id"])["state"]
            except KeyError:
                external_state = "missing"
        external_final = external_state is not None and external_state != "awaiting_review"
        self.apply_button.setEnabled(not external_final)
        self.reject_button.setEnabled(external_state == "awaiting_review")
        self.raw.setPlainText(capture["raw"])
        self._items = capture["items"]
        self.review.setRowCount(len(self._items))
        categories = list(dict.fromkeys(
            ["미분류"] + [row["name"] for row in schedule_categories(self.store)]
            + [name for name, _ in CATEGORIES] + [str(c["name"]) for c in self.store.categories()]
        ))
        for row, item in enumerate(self._items):
            locked = bool(item.get("schedule_id")) or external_final
            duplicate = bool(self.repo.duplicate_titles([item])) if not locked else False
            reason = item['reason'] + (' 중복 가능: 이미 반영한 항목이 있습니다.' if duplicate else '')
            choice = QTableWidgetItem()
            choice.setFlags(Qt.ItemFlag.ItemIsEnabled | (Qt.ItemFlag.ItemIsUserCheckable if not locked else Qt.ItemFlag.NoItemFlags))
            choice.setCheckState(Qt.CheckState.Checked if not locked and not reason else Qt.CheckState.Unchecked)
            self.review.setItem(row, 0, choice)
            for col, key in ((1, "title"), (3, "day"), (4, "clock"), (5, "end_clock"), (8, "reason")):
                if col == 8 and locked:
                    text = (
                        "등록됨 · 캘린더에서 수정" if item.get("schedule_id") else
                        "등록됨 · 메모에서 수정" if item.get("note_id") else
                        "거부됨 · 원문만 보존" if external_state == "rejected" else
                        "이번 승인에서 제외됨" if external_state == "applied" else
                        "영수증 확인 필요"
                    )
                else:
                    text = reason if col == 8 else str(item[key])
                cell = QTableWidgetItem(text)
                cell.setToolTip(item["raw"] if col == 1 else text)
                if locked or col == 8:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.review.setItem(row, col, cell)
            kind = QComboBox()
            for key, label in KINDS.items():
                kind.addItem(label, key)
            kind.setCurrentIndex(kind.findData(item["kind"]))
            kind.setEnabled(not locked)
            self.review.setCellWidget(row, 2, kind)
            category = QComboBox()
            category.setEditable(True)
            category.addItems(categories)
            category.setCurrentText(item["category"])
            category.setEnabled(not locked)
            category.setToolTip("일정의 기본 분류에 없는 이름은 캘린더에서 기타로 표시되며 상세 내용에 원래 분류를 보존합니다.")
            self.review.setCellWidget(row, 6, category)
            notify = QCheckBox()
            notify.setChecked(bool(item.get("notify")))
            notify.setEnabled(not locked)
            self.review.setCellWidget(row, 7, notify)
            kind.currentIndexChanged.connect(lambda _value, r=row: self._review_row_changed(r))
            category.currentTextChanged.connect(lambda _value, r=row: self._review_row_changed(r))
            notify.toggled.connect(lambda _value, r=row: self._review_row_changed(r))
        self._loading = False

    def _values(self, row):
        item = dict(self._items[row])
        for col, key in ((1, "title"), (3, "day"), (4, "clock"), (5, "end_clock")):
            item[key] = self.review.item(row, col).text().strip()
        item["kind"] = self.review.cellWidget(row, 2).currentData()
        item["category"] = self.review.cellWidget(row, 6).currentText().strip() or "미분류"
        item["notify"] = self.review.cellWidget(row, 7).isChecked()
        return item

    def _review_changed(self, cell):
        if cell.column() != 0:
            self._review_row_changed(cell.row())

    def _review_row_changed(self, row):
        if self._loading:
            return
        try:
            self.repo.save_review(self.capture_id, [self._values(row)])
            values = self._values(row)
            warning = ''
            try:
                validate(values)
            except ValueError as exc:
                warning = str(exc)
            if self.repo.duplicate_titles([values]):
                warning += ' 중복 가능: 이미 반영한 항목이 있습니다.'
            self._loading = True
            try:
                self.review.item(row, 8).setText(warning or self._items[row]['reason'])
                if warning:
                    self.review.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
            finally:
                self._loading = False
            self.status.setText("수정 내용을 보관했습니다. 선택 후 반영하면 적용됩니다.")
        except (ValueError, KeyError, sqlite3.Error) as exc:
            self._error(exc)

    def apply_selected(self):
        values = [self._values(row) for row in range(self.review.rowCount())
                  if self.review.item(row, 0).checkState() == Qt.CheckState.Checked]
        try:
            capture = self.repo.get_capture(self.capture_id)
            external = capture.get("external")

            def apply(allow_duplicates=False):
                if external:
                    result = HubActionStore(self.store).apply_review(
                        external["action_id"], values, allow_duplicates=allow_duplicates,
                    )
                    return result["applied_count"]
                return self.repo.apply(self.capture_id, values, allow_duplicates=allow_duplicates)

            try:
                count = apply() if values else 0
            except DuplicateMemoError:
                answer = QMessageBox.question(self, '중복 메모 확인',
                    '같은 내용·날짜·시각·분류의 항목이 있습니다.\n그래도 별도 항목으로 반영할까요?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                count = apply(allow_duplicates=True)
            self.status.setText(f"{count}개 항목을 반영했습니다." if count else "반영할 항목을 선택해 주세요.")
            self.reload_captures()
            self.refresh_overview()
            self.changed.emit()
        except (ValueError, KeyError, sqlite3.Error) as exc:
            self._error(exc)

    def reject_external(self):
        try:
            capture = self.repo.get_capture(self.capture_id)
            external = capture.get("external")
            if not external:
                raise ValueError("외부 요청만 거부할 수 있습니다.")
            answer = QMessageBox.question(
                self, "외부 요청 거부", "이 요청을 반영하지 않고 종료할까요? 원문은 보존됩니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            HubActionStore(self.store).reject(external["action_id"])
            self.status.setText("외부 요청을 거부했습니다. 원문과 영수증은 보존됩니다.")
            self.reload_captures()
            self.refresh_overview()
            self.changed.emit()
        except (ValueError, KeyError, sqlite3.Error) as exc:
            self._error(exc)

    def refresh_overview(self, *_):
        if not hasattr(self, "overview"):
            return
        try:
            rows = self.repo.rows()
            category = self.category_filter.currentText()
            self.category_filter.blockSignals(True)
            self.category_filter.clear()
            self.category_filter.addItems(["전체 분류"] + sorted({r["category"] for r in rows}))
            self.category_filter.setCurrentText(category if category in [self.category_filter.itemText(i) for i in range(self.category_filter.count())] else "전체 분류")
            self.category_filter.blockSignals(False)
            if category != "전체 분류":
                rows = [r for r in rows if r["category"] == category]
            rows = [r for r in rows if self.show_completed.isChecked() or not r["completed"]]
            if self.sort.currentIndex() == 1:
                rows.sort(key=lambda r: (r["category"], r["day"] or "9999", r["title"]))
            self._overview_rows = rows
            self.overview.blockSignals(True)
            self.overview.setRowCount(len(rows))
            for row, item in enumerate(rows):
                for col, text in enumerate(("", item["title"], KINDS[item["kind"]],
                        f"{item['day']} {item['clock']} {self.repo.dday(item['day'])}", item["category"],
                        "확인 필요" if not item["applied"] or item["kind"] == "review" else "반영됨")):
                    cell = QTableWidgetItem(text)
                    cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    if col == 0 and item["applied"] and item["kind"] in ("task", "event"):
                        cell.setFlags(cell.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        cell.setCheckState(Qt.CheckState.Checked if item["completed"] else Qt.CheckState.Unchecked)
                    if item["day"] and item["applied"] and item["kind"] in ("task", "event") and not item["completed"]:
                        font = cell.font()
                        font.setBold((date.fromisoformat(item["day"]) - date.today()).days <= 3)
                        cell.setFont(font)
                    self.overview.setItem(row, col, cell)
            self.summary.setHtml(self.repo.summary_html())
            self.policy_label.setText(self.policy.status)
        except ValueError as exc:
            self.status.setText(str(exc))
        finally:
            self.overview.blockSignals(False)

    def _complete(self, cell):
        if cell.column() != 0:
            return
        try:
            self.repo.complete(self._overview_rows[cell.row()]["id"], cell.checkState() == Qt.CheckState.Checked)
            self.refresh_overview()
            self.changed.emit()
        except (ValueError, sqlite3.Error) as exc:
            self._error(exc)

    def _open_review(self, row, _col):
        item = self._overview_rows[row]
        self.captures.setCurrentIndex(self.captures.findData(item["capture_id"]))
        self.views.setCurrentIndex(0)
        self._load_capture()

    def save_snapshot(self):
        try:
            self.store.create_note(f"메모 정리 · {date.today():%Y-%m-%d}", self.repo.summary_html())
            self.status.setText("현재 요약을 일반 메모로 저장했습니다. 저장한 요약은 자동 변경되지 않습니다.")
            self.changed.emit()
        except (ValueError, sqlite3.Error) as exc:
            self._error(exc)

    def choose_snapshot_visibility(self):
        dialog = HubSnapshotVisibilityDialog(self.store, self)
        accepted = dialog.exec() == dialog.DialogCode.Accepted
        dialog.deleteLater()
        if accepted:
            self.status.setText("조회 공개 일정 선택을 저장했습니다. 현재는 외부로 전송하지 않습니다.")

    def _tick(self):
        if self.isVisible():
            self.refresh_overview()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_overview()
