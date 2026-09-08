"""Small UI-polish helpers shared by the shortcut launcher screens."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication, QStyle, QStyleOptionViewItem, QStyledItemDelegate, QTableWidgetItem,
)


class ActiveStateItem(QTableWidgetItem):
    """Invisible active-state value that still sorts correctly under a switch."""

    def __init__(self, active: bool):
        super().__init__("")
        self.setData(Qt.ItemDataRole.UserRole, int(active))

    def __lt__(self, other) -> bool:
        left = int(self.data(Qt.ItemDataRole.UserRole) or 0)
        right = int(other.data(Qt.ItemDataRole.UserRole) or 0)
        return left < right


# 등록 상태를 글자 대신 점 하나로 보여 준다.  꺼진 것은 빈 점, 켜진 것은 찬
# 점 — 신호등처럼 한눈에 읽히고, 열 폭도 글자 몫만큼 줄어든다.
REGISTRATION_MARKS = {
    "등록됨": "●", "등록 실패": "●", "제외 중": "○", "비활성": "○", "확인 중": "○",
}
REGISTRATION_ORDER = {"등록됨": 0, "제외 중": 1, "확인 중": 2, "비활성": 3, "등록 실패": 4}


class RegistrationStateItem(QTableWidgetItem):
    """점으로 보이고, 무슨 상태인지는 도움말과 읽어 주기로 남는다."""

    def __init__(self, status: str = "확인 중", detail: str = ""):
        super().__init__("")
        self.set_status(status, detail)

    def set_status(self, status: str, detail: str = "") -> None:
        self.setText(REGISTRATION_MARKS.get(status, "○"))
        self.setData(Qt.ItemDataRole.UserRole, status)
        self.setData(Qt.ItemDataRole.AccessibleTextRole, status)
        self.setToolTip(f"{status} · {detail}" if detail else status)

    def status(self) -> str:
        return str(self.data(Qt.ItemDataRole.UserRole) or "")

    def __lt__(self, other) -> bool:
        left = REGISTRATION_ORDER.get(self.status(), 9)
        right = REGISTRATION_ORDER.get(str(other.data(Qt.ItemDataRole.UserRole) or ""), 9)
        return left < right


class RegistrationDotDelegate(QStyledItemDelegate):
    """점 색이 곧 뜻이다.

    줄을 고르면 스타일시트가 글자색을 선택색으로 덮어써서, 무슨 상태인지
    알려 주던 색이 사라졌다.  배경까지는 스타일에 맡기고 점만 직접 찍어
    이 칸의 색을 지킨다.
    """

    def paint(self, painter, option, index) -> None:
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        mark, item.text = item.text, ""
        widget = item.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, widget)
        if not mark:
            return
        value = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(value, QBrush):
            color = value.color()
        elif value is None:
            color = item.palette.text().color()
        else:
            color = QColor(value)
        painter.save()
        painter.setPen(color)
        painter.drawText(item.rect, Qt.AlignmentFlag.AlignCenter, mark)
        painter.restore()


def refresh_property(widget, name: str, value) -> None:
    """Set a dynamic Qt property and immediately refresh matching QSS rules."""
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def apply_numeric_font(widget) -> None:
    """Use stable-width numerals for changing hotkey, count, and speed values."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    _match_font_size(font, widget.font())
    widget.setFont(font)


def _match_font_size(target: QFont, reference: QFont) -> None:
    """Keep the effective font size without passing Qt's unset -1 point size."""
    if reference.pointSize() > 0:
        target.setPointSize(reference.pointSize())
    elif reference.pixelSize() > 0:
        target.setPixelSize(reference.pixelSize())


def polish_button(button, accessible_name: str | None = None) -> None:
    """Give text buttons a consistent pointer and accessible label."""
    label = accessible_name or button.text().replace("＋", "").replace("▶", "").strip()
    button.setAccessibleName(label)
    button.setCursor(Qt.CursorShape.PointingHandCursor)


def polish_action_item(item, column: int) -> None:
    """Apply stable alignment and optical weight to a launcher table item."""
    if column in {1, 4, 5, 6}:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    if column == 1:
        item.setForeground(QColor("#64748b"))
    elif column == 3:
        font = item.font()
        font.setWeight(QFont.Weight.DemiBold)
        item.setFont(font)
    elif column == 4:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        _match_font_size(font, item.font())
        item.setFont(font)
        item.setForeground(QColor("#1d4ed8"))
    elif column == 5:
        item.setForeground(QColor("#475569"))
