from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QHeaderView, QStyle, QStyleOptionButton


class SelectAllHeader(QHeaderView):
    """첫 번째 열에 전체 선택 체크박스를 표시하는 표 머리글."""

    check_state_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._checkbox = QCheckBox(self)
        self._checkbox.setAccessibleName("전체 선택")
        self._checkbox.setToolTip("전체 선택/해제")
        self._checkbox.clicked.connect(self.check_state_changed)
        self.sectionResized.connect(self._position_checkbox)
        self.sectionMoved.connect(self._position_checkbox)

    def set_check_state(self, state: Qt.CheckState) -> None:
        self._checkbox.blockSignals(True)
        self._checkbox.setCheckState(state)
        self._checkbox.blockSignals(False)

    def check_state(self) -> Qt.CheckState:
        return self._checkbox.checkState()

    def toggle_check_state(self) -> None:
        self._checkbox.click()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_checkbox()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._position_checkbox()

    def mousePressEvent(self, event) -> None:
        if self.logicalIndexAt(event.position().toPoint()) == 0:
            self._checkbox.click()
            event.accept()
            return
        super().mousePressEvent(event)

    def _indicator_centre(self) -> QPoint:
        """체크 상자 그림의 한가운데.  위젯 한가운데와는 다르다.

        빈 QCheckBox 도 글자 자리를 남겨 두므로, 위젯을 가운데 놓으면 정작 네모는
        왼쪽으로 치우친다.  목록 쪽 체크와 어긋나 보이던 원인이다.
        """
        option = QStyleOptionButton()
        option.initFrom(self._checkbox)
        option.rect = QRect(QPoint(0, 0), self._checkbox.size())
        indicator = self._checkbox.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, self._checkbox,
        )
        return indicator.center()

    def _position_checkbox(self, *_args) -> None:
        if self.count() == 0:
            return
        width = self.sectionSize(0)
        x = self.sectionViewportPosition(0)
        self._checkbox.resize(self._checkbox.sizeHint())
        centre = self._indicator_centre()
        self._checkbox.move(
            x + width // 2 - centre.x(),
            self.height() // 2 - centre.y(),
        )
