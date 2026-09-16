"""메모 층 나누기 5단계 — / 삽입 메뉴, 강조 상자·구분선, 고정, 전부 접기."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent, QKeySequence
from PyQt6.QtWidgets import QApplication

from alert_notes.insert_menu import (
    INSERT_ITEMS, PENDING_SUFFIX, build_insert_menu, item_tooltip,
    matching_items,
)
from alert_notes.memo_list import MemoListPanel
from alert_notes.panel import AlertNotesPanel
from alert_notes.rich_memo_edit import (
    CALLOUT_BACKGROUND, CALLOUT_PREFIX, DIVIDER_TEXT, TOGGLE_CLOSED_PREFIX,
    TOGGLE_OPEN_PREFIX,
    RichMemoTextEdit,
)
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel, destroy_widget


def press(widget, key, text=""):
    widget.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
    )


def block_texts(editor):
    texts = []
    block = editor.document().begin()
    while block.isValid():
        texts.append(block.text())
        block = block.next()
    return texts


class SlashMenuTest(unittest.TestCase):
    """본문에서 `/` 를 치면 뜨는 삽입 메뉴."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("드라마", "")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.resize(600, 400)
        self.editor.show()
        self.editor.set_note_context(self.note_id)

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def _type(self, text):
        self.editor.textCursor().insertText(text)
        self.editor._refresh_insert_popup()

    def test_a_slash_opens_the_menu(self):
        self._type("/")
        self.assertTrue(self.editor.insert_popup_visible())
        labels = self.editor.insert_popup_items()
        self.assertTrue(any("토글" in label for label in labels), labels)
        self.assertTrue(any("강조 상자" in label for label in labels), labels)
        self.assertTrue(any("구분선" in label for label in labels), labels)

    def test_typing_narrows_the_menu(self):
        self._type("/강조")
        self.assertEqual(len(self.editor.insert_popup_items()), 1)
        self.assertIn("강조 상자", self.editor.insert_popup_items()[0])

    def test_a_word_that_matches_nothing_closes_it(self):
        self._type("/없는것")
        self.assertFalse(self.editor.insert_popup_visible())

    def test_a_slash_inside_a_word_is_left_alone(self):
        self._type("주소는 https://example.com")
        self.assertFalse(self.editor.insert_popup_visible(), "주소에서 메뉴가 떴습니다")

    def test_escape_closes_it_and_keeps_the_slash(self):
        self._type("/토")
        press(self.editor, Qt.Key.Key_Escape)
        self.assertFalse(self.editor.insert_popup_visible())
        self.assertEqual(block_texts(self.editor), ["/토"])

    def test_enter_inserts_the_chosen_one_and_clears_the_slash(self):
        self._type("/강조")
        press(self.editor, Qt.Key.Key_Return)
        self.assertFalse(self.editor.insert_popup_visible())
        self.assertEqual(block_texts(self.editor)[0], CALLOUT_PREFIX)

    def _press_on_popup(self, key):
        """실제 앱처럼 뜬 메뉴 쪽으로 키를 보낸다.

        메뉴는 창 하나라서 키를 먼저 가져간다.  편집기에 직접 보내는 검사만
        있으면 실제로는 Enter 가 먹히지 않는 것을 놓친다.
        """
        QApplication.sendEvent(
            self.editor._insert_popup,
            QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, ""),
        )

    def test_enter_on_the_popup_itself_inserts(self):
        self._type("/강조")
        self._press_on_popup(Qt.Key.Key_Return)
        self.assertFalse(self.editor.insert_popup_visible())
        self.assertEqual(block_texts(self.editor)[0], CALLOUT_PREFIX)

    def test_arrows_on_the_popup_walk_the_list(self):
        self._type("/")
        first = self.editor._insert_popup.currentRow()
        self._press_on_popup(Qt.Key.Key_Down)
        self.assertNotEqual(self.editor._insert_popup.currentRow(), first)

    def test_choosing_with_the_arrows_then_enter_inserts_that_one(self):
        self._type("/")
        labels = self.editor.insert_popup_items()
        wanted = labels.index(next(l for l in labels if "구분선" in l))
        for _ in range(wanted):
            self._press_on_popup(Qt.Key.Key_Down)
        self._press_on_popup(Qt.Key.Key_Return)
        self.assertIn(DIVIDER_TEXT, block_texts(self.editor), block_texts(self.editor))

    def test_escape_on_the_popup_closes_it(self):
        self._type("/토")
        self._press_on_popup(Qt.Key.Key_Escape)
        self.assertFalse(self.editor.insert_popup_visible())
        self.assertEqual(block_texts(self.editor), ["/토"])

    def test_typing_reaches_the_editor_through_the_popup(self):
        self._type("/")
        QApplication.sendEvent(
            self.editor._insert_popup,
            QKeyEvent(
                QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "강",
            ),
        )
        self.assertEqual(block_texts(self.editor), ["/강"])

    def test_the_arrow_keys_walk_the_list(self):
        self._type("/")
        first = self.editor._insert_popup.currentRow()
        press(self.editor, Qt.Key.Key_Down)
        self.assertNotEqual(self.editor._insert_popup.currentRow(), first)
        press(self.editor, Qt.Key.Key_Up)
        self.assertEqual(self.editor._insert_popup.currentRow(), first)

    def test_the_menu_offers_the_same_things_as_the_button(self):
        self._type("/")
        from_slash = {label.split("   ")[-1] for label in self.editor.insert_popup_items()}
        menu = build_insert_menu(self.editor)
        panel = menu.actions()[0].defaultWidget()
        from_button = {
            panel.feature_list.item(row).text().replace(PENDING_SUFFIX, "").split("   ")[-1]
            for row in range(panel.feature_list.count())
            if panel.feature_list.item(row).flags() & Qt.ItemFlag.ItemIsEnabled
        }
        self.assertEqual(from_slash, from_button)
        menu.deleteLater()

    def test_every_listed_item_can_actually_run(self):
        for item, handler in matching_items(self.editor, ""):
            self.assertTrue(callable(handler), item)


class CalloutAndDividerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = RichMemoTextEdit()
        self.editor.resize(600, 400)
        self.editor.show()

    def tearDown(self):
        destroy_widget(self.editor, self.app)

    def test_a_callout_gets_a_mark_and_a_background(self):
        self.editor.textCursor().insertText("잊지 말 것")
        self.editor.make_callout()
        block = self.editor.document().begin()
        self.assertEqual(block.text(), f"{CALLOUT_PREFIX}잊지 말 것")
        self.assertTrue(self.editor.current_block_is_callout())
        self.assertEqual(
            block.blockFormat().background().color().name(), CALLOUT_BACKGROUND,
        )

    def test_calling_it_again_puts_the_line_back(self):
        self.editor.textCursor().insertText("잊지 말 것")
        self.editor.make_callout()
        self.editor.make_callout()
        self.assertEqual(self.editor.document().begin().text(), "잊지 말 것")
        self.assertFalse(self.editor.current_block_is_callout())

    def test_a_callout_survives_a_round_trip(self):
        self.editor.textCursor().insertText("잊지 말 것")
        self.editor.make_callout()
        saved = self.editor.content()
        reopened = RichMemoTextEdit()
        reopened.show()
        reopened.set_content(saved)
        self.assertTrue(
            reopened.is_callout_block(reopened.document().begin()),
            block_texts(reopened),
        )
        destroy_widget(reopened, self.app)

    def test_the_background_stops_at_the_end_of_the_callout(self):
        self.editor.textCursor().insertText("잊지 말 것")
        self.editor.make_callout()
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("그다음 줄")
        second = self.editor.document().begin().next()
        self.assertEqual(second.text(), "그다음 줄")
        # 빈 QColor 도 isValid 는 참이다.  칠이 있는지로 봐야 한다.
        self.assertEqual(
            second.blockFormat().background().style(), Qt.BrushStyle.NoBrush,
            "강조 상자의 배경이 다음 줄까지 번졌습니다",
        )
        self.assertEqual(second.blockFormat().leftMargin(), 0)

    def test_the_background_does_not_reach_a_divider(self):
        self.editor.textCursor().insertText("잊지 말 것")
        self.editor.make_callout()
        self.editor.insert_divider()
        divider = next(
            block for block in self.editor._iter_blocks()
            if self.editor.is_divider_block(block)
        )
        self.assertEqual(
            divider.blockFormat().background().style(), Qt.BrushStyle.NoBrush,
            "구분선이 강조 상자 배경 위에 그려집니다",
        )

    def test_the_background_does_not_reach_a_page_line(self):
        from pathlib import Path as _Path
        from tempfile import TemporaryDirectory as _Temp

        temp = _Temp()
        store = NoteReminderStore(_Path(temp.name) / "notes.db", "새 메모")
        try:
            note_id = store.create_note("메모", "")
            editor = RichMemoTextEdit(store)
            editor.show()
            editor.set_note_context(note_id)
            editor.textCursor().insertText("잊지 말 것")
            editor.make_callout()
            editor.insert_page_link()
            line = editor.textCursor().block()
            self.assertEqual(
                line.blockFormat().background().style(), Qt.BrushStyle.NoBrush,
                "페이지 줄이 강조 상자 배경 위에 놓입니다",
            )
            destroy_widget(editor, self.app)
        finally:
            store.close()
            temp.cleanup()

    def test_a_divider_is_one_line_you_can_keep_writing_after(self):
        self.editor.textCursor().insertText("앞 이야기")
        self.editor.insert_divider()
        self.editor.textCursor().insertText("뒷 이야기")
        texts = block_texts(self.editor)
        self.assertEqual(texts, ["앞 이야기", DIVIDER_TEXT, "뒷 이야기"])
        self.assertTrue(
            self.editor.is_divider_block(self.editor.document().begin().next()),
        )

    def test_the_divider_line_spans_the_editor(self):
        self.editor.insert_divider()
        block = self.editor.document().begin()
        line = self.editor._divider_line(block)
        self.assertLess(line.x1(), 20)
        self.assertGreater(line.x2(), self.editor.viewport().width() - 20)

    def test_writing_after_a_divider_is_not_hidden(self):
        self.editor.insert_divider()
        self.editor.textCursor().insertText("뒷 이야기")
        self.editor._refresh_checklist_display()
        # 감춘 것은 구분선 줄 하나뿐이라야 한다.
        self.assertEqual(len(self.editor.extraSelections()), 1)


class FoldAllTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.panel = AlertNotesPanel(self.store)
        self.editor = self.panel.editor.content_edit
        note_id = self.store.create_note("긴 메모", "")
        self.panel.refresh()
        self.panel.show_note(note_id)
        self.editor = self.panel.editor.content_edit
        for title in ("준비물", "일정"):
            self.editor.textCursor().insertText(title)
            self.editor.make_toggle()
            press(self.editor, Qt.Key.Key_Return)
            self.editor.textCursor().insertText("안쪽")
            press(self.editor, Qt.Key.Key_Return)
            press(self.editor, Qt.Key.Key_Backtab)

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _open_marks(self):
        return [
            text[:2] for text in block_texts(self.editor)
            if text.startswith((TOGGLE_OPEN_PREFIX, TOGGLE_CLOSED_PREFIX))
        ]

    def test_it_folds_everything_at_once(self):
        self.assertEqual(self._open_marks(), [TOGGLE_OPEN_PREFIX] * 2)
        self.editor.toggle_all_folds()
        self.assertEqual(self._open_marks(), [TOGGLE_CLOSED_PREFIX] * 2)

    def test_it_opens_everything_the_second_time(self):
        self.editor.toggle_all_folds()
        self.editor.toggle_all_folds()
        self.assertEqual(self._open_marks(), [TOGGLE_OPEN_PREFIX] * 2)

    def test_one_open_toggle_means_fold_them_all(self):
        blocks = [
            block for block in self.editor._iter_blocks()
            if self.editor._is_toggle_block(block)
        ]
        self.editor._set_toggle_open(blocks[0], False)
        self.editor.toggle_all_folds()
        self.assertEqual(self._open_marks(), [TOGGLE_CLOSED_PREFIX] * 2)

    def test_the_shortcut_is_ctrl_shift_e(self):
        self.assertEqual(
            self.panel.editor.fold_all_shortcut.key(), QKeySequence("Ctrl+Shift+E"),
        )
        self.assertEqual(
            self.panel.editor.fold_all_shortcut.context(),
            Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )


