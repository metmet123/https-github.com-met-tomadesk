"""Insert menu with persistent feature, typing, and document-import settings."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QScrollArea, QTabWidget, QVBoxLayout,
    QWidget,
)

from .insert_menu import PENDING_SUFFIX, item_label, item_tooltip
from .insert_preferences import default_order, default_triggers, get_insert_preferences
from .structured_import import (
    STRATEGIES, import_strategy, save_import_strategies,
)


class LongPressOrderList(QListWidget):
    """Enable drag only after a deliberate 350 ms press."""

    reorder_completed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAccessibleName("기능 순서")
        self._source_row = -1
        self._target_row = -1
        self._armed = False
        self._drag_click = False
        self._arm = QTimer(self)
        self._arm.setSingleShot(True)
        self._arm.setInterval(350)
        self._arm.timeout.connect(self._arm_reorder)

    def _arm_reorder(self) -> None:
        self._armed = self._source_row >= 0
        self._target_row = self._source_row

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._source_row = self.indexAt(event.position().toPoint()).row()
        self._target_row = self._source_row
        self._armed = False
        self._drag_click = False
        self._arm.start()

    def mouseMoveEvent(self, event):
        if self._armed:
            row = self.indexAt(event.position().toPoint()).row()
            if row >= 0:
                self._target_row = row
                self.setCurrentRow(row)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._arm.stop()
        source, target = self._source_row, self._target_row
        if self._armed and source >= 0 and target >= 0 and source != target:
            item = self.takeItem(source)
            self.insertItem(target, item)
            self.setCurrentRow(target)
            self._drag_click = True
            self.reorder_completed.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        self._source_row = -1
        self._target_row = -1
        self._armed = False

    def take_drag_click(self) -> bool:
        value = self._drag_click
        self._drag_click = False
        return value


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
        self._build_import_tab()
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
        self.feature_list.itemClicked.connect(self._run_clicked_item)
        self.feature_list.reorder_completed.connect(self._save_order)
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

    def _build_import_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        explanation = QLabel(
            "GPT·Claude 응답이나 문서의 제목을 메모 토글로 바꾸는 기준입니다. "
            "목록·표·인용문·코드와 글자 서식은 그대로 가져옵니다."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("insertPanelHint")
        layout.addWidget(explanation)
        form = QFormLayout()
        self.clipboard_import_combo = QComboBox()
        self.file_import_combo = QComboBox()
        for value, label in STRATEGIES.items():
            self.clipboard_import_combo.addItem(label, value)
            self.file_import_combo.addItem(label, value)
        form.addRow("클립보드", self.clipboard_import_combo)
        form.addRow("문서 파일", self.file_import_combo)
        layout.addLayout(form)
        layout.addStretch(1)
        actions = QHBoxLayout()
        reset = QPushButton("가져오기 기본값")
        save = QPushButton("저장")
        reset.clicked.connect(self._reset_import_settings)
        save.clicked.connect(self._save_import_settings)
        actions.addWidget(reset)
        actions.addStretch(1)
        actions.addWidget(save)
        layout.addLayout(actions)
        self.tabs.addTab(page, "가져오기")
        self._load_import_settings()

    def _load_import_settings(self) -> None:
        store = getattr(self.editor, "store", None)
        for combo, kind in (
            (self.clipboard_import_combo, "clipboard"),
            (self.file_import_combo, "file"),
        ):
            index = combo.findData(import_strategy(store, kind))
            combo.setCurrentIndex(max(0, index))

    def _save_import_settings(self) -> None:
        save_import_strategies(
            getattr(self.editor, "store", None),
            str(self.clipboard_import_combo.currentData()),
            str(self.file_import_combo.currentData()),
        )

    def _reset_import_settings(self) -> None:
        self.clipboard_import_combo.setCurrentIndex(
            max(0, self.clipboard_import_combo.findData("top_two_toggles"))
        )
        self.file_import_combo.setCurrentIndex(
            max(0, self.file_import_combo.findData("preserve"))
        )
        self._save_import_settings()

    def reload(self) -> None:
        selected = self._selected_id()
        self.feature_list.blockSignals(True)
        self.feature_list.clear()
        for item in self.preferences.ordered_items():
            row = QListWidgetItem(item_label(item))
            row.setData(Qt.ItemDataRole.UserRole, item.item_id or item.method)
            row.setData(Qt.ItemDataRole.UserRole + 1, item.method)
            trigger = self.preferences.triggers.get(item.item_id or item.method, item.typing)
            row.setToolTip(item_tooltip(item, trigger))
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
            menu = self.parent()
            if isinstance(menu, QMenu):
                menu.close()

    def _run_clicked_item(self, item) -> None:
        if not self.feature_list.take_drag_click():
            self._run_item(item)
            menu = self.parent()
            if isinstance(menu, QMenu):
                menu.close()
            menu = self.parentWidget()
            if menu is not None:
                menu.hide()

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
        self.preferences.save(self.preferences.order, self._values())

    def _reset_trigger_edits(self) -> None:
        defaults = default_triggers()
        for item_id, edit in self.trigger_edits.items():
            edit.setText(defaults.get(item_id, ""))
        self._validate_edits()
        if not errors:
            self.error_label.setText("저장했습니다. 열려 있는 편집기에 바로 적용됩니다.")
            self.error_label.setProperty("success", True)
            self.error_label.show()

    def _reset_trigger_edits(self) -> None:
        defaults = default_triggers()
        for item_id, edit in self.trigger_edits.items():
            edit.setText(defaults.get(item_id, ""))
        self._validate_edits()
