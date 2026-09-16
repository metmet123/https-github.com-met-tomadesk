"""메모 층 나누기 4단계 — 메모 안에 사는 메모(페이지) 테스트."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

from alert_notes.insert_menu import build_insert_menu
from alert_notes.panel import AlertNotesPanel
from alert_notes.rich_memo_edit import (
    DEFAULT_PAGE_TITLE, PAGE_MARK, PAGE_URL_PREFIX, RichMemoTextEdit,
)
from alert_notes.sqlite_store import TOP_LEVEL_PARENT, NoteReminderStore
from qt_test_support import close_alert_panel


def press(widget, key, text=""):
    from PyQt6.QtGui import QKeyEvent

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


class PageLinkTest(unittest.TestCase):
    """본문에 넣는 페이지 줄."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("드라마", "")
        self.panel = AlertNotesPanel(self.store)
        self.panel.refresh()
        self.panel.show_note(self.note_id)
        self.editor = self.panel.editor.content_edit

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _page_ids(self):
        return [int(row["id"]) for row in self.store.child_notes(self.note_id)]

    def test_inserting_a_page_makes_a_note_inside_this_one(self):
        self.assertTrue(self.editor.insert_page_link())
        pages = self._page_ids()
        self.assertEqual(len(pages), 1)
        self.assertEqual(int(self.store.note(pages[0])["parent_id"]), self.note_id)
        self.assertEqual(str(self.store.note(pages[0])["title"]), DEFAULT_PAGE_TITLE)

    def test_the_body_gets_a_line_ready_for_the_title(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        block = self.editor.textCursor().block()
        self.assertEqual(block.text(), PAGE_MARK, "표시만 남기고 커서를 둬야 합니다")
        self.assertTrue(self.editor.textCursor().atBlockEnd(), "커서가 표시 뒤가 아닙니다")
        self.assertIn(
            f"{PAGE_URL_PREFIX}v2/{self.store.note(page_id)['sync_id']}", self.editor.content()
        )

    def test_what_you_type_on_the_line_becomes_the_title(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        self.editor.textCursor().insertText("회차별 감상 기록")
        self.editor.sync_page_titles()
        self.assertEqual(str(self.store.note(page_id)["title"]), "회차별 감상 기록")

    def test_leaving_it_empty_keeps_the_untitled_name(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        self.editor.sync_page_titles()
        self.assertEqual(str(self.store.note(page_id)["title"]), DEFAULT_PAGE_TITLE)

    def test_enter_finishes_the_line_and_starts_plain_text(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        self.editor.textCursor().insertText("회차별 감상")
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("그다음 줄")
        self.assertEqual(str(self.store.note(page_id)["title"]), "회차별 감상")
        texts = block_texts(self.editor)
        self.assertIn("그다음 줄", texts, texts)
        self.assertEqual(sum(1 for text in texts if text.startswith(PAGE_MARK)), 1, texts)

    def test_deleting_the_line_sends_the_page_to_the_trash(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        self.editor.textCursor().insertText("회차별 감상")
        self.editor.sync_page_titles()
        cursor = self.editor.textCursor()
        cursor.select(cursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        self.editor.sync_page_titles()
        self.assertIsNone(self.store.note(page_id), "줄을 지웠는데 페이지가 남았습니다")
        self.assertIn(
            "회차별 감상",
            [str(row["title"]) for row in self.store.trashed_notes()],
        )

    def test_bringing_the_line_back_brings_the_page_back(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        self.editor.textCursor().insertText("회차별 감상")
        self.editor.sync_page_titles()
        cursor = self.editor.textCursor()
        cursor.select(cursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        self.editor.sync_page_titles()
        self.editor.undo()
        self.editor.sync_page_titles()
        self.assertIsNotNone(
            self.store.note(page_id), "되돌렸는데 페이지가 휴지통에 남았습니다",
        )

    def test_switching_memos_does_not_bin_the_pages(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        self.editor.textCursor().insertText("회차별 감상")
        self.panel.editor.flush_pending_save()
        other = self.store.create_note("다른 메모", "")
        self.panel.show_note(other)
        self.panel.editor.content_edit.sync_page_titles()
        self.assertIsNotNone(
            self.store.note(page_id), "다른 메모로 갔다고 페이지가 지워졌습니다",
        )

    def test_the_line_carries_the_new_title_after_a_rename(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        saved = self.editor.content()
        self.store.update_note(page_id, title="회차별 감상")

        reopened = RichMemoTextEdit(self.store)
        reopened.show()
        reopened.set_note_context(self.note_id + 1000)
        reopened.set_content(saved)
        texts = []
        block = reopened.document().begin()
        while block.isValid():
            texts.append(block.text())
            block = block.next()
        self.assertIn(f"{PAGE_MARK}회차별 감상", texts, texts)
        self.assertNotIn(f"{PAGE_MARK}{DEFAULT_PAGE_TITLE}", texts)
        reopened.hide()
        reopened.deleteLater()

    def test_a_deleted_page_says_so_instead_of_lying(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        saved = self.editor.content()
        self.store.delete_note(page_id)

        reopened = RichMemoTextEdit(self.store)
        reopened.show()
        reopened.set_content(saved)
        texts = []
        block = reopened.document().begin()
        while block.isValid():
            texts.append(block.text())
            block = block.next()
        self.assertIn(f"{PAGE_MARK}지운 페이지", texts, texts)
        reopened.hide()
        reopened.deleteLater()

    def test_renaming_a_page_updates_the_line_when_you_come_back(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        self.panel.editor.flush_pending_save()
        # 페이지를 열어 제목을 고치고, 부모 메모로 돌아온다.
        self.panel.show_note(page_id)
        self.panel.editor.title_edit.setText("회차별 감상")
        self.panel.editor.flush_pending_save()
        self.panel.show_note(self.note_id)
        texts = []
        block = self.panel.editor.content_edit.document().begin()
        while block.isValid():
            texts.append(block.text())
            block = block.next()
        self.assertIn(f"{PAGE_MARK}회차별 감상", texts, texts)

    def test_typing_after_a_page_line_stays_ordinary_text(self):
        self.editor.insert_page_link()
        self.editor.textCursor().insertText("회차별 감상")
        press(self.editor, Qt.Key.Key_Return)
        self.editor.textCursor().insertText("미스터 션샤인 — 재시청 중")
        self.editor.insert_page_link()
        self.editor.textCursor().insertText("명대사 모음")
        self.panel.editor.set_note(self.store.note(self.note_id))
        texts = []
        block = self.panel.editor.content_edit.document().begin()
        while block.isValid():
            texts.append(block.text())
            block = block.next()
        self.assertIn("미스터 션샤인 — 재시청 중", texts, texts)
        self.assertEqual(
            sum(1 for text in texts if text.startswith(PAGE_MARK)), 2, texts,
        )

    def test_writing_in_the_opened_page_is_not_underlined(self):
        self.editor.insert_page_link()
        self.editor.textCursor().insertText("회차별 감상")
        page_id = self._page_ids()[0]
        # 본문 줄을 눌러 그 페이지를 연다.
        self.panel.show_note(page_id)
        body = self.panel.editor.content_edit
        self.assertFalse(
            body.currentCharFormat().fontUnderline(),
            "페이지 줄의 밑줄이 새 메모까지 따라왔습니다",
        )
        self.assertFalse(body.currentCharFormat().isAnchor())
        body.textCursor().insertText("1화 감상문")
        cursor = body.textCursor()
        cursor.setPosition(body.document().begin().position() + 1)
        self.assertFalse(cursor.charFormat().fontUnderline(), "친 글자에 밑줄이 붙었습니다")
        self.assertFalse(cursor.charFormat().isAnchor())

    def test_the_page_line_itself_still_looks_like_a_link(self):
        self.editor.insert_page_link()
        self.editor.textCursor().insertText("회차별 감상")
        block = self.editor.textCursor().block()
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + len(PAGE_MARK) + 1)
        self.assertTrue(cursor.charFormat().isAnchor(), "페이지 줄이 링크가 아닙니다")
        self.assertTrue(cursor.charFormat().fontUnderline())

    def test_an_unsaved_memo_cannot_hold_a_page(self):
        loose = RichMemoTextEdit(self.store)
        loose.show()
        with patch("alert_notes.rich_memo_edit.QMessageBox.information") as told:
            self.assertFalse(loose.insert_page_link())
        told.assert_called_once()
        loose.hide()
        loose.deleteLater()

    def test_the_page_reading_survives_a_round_trip(self):
        self.editor.insert_page_link()
        page_id = self._page_ids()[0]
        self.assertEqual(
            RichMemoTextEdit.page_id_at(f"{PAGE_URL_PREFIX}{page_id}"), page_id,
        )
        self.assertIsNone(RichMemoTextEdit.page_id_at("https://example.com"))
        self.assertIsNone(RichMemoTextEdit.page_id_at(""))


class PageOpeningTest(unittest.TestCase):
    """페이지 줄을 눌렀을 때와 위치 표시줄."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.hobby = self.store.create_note("취미", "")
        self.drama = self.store.create_note("드라마", "")
        self.episode = self.store.create_note("1화", "")
        self.store.set_note_parent(self.drama, self.hobby)
        self.store.set_note_parent(self.episode, self.drama)
        self.panel = AlertNotesPanel(self.store)
        self.panel.refresh()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_clicking_a_page_line_opens_that_memo(self):
        self.panel.show_note(self.hobby)
        editor = self.panel.editor.content_edit
        editor.page_open_requested.emit(self.drama)
        self.app.processEvents()
        self.assertEqual(self.panel.current_id, self.drama)
        self.assertEqual(self.panel.editor.note_id, self.drama)

    def test_the_breadcrumb_shows_where_you_are(self):
        self.panel.show_note(self.episode)
        crumb = self.panel.editor.breadcrumb
        # 패널을 띄우지 않은 검사이므로, 스스로 숨었는지만 본다.
        self.assertFalse(crumb.isHidden())
        self.assertIn("취미", crumb.text())
        self.assertIn("드라마", crumb.text())
        self.assertIn("1화", crumb.text())
        self.assertIn(f'href="{self.hobby}"', crumb.text())

    def test_a_top_level_memo_has_no_breadcrumb(self):
        self.panel.show_note(self.hobby)
        self.assertTrue(self.panel.editor.breadcrumb.isHidden())

    def test_the_breadcrumb_takes_you_up(self):
        self.panel.show_note(self.episode)
        self.panel.editor._breadcrumb_clicked(str(self.hobby))
        self.app.processEvents()
        self.assertEqual(self.panel.current_id, self.hobby)

    def test_the_path_stops_even_if_the_links_make_a_ring(self):
        # 저장소가 막지만, 어쩌다 고리가 생겨도 돌지 않아야 한다.
        self.store.conn.execute(
            "UPDATE notes SET parent_id=? WHERE id=?", (self.episode, self.hobby),
        )
        self.store.conn.commit()
        path = self.store.note_path(self.episode)
        self.assertLessEqual(len(path), 3)


class ListPlusButtonTest(unittest.TestCase):
    """목록에서 줄에 마우스를 올렸을 때 뜨는 + 단추."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.hobby = self.store.create_note("취미", "")
        self.panel = AlertNotesPanel(self.store)
        self.panel.list_panel.resize(700, 330)
        self.panel.refresh()
        self.list = self.panel.list_panel
        self.app.processEvents()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _hover(self, point):
        self.list.table.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, QPointF(point), QPointF(point),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        ))

    def test_hovering_a_row_offers_the_plus(self):
        item = self.list._item_for(self.hobby)
        self._hover(self.list.table.plus_rect(item).center())
        self.assertIs(self.list.table.hovered_row(), item)
        self.assertEqual(
            self.list.table.viewport().cursor().shape(), Qt.CursorShape.PointingHandCursor,
        )

    def test_pressing_it_makes_a_memo_inside_that_one(self):
        self.panel.create_child_note(self.hobby)
        children = self.store.child_notes(self.hobby)
        self.assertEqual(len(children), 1)
        self.assertEqual(int(children[0]["parent_id"]), self.hobby)
        self.assertEqual(self.panel.current_id, int(children[0]["id"]))
        self.assertTrue(self.list._item_for(self.hobby).isExpanded())

    def test_the_plus_sits_inside_the_title_column(self):
        item = self.list._item_for(self.hobby)
        plus = self.list.table.plus_rect(item)
        header = self.list.table.header()
        left = header.sectionViewportPosition(self.list.TITLE_COLUMN)
        right = left + self.list.table.columnWidth(self.list.TITLE_COLUMN)
        self.assertGreaterEqual(plus.left(), left)
        self.assertLessEqual(plus.right(), right)


class PlusButtonCrashTest(unittest.TestCase):
    """+ 를 누르면 목록을 다시 그린다.  지워진 줄을 잡고 있으면 프로그램이 꺼졌다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.hobby = self.store.create_note("취미", "")
        self.panel = AlertNotesPanel(self.store)
        self.panel.list_panel.resize(700, 330)
        self.panel.refresh()
        self.list = self.panel.list_panel
        self.app.processEvents()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _hover(self, item):
        point = self.list.table.plus_rect(item).center()
        self.list.table.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, QPointF(point), QPointF(point),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        ))

    def test_redrawing_lets_go_of_the_row_under_the_mouse(self):
        self._hover(self.list._item_for(self.hobby))
        self.assertIsNotNone(self.list.table.hovered_row())
        self.panel.refresh()
        self.assertIsNone(
            self.list.table.hovered_row(),
            "지워진 줄을 아직 잡고 있습니다.  다음 그리기에서 프로그램이 꺼집니다",
        )

    def test_pressing_the_plus_and_drawing_again_does_not_crash(self):
        self._hover(self.list._item_for(self.hobby))
        self.panel.create_child_note(self.hobby)
        # 다시 그려 본다.  잡고 있던 줄이 살아 있지 않으면 여기서 죽었다.
        self.list.table.viewport().grab()
        self.app.processEvents()
        self.assertEqual(len(self.store.child_notes(self.hobby)), 1)

    def test_a_stale_row_is_shrugged_off_while_drawing(self):
        from alert_notes.memo_list import TitleCountDelegate

        item = self.list._item_for(self.hobby)
        index = self.list.table.indexFromItem(item, self.list.TITLE_COLUMN)
        self._hover(item)
        self.list.table.clear()
        self.assertFalse(TitleCountDelegate._hovered(self.list.table, index))
        self.assertIsNone(self.list.table.hovered_row())


class EscapeGoesBackTest(unittest.TestCase):
    """Esc 로 왔던 메모로 돌아간다."""

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

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_escape_returns_to_the_memo_you_came_from(self):
        self.panel.show_note(self.hobby)
        self.panel.show_note(self.drama)
        self.assertTrue(self.panel.go_back())
        self.assertEqual(self.panel.current_id, self.hobby)

    def test_it_walks_all_the_way_back(self):
        self.panel.show_note(self.hobby)
        self.panel.show_note(self.drama)
        page = self.store.create_child_note(self.drama, "1화", embedded=True)
        self.panel.show_note(page)
        self.assertTrue(self.panel.go_back())
        self.assertEqual(self.panel.current_id, self.drama)
        self.assertTrue(self.panel.go_back())
        self.assertEqual(self.panel.current_id, self.hobby)

    def test_with_no_history_it_climbs_to_the_parent(self):
        self.panel.select_note(self.drama)
        self.panel.visit_history.clear()
        self.assertTrue(self.panel.go_back())
        self.assertEqual(self.panel.current_id, self.hobby)

    def test_a_top_level_memo_with_no_history_stays_put(self):
        self.panel.select_note(self.hobby)
        self.panel.visit_history.clear()
        self.assertFalse(self.panel.go_back())
        self.assertEqual(self.panel.current_id, self.hobby)

    def test_a_memo_that_was_deleted_meanwhile_is_skipped(self):
        self.panel.show_note(self.hobby)
        self.panel.show_note(self.drama)
        self.store.delete_note(self.hobby)
        self.assertFalse(self.panel.go_back(), "지운 메모로 돌아가려 했습니다")

    def test_the_shortcut_is_esc_and_only_inside_the_editor(self):
        from PyQt6.QtGui import QKeySequence

        self.assertEqual(
            self.panel.back_shortcut.key(), QKeySequence(Qt.Key.Key_Escape),
        )
        self.assertEqual(
            self.panel.back_shortcut.context(),
            Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        self.assertIs(self.panel.back_shortcut.parent(), self.panel.editor)


class EmbeddedPagesStayOutOfTheListTest(unittest.TestCase):
    """본문에 넣은 페이지는 메모 목록에 내놓지 않는다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.drama = self.store.create_note("드라마", "")
        self.panel = AlertNotesPanel(self.store)
        self.panel.refresh()
        self.panel.show_note(self.drama)
        self.list = self.panel.list_panel

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _titles(self):
        return [
            item.text(self.list.TITLE_COLUMN) for item in self.list._walk()
        ]

    def test_a_page_from_the_body_is_not_listed(self):
        self.panel.editor.content_edit.insert_page_link()
        self.panel.refresh()
        self.assertEqual(self._titles(), ["드라마"])
        self.assertNotIn(DEFAULT_PAGE_TITLE, self._titles())

    def test_the_page_still_exists_and_opens(self):
        self.panel.editor.content_edit.insert_page_link()
        page = self.store.child_notes(self.drama)[0]
        self.assertEqual(int(page["embedded"]), 1)
        self.panel.show_note(int(page["id"]))
        self.assertEqual(self.panel.editor.note_id, int(page["id"]))

    def test_a_child_made_from_the_list_is_still_listed(self):
        self.panel.create_child_note(self.drama)
        self.panel.refresh()
        self.list._item_for(self.drama).setExpanded(True)
        self.assertIn("새 메모", self._titles(), self._titles())

    def test_searching_can_still_find_a_page(self):
        self.panel.editor.content_edit.insert_page_link()
        self.panel.refresh()
        self.list.search.setText(DEFAULT_PAGE_TITLE)
        self.app.processEvents()
        self.assertIn(DEFAULT_PAGE_TITLE, self._titles(), self._titles())

    def test_deleting_the_parent_takes_the_page_too(self):
        self.panel.editor.content_edit.insert_page_link()
        page_id = int(self.store.child_notes(self.drama)[0]["id"])
        self.store.delete_note(self.drama)
        self.assertIsNone(self.store.note(page_id), "본문 페이지가 남았습니다")


class InsertMenuPageTest(unittest.TestCase):
    """기능 펼침 메뉴의 '페이지 추가' 가 이제 켜져 있어야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.show()

    def tearDown(self):
        self.editor.hide()
        self.editor.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.store.close()
        self.temp.cleanup()

    def test_the_page_item_is_no_longer_pending(self):
        menu = build_insert_menu(self.editor)
        panel = menu.actions()[0].defaultWidget()
        page = next(
            panel.feature_list.item(row)
            for row in range(panel.feature_list.count())
            if "페이지" in panel.feature_list.item(row).text()
        )
        self.assertTrue(page.flags() & Qt.ItemFlag.ItemIsEnabled, "페이지 추가가 아직 흐리게 남아 있습니다")
        self.assertNotIn("준비 중", page.text())
        menu.deleteLater()


if __name__ == "__main__":
    unittest.main()
