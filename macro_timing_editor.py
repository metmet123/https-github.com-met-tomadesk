"""Table editor for recorded macro actions and their following waits."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from macro_step_editor import MacroStepDialog, step_label


class TimingEditorDialog(QDialog):
    def __init__(self, steps: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("단계별 시간 편집")
        self.resize(680, 440)
        self.setMinimumSize(600, 370)
        self.setSizeGripEnabled(True)
        self._steps = [dict(step) for step in steps]
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "작업을 더블클릭하면 내용을 수정할 수 있습니다. 0초는 대기 단계를 제거합니다."
        ))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["순서", "작업", "다음 작업까지 대기"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setMinimumHeight(190)
        self.table.setColumnWidth(0, 58)
        self.table.setColumnWidth(1, 260)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._edit_cell)
        self._rows: list[tuple[int, QDoubleSpinBox]] = []
        self._populate_rows()
        layout.addWidget(self.table, 1)

        quick = QHBoxLayout()
        quick.addWidget(QLabel("전체 대기시간"))
        self.apply_all_delay = QDoubleSpinBox()
        self.apply_all_delay.setRange(0, 60)
        self.apply_all_delay.setDecimals(2)
        self.apply_all_delay.setSingleStep(0.1)
        self.apply_all_delay.setSuffix(" 초")
        self.apply_all_delay.setValue(0.3)
        quick.addWidget(self.apply_all_delay)
        apply_all = QPushButton("모두 적용")
        apply_all.clicked.connect(self.apply_delay_to_all)
        quick.addWidget(apply_all)
        halve = QPushButton("대기시간 ÷ 2")
        halve.clicked.connect(lambda: [spin.setValue(spin.value() / 2) for _, spin in self._rows])
        quick.addWidget(halve)
        quick.addStretch()
        layout.addLayout(quick)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_rows(self) -> None:
        action_number = 0
        for index, step in enumerate(self._steps):
            if step.get("type") == "wait":
                continue
            action_number += 1
            row = self.table.rowCount()
            self.table.insertRow(row)
            number = QTableWidgetItem(str(action_number))
            number.setFlags(number.flags() & ~Qt.ItemFlag.ItemIsEditable)
            action = QTableWidgetItem(step_label(step))
            action.setFlags(action.flags() & ~Qt.ItemFlag.ItemIsEditable)
            action.setData(Qt.ItemDataRole.UserRole, index)
            self.table.setItem(row, 0, number)
            self.table.setItem(row, 1, action)
            delay = 0.0
            if index + 1 < len(self._steps) and self._steps[index + 1].get("type") == "wait":
                delay = float(self._steps[index + 1].get("seconds", 0))
            spin = QDoubleSpinBox()
            spin.setRange(0, 60)
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            spin.setSuffix(" 초")
            spin.setValue(delay)
            self.table.setCellWidget(row, 2, spin)
            self._rows.append((index, spin))

    def apply_delay_to_all(self) -> None:
        value = self.apply_all_delay.value()
        for _, spin in self._rows:
            spin.setValue(value)

    def _edit_cell(self, row: int, column: int) -> None:
        if column != 1:
            return
        item = self.table.item(row, column)
        if item is None:
            return
        step_index = int(item.data(Qt.ItemDataRole.UserRole))
        try:
            dialog = MacroStepDialog(self._steps[step_index], self)
        except ValueError as exc:
            QMessageBox.warning(self, "작업 수정", str(exc))
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._steps[step_index] = dialog.step()
            item.setText(step_label(self._steps[step_index]))

    def steps(self) -> list[dict]:
        desired = {index: round(spin.value(), 2) for index, spin in self._rows}
        result: list[dict] = []
        index = 0
        while index < len(self._steps):
            step = self._steps[index]
            if step.get("type") == "wait" and index > 0 and (index - 1) in desired:
                index += 1
                continue
            result.append(dict(step))
            if index in desired and desired[index] > 0:
                result.append({"type": "wait", "seconds": desired[index]})
            index += 1
        return result
