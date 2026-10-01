"""드롭박스의 글자 부분을 누르면 다음 항목으로 넘긴다.

화살표를 누르면 지금처럼 목록이 펼쳐진다.  편집할 수 있는 드롭박스와
``cycleOnClick`` 속성을 False 로 둔 드롭박스(단축키 조합 칸)는 건드리지 않는다.
"""
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QStyle, QStyleOptionComboBox

CYCLE_PROPERTY = "cycleOnClick"


def arrow_rect(combo: QComboBox):
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    rect = combo.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox, option,
        QStyle.SubControl.SC_ComboBoxArrow, combo,
    )
    if not rect.isValid() or rect.width() <= 0:
        rect = combo.rect().adjusted(max(0, combo.width() - 22), 0, 0, 0)
    return rect


def cycles_on_click(combo: QComboBox) -> bool:
    return (
        combo.isEnabled() and not combo.isEditable() and combo.count() > 1
        and combo.property(CYCLE_PROPERTY) is not False
    )


def select_next(combo: QComboBox) -> bool:
    """사용할 수 있는 다음 항목으로 넘긴다.  끝에서는 처음으로 돌아간다."""
    model = combo.model()
    count = combo.count()
    current = combo.currentIndex()
    for step in range(1, count + 1):
        index = (current + step) % count
        item = model.index(index, combo.modelColumn(), combo.rootModelIndex())
        if index != current and item.flags() & Qt.ItemFlag.ItemIsEnabled:
            combo.setCurrentIndex(index)
            # 사람이 목록에서 고른 것과 같은 신호를 보낸다.
            combo.activated.emit(index)
            combo.textActivated.emit(combo.itemText(index))
            return True
    return False


class ComboClickCycler(QObject):
    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
            and isinstance(watched, QComboBox)
            and event.button() == Qt.MouseButton.LeftButton
            and cycles_on_click(watched)
            and not arrow_rect(watched).contains(event.position().toPoint())
        ):
            watched.setFocus(Qt.FocusReason.MouseFocusReason)
            select_next(watched)
            event.accept()
            return True
        return False


def install_combo_click_cycle(app: QApplication | None = None) -> ComboClickCycler:
    app = app or QApplication.instance()
    existing = getattr(app, "_combo_click_cycler", None)
    if existing is not None:
        return existing
    cycler = ComboClickCycler(app)
    app.installEventFilter(cycler)
    app._combo_click_cycler = cycler
    return cycler
