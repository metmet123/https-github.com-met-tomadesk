"""메모 편집 8단계 — 빠르기, 최근 본 메모, 본문 찾기, 인용문·코드, 표."""

import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QKeySequence, QTextBlockFormat, QTextCursor
from PyQt6.QtWidgets import QApplication

from alert_notes.insert_menu import INSERT_ITEMS
from alert_notes.rich_memo_edit import (
    CODE_BACKGROUND, CODE_FONT_FAMILY, CODE_PREFIX, QUOTE_PREFIX,
    TABLE_HEADER_BACKGROUND, RichMemoTextEdit,
)
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel, destroy_widget


def press(widget, key, text="", modifiers=Qt.KeyboardModifier.NoModifier):
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers, text))


def block_texts(editor):
    texts = []
    block = editor.document().begin()
    while block.isValid():
        texts.append(block.text())
        block = block.next()
    return texts


def long_body(lines: int) -> str:
    rows = []
    for index in range(lines):
        if index % 12 == 0:
            rows.append(f"▾ 묶음 {index // 12}")
        elif index % 7 == 0:
            rows.append(f"☐ 할 일 {index}")
        else:
            rows.append(f"{index}번째 줄, 예산 항목 명칭 정리 건")
    return "\n".join(rows)


class EditorCase(unittest.TestCase):
    """본문 편집기 하나를 띄워 두고 쓰는 검사들의 바탕."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("여기", "")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.resize(700, 460)
        self.editor.show()
        self.editor.set_note_context(self.note_id)
        self.editor.setPlainText("")

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def _to_end(self):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)

    def _type_letter(self, letter="가"):
        press(self.editor, Qt.Key.Key_A, letter)


class OnlyRedrawWhatChangedTest(EditorCase):
    """글자만 친 것으로 문서 전체를 다시 계산하지 않는다."""

    def _count_full_passes(self):
        """문서 전체를 다시 훑은 횟수를 센다."""
        original = self.editor._refresh_toggle_visibility
        counter = {"n": 0}

        def counted():
            counter["n"] += 1
            original()

        self.editor._refresh_toggle_visibility = counted
        return counter

    def test_typing_a_letter_never_rescans_the_document(self):
        self.editor.setPlainText(long_body(200))
        self.app.processEvents()
        self._to_end()
        counter = self._count_full_passes()
        for _ in range(10):
            self._type_letter()
        self.assertEqual(
            counter["n"], 0, "글자만 쳤는데 문서 전체를 다시 훑었습니다",
        )

    def test_a_new_line_does_rescan(self):
        self.editor.setPlainText("첫 줄")
        self.app.processEvents()
        self._to_end()
        counter = self._count_full_passes()
        press(self.editor, Qt.Key.Key_Return)
        self.assertGreaterEqual(counter["n"], 1, "줄이 늘었는데 다시 훑지 않았습니다")

    def test_touching_a_toggle_line_does_rescan(self):
        self.editor.setPlainText("▾ 묶음\n안쪽")
        self.app.processEvents()
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self.editor.setTextCursor(cursor)
        counter = self._count_full_passes()
        self._type_letter()
        self.assertGreaterEqual(
            counter["n"], 1, "토글 줄을 고쳤는데 접힘을 다시 계산하지 않았습니다",
        )

    def test_only_the_lines_on_screen_get_painted(self):
        self.editor.setPlainText(long_body(400))
        self.app.processEvents()
        seen = list(self.editor._visible_blocks())
        self.assertLess(len(seen), 400, "화면 밖 줄까지 훑고 있습니다")
        self.assertGreater(len(seen), 0)

    def test_scrolling_repaints_the_new_lines(self):
        self.editor.setPlainText(long_body(400))
        self.app.processEvents()
        bar = self.editor.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        self.app.processEvents()
        numbers = {block.blockNumber() for block in self.editor._visible_blocks()}
        self.assertTrue(numbers, "스크롤한 자리에 그릴 줄이 없습니다")
        self.assertNotIn(0, numbers, "가운데로 내렸는데 첫 줄을 그리고 있습니다")

    def test_a_long_memo_types_as_fast_as_a_short_one(self):
        """줄 수에 따라 느려지지 않아야 한다.  절대 시간 대신 비율로 본다."""
        def per_key(lines: int) -> float:
            self.editor.setPlainText(long_body(lines))
            self.app.processEvents()
            self._to_end()
            for _ in range(5):
                self._type_letter()
            start = time.perf_counter()
            for _ in range(30):
                self._type_letter()
            return (time.perf_counter() - start) / 30

        short = per_key(200)
        long = per_key(3000)
        self.assertLess(
            long, max(short * 5, 0.004),
            f"긴 메모가 짧은 메모보다 훨씬 느립니다 ({short * 1000:.1f}ms → {long * 1000:.1f}ms)",
        )


class FindInBodyTest(EditorCase):
    """Ctrl+F.  본문에서 찾고, 접힌 토글 안까지 데려간다."""

    BODY = (
        "1. 세출예산 명칭 정리\n"
        "2. 부서별 예산 요구안 취합\n"
        "3. 예산 심의 일정 공유\n"
    )

    def test_it_finds_every_place(self):
        self.editor.setPlainText(self.BODY)
        self.assertEqual(len(self.editor.find_matches("예산")), 3)

    def test_an_empty_word_finds_nothing(self):
        self.editor.setPlainText(self.BODY)
        self.assertEqual(self.editor.find_matches(""), [])

    def test_it_ignores_upper_and_lower_case(self):
        self.editor.setPlainText("Budget budget BUDGET")
        self.assertEqual(len(self.editor.find_matches("budget")), 3)
        self.assertEqual(len(self.editor.find_matches("budget", True)), 1)

    def test_the_found_places_are_painted(self):
        self.editor.setPlainText(self.BODY)
        self.app.processEvents()
        matches = self.editor.find_matches("예산")
        self.editor.set_find_highlights(matches, 0)
        painted = [
            selection for selection in self.editor.extraSelections()
            if selection.format.background().color().name() in (
                self.editor.FIND_BACKGROUND, self.editor.FIND_CURRENT_BACKGROUND,
            )
        ]
        self.assertEqual(len(painted), 3)
        current = [
            selection for selection in painted
            if selection.format.background().color().name()
            == self.editor.FIND_CURRENT_BACKGROUND
        ]
        self.assertEqual(len(current), 1, "지금 자리 하나만 진하게 칠해져야 합니다")

    def test_closing_the_search_clears_the_paint(self):
        self.editor.setPlainText(self.BODY)
        self.app.processEvents()
        self.editor.set_find_highlights(self.editor.find_matches("예산"), 0)
        self.editor.clear_find_highlights()
        self.assertFalse([
            selection for selection in self.editor.extraSelections()
            if selection.format.background().color().name() == self.editor.FIND_BACKGROUND
        ])

    def test_it_opens_a_folded_toggle_to_show_the_place(self):
        self.editor.setPlainText("첫 줄\n▾ 묶음\n안쪽에 예산 항목\n끝 줄\n")
        self.app.processEvents()
        child = next(b for b in self.editor._iter_blocks() if "안쪽에" in b.text())
        cursor = QTextCursor(child)
        fmt = QTextBlockFormat()
        fmt.setIndent(1)
        cursor.setBlockFormat(fmt)
        toggle = next(b for b in self.editor._iter_blocks() if "묶음" in b.text())
        self.editor.fold_toggle(toggle)
        self.app.processEvents()
        child = next(b for b in self.editor._iter_blocks() if "안쪽에" in b.text())
        self.assertFalse(child.isVisible(), "먼저 접혀 있어야 합니다")

        self.assertTrue(self.editor.reveal_position(child.position()))
        self.app.processEvents()
        toggle = next(b for b in self.editor._iter_blocks() if "묶음" in b.text())
        child = next(b for b in self.editor._iter_blocks() if "안쪽에" in b.text())
        self.assertTrue(self.editor._toggle_is_open(toggle), "토글 표시가 그대로입니다")
        self.assertTrue(child.isVisible())

    def test_revealing_a_visible_place_changes_nothing(self):
        self.editor.setPlainText(self.BODY)
        self.app.processEvents()
        start = self.editor.find_matches("예산")[0][0]
        self.assertFalse(self.editor.reveal_position(start))


class FindBarTest(unittest.TestCase):
    """찾기 줄을 실제로 열고 눌러 본다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from alert_notes.editor import MemoEditor
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("여기", "")
        self.editor = MemoEditor(self.store)
        self.editor.resize(700, 560)
        self.editor.show()
        self.editor.set_note(self.store.note(self.note_id))
        self.editor.content_edit.textCursor().insertText(
            "1. 세출예산 명칭 정리\n2. 부서별 예산 요구안 취합\n3. 예산 심의 일정 공유\n"
        )
        self.app.processEvents()
        self.bar = self.editor.find_bar

    def tearDown(self):
        self.editor.shutdown()
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_it_stays_out_of_the_way_until_asked(self):
        self.assertFalse(self.bar.isVisible())

    def test_ctrl_f_opens_it(self):
        self.assertEqual(self.editor.find_shortcut.key(), QKeySequence("Ctrl+F"))
        self.bar.open_bar()
        self.assertTrue(self.bar.isVisible())

    def test_it_counts_what_it_found(self):
        self.bar.open_bar()
        self.bar.input.setText("예산")
        self.bar.refresh()
        self.assertEqual(self.bar.count_label.text(), "1 / 3")

    def test_it_says_so_when_there_is_nothing(self):
        self.bar.open_bar()
        self.bar.input.setText("없는말")
        self.bar.refresh()
        self.assertEqual(self.bar.count_label.text(), "없음")

    def test_next_and_previous_walk_round(self):
        self.bar.open_bar()
        self.bar.input.setText("예산")
        self.bar.refresh()
        first = self.bar.index
        self.bar.step(1)
        self.assertEqual(self.bar.index, (first + 1) % 3)
        self.bar.step(1)
        self.bar.step(1)
        self.assertEqual(self.bar.index, first, "끝에서 처음으로 돌아와야 합니다")
        self.bar.step(-1)
        self.assertEqual(self.bar.index, (first - 1) % 3)

    def test_walking_moves_the_caret_onto_the_word(self):
        self.bar.open_bar()
        self.bar.input.setText("예산")
        self.bar.refresh()
        self.assertEqual(self.editor.content_edit.textCursor().selectedText(), "예산")

    def test_escape_closes_it_and_wipes_the_paint(self):
        self.bar.open_bar()
        self.bar.input.setText("예산")
        self.bar.refresh()
        press(self.bar, Qt.Key.Key_Escape)
        self.assertFalse(self.bar.isVisible())
        self.assertFalse([
            selection for selection in self.editor.content_edit.extraSelections()
            if selection.format.background().color().name()
            == self.editor.content_edit.FIND_BACKGROUND
        ])


