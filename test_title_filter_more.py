from unittest.mock import patch
import pytest
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QMenu
from alert_notes.memo_list import MemoListPanel
from qt_test_support import destroy_widget
from test_title_filter_controls import APP, listing


def submenus(menu):
    return {action.text(): action.menu() for action in menu.actions() if action.menu()}


@pytest.mark.parametrize("width", [300, 420, 800])
def test_more_always_rightmost_and_combos_never_in_search(listing, width):
    panel, _store, scale = listing
    panel.resize(round(width * scale), 600)
    APP.processEvents()
    assert panel.more_categories_button.isVisible()
    assert abs(panel.more_categories_button.geometry().right() - (panel.filter_host.width() - 1)) <= 1
    for combo in (panel.view_combo, panel.sort_combo):
        assert combo.isHidden() and combo.parentWidget() is panel
        assert panel.search.parentWidget().layout().indexOf(combo) == -1
    assert panel.search.width() >= round(120 * scale)
    menu = panel._build_more_categories_menu()
    assert list(submenus(menu)) == ["보기", "정렬"]
    assert len(submenus(menu)["보기"].actions()) == 2
    assert len(submenus(menu)["정렬"].actions()) == 5
    assert menu.actions()[-2].isSeparator()
    assert menu.actions()[-1].text() == "⚙ 카테고리 설정…"


def test_menu_actions_save_restore_sort_and_blue_dot(listing):
    panel, store, _scale = listing
    store.create_note("z-last")
    store.create_note("a-first")
    changed = QSignalSpy(panel.filters_changed)
    menu = panel._build_more_categories_menu()
    submenus(menu)["정렬"].actions()[3].trigger()
    assert len(changed) == 1
    assert store.setting(panel.SORT_SETTING) == "title_asc"
    assert [item.text(1) for item in panel._note_items()] == ["a-first", "z-last"]
    assert not panel.more_categories_button.icon().isNull()
    assert not panel.more_categories_button.isChecked()
    assert panel.more_categories_button.toolTip() == "보기·정렬이 기본값이 아닙니다"
    menu = panel._build_more_categories_menu()
    assert submenus(menu)["정렬"].actions()[3].isChecked()
    submenus(menu)["보기"].actions()[1].trigger()
    assert store.setting(panel.VIEW_SETTING) == "category"
    restored = MemoListPanel(store)
    try:
        assert restored.sort_combo.currentData() == "title_asc"
        assert restored.view_combo.currentData() == "category"
        assert restored.view_combo.isHidden() and restored.sort_combo.isHidden()
    finally:
        destroy_widget(restored, APP)
    panel.reset_all_filters()
    assert panel.sort_combo.currentData() == "title_asc"
    panel.view_combo.setCurrentIndex(0)
    panel.sort_combo.setCurrentIndex(0)
    assert panel.more_categories_button.icon().isNull()
    assert "기본값이 아닙니다" not in panel.more_categories_button.toolTip()


def test_hidden_category_header_selection_priority_and_settings_signal(listing):
    panel, store, scale = listing
    for i in range(8):
        store.create_category(f"추가 카테고리 {i}", "#ef4444")
    panel.refresh_category_filters()
    panel.resize(round(300 * scale), 600)
    APP.processEvents()
    menu = panel._build_more_categories_menu()
    assert menu.actions()[0].text() == "카테고리" and not menu.actions()[0].isEnabled()
    hidden = [b for b in panel.category_filter_buttons if b.isHidden()]
    selected = hidden[-2]
    key = selected.property("category_id")
    next(a for a in menu.actions() if a.data() == key).trigger()
    panel.sort_combo.setCurrentIndex(1)
    APP.processEvents()
    assert panel.category_filter_id == key
    assert panel.more_categories_button.isChecked()
    assert panel.more_categories_button.text() == selected.text()
    assert panel.more_categories_button.toolTip() == selected.text()
    assert panel.more_categories_button.icon().cacheKey() == selected.icon().cacheKey()
    spy = QSignalSpy(panel.category_settings_requested)
    menu = panel._build_more_categories_menu()
    menu.actions()[-1].trigger()
    assert len(spy) == 1
    panel._set_category_filter(None)
    assert panel.more_categories_button.text() == "더보기"
    assert not panel.more_categories_button.isChecked()


def test_no_empty_category_header_and_cancel_restores_button(listing):
    panel, _store, _scale = listing
    panel.resize(1800, 600)
    APP.processEvents()
    menu = panel._build_more_categories_menu()
    assert menu.actions()[0].text() == "보기"
    assert not menu.actions()[0].isSeparator()
    spy = QSignalSpy(panel.filters_changed)
    with patch.object(QMenu, "exec", return_value=None):
        panel.more_categories_button.click()
    assert not panel.more_categories_button.isChecked()
    assert not spy


def test_category_settings_entry_uses_existing_editor_action():
    from test_settings_dday_ux import SettingsWindowTest
    from alert_notes.editor import MemoEditor
    calls = []
    case = SettingsWindowTest()
    case.setUpClass()
    with patch.object(MemoEditor, "_manage_categories", lambda editor: calls.append(editor)):
        case.setUp()
    try:
        panel = case.window.alert_panel
        panel.list_panel._build_more_categories_menu().actions()[-1].trigger()
        assert calls == [panel.editor]
    finally:
        case.tearDown()