class EscapeAndTheMenuTest(unittest.TestCase):
    """메뉴가 떠 있을 때 Esc 는 메뉴만 닫는다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.hobby = self.store.create_note("취미", "")
        self.drama = self.store.create_note("드라마", "")
        self.store.set_note_parent(self.drama, self.hobby)
        self.panel = AlertNotesPanel(self.store)
        self.panel.refresh()
        self.panel.show_note(self.hobby)
        self.panel.show_note(self.drama)

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_escape_closes_the_menu_instead_of_going_back(self):
        body = self.panel.editor.content_edit
        body.textCursor().insertText("/")
        body._refresh_insert_popup()
        self.assertTrue(body.insert_popup_visible())
        self.assertFalse(self.panel.go_back(), "메뉴를 닫는 대신 앞 메모로 갔습니다")
        self.assertEqual(self.panel.current_id, self.drama)
        self.assertFalse(body.insert_popup_visible())

    def test_escape_goes_back_once_the_menu_is_closed(self):
        self.assertTrue(self.panel.go_back())
        self.assertEqual(self.panel.current_id, self.hobby)


class PinnedNoteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.old = self.store.create_note("오래된 메모", "")
        self.fresh = self.store.create_note("새 메모", "")
        self.store.conn.execute(
            "UPDATE notes SET updated_at='202609040900' WHERE id=?", (self.old,))
        self.store.conn.execute(
            "UPDATE notes SET updated_at='202609041000' WHERE id=?", (self.fresh,))
        self.store.conn.commit()
        self.panel = AlertNotesPanel(self.store)
        self.panel.refresh()
        self.list = self.panel.list_panel

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _titles(self):
        return [
            item.text(self.list.TITLE_COLUMN) for item in self.list._walk()
        ]

    def test_a_pinned_memo_climbs_to_the_top(self):
        self.assertEqual(self._titles()[0], "새 메모")
        self.store.update_note(self.old, pinned=True)
        self.panel.refresh()
        self.assertTrue(self._titles()[0].endswith("오래된 메모"), self._titles())

    def test_it_is_marked_so_you_can_tell(self):
        self.store.update_note(self.old, pinned=True)
        self.panel.refresh()
        item = self.list._item_for(self.old)
        self.assertTrue(item.text(self.list.TITLE_COLUMN).startswith(self.list.PINNED_MARK))
        self.assertIn("고정", item.toolTip(self.list.TITLE_COLUMN))

    def test_the_right_click_menu_turns_it_on(self):
        self.panel.set_note_pinned(self.old, True)
        self.assertTrue(bool(self.store.note(self.old)["pinned"]))
        self.assertIn("고정", self.panel.status_label.text())
        self.panel.set_note_pinned(self.old, False)
        self.assertFalse(bool(self.store.note(self.old)["pinned"]))

    def test_the_editor_no_longer_carries_the_switch(self):
        self.panel.show_note(self.old)
        self.assertFalse(
            hasattr(self.panel.editor, "pin_check"),
            "고정은 목록에서 오른쪽 단추로만 켠다",
        )

    def test_the_row_knows_whether_it_is_pinned(self):
        from alert_notes.memo_list import PINNED_ROLE

        self.store.update_note(self.old, pinned=True)
        self.panel.refresh()
        self.assertTrue(bool(self.list._item_for(self.old).data(0, PINNED_ROLE)))
        self.assertFalse(bool(self.list._item_for(self.fresh).data(0, PINNED_ROLE)))

    def test_unpinning_puts_it_back_in_time_order(self):
        self.store.update_note(self.old, pinned=True)
        self.panel.refresh()
        self.store.update_note(self.old, pinned=False)
        self.panel.refresh()
        self.assertEqual(self._titles()[0], "새 메모")

    def test_a_pinned_child_leads_its_own_siblings(self):
        parent = self.store.create_note("취미", "")
        first = self.store.create_child_note(parent, "드라마")
        second = self.store.create_child_note(parent, "게임")
        self.store.update_note(second, pinned=True)
        titles = [str(row["title"]) for row in self.store.child_notes(parent)]
        self.assertEqual(titles[0], "게임", titles)
        self.assertIn("드라마", titles)
        self.assertNotEqual(first, second)


class ListFoldButtonTest(unittest.TestCase):
    """목록에서 하위 메모를 한 번에 접고 펴는 단추."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.hobby = self.store.create_note("취미", "")
        self.diary = self.store.create_note("일기", "")
        for parent in (self.hobby, self.diary):
            self.store.create_child_note(parent, "하위")
        self.panel = AlertNotesPanel(self.store)
        self.panel.list_panel.resize(700, 400)
        self.panel.refresh()
        self.list = self.panel.list_panel
        self.app.processEvents()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _parents(self):
        return [item for item in self.list._walk() if item.childCount()]

    def test_one_press_folds_them_all(self):
        for item in self._parents():
            item.setExpanded(True)
        self.list.toggle_all_folds()
        self.assertFalse(any(item.isExpanded() for item in self._parents()))

    def test_pressing_again_opens_them_all(self):
        self.list.toggle_all_folds()
        self.list.toggle_all_folds()
        self.assertTrue(all(item.isExpanded() for item in self._parents()))

    def test_the_button_says_what_it_will_do(self):
        for item in self._parents():
            item.setExpanded(True)
        self.list._sync_fold_button()
        self.assertEqual(self.list.fold_button.text(), "모두 접기")
        self.list.toggle_all_folds()
        self.assertEqual(self.list.fold_button.text(), "모두 펼치기")

    def test_it_is_switched_off_when_nothing_can_fold(self):
        flat = NoteReminderStore(Path(self.temp.name) / "flat.db", "새 메모")
        try:
            flat.create_note("혼자", "")
            panel = MemoListPanel(flat)
            panel.set_rows(flat.notes())
            self.assertFalse(panel.fold_button.isEnabled())
            panel.deleteLater()
        finally:
            flat.close()


