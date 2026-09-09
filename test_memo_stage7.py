"""메모 편집 보강 — 메모 링크, 그림 크기 조절, 전체 화면, 오른쪽 손잡이."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QImage, QKeySequence, QMouseEvent, QTextCursor
from PyQt6.QtWidgets import QApplication, QDialog

from alert_notes.editor import MemoEditor
from alert_notes.insert_menu import build_insert_menu
from alert_notes.note_link_dialog import NoteLinkDialog
from alert_notes.panel import AlertNotesPanel
from alert_notes.rich_memo_edit import (
    IMAGE_USER_WIDTH, LINK_MARK, PAGE_MARK, PAGE_URL_PREFIX, RichMemoTextEdit,
)
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel, destroy_widget


def block_texts(editor):
    texts = []
    block = editor.document().begin()
    while block.isValid():
        texts.append(block.text())
        block = block.next()
    return texts


class NoteLinkTest(unittest.TestCase):
    """메모 링크는 가리키기만 한다.  지워도 그 메모는 남는다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.here = self.store.create_note("여기", "")
        self.there = self.store.create_note("저기 메모", "본문")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.resize(560, 300)
        self.editor.show()
        self.editor.set_note_context(self.here)

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def _insert_link(self, note_id=None):
        wanted = self.there if note_id is None else note_id
        with (
            patch.object(NoteLinkDialog, "exec", return_value=QDialog.DialogCode.Accepted),
            patch.object(NoteLinkDialog, "chosen_id", return_value=wanted),
            patch.object(
                NoteLinkDialog, "chosen_title",
                return_value=str(self.store.note(wanted)["title"]),
            ),
        ):
            return self.editor.insert_note_link()

    def test_a_link_carries_the_memo_title(self):
        self.assertTrue(self._insert_link())
        self.assertIn(f"{LINK_MARK}저기 메모", block_texts(self.editor)[0])
        self.assertIn(f"{PAGE_URL_PREFIX}{self.there}", self.editor.content())

    def test_a_link_makes_no_new_memo(self):
        before = len(self.store.notes())
        self._insert_link()
        self.assertEqual(len(self.store.notes()), before, "링크가 메모를 새로 만들었습니다")
        self.assertEqual(self.store.child_notes(self.here), [])

    def test_deleting_the_link_keeps_the_memo(self):
        self._insert_link()
        cursor = self.editor.textCursor()
        cursor.select(cursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        self.editor.sync_page_titles()
        self.assertIsNotNone(
            self.store.note(self.there), "링크를 지웠더니 메모까지 사라졌습니다",
        )

    def test_backspacing_the_link_away_keeps_the_memo(self):
        self._insert_link()
        cursor = self.editor.textCursor()
        for _ in range(len(LINK_MARK) + len("저기 메모") + 1):
            cursor.deletePreviousChar()
        self.editor.sync_page_titles()
        self.assertIsNotNone(self.store.note(self.there))
        self.assertNotIn(LINK_MARK, "".join(block_texts(self.editor)))

    def test_the_link_follows_a_renamed_memo(self):
        self._insert_link()
        saved = self.editor.content()
        self.store.update_note(self.there, title="이름 바꾼 메모")
        reopened = RichMemoTextEdit(self.store)
        reopened.show()
        reopened.set_content(saved)
        self.assertIn(f"{LINK_MARK}이름 바꾼 메모", "".join(block_texts(reopened)))
        destroy_widget(reopened, self.app)

    def test_a_link_to_a_binned_memo_says_so(self):
        self._insert_link()
        saved = self.editor.content()
        self.store.delete_note(self.there)
        reopened = RichMemoTextEdit(self.store)
        reopened.show()
        reopened.set_content(saved)
        self.assertIn(f"{LINK_MARK}지운 메모", "".join(block_texts(reopened)))
        destroy_widget(reopened, self.app)

    def test_writing_after_a_link_is_ordinary_text(self):
        self._insert_link()
        self.editor.textCursor().insertText("그다음 글")
        cursor = self.editor.textCursor()
        cursor.setPosition(cursor.position() - 1)
        self.assertFalse(cursor.charFormat().isAnchor(), "이어 친 글까지 링크가 됐습니다")

    def test_the_menu_offers_it(self):
        menu = build_insert_menu(self.editor)
        panel = menu.actions()[0].defaultWidget()
        labels = [panel.feature_list.item(row).text() for row in range(panel.feature_list.count())]
        self.assertTrue(any("메모 링크" in label for label in labels), labels)
        menu.deleteLater()

    def test_the_chooser_leaves_out_the_memo_you_are_in(self):
        dialog = NoteLinkDialog(self.store, self.here)
        ids = [
            dialog.list.item(row).data(NoteLinkDialog.ID_ROLE)
            for row in range(dialog.list.count())
        ]
        self.assertNotIn(self.here, ids)
        self.assertIn(self.there, ids)
        dialog.deleteLater()


class ImageResizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("그림", "")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.resize(600, 400)
        self.editor.show()
        self.editor.set_note_context(self.note_id)
        image = QImage(400, 200, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkCyan)
        self.assertTrue(self.editor.insert_image(image))
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def _fragment(self):
        return next(self.editor._image_fragments())

    def test_the_corner_can_be_grabbed(self):
        rect = self.editor.image_rect(self._fragment())
        corner = QPointF(rect.right() - 3, rect.bottom() - 3)
        self.assertIsNotNone(self.editor.image_grip_at(corner))
        middle = QPointF(rect.center())
        self.assertIsNone(self.editor.image_grip_at(middle), "가운데도 모서리로 봅니다")

    def test_dragging_the_corner_changes_the_size(self):
        before = self.editor.image_rect(self._fragment())
        self.editor.begin_image_resize(self._fragment())
        self.assertTrue(self.editor.resize_image_to(before.width() - 80))
        after = self.editor.image_rect(self._fragment())
        self.assertLess(after.width(), before.width())
        self.assertAlmostEqual(
            after.width() / after.height(), before.width() / before.height(), places=2,
        )

    def test_it_never_shrinks_to_nothing(self):
        self.editor.begin_image_resize(self._fragment())
        self.editor.resize_image_to(4)
        self.assertGreaterEqual(self.editor.image_rect(self._fragment()).width(), 60)

    def test_the_chosen_size_survives_a_window_resize(self):
        self.editor.begin_image_resize(self._fragment())
        self.editor.resize_image_to(180)
        self.editor.finish_image_resize()
        chosen = self.editor.image_rect(self._fragment()).width()
        self.editor.resize(760, 400)
        self.editor.refit_images()
        self.app.processEvents()
        self.assertAlmostEqual(
            self.editor.image_rect(self._fragment()).width(), chosen, places=0,
        )

    def test_the_chosen_size_is_written_down(self):
        self.editor.begin_image_resize(self._fragment())
        self.editor.resize_image_to(200)
        image = self._fragment().charFormat().toImageFormat()
        self.assertTrue(image.property(IMAGE_USER_WIDTH))

    def test_it_never_grows_past_the_editor(self):
        self.editor.begin_image_resize(self._fragment())
        self.editor.resize_image_to(5000)
        self.assertLessEqual(
            self.editor.image_rect(self._fragment()).width(),
            self.editor._available_image_width() + 1,
        )


class EditorFullscreenTest(unittest.TestCase):
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

    def test_it_hides_the_list_and_the_summary(self):
        self.panel.toggle_editor_fullscreen()
        self.assertTrue(self.panel.editor_fullscreen)
        self.assertTrue(self.panel.list_panel.isHidden())
        self.assertTrue(self.panel.editor_remainder.isHidden())
        self.assertTrue(self.panel.tabs.tabBar().isHidden())

    def test_it_puts_everything_back(self):
        self.panel.toggle_editor_fullscreen()
        self.panel.toggle_editor_fullscreen()
        self.assertFalse(self.panel.editor_fullscreen)
        self.assertFalse(self.panel.list_panel.isHidden())
        self.assertFalse(self.panel.editor_remainder.isHidden())
        self.assertFalse(self.panel.tabs.tabBar().isHidden())

    def test_the_editor_gets_the_whole_width(self):
        before = self.panel.editor_scroll.width()
        self.panel.toggle_editor_fullscreen()
        self.app.processEvents()
        self.assertGreater(self.panel.editor_scroll.width(), before)

    def test_the_button_and_the_key_do_the_same_thing(self):
        self.assertEqual(
            self.panel.fullscreen_shortcut.key(), QKeySequence("F11"),
        )
        self.panel.editor.fullscreen_button.click()
        self.assertTrue(self.panel.editor_fullscreen)
        self.panel.editor.fullscreen_button.click()
        self.assertFalse(self.panel.editor_fullscreen)

    def test_the_button_says_how_to_come_back(self):
        self.panel.toggle_editor_fullscreen()
        self.assertIn("원래 화면", self.panel.editor.fullscreen_button.toolTip())
        self.panel.toggle_editor_fullscreen()
        self.assertIn("크게", self.panel.editor.fullscreen_button.toolTip())

    def test_asking_twice_for_the_same_thing_is_harmless(self):
        self.assertTrue(self.panel.toggle_editor_fullscreen(True))
        self.assertTrue(self.panel.toggle_editor_fullscreen(True))
        self.assertTrue(self.panel.editor_fullscreen)


class InsertPopupRoomTest(unittest.TestCase):
    """`/` 메뉴는 스크롤 없이 다 보여야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("메모", "")
        self.editor = RichMemoTextEdit(self.store)
        self.editor.resize(600, 500)
        self.editor.show()
        self.editor.set_note_context(self.note_id)

    def tearDown(self):
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_every_item_fits_without_scrolling(self):
        self.editor.textCursor().insertText("/")
        self.editor._refresh_insert_popup()
        popup = self.editor._insert_popup
        count = popup.count()
        self.assertGreaterEqual(count, 7, "항목이 줄었습니다")
        needed = count * max(popup.sizeHintForRow(0), self.editor.INSERT_ROW_HEIGHT)
        self.assertGreaterEqual(
            popup.height(), needed,
            f"{count}개를 담기에 {popup.height()}px 은 모자랍니다",
        )
        self.assertEqual(
            popup.verticalScrollBar().maximum(), 0, "스크롤을 내려야 다 보입니다",
        )

    def test_a_narrowed_list_shrinks_to_fit(self):
        self.editor.textCursor().insertText("/강조")
        self.editor._refresh_insert_popup()
        popup = self.editor._insert_popup
        self.assertEqual(popup.count(), 1)
        self.assertLess(popup.height(), 60, "한 줄인데 창이 큽니다")


class SidebarToggleTest(unittest.TestCase):
    """메모 목록 접기와, 접었을 때의 자리 나눔."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.store.create_note("메모", "본문")
        self.panel = AlertNotesPanel(self.store)
        self.panel.resize(1300, 720)
        self.panel.show()
        self.panel.refresh()
        self.app.processEvents()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_it_folds_the_list_away(self):
        self.panel.toggle_memo_list()
        self.assertTrue(self.panel.memo_list_hidden)
        self.assertTrue(self.panel.list_panel.isHidden())
        self.assertFalse(
            self.panel.editor_remainder.isHidden(), "오늘 요약까지 접혔습니다",
        )

    def test_the_body_takes_the_freed_room(self):
        before = self.panel.editor_scroll.width()
        self.panel.toggle_memo_list()
        self.app.processEvents()
        self.assertGreater(self.panel.editor_scroll.width(), before)

    def test_the_side_rows_stop_at_a_readable_width(self):
        self.panel.toggle_memo_list()
        self.app.processEvents()
        for widget in self.panel.editor.side_rows:
            self.assertLessEqual(
                widget.width(), self.panel.editor.SIDE_ROW_WIDTH,
                "가로로 늘어나 봐야 빈 자리만 생기는 줄이 넓어졌습니다",
            )

    def test_unfolding_puts_the_widths_back(self):
        self.panel.toggle_memo_list()
        self.panel.toggle_memo_list()
        self.app.processEvents()
        self.assertFalse(self.panel.memo_list_hidden)
        self.assertFalse(self.panel.list_panel.isHidden())
        for widget in self.panel.editor.side_rows:
            self.assertGreater(widget.maximumWidth(), self.panel.editor.SIDE_ROW_WIDTH)

    def test_the_button_says_which_way_it_goes(self):
        button = self.panel.editor.sidebar_button
        self.assertEqual(button.text(), "◀")
        self.panel.toggle_memo_list()
        self.assertEqual(button.text(), "▶")
        self.assertIn("다시", button.toolTip())

    def test_the_button_and_the_key_agree(self):
        self.assertEqual(
            self.panel.sidebar_shortcut.key(), QKeySequence("Ctrl+\\"),
        )
        self.panel.editor.sidebar_button.click()
        self.assertTrue(self.panel.memo_list_hidden)
        self.panel.editor.sidebar_button.click()
        self.assertFalse(self.panel.memo_list_hidden)


class BottomTwoColumnTest(unittest.TestCase):
    """넓어지면 보조 줄이 두 칸으로 갈라져 본문에 자리를 내준다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note = self.store.create_note("여기", "")
        self.editor = MemoEditor(self.store)
        self.editor.resize(520, 620)
        self.editor.show()
        self.editor.set_note(self.store.note(self.note))
        self.app.processEvents()

    def tearDown(self):
        self.editor.shutdown()
        destroy_widget(self.editor, self.app)
        self.store.close()
        self.temp.cleanup()

    def _resize(self, width):
        self.editor.resize(width, 620)
        self.app.processEvents()
        self.app.processEvents()

    def test_narrow_keeps_the_old_stacking(self):
        self.assertFalse(self.editor._two_column_bottom)
        self.assertFalse(self.editor.bottom_right.isVisible())
        # 서식 도구는 본문 바로 위, 제목 아래에 있다.
        self.assertIs(self.editor.format_toolbar.parentWidget(), self.editor)
        self.assertLess(
            self.editor.format_toolbar.y(), self.editor.content_edit.y(),
        )

    def test_wide_splits_into_two_columns(self):
        self._resize(1200)
        self.assertTrue(self.editor._two_column_bottom)
        self.assertTrue(self.editor.bottom_right.isVisible())
        for widget in (self.editor.format_toolbar, self.editor.below_host,
                       self.editor.actions_host):
            self.assertIs(widget.parentWidget(), self.editor.bottom_right)
        for widget in (self.editor.reminder_card, self.editor.hotkey_card):
            self.assertIs(widget.parentWidget(), self.editor.bottom_left)

    def test_the_body_gains_room_when_it_splits(self):
        self._resize(880)
        narrow = self.editor.content_edit.height()
        self._resize(1200)
        self.assertGreater(self.editor.content_edit.height(), narrow)

    def test_going_back_and_forth_keeps_every_row(self):
        rows = (self.editor.format_toolbar, self.editor.below_host,
                self.editor.reminder_card, self.editor.hotkey_card,
                self.editor.actions_host)
        for _ in range(2):
            self._resize(1200)
            self._resize(520)
        for widget in rows:
            self.assertTrue(widget.isVisible(), widget.objectName())
            self.assertGreater(widget.height(), 0)
        self.assertIs(self.editor.format_toolbar.parentWidget(), self.editor)

    def test_a_squeezed_right_column_folds_the_colour_row(self):
        """오른쪽 칸이 좁으면 색상 줄이 두 줄로 접혀 휴지통이 잘리지 않는다."""
        self._resize(960)
        self.assertTrue(self.editor._two_column_bottom)
        self.assertTrue(self.editor._responsive_compact)
        # 오른쪽 칸이 색상 줄 한 줄만큼 넓어지면 다시 한 줄로 편다.
        self._resize(1080)
        self.assertFalse(self.editor._responsive_compact)
        self._resize(1400)
        self.assertFalse(self.editor._responsive_compact)

    def test_the_delete_button_never_runs_past_the_edge(self):
        for width in (900, 960, 1040, 1071, 1080, 1200, 1400):
            self._resize(width)
            button = self.editor.delete_button
            right = button.mapTo(self.editor, button.rect().topRight()).x()
            self.assertLessEqual(right, width, f"{width}px 에서 휴지통이 넘친다")


if __name__ == "__main__":
    unittest.main()
