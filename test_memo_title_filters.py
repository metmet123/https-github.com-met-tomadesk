"""Stage G-A: title symbol and bracketed-prefix rules, without UI changes."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from PyQt6.QtWidgets import QApplication, QMenu

from alert_notes.memo_list import GROUP_ROLE, MemoListPanel
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.title_symbols import (
    TitleValueCount,
    count_title_values,
    leading_title_prefix,
    leading_title_symbol,
    title_prefix_key,
    title_symbol_key,
)
from qt_test_support import close_alert_panel, destroy_widget
from ui_theme import scaled_stylesheet


EXAMPLE_TITLES = [
    "[TD]메모기능 개선 계획", "[TD]캘린더 축 개선", "[TD]서식 프리셋",
    "개발 명령어 정리", "개발 환경 설정", "오늘 할 일", "오늘 장보기",
    "회의록 9월", "회의록 10월", "새 기능 아이디어", "새 폴더 정리",
    "[토마] 밥주기", "[토마] 장난감사기", "[모리] 새장청소", "[모리] 밥주기",
    "선풍기 사기", "2026 목표", "2026 여행", "업무 정리", "업무 인수인계",
]

_APP: QApplication | None = None


def _application() -> QApplication:
    # Keep the wrapper alive when the next pytest module creates Qt windows.
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.mark.parametrize("title, display, key", [
    ("  ✨테스트", "✨", "✨"),
    ("✨️개발용", "✨️", "✨"),
    ("❤️ 마음", "❤️", "❤"),
    ("❤ 마음", "❤", "❤"),
    ("👍🏻 좋아요", "👍🏻", "👍"),
    ("👩🏽\u200d💻 개발", "👩🏽\u200d💻", "👩\u200d💻"),
    ("🇰🇷 출장", "🇰🇷", "🇰🇷"),
    ("★중요", "★", "★"),
    ("〒 우편", "〒", "〒"),
    ("©️ 저작권", "©️", "©"),
    ("✨⚡토마", "✨", "✨"),
])
def test_leading_symbol_rule(title, display, key):
    symbol = leading_title_symbol(title)
    assert symbol == display
    assert title_symbol_key(symbol) == key


@pytest.mark.parametrize("title", [
    "+ 할 일", "$ 가계부", "^^ 웃음", "→ 다음", "※ 참고",
    "- 일반", "# 제목", "1️⃣ 첫째", "[TD]메모", "업무일반",
])
def test_non_so_leading_character_is_not_symbol(title):
    assert leading_title_symbol(title) is None


@pytest.mark.parametrize("title, expected", [
    ("[토마] 밥주기", "토마"),
    ("✨[토마] 밥주기", "토마"),
    ("✨⚡ [업무] 보고", "업무"),
    ("👩🏽\u200d💻 [개발] 구현", "개발"),
    ("[ 토마 ]장난감", "토마"),
    ("[td] 정리", "td"),
    ("[TD]메모기능", "TD"),
    ("[토마][병원] 예약", "토마"),
    ("밥주기 [토마]", None),
    ("[토마 밥주기", None),
    ("[] 빈칸", None),
    ("[   ] 빈칸", None),
    ("[가나다라마바사아자차카타파하가나다라마바사] x", None),
    ("※ [토마]", None),
    ("→ [토마]", None),
])
def test_leading_bracketed_prefix_rule(title, expected):
    assert leading_title_prefix(title) == expected


def test_prefix_key_normalizes_and_folds_case():
    assert title_prefix_key("TD") == title_prefix_key("td") == "td"
    assert title_prefix_key("e\u0301") == title_prefix_key("é") == "é"


def test_prefix_length_and_bracket_boundaries():
    assert leading_title_prefix("[" + "가" * 20 + "] 제목") == "가" * 20
    assert leading_title_prefix("[" + "가" * 21 + "] 제목") is None
    assert leading_title_prefix("[중[첩] 제목") is None
    assert leading_title_prefix("[두\n줄] 제목") is None


def test_fixed_twenty_titles_have_only_intentional_prefixes():
    assert len(EXAMPLE_TITLES) == 20
    rows = [
        {"title": title, "updated_at": f"2026-09-16 10:{index:02d}:00"}
        for index, title in enumerate(EXAMPLE_TITLES)
    ]
    counts = count_title_values(rows, leading_title_prefix, title_prefix_key)
    assert {value.key: value.count for value in counts} == {
        "td": 3, "토마": 2, "모리": 2,
    }
    assert {value.display for value in counts} == {"TD", "토마", "모리"}


def test_count_groups_symbol_variants_and_uses_newest_display():
    rows = [
        {"title": "✨️오래됨", "updated_at": "2026-09-14 09:00:00"},
        {"title": "✨새로움", "updated_at": "2026-09-16 09:00:00"},
        {"title": "👍🏻 좋아요", "updated_at": "2026-09-15 09:00:00"},
        {"title": "👍 좋아요", "updated_at": "2026-09-13 09:00:00"},
        {"title": "⚡하나", "updated_at": "2026-09-16 10:00:00"},
    ]
    assert count_title_values(rows, leading_title_symbol, title_symbol_key) == [
        TitleValueCount("✨", "✨", 2, "2026-09-16 09:00:00"),
        TitleValueCount("👍", "👍🏻", 2, "2026-09-15 09:00:00"),
        TitleValueCount("⚡", "⚡", 1, "2026-09-16 10:00:00"),
    ]


def test_count_sorts_equal_count_and_date_by_key_and_keeps_first_spelling():
    rows = [
        {"title": "[td] 먼저", "updated_at": "2026-09-16 09:00:00"},
        {"title": "[TD] 같은 시각", "updated_at": "2026-09-16 09:00:00"},
        {"title": "[z] 하나", "updated_at": "2026-09-15 09:00:00"},
        {"title": "[a] 하나", "updated_at": "2026-09-15 09:00:00"},
    ]
    assert count_title_values(rows, leading_title_prefix, title_prefix_key) == [
        TitleValueCount("td", "td", 2, "2026-09-16 09:00:00"),
        TitleValueCount("a", "a", 1, "2026-09-15 09:00:00"),
        TitleValueCount("z", "z", 1, "2026-09-15 09:00:00"),
    ]


def test_prefix_count_uses_newest_original_case_from_sqlite_rows():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE notes(title TEXT, updated_at TEXT)")
        connection.executemany("INSERT INTO notes VALUES (?, ?)", [
            ("[td] 예전", "2026-09-14 09:00:00"),
            ("[TD] 최신", "2026-09-16 09:00:00"),
        ])
        rows = connection.execute("SELECT title, updated_at FROM notes").fetchall()
    assert count_title_values(rows, leading_title_prefix, title_prefix_key) == [
        TitleValueCount("td", "TD", 2, "2026-09-16 09:00:00"),
    ]


@pytest.fixture(params=(1.0, 1.25, 1.5), ids=("100%", "125%", "150%"))
def memo_list(tmp_path, request):
    app = _application()
    previous_style = app.styleSheet()
    app.setStyleSheet(scaled_stylesheet(request.param))
    store = NoteReminderStore(tmp_path / "title_filters.db", "새 메모")
    work, dev = (int(row["id"]) for row in store.categories()[:2])
    titles = {
        "parent": "✨[토마] 부모",
        "variant": "✨️[토마] 특별",
        "bolt": "⚡[토마] 전기",
        "other_prefix": "✨[업무] 보고",
        "no_symbol": "[토마] 글자",
        "dev": "✨[토마] 자료",
    }
    ids = {key: store.create_note(title) for key, title in titles.items()}
    for key in ("parent", "variant", "bolt", "other_prefix", "no_symbol"):
        store.set_note_category(ids[key], work)
    store.set_note_category(ids["dev"], dev)
    listing = MemoListPanel(store)
    listing.resize(480, 700)
    listing.show()
    listing.set_rows(store.notes())
    app.processEvents()
    try:
        yield listing, store, ids, work, dev, app
    finally:
        destroy_widget(listing, app)
        store.close()
        app.setStyleSheet(previous_style)


def _counts(values):
    return {value.key: value.count for value in values}


def test_symbol_prefix_category_and_search_are_combined(memo_list):
    listing, store, ids, work, _dev, app = memo_list
    listing._set_category_filter(work)
    listing._set_title_symbol_filter("✨️")
    listing._set_title_prefix_filter("토마")
    listing.set_rows(store.notes())
    assert listing.title_symbol_filter == "✨"
    assert listing.row_count() == 2
    assert {item.text(1) for item in listing._note_items()} == {
        "✨[토마] 부모", "✨️[토마] 특별",
    }
    listing.search.setText("특별")
    listing.set_rows(store.notes(listing.search.text()))
    app.processEvents()
    assert listing.row_count() == 1
    assert next(listing._note_items()).text(1) == "✨️[토마] 특별"
    assert listing.category_filter_id == work
    assert ids["variant"] in listing.rows_by_id


def test_counts_exclude_own_filter_and_include_other_filter(memo_list):
    listing, store, _ids, work, _dev, _app = memo_list
    listing._set_category_filter(work)
    listing._set_title_symbol_filter("✨")
    listing._set_title_prefix_filter("토마")
    listing.set_rows(store.notes())
    assert _counts(listing._title_symbol_counts) == {"✨": 2, "⚡": 1}
    assert _counts(listing._title_prefix_counts) == {"토마": 2, "업무": 1}
    assert listing.row_count() == 2


def test_active_symbol_key_survives_zero_count_and_is_not_saved(memo_list, monkeypatch):
    listing, store, ids, _work, dev, app = memo_list
    listing._set_category_filter(dev)
    listing._set_title_symbol_filter("✨️")
    store.update_note(ids["dev"], title="[토마] 자료")
    listing.set_rows(store.notes())
    app.processEvents()
    assert listing.title_symbol_filter == "✨"
    assert listing._title_symbol_counts == []
    assert listing.row_count() == 0
    assert listing.title_symbol_button.text() == "✨ ▾"
    monkeypatch.setattr(QMenu, "exec", lambda self, *_args: None)
    listing._show_title_symbol_menu()
    active = next(action for action in listing.title_symbol_menu.actions() if "✨" in action.text())
    assert active.isChecked() and "0" in active.text()
    assert store.setting("memo_title_symbol_filter", "missing") == "missing"
    assert store.setting("memo_title_prefix_filter", "missing") == "missing"


def test_flat_result_disables_drag_and_fold_then_restores_tree(memo_list):
    listing, store, ids, _work, _dev, app = memo_list
    child_id = store.create_child_note(ids["parent"], "✨[토마] 자식")
    listing.set_rows(store.notes())
    assert listing._item_for(child_id).parent() is listing._item_for(ids["parent"])
    assert listing.fold_button.isEnabled()
    listing._set_title_prefix_filter("토마")
    listing.set_rows(store.notes())
    app.processEvents()
    assert listing._item_for(child_id).parent() is None
    assert not listing.table.dragEnabled()
    assert not listing.fold_button.isEnabled()
    assert "원래 위치:" in listing._item_for(child_id).toolTip(1)
    listing.clear_title_filters()
    listing.set_rows(store.notes())
    assert listing._item_for(child_id).parent() is listing._item_for(ids["parent"])
    assert listing.table.dragEnabled()
    assert listing.fold_button.isEnabled()


def test_title_filter_temporarily_overrides_category_view(memo_list):
    listing, store, _ids, _work, _dev, _app = memo_list
    listing.view_combo.setCurrentIndex(listing.view_combo.findData("category"))
    listing.set_rows(store.notes())
    assert listing.table.topLevelItem(0).data(0, GROUP_ROLE) is True
    listing._set_title_prefix_filter("토마")
    listing.set_rows(store.notes())
    assert all(item.data(0, GROUP_ROLE) is not True for item in (
        listing.table.topLevelItem(index)
        for index in range(listing.table.topLevelItemCount())
    ))
    assert not listing.table.dragEnabled()
    assert not listing.fold_button.isEnabled()
    listing.clear_title_filters()
    listing.set_rows(store.notes())
    assert listing.table.topLevelItem(0).data(0, GROUP_ROLE) is True


def test_filtered_empty_state_and_clear_keep_category_and_search(memo_list):
    listing, store, _ids, work, _dev, app = memo_list
    listing._set_category_filter(work)
    listing.search.setText("특별")
    listing._set_title_symbol_filter("⚡")
    listing._set_title_prefix_filter("업무")
    listing.set_rows(store.notes(listing.search.text()))
    app.processEvents()
    assert listing.row_count() == 0
    assert listing.filtered_empty_host.isVisible()
    assert not listing.empty_label.isVisible()
    assert listing.filtered_empty_message.text() == "조건에 맞는 메모가 없습니다."
    for term in ("업무", "검색: 특별", "⚡", "[업무]"):
        assert term in listing.filtered_empty_summary.text()
    assert listing.clear_title_filters_button.isVisible()
    emissions = []
    listing.filters_changed.connect(lambda: emissions.append(True))
    listing.clear_title_filters_button.click()
    assert len(emissions) == 1
    listing.set_rows(store.notes(listing.search.text()))
    assert listing.title_symbol_filter is None
    assert listing.title_prefix_filter is None
    assert listing.category_filter_id == work
    assert listing.search.text() == "특별"
    assert listing.row_count() == 1


def test_empty_state_without_title_filter_or_any_filter(memo_list):
    listing, store, _ids, work, _dev, app = memo_list
    listing._set_category_filter(work)
    listing.search.setText("없는 검색어")
    listing.set_rows(store.notes(listing.search.text()))
    app.processEvents()
    assert listing.filtered_empty_host.isVisible()
    assert not listing.clear_title_filters_button.isVisible()
    listing._set_category_filter(None)
    listing.search.clear()
    listing.set_rows([])
    app.processEvents()
    assert listing.empty_label.isVisible()
    assert not listing.filtered_empty_host.isVisible()


def test_title_filters_reset_on_new_panel_but_category_remains(memo_list):
    listing, store, _ids, work, _dev, app = memo_list
    listing._set_category_filter(work)
    listing._set_title_symbol_filter("✨")
    listing._set_title_prefix_filter("토마")
    reopened = MemoListPanel(store)
    try:
        assert reopened.title_symbol_filter is None
        assert reopened.title_prefix_filter is None
        assert reopened.category_filter_id == work
    finally:
        destroy_widget(reopened, app)


def test_main_panel_refresh_applies_both_title_filters_and_search(tmp_path):
    app = _application()
    store = NoteReminderStore(tmp_path / "panel_title_filters.db", "새 메모")
    store.create_note("✨[토마] 특별", "본문")
    store.create_note("⚡[토마] 전기", "본문")
    store.create_note("✨[업무] 특별", "본문")
    panel = AlertNotesPanel(store)
    panel.resize(1080, 700)
    panel.show()
    try:
        listing = panel.list_panel
        listing._set_title_symbol_filter("✨")
        listing._set_title_prefix_filter("토마")
        assert listing.row_count() == 1
        listing.search.setText("특별")
        assert listing.row_count() == 1
        listing.search.setText("없는 검색어")
        assert listing.row_count() == 0
        assert listing.filtered_empty_host.isVisible()
    finally:
        close_alert_panel(panel, app)
        store.close()