class ListRoomTest(unittest.TestCase):
    """목록이 세로로 더 많이 보이는지."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        for index in range(12):
            self.store.create_note(f"메모 {index}", "본문")
        self.panel = MemoListPanel(self.store)
        self.panel.resize(700, 420)
        self.panel.show()
        self.panel.set_rows(self.store.notes())
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_the_list_fills_the_room_under_the_buttons(self):
        table_bottom = self.panel.table.geometry().bottom()
        actions_top = self.panel.actions_host.geometry().top()
        self.assertLessEqual(
            actions_top - table_bottom, 12,
            "목록과 아래 단추 사이에 빈 자리가 남습니다",
        )

    def test_nothing_is_left_over_at_the_very_bottom(self):
        actions_bottom = self.panel.actions_host.geometry().bottom()
        self.assertLessEqual(
            self.panel.height() - actions_bottom, 14,
            "Excel 내보내기 아래에 빈 자리가 남습니다",
        )

    def test_the_chrome_above_the_list_is_slim(self):
        self.assertLessEqual(
            self.panel.table.y(), 112, "목록 위쪽 여백이 아직 큽니다",
        )

    def test_more_rows_fit_than_before(self):
        # 줄 높이 32px 기준, 420px 짜리 칸에 여덟 줄은 들어가야 한다.
        room = self.panel.table.viewport().height()
        self.assertGreaterEqual(room // self.panel.ROW_HEIGHT, 8, room)


class PanelBottomTest(unittest.TestCase):
    """메모·일정 화면 맨 아래는 상태 한 줄이면 된다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.store.create_note("메모", "본문")
        self.panel = AlertNotesPanel(self.store)
        self.panel.resize(1200, 700)
        self.panel.show()
        self.panel.refresh()
        self.app.processEvents()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_the_status_line_is_one_line_tall(self):
        # 38px 이던 자리다.  글자 한 줄에 필요한 만큼만 남긴다.
        self.assertLessEqual(self.panel.STATUS_HEIGHT, 24)
        self.assertEqual(self.panel.status_label.height(), self.panel.STATUS_HEIGHT)
        self.assertGreaterEqual(
            self.panel.STATUS_HEIGHT,
            self.panel.status_label.fontMetrics().height(),
            "글자가 잘릴 만큼 낮습니다",
        )

    def test_the_tabs_take_the_rest_of_the_room(self):
        bottom = self.panel.tabs.geometry().bottom()
        top = self.panel.status_label.geometry().top()
        self.assertLessEqual(
            top - bottom, 4, "탭과 상태줄 사이가 벌어져 있습니다",
        )
        self.assertLessEqual(
            self.panel.height() - self.panel.status_label.geometry().bottom(), 2,
            "상태줄 아래에 빈 자리가 남습니다",
        )

    def test_growing_the_window_grows_the_content_not_the_gap(self):
        first = self.panel.tabs.height()
        self.panel.resize(1200, 900)
        self.app.processEvents()
        self.assertGreaterEqual(
            self.panel.tabs.height() - first, 190,
            "늘어난 높이가 탭 안 내용으로 가지 않았습니다",
        )
        self.assertEqual(self.panel.status_label.height(), self.panel.STATUS_HEIGHT)


