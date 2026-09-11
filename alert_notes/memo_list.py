import json
from datetime import date

from PyQt6.QtCore import QEvent, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QPushButton, QStyle, QStyledItemDelegate, QStyleOptionButton, QStyleOptionViewItem,
    QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .deadline import deadline_chip_text, is_deadline_done, reminder_display_text
from .rich_text import plain_text_from_content
from .sqlite_store import TOP_LEVEL_PARENT
from select_all_header import SelectAllHeader

NOTE_ID_ROLE = Qt.ItemDataRole.UserRole
SORT_KEY_ROLE = Qt.ItemDataRole.UserRole + 1
CHILD_COUNT_ROLE = Qt.ItemDataRole.UserRole + 2
PINNED_ROLE = Qt.ItemDataRole.UserRole + 3


def list_datetime(value) -> str:
    """Shorter than the export format: this year needs no year in a narrow column."""
    text = str(value or "")[:12]
    if len(text) != 12 or not text.isdigit():
        return ""
    clock = f"{text[8:10]}:{text[10:12]}"
    if text[:4] == str(date.today().year):
        return f"{text[4:6]}-{text[6:8]} {clock}"
    return f"{text[2:4]}-{text[4:6]}-{text[6:8]} {clock}"


class CenteredCheckDelegate(QStyledItemDelegate):
    """체크 상자를 열 한가운데에 그린다.

    기본 그리기는 칸 왼쪽에 붙이므로, 가운데 놓인 머리글 체크와 어긋나 보였다.
    """

    @staticmethod
    def _style_for(option):
        widget = option.widget
        return widget, (widget.style() if widget is not None else QApplication.style())

    @classmethod
    def indicator_rect(cls, option) -> QRect:
        widget, style = cls._style_for(option)
        size = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, widget)
        centre = option.rect.center()
        return QRect(centre.x() - size // 2 + 1, centre.y() - size // 2 + 1, size, size)

    def paint(self, painter, option, index) -> None:
        widget, style = self._style_for(option)
        panel = QStyleOptionViewItem(option)
        self.initStyleOption(panel, index)
        panel.text = ""
        panel.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, panel, painter, widget)
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        if state is None:
            return
        box = QStyleOptionButton()
        box.rect = self.indicator_rect(option)
        box.state = QStyle.StateFlag.State_Enabled | {
            Qt.CheckState.Checked: QStyle.StateFlag.State_On,
            Qt.CheckState.PartiallyChecked: QStyle.StateFlag.State_NoChange,
        }.get(Qt.CheckState(state), QStyle.StateFlag.State_Off)
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, box, painter, widget)

    def editorEvent(self, event, model, option, index) -> bool:
        checkable = bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        if event.type() == QEvent.Type.MouseButtonRelease and checkable:
            if not self.indicator_rect(option).contains(event.position().toPoint()):
                return False
            current = Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole))
            model.setData(
                index,
                Qt.CheckState.Unchecked if current == Qt.CheckState.Checked
                else Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )
            return True
        if event.type() == QEvent.Type.MouseButtonDblClick and checkable:
            # 두 번 누르면 켜졌다 꺼져 제자리로 돌아온다.  한 번만 세도록 흘린다.
            return True
        return super().editorEvent(event, model, option, index)


