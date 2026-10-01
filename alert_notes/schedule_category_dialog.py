"""Editor for schedule-only categories; existing schedule keys remain stable."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .categories import (
    CATEGORIES, CATEGORY_COLORS, new_schedule_category, save_schedule_categories,
    schedule_categories,
)


class _CategoryNameLabel(QLabel):
    """긴 사용자 이름을 버튼 영역까지 밀어내지 않고 말줄임한다."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(
            self.contentsRect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width()),
        )


class ScheduleCategoryDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.rows = [dict(row) for row in schedule_categories(store)]
        self._editing_index: int | None = None
        self.setWindowTitle("일정 분류 관리")
        self.setObjectName("scheduleCategoryDialog")
        self.setMinimumWidth(360)
        self.resize(380, 480)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        heading = QLabel("일정 분류 관리")
        heading.setObjectName("popoverHeading")
        root.addWidget(heading)
        helper = QLabel("이름·색상·연관어를 설정하세요. 연관어는 제목 자동 분류에 사용됩니다.")
        helper.setObjectName("popoverHint")
        helper.setWordWrap(True)
        root.addWidget(helper)
        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_body = QWidget()
        self.list_layout = QVBoxLayout(self.list_body)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        scroll.setWidget(self.list_body)
        root.addWidget(scroll)
        add = QPushButton("+ 분류 추가")
        add.setObjectName("popoverCategoryAdd")
        add.clicked.connect(self._add)
        root.addWidget(add)
        footer = QHBoxLayout()
        footer.addStretch()
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        save = QPushButton("저장")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)
        self._render()

    def _read_fields(self) -> None:
        for index, (name, color, aliases) in enumerate(getattr(self, "_fields", [])):
            if name is None:
                continue
            self.rows[index]["name"] = name.text().strip()
            self.rows[index]["color"] = color.currentData()
            self.rows[index]["aliases"] = [part.strip() for part in aliases.text().split(",") if part.strip()]

    def _render(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self._fields = []
        for index, row in enumerate(self.rows):
            card = QFrame()
            card.setObjectName("scheduleCategoryCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(8, 5, 8, 5)
            layout.setSpacing(6)
            first = QHBoxLayout()
            first.setSpacing(5)
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {CATEGORY_COLORS[row['color']][1]}; font-size: 15px;")
            dot.setAccessibleName(f"{row['name']} 색상")
            first.addWidget(dot)
            label = _CategoryNameLabel(row["name"])
            label.setToolTip(row["name"])
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            first.addWidget(label)
            for label, step in (("↑", -1), ("↓", 1)):
                button = QPushButton(label)
                button.setObjectName("popoverCategoryRowAction")
                button.setAccessibleName(f"{row['name']} {'위로' if step < 0 else '아래로'} 이동")
                button.setToolTip(button.accessibleName())
                button.setEnabled(0 <= index + step < len(self.rows))
                button.clicked.connect(lambda _checked=False, i=index, delta=step: self._move(i, delta))
                first.addWidget(button)
            edit = QPushButton("접기" if index == self._editing_index else "수정")
            edit.setObjectName("popoverCategoryRowAction")
            edit.setAccessibleName(f"{row['name']} 분류 편집")
            edit.clicked.connect(lambda _checked=False, i=index: self._toggle_editor(i))
            first.addWidget(edit)
            remove = QPushButton("삭제")
            remove.setObjectName("popoverCategoryRowAction")
            remove.setAccessibleName(f"{row['name']} 분류 삭제")
            used = self.store.conn.execute(
                "SELECT COUNT(*) FROM schedule_items WHERE category=?", (row["id"],)
            ).fetchone()[0]
            remove.setEnabled(not used and len(self.rows) > 1)
            if used:
                remove.setToolTip(f"일정 {used}개에서 사용 중이므로 삭제할 수 없습니다")
            elif len(self.rows) == 1:
                remove.setToolTip("분류는 최소 1개가 필요합니다")
            remove.clicked.connect(lambda _checked=False, i=index: self._remove(i))
            first.addWidget(remove)
            layout.addLayout(first)
            if index == self._editing_index:
                fields = QHBoxLayout()
                name = QLineEdit(row["name"])
                name.setPlaceholderText("분류 이름")
                name.setAccessibleName(f"{index + 1}번째 분류 이름")
                color = QComboBox()
                color.setAccessibleName(f"{index + 1}번째 분류 색상")
                for color_name, key in CATEGORIES:
                    color.addItem(color_name, key)
                color.setCurrentIndex(max(0, color.findData(row["color"])))
                fields.addWidget(name, 1)
                fields.addWidget(color)
                layout.addLayout(fields)
                aliases = QLineEdit(", ".join(row.get("aliases", [])))
                aliases.setPlaceholderText("연관어 · 예: 결재, 회계")
                aliases.setAccessibleName(f"{row['name']} 분류 연관어")
                aliases.setToolTip("쉼표로 구분합니다. 여러 분류의 연관어가 겹치면 자동 선택하지 않습니다.")
                layout.addWidget(aliases)
                self._fields.append((name, color, aliases))
            else:
                self._fields.append((None, None, None))
            self.list_layout.addWidget(card)
        self.list_layout.addStretch()
        list_height = len(self.rows) * 52 + (76 if self._editing_index is not None else 0)
        self.scroll.setFixedHeight(min(340, max(64, list_height)))
        self.resize(self.width(), min(600, max(280, 190 + self.scroll.height())))

    def _toggle_editor(self, index: int) -> None:
        self._read_fields()
        self._editing_index = None if self._editing_index == index else index
        self._render()
        if self._editing_index is not None:
            self._fields[index][0].setFocus()

    def _add(self) -> None:
        self._read_fields()
        if len(self.rows) >= 100:
            QMessageBox.warning(self, "일정 분류", "분류는 최대 100개까지 추가할 수 있습니다.")
            return
        self.rows.append(new_schedule_category("새 분류"))
        self._editing_index = len(self.rows) - 1
        self._render()
        self._fields[-1][0].setFocus()
        self._fields[-1][0].selectAll()

    def _move(self, index: int, step: int) -> None:
        self._read_fields()
        other = index + step
        if 0 <= other < len(self.rows):
            self.rows[index], self.rows[other] = self.rows[other], self.rows[index]
            if self._editing_index == index:
                self._editing_index = other
            elif self._editing_index == other:
                self._editing_index = index
            self._render()

    def _remove(self, index: int) -> None:
        self._read_fields()
        row = self.rows[index]
        used = self.store.conn.execute(
            "SELECT COUNT(*) FROM schedule_items WHERE category=?", (row["id"],)
        ).fetchone()[0]
        if used:
            QMessageBox.information(
                self, "분류 삭제", f"'{row['name']}' 분류를 사용하는 일정이 {used}개 있어 삭제할 수 없습니다."
            )
            return
        if len(self.rows) == 1:
            QMessageBox.information(self, "분류 삭제", "분류는 최소 1개가 필요합니다.")
            return
        self.rows.pop(index)
        if self._editing_index == index:
            self._editing_index = None
        elif self._editing_index is not None and self._editing_index > index:
            self._editing_index -= 1
        self._render()

    def _save(self) -> None:
        self._read_fields()
        retained = {row["id"] for row in self.rows}
        for old in schedule_categories(self.store):
            if old["id"] in retained:
                continue
            used = self.store.conn.execute(
                "SELECT COUNT(*) FROM schedule_items WHERE category=?", (old["id"],)
            ).fetchone()[0]
            if used:
                QMessageBox.warning(
                    self, "분류 삭제", f"'{old['name']}' 분류를 사용하는 일정이 {used}개 있어 삭제할 수 없습니다."
                )
                return
        try:
            save_schedule_categories(self.store, self.rows)
        except ValueError as exc:
            QMessageBox.warning(self, "일정 분류", str(exc))
            return
        self.accept()
