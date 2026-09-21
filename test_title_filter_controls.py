import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest.mock import patch
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QMenu, QPushButton, QWidgetAction
from alert_notes.memo_list import MemoListPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget
from ui_theme import scaled_stylesheet

APP = QApplication.instance() or QApplication([])


@pytest.fixture(params=[1.0, 1.25, 1.5])
def listing(tmp_path, request):
    previous_style, previous_font = APP.styleSheet(), APP.font()
    font_id = QFontDatabase.addApplicationFont(os.path.join(os.environ["WINDIR"], "Fonts", "malgun.ttf"))
    APP.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    APP.setStyleSheet(scaled_stylesheet(request.param))
    store = NoteReminderStore(tmp_path / "notes.db")
    panel = MemoListPanel(store)
    panel.apply_title_filter_scale(request.param)
    panel.resize(round(420 * request.param), 600)
    panel.filters_changed.connect(lambda: panel.set_rows(store.notes(panel.search.text())))
    panel.search.textChanged.connect(lambda: panel.set_rows(store.notes(panel.search.text())))
    panel.set_rows(store.notes())
    panel.show()
    APP.processEvents()
    yield panel, store, request.param
    destroy_widget(panel, APP)
    store.close()
    APP.setStyleSheet(previous_style)
    APP.setFont(previous_font)
    QFontDatabase.removeApplicationFont(font_id)


def refresh(panel, store):
    panel.set_rows(store.notes(panel.search.text()))
    APP.processEvents()


@pytest.mark.parametrize("prefix", ["R&D", "A&&B", "&A", "A&"])
def test_literal_ampersand_prefix_has_no_accelerator(listing, prefix):
    panel, store, scale = listing
    note = store.create_note(f"[{prefix}] 연구 메모")
    panel.resize(round(800 * scale), 600)
    refresh(panel, store)
    button = panel.title_prefix_button
    assert button.text() == f"[{prefix.replace('&', '&&')}] 1 ▾"
    assert button.shortcut().isEmpty()
    assert f"[{prefix}]" in button.toolTip()
    menu = panel._build_title_prefix_menu()
    action = next(a for a in menu.actions() if a.data() == prefix.casefold())
    assert action.text() == f"[{prefix.replace('&', '&&')}]  1"
    action.trigger()
    assert button.text() == f"[{prefix.replace('&', '&&')}] ▾"
    assert button.shortcut().isEmpty() and panel.row_count() == 1
    store.update_note(note, title="다른 제목")
    refresh(panel, store)
    assert button.shortcut().isEmpty()
    assert "0개" in button.toolTip()
    panel.reset_all_filters()
    assert button.text() == "머리말" and button.shortcut().isEmpty()


def test_long_ampersand_prefix_width_uses_literal_text(listing):
    panel, store, scale = listing
    store.create_note("[R&D연구개발팀의아주긴머리말] 메모")
    panel.resize(round(300 * scale), 600)
    refresh(panel, store)
    button = panel.title_prefix_button
    literal = button.text().replace("&&", "&")
    assert button.shortcut().isEmpty()
    assert "…" in literal
    assert button.fontMetrics().horizontalAdvance(literal) <= round(96 * scale)
    assert button.width() <= round(120 * scale)
    assert panel.search.width() >= round(120 * scale)


def test_empty_buttons_help_and_check_state(listing):
    panel, _store, scale = listing
    assert panel.title_symbol_button.text() == "기호"
    assert panel.title_prefix_button.text() == "머리말"
    for button in (panel.title_symbol_button, panel.title_prefix_button):
        assert button.property("empty") is True and not button.isChecked()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        APP.processEvents()
        popup = panel.title_filter_help
        assert popup.isVisible() and popup.width() == round(240 * scale)
        assert popup.findChild(QLabel, "memoTitleFilterHelpExample") is not None
        assert not button.isChecked()
        QTest.keyClick(popup, Qt.Key.Key_Escape)
        assert not popup.isVisible()


def test_constrained_help_no_example_and_confirm_closes(listing):
    panel, _store, _scale = listing
    panel.search.setText("없는검색")
    panel._show_title_prefix_menu()
    popup = panel.title_filter_help
    assert any("지금 조건" in label.text() for label in popup.findChildren(QLabel))
    assert popup.findChild(QLabel, "memoTitleFilterHelpExample") is None
    popup.findChild(QPushButton).click()
    assert not popup.isVisible()


def test_representative_recency_active_and_zero_count(listing):
    panel, store, _scale = listing
    older = store.create_note("⚡[A] old")
    newer = store.create_note("✨[Z] new")
    store.conn.execute("UPDATE notes SET updated_at='202609010000' WHERE id=?", (older,))
    store.conn.execute("UPDATE notes SET updated_at='202609020000' WHERE id=?", (newer,))
    store.conn.commit()
    refresh(panel, store)
    assert panel.title_symbol_button.text() == "✨ 1 ▾"
    assert panel.title_prefix_button.text() == "[Z] 1 ▾"
    panel._set_title_prefix_filter("z")
    assert panel.title_prefix_button.text() == "[Z] ▾"
    assert panel.title_prefix_button.isChecked() and not panel.title_prefix_button.property("empty")
    store.update_note(newer, title="제목 변경")
    refresh(panel, store)
    assert panel.title_prefix_button.text() == "[z] ▾"
    actions = panel._build_title_prefix_menu().actions()
    active = next(a for a in actions if a.data() == "z")
    assert active.isChecked() and active.text().endswith("  0")


