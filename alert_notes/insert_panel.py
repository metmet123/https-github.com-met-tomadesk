"""Two-tab insert menu with persistent order and typing-trigger settings."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QTabWidget, QVBoxLayout,
    QWidget,
)

from .insert_menu import PENDING_SUFFIX, item_label, item_tooltip
from .insert_preferences import default_order, default_triggers, get_insert_preferences


class LongPressOrderList(QListWidget):
    """Enable drag only after a deliberate 350 ms press."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(False)
        self.setAccessibleName("기능 순서")
        self._arm = QTimer(self)
        self._arm.setSingleShot(True)
        self._arm.setInterval(350)
        self._arm.timeout.connect(lambda: self.setDragEnabled(True))

    def mousePressEvent(self, event):
        self.setDragEnabled(False)
        self._arm.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._arm.stop()
        super().mouseReleaseEvent(event)
        self.setDragEnabled(False)


class InsertPanel(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.preferences = get_insert_preferences(getattr(editor, "store", None))
        self.trigger_edits: dict[str, QLineEdit] = {}
        self.setObjectName("insertPreferencesPanel")
        self.setMinimumWidth(370)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("insertPreferencesTabs")
        root.addWidget(self.tabs)
        self._build_features_tab()
        self._build_settings_tab()
        self.preferences.changed.connect(self.reload)
        self.reload()

    def _build_features_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("클릭하여 넣기 · 0.35초 길게 눌러 순서 변경")
        hint.setObjectName("insertPanelHint")
        layout.addWidget(hint)
        self.feature_list = LongPressOrderList()
        self.feature_list.setObjectName("insertFeatureList")
        self.feature_list.setMinimumHeight(330)
        self.feature_list.itemClicked.connect(self._run_item)
        self.feature_list.model().rowsMoved.connect(lambda *_args: self._save_order())
        layout.addWidget(self.feature_list)
        actions = QHBoxLayout()
        self.up_button = QPushButton("위로")
        self.down_button = QPushButton("아래로")
        self.reset_order_button = QPushButton("기본 순서")
        self.up_button.clicked.connect(lambda: self._move_selected(-1))
        self.down_button.clicked.connect(lambda: self._move_selected(1))
        self.reset_order_button.clicked.connect(self.preferences.reset_order)
        actions.addWidget(self.up_button)
        actions.addWidget(self.down_button)
        actions.addStretch(1)
        actions.addWidget(self.reset_order_button)
        layout.addLayout(actions)
        self.tabs.addTab(page, "기능")

    def _build_settings_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        explanation = QLabel("줄 맨 앞에서 입력할 조합입니다. 기존 호환 별칭은 그대로 유지됩니다.")
        explanation.setWordWrap(True)
        explanation.setObjectName("insertPanelHint")
        layout.addWidget(explanation)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_host = QWidget()
        self.trigger_form = QFormLayout(form_host)
        self.trigger_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(form_host)
        layout.addWidget(scroll, 1)
        self.error_label = QLabel()
        self.error_label.setObjectName("insertPanelError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        reset = QPushButton("입력 기본값")
        save = QPushButton("저장")
        reset.clicked.connect(self._reset_trigger_edits)
        save.clicked.connect(self._save_triggers)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        self.tabs.addTab(page, "설정")

    def reload(self) -> None:
        selected = self._selected_id()
        self.feature_list.blockSignals(True)
        self.feature_list.clear()
        for item in self.preferences.ordered_items():
            row = QListWidgetItem(item_label(item))
            row.setData(Qt.ItemDataRole.UserRole, item.item_id or item.method)
            row.setData(Qt.ItemDataRole.UserRole + 1, item.method)
            row.setToolTip(item_tooltip(item))
            handler = getattr(self.editor, item.method, None)
            if not callable(handler):
                row.setText(item_label(item) + PENDING_SUFFIX)
                row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.feature_list.addItem(row)
            if row.data(Qt.ItemDataRole.UserRole) == selected:
                self.feature_list.setCurrentItem(row)
        self.feature_list.blockSignals(False)
        while self.trigger_form.rowCount():
            self.trigger_form.removeRow(0)
        self.trigger_edits.clear()
        names = {item.item_id or item.method: item.name for item in self.preferences.ordered_items()}
        for item_id, trigger in self.preferences.triggers.items():
            edit = QLineEdit(trigger)
            edit.setAccessibleName(f"{names.get(item_id, item_id)} 줄앞 입력")
            edit.editingFinished.connect(self._validate_edits)
            self.trigger_edits[item_id] = edit
            self.trigger_form.addRow(names.get(item_id, item_id), edit)
        self._clear_error()

    def _selected_id(self) -> str:
        item = self.feature_list.currentItem() if hasattr(self, "feature_list") else None
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ""

    def _run_item(self, item) -> None:
        handler = getattr(self.editor, str(item.data(Qt.ItemDataRole.UserRole + 1)), None)
        if callable(handler):
            handler()

    def _current_order(self) -> list[str]:
        return [
            str(self.feature_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.feature_list.count())
        ]

    def _save_order(self) -> None:
        order = self._current_order()
        if order != self.preferences.order:
            self.preferences.save(order, self.preferences.triggers)

    def _move_selected(self, step: int) -> None:
        row = self.feature_list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.feature_list.count():
            return
        item = self.feature_list.takeItem(row)
        self.feature_list.insertItem(target, item)
        self.feature_list.setCurrentRow(target)
        self._save_order()

    def _values(self) -> dict[str, str]:
        return {item_id: edit.text() for item_id, edit in self.trigger_edits.items()}

    def _validate_edits(self) -> bool:
        from .insert_preferences import validate_triggers
        errors = validate_triggers(self._values())
        for item_id, edit in self.trigger_edits.items():
            edit.setProperty("invalid", item_id in errors)
            edit.style().unpolish(edit)
            edit.style().polish(edit)
            edit.setToolTip(errors.get(item_id, ""))
        if errors:
            self.error_label.setText(next(iter(errors.values())))
            self.error_label.show()
            return False
        self._clear_error()
        return True

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.hide()

    def _save_triggers(self) -> None:
        if not self._validate_edits():
            return
        errors = self.preferences.save(self.preferences.order, self._values())
        if not errors:
            self.error_label.setText("저장했습니다. 열려 있는 편집기에 바로 적용됩니다.")
            self.error_label.setProperty("success", True)
            self.error_label.show()

    def _reset_trigger_edits(self) -> None:
        defaults = default_triggers()
        for item_id, edit in self.trigger_edits.items():
            edit.setText(defaults.get(item_id, ""))
        self._validate_edits()