class InsertItemsTest(unittest.TestCase):
    def test_every_item_is_well_formed(self):
        for item in INSERT_ITEMS:
            self.assertTrue(item.mark and item.name and item.method, item)
            self.assertTrue(item.hint and item.keys, item)

    def test_every_item_can_be_called_by_name(self):
        """단축키든 줄 앞 입력이든, 부르는 길이 하나는 있어야 한다."""
        for item in INSERT_ITEMS:
            self.assertTrue(item.shortcut or item.typing, item.name)

    def test_no_two_items_share_a_shortcut(self):
        used = [item.shortcut for item in INSERT_ITEMS if item.shortcut]
        self.assertEqual(len(used), len(set(used)), used)

    def test_the_plus_menu_actually_shows_its_tooltips(self):
        """Qt 는 메뉴 설명을 기본으로 감춘다.  켜 두지 않으면 적어도 안 뜬다."""
        app = QApplication.instance() or QApplication([])
        temp = tempfile.TemporaryDirectory()
        store = NoteReminderStore(Path(temp.name) / "notes.db", "새 메모")
        editor = RichMemoTextEdit(store)
        editor.set_note_context(store.create_note("여기", ""))
        menu = build_insert_menu(editor)
        try:
            self.assertTrue(menu.toolTipsVisible())
            names = {item.name: item for item in INSERT_ITEMS}
            panel = menu.actions()[0].defaultWidget()
            for row in range(panel.feature_list.count()):
                entry = panel.feature_list.item(row)
                name = entry.text().replace(PENDING_SUFFIX, "").split()[-1]
                item = names.get(name)
                if item is None:
                    continue
                self.assertIn(item.hint, entry.toolTip(), name)
        finally:
            menu.deleteLater()
            destroy_widget(editor, app)
            store.close()
            temp.cleanup()

    def test_the_tooltip_shows_what_it_is_and_how_to_call_it(self):
        for item in INSERT_ITEMS:
            tip = item_tooltip(item)
            self.assertIn(item.name, tip)
            self.assertIn(item.hint, tip)
            if item.shortcut:
                self.assertIn(item.shortcut, tip)


class TypingRuleTest(unittest.TestCase):
    """줄 앞에서 치는 글로도 기능이 켜진다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("여기", "")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.resize(600, 400)
        self.editor.show()
        self.editor.set_note_context(self.note_id)
        self.editor.setPlainText("")

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def _type(self, text):
        # Qt.Key.Key_Any 는 Key_Space 와 값이 같다.  글자는 Key_A 로 보내고
        # 실제 글자는 event.text() 에 실어 보낸다.
        for character in text:
            if character == " ":
                press(self.editor, Qt.Key.Key_Space, " ")
            else:
                press(self.editor, Qt.Key.Key_A, character)

    def _leftover(self):
        joined = "".join(block_texts(self.editor))
        for mark in (TOGGLE_OPEN_PREFIX, CALLOUT_PREFIX, DIVIDER_TEXT, "☐ "):
            joined = joined.replace(mark, "")
        return joined.strip()

    def test_dash_makes_a_bullet(self):
        self._type("- ")
        self.assertTrue(self.editor.current_block_is_bullet_list())
        self.assertEqual(self._leftover(), "")

    def test_star_makes_a_bullet_too(self):
        self._type("* ")
        self.assertTrue(self.editor.current_block_is_bullet_list())

    def test_brackets_make_a_checklist(self):
        self._type("[] ")
        self.assertTrue(self.editor.current_block_is_checklist())
        self.assertEqual(self._leftover(), "")

    def test_bang_makes_a_callout(self):
        self._type("! ")
        self.assertTrue(self.editor.current_block_is_callout())
        self.assertEqual(self._leftover(), "")

    def test_three_dashes_make_a_divider(self):
        self._type("---")
        self.assertTrue(
            any(self.editor.is_divider_block(b) for b in self.editor._iter_blocks())
        )
        self.assertEqual(self._leftover(), "")

    def test_the_angle_bracket_still_makes_a_toggle(self):
        self._type("> ")
        self.assertTrue(self.editor.current_block_is_toggle())

    def test_a_dash_in_the_middle_of_a_line_is_just_a_dash(self):
        self._type("가- ")
        self.assertFalse(self.editor.current_block_is_bullet_list())
        self.assertIn("가-", "".join(block_texts(self.editor)))

    def test_every_shortcut_in_the_list_is_actually_bound(self):
        bound = {shortcut.key().toString() for shortcut in self.editor.insert_shortcuts}
        for item in INSERT_ITEMS:
            if not item.shortcut or not hasattr(self.editor, item.method):
                continue
            self.assertIn(item.shortcut, bound, item.name)


if __name__ == "__main__":
    unittest.main()
