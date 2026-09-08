"""User-friendly editing for recorded macro steps and their following waits."""

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from hotkey_parser import parse_hotkey, parse_key


class MacroStepDialog(QDialog):
    """Edit one meaningful macro step with controls specific to its type."""

    def __init__(self, step: dict, parent=None):
        super().__init__(parent)
        self._original = dict(step)
        self._kind = str(step.get("type", ""))
        self.setWindowTitle(f"{step_label(step)} 수정")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("선택한 작업만 수정합니다. 앞뒤 순서와 대기시간은 유지됩니다."))
        self.form = QFormLayout()
        layout.addLayout(self.form)
        self._build_fields(step)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _coordinate(self, value: object) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(-100000, 100000)
        spin.setValue(int(value or 0))
        return spin

    def _build_fields(self, step: dict) -> None:
        if self._kind == "click":
            self.x = self._coordinate(step.get("x"))
            self.y = self._coordinate(step.get("y"))
            self.button = QComboBox()
            self.button.addItem("왼쪽 클릭", "left")
            self.button.addItem("오른쪽 클릭", "right")
            self.button.setCurrentIndex(max(0, self.button.findData(step.get("button", "left"))))
            self.form.addRow("종류", self.button)
            self.form.addRow("X 좌표", self.x)
            self.form.addRow("Y 좌표", self.y)
        elif self._kind == "key":
            self.key = QLineEdit(str(step.get("key", "")))
            self.key.setPlaceholderText("예: Enter, Backspace, Ctrl+C, Alt+Tab")
            self.form.addRow("키 또는 단축키", self.key)
        elif self._kind == "text":
            self.text = QTextEdit()
            self.text.setPlainText(str(step.get("text", "")))
            self.text.setMinimumHeight(110)
            self.press_enter = QCheckBox("문구 입력 후 Enter 누르기")
            self.press_enter.setChecked(bool(step.get("press_enter", False)))
            self.form.addRow("입력 문구", self.text)
            self.form.addRow("", self.press_enter)
        elif self._kind == "drag":
            self.start_x = self._coordinate(step.get("start_x"))
            self.start_y = self._coordinate(step.get("start_y"))
            self.end_x = self._coordinate(step.get("end_x"))
            self.end_y = self._coordinate(step.get("end_y"))
            self.duration = QDoubleSpinBox()
            self.duration.setRange(0.01, 60.0)
            self.duration.setDecimals(2)
            self.duration.setSuffix(" 초")
            self.duration.setValue(float(step.get("duration", 0.2)))
            self.form.addRow("시작 X", self.start_x)
            self.form.addRow("시작 Y", self.start_y)
            self.form.addRow("끝 X", self.end_x)
            self.form.addRow("끝 Y", self.end_y)
            self.form.addRow("드래그 시간", self.duration)
        elif self._kind == "wheel":
            self.direction = QComboBox()
            for label, value in (
                ("위", "up"), ("아래", "down"), ("왼쪽", "left"), ("오른쪽", "right")
            ):
                self.direction.addItem(label, value)
            delta = int(step.get("delta", 0))
            axis = step.get("axis", "vertical")
            current = ("right" if delta > 0 else "left") if axis == "horizontal" else (
                "up" if delta > 0 else "down"
            )
            self.direction.setCurrentIndex(self.direction.findData(current))
            self.notches = QSpinBox()
            self.notches.setRange(1, 100)
            self.notches.setSuffix(" 칸")
            self.notches.setValue(max(1, abs(delta) // 120))
            self.x = self._coordinate(step.get("x"))
            self.y = self._coordinate(step.get("y"))
            self.form.addRow("방향", self.direction)
            self.form.addRow("이동량", self.notches)
            self.form.addRow("X 좌표", self.x)
            self.form.addRow("Y 좌표", self.y)
        else:
            raise ValueError(f"수정할 수 없는 작업 유형입니다: {self._kind or '알 수 없음'}")

    def _validate_and_accept(self) -> None:
        if self._kind == "key":
            value = self.key.text().strip()
            if not value:
                QMessageBox.warning(self, "키 입력 확인", "키 또는 단축키를 입력해 주세요.")
                return
            if value != str(self._original.get("key", "")):
                try:
                    if value.casefold() == "alt+tab":
                        value = "Alt+Tab"
                    elif "+" in value:
                        value = parse_hotkey(value).text
                    else:
                        _, value = parse_key(value)
                except Exception as exc:
                    QMessageBox.warning(self, "키 입력 확인", str(exc))
                    return
                self.key.setText(value)
        self.accept()

    def step(self) -> dict:
        result = dict(self._original)
        if self._kind == "click":
            result.update(x=self.x.value(), y=self.y.value())
            if self.button.currentData() == "right":
                result["button"] = "right"
            else:
                result.pop("button", None)
        elif self._kind == "key":
            new_key = self.key.text().strip()
            if new_key != str(result.get("key", "")):
                result.pop("vk", None)
                result.pop("modifier_vks", None)
            result["key"] = new_key
        elif self._kind == "text":
            result.update(text=self.text.toPlainText(), press_enter=self.press_enter.isChecked())
        elif self._kind == "drag":
            result.update(
                start_x=self.start_x.value(), start_y=self.start_y.value(),
                end_x=self.end_x.value(), end_y=self.end_y.value(),
                duration=round(self.duration.value(), 2),
            )
        elif self._kind == "wheel":
            direction = self.direction.currentData()
            horizontal = direction in {"left", "right"}
            positive = direction in {"up", "right"}
            delta = self.notches.value() * 120 * (1 if positive else -1)
            result.update(
                axis="horizontal" if horizontal else "vertical",
                delta=delta, x=self.x.value(), y=self.y.value(),
            )
        return result


def step_label(step: dict) -> str:
    kind = step.get("type")
    if kind == "click":
        button = "오른쪽 " if step.get("button", "left") == "right" else ""
        return f"{button}클릭 ({step.get('x', 0)}, {step.get('y', 0)})"
    if kind == "drag":
        return (
            f"드래그 ({step.get('start_x', 0)}, {step.get('start_y', 0)}) → "
            f"({step.get('end_x', 0)}, {step.get('end_y', 0)})"
        )
    if kind == "wheel":
        delta = int(step.get("delta", 0))
        if step.get("axis") == "horizontal":
            direction = "오른쪽" if delta > 0 else "왼쪽"
        else:
            direction = "위" if delta > 0 else "아래"
        return f"휠 {direction} {max(1, abs(delta) // 120)}칸"
    if kind == "text":
        preview = str(step.get("text", "")).replace("\n", " ")[:18]
        return f"문구 입력 ({preview})" if preview else "문구 입력"
    if kind == "key":
        return f"키 입력 ({step.get('key', '')})"
    return str(kind or "작업")