class RecentNoteChipsTest(unittest.TestCase):
    """최근 본 메모 칩."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from alert_notes.panel import AlertNotesPanel
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.ids = {
            title: self.store.create_note(title, "본문")
            for title in ("가 메모", "나 메모", "다 메모", "라 메모", "마 메모")
        }
        self.panel = AlertNotesPanel(self.store)
        self.panel.resize(1300, 700)
        self.panel.show()
        self.panel.refresh()
        self.app.processEvents()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _visit(self, *titles):
        for title in titles:
            self.panel.show_note(self.ids[title])
            self.app.processEvents()

    def _chips(self):
        return [
            button.text() for button in self.panel.list_panel.recent_buttons
            if not button.isHidden()
        ]

    def test_no_chips_before_anything_is_opened(self):
        self.panel.list_panel.set_recent([])
        self.assertFalse(self.panel.list_panel.recent_host.isVisible())

    def test_it_shows_the_last_three_in_order(self):
        self._visit("가 메모", "나 메모", "다 메모", "라 메모", "마 메모")
        self.assertTrue(self.panel.list_panel.recent_toggle.isVisible())
        self.assertFalse(self.panel.list_panel.recent_host.isVisible())
        chips = self._chips()
        self.assertEqual(len(chips), 3)
        self.assertIn("라 메모", chips[0])
        self.assertIn("다 메모", chips[1])
        self.assertIn("나 메모", chips[2])

    def test_the_memo_being_read_is_not_offered(self):
        self._visit("가 메모", "나 메모")
        self.assertTrue(all("나 메모" not in chip for chip in self._chips()))

    def test_pressing_a_chip_opens_that_memo(self):
        self._visit("가 메모", "나 메모", "다 메모")
        self.panel.list_panel.recent_toggle.click()
        self.app.processEvents()
        self.assertTrue(self.panel.list_panel.recent_host.isVisible())
        self.panel.list_panel.recent_buttons[0].click()
        self.app.processEvents()
        self.assertEqual(self.panel.current_id, self.ids["나 메모"])

    def test_it_remembers_across_a_restart(self):
        self._visit("가 메모", "나 메모", "다 메모")
        kept = self.panel._recent_ids()
        self.assertEqual(kept[0], self.ids["다 메모"])
        self.assertEqual(
            [int(value) for value in self.store.setting(self.panel.RECENT_SETTING).split(",")],
            kept,
        )

    def test_a_page_inside_a_memo_never_becomes_a_chip(self):
        page = self.store.create_child_note(self.ids["가 메모"], "안쪽 페이지", True)
        self.panel.show_note(page)
        self.app.processEvents()
        self.assertNotIn(page, self.panel._recent_ids())

    def test_a_deleted_memo_drops_off_the_chips(self):
        self._visit("가 메모", "나 메모", "다 메모")
        self.store.delete_note(self.ids["나 메모"])
        self.panel.refresh_recent_chips()
        self.assertTrue(all("나 메모" not in chip for chip in self._chips()))


class QuoteAndCodeTest(EditorCase):
    """인용문과 코드 줄."""

    def _type(self, text):
        for character in text:
            if character == " ":
                press(self.editor, Qt.Key.Key_Space, " ")
            else:
                press(self.editor, Qt.Key.Key_A, character)

    def test_a_quote_mark_makes_a_quote(self):
        self._type('" ')
        self.assertTrue(self.editor.current_block_is_quote())

    def test_a_pipe_makes_a_quote_too(self):
        self._type("| ")
        self.assertTrue(self.editor.current_block_is_quote())

    def test_the_quote_mark_itself_is_not_left_behind(self):
        self._type('" 옮겨 적은 말')
        text = self.editor.textCursor().block().text()
        self.assertEqual(text, QUOTE_PREFIX + "옮겨 적은 말")

    def test_a_quote_is_slanted_and_indented(self):
        self.editor.make_quote()
        self._type("옮겨 적은 말")
        block = self.editor.textCursor().block()
        self.assertGreater(block.blockFormat().leftMargin(), 0)
        self.assertTrue(self.editor.textCursor().charFormat().fontItalic())

    def test_calling_it_twice_puts_the_line_back(self):
        self._type("보통 줄")
        self.editor.make_quote()
        self.assertTrue(self.editor.current_block_is_quote())
        self.editor.make_quote()
        self.assertFalse(self.editor.current_block_is_quote())
        self.assertEqual(self.editor.textCursor().block().text(), "보통 줄")
        self.assertEqual(self.editor.textCursor().block().blockFormat().leftMargin(), 0)

    def test_enter_leaves_the_quote(self):
        self._type('" 옮겨 적은 말')
        press(self.editor, Qt.Key.Key_Return)
        self.assertFalse(self.editor.current_block_is_quote())

    def test_three_backticks_make_a_code_line(self):
        self._type("```")
        self.assertTrue(self.editor.current_block_is_code())

    def test_a_code_line_wears_a_grey_ground_and_fixed_width_letters(self):
        self.editor.make_code_block()
        self._type("SELECT 1")
        block = self.editor.textCursor().block()
        self.assertEqual(
            block.blockFormat().background().color().name(), CODE_BACKGROUND,
        )
        families = self.editor.textCursor().charFormat().fontFamilies()
        self.assertIn(CODE_FONT_FAMILY, list(families or []))

    def test_enter_keeps_writing_code(self):
        self._type("```SELECT 1")
        press(self.editor, Qt.Key.Key_Return)
        self.assertTrue(
            self.editor.current_block_is_code(), "코드는 여러 줄로 이어져야 합니다",
        )

    def test_enter_on_an_empty_code_line_gets_out(self):
        self._type("```SELECT 1")
        press(self.editor, Qt.Key.Key_Return)
        press(self.editor, Qt.Key.Key_Return)
        self.assertFalse(self.editor.current_block_is_code())
        self.assertEqual(self.editor.textCursor().block().text(), "")

    def test_backspace_at_the_front_puts_the_line_back(self):
        self._type("```SELECT 1")
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
        self.editor.setTextCursor(cursor)
        press(self.editor, Qt.Key.Key_Backspace)
        self.assertFalse(self.editor.current_block_is_code())

    def test_a_quote_becomes_code_without_leaving_a_mark(self):
        self._type('" 옮겨 적은 말')
        self.editor.make_code_block()
        self.assertTrue(self.editor.current_block_is_code())
        self.assertEqual(
            self.editor.textCursor().block().text(), CODE_PREFIX + "옮겨 적은 말",
        )

    def test_both_survive_being_saved_and_opened_again(self):
        self._type('" 옮겨 적은 말')
        press(self.editor, Qt.Key.Key_Return)
        self._type("```SELECT 1")
        html = self.editor.document().toHtml()
        again = RichMemoTextEdit(self.store)
        try:
            again.document().setHtml(html)
            kinds = [
                "인용" if again.is_quote_block(block)
                else "코드" if again.is_code_block(block) else "보통"
                for block in again._iter_blocks()
            ]
            self.assertIn("인용", kinds)
            self.assertIn("코드", kinds)
        finally:
            destroy_widget(again, self.app)

    def test_the_marks_are_hidden_from_sight(self):
        self._type('" 옮겨 적은 말')
        self.app.processEvents()
        hidden = [
            selection for selection in self.editor.extraSelections()
            if selection.format.foreground().color().alpha() == 0
        ]
        self.assertTrue(hidden, "인용 표시가 그대로 보입니다")


class TableTest(EditorCase):
    """표 블록."""

    def _type(self, text):
        for character in text:
            if character == " ":
                press(self.editor, Qt.Key.Key_Space, " ")
            else:
                press(self.editor, Qt.Key.Key_A, character)

    def test_it_starts_with_a_header_row_and_three_columns(self):
        self.editor.insert_table()
        table = self.editor.current_table()
        self.assertIsNotNone(table)
        self.assertEqual((table.rows(), table.columns()), (3, 3))
        self.assertEqual(table.format().headerRowCount(), 1)

    def test_the_caret_lands_in_the_first_cell(self):
        self.editor.insert_table()
        cell = self.editor.current_table().cellAt(self.editor.textCursor())
        self.assertEqual((cell.row(), cell.column()), (0, 0))

    def test_the_header_row_is_marked_out(self):
        self.editor.insert_table()
        table = self.editor.current_table()
        head = table.cellAt(0, 0)
        body = table.cellAt(1, 0)
        self.assertEqual(
            head.format().background().color().name(), TABLE_HEADER_BACKGROUND,
        )
        self.assertNotEqual(
            body.format().background().color().name(), TABLE_HEADER_BACKGROUND,
        )

    def test_tab_walks_to_the_next_cell(self):
        self.editor.insert_table()
        press(self.editor, Qt.Key.Key_Tab)
        cell = self.editor.current_table().cellAt(self.editor.textCursor())
        self.assertEqual((cell.row(), cell.column()), (0, 1))

    def test_tab_wraps_to_the_next_row(self):
        self.editor.insert_table()
        for _ in range(3):
            press(self.editor, Qt.Key.Key_Tab)
        cell = self.editor.current_table().cellAt(self.editor.textCursor())
        self.assertEqual((cell.row(), cell.column()), (1, 0))

    def test_tab_in_the_last_cell_grows_the_table(self):
        self.editor.insert_table()
        for _ in range(9):
            press(self.editor, Qt.Key.Key_Tab)
        self.assertEqual(self.editor.current_table().rows(), 4)

    def test_shift_tab_walks_back(self):
        self.editor.insert_table()
        press(self.editor, Qt.Key.Key_Tab)
        press(self.editor, Qt.Key.Key_Tab)
        press(self.editor, Qt.Key.Key_Backtab)
        cell = self.editor.current_table().cellAt(self.editor.textCursor())
        self.assertEqual((cell.row(), cell.column()), (0, 1))

    def test_typing_lands_in_the_cell_you_are_in(self):
        self.editor.insert_table()
        self._type("항목")
        press(self.editor, Qt.Key.Key_Tab)
        self._type("요구액")
        table = self.editor.current_table()
        self.assertEqual(table.cellAt(0, 0).firstCursorPosition().block().text(), "항목")
        self.assertEqual(table.cellAt(0, 1).firstCursorPosition().block().text(), "요구액")

    def test_a_row_and_a_column_can_be_added(self):
        self.editor.insert_table()
        self.assertTrue(self.editor.add_table_row())
        self.assertEqual(self.editor.current_table().rows(), 4)
        self.assertTrue(self.editor.add_table_column())
        self.assertEqual(self.editor.current_table().columns(), 4)

    def test_outside_a_table_tab_still_indents(self):
        self._type("보통 줄")
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        self.editor.setTextCursor(cursor)
        press(self.editor, Qt.Key.Key_Tab)
        self.assertEqual(self.editor._block_indent(self.editor.textCursor().block()), 1)

    def test_it_survives_being_saved_and_opened_again(self):
        self.editor.insert_table()
        self._type("항목")
        html = self.editor.document().toHtml()
        again = RichMemoTextEdit(self.store)
        try:
            again.document().setHtml(html)
            cursor = QTextCursor(again.document())
            found = None
            while not cursor.atEnd():
                if cursor.currentTable() is not None:
                    found = cursor.currentTable()
                    break
                cursor.movePosition(QTextCursor.MoveOperation.NextBlock)
            self.assertIsNotNone(found, "다시 열었더니 표가 사라졌습니다")
            self.assertEqual((found.rows(), found.columns()), (3, 3))
        finally:
            destroy_widget(again, self.app)


class EverythingIsReachableTest(unittest.TestCase):
    """＋ 메뉴에 적힌 것이 모두 실제로 눌리는 상태여야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.set_note_context(self.store.create_note("여기", ""))

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_nothing_is_still_pending(self):
        missing = [
            item.name for item in INSERT_ITEMS
            if not callable(getattr(self.editor, item.method, None))
        ]
        self.assertEqual(missing, [], f"아직 못 만든 것: {missing}")

    def test_every_shortcut_is_bound(self):
        bound = {shortcut.key().toString() for shortcut in self.editor.insert_shortcuts}
        for item in INSERT_ITEMS:
            if item.shortcut:
                self.assertIn(item.shortcut, bound, item.name)


if __name__ == "__main__":
    unittest.main()
