import json
import re

from PyQt6.QtCore import QEvent, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit, QMenu,
    QPushButton, QComboBox, QStyle, QStyledItemDelegate, QStyleOptionButton, QStyleOptionViewItem,
    QSizePolicy, QToolTip, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .deadline import deadline_chip_text, is_deadline_done, reminder_display_text
from .rich_text import display_plain_text_from_content
from .sqlite_store import TOP_LEVEL_PARENT
from .title_symbols import (
    TitleValueCount, count_title_values, leading_title_prefix,
    leading_title_symbol, title_prefix_key, title_symbol_key,
)
from select_all_header import SelectAllHeader
from .title_filter_controls import TitleFilterControls

NOTE_ID_ROLE = Qt.ItemDataRole.UserRole
SORT_KEY_ROLE = Qt.ItemDataRole.UserRole + 1
CHILD_COUNT_ROLE = Qt.ItemDataRole.UserRole + 2
PINNED_ROLE = Qt.ItemDataRole.UserRole + 3
GROUP_ROLE = Qt.ItemDataRole.UserRole + 4


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


def list_datetime(value) -> str:
    """Compact list value; the title tooltip keeps the complete timestamp."""
    text = str(value or "")[:12]
    if len(text) != 12 or not text.isdigit():
        return ""
    return f"{text[4:6]}-{text[6:8]}"


def full_list_datetime(value) -> str:
    text = str(value or "")[:12]
    if len(text) != 12 or not text.isdigit():
        return ""
    return f"{text[:4]}-{text[4:6]}-{text[6:8]} {text[8:10]}:{text[10:12]}"


def color_dot_icon(value: str, size: int = 10) -> QIcon:
    color = QColor(str(value or "#94a3b8"))
    if not color.isValid():
        color = QColor("#94a3b8")
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


