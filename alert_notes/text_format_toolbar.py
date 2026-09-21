from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QConicalGradient, QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygon, QShortcut, QTextCharFormat
from PyQt6.QtWidgets import (
    QComboBox, QFontComboBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QMenu, QPushButton,
    QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from .insert_menu import build_insert_menu
from .format_presets import (
    PRESET_COUNT, clear_preset, ensure_first_preset, load_preset, load_preset_name,
    save_preset, save_preset_name,
)
from .note_shortcuts import FORMAT_SHORTCUTS
from .editor_icons import compact_combo_style, gear_icon
from .format_preset_strip import PresetStrip
from .value_input_guard import install_value_input_guard


class TextFormatToolbar(QWidget):
    shortcut_settings_requested = pyqtSignal()
    presets_changed = pyqtSignal()
    active_preset_changed = pyqtSignal(object)
    # 커서 서식을 읽어 크기·줄 간격·색을 맞춘 뒤.  선택 서식 창이 같은 값을 따라간다.
    format_synced = pyqtSignal()
    VISIBLE_PRESET_COUNT = 3
    # 두 번째 줄의 도구 단추.  테두리 없이 좁게 두어 한 줄로 끝낸다.
    TOOL_BUTTON_WIDTH = 28
    TOOL_BUTTON_HEIGHT = 28
    LEGACY_FONT_BOX_WIDTH = 210
    COMPACT_FONT_BOX_WIDTH = 150
    SIZE_BOX_WIDTH = 44
    LINE_SPACING_BOX_WIDTH = 73

    COMPACT_FONT_BOX_MAX_WIDTH = COMPACT_FONT_BOX_WIDTH
    # 창 기본·최소 폭이 줄어든 양(글꼴 칸 210→130 때 정함).  글꼴 칸을 150으로
    # 넓혀도 크기·줄 간격 칸이 더 줄어 첫 줄은 짧아졌으므로 창 폭 계약은 그대로 둔다.
    WIDTH_REDUCTION = 80
    PALETTE_COLORS = (
        "#000000", "#8c8c8c", "#9b111e", "#e11d48", "#ff7a2f", "#ffe600", "#16a34a", "#14b8a6", "#2563eb", "#8b4fb3",
        "#ffffff", "#d1d5db", "#b7795b", "#f3a6a6", "#facc15", "#f4e7ad", "#a3e635", "#8cc7e8", "#7ea4c6", "#c4b5e8",
    )
    def __init__(self, editor, store, parent=None):
        super().__init__(parent or editor)
        self.editor = editor
        self.store = store
        self._shutdown = False
        self._active_preset_slot: int | None = None
        self._applying_preset = False
        self._base_font_width = self.COMPACT_FONT_BOX_WIDTH
        self.current_color = QColor("black")
        self.shortcuts: list[QShortcut] = []
        self._build_ui()
        ensure_first_preset(store, self.font_box.currentFont().family())
        self.sync_timer = QTimer(self)
        self.sync_timer.setSingleShot(True)
        self.sync_timer.setInterval(40)
        self.sync_timer.timeout.connect(self._sync_from_cursor)
        editor.cursorPositionChanged.connect(self._queue_cursor_sync)
        editor.currentCharFormatChanged.connect(self._queue_cursor_sync)
        editor.selectionChanged.connect(self._queue_cursor_sync)
        editor.block_selection.changed.connect(self._queue_cursor_sync)
        self.apply_default()
        self.reload_presets()
        self.reload_shortcuts()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        first, second = QHBoxLayout(), QHBoxLayout()
        first.setSpacing(4)
        second.setSpacing(2)
        self.second_layout = second
        self.font_box = QFontComboBox()
        self.font_box.setAccessibleName("글씨체")
        self.font_box.setToolTip("글씨체")
        self.font_box.setFixedWidth(self.COMPACT_FONT_BOX_WIDTH)
        self.font_box.setStyleSheet(compact_combo_style())
        self.font_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.size_box = QSpinBox()
        self.size_box.setRange(8, 72)
        self.size_box.setValue(10)
        self.size_box.setAccessibleName("글자 크기")
        self.size_box.setToolTip("글자 크기")
        self.size_box.setObjectName("formatSizeBox")
        # 위아래 화살표가 숫자 칸을 8px 까지 밀어내던 자리.  숫자만 두고
        # ↑↓ 키·입력·(칸을 누른 뒤) 휠로 바꾼다.
        self.size_box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.size_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.size_box.setStyleSheet("QSpinBox#formatSizeBox{padding:0 3px;}")
        self.size_box.setFixedWidth(self.SIZE_BOX_WIDTH)
        self.line_spacing_box = QComboBox()
        self.line_spacing_box.setAccessibleName("줄 간격")
        self.line_spacing_box.setToolTip("줄 간격")
        self.line_spacing_box.setFixedWidth(self.LINE_SPACING_BOX_WIDTH)
        self.line_spacing_box.setStyleSheet(compact_combo_style())
        self.line_spacing_box.addItem("혼합", None)
        for value, label in ((1.0, "1.0"), (1.15, "1.15"), (1.5, "1.5"), (2.0, "2.0")):
            self.line_spacing_box.addItem(label, value)
        self.line_spacing_box.setCurrentIndex(1)
        first.addWidget(self.font_box)
        first.addWidget(self.size_box)
        first.addWidget(self.line_spacing_box)
        color_controls = QWidget()
        color_layout = QVBoxLayout(color_controls)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(3)
        color_row = QHBoxLayout()
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.setSpacing(4)
        self.color_button = QPushButton()
        self.color_button.setObjectName("textColorPickerButton")
        self.color_button.setAccessibleName("글자 색상 선택")
        self.color_button.setFixedWidth(30)
        color_row.addWidget(self.color_button)
        self.color_buttons = {}
        for key, label, color in (("black", "검정", "#000000"), ("red", "빨강", "#d00000"), ("blue", "파랑", "#0057d9")):
            button = QPushButton()
            button.setObjectName("quickTextColorButton")
            button.setAccessibleName(label)
            button.setFixedSize(24, 24)
            button.setStyleSheet(self._swatch_style(color))
            button.clicked.connect(lambda _checked=False, value=color: self.apply_color(QColor(value)))
            self.color_buttons[key] = button
            color_row.addWidget(button)
        color_layout.addLayout(color_row)
        self._color_controls_layout = color_layout
        first.addWidget(self._group_separator())
        first.addWidget(color_controls)
        self.style_buttons = {}
        self.style_button_labels = {
            "bold": "B", "italic": "I", "underline": "U", "strike": "S",
        }
        for key, label in self.style_button_labels.items():
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("formatToggleButton")
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.toggled.connect(lambda checked, name=key: self._style_toggled(name, checked))
            self.style_buttons[key] = button
            second.addWidget(button)
        second.addWidget(self._group_separator())
        self.bullet_button = QPushButton("•")
        self.bullet_button.setAccessibleName("글머리표")
        self.bullet_button.setToolTip("글머리표 (Ctrl+Shift+5)")
        self.bullet_button.setObjectName("formatToggleButton")
        self.bullet_button.setCheckable(True)
        self.bullet_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.bullet_button.clicked.connect(self.editor.toggle_bullet_list)
        second.addWidget(self.bullet_button)
        self.checklist_button = QPushButton("☐")
        self.checklist_button.setAccessibleName("체크리스트")
        self.checklist_button.setToolTip("체크리스트")
        self.checklist_button.setObjectName("formatToggleButton")
        self.checklist_button.setCheckable(True)
        self.checklist_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.checklist_button.clicked.connect(self.editor.toggle_checklist)
        second.addWidget(self.checklist_button)
        # 넣을 수 있는 것들을 한 단추 아래 모은다.  서식과 달리 "지금 켜져 있음"
        # 이라는 상태가 없는 동작이므로 켜짐/꺼짐 표시를 두지 않는다.
        self.insert_button = QPushButton("＋")
        self.insert_button.setAccessibleName("기능 넣기")
        self.insert_button.setToolTip("기능 넣기 (토글 · 페이지 추가)")
        self.insert_button.setObjectName("formatInsertButton")
        self.insert_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.insert_menu = build_insert_menu(self.editor, self.insert_button)
        self.insert_button.setMenu(self.insert_menu)
        second.addWidget(self.insert_button)
        self.image_button = QPushButton()
        self.image_button.setAccessibleName("이미지 삽입")
        self.image_button.setToolTip("이미지 삽입")
        self.image_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.image_button.setIcon(_image_insert_icon())
        self.image_button.setIconSize(QSize(18, 18))
        self.image_button.setObjectName("formatToolButton")
        self.image_button.clicked.connect(self.editor.choose_and_insert_image)
        second.addWidget(self.image_button)
        second.addWidget(self._group_separator())
        self._equalize_format_button_sizes()
        self.default_button = QPushButton()
        self.default_button.setObjectName("formatToolButton")
        self.default_button.setIcon(_reset_format_icon())
        self.default_button.setIconSize(QSize(18, 18))
        self.default_button.setAccessibleName("선택한 글자 서식을 기본값으로 되돌리기")
        self.default_button.setToolTip("선택한 글자의 서식을 기본값으로 되돌립니다")
        self.default_button.setFixedSize(28, 28)
        second.addWidget(self.default_button)
        second.addWidget(self._group_separator())
        self.preset_strip = PresetStrip(self)
        self.preset_buttons = self.preset_strip.buttons
        self.preset_strip.apply_requested.connect(self.apply_preset)
        self.preset_strip.menu_requested.connect(self._show_slot_menu)
        second.addWidget(self.preset_strip)
        self.preset_settings_button = QToolButton(self)
        self.preset_settings_button.setIcon(gear_icon())
        self.preset_settings_button.setIconSize(QSize(18, 18))
        self.preset_settings_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.preset_settings_button.setObjectName("formatPresetSettings")
        self.preset_settings_button.setAccessibleName("서식 프리셋 및 편집 단축키 설정")
        self.preset_settings_button.setToolTip("서식 1~3 관리 · 편집 단축키 설정")
        self.preset_settings_button.setFixedSize(28, 28)
        self.preset_settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.preset_settings_menu = QMenu(self.preset_settings_button)
        for slot in range(1, min(PRESET_COUNT, self.VISIBLE_PRESET_COUNT) + 1):
            self.preset_settings_menu.addMenu(self.slot_menu(slot, self.preset_settings_menu))
        self.preset_settings_menu.addSeparator()
        self.preset_settings_menu.addAction("편집 단축키 설정…", self.shortcut_settings_requested.emit)
        self.preset_settings_menu.aboutToShow.connect(self._refresh_settings_menu_titles)
        self.preset_settings_button.setMenu(self.preset_settings_menu)
        second.addWidget(self.preset_settings_button)
        # Without a trailing stretch the fixed-size controls get the leftover
        # width spread between them, so the toolbar reads as scattered buttons
        # instead of one left-aligned group.
        first.addStretch(1)
        second.addStretch(1)
        root.addLayout(first)
        root.addLayout(second)
        # Two 28px rows plus their 4px gap must never be vertically squeezed.
        self.setMinimumHeight(60)
        self.font_box.currentFontChanged.connect(lambda font: self.apply_family(font.family()))
        self.font_box.currentFontChanged.connect(self._show_font_name_from_start)
        self.size_box.valueChanged.connect(self.apply_size)
        self.line_spacing_box.activated.connect(self._apply_line_spacing_index)
        self._build_color_menu()
        self.color_button.clicked.connect(self.choose_color)
        self.default_button.clicked.connect(self.apply_default)
        self._value_input_guard = install_value_input_guard(self)
        self.editor.character_selection.changed.connect(self._sync_character_range_mode)

    def _sync_character_range_mode(self) -> None:
        # Keep only inline formatting available while character ranges are
        # highlighted; structural tools would target an unrelated caret block.
        enabled = not self.editor.character_selection.count()
        for widget in (
            self.line_spacing_box, self.bullet_button, self.checklist_button,
            self.insert_button, self.image_button,
        ):
            widget.setEnabled(enabled)

    def _apply_line_spacing_index(self, index: int) -> None:
        value = self.line_spacing_box.itemData(index)
        if value is not None:
            self.editor.apply_line_spacing(float(value))

    @staticmethod
    def _group_separator() -> QFrame:
        """묶음을 나누는 가는 세로선.  테두리를 걷어낸 자리를 대신한다."""
        line = QFrame()
        line.setObjectName("formatGroupLine")
        line.setFrameShape(QFrame.Shape.VLine)
        return line

    def _show_font_name_from_start(self, font=None) -> None:
        """긴 글꼴 이름은 끝이 아니라 앞부터 보이게 한다(Segoe UI Variable)."""
        family = self.font_box.currentFont().family()
        self.font_box.setToolTip(f"글씨체 · {family}")
        line_edit = self.font_box.lineEdit()
        if line_edit is not None:
            QTimer.singleShot(0, lambda: line_edit.setCursorPosition(0))

    def _refresh_settings_menu_titles(self) -> None:
        for action in self.preset_settings_menu.actions():
            menu = action.menu()
            if menu is None:
                continue
            slot = int(menu.property("presetSlot") or 0)
            if slot:
                menu.setTitle(load_preset_name(self.store, slot) or f"서식 {slot}")

    def apply_ui_scale(self, scale: float) -> None:
        """앱 확대 배율에 맞춰 고정 크기를 한 번에 키운다.

        테마의 px 값은 scaled_stylesheet 가 키우므로, 코드에서 고정한 크기도 같은
        배율로 맞춰야 최소·최대 크기가 서로 어긋나 줄이 넘치지 않는다.
        """
        def px(value: int) -> int:
            return max(1, round(value * scale))
        target = QSize(px(self.TOOL_BUTTON_WIDTH), px(self.TOOL_BUTTON_HEIGHT))
        for button in (*self.style_buttons.values(), self.bullet_button, self.checklist_button,
                       self.insert_button, self.image_button, self.default_button,
                       self.preset_settings_button):
            if button.objectName() != "titleFoldButton":
                button.setFixedSize(target)
        self.font_box.setFixedWidth(px(self.COMPACT_FONT_BOX_WIDTH))
        self._base_font_width = px(self.COMPACT_FONT_BOX_WIDTH)
        self.size_box.setFixedWidth(px(self.SIZE_BOX_WIDTH))
        self.line_spacing_box.setFixedWidth(px(self.LINE_SPACING_BOX_WIDTH))
        self.color_button.setFixedWidth(px(30))
        for button in self.color_buttons.values():
            button.setFixedSize(px(24), px(24))
        self.preset_strip.set_button_size(px(26))
        # At 150% the same two rows can be wider than the editor pane of a
        # 1080px window. Use separator space before sacrificing any action.
        compact_second = scale >= 1.5
        self.second_layout.setSpacing(0 if compact_second else 2)
        for index in range(self.second_layout.count()):
            widget = self.second_layout.itemAt(index).widget()
            if widget is None or widget.objectName() != "formatGroupLine":
                continue
            if compact_second:
                widget.setFixedWidth(px(7))
            else:
                widget.setMinimumWidth(0)
                widget.setMaximumWidth(16777215)
        self.setMinimumHeight(px(60))
        self._fit_font_box_to_row()
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_font_box_to_row()

    def _fit_font_box_to_row(self) -> None:
        available = self.contentsRect().width()
        if available <= 0:
            return
        row = self.layout().itemAt(0).layout()
        base = self._base_font_width
        needed_at_base = row.sizeHint().width() - self.font_box.width() + base
        minimum = self.font_box.fontMetrics().horizontalAdvance(self.font_box.currentText()) + 28
        target = max(minimum, base - max(0, needed_at_base - available))
        if target != self.font_box.width():
            self.font_box.setFixedWidth(target)
            row.invalidate()
            self.layout().activate()

    def _equalize_format_button_sizes(self) -> None:
        target = QSize(self.TOOL_BUTTON_WIDTH, self.TOOL_BUTTON_HEIGHT)
        self.image_button.setFixedSize(target)
        for button in (*self.style_buttons.values(), self.bullet_button,
                       self.checklist_button, self.insert_button):
            if button.objectName() != "titleFoldButton":
                button.setFixedSize(target)
    def move_presets_to(self, target_layout: QHBoxLayout) -> None:
        """Place visible presets below the editor while preserving saved slot data."""
        self.second_layout.removeWidget(self.preset_strip)
        target_layout.addWidget(self.preset_strip)
        self.updateGeometry()

    def slot_menu(self, slot: int, parent=None) -> QMenu:
        menu = QMenu(load_preset_name(self.store, slot) or f"서식 {slot}", parent or self)
        menu.setProperty("presetSlot", slot)
        menu.addAction("현재 서식 저장", lambda _checked=False, value=slot: self.save_current_preset(value))
        menu.addAction("이름 바꾸기", lambda _checked=False, value=slot: self.rename_preset(value))
        menu.addAction("초기화", lambda _checked=False, value=slot: self.clear_saved_preset(value))
        return menu

    def _show_slot_menu(self, slot: int, global_pos: QPoint | None = None) -> None:
        self._slot_popup_menu = self.slot_menu(slot, self)
        if self._slot_popup_menu.actions():
            self._slot_popup_menu.setActiveAction(self._slot_popup_menu.actions()[0])
        button = self.preset_buttons[slot]
        pos = global_pos or button.mapToGlobal(button.rect().bottomLeft())
        self._slot_popup_menu.popup(pos)

    @staticmethod
    def _swatch_style(color: str, selected: bool = False) -> str:
        border = "#2563eb" if selected else "#94a3b8"
        width = "2px" if selected else "1px"
        return f"background:{color}; border:{width} solid {border}; border-radius:9px; padding:0;"

    def _build_color_menu(self) -> None:
        self.color_menu = QMenu(self)
        self.color_menu.setObjectName("textColorPalette")
        panel = QWidget(self.color_menu)
        grid = QGridLayout(panel)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(5)
        self.palette_buttons: dict[str, QToolButton] = {}
        for index, color in enumerate(self.PALETTE_COLORS):
            button = QToolButton(panel)
            button.setObjectName("textColorPaletteSwatch")
            button.setAccessibleName(f"글자 색상 {color}")
            button.setToolTip(color.upper())
            button.setFixedSize(24, 24)
            button.setStyleSheet(self._swatch_style(color))
            button.clicked.connect(lambda _checked=False, value=color: self._select_palette_color(value))
            grid.addWidget(button, index // 10, index % 10)
            self.palette_buttons[color.lower()] = button
        action = QWidgetAction(self.color_menu)
        action.setDefaultWidget(panel)
        self.color_menu.addAction(action)

    def _select_palette_color(self, color: str) -> None:
        self.apply_color(QColor(color))
        self.color_menu.close()

    def _merge(self, fmt: QTextCharFormat, *, restore_editor_focus: bool = True) -> None:
        if not self._applying_preset:
            self._active_preset_slot = None
            self._refresh_preset_buttons()
        self.editor.apply_character_format(fmt)
        if restore_editor_focus:
            self.editor.setFocus()

    def apply_family(self, family: str) -> None:
        fmt = QTextCharFormat()
        fmt.setFontFamily(family)
        self._merge(fmt, restore_editor_focus=False)

    def apply_size(self, size) -> None:
        value = float(size)
        if value > 0:
            fmt = QTextCharFormat()
            fmt.setFontPointSize(value)
            self._merge(fmt, restore_editor_focus=False)

    def apply_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self.current_color = color
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        self._merge(fmt)
        self._refresh_color_button()

    def choose_color(self) -> None:
        self.color_menu.popup(self.color_button.mapToGlobal(QPoint(0, self.color_button.height())))

    def apply_style(self, name: str, checked: bool) -> None:
        fmt = QTextCharFormat()
        if name == "bold":
            fmt.setFontWeight(QFont.Weight.Bold if checked else QFont.Weight.Normal)
        elif name == "italic":
            fmt.setFontItalic(checked)
        elif name == "underline":
            fmt.setFontUnderline(checked)
        else:
            fmt.setFontStrikeOut(checked)
        self._merge(fmt)

    def _style_toggled(self, name: str, checked: bool) -> None:
        self._refresh_style_button(name)
        self.apply_style(name, checked)

    def _refresh_style_button(self, name: str) -> None:
        button = self.style_buttons[name]
        checked = button.isChecked()
        accessible_label = FORMAT_SHORTCUTS[name][0]
        button.setAccessibleName(f"{accessible_label} {'선택됨' if checked else '선택 안 됨'}")

    def _refresh_style_buttons(self) -> None:
        for name in self.style_buttons:
            self._refresh_style_button(name)

    def apply_default(self) -> None:
        self._active_preset_slot = None
        data = self.format_data()
        data.update(size=10, color="#000000", bold=False, italic=False, underline=False, strike=False)
        self.apply_data(data)

    def format_data(self) -> dict:
        return {
            "family": self.font_box.currentFont().family(), "size": float(self.size_box.value()),
            "color": self.current_color.name(),
            **{key: button.isChecked() for key, button in self.style_buttons.items()},
        }

    def apply_data(self, data: dict) -> None:
        fmt = QTextCharFormat()
        fmt.setFontFamily(str(data["family"]))
        fmt.setFontPointSize(float(data["size"]))
        fmt.setForeground(QColor(str(data["color"])))
        fmt.setFontWeight(QFont.Weight.Bold if data["bold"] else QFont.Weight.Normal)
        fmt.setFontItalic(bool(data["italic"]))
        fmt.setFontUnderline(bool(data["underline"]))
        fmt.setFontStrikeOut(bool(data["strike"]))
        self._merge(fmt)
        self._sync_from_format(fmt)

    def save_current_preset(self, slot: int) -> None:
        save_preset(self.store, slot, self.format_data())
        self.reload_presets()

    def clear_saved_preset(self, slot: int) -> None:
        clear_preset(self.store, slot)
        self.reload_presets()

    def apply_preset(self, slot: int) -> None:
        data = load_preset(self.store, slot)
        if data is None:
            self._active_preset_slot = None
            self._refresh_preset_buttons()
            self._show_slot_menu(slot)
            return
        self._active_preset_slot = slot
        self._applying_preset = True
        try:
            self.apply_data(data)
        finally:
            self._applying_preset = False
        self._refresh_preset_buttons()

    def rename_preset(self, slot: int) -> None:
        """A numbered slot says nothing about what it applies."""
        current = load_preset_name(self.store, slot)
        name, accepted = QInputDialog.getText(
            self, "서식 이름", f"서식 {slot}의 이름을 입력하세요. 비우면 번호로 돌아갑니다.",
            text=current,
        )
        if not accepted:
            return
        save_preset_name(self.store, slot, name[:12])
        self.reload_presets()

    def reload_presets(self) -> None:
        self.preset_strip.reload(self.store)
        if self._active_preset_slot is not None and load_preset(self.store, self._active_preset_slot) is None:
            self._active_preset_slot = None
        self._refresh_preset_buttons()
        self.presets_changed.emit()

    def _refresh_preset_buttons(self) -> None:
        active = self._active_preset_slot
        if active is not None and not self._current_format_matches_preset(active):
            active = None
            self._active_preset_slot = None
        self.preset_strip.set_active(active)
        self.active_preset_changed.emit(active)

    def _current_format_matches_preset(self, slot: int) -> bool:
        saved = load_preset(self.store, slot)
        if saved is None:
            return False
        current = self.format_data()
        return (
            str(current["family"]) == str(saved["family"])
            and abs(float(current["size"]) - float(saved["size"])) < 0.01
            and QColor(str(current["color"])).name() == QColor(str(saved["color"])).name()
            and all(bool(current[key]) == bool(saved[key]) for key in ("bold", "italic", "underline", "strike"))
        )

    def reload_shortcuts(self) -> None:
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.shortcuts = []
        key_handlers = {}
        for action, (label, setting, default) in FORMAT_SHORTCUTS.items():
            text = self.store.setting(setting, default)
            shortcut = QShortcut(QKeySequence(text), self.editor)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            button = self.style_buttons.get(action) or self.color_buttons.get(action)
            if action in self.style_buttons:
                handler = lambda name=action: self.editor.toggle_character_style(name)
            else:
                color = {"black": "#000000", "red": "#d00000", "blue": "#0057d9"}[action]
                handler = lambda value=color: self.apply_color(QColor(value))
            shortcut.activated.connect(handler)
            key_handlers[QKeySequence(text).toString()] = handler
            button.setToolTip(f"{label} ({text})")
            self.shortcuts.append(shortcut)
        self.editor.format_shortcut_handlers = key_handlers

    def _sync_from_cursor(self) -> None:
        if self._shutdown:
            return
        self._sync_from_format(self.editor.currentCharFormat())

    def _queue_cursor_sync(self, *_args) -> None:
        """Coalesce high-frequency editor signals without leaving a zero-delay callback."""
        if not self._shutdown:
            self.sync_timer.start()

    def shutdown(self) -> None:
        """Stop queued editor work before the parent widget/store is torn down."""
        if self._shutdown:
            return
        self._shutdown = True
        self.sync_timer.stop()
        for signal in (self.editor.cursorPositionChanged, self.editor.currentCharFormatChanged):
            try:
                signal.disconnect(self._queue_cursor_sync)
            except (RuntimeError, TypeError):
                pass

    def _sync_from_format(self, fmt: QTextCharFormat) -> None:
        controls = [
            self.font_box, self.size_box, self.line_spacing_box, self.bullet_button, self.checklist_button,
            *self.style_buttons.values(),
        ]
        for control in controls:
            control.blockSignals(True)
        try:
            family = fmt.font().family()
            if family and self.font_box.currentFont().family() != family:
                # QFont(family) has an unset point size (-1).  Passing that
                # font to QFontComboBox makes Qt repeatedly call
                # QFont::setPointSize(-1) while cursor formatting is synced.
                # The combo box only uses the family here, but give the font a
                # valid size as well so the sync remains warning-free.
                point_size = fmt.fontPointSize()
                if point_size <= 0:
                    point_size = self.editor.fontPointSize()
                if point_size <= 0:
                    point_size = 10.0
                family_font = QFont(family)
                family_font.setPointSizeF(point_size)
                self.font_box.setCurrentFont(family_font)
            if fmt.fontPointSize() > 0:
                self.size_box.setValue(round(fmt.fontPointSize()))
            spacing = self.editor.selected_line_spacing()
            index = self.line_spacing_box.findData(spacing) if spacing is not None else 0
            self.line_spacing_box.setCurrentIndex(max(0, index))
            color = fmt.foreground().color()
            if color.isValid():
                self.current_color = color
            self.style_buttons["bold"].setChecked(fmt.fontWeight() >= QFont.Weight.Bold)
            self.style_buttons["italic"].setChecked(fmt.fontItalic())
            self.style_buttons["underline"].setChecked(fmt.fontUnderline())
            self.style_buttons["strike"].setChecked(fmt.fontStrikeOut())
            self.bullet_button.setChecked(self.editor.current_block_is_bullet_list())
            self.checklist_button.setChecked(self.editor.current_block_is_checklist())
        finally:
            for control in controls:
                control.blockSignals(False)
        self._refresh_style_buttons()
        self._refresh_preset_buttons()
        self._refresh_color_button()
        self.format_synced.emit()

    def _refresh_color_button(self) -> None:
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QConicalGradient(9, 9, 0)
        for position, color in ((0.0, "#f43f5e"), (0.18, "#facc15"), (0.36, "#22c55e"), (0.54, "#06b6d4"), (0.72, "#2563eb"), (0.88, "#a855f7"), (1.0, "#f43f5e")):
            gradient.setColorAt(position, QColor(color))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 15, 15)
        painter.setBrush(QColor("white"))
        painter.setPen(QColor("#64748b"))
        painter.drawEllipse(11, 0, 7, 7)
        painter.drawLine(14, 2, 14, 5)
        painter.drawLine(12, 4, 16, 4)
        painter.end()
        self.color_button.setIcon(QIcon(pixmap))
        self.color_button.setIconSize(QSize(18, 18))
        self.color_button.setToolTip(f"글자 색상 선택 (현재 {self.current_color.name().upper()})")
        for color, button in getattr(self, "palette_buttons", {}).items():
            button.setStyleSheet(self._swatch_style(color, color == self.current_color.name().lower()))
        for key, button in self.color_buttons.items():
            color = {"black": "#000000", "red": "#d00000", "blue": "#0057d9"}[key]
            button.setStyleSheet(self._swatch_style(color, color == self.current_color.name().lower()))
        self.format_synced.emit()

def _image_insert_icon() -> QIcon:
    """Return a compact photo-outline icon that remains crisp at UI scale."""
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#172033"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawRoundedRect(2, 3, 16, 14, 2, 2)
    painter.drawEllipse(5, 6, 3, 3)
    painter.drawLine(3, 15, 8, 10)
    painter.drawLine(8, 10, 11, 13)
    painter.drawLine(11, 13, 14, 9)
    painter.drawLine(14, 9, 18, 13)
    painter.end()
    return QIcon(pixmap)


def _reset_format_icon() -> QIcon:
    """Compact reset arrow used instead of the wide default-format label."""
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#475569"), 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(4, 4, 12, 12, 35 * 16, 280 * 16)
    painter.setBrush(QColor("#475569"))
    painter.drawPolygon(QPolygon([QPoint(3, 4), QPoint(8, 4), QPoint(4, 9)]))
    painter.end()
    return QIcon(pixmap)