class TitleCountDelegate(QStyledItemDelegate):
    """접어 둔 메모 끝에 안에 몇 개가 들었는지 숫자만 적는다.

    "하위" 같은 낱말을 붙이면 좁은 제목 열을 그만큼 잡아먹는다.
    """

    BADGE_PADDING = 7
    BADGE_HEIGHT = 16
    BADGE_GAP = 10

    @staticmethod
    def visible_count(widget, index) -> int:
        """펼쳐 두면 안이 다 보이므로 숫자를 지운다.

        펼침 상태는 0 번 열 자리로 기억되므로, 제목 열 그대로 물으면 늘 접힌
        것으로 나온다.
        """
        count = int(index.data(CHILD_COUNT_ROLE) or 0)
        if widget is not None and widget.isExpanded(index.siblingAtColumn(0)):
            return 0
        return count

    @staticmethod
    def _hovered(widget, index) -> bool:
        if widget is None or not hasattr(widget, "hovered_row"):
            return False
        item = widget.hovered_row()
        if item is None:
            return False
        try:
            return widget.indexFromItem(item, index.column()) == index
        except RuntimeError:
            # 이미 지워진 줄이면 없는 셈 친다.  그리다가 꺼지는 것보다 낫다.
            widget.forget_hover()
            return False

    def paint(self, painter, option, index) -> None:
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        panel = QStyleOptionViewItem(option)
        self.initStyleOption(panel, index)
        # 마우스를 올린 줄에는 개수 대신 "하위 메모 추가"가 뜬다.
        adding = self._hovered(widget, index)
        count = 0 if adding else self.visible_count(widget, index)
        if adding:
            self._paint_plus(painter, style, widget, panel, option)
            return
        if not count:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, panel, painter, widget)
            return
        label = str(count)
        metrics = panel.fontMetrics
        badge_width = metrics.horizontalAdvance(label) + self.BADGE_PADDING * 2
        room = max(0, panel.rect.width() - badge_width - self.BADGE_GAP)
        panel.text = metrics.elidedText(panel.text, Qt.TextElideMode.ElideRight, room)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, panel, painter, widget)
        badge = QRect(
            option.rect.right() - badge_width - 4,
            option.rect.center().y() - self.BADGE_HEIGHT // 2,
            badge_width, self.BADGE_HEIGHT,
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(59, 84, 232, 30))
        painter.drawRoundedRect(badge, 8.0, 8.0)
        painter.setPen(QColor("#2438b8"))
        painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), label)
        painter.restore()

    def _paint_plus(self, painter, style, widget, panel, option) -> None:
        """줄 오른쪽 끝의 + 단추.  누르면 그 메모의 하위로 새 메모가 생긴다."""
        plus = widget.plus_rect(widget.hovered_row())
        metrics = panel.fontMetrics
        room = max(0, plus.left() - option.rect.left() - 6)
        panel.text = metrics.elidedText(panel.text, Qt.TextElideMode.ElideRight, room)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, panel, painter, widget)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(59, 84, 232, 34))
        painter.drawRoundedRect(QRectF(plus), 6.0, 6.0)
        pen = QPen(QColor("#2438b8"), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        centre = plus.center()
        arm = plus.width() // 2 - 5
        painter.drawLine(centre.x() - arm, centre.y(), centre.x() + arm, centre.y())
        painter.drawLine(centre.x(), centre.y() - arm, centre.x(), centre.y() + arm)
        painter.restore()


class MemoTree(QTreeWidget):
    """메모 목록.  줄을 끌어 다른 메모 안으로 넣거나 순서를 바꿀 수 있다."""

    note_moved = pyqtSignal(int, int, int)
    child_requested = pyqtSignal(int)
    pin_toggled = pyqtSignal(int, bool)

    PLUS_SIZE = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_arrow = None
        self._hover_row = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_row_menu)

    def _show_row_menu(self, point) -> None:
        """줄에서 오른쪽 단추.  지금은 목록 고정을 켜고 끈다."""
        item = self.itemAt(point)
        if item is None:
            return
        self.setCurrentItem(item)
        note_id = int(item.data(0, NOTE_ID_ROLE))
        pinned = bool(item.data(0, PINNED_ROLE))
        menu = QMenu(self)
        menu.setObjectName("memoRowMenu")
        action = menu.addAction("고정 해제" if pinned else "목록 맨 위에 고정")
        action.triggered.connect(
            lambda _checked=False: self.pin_toggled.emit(note_id, not pinned)
        )
        self.row_menu = menu
        menu.exec(self.viewport().mapToGlobal(point))

    # ---------------------------------------------------- 하위 메모 추가 --
    def hovered_row(self):
        return self._hover_row

    def forget_hover(self) -> None:
        """줄을 다시 그리기 전에 마우스가 잡고 있던 줄을 놓는다.

        놓지 않으면 지워진 줄을 가리킨 채로 남아, 다음 그리기에서 이미 사라진
        항목을 만지며 프로그램이 통째로 꺼진다.
        """
        self._hover_row = None
        self._hover_arrow = None

    def plus_rect(self, item) -> QRect:
        """줄에 마우스를 올렸을 때 제목 열 오른쪽 끝에 뜨는 + 자리."""
        row = self.visualItemRect(item)
        column = self.header().sectionViewportPosition(self.treePosition())
        width = self.columnWidth(self.treePosition())
        size = self.PLUS_SIZE
        return QRect(
            column + width - size - 5,
            row.y() + (row.height() - size) // 2,
            size, size,
        )

    def plus_item_at(self, point):
        item = self.itemAt(point)
        if item is None:
            return None
        return item if self.plus_rect(item).contains(point) else None

    # --------------------------------------------------- 마우스 올림 --
    def arrow_rect(self, item) -> QRect:
        """펼침 화살표가 그려지는 자리.

        화살표는 제목 열 왼쪽의 들여쓰기 칸에 그려지고, 층이 깊을수록 그만큼
        오른쪽으로 밀린다.
        """
        row = self.visualItemRect(item)
        column = self.header().sectionViewportPosition(self.treePosition())
        indent = self.indentation()
        depth = 0
        walker = item.parent()
        while walker is not None:
            walker, depth = walker.parent(), depth + 1
        return QRect(column + depth * indent, row.y(), indent, row.height())

    def arrow_item_at(self, point):
        item = self.itemAt(point)
        if item is None or not item.childCount():
            return None
        return item if self.arrow_rect(item).contains(point) else None

    def _set_hover_arrow(self, item) -> None:
        # 화살표는 눌러서 접었다 펴는 자리다.  글자 고르는 커서와 달라야 한다.
        shape = (
            Qt.CursorShape.PointingHandCursor if item is not None
            else Qt.CursorShape.ArrowCursor
        )
        if self.viewport().cursor().shape() != shape:
            self.viewport().setCursor(shape)
        if item is not self._hover_arrow:
            self._hover_arrow = item
            self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if event.buttons() != Qt.MouseButton.NoButton:
            return
        point = event.position().toPoint()
        row = self.itemAt(point)
        if row is not self._hover_row:
            self._hover_row = row
            self.viewport().update()
        self._set_hover_arrow(self.arrow_item_at(point))
        if self._hover_arrow is None and self.plus_item_at(point) is not None:
            if self.viewport().cursor().shape() != Qt.CursorShape.PointingHandCursor:
                self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.plus_item_at(event.position().toPoint())
            if item is not None:
                self.child_requested.emit(int(item.data(0, NOTE_ID_ROLE)))
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hover_arrow(None)
        if self._hover_row is not None:
            self._hover_row = None
            self.viewport().update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        item = self._hover_arrow
        if item is None:
            return
        rect = QRectF(self.arrow_rect(item)).adjusted(-1, 4, -1, -4)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(59, 84, 232, 30))
        painter.drawRoundedRect(rect, 5.0, 5.0)
        painter.end()

    def dropEvent(self, event) -> None:
        dragged = self.currentItem()
        # 저장소가 참이다.  Qt 가 항목만 옮기면 다시 그릴 때 제자리로 돌아온다.
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        note_id = None if dragged is None else dragged.data(0, NOTE_ID_ROLE)
        if note_id is None:
            return
        parent_id, position = self._drop_target(event.position().toPoint(), dragged)
        self.note_moved.emit(int(note_id), int(parent_id), int(position))

    def _drop_target(self, point, dragged) -> tuple[int, int]:
        target = self.itemAt(point)
        where = self.dropIndicatorPosition()
        viewport = QAbstractItemView.DropIndicatorPosition.OnViewport
        if target is None or where == viewport:
            return TOP_LEVEL_PARENT, self.topLevelItemCount()
        if where == QAbstractItemView.DropIndicatorPosition.OnItem:
            # 메모 위에 그대로 떨어뜨리면 그 안으로 들어간다.
            return int(target.data(0, NOTE_ID_ROLE)), target.childCount()
        parent = target.parent()
        if parent is None:
            index = self.indexOfTopLevelItem(target)
            parent_id = TOP_LEVEL_PARENT
        else:
            index = parent.indexOfChild(target)
            parent_id = int(parent.data(0, NOTE_ID_ROLE))
        below = QAbstractItemView.DropIndicatorPosition.BelowItem
        return parent_id, index + (1 if where == below else 0)


