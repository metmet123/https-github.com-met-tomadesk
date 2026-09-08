from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout


def display_due(value: str) -> str:
    text = str(value or "")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]} {text[8:10]}:{text[10:12]}" if len(text) == 12 else text


class ExistingReminderDialog(QDialog):
    def __init__(self, reminders, parent=None, allow_add: bool = True):
        super().__init__(parent)
        self.setWindowTitle("기존 알림 처리")
        self.choice: str | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("이 메모에 예정된 알림이 있습니다."))
        self.combo = QComboBox()
        for row in reminders:
            self.combo.addItem(
                f"{display_due(row['due_at'])} · {str(row['memo'])[:50]}", int(row["id"]),
            )
        layout.addWidget(self.combo)
        if allow_add:
            add = QPushButton("새 알림 추가")
            add.clicked.connect(lambda: self._finish("add"))
            layout.addWidget(add)
        change = QPushButton("선택한 알림 변경")
        change.clicked.connect(lambda: self._finish("change"))
        layout.addWidget(change)
        cancel = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel.rejected.connect(self.reject)
        layout.addWidget(cancel)

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def result_choice(self) -> tuple[str | None, int | None]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None, None
        return self.choice, int(self.combo.currentData())