def test_menus_search_keeps_all_and_active_and_empty_hint(listing):
    panel, store, _scale = listing
    for index in range(11):
        store.create_note(f"[tag{index}] 메모")
    refresh(panel, store)
    panel._set_title_prefix_filter("tag0")
    menu = panel._build_title_prefix_menu()
    assert isinstance(menu.actions()[0], QWidgetAction)
    search = menu.actions()[0].defaultWidget()
    search.setText("no matches")
    assert next(a for a in menu.actions() if a.text() == "전체").isVisible()
    assert next(a for a in menu.actions() if a.data() == "tag0").isVisible()
    assert not next(a for a in menu.actions() if a.data() == "tag1").isVisible()
    hint = next(a for a in menu.actions() if a.text() == "맞는 머리말이 없습니다")
    assert hint.isVisible() and not hint.isEnabled()
    search.clear()
    assert not hint.isVisible()
    next(a for a in menu.actions() if a.data() == "tag1").trigger()
    assert panel.title_prefix_filter == "tag1"


def test_reset_all_four_once_preserves_sort_view_pins_and_notes(listing):
    panel, store, _scale = listing
    note = store.create_note("✨[토마] needle")
    category = int(store.categories()[0]["id"])
    store.set_note_category(note, category)
    store.set_setting("memo_category_pinned", '[1,"none"]')
    panel.view_combo.setCurrentIndex(1)
    panel.sort_combo.setCurrentIndex(2)
    panel._set_category_filter(category)
    panel._set_title_symbol_filter("✨")
    panel._set_title_prefix_filter("토마")
    panel.search.setText("needle")
    snapshot = dict(store.note(note))
    spy = QSignalSpy(panel.filters_changed)
    search_spy = QSignalSpy(panel.search.textChanged)
    panel.reset_all_filters()
    assert len(spy) == 1 and len(search_spy) == 0
    assert panel.category_filter_id is panel.title_symbol_filter is panel.title_prefix_filter is None
    assert not panel.search.text()
    assert panel.view_combo.currentIndex() == 1 and panel.sort_combo.currentIndex() == 2
    assert store.setting("memo_category_pinned") == '[1,"none"]'
    assert store.setting(panel.FILTER_SETTING) == ""
    assert dict(store.note(note)) == snapshot
    assert panel.reset_filters_button.isHidden()
    panel.reset_all_filters()
    assert len(spy) == 1


def test_reset_layout_and_scaled_search_minimum(listing):
    panel, store, scale = listing
    store.create_note("✨[매우아주긴머리말이름입니다] needle")
    panel.search.setText("needle")
    panel.resize(round(300 * scale), 600)
    APP.processEvents()
    refresh(panel, store)
    assert panel.search.width() >= round(120 * scale)
    assert panel.reset_filters_button.text() == "↺"
    assert panel.reset_filters_button.width() == round(28 * scale)
    assert panel.reset_filters_button.geometry().right() < panel.more_categories_button.geometry().left()
    assert panel.title_prefix_button.width() > 0
    assert panel.title_prefix_button.geometry().right() <= panel.title_prefix_button.parentWidget().width()
    assert panel.title_prefix_button.fontMetrics().horizontalAdvance(panel.title_prefix_button.text()) <= round(96 * scale)
    assert "…" in panel.title_prefix_button.text()
    panel.resize(round(480 * scale), 600)
    APP.processEvents()
    assert panel.title_prefix_button.geometry().right() <= panel.title_prefix_button.parentWidget().width()
    panel.resize(round(800 * scale), 600)
    APP.processEvents()
    assert panel.reset_filters_button.text() == "↺ 필터 초기화"
    assert panel.title_prefix_button.width() <= round(120 * scale)


def test_filter_reset_preserves_real_manual_editor_draft():
    from test_settings_dday_ux import SettingsWindowTest
    case = SettingsWindowTest()
    case.setUpClass()
    case.setUp()
    try:
        panel = case.window.alert_panel
        note_id = case.window.note_store.create_note("✨[토마] 기존", "저장된 본문")
        panel.show_note(note_id)
        panel.set_auto_save_enabled(False)
        panel.editor.content_edit.setPlainText("미저장 본문 유지")
        before = dict(case.window.note_store.note(note_id))
        panel.list_panel._set_title_prefix_filter("토마")
        panel.list_panel.reset_all_filters()
        APP.processEvents()
        assert panel.current_id == note_id
        assert panel.editor.content_edit.toPlainText() == "미저장 본문 유지"
        assert dict(case.window.note_store.note(note_id)) == before
    finally:
        case.tearDown()


def test_menu_cancel_restores_checked_state_without_filter_changes(listing):
    panel, store, _scale = listing
    store.create_note("✨[토마] 메모")
    refresh(panel, store)
    spy = QSignalSpy(panel.filters_changed)
    with patch.object(QMenu, "exec", return_value=None):
        panel.title_prefix_button.click()
        panel.title_symbol_button.click()
    assert not panel.title_prefix_button.isChecked() and not panel.title_symbol_button.isChecked()
    assert len(spy) == 0