class MemoListPanel(QWidget):
    note_selected = pyqtSignal(int)
    recent_chosen = pyqtSignal(int)
    new_requested = pyqtSignal()
    export_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    note_moved = pyqtSignal(int, int, int)
    child_requested = pyqtSignal(int)
    pin_toggled = pyqtSignal(int, bool)
    copy_requested = pyqtSignal()
    paste_requested = pyqtSignal()
    clone_undo_requested = pyqtSignal()
    clone_redo_requested = pyqtSignal()

    # 번호 carried no information the row order did not already show, and 표시
    # spent a whole column on one word; it is now a mark in front of the title.
    # 머리글 글자가 곧 그 열의 최소 폭이다.  좁은 목록에서 제목이 잘리던 가장
    # 큰 까닭이라 이름을 짧게 줄였다.  열에 담기는 내용은 그대로다.
    HEADERS = ["", "제목", "내용", "일정", "수정시간"]
    COLUMN_WEIGHTS = (34, 210, 196, 122, 114)
    # 이보다 좁아지면 수정시간을 접는다.  접은 값은 제목 말풍선에 남는다.
    NARROW_WIDTH = 520
    FOLDABLE_COLUMN = 4
    # 모두 접기·펼치기 단축키.  이 창이 앞에 있을 때만 듣는다.  본문 토글은
    # 편집 구역의 Ctrl+Shift+E 가 따로 맡고 있어 글자를 겹치지 않게 골랐다.
    FOLD_ALL_SHORTCUT = "Ctrl+Shift+A"
    # 제목이 잘릴 때 폭을 빌려 오는 차례.
    BORROW_ORDER = (4, 3, 2)
    # Floor per column; the real minimum also has to fit the header text, which
    # is measured at runtime so every title stays readable at the narrowest width.
    COLUMN_FLOORS = (30, 62, 62, 62, 62)
    HEADER_PADDING = 20
    # A column may not be dragged below this share of the width it would get from
    # the default proportions, so the minimum follows the splitter, not a constant.
    MIN_SHARE_OF_DEFAULT = 0.55
    POSTIT_MARK = "📌"
    PINNED_MARK = "⭐"
    TITLE_COLUMN = 1
    # 한 줄에 제목 한 줄만 들어간다.  48px 은 빈 위아래 여백이 너무 넓었다.
    ROW_HEIGHT = 32
    # 목록 위아래의 단추와 검색칸 높이.  낮출수록 목록이 길어진다.
    BUTTON_HEIGHT = 28
    HEADER_HEIGHT = 29
    COLUMN_RATIOS_SETTING = "memo_list_column_ratios_v2"
    EXPANDED_SETTING = "memo_list_expanded_ids"

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self.store = store
        self._restoring_columns = False
        self._restoring_expansion = False
        self.setObjectName("memoListPanel")
        self.rows_by_id: dict[int, object] = {}
        layout = QVBoxLayout(self)
        # 세로로 남는 자리는 모두 목록에 준다.
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel("메모 목록")
        title.setObjectName("memoListTitle")
        header.addWidget(title)
        header.addStretch()
        self.fold_button = QPushButton("모두 접기")
        self.fold_button.setObjectName("compactUtilityButton")
        self.fold_button.setAccessibleName("모든 메모 접기/펼치기")
        self.fold_button.setToolTip(
            f"하위 메모를 한 번에 접거나 폅니다. ({self.FOLD_ALL_SHORTCUT})"
        )
        self.fold_button.setFixedHeight(self.BUTTON_HEIGHT)
        self.fold_button.clicked.connect(self.toggle_all_folds)
        self.fold_shortcut = QShortcut(QKeySequence(self.FOLD_ALL_SHORTCUT), self)
        # 창이 앞에 있을 때만 듣는다.  전역 단축키처럼 다른 프로그램에서
        # 일하는 중에 끼어들면 곤란하다.
        self.fold_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.fold_shortcut.activated.connect(self._fold_shortcut_pressed)
        header.addWidget(self.fold_button)
        self.add_button = QPushButton("+ 새 메모")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setFixedHeight(self.BUTTON_HEIGHT)
        self.add_button.clicked.connect(self.new_requested)
        header.addWidget(self.add_button)
        layout.addLayout(header)

        self.search = QLineEdit()
        self.search.setPlaceholderText("메모 제목과 내용 검색")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("알림 메모 검색")
        self.search.setFixedHeight(self.BUTTON_HEIGHT)
        layout.addWidget(self.search)

        # 방금 보던 메모로 한 번에 돌아가는 칩.  없을 때는 자리도 차지하지 않는다.
        self.recent_host = QWidget()
        self.recent_layout = QHBoxLayout(self.recent_host)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(4)
        self.recent_buttons: list[QPushButton] = []
        # 칩은 왼쪽에 붙는다.  남는 자리를 나눠 가지면 사이가 벌어져 보인다.
        self.recent_layout.addStretch(1)
        self.recent_host.hide()
        layout.addWidget(self.recent_host)

        self.table = MemoTree()
        self.table.setObjectName("memoListTable")
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setUniformRowHeights(True)
        # 층이 깊어질수록 제목이 밀린다.  밀리는 정도를 줄인다.
        self.table.setIndentation(12)
        self.table.setRootIsDecorated(True)
        # 펼침 화살표는 제목 열에 둔다.  0 번 열은 선택 체크 자리다.
        self.table.setTreePosition(self.TITLE_COLUMN)
        self.table.setExpandsOnDoubleClick(False)
        # 끌어 놓은 차례가 곧 목록 차례이므로 머리글 정렬은 쓰지 않는다.
        self.table.setSortingEnabled(False)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table_header = SelectAllHeader(self.table)
        self.table.setHeader(self.table_header)
        self.check_delegate = CenteredCheckDelegate(self.table)
        self.table.setItemDelegateForColumn(0, self.check_delegate)
        self.count_delegate = TitleCountDelegate(self.table)
        self.table.setItemDelegateForColumn(self.TITLE_COLUMN, self.count_delegate)
        # 머리글도 낮춰 목록에 한 줄을 더 준다.  서식의 min-height 보다 세다.
        self.table_header.setFixedHeight(self.HEADER_HEIGHT)
        self.table_header.setMinimumSectionSize(min(self.COLUMN_FLOORS))
        # Fixed meant the user could not widen a column at all.
        self.table_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_header.setStretchLastSection(False)
        self.table_header.sectionResized.connect(self._on_section_resized)
        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        self.table.itemClicked.connect(self._activate_row)
        self.table.itemChanged.connect(self._sync_select_all_state)
        self.table.itemExpanded.connect(self._sync_fold_button)
        self.table.itemCollapsed.connect(self._sync_fold_button)
        self.table.itemExpanded.connect(self._save_expanded)
        self.table.itemCollapsed.connect(self._save_expanded)
        # 펼치면 한 층 더 들어간 제목이 나타난다.  그때마다 폭을 다시 잡는다.
        self.table.itemExpanded.connect(self._resize_table_columns)
        self.table.itemCollapsed.connect(self._resize_table_columns)
        self.table.note_moved.connect(self.note_moved)
        self.table.child_requested.connect(self.child_requested)
        self.table.pin_toggled.connect(self.pin_toggled)
        self.table_header.check_state_changed.connect(self._set_all_checked)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("메모가 없습니다.\n편집 구역에 바로 입력하거나 새 메모를 만들어 주세요.")
        self.empty_label.setObjectName("memoEmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label, 1)

        self.actions_host = QWidget()
        actions = QHBoxLayout(self.actions_host)
        actions.setContentsMargins(0, 0, 0, 0)
        self.export_button = QPushButton("Excel 내보내기")
        self.delete_button = QPushButton("선택 삭제")
        self.delete_button.setObjectName("dangerButton")
        for button in (self.export_button, self.delete_button):
            button.setFixedHeight(self.BUTTON_HEIGHT)
            actions.addWidget(button)
        actions.addStretch()
        layout.addWidget(self.actions_host)
        self.export_button.clicked.connect(self.export_requested.emit)
        self.delete_button.clicked.connect(self.delete_requested.emit)

    # ------------------------------------------------------------- 크기 --
    def height_for_rows(self, rows: int) -> int:
        """Height this panel needs before the table can show `rows` entries."""
        header = max(22, self.table_header.height())
        above = self.table.y()
        if above <= 0:
            above = self.BUTTON_HEIGHT * 2 + 8 + 6 + 6
        below = self.BUTTON_HEIGHT + 6 + 8
        return above + header + rows * self.ROW_HEIGHT + below

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self._resize_table_columns()
        if watched is self.table and event.type() == QEvent.Type.KeyPress:
            modifiers = event.modifiers()
            if event.key() == Qt.Key.Key_C and modifiers == Qt.KeyboardModifier.ControlModifier:
                self.copy_requested.emit()
                return True
            if event.key() == Qt.Key.Key_V and modifiers == Qt.KeyboardModifier.ControlModifier:
                self.paste_requested.emit()
                return True
            if event.key() == Qt.Key.Key_Z and modifiers == Qt.KeyboardModifier.ControlModifier:
                self.clone_undo_requested.emit()
                return True
            if (
                (event.key() == Qt.Key.Key_Y and modifiers == Qt.KeyboardModifier.ControlModifier)
                or (event.key() == Qt.Key.Key_Z and modifiers == (
                    Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                ))
            ):
                self.clone_redo_requested.emit()
                return True
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.deletion_ids():
                self.delete_requested.emit()
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_table_columns()

    def text_minimums(self) -> list[int]:
        """Hard floor: a header must never be cut off, whatever the width."""
        metrics = self.table_header.fontMetrics()
        return [
            max(floor, metrics.horizontalAdvance(title) + self.HEADER_PADDING)
            for floor, title in zip(self.COLUMN_FLOORS, self.HEADERS)
        ]

    def column_minimums(self, available: int | None = None) -> list[int]:
        """Narrowest each column may get at the width the splitter gives us.

        A fixed floor meant a column dragged thin stayed thin at every panel
        width, so the saved width kept re-clipping the header.  The floor now
        scales with the panel: wide panel, roomier minimum.
        """
        floors = self.text_minimums()
        if available is None:
            available = self.table.viewport().width()
        if available <= 0:
            return floors
        total = sum(self.COLUMN_WEIGHTS)
        return [
            max(floor, round(available * weight / total * self.MIN_SHARE_OF_DEFAULT))
            for floor, weight in zip(floors, self.COLUMN_WEIGHTS)
        ]

    def minimum_table_width(self) -> int:
        """Width the panel needs before a header would be cut off."""
        margins = self.layout().contentsMargins()
        return sum(self.text_minimums()) + margins.left() + margins.right() + 24

    def _column_ratios(self) -> list[float]:
        """User-dragged proportions when there are any, else the defaults."""
        raw = ""
        if self.store is not None:
            raw = str(self.store.setting(self.COLUMN_RATIOS_SETTING, ""))
        try:
            values = [float(value) for value in json.loads(raw)]
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        if len(values) != len(self.HEADERS) or any(value <= 0 for value in values):
            values = list(self.COLUMN_WEIGHTS)
        total = sum(values)
        return [value / total for value in values]

    def _on_section_resized(self, index: int, _old: int, new: int) -> None:
        if self._restoring_columns:
            return
        minimums = self.column_minimums()
        if index < len(minimums) and new < minimums[index]:
            # Let go below the floor and it snaps back, so a header can never be
            # left clipped — and a clipped width can never be saved.
            self._restoring_columns = True
            try:
                self.table.setColumnWidth(index, minimums[index])
            finally:
                self._restoring_columns = False
        if self.store is None or self.is_narrow():
            # 접힌 열이 있는 동안의 폭은 그 폭대로일 뿐이다.  넓은 창에서 쓸
            # 비율로 저장하면 다음에 열었을 때 열 하나가 사라진 채로 남는다.
            return
        widths = [self.table.columnWidth(column) for column in range(self.table.columnCount())]
        total = sum(widths)
        if total <= 0:
            return
        self.store.set_setting(
            self.COLUMN_RATIOS_SETTING,
            json.dumps([width / total for width in widths]),
        )

    def is_narrow(self) -> bool:
        return self.width() < self.NARROW_WIDTH

    def _sync_folded_columns(self) -> None:
        """좁아지면 수정시간을 접는다.  넓히면 바로 돌아온다."""
        folded = self.is_narrow()
        if self.table.isColumnHidden(self.FOLDABLE_COLUMN) != folded:
            self.table.setColumnHidden(self.FOLDABLE_COLUMN, folded)

    def visible_columns(self) -> list[int]:
        return [
            column for column in range(len(self.HEADERS))
            if not self.table.isColumnHidden(column)
        ]

    def _visible_items(self):
        """접힌 부모 안에 있어 지금 화면에 없는 줄은 뺀다."""
        for item in self._walk():
            parent, shown = item.parent(), True
            while parent is not None:
                if not parent.isExpanded():
                    shown = False
                    break
                parent = parent.parent()
            if shown:
                yield item

    def title_room_needed(self) -> int:
        """지금 보이는 제목 가운데 가장 긴 것이 다 보이려면 필요한 폭."""
        metrics = self.table.fontMetrics()
        indent = self.table.indentation()
        needed = 0
        for item in self._visible_items():
            depth, walker = 0, item.parent()
            while walker is not None:
                walker, depth = walker.parent(), depth + 1
            text = metrics.horizontalAdvance(item.text(self.TITLE_COLUMN))
            needed = max(needed, indent * (depth + 1) + text + self.HEADER_PADDING + 14)
        return needed

    def _lend_to_title(self, widths: dict[int, int], minimums) -> None:
        """제목이 잘릴 때만 수정시간 → 일정 → 내용 차례로 폭을 빌려 온다."""
        want = self.title_room_needed() - widths.get(self.TITLE_COLUMN, 0)
        if want <= 0:
            return
        for column in self.BORROW_ORDER:
            if want <= 0:
                break
            if column not in widths:
                continue
            take = min(max(0, widths[column] - minimums[column]), want)
            widths[column] -= take
            widths[self.TITLE_COLUMN] += take
            want -= take

    def _resize_table_columns(self) -> None:
        """Fill the current viewport while preserving the column proportions."""
        if not hasattr(self, "table") or not self.table.isVisible():
            return
        self._sync_folded_columns()
        available = self.table.viewport().width()
        if available <= 0:
            return
        minimums = self.column_minimums(available)
        ratios = self._column_ratios()
        columns = self.visible_columns()
        # 접은 열이 쓰던 자리는 남은 열들이 비율대로 나눠 갖는다.
        share = sum(ratios[column] for column in columns) or 1.0
        widths = {
            column: max(minimums[column], round(available * ratios[column] / share))
            for column in columns
        }
        difference = available - sum(widths.values())
        if difference > 0:
            order = sorted(columns, key=lambda column: ratios[column], reverse=True)
            for offset in range(difference):
                widths[order[offset % len(order)]] += 1
        elif difference < 0:
            remaining = -difference
            while remaining:
                candidates = [
                    column for column in columns if widths[column] > minimums[column]
                ]
                if not candidates:
                    break
                column = max(candidates, key=lambda value: widths[value] - minimums[value])
                widths[column] -= 1
                remaining -= 1
        self._lend_to_title(widths, minimums)
        self._restoring_columns = True
        try:
            for column, width in widths.items():
                self.table.setColumnWidth(column, width)
        finally:
            self._restoring_columns = False

    # ------------------------------------------------------------- 내용 --
    def searching(self) -> bool:
        return bool(self.search.text().strip())

    @staticmethod
    def _pinned(row) -> bool:
        try:
            return bool(row["pinned"])
        except (IndexError, KeyError):
            return False

    @classmethod
    def _ordered(cls, rows) -> list:
        """고정한 것이 맨 위, 그다음 직접 끌어 옮긴 차례, 나머지는 최근 순."""
        pinned = [row for row in rows if cls._pinned(row)]
        rows = [row for row in rows if not cls._pinned(row)]
        moved = sorted(
            [row for row in rows if int(row["sort_order"] or 0)],
            key=lambda row: int(row["sort_order"]),
        )
        rest = sorted(
            [row for row in rows if not int(row["sort_order"] or 0)],
            key=lambda row: (str(row["updated_at"] or ""), int(row["id"])),
            reverse=True,
        )
        return pinned + moved + rest

    @staticmethod
    def _is_embedded(row) -> bool:
        try:
            return bool(row["embedded"])
        except (IndexError, KeyError):
            return False

    def set_rows(self, rows, selected_id: int | None = None) -> None:
        checked = set(self.checked_ids())
        if not self.searching():
            # 본문에 넣은 페이지는 그 메모의 줄로만 오간다.  목록에는 내놓지
            # 않되, 찾을 때는 보여 준다.  그러지 않으면 영영 못 찾는다.
            rows = [row for row in rows if not self._is_embedded(row)]
        self.rows_by_id = {int(row["id"]): row for row in rows}
        by_parent: dict[int, list] = {}
        for row in rows:
            parent = int(row["parent_id"] or TOP_LEVEL_PARENT)
            if parent not in self.rows_by_id:
                # 검색에 부모가 걸리지 않았어도 찾은 메모는 보여야 한다.
                parent = TOP_LEVEL_PARENT
            by_parent.setdefault(parent, []).append(row)
        for parent, group in by_parent.items():
            by_parent[parent] = self._ordered(group)
        blocked = self.table.blockSignals(True)
        try:
            # 지울 줄을 마우스가 아직 잡고 있으면 다음 그리기에서 프로그램이 꺼진다.
            self.table.forget_hover()
            self.table.clear()
            self._build_children(None, TOP_LEVEL_PARENT, by_parent, checked, set())
        finally:
            self.table.blockSignals(blocked)
        self._restore_expansion()
        has_rows = bool(rows)
        self.table.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows)
        if has_rows:
            self._resize_table_columns()
        if selected_id is not None:
            self.select_id(selected_id)
        self._sync_select_all_state()
        self._sync_fold_button()

    def _build_children(self, parent_item, parent_id, by_parent, checked, seen) -> None:
        for row in by_parent.get(parent_id, []):
            note_id = int(row["id"])
            if note_id in seen:
                continue
            seen.add(note_id)
            item = QTreeWidgetItem()
            self._fill_item(item, row, note_id in checked)
            if parent_item is None:
                self.table.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            self._build_children(item, note_id, by_parent, checked, seen)
            item.setData(self.TITLE_COLUMN, CHILD_COUNT_ROLE, item.childCount())

    def _fill_item(self, item: QTreeWidgetItem, row, checked: bool) -> None:
        note_id = int(row["id"])
        preview = plain_text_from_content(str(row["content"])).replace("\n", " ").strip()[:80]
        # DD3: both live in one column, so they must not look alike —
        # a reminder shows a clock, a D-Day shows a countdown chip.
        parts = []
        countdown = deadline_chip_text(row)
        if countdown:
            parts.append(("✓ " if is_deadline_done(row) else "▪ ") + countdown)
        reminder_text = reminder_display_text(str(row["reminder_due_at"] or ""))
        if reminder_text:
            parts.append(reminder_text)
        title = str(row["title"] or "제목 없음")
        if row["postit"]:
            title = f"{self.POSTIT_MARK} {title}"
        if self._pinned(row):
            title = f"{self.PINNED_MARK} {title}"
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        item.setData(0, PINNED_ROLE, self._pinned(row))
        item.setSizeHint(0, QSize(0, self.ROW_HEIGHT))
        for column, value in enumerate(
            ["", title, preview, "   ".join(parts), list_datetime(row["updated_at"])]
        ):
            if column:
                item.setText(column, value)
            item.setData(column, NOTE_ID_ROLE, note_id)
        item.setData(4, SORT_KEY_ROLE, str(row["updated_at"] or ""))
        # 좁은 창에서는 수정시간 열이 접히므로, 말풍선에 남겨 둔다.
        tip = [title]
        updated = list_datetime(row["updated_at"])
        if updated:
            tip.append(f"수정 {updated}")
        if row["postit"]:
            tip.append("포스트잇으로 띄워둔 메모입니다.")
        if self._pinned(row):
            tip.append("목록 맨 위에 고정한 메모입니다.")
        item.setToolTip(self.TITLE_COLUMN, "\n".join(tip))

    # --------------------------------------------------------- 펼침 상태 --
    def _saved_expanded(self) -> set[int]:
        raw = str(self.store.setting(self.EXPANDED_SETTING, "")) if self.store else ""
        try:
            return {int(value) for value in json.loads(raw)}
        except (TypeError, ValueError, json.JSONDecodeError):
            return set()

    def expanded_ids(self) -> list[int]:
        return [
            int(item.data(0, NOTE_ID_ROLE)) for item in self._walk()
            if item.childCount() and item.isExpanded()
        ]

    def _save_expanded(self, *_args) -> None:
        if self.store is None or self._restoring_expansion or self.searching():
            return
        self.store.set_setting(self.EXPANDED_SETTING, json.dumps(sorted(self.expanded_ids())))

    def _restore_expansion(self) -> None:
        """검색 중에는 다 펼친다.  찾은 메모가 접힌 부모에 가려지면 안 된다."""
        self._restoring_expansion = True
        try:
            if self.searching():
                self.table.expandAll()
                return
            wanted = self._saved_expanded()
            for item in self._walk():
                if not item.childCount():
                    continue
                item.setExpanded(int(item.data(0, NOTE_ID_ROLE)) in wanted)
        finally:
            self._restoring_expansion = False

    def has_children_anywhere(self) -> bool:
        return any(item.childCount() for item in self._walk())

    def _fold_shortcut_pressed(self) -> None:
        """목록이 화면에 없을 때는(다른 작업공간·접어 둔 목록) 못 들은 척한다."""
        if not self.isVisible() or not self.fold_button.isEnabled():
            return
        self.toggle_all_folds()

    RECENT_CHIPS = 3
    RECENT_CHIP_CHARS = 12

    def set_recent(self, rows) -> None:
        """최근에 본 메모를 칩으로 보여 준다.  눌러 바로 옮겨 간다."""
        wanted = list(rows)[: self.RECENT_CHIPS]
        while len(self.recent_buttons) < len(wanted):
            button = QPushButton()
            button.setObjectName("recentNoteChip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(self.BUTTON_HEIGHT - 4)
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self.recent_layout.insertWidget(len(self.recent_buttons), button)
            self.recent_buttons.append(button)
        for index, button in enumerate(self.recent_buttons):
            if index >= len(wanted):
                button.hide()
                continue
            note_id, title = wanted[index]
            text = str(title or "제목 없음")
            shown = text if len(text) <= self.RECENT_CHIP_CHARS else text[: self.RECENT_CHIP_CHARS - 1] + "…"
            button.setText("↩ " + shown)
            button.setToolTip(f"{text} 로 돌아갑니다")
            button.setAccessibleName(f"최근 본 메모 {text}")
            try:
                button.clicked.disconnect()
            except TypeError:
                pass
            button.clicked.connect(lambda _checked=False, value=int(note_id): self.recent_chosen.emit(value))
            button.show()
        self.recent_host.setVisible(bool(wanted))

    def toggle_all_folds(self) -> bool:
        """하위가 있는 메모를 한 번에 접거나 편다.  펼친 것이 있으면 접는다."""
        parents = [item for item in self._walk() if item.childCount()]
        if not parents:
            self._sync_fold_button()
            return False
        opening = not any(item.isExpanded() for item in parents)
        for item in parents:
            item.setExpanded(opening)
        self._sync_fold_button()
        return opening

    def _sync_fold_button(self) -> None:
        """단추 글자는 지금 누르면 무슨 일이 나는지를 적는다."""
        parents = [item for item in self._walk() if item.childCount()]
        self.fold_button.setEnabled(bool(parents))
        opened = any(item.isExpanded() for item in parents)
        self.fold_button.setText("모두 접기" if opened else "모두 펼치기")

    def expand_to(self, note_id: int) -> None:
        """그 메모가 보이도록 위쪽 메모를 모두 펼친다."""
        item = self._item_for(note_id)
        parent = None if item is None else item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    # ------------------------------------------------------------- 선택 --
    def _walk(self, parent: QTreeWidgetItem | None = None):
        if parent is None:
            children = [self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount())]
        else:
            children = [parent.child(i) for i in range(parent.childCount())]
        for child in children:
            if child is None:
                continue
            yield child
            yield from self._walk(child)

    def _item_for(self, note_id: int) -> QTreeWidgetItem | None:
        for item in self._walk():
            if int(item.data(0, NOTE_ID_ROLE)) == int(note_id):
                return item
        return None

    def row_count(self) -> int:
        """화면에 올라온 메모 수.  접혀서 보이지 않는 것도 센다."""
        return sum(1 for _item in self._walk())

    def select_id(self, note_id: int) -> None:
        item = self._item_for(note_id)
        if item is None:
            return
        self.expand_to(note_id)
        self.table.setCurrentItem(item)

    def checked_ids(self) -> list[int]:
        return [
            int(item.data(0, NOTE_ID_ROLE)) for item in self._walk()
            if item.checkState(0) == Qt.CheckState.Checked
        ]

    def export_ids(self) -> list[int]:
        return self.checked_ids() or [int(item.data(0, NOTE_ID_ROLE)) for item in self._walk()]

    def deletion_ids(self) -> list[int]:
        """Checked rows if any, else the row the user is standing on."""
        checked = self.checked_ids()
        if checked:
            return checked
        current = self.table.currentItem()
        if current is None:
            return []
        return [int(current.data(0, NOTE_ID_ROLE))]

    def toggle_all(self) -> None:
        items = list(self._walk())
        checked = bool(items) and all(
            item.checkState(0) == Qt.CheckState.Checked for item in items
        )
        self._set_all_checked(not checked)

    def _set_all_checked(self, checked) -> None:
        if not isinstance(checked, bool):
            checked = Qt.CheckState(checked) != Qt.CheckState.Unchecked
        blocked = self.table.blockSignals(True)
        try:
            state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            for item in self._walk():
                item.setCheckState(0, state)
        finally:
            self.table.blockSignals(blocked)
        self.table.viewport().update()
        self._sync_select_all_state()

    def _sync_select_all_state(self, *_args) -> None:
        items = list(self._walk())
        total = len(items)
        selected = sum(item.checkState(0) == Qt.CheckState.Checked for item in items)
        if selected == 0:
            state = Qt.CheckState.Unchecked
        elif selected == total:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        self.table_header.set_check_state(state)
        self._update_action_buttons(selected, total)

    def _update_action_buttons(self, selected: int, total: int) -> None:
        """Nothing checked means nothing to delete, so say so with the button."""
        self.export_button.setEnabled(total > 0)
        self.delete_button.setEnabled(selected > 0)
        self.delete_button.setText(f"선택 삭제 ({selected})" if selected else "선택 삭제")

    def _activate_row(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 and item is not None:
            self.note_selected.emit(int(item.data(0, NOTE_ID_ROLE)))