class ElidingStatusLabel(QLabel):
    """Keep the complete status in a tooltip while fitting the footer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""

    def setText(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._refresh_elision()

    def fullText(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_elision()

    def _refresh_elision(self) -> None:
        width = max(0, self.contentsRect().width() - 2)
        shown = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, width,
        ) if width else self._full_text
        QLabel.setText(self, shown)


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

    def createEditor(self, parent, option, index):
        if index.column() != 1:
            return None
        return super().createEditor(parent, option, index)

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
    range_checked = pyqtSignal()
    reorder_requested = pyqtSignal(int, int, int)
    siblings_reordered = pyqtSignal(int, list)
    reorder_blocked = pyqtSignal(str)

    PLUS_SIZE = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_arrow = None
        self._hover_row = None
        self._shift_anchor = None
        self._range_target = None
        self._range_base = None
        self._fold_chord_active = False
        self._fold_chord_used = False
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_row_menu)

    def _show_row_menu(self, point) -> None:
        """줄에서 오른쪽 단추.  지금은 목록 고정을 켜고 끈다."""
        item = self.itemAt(point)
        if item is None or item.data(0, NOTE_ID_ROLE) is None:
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
        self._shift_anchor = None
        self._range_target = None
        self._range_base = None

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

    def mousePressEvent(self, event) -> None:
        if self._fold_chord_active:
            self._fold_chord_used = True
        item = self.itemAt(event.position().toPoint())
        note_item = item is not None and item.data(0, NOTE_ID_ROLE) is not None
        if (
            event.button() == Qt.MouseButton.LeftButton and note_item
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._range_target = item
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and note_item:
            self._shift_anchor = item
            self._range_base = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._range_target is not None:
                target = self._range_target
                self._range_target = None
                anchor = self._shift_anchor or self.currentItem() or target
                items = self._visible_note_items()
                if anchor not in items:
                    anchor = target
                first, last = sorted((items.index(anchor), items.index(target)))
                if self._range_base is None:
                    self._range_base = {int(i.data(0, NOTE_ID_ROLE)) for i in items
                                        if i.checkState(0) == Qt.CheckState.Checked}
                blocked = self.blockSignals(True)
                try:
                    for index, item in enumerate(items):
                        checked = first <= index <= last or int(item.data(0, NOTE_ID_ROLE)) in self._range_base
                        item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                finally:
                    self.blockSignals(blocked)
                self._shift_anchor = anchor
                self.setCurrentItem(target)
                self.range_checked.emit()
                event.accept()
                return
            item = self.plus_item_at(event.position().toPoint())
            if item is not None:
                self.child_requested.emit(int(item.data(0, NOTE_ID_ROLE)))
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def _visible_note_items(self) -> list[QTreeWidgetItem]:
        items = []
        item = self.topLevelItem(0)
        while item is not None:
            if item.data(0, NOTE_ID_ROLE) is not None:
                items.append(item)
            item = self.itemBelow(item)
        return items

    def keyPressEvent(self, event) -> None:
        if (
            event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down)
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        ):
            if not self.dragEnabled():
                self.reorder_blocked.emit("기본 보기·기본 정렬에서 필터를 해제한 뒤 이동할 수 있습니다.")
                event.accept()
                return
            if self.state() == QAbstractItemView.State.EditingState:
                return super().keyPressEvent(event)
            item = self.currentItem()
            if item is not None and item.data(0, NOTE_ID_ROLE) is not None and self.dragEnabled():
                parent = item.parent()
                if parent is None:
                    index = self.indexOfTopLevelItem(item)
                    parent_id = TOP_LEVEL_PARENT
                    count = self.topLevelItemCount()
                else:
                    index = parent.indexOfChild(item)
                    parent_id = int(parent.data(0, NOTE_ID_ROLE))
                    count = parent.childCount()
                target = index + (-1 if event.key() == Qt.Key.Key_Up else 1)
                siblings = ([self.topLevelItem(i) for i in range(count)] if parent is None
                            else [parent.child(i) for i in range(count)])
                checked = [i for i in self._visible_note_items() if i.checkState(0) == Qt.CheckState.Checked]
                if len(checked) > 1:
                    if any(i.parent() is not parent for i in checked):
                        self.reorder_blocked.emit("같은 부모 아래의 메모만 함께 이동할 수 있습니다.")
                    else:
                        self._move_checked_siblings(siblings, checked, parent_id, event.key() == Qt.Key.Key_Up)
                    event.accept()
                    return
                if 0 <= target < count:
                    if bool(siblings[target].data(0, PINNED_ROLE)) == bool(item.data(0, PINNED_ROLE)):
                        self.reorder_requested.emit(int(item.data(0, NOTE_ID_ROLE)), parent_id, target)
                    else:
                        self.reorder_blocked.emit("고정 메모와 일반 메모의 경계를 넘어 이동할 수 없습니다.")
            event.accept()
            return
        if self._fold_chord_active and event.key() not in {
            Qt.Key.Key_Control, Qt.Key.Key_Shift,
        }:
            self._fold_chord_used = True
        if event.key() in {Qt.Key.Key_Control, Qt.Key.Key_Shift} and not event.isAutoRepeat():
            modifiers = event.modifiers()
            modifiers |= (
                Qt.KeyboardModifier.ControlModifier
                if event.key() == Qt.Key.Key_Control
                else Qt.KeyboardModifier.ShiftModifier
            )
            both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
            if modifiers & both == both:
                self._fold_chord_active = True
                self._fold_chord_used = False
        super().keyPressEvent(event)

    def _move_checked_siblings(self, siblings, checked, parent_id, upward):
        selected = {int(i.data(0, NOTE_ID_ROLE)) for i in checked}
        if len({bool(i.data(0, PINNED_ROLE)) for i in checked}) > 1:
            self.reorder_blocked.emit("고정 상태가 같은 메모끼리 이동해 주세요.")
            return
        order = list(siblings)
        indexes = range(1, len(order)) if upward else range(len(order) - 2, -1, -1)
        changed = False
        for index in indexes:
            target = index - 1 if upward else index + 1
            current, neighbor = order[index], order[target]
            if (int(current.data(0, NOTE_ID_ROLE)) in selected
                    and int(neighbor.data(0, NOTE_ID_ROLE)) not in selected
                    and bool(current.data(0, PINNED_ROLE)) == bool(neighbor.data(0, PINNED_ROLE))):
                order[index], order[target] = neighbor, current
                changed = True
        if changed:
            self.siblings_reordered.emit(parent_id, [int(i.data(0, NOTE_ID_ROLE)) for i in order])

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride and getattr(self, "_fold_chord_active", False):
            if event.key() not in (Qt.Key.Key_Control, Qt.Key.Key_Shift):
                self._fold_chord_used = True
        if event.type() in (QEvent.Type.FocusOut, QEvent.Type.WindowDeactivate, QEvent.Type.Hide):
            self._fold_chord_active = False
        return super().event(event)

    def keyReleaseEvent(self, event) -> None:
        if (
            event.key() in {Qt.Key.Key_Control, Qt.Key.Key_Shift}
            and self._fold_chord_active and not event.isAutoRepeat()
        ):
            should_toggle = not self._fold_chord_used
            self._fold_chord_active = False
            self._fold_chord_used = False
            item = self.currentItem()
            if should_toggle and item is not None and item.childCount():
                item.setExpanded(not item.isExpanded())
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        self._fold_chord_active = False
        self._fold_chord_used = False
        super().focusOutEvent(event)

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


class MemoListPanel(TitleFilterControls, QWidget):
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
    filters_changed = pyqtSignal()
    category_settings_requested = pyqtSignal()
    category_assign_requested = pyqtSignal(list, object)
    group_requested = pyqtSignal(list, str)
    siblings_reordered = pyqtSignal(int, list)
    note_rename_requested = pyqtSignal(int, str)

    # 번호 carried no information the row order did not already show, and 표시
    # spent a whole column on one word; it is now a mark in front of the title.
    # 머리글 글자가 곧 그 열의 최소 폭이다.  좁은 목록에서 제목이 잘리던 가장
    # 큰 까닭이라 이름을 짧게 줄였다.  열에 담기는 내용은 그대로다.
    HEADERS = ["", "제목", "카테고리", "수정일"]
    COLUMN_WEIGHTS = (28, 300, 72, 48)
    NARROW_WIDTH = 380
    FOLDABLE_COLUMN = 3
    # 모두 접기·펼치기 단축키.  이 창이 앞에 있을 때만 듣는다.  본문 토글은
    # 편집 구역의 Ctrl+Shift+E 가 따로 맡고 있어 글자를 겹치지 않게 골랐다.
    FOLD_ALL_SHORTCUT = "Ctrl+Shift+A"
    # 제목이 잘릴 때 폭을 빌려 오는 차례.
    BORROW_ORDER = (3, 2)
    # Floor per column; the real minimum also has to fit the header text, which
    # is measured at runtime so every title stays readable at the narrowest width.
    COLUMN_FLOORS = (28, 62, 62, 48)
    HEADER_PADDING = 20
    # A column may not be dragged below this share of the width it would get from
    # the default proportions, so the minimum follows the splitter, not a constant.
    MIN_SHARE_OF_DEFAULT = 0.55
    POSTIT_MARK = "📌"
    PINNED_MARK = "⭐"
    TITLE_COLUMN = 1
    # 한 줄에 제목 한 줄만 들어간다.  48px 은 빈 위아래 여백이 너무 넓었다.
    ROW_HEIGHT = 28
    # 목록 위아래의 단추와 검색칸 높이.  낮출수록 목록이 길어진다.
    BUTTON_HEIGHT = 28
    HEADER_HEIGHT = 29
    COLUMN_RATIOS_SETTING = "memo_list_column_ratios_v2"
    EXPANDED_SETTING = "memo_list_expanded_ids"
    FILTER_SETTING = "memo_category_filter"
    VIEW_SETTING = "memo_category_view"
    SORT_SETTING = "memo_category_sort"

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self.store = store
        self._restoring_columns = False
        self._restoring_expansion = False
        self.title_symbol_filter: str | None = None
        self.title_prefix_filter: str | None = None
        self._title_symbol_counts: list[TitleValueCount] = []
        self._title_prefix_counts: list[TitleValueCount] = []
        self._inline_editing_id: int | None = None
        self.setObjectName("memoListPanel")
        self.rows_by_id: dict[int, object] = {}
        layout = QVBoxLayout(self)
        # Responsive controls move into "더보기" below 480px.  Let the panel
        # reach that width before the child layouts have switched state.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
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

        search_host = QWidget()
        search_row = QHBoxLayout(search_host)
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("메모 제목과 내용 검색")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("알림 메모 검색")
        self.search.setFixedHeight(self.BUTTON_HEIGHT)
        search_row.addWidget(self.search, 1)
        self.title_symbol_button = QPushButton("기호 ▾")
        self.title_symbol_button.setObjectName("memoTitleSymbolFilter")
        self.title_symbol_button.setCheckable(True)
        self.title_symbol_button.setAccessibleName("제목 첫 기호 필터")
        self.title_symbol_button.setToolTip("제목 맨 앞의 이모지·기호로 메모를 모아 봅니다.")
        self.title_symbol_button.setFixedHeight(self.BUTTON_HEIGHT)
        self.title_symbol_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.title_symbol_button.clicked.connect(self._show_title_symbol_menu)
        search_row.addWidget(self.title_symbol_button)
        self.title_prefix_button = QPushButton("머리말")
        self.title_prefix_button.setObjectName("memoTitlePrefixFilter")
        self.title_prefix_button.setCheckable(True)
        self.title_prefix_button.setAccessibleName("제목 머리말 필터")
        self.title_prefix_button.setFixedHeight(self.BUTTON_HEIGHT)
        self.title_prefix_button.setMinimumWidth(0)
        self.title_prefix_button.setMaximumWidth(120)
        self.title_prefix_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.title_prefix_button.clicked.connect(self._show_title_prefix_menu)
        search_row.addWidget(self.title_prefix_button)
        self.search.setMinimumWidth(120)
        layout.addWidget(search_host)

        self.filter_host = QWidget()
        filter_row = QHBoxLayout(self.filter_host)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(4)
        self.category_filter_buttons: list[QPushButton] = []
        self.category_filter_id = self._saved_category_filter()
        self.category_chip_host = QWidget()
        self.category_chip_host.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.category_chip_layout = QHBoxLayout(self.category_chip_host)
        self.category_chip_layout.setContentsMargins(0, 0, 0, 0)
        self.category_chip_layout.setSpacing(4)
        filter_row.addWidget(self.category_chip_host, 1)
        self.reset_filters_button = QPushButton("↺ 필터 초기화")
        self.reset_filters_button.setObjectName("memoResetFiltersButton")
        self.reset_filters_button.setAccessibleName("필터 초기화")
        self.reset_filters_button.setToolTip("카테고리·검색·기호·머리말 필터를 모두 풉니다")
        self.reset_filters_button.setFixedHeight(self.BUTTON_HEIGHT)
        self.reset_filters_button.clicked.connect(self.reset_all_filters)
        self.reset_filters_button.hide()
        filter_row.addWidget(self.reset_filters_button)
        self.search.textChanged.connect(lambda _text: self._layout_category_filters())
        self.more_categories_button = QPushButton("더보기")
        self.more_categories_button.setObjectName("memoMoreCategoriesButton")
        self.more_categories_button.setCheckable(True)
        self.more_categories_button.setFixedHeight(self.BUTTON_HEIGHT)
        self.more_categories_button.setMaximumWidth(120)
        self.more_categories_button.clicked.connect(self._show_more_categories)
        filter_row.addWidget(self.more_categories_button)
        layout.addWidget(self.filter_host)
        self.view_combo = NoWheelComboBox(self)
        self.view_combo.addItem("보기: 기본", "default")
        self.view_combo.addItem("보기: 카테고리별", "category")
        self.sort_combo = NoWheelComboBox(self)
        for label, value in (
            ("정렬: 기본", "default"), ("수정일 최근순", "updated_desc"),
            ("수정일 오래된순", "updated_asc"), ("제목 가나다순", "title_asc"),
            ("제목 역순", "title_desc"),
        ):
            self.sort_combo.addItem(label, value)
        for combo in (self.view_combo, self.sort_combo):
            combo.hide()  # Settings models only; all interaction lives in More.
        self._controls_in_more = True
        self.recent_toggle = QPushButton("최근 ▸")
        self.recent_toggle.setObjectName("compactUtilityButton")
        self.recent_toggle.setFixedHeight(self.BUTTON_HEIGHT)
        self.recent_toggle.setCheckable(True)
        self.recent_toggle.setAccessibleName("최근 본 메모 펼치기")
        self.recent_toggle.clicked.connect(self._toggle_recent)
        self.recent_toggle.hide()
        filter_row.insertWidget(1, self.recent_toggle)
        self._restore_combo(self.view_combo, self.store.setting(self.VIEW_SETTING, "default") if self.store else "default")
        self._restore_combo(self.sort_combo, self.store.setting(self.SORT_SETTING, "default") if self.store else "default")
        self.view_combo.currentIndexChanged.connect(self._filter_controls_changed)
        self.sort_combo.currentIndexChanged.connect(self._filter_controls_changed)
        self.refresh_category_filters()

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
        self.table.itemChanged.connect(self._inline_title_changed)
        self.table.itemExpanded.connect(self._sync_fold_button)
        self.table.itemCollapsed.connect(self._sync_fold_button)
        self.table.itemExpanded.connect(self._save_expanded)
        self.table.itemCollapsed.connect(self._save_expanded)
        # 펼치면 한 층 더 들어간 제목이 나타난다.  그때마다 폭을 다시 잡는다.
        self.table.itemExpanded.connect(self._resize_table_columns)
        self.table.itemCollapsed.connect(self._resize_table_columns)
        self.table.note_moved.connect(self.note_moved)
        self.table.reorder_requested.connect(self.note_moved)
        self.table.siblings_reordered.connect(self.siblings_reordered)
        self.table.reorder_blocked.connect(self._show_reorder_reason)
        self.count_delegate.closeEditor.connect(self._end_inline_rename)
        self.table.child_requested.connect(self.child_requested)
        self.table.pin_toggled.connect(self.pin_toggled)
        self.table.range_checked.connect(self._sync_select_all_state)
        self.table_header.check_state_changed.connect(self._set_all_checked)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("메모가 없습니다.\n편집 구역에 바로 입력하거나 새 메모를 만들어 주세요.")
        self.empty_label.setObjectName("memoEmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label, 1)

        self.filtered_empty_host = QWidget()
        self.filtered_empty_host.setObjectName("memoFilteredEmptyState")
        filtered_empty_layout = QVBoxLayout(self.filtered_empty_host)
        filtered_empty_layout.addStretch(1)
        self.filtered_empty_message = QLabel("조건에 맞는 메모가 없습니다.")
        self.filtered_empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        filtered_empty_layout.addWidget(self.filtered_empty_message)
        self.filtered_empty_summary = QLabel()
        self.filtered_empty_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.filtered_empty_summary.setWordWrap(True)
        filtered_empty_layout.addWidget(self.filtered_empty_summary)
        self.clear_title_filters_button = QPushButton("기호·머리말 필터 해제")
        self.clear_title_filters_button.setObjectName("memoClearTitleFiltersButton")
        self.clear_title_filters_button.setFixedHeight(self.BUTTON_HEIGHT)
        self.clear_title_filters_button.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self.clear_title_filters_button.clicked.connect(self.clear_title_filters)
        filtered_empty_layout.addWidget(
            self.clear_title_filters_button, 0, Qt.AlignmentFlag.AlignHCenter
        )
        filtered_empty_layout.addStretch(1)
        self.filtered_empty_host.hide()
        layout.addWidget(self.filtered_empty_host, 1)

        self.actions_host = QWidget()
        actions = QHBoxLayout(self.actions_host)
        actions.setContentsMargins(0, 0, 0, 0)
        self.export_button = QPushButton("Excel 내보내기")
        self.delete_button = QPushButton("선택 삭제")
        self.delete_button.setObjectName("dangerButton")
        for button in (self.export_button, self.delete_button):
            button.setFixedHeight(self.BUTTON_HEIGHT)
        self.selection_chip = QLabel()
        self.selection_chip.setObjectName("selectedMemoCountChip")
        self.selection_chip.setFixedHeight(self.BUTTON_HEIGHT)
        self.selection_chip.hide()
        actions.addWidget(self.selection_chip)
        actions.addWidget(self.export_button)
        self.action_status = ElidingStatusLabel()
        self.action_status.setObjectName("memoStatus")
        self.action_status.setProperty("level", "info")
        self.action_status.setFixedHeight(self.BUTTON_HEIGHT)
        self.action_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        actions.addWidget(self.action_status, 1)
        self.bulk_category_button = QPushButton("카테고리 지정 ▾")
        self.bulk_category_button.setFixedHeight(self.BUTTON_HEIGHT)
        self.bulk_category_button.clicked.connect(self._show_bulk_category_menu)
        self.bulk_category_button.hide()
        actions.addWidget(self.bulk_category_button)
        self.group_button = QPushButton("묶기")
        self.group_button.setObjectName("compactUtilityButton")
        self.group_button.setFixedHeight(self.BUTTON_HEIGHT)
        self.group_button.setToolTip("선택한 메모를 새 부모 메모 아래로 묶습니다")
        self.group_button.clicked.connect(self._request_group)
        self.group_button.hide()
        actions.addWidget(self.group_button)
        actions.addWidget(self.delete_button)
        self.delete_button.hide()
        layout.addWidget(self.actions_host)
        self.export_button.clicked.connect(self.export_requested.emit)
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self._update_title_symbol_button()
        self._update_title_prefix_button()

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
        self._sync_responsive_filter_controls(event.size().width())
        self._layout_category_filters()
        self._resize_table_columns()

    def _show_reorder_reason(self, text: str) -> None:
        self.action_status.setText(text)
        QToolTip.showText(self.table.mapToGlobal(self.table.rect().center()), text, self.table)

    def _sync_responsive_filter_controls(self, width: int | None = None) -> None:
        # Keep the existing resize hook, but never put these back in the row.
        for combo in (self.view_combo, self.sort_combo):
            combo.hide()
        if hasattr(self, "title_prefix_button"):
            self._update_title_prefix_button()

    def _saved_category_filter(self):
        if self.store is None:
            return None
        raw = str(self.store.setting(self.FILTER_SETTING, "") or "")
        if raw == "none":
            return "none"
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if self.store.category(value) is not None else None

    @staticmethod
    def _restore_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(str(value))
        combo.setCurrentIndex(max(0, index))

    def refresh_category_filters(self) -> None:
        if (
            self.category_filter_id not in (None, "none")
            and (self.store is None or self.store.category(self.category_filter_id) is None)
        ):
            self.category_filter_id = None
            if self.store is not None:
                self.store.set_setting(self.FILTER_SETTING, "")
        while self.category_chip_layout.count():
            item = self.category_chip_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.category_filter_buttons = []
        category_rows = list(self.store.categories() if self.store else [])
        choices = [(None, "전체", "")] + [
            (int(row["id"]), str(row["name"]), str(row["color"])) for row in category_rows
        ] + [("none", "미지정", "")]
        for category_id, label, color in choices:
            button = QPushButton(label)
            button.setObjectName("memoCategoryFilterChip")
            button.setCheckable(True)
            button.setChecked(category_id == self.category_filter_id)
            button.setFixedHeight(self.BUTTON_HEIGHT)
            button.setProperty("category_id", category_id)
            if color:
                button.setIcon(color_dot_icon(color))
            button.clicked.connect(lambda _checked=False, value=category_id: self._set_category_filter(value))
            self.category_chip_layout.addWidget(button)
            self.category_filter_buttons.append(button)
        self.category_chip_layout.addStretch(1)
        self._layout_category_filters()

    def _layout_category_filters(self) -> None:
        if not hasattr(self, "category_filter_buttons"):
            return
        filtered = self._has_any_filter()
        scale = self._filter_scale()
        compact_reset = self.width() <= round(300 * scale)
        self.reset_filters_button.setText("↺" if compact_reset else "↺ 필터 초기화")
        self.reset_filters_button.setFixedWidth(round(28 * scale) if compact_reset else self.reset_filters_button.sizeHint().width())
        self.reset_filters_button.setVisible(filtered)
        available = max(0, self.filter_host.width() - self.more_categories_button.sizeHint().width() - 4
                        - (self.reset_filters_button.width() + 4 if filtered else 0)
                        - (self.recent_toggle.sizeHint().width() + 4 if not self.recent_toggle.isHidden() else 0))
        used = 0
        hidden_buttons = []
        for button in self.category_filter_buttons:
            width = button.sizeHint().width() + 4
            visible = used + width <= available or button.property("category_id") is None
            button.setVisible(visible)
            used += width if visible else 0
            if not visible:
                hidden_buttons.append(button)
        selected_hidden = next(
            (
                button for button in hidden_buttons
                if button.property("category_id") == self.category_filter_id
            ),
            None,
        )
        self.more_categories_button.setText(
            selected_hidden.text() if selected_hidden is not None else "더보기"
        )
        self.more_categories_button.setIcon(
            selected_hidden.icon() if selected_hidden is not None else
            color_dot_icon("#3b82f6", 8) if self._custom_view_or_sort() else QIcon()
        )
        self.more_categories_button.setChecked(selected_hidden is not None)
        self.more_categories_button.setToolTip(
            selected_hidden.text() if selected_hidden is not None else
            "보기·정렬이 기본값이 아닙니다" if self._custom_view_or_sort() else
            "카테고리·보기·정렬 및 카테고리 설정"
        )
        self.more_categories_button.setVisible(True)

    def _custom_view_or_sort(self) -> bool:
        return self.view_combo.currentData() != "default" or self.sort_combo.currentData() != "default"

    def _build_more_categories_menu(self) -> QMenu:
        old = getattr(self, "more_categories_menu", None)
        if old is not None:
            old.deleteLater()
        menu = QMenu(self.more_categories_button)
        hidden = [button for button in self.category_filter_buttons if button.isHidden()]
        if hidden:
            menu.addAction("카테고리").setEnabled(False)
        for button in hidden:
            action = menu.addAction(button.text().replace("&", "&&"))
            action.setData(button.property("category_id"))
            action.setIcon(button.icon())
            action.setCheckable(True)
            action.setChecked(button.property("category_id") == self.category_filter_id)
            action.triggered.connect(
                lambda _checked=False, value=button.property("category_id"): self._set_category_filter(value)
            )
        if hidden:
            menu.addSeparator()
        for label, combo in (("보기", self.view_combo), ("정렬", self.sort_combo)):
            submenu = menu.addMenu(label)
            for index in range(combo.count()):
                action = submenu.addAction(combo.itemText(index).removeprefix(f"{label}: "))
                action.setData(combo.itemData(index))
                action.setCheckable(True)
                action.setChecked(index == combo.currentIndex())
                action.triggered.connect(
                    lambda _checked=False, value=index, model=combo: model.setCurrentIndex(value)
                )
        menu.addSeparator()
        menu.addAction("⚙ 카테고리 설정…").triggered.connect(self.category_settings_requested.emit)
        self.more_categories_menu = menu
        return menu

    def _show_more_categories(self) -> None:
        try:
            self._build_more_categories_menu().exec(
                self.more_categories_button.mapToGlobal(self.more_categories_button.rect().bottomLeft()))
        finally:
            self._layout_category_filters()

    def _set_category_filter(self, category_id) -> None:
        self.category_filter_id = (
            None if category_id is None else "none" if category_id == "none" else int(category_id)
        )
        if self.store:
            self.store.set_setting(
                self.FILTER_SETTING, "" if self.category_filter_id is None else str(self.category_filter_id),
            )
        for button in self.category_filter_buttons:
            button.setChecked(button.property("category_id") == self.category_filter_id)
        self._layout_category_filters()
        self.filters_changed.emit()

    def _show_title_symbol_menu(self) -> None:
        self._show_title_menu("symbol")

    def _set_title_symbol_filter(self, symbol: str | None) -> None:
        self.title_symbol_filter = title_symbol_key(symbol) if symbol else None
        self._update_title_symbol_button()
        self._layout_category_filters()
        self.filters_changed.emit()

    def _set_title_prefix_filter(self, key: str | None) -> None:
        self.title_prefix_filter = title_prefix_key(key) if key else None
        self._update_title_prefix_button()
        self._layout_category_filters()
        self.filters_changed.emit()

    def clear_title_filters(self) -> None:
        if self.title_symbol_filter is None and self.title_prefix_filter is None:
            return
        self.title_symbol_filter = None
        self.title_prefix_filter = None
        self._update_title_symbol_button()
        self._update_title_prefix_button()
        self._layout_category_filters()
        self.filters_changed.emit()

    def _update_title_symbol_button(self) -> None:
        self._update_title_button("symbol")

    def _filter_controls_changed(self, *_args) -> None:
        if self.store:
            self.store.set_setting(self.VIEW_SETTING, str(self.view_combo.currentData()))
            self.store.set_setting(self.SORT_SETTING, str(self.sort_combo.currentData()))
        self._layout_category_filters()
        self.filters_changed.emit()

    def _show_bulk_category_menu(self) -> None:
        ids = self.checked_ids()
        if not ids:
            return
        menu = QMenu(self.bulk_category_button)
        action = menu.addAction("미지정")
        action.triggered.connect(lambda: self.category_assign_requested.emit(ids, None))
        for row in self.store.categories() if self.store else []:
            action = menu.addAction(str(row["name"]))
            action.triggered.connect(
                lambda _checked=False, category_id=int(row["id"]):
                self.category_assign_requested.emit(ids, category_id)
            )
        self.bulk_category_menu = menu
        menu.exec(self.bulk_category_button.mapToGlobal(self.bulk_category_button.rect().topLeft()))

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

    def _ordered(self, rows) -> list:
        """고정한 것이 맨 위, 그다음 직접 끌어 옮긴 차례, 나머지는 최근 순."""
        pinned = [row for row in rows if self._pinned(row)]
        rows = [row for row in rows if not self._pinned(row)]
        mode = str(self.sort_combo.currentData()) if hasattr(self, "sort_combo") else "default"
        if mode != "default":
            reverse = mode in {"updated_desc", "title_desc"}
            key = (
                (lambda row: (str(row["updated_at"] or ""), int(row["id"])))
                if mode.startswith("updated") else
                (lambda row: (str(row["title"] or "").casefold(), int(row["id"])))
            )
            return sorted(pinned, key=key, reverse=reverse) + sorted(rows, key=key, reverse=reverse)
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

    @staticmethod
    def _row_symbol_key(row) -> str | None:
        symbol = leading_title_symbol(str(row["title"] or ""))
        return title_symbol_key(symbol) if symbol is not None else None

    @staticmethod
    def _row_prefix_key(row) -> str | None:
        prefix = leading_title_prefix(str(row["title"] or ""))
        return title_prefix_key(prefix) if prefix is not None else None

    def _set_empty_state(self, has_rows: bool) -> None:
        filtered = (
            self.category_filter_id is not None or self.searching()
            or self.title_symbol_filter is not None or self.title_prefix_filter is not None
        )
        self.empty_label.setVisible(not has_rows and not filtered)
        self.filtered_empty_host.setVisible(not has_rows and filtered)
        if has_rows or not filtered:
            return
        labels = []
        if self.category_filter_id == "none":
            labels.append("● 미지정")
        elif self.category_filter_id is not None and self.store is not None:
            category = self.store.category(self.category_filter_id)
            if category is not None:
                labels.append(f"● {category['name']}")
        if self.searching():
            labels.append(f"검색: {self.search.text().strip()}")
        if self.title_symbol_filter is not None:
            value = next(
                (entry for entry in self._title_symbol_counts if entry.key == self.title_symbol_filter),
                None,
            )
            labels.append(value.display if value is not None else self.title_symbol_filter)
        if self.title_prefix_filter is not None:
            value = next(
                (entry for entry in self._title_prefix_counts if entry.key == self.title_prefix_filter),
                None,
            )
            labels.append(f"[{value.display if value is not None else self.title_prefix_filter}]")
        self.filtered_empty_summary.setText(" · ".join(labels))
        self.clear_title_filters_button.setVisible(
            self.title_symbol_filter is not None or self.title_prefix_filter is not None
        )

    def set_rows(self, rows, selected_id: int | None = None) -> None:
        rows = list(rows)
        live_ids = {int(row["id"]) for row in rows}
        self._preview_cache = {key: value for key, value in getattr(self, "_preview_cache", {}).items()
                               if key in live_ids}
        checked = set(self.checked_ids())
        if not self.searching():
            # 본문에 넣은 페이지는 그 메모의 줄로만 오간다.  목록에는 내놓지
            # 않되, 찾을 때는 보여 준다.  그러지 않으면 영영 못 찾는다.
            rows = [row for row in rows if not self._is_embedded(row)]
        if self.category_filter_id == "none":
            rows = [row for row in rows if row["category_id"] is None]
        elif self.category_filter_id is not None:
            rows = [
                row for row in rows
                if row["category_id"] is not None and int(row["category_id"]) == self.category_filter_id
            ]
        symbol_rows = [
            row for row in rows
            if self.title_prefix_filter is None
            or self._row_prefix_key(row) == self.title_prefix_filter
        ]
        prefix_rows = [
            row for row in rows
            if self.title_symbol_filter is None
            or self._row_symbol_key(row) == self.title_symbol_filter
        ]
        self._title_symbol_counts = count_title_values(
            symbol_rows, leading_title_symbol, title_symbol_key
        )
        self._title_prefix_counts = count_title_values(
            prefix_rows, leading_title_prefix, title_prefix_key
        )
        self._update_title_symbol_button()
        self._update_title_prefix_button()
        self._layout_category_filters()
        rows = [
            row for row in rows
            if (self.title_symbol_filter is None
                or self._row_symbol_key(row) == self.title_symbol_filter)
            and (self.title_prefix_filter is None
                 or self._row_prefix_key(row) == self.title_prefix_filter)
        ]
        self.rows_by_id = {int(row["id"]): row for row in rows}
        if self.title_symbol_filter is not None or self.title_prefix_filter is not None:
            self._set_flat_rows(rows, checked)
            if selected_id is not None:
                self.select_id(selected_id)
            return
        if str(self.view_combo.currentData()) == "category":
            self._set_category_rows(rows, checked)
            if selected_id is not None:
                self.select_id(selected_id)
            return
        can_move = (not self.searching() and self.category_filter_id is None
                    and self.sort_combo.currentData() == "default")
        self.table.setDragEnabled(can_move)
        self.table.setToolTip("Ctrl+↑/↓: 같은 부모 안에서 이동" if can_move else
                             "기본 보기·기본 정렬에서 필터를 해제하면 순서를 이동할 수 있습니다.")
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
        self._set_empty_state(has_rows)
        if has_rows:
            self._resize_table_columns()
        if selected_id is not None:
            self.select_id(selected_id)
        self._sync_select_all_state()
        self._sync_fold_button()

    def _set_category_rows(self, rows, checked: set[int]) -> None:
        blocked = self.table.blockSignals(True)
        try:
            self.table.forget_hover()
            self.table.clear()
            groups = [(int(row["id"]), str(row["name"])) for row in (self.store.categories() if self.store else [])]
            groups.append((None, "미지정"))
            for category_id, label in groups:
                members = [
                    row for row in rows
                    if (None if row["category_id"] is None else int(row["category_id"])) == category_id
                ]
                if not members:
                    continue
                group = QTreeWidgetItem(["", f"{label} ({len(members)})", "", ""])
                group.setData(0, GROUP_ROLE, True)
                group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.addTopLevelItem(group)
                for row in self._ordered(members):
                    item = QTreeWidgetItem()
                    self._fill_item(item, row, int(row["id"]) in checked)
                    parent_id = int(row["parent_id"] or 0)
                    if parent_id:
                        path = self.store.note_path(int(row["id"]))
                        item.setToolTip(self.TITLE_COLUMN, item.toolTip(self.TITLE_COLUMN) + "\n원래 위치: " + " › ".join(str(p["title"]) for p in path))
                    group.addChild(item)
                group.setExpanded(True)
        finally:
            self.table.blockSignals(blocked)
        self.table.setDragEnabled(False)
        has_rows = bool(rows)
        self.table.setVisible(has_rows)
        self._set_empty_state(has_rows)
        if has_rows:
            self._resize_table_columns()
        self._sync_select_all_state()
        self._sync_fold_button()

    def _set_flat_rows(self, rows, checked: set[int]) -> None:
        """Filtered results are flat so dragging cannot alter the real hierarchy."""
        blocked = self.table.blockSignals(True)
        try:
            self.table.forget_hover()
            self.table.clear()
            for row in self._ordered(rows):
                item = QTreeWidgetItem()
                self._fill_item(item, row, int(row["id"]) in checked)
                parent_id = int(row["parent_id"] or 0)
                if parent_id and self.store is not None:
                    path = self.store.note_path(int(row["id"]))
                    item.setToolTip(
                        self.TITLE_COLUMN,
                        item.toolTip(self.TITLE_COLUMN)
                        + "\n원래 위치: "
                        + " › ".join(str(part["title"]) for part in path),
                    )
                self.table.addTopLevelItem(item)
        finally:
            self.table.blockSignals(blocked)
        self.table.setDragEnabled(False)
        has_rows = bool(rows)
        self.table.setVisible(has_rows)
        self._set_empty_state(has_rows)
        if has_rows:
            self._resize_table_columns()
        self._sync_select_all_state()
        self._sync_fold_button()
        self.fold_button.setEnabled(False)

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
        content = str(row["content"])
        cache = getattr(self, "_preview_cache", {})
        cached = cache.get(int(row["id"]))
        if cached is None or cached[0] != content:
            cached = (content, display_plain_text_from_content(content).replace("\n", " ").strip()[:80])
            cache[int(row["id"])] = cached
        self._preview_cache = cache
        preview = cached[1]
        # DD3: both live in one column, so they must not look alike —
        # a reminder shows a clock, a D-Day shows a countdown chip.
        parts = []
        countdown = deadline_chip_text(row)
        if countdown:
            parts.append(("✓ " if is_deadline_done(row) else "▪ ") + countdown)
        reminder_text = reminder_display_text(str(row["reminder_due_at"] or ""))
        if reminder_text:
            parts.append(reminder_text)
        raw_title = str(row["title"] or "제목 없음")
        title = raw_title
        conflict_sync_id = str(row["conflict_of_sync_id"] or "")
        if conflict_sync_id:
            title = f"⚠ 충돌 · {title}"
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
        category = None if row["category_id"] is None or self.store is None else self.store.category(int(row["category_id"]))
        category_name = str(category["name"]) if category is not None else "미지정"
        category_text = category_name if category is not None else "—"
        for column, value in enumerate(["", title, category_text, list_datetime(row["updated_at"]) ]):
            if column:
                item.setText(column, value)
            item.setData(column, NOTE_ID_ROLE, note_id)
        if category is not None:
            item.setIcon(2, color_dot_icon(str(category["color"])))
        item.setToolTip(2, category_name)
        item.setToolTip(3, full_list_datetime(row["updated_at"]))
        item.setData(3, SORT_KEY_ROLE, str(row["updated_at"] or ""))
        # 좁은 창에서는 수정시간 열이 접히므로, 말풍선에 남겨 둔다.
        tip = [title]
        updated = full_list_datetime(row["updated_at"])
        if updated:
            tip.append(f"수정 {updated}")
        if preview:
            tip.append(f"내용: {preview}")
        if parts:
            tip.append("일정: " + "   ".join(parts))
        tip.append(f"카테고리: {category_name}")
        if conflict_sync_id:
            original = self.store.note_by_sync_id(conflict_sync_id, include_trashed=True) if self.store else None
            original_title = str(original["title"]) if original is not None else conflict_sync_id
            tip.extend((f"충돌 사본 · 원본: {original_title}", "두 버전을 비교한 뒤 정리해 주세요."))
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
            int(item.data(0, NOTE_ID_ROLE)) for item in self._note_items()
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
                note_id = item.data(0, NOTE_ID_ROLE)
                item.setExpanded(True if note_id is None else int(note_id) in wanted)
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
        self.recent_toggle.setVisible(bool(wanted))
        if not wanted:
            self.recent_toggle.setChecked(False)
        self._sync_recent_visibility()

    def _toggle_recent(self, checked: bool) -> None:
        self.recent_toggle.setText("최근 ▾" if checked else "최근 ▸")
        self.recent_toggle.setAccessibleName(
            "최근 본 메모 접기" if checked else "최근 본 메모 펼치기"
        )
        self._sync_recent_visibility()

    def _sync_recent_visibility(self) -> None:
        has_recent = any(not button.isHidden() for button in self.recent_buttons)
        self.recent_host.setVisible(has_recent and self.recent_toggle.isChecked())

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

    def _note_items(self):
        return (item for item in self._walk() if item.data(0, NOTE_ID_ROLE) is not None)

    def _item_for(self, note_id: int) -> QTreeWidgetItem | None:
        for item in self._note_items():
            if int(item.data(0, NOTE_ID_ROLE)) == int(note_id):
                return item
        return None

    def row_count(self) -> int:
        """화면에 올라온 메모 수.  접혀서 보이지 않는 것도 센다."""
        return sum(1 for _item in self._note_items())

    def select_id(self, note_id: int) -> None:
        item = self._item_for(note_id)
        if item is None:
            return
        self.expand_to(note_id)
        self.table.setCurrentItem(item)

    def checked_ids(self) -> list[int]:
        return [
            int(item.data(0, NOTE_ID_ROLE)) for item in self._note_items()
            if item.checkState(0) == Qt.CheckState.Checked
        ]

    def export_ids(self) -> list[int]:
        return self.checked_ids() or [int(item.data(0, NOTE_ID_ROLE)) for item in self._note_items()]

    def deletion_ids(self) -> list[int]:
        """Checked rows if any, else the row the user is standing on."""
        checked = self.checked_ids()
        if checked:
            return checked
        current = self.table.currentItem()
        if current is None or current.data(0, NOTE_ID_ROLE) is None:
            return []
        return [int(current.data(0, NOTE_ID_ROLE))]

    def toggle_all(self) -> None:
        items = list(self._note_items())
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
            for item in self._note_items():
                item.setCheckState(0, state)
        finally:
            self.table.blockSignals(blocked)
        self.table.viewport().update()
        self._sync_select_all_state()

    def _sync_select_all_state(self, *_args) -> None:
        items = list(self._note_items())
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
        self.export_button.setVisible(selected == 0)
        self.action_status.setVisible(selected == 0)
        self.selection_chip.setText(f"{selected}개 선택")
        self.selection_chip.setVisible(selected > 0)
        self.delete_button.setVisible(selected > 0)
        self.delete_button.setEnabled(selected > 0)
        self.delete_button.setText("선택 삭제")
        self.bulk_category_button.setVisible(selected > 0)
        self.group_button.setVisible(selected >= 2)

    def _request_group(self) -> None:
        note_ids = self.checked_ids()
        if len(note_ids) < 2:
            return
        prefixes = []
        for note_id in note_ids:
            row = self.rows_by_id.get(note_id)
            title = str(row["title"] or "") if row is not None else ""
            match = re.match(r"^\s*(\[[^\]\r\n]{1,40}\])", title)
            prefixes.append(match.group(1) if match else "")
        suggested = prefixes[0] if prefixes and prefixes[0] and len(set(prefixes)) == 1 else "새 묶음"
        self.group_requested.emit(note_ids, suggested)

    def begin_inline_rename(self, note_id: int) -> bool:
        item = self._item_for(note_id)
        if item is None:
            return False
        self._inline_editing_id = int(note_id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.table.setCurrentItem(item, self.TITLE_COLUMN)
        self.table.editItem(item, self.TITLE_COLUMN)
        return True

    def _inline_title_changed(self, item: QTreeWidgetItem, column: int) -> None:
        note_id = item.data(0, NOTE_ID_ROLE)
        if column != self.TITLE_COLUMN or note_id is None:
            return
        if self._inline_editing_id != int(note_id):
            return
        title = item.text(self.TITLE_COLUMN).strip() or "새 묶음"
        self._inline_editing_id = None
        blocked = self.table.blockSignals(True)
        item.setText(self.TITLE_COLUMN, title)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.blockSignals(blocked)
        self.note_rename_requested.emit(int(note_id), title)

    def _end_inline_rename(self, *_args) -> None:
        if self._inline_editing_id is not None:
            item = self._item_for(self._inline_editing_id)
            self._inline_editing_id = None
            if item is not None:
                blocked = self.table.blockSignals(True)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.blockSignals(blocked)

    def _activate_row(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 and item is not None and item.data(0, NOTE_ID_ROLE) is not None:
            self.note_selected.emit(int(item.data(0, NOTE_ID_ROLE)))
