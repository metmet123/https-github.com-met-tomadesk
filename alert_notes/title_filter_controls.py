"""Stage G-C presentation; filtering and storage stay in MemoListPanel."""
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QFrame, QLabel, QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidgetAction
from .title_symbols import TitleValueCount


class TitleFilterHelp(QFrame):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class TitleFilterControls:
    def _filter_scale(self):
        return float(getattr(self, "_title_filter_scale", 1.0))

    def apply_title_filter_scale(self, scale):
        self._title_filter_scale = float(scale)
        self.search.setMinimumWidth(round(120 * scale))
        for button in (self.title_symbol_button, self.title_prefix_button, self.reset_filters_button):
            button.setFixedHeight(round(self.BUTTON_HEIGHT * scale))
        if getattr(self, "title_filter_help", None) is not None:
            self.title_filter_help.close()
        self._update_title_symbol_button()
        self._update_title_prefix_button()
        self._layout_category_filters()

    def _update_title_prefix_button(self):
        self._update_title_button("prefix")

    def _update_title_button(self, kind):
        button = getattr(self, f"title_{kind}_button")
        values = getattr(self, f"_title_{kind}_counts")
        key = getattr(self, f"title_{kind}_filter")
        value = next((v for v in values if v.key == key), None) if key is not None else (values[0] if values else None)
        empty = key is None and value is None
        button.setChecked(key is not None)
        if button.property("empty") != empty:
            button.setProperty("empty", empty)
            button.style().unpolish(button)
            button.style().polish(button)
        if empty:
            text = "기호" if kind == "symbol" else "머리말"
            tooltip = "제목 앞 기호로 모아 보기" if kind == "symbol" else "제목 앞 [머리말]로 모아 보기"
        else:
            display = value.display if value else key
            count = value.count if value else 0
            suffix = " ▾" if key is not None else f" {count} ▾"
            full_display = display if kind == "symbol" else f"[{display}]"
            tooltip = (f"{full_display} 필터 적용 중 · {count}개" if key is not None
                       else f"제목이 {full_display}로 시작하는 메모 {count}개 · 눌러서 고르기")
            if kind == "prefix":
                scale = self._filter_scale()
                available = self.width() - self.layout().contentsMargins().left() - self.layout().contentsMargins().right()
                cap = min(round(120 * scale), max(40, available - round(120 * scale) - self.title_symbol_button.sizeHint().width() - 8))
                button.setMaximumWidth(cap)
                text_budget = min(round(96 * scale), max(0, cap - round(24 * scale)))
                inner_budget = max(0, text_budget - button.fontMetrics().horizontalAdvance("[]" + suffix))
                display = "[" + button.fontMetrics().elidedText(display, Qt.TextElideMode.ElideRight, inner_budget) + "]"
            text = display + suffix
        if kind == "prefix" and empty:
            cap = round(120 * self._filter_scale())
        if kind == "prefix":
            button.setFixedWidth(min(cap, button.fontMetrics().horizontalAdvance(text) + round(24 * self._filter_scale())))
        # Measure/elide the literal title first, then escape Qt mnemonics.
        button.setText(text.replace("&", "&&"))
        button.setToolTip(tooltip)

    def _build_title_symbol_menu(self):
        return self._build_title_menu("symbol")

    def _build_title_prefix_menu(self):
        return self._build_title_menu("prefix")

    def _build_title_menu(self, kind):
        button = getattr(self, f"title_{kind}_button")
        old = getattr(self, f"title_{kind}_menu", None)
        if old is not None:
            old.deleteLater()
        menu = QMenu(button)
        setattr(self, f"title_{kind}_menu", menu)
        key = getattr(self, f"title_{kind}_filter")
        setter = getattr(self, f"_set_title_{kind}_filter")
        values = list(getattr(self, f"_title_{kind}_counts"))  # already count/recency/key ordered
        if key is not None and not any(v.key == key for v in values):
            values.insert(0, TitleValueCount(key, key, 0, ""))
        search = None
        if kind == "prefix" and len(values) > 10:
            widget_action = QWidgetAction(menu)
            search = QLineEdit(menu)
            search.setPlaceholderText("머리말 찾기")
            search.setAccessibleName("머리말 찾기")
            widget_action.setDefaultWidget(search)
            menu.addAction(widget_action)
        all_action = menu.addAction("전체")
        all_action.setCheckable(True)
        all_action.setChecked(key is None)
        all_action.triggered.connect(lambda: setter(None))
        menu.addSeparator()
        entries = []
        for value in values:
            display = value.display if kind == "symbol" else f"[{value.display}]"
            action = menu.addAction(f"{display.replace('&', '&&')}  {value.count}")
            action.setData(value.key)
            action.setCheckable(True)
            action.setChecked(value.key == key)
            action.triggered.connect(lambda _checked=False, selected=value.key: setter(selected))
            entries.append((action, value))
        if search is not None:
            no_match = menu.addAction("맞는 머리말이 없습니다")
            no_match.setEnabled(False)
            no_match.setVisible(False)
            def narrow(text):
                from .title_symbols import title_prefix_key
                query = title_prefix_key(text.strip())
                matches = 0
                for action, value in entries:
                    matched = query in value.key
                    action.setVisible(matched or value.key == key)
                    matches += bool(matched)
                no_match.setVisible(matches == 0)
            search.textChanged.connect(narrow)
        return menu

    def _show_title_prefix_menu(self):
        self._show_title_menu("prefix")

    def _show_title_menu(self, kind):
        button = getattr(self, f"title_{kind}_button")
        try:
            if not getattr(self, f"_title_{kind}_counts") and getattr(self, f"title_{kind}_filter") is None:
                self._show_title_filter_help(kind)
            else:
                self._build_title_menu(kind).exec(button.mapToGlobal(button.rect().bottomLeft()))
        finally:
            self._update_title_button(kind)

    def _show_title_filter_help(self, kind):
        old = getattr(self, "title_filter_help", None)
        if old is not None:
            old.close()
            old.deleteLater()
        popup = TitleFilterHelp(self, Qt.WindowType.Popup)
        self.title_filter_help = popup
        popup.setObjectName("memoTitleFilterHelp")
        popup.setFixedWidth(round(240 * self._filter_scale()))
        layout = QVBoxLayout(popup)
        margin = round(12 * self._filter_scale())
        layout.setContentsMargins(margin, margin, margin, margin)
        other = self.title_prefix_filter if kind == "symbol" else self.title_symbol_filter
        constrained = self.category_filter_id is not None or bool(self.search.text().strip()) or other is not None
        label = "기호" if kind == "symbol" else "머리말"
        if constrained:
            title = f"지금 조건에는 {label}가 붙은 메모가 없어요"
            body = "카테고리·검색·다른 제목 필터를 풀면 다른 값이 보일 수 있어요."
            example = None
        elif kind == "symbol":
            title, body = "기호로 모아 보기", "메모 제목 맨 앞에 이모지나 기호를 붙이면 같은 기호끼리 모아 볼 수 있어요."
            example = "✨테스트 메모\n✨개발용 → ✨ 2"
        else:
            title, body = "머리말로 모아 보기", "제목 맨 앞에 [토마]처럼 대괄호 머리말을 붙이면 같은 머리말끼리 모아 볼 수 있어요."
            example = "[토마] 밥주기\n[토마] 장난감사기 → [토마] 2"
        for text in (title, body):
            widget = QLabel(text)
            widget.setWordWrap(True)
            layout.addWidget(widget)
        if example:
            widget = QLabel(example)
            widget.setObjectName("memoTitleFilterHelpExample")
            widget.setWordWrap(True)
            layout.addWidget(widget)
        close = QPushButton("확인")
        close.clicked.connect(popup.close)
        layout.addWidget(close)
        popup.adjustSize()
        button = getattr(self, f"title_{kind}_button")
        point = button.mapToGlobal(button.rect().bottomLeft())
        screen = button.screen().availableGeometry()
        if point.x() + popup.width() > screen.right() + 1:
            point.setX(button.mapToGlobal(button.rect().bottomRight()).x() - popup.width() + 1)
        point.setX(max(screen.left(), min(point.x(), screen.right() - popup.width() + 1)))
        point.setY(max(screen.top(), min(point.y(), screen.bottom() - popup.height() + 1)))
        popup.move(point)
        popup.show()
        close.setFocus()

    def reset_all_filters(self):
        if not self._has_any_filter():
            return
        if self.store is not None:
            self.store.set_setting(self.FILTER_SETTING, "")
        self.category_filter_id = None
        self.title_symbol_filter = self.title_prefix_filter = None
        blocked = self.search.blockSignals(True)
        try:
            self.search.clear()
        finally:
            self.search.blockSignals(blocked)
        for button in self.category_filter_buttons:
            button.setChecked(button.property("category_id") is None)
        self._update_title_symbol_button()
        self._update_title_prefix_button()
        self._layout_category_filters()
        self.filters_changed.emit()

    def _has_any_filter(self):
        return (self.category_filter_id is not None or bool(self.search.text().strip())
                or self.title_symbol_filter is not None or self.title_prefix_filter is not None)
