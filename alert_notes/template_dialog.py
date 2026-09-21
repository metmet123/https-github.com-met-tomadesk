from __future__ import annotations

from datetime import datetime
import json
import sqlite3

from .builtin_templates import (
    DATE_FORMAT_OPTIONS, DATE_FORMAT_SETTING, TIME_FORMAT_OPTIONS, TIME_FORMAT_SETTING,
    builtin_payload, fill_template_payload, selected_template_formats,
)

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QVBoxLayout,
)


TEMPLATE_ID_ROLE = Qt.ItemDataRole.UserRole


class TemplateManagerDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("블록 템플릿 관리")
        self.resize(540, 590)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setMinimumHeight(145)
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.model().rowsMoved.connect(self._save_order)
        layout.addWidget(self.list, 1)
        actions = QHBoxLayout()
        for label, slot in (
            ("내장 양식 복사", self._copy_builtin),
            ("이름·호출어", self._edit), ("위로", lambda: self._move(-1)),
            ("아래로", lambda: self._move(1)), ("삭제", self._delete),
        ):
            button = QPushButton(label)
            button.setFixedHeight(28)
            button.clicked.connect(slot)
            actions.addWidget(button)
        layout.addLayout(actions)
        format_box = QGroupBox("자동 채우기 기본 형식")
        format_layout = QVBoxLayout(format_box)
        format_layout.addWidget(QLabel("날짜 표기"))
        self.date_group = QButtonGroup(self)
        self.date_buttons = {}
        for code, example in DATE_FORMAT_OPTIONS:
            button = QRadioButton(example)
            button.setAccessibleName(f"날짜 표기 {example}")
            button.toggled.connect(self._format_changed)
            self.date_group.addButton(button)
            self.date_buttons[code] = button
            format_layout.addWidget(button)
        time_row = QHBoxLayout()
        time_label = QLabel("시간 표기")
        self.time_format = QComboBox()
        self.time_format.setAccessibleName("시간 표기")
        for code, example in TIME_FORMAT_OPTIONS:
            self.time_format.addItem(example, code)
        self.time_format.currentIndexChanged.connect(self._format_changed)
        time_row.addWidget(time_label)
        time_row.addWidget(self.time_format, 1)
        format_layout.addLayout(time_row)
        layout.addWidget(format_box)
        self.preview_label = QLabel("선택한 템플릿 미리보기")
        layout.addWidget(self.preview_label)
        self.preview = QPlainTextEdit()
        self.preview.setAccessibleName("선택한 템플릿 미리보기")
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(90)
        self.preview.setMaximumHeight(125)
        layout.addWidget(self.preview)
        self.format_status = QLabel("형식을 저장하면 이후 삽입하는 템플릿에 적용됩니다.")
        self.format_status.setAccessibleName("템플릿 형식 저장 상태")
        layout.addWidget(self.format_status)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.save_format_button = QPushButton("기본 형식 저장")
        self.save_format_button.clicked.connect(self._save_formats)
        footer.addWidget(self.save_format_button)
        close = QPushButton("닫기")
        close.setFixedHeight(28)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)
        date_code, time_code = selected_template_formats(self.service.store)
        self.date_buttons[date_code].setChecked(True)
        self.time_format.setCurrentIndex(max(0, self.time_format.findData(time_code)))
        self.list.currentItemChanged.connect(self._update_preview)
        self.refresh()

    def refresh(self, selected_id=None):
        self.list.clear()
        for row in self.service.available_templates():
            prefix = "기본 · " if int(row["id"]) < 0 else ""
            item = QListWidgetItem(f"{prefix}{row['name']}   /{row['trigger']}")
            item.setData(TEMPLATE_ID_ROLE, int(row["id"]))
            item.setData(Qt.ItemDataRole.UserRole + 1, dict(row))
            if int(row["id"]) < 0:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            self.list.addItem(item)
            if selected_id == int(row["id"]):
                self.list.setCurrentItem(item)
        if self.list.count() and self.list.currentItem() is None:
            self.list.setCurrentRow(0)
        self._update_preview()

    def _chosen_formats(self):
        date_code = next(
            code for code, button in self.date_buttons.items() if button.isChecked()
        )
        return date_code, str(self.time_format.currentData())

    def _format_changed(self, *_args):
        if not hasattr(self, "format_status"):
            return
        self.format_status.setText("변경 내용을 저장하세요.")
        self._update_preview()

    def _save_formats(self):
        date_code, time_code = self._chosen_formats()
        try:
            self.service.store.set_setting(DATE_FORMAT_SETTING, date_code)
            self.service.store.set_setting(TIME_FORMAT_SETTING, time_code)
        except sqlite3.Error as exc:
            QMessageBox.warning(self, "기본 형식을 저장할 수 없음", str(exc))
            return
        self.format_status.setText("기본 형식이 저장되었습니다.")

    def _update_preview(self, *_args):
        if not hasattr(self, "preview"):
            return
        template_id = self._id()
        if template_id is None:
            self.preview_label.setText("선택한 템플릿 미리보기")
            self.preview.clear()
            return
        row = self.list.currentItem().data(Qt.ItemDataRole.UserRole + 1)
        self.preview_label.setText(f"선택한 템플릿 미리보기 · {row['name']}")
        try:
            if template_id < 0:
                payload = builtin_payload(template_id)
            else:
                stored = self.service.conn.execute(
                    "SELECT payload_version,payload_json FROM memo_templates WHERE id=?", (template_id,)
                ).fetchone()
                if stored is None or int(stored["payload_version"]) != 1:
                    raise ValueError("지원하지 않는 템플릿 형식입니다.")
                payload = json.loads(str(stored["payload_json"]))
            if not isinstance(payload, dict) or int(payload.get("version", 0)) != 1:
                raise ValueError("지원하지 않는 템플릿 형식입니다.")
            title_edit = getattr(self.parent(), "title_edit", None)
            title = title_edit.text() if title_edit is not None else "예시 메모 제목"
            date_code, time_code = self._chosen_formats()
            shown = fill_template_payload(
                payload, title=title, now=datetime.now(),
                date_format=date_code, time_format=time_code,
            )
            self.preview.setPlainText(shown["text"])
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.preview.setPlainText(f"미리보기를 표시할 수 없습니다: {exc}")

    def _id(self):
        item = self.list.currentItem()
        return None if item is None else int(item.data(TEMPLATE_ID_ROLE))

    def _edit(self):
        item = self.list.currentItem()
        if item is None:
            return
        if self._id() < 0:
            QMessageBox.information(self, "기본 템플릿", "기본 양식은 복사한 뒤 개인 양식을 수정하세요.")
            return
        row = item.data(Qt.ItemDataRole.UserRole + 1)
        name, ok = QInputDialog.getText(self, "템플릿 이름", "이름", text=str(row["name"]))
        if not ok:
            return
        trigger, ok = QInputDialog.getText(self, "템플릿 호출어", "호출어 (/ 제외)", text=str(row["trigger"]))
        if not ok:
            return
        try:
            self.service.update_template(self._id(), name=name, trigger=trigger)
        except Exception as exc:
            QMessageBox.warning(self, "템플릿", str(exc))
            return
        self.refresh(self._id())

    def _move(self, offset):
        row, target = self.list.currentRow(), self.list.currentRow() + int(offset)
        if row < 0 or target < 0 or target >= self.list.count():
            return
        if self._id() < 0 or int(self.list.item(target).data(TEMPLATE_ID_ROLE)) < 0:
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)
        self._save_order()

    def _save_order(self, *_args):
        try:
            self.service.reorder_templates([
                int(self.list.item(index).data(TEMPLATE_ID_ROLE)) for index in range(self.list.count())
                if int(self.list.item(index).data(TEMPLATE_ID_ROLE)) > 0
            ])
        except ValueError as exc:
            QMessageBox.warning(self, "템플릿 순서를 저장할 수 없음", str(exc))
            self.refresh()

    def _delete(self):
        template_id = self._id()
        if template_id is None:
            return
        if template_id < 0:
            QMessageBox.information(self, "기본 템플릿", "기본 양식은 삭제할 수 없습니다.")
            return
        if QMessageBox.question(self, "템플릿 삭제", "선택한 템플릿을 삭제할까요?") == QMessageBox.StandardButton.Yes:
            try:
                self.service.delete_template(template_id)
            except ValueError as exc:
                QMessageBox.warning(self, "템플릿을 삭제할 수 없음", str(exc))
                return
            self.refresh()

    def _copy_builtin(self):
        template_id = self._id()
        if template_id is None or template_id >= 0:
            return
        row = self.list.currentItem().data(Qt.ItemDataRole.UserRole + 1)
        name, ok = QInputDialog.getText(self, "개인 템플릿으로 복사", "이름", text=f"{row['name']} (사본)")
        if not ok or not name.strip():
            return
        trigger, ok = QInputDialog.getText(
            self, "개인 템플릿으로 복사", "호출어 (/ 제외)", text=f"{row['trigger']}사본"
        )
        if not ok or not trigger.strip():
            return
        try:
            new_id = self.service.save_template(name, trigger, builtin_payload(template_id))
        except (ValueError, sqlite3.IntegrityError) as exc:
            QMessageBox.warning(self, "템플릿 복사", str(exc))
            return
        self.refresh(new_id)
