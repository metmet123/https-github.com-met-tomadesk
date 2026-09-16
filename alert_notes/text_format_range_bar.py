"""Text selection tools that use spare line space or the shared reserved strip."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QSizePolicy, QSpinBox, QToolButton,
)

from .format_preset_strip import PresetStrip
from .editor_icons import compact_combo_style
from .format_presets import load_preset

QUICK_COLORS = (("black", "검정", "#000000"), ("red", "빨강", "#d00000"), ("blue", "파랑", "#0057d9"))


class TextFormatRangeBar(QFrame):
    HEIGHT = 38
    GAP = 10
    MARGIN = 6

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.toolbar = None
        self.open_more = None
        self._preset_menu = None
        self.is_reserved = False
        self._syncing = False
        self.setObjectName("textFormatRangeBar")
        self.setAccessibleName("선택한 글자 서식 도구")
        self.setFixedHeight(self.HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(7, 3, 7, 3)
        row.setSpacing(3)
        self.style_buttons = {}
        for key, label in (("bold", "B"), ("italic", "I"),
                           ("underline", "U"), ("strike", "S")):
            button = QToolButton(self)
            button.setText(label)
            button.setAccessibleName({
                "bold": "선택 글자 굵게", "italic": "선택 글자 기울임",
                "underline": "선택 글자 밑줄", "strike": "선택 글자 취소선",
            }[key])
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.setFixedWidth(28)
            button.clicked.connect(lambda _checked=False, name=key: self._apply(name))
            row.addWidget(button)
            self.style_buttons[key] = button
        row.addWidget(self._separator())
        self.preset_strip = PresetStrip(self, button_size=24)
        self.preset_strip.setAccessibleName("선택한 글자 서식 프리셋")
        self.preset_strip.apply_requested.connect(self._apply_preset)
        self.preset_strip.menu_requested.connect(self._show_preset_menu)
        row.addWidget(self.preset_strip)
        row.addWidget(self._separator())
        # 위쪽 서식 패널을 열러 갈 필요 없이 크기·줄 간격·색을 여기서 바로 바꾼다.
        self.size_box = QSpinBox(self)
        self.size_box.setObjectName("rangeSizeBox")
        self.size_box.setRange(8, 72)
        self.size_box.setValue(10)
        self.size_box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.size_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.size_box.setAccessibleName("선택 글자 크기")
        self.size_box.setToolTip("글자 크기")
        self.size_box.setFixedSize(40, 26)
        self.size_box.setStyleSheet("QSpinBox#rangeSizeBox{padding:0 3px;}")
        self.size_box.valueChanged.connect(self._apply_size)
        row.addWidget(self.size_box)
        self.line_spacing_box = QComboBox(self)
        self.line_spacing_box.setObjectName("rangeLineSpacingBox")
        self.line_spacing_box.setAccessibleName("선택 줄 간격")
        self.line_spacing_box.setToolTip("줄 간격")
        self.line_spacing_box.addItem("혼합", None)
        for value, label in ((1.0, "1.0"), (1.15, "1.15"), (1.5, "1.5"), (2.0, "2.0")):
            self.line_spacing_box.addItem(label, value)
        self.line_spacing_box.setCurrentIndex(1)
        self.line_spacing_box.setFixedSize(52, 26)
        self.line_spacing_box.setStyleSheet(compact_combo_style())
        self.line_spacing_box.activated.connect(self._apply_line_spacing)
        row.addWidget(self.line_spacing_box)
        row.addWidget(self._separator())
        self.color_button = QToolButton(self)
        self.color_button.setObjectName("rangeColorButton")
        self.color_button.setAccessibleName("선택 글자 색상 선택")
        self.color_button.setToolTip("글자 색상 선택")
        self.color_button.setFixedSize(26, 26)
        self.color_button.setIconSize(QSize(18, 18))
        self.color_button.clicked.connect(self._choose_color)
        row.addWidget(self.color_button)
        self.color_buttons = {}
        for key, label, color in QUICK_COLORS:
            button = QToolButton(self)
            button.setObjectName("rangeQuickColor")
            button.setAccessibleName(f"선택 글자 {label}")
            button.setToolTip(label)
            button.setFixedSize(18, 18)
            button.clicked.connect(lambda _checked=False, value=color: self._apply_color(value))
            self.color_buttons[key] = button
            row.addWidget(button)
        self._refresh_swatches("")
        row.addStretch(1)
        self.close_button = QToolButton(self)
        self.close_button.setText("×")
        self.close_button.setAccessibleName("글자 선택 해제")
        self.close_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.close_button.setFixedWidth(28)
        self.close_button.clicked.connect(self.clear_selection)
        row.addWidget(self.close_button)
        self.close_button.hide()
        self.hide()

    def bind(self, toolbar, open_more) -> None:
        if self.toolbar is not None:
            try:
                self.toolbar.presets_changed.disconnect(self._reload_presets)
                self.toolbar.active_preset_changed.disconnect(self._set_active_preset)
                self.toolbar.format_synced.disconnect(self._sync_format_controls)
            except (TypeError, RuntimeError):
                pass
        self.toolbar = toolbar
        self.open_more = open_more
        if toolbar is not None:
            toolbar.presets_changed.connect(self._reload_presets)
            toolbar.active_preset_changed.connect(self._set_active_preset)
            toolbar.format_synced.connect(self._sync_format_controls)
            self._sync_format_controls()
            self._reload_presets()
            active = next((slot for slot, button in toolbar.preset_buttons.items()
                           if button.isChecked()), None)
            self._set_active_preset(active)

    def _separator(self) -> QFrame:
        line = QFrame(self)
        line.setObjectName("textFormatRangeSeparator")
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
        return line

    def _reload_presets(self) -> None:
        if self.toolbar is not None:
            self.preset_strip.reload(self.toolbar.store)

    def _set_active_preset(self, slot) -> None:
        self.preset_strip.set_active(slot)

    def _show_preset_menu(self, slot: int, global_pos: QPoint) -> None:
        if self.toolbar is None:
            return
        if self._preset_menu is not None:
            self._preset_menu.close()
        self._preset_menu = self.toolbar.slot_menu(slot, self)
        if self._preset_menu.actions():
            self._preset_menu.setActiveAction(self._preset_menu.actions()[0])
        self._preset_menu.popup(global_pos)

    def _sync_format_controls(self) -> None:
        """위쪽 서식 패널이 커서 서식을 읽을 때마다 같은 값을 보여 준다."""
        toolbar = self.toolbar
        if toolbar is None:
            return
        for control in (self.size_box, self.line_spacing_box):
            control.blockSignals(True)
        try:
            self.size_box.setValue(toolbar.size_box.value())
            self.line_spacing_box.setCurrentIndex(toolbar.line_spacing_box.currentIndex())
        finally:
            for control in (self.size_box, self.line_spacing_box):
                control.blockSignals(False)
        self.line_spacing_box.setEnabled(toolbar.line_spacing_box.isEnabled())
        self.color_button.setIcon(toolbar.color_button.icon())
        self._refresh_swatches(toolbar.current_color.name().lower())

    def _refresh_swatches(self, current: str) -> None:
        for key, _label, color in QUICK_COLORS:
            selected = color == current
            border = "#2563eb" if selected else "#e2e8f0"
            width = 2 if selected else 1
            self.color_buttons[key].setStyleSheet(
                f"QToolButton#rangeQuickColor{{background:{color};border:{width}px solid {border};"
                f"border-radius:9px;padding:0;min-width:{18 - 2 * width}px;max-width:{18 - 2 * width}px;"
                f"min-height:{18 - 2 * width}px;max-height:{18 - 2 * width}px;}}"
            )

    def _apply_size(self, value: int) -> None:
        if self.toolbar is not None:
            self.toolbar.size_box.setValue(int(value))

    def _apply_line_spacing(self, index: int) -> None:
        if self.toolbar is None:
            return
        self.toolbar.line_spacing_box.setCurrentIndex(index)
        self.toolbar._apply_line_spacing_index(index)

    def _apply_color(self, color: str) -> None:
        if self.toolbar is not None:
            self.toolbar.apply_color(QColor(color))

    def _choose_color(self) -> None:
        if self.toolbar is not None:
            self.toolbar.color_menu.popup(self.color_button.mapToGlobal(QPoint(0, self.color_button.height())))

    def _apply_preset(self, slot: int) -> None:
        if self.toolbar is None:
            return
        if load_preset(self.toolbar.store, slot) is None:
            # 빈 칸은 적용되지 않았으니 눌린 표시를 되돌린 뒤 저장 메뉴를 연다.
            self.preset_strip.set_active(self.toolbar._active_preset_slot)
            button = self.preset_strip.buttons[slot]
            self._show_preset_menu(slot, button.mapToGlobal(button.rect().bottomLeft()))
            return
        self.toolbar.apply_preset(slot)
        self.editor.setFocus()

    def _apply(self, name: str) -> None:
        if self.toolbar is not None:
            self.toolbar.style_buttons[name].click()

    def clear_selection(self) -> None:
        cursor = self.editor.textCursor()
        cursor.clearSelection()
        self.editor.setTextCursor(cursor)
        self.sync()
        self.editor.setFocus()

    def _style(self, reserved: bool) -> None:
        if reserved:
            self.setStyleSheet(
                "QFrame#textFormatRangeBar{background:#f8fafc;border-top:1px solid #cbd5e1;}"
                "QToolButton{color:#172033;border:0;padding:3px 6px;min-height:25px;}"
                "QFrame#textFormatRangeSeparator{background:#dbe2ea;border:0;margin:7px 0px;}"
                "QSpinBox,QComboBox{background:#ffffff;color:#172033;border:1px solid #cbd5e1;border-radius:5px;min-height:0px;max-height:26px;}"
            )
        else:
            self.setStyleSheet(
                "QFrame#textFormatRangeBar{background:#172033;border-radius:9px;}"
                "QToolButton{color:white;border:0;padding:3px 6px;min-height:25px;}"
                "QFrame#textFormatRangeSeparator{background:#3b475c;border:0;margin:7px 0px;}"
                "QSpinBox,QComboBox{background:#ffffff;color:#172033;border:1px solid #cbd5e1;border-radius:5px;min-height:0px;max-height:26px;}"
            )

    def _candidate_clear(self, candidate: QRect) -> bool:
        view = self.editor.viewport()
        if (candidate.left() < 0 or candidate.top() < 0
                or candidate.right() + self.MARGIN >= view.width()
                or candidate.bottom() >= view.height()):
            return False
        # Sample every visible text line crossing the bar. A spare tail on the
        # selected line is insufficient if the bar also spans an adjacent line.
        for y in range(candidate.top(), candidate.bottom() + 1, 3):
            cursor = self.editor.cursorForPosition(QPoint(view.width() - 1, y))
            rect = self.editor.cursorRect(cursor)
            if rect.top() <= y <= rect.bottom() and rect.x() >= candidate.left():
                return False
        return True

    def sync(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            cursor = self.editor.textCursor()
            selected = cursor.hasSelection() and not (
                self.editor.character_selection.count() or self.editor.block_selection.count()
            ) and self.toolbar is not None
            if not selected or QApplication.mouseButtons() != Qt.MouseButton.NoButton:
                self.is_reserved = False
                self.hide()
                self.editor._sync_selection_bar_height()
                return
            end = QTextCursor(cursor)
            end.setPosition(cursor.selectionEnd())
            tail = self.editor.cursorRect(end)
            # Measure the full reserved form, including its close button. This
            # also makes the floating candidate conservative at narrow widths.
            self.close_button.show()
            self.ensurePolished()
            width = self.sizeHint().width()
            candidate = QRect(
                tail.right() + self.GAP,
                tail.top() + (tail.height() - self.HEIGHT) // 2,
                width, self.HEIGHT,
            )
            reserved = not self._candidate_clear(candidate)
            self.is_reserved = reserved
            self._style(reserved)
            self.editor._sync_selection_bar_height()
            frame = self.editor.frameWidth()
            if reserved:
                self.setGeometry(
                    frame, self.editor.height() - frame - self.HEIGHT,
                    max(0, self.editor.width() - frame * 2), self.HEIGHT,
                )
                self.close_button.show()
            else:
                view = self.editor.viewport().geometry()
                self.setGeometry(view.x() + candidate.x(), view.y() + candidate.y(),
                                 candidate.width(), candidate.height())
                self.close_button.hide()
            self.show()
            self.raise_()
        finally:
            self._syncing = False
