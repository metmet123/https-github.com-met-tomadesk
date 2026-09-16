"""메모 층 나누기 3단계 — 접히는 메모 목록 테스트."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QMessageBox, QTreeWidgetItem,
)

from alert_notes.memo_list import (
    CHILD_COUNT_ROLE, NOTE_ID_ROLE, MemoListPanel, MemoTree, TitleCountDelegate,
)
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import TOP_LEVEL_PARENT, NoteReminderStore
from qt_test_support import close_alert_panel


class MemoTreeListTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = NoteReminderStore(self.root / "notes.db", default_title="새 메모")
        self.hobby = self.store.create_note("취미", "취미 모음")
        self.drama = self.store.create_note("드라마", "폭싹 속았수다")
        self.game = self.store.create_note("게임", "젤다 사당 정리")
        self.diary = self.store.create_note("일기", "오늘 회의")
        self.store.set_note_parent(self.drama, self.hobby)
        self.store.set_note_parent(self.game, self.hobby)
        self.panel = AlertNotesPanel(self.store)
        self.list = self.panel.list_panel
        self.panel.refresh()

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _item(self, note_id):
        return self.list._item_for(note_id)

    def _titles(self, item):
        return [item.child(index).text(1) for index in range(item.childCount())]

    # ------------------------------------------------------------- 모양 --
    def test_children_sit_under_their_parent(self):
        hobby = self._item(self.hobby)
        self.assertIsNotNone(hobby)
        self.assertEqual(sorted(self._titles(hobby)), ["게임", "드라마"])
        self.assertIsNone(self._item(self.diary).parent(), "일기는 맨 위층이라야 합니다")

    def test_the_arrow_sits_in_the_title_column(self):
        self.assertEqual(
            self.list.table.treePosition(), self.list.TITLE_COLUMN,
            "펼침 화살표가 선택 체크 자리를 차지합니다",
        )

    def test_folding_hides_the_children(self):
        hobby = self._item(self.hobby)
        hobby.setExpanded(True)
        self.assertTrue(all(not hobby.child(i).isHidden() for i in range(hobby.childCount())))
        hobby.setExpanded(False)
        self.assertFalse(hobby.isExpanded())
        self.assertEqual(self.list.row_count(), 4, "접어도 메모 자체가 사라지면 안 됩니다")

    def test_a_folded_parent_carries_its_count_as_a_bare_number(self):
        hobby = self._item(self.hobby)
        self.assertEqual(hobby.data(self.list.TITLE_COLUMN, CHILD_COUNT_ROLE), 2)
        self.assertNotIn("하위", hobby.text(self.list.TITLE_COLUMN))
        self.assertEqual(hobby.text(self.list.TITLE_COLUMN), "취미")

    def test_the_count_is_only_shown_while_the_parent_is_folded(self):
        hobby = self._item(self.hobby)
        index = self.list.table.indexFromItem(hobby, self.list.TITLE_COLUMN)
        hobby.setExpanded(False)
        self.assertEqual(TitleCountDelegate.visible_count(self.list.table, index), 2)
        hobby.setExpanded(True)
        self.assertEqual(
            TitleCountDelegate.visible_count(self.list.table, index), 0,
            "펼쳐 놓았는데 개수가 그대로 남아 있습니다",
        )

    def test_a_note_without_children_shows_no_number(self):
        diary = self._item(self.diary)
        index = self.list.table.indexFromItem(diary, self.list.TITLE_COLUMN)
        self.assertEqual(TitleCountDelegate.visible_count(self.list.table, index), 0)

    # --------------------------------------------------------- 펼침 저장 --
    def test_the_open_state_survives_a_reopen(self):
        self._item(self.hobby).setExpanded(True)
        self.assertEqual(self.list.expanded_ids(), [self.hobby])
        self.panel.refresh()
        self.assertTrue(self._item(self.hobby).isExpanded())

        self._item(self.hobby).setExpanded(False)
        self.panel.refresh()
        self.assertFalse(self._item(self.hobby).isExpanded(), "접어 둔 상태가 사라졌습니다")

    def test_a_fresh_panel_reads_the_saved_state(self):
        self._item(self.hobby).setExpanded(True)
        second = MemoListPanel(self.store)
        try:
            second.set_rows(self.store.notes())
            self.assertTrue(second._item_for(self.hobby).isExpanded())
        finally:
            second.deleteLater()

    # ------------------------------------------------------------- 검색 --
    def test_searching_opens_everything_so_matches_are_visible(self):
        self._item(self.hobby).setExpanded(False)
        self.list.search.setText("드라마")
        self.app.processEvents()
        drama = self._item(self.drama)
        self.assertIsNotNone(drama, "찾은 메모가 목록에 없습니다")
        parent = drama.parent()
        if parent is not None:
            self.assertTrue(parent.isExpanded(), "찾은 메모가 접힌 부모에 가려집니다")

    def test_a_match_whose_parent_is_filtered_out_still_shows(self):
        self.list.search.setText("젤다")
        self.app.processEvents()
        game = self._item(self.game)
        self.assertIsNotNone(game)
        self.assertIsNone(game.parent(), "부모가 검색에서 빠지면 맨 위로 올려야 합니다")

    def test_searching_does_not_overwrite_the_saved_state(self):
        self._item(self.hobby).setExpanded(False)
        saved = str(self.store.setting(self.list.EXPANDED_SETTING, ""))
        self.list.search.setText("드라마")
        self.app.processEvents()
        self.assertEqual(str(self.store.setting(self.list.EXPANDED_SETTING, "")), saved)

    # ------------------------------------------------------------- 선택 --
    def test_select_all_counts_the_children_too(self):
        self.list.table_header.toggle_check_state()
        self.assertEqual(len(self.list.checked_ids()), 4)

    def test_selecting_a_hidden_note_opens_its_parent(self):
        self._item(self.hobby).setExpanded(False)
        self.list.select_id(self.drama)
        self.assertTrue(self._item(self.hobby).isExpanded())

    # ------------------------------------------------------------- 차례 --
    def test_the_dragged_order_is_the_shown_order(self):
        self.store.reorder_notes(self.hobby, [self.game, self.drama])
        self.panel.refresh()
        self.assertEqual(self._titles(self._item(self.hobby)), ["게임", "드라마"])
        self.store.reorder_notes(self.hobby, [self.drama, self.game])
        self.panel.refresh()
        self.assertEqual(self._titles(self._item(self.hobby)), ["드라마", "게임"])

    # ------------------------------------------------------------- 옮김 --
    def test_dropping_a_note_on_another_moves_it_in_the_database(self):
        self.panel.move_note(self.diary, self.hobby, 0)
        self.assertEqual(int(self.store.note(self.diary)["parent_id"]), self.hobby)
        self.assertIn("일기", self._titles(self._item(self.hobby)))

    def test_a_move_that_would_make_a_loop_is_refused(self):
        self.panel.move_note(self.hobby, self.drama, 0)
        self.assertEqual(int(self.store.note(self.hobby)["parent_id"]), TOP_LEVEL_PARENT)
        self.assertIn("옮길 수 없습니다", self.panel.status_label.text())

    def test_moving_a_note_out_to_the_top_level(self):
        self.panel.move_note(self.drama, TOP_LEVEL_PARENT, 0)
        self.assertEqual(int(self.store.note(self.drama)["parent_id"]), TOP_LEVEL_PARENT)
        self.assertIsNone(self._item(self.drama).parent())

    # ----------------------------------------------------------- 휴지통 --
    def test_deleting_a_parent_warns_about_the_children_and_takes_them(self):
        self.list.select_id(self.hobby)
        with patch(
            "alert_notes.panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as question:
            self.panel.delete_selected_notes()
        message = question.call_args[0][2]
        self.assertIn("2건", message, message)
        self.assertEqual({str(row["title"]) for row in self.store.notes()}, {"일기"})


class NarrowListTest(unittest.TestCase):
    """좁은 목록에서 제목이 잘리지 않게 하는 처리."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.plan = self.store.create_note("프로젝트 플래너", "TomaDesk 9월 일정")
        for title in ("주간 회의 준비 메모", "작업 인수인계 정리"):
            self.store.set_note_parent(self.store.create_note(title, "본문"), self.plan)
        self.panel = MemoListPanel(self.store)
        self.panel.show()

    def tearDown(self):
        self.panel.hide()
        self.panel.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.store.close()
        self.temp.cleanup()

    def _lay_out(self, width: int, expanded: bool = True):
        self.panel.resize(width, 330)
        self.panel.set_rows(self.store.notes())
        self.panel._item_for(self.plan).setExpanded(expanded)
        self.panel._resize_table_columns()
        self.app.processEvents()

    def _title_width(self) -> int:
        return self.panel.table.columnWidth(self.panel.TITLE_COLUMN)

    def test_the_headers_are_short_at_every_width(self):
        self._lay_out(760)
        self.assertEqual(self.panel.HEADERS, ["", "제목", "카테고리", "수정일"])
        self.assertEqual(
            [self.panel.table.headerItem().text(i) for i in range(4)],
            ["", "제목", "카테고리", "수정일"],
            "넓은 창에서도 같은 머리글이라야 합니다",
        )

    def test_a_narrow_list_folds_the_edit_time_column(self):
        self._lay_out(360)
        self.assertTrue(self.panel.is_narrow())
        self.assertTrue(self.panel.table.isColumnHidden(self.panel.FOLDABLE_COLUMN))
        self.assertEqual(self.panel.visible_columns(), [0, 1, 2])

    def test_widening_brings_the_column_back(self):
        self._lay_out(430)
        self._lay_out(760)
        self.assertFalse(self.panel.is_narrow())
        self.assertFalse(self.panel.table.isColumnHidden(self.panel.FOLDABLE_COLUMN))

    def test_the_folded_time_is_kept_in_the_tooltip(self):
        self._lay_out(430)
        item = self.panel._item_for(self.plan)
        self.assertIn("수정", item.toolTip(self.panel.TITLE_COLUMN))

    def test_a_narrow_list_gives_the_title_far_more_room(self):
        self._lay_out(430)
        # 고치기 전에는 72px 였다.  최소한 두 배는 받아야 한다.
        self.assertGreater(self._title_width(), 140, "제목 열이 여전히 좁습니다")

    def test_the_columns_still_fill_the_viewport(self):
        for width in (430, 760):
            self._lay_out(width)
            total = sum(
                self.panel.table.columnWidth(column)
                for column in self.panel.visible_columns()
            )
            self.assertLessEqual(
                abs(total - self.panel.table.viewport().width()), 1,
                f"{width}px 에서 오른쪽에 빈 띠가 남습니다",
            )

    def test_folding_everything_returns_the_borrowed_room(self):
        self._lay_out(760, expanded=True)
        opened = self._title_width()
        self._lay_out(760, expanded=False)
        self.assertLessEqual(
            self._title_width(), opened, "다 접었는데도 제목 열이 넓어진 채입니다",
        )

    def test_a_narrow_list_never_saves_its_widths(self):
        self._lay_out(760)
        saved = str(self.store.setting(self.panel.COLUMN_RATIOS_SETTING, ""))
        self._lay_out(360)
        self.panel._on_section_resized(1, 0, self._title_width())
        self.assertEqual(
            str(self.store.setting(self.panel.COLUMN_RATIOS_SETTING, "")), saved,
            "좁을 때의 폭이 저장되면 다음에 열 하나가 사라진 채로 남습니다",
        )

    def test_the_rows_are_shorter_than_before(self):
        self._lay_out(760)
        self.assertLessEqual(self.panel.ROW_HEIGHT, 36, "줄 높이가 아직 큽니다")
        item = self.panel._item_for(self.plan)
        self.assertLessEqual(self.panel.table.visualItemRect(item).height(), 36)


class ArrowHoverTest(unittest.TestCase):
    """목록 화살표 위에서는 누를 수 있다는 표시가 떠야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.plan = self.store.create_note("프로젝트 플래너", "본문")
        self.child = self.store.create_note("주간 회의", "본문")
        self.alone = self.store.create_note("혼자 메모", "본문")
        self.store.set_note_parent(self.child, self.plan)
        self.panel = MemoListPanel(self.store)
        self.panel.resize(700, 330)
        self.panel.show()
        self.panel.set_rows(self.store.notes())
        self.panel._item_for(self.plan).setExpanded(True)
        self.panel._resize_table_columns()
        self.app.processEvents()

    def tearDown(self):
        self.panel.hide()
        self.panel.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.store.close()
        self.temp.cleanup()

    def _hover(self, point):
        self.panel.table.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, QPointF(point), QPointF(point),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        ))

    def _shape(self):
        return self.panel.table.viewport().cursor().shape()

    def test_the_arrow_shows_a_hand(self):
        item = self.panel._item_for(self.plan)
        self._hover(self.panel.table.arrow_rect(item).center())
        self.assertEqual(self._shape(), Qt.CursorShape.PointingHandCursor)
        self.assertIs(self.panel.table._hover_arrow, item)

    def test_the_title_keeps_the_ordinary_cursor(self):
        item = self.panel._item_for(self.plan)
        self._hover(self.panel.table.arrow_rect(item).center())
        row = self.panel.table.visualItemRect(item)
        self._hover(QPoint(row.right() - 20, row.center().y()))
        self.assertEqual(self._shape(), Qt.CursorShape.ArrowCursor)
        self.assertIsNone(self.panel.table._hover_arrow)

    def test_a_note_without_children_has_no_arrow(self):
        item = self.panel._item_for(self.alone)
        self.assertIsNone(
            self.panel.table.arrow_item_at(self.panel.table.arrow_rect(item).center()),
            "하위가 없는 메모에 화살표 표시가 뜹니다",
        )

    def test_leaving_the_list_puts_the_cursor_back(self):
        item = self.panel._item_for(self.plan)
        self._hover(self.panel.table.arrow_rect(item).center())
        self.panel.table.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertEqual(self._shape(), Qt.CursorShape.ArrowCursor)


class DropTargetTest(unittest.TestCase):
    """끌어다 놓은 자리를 어디로 읽는지."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tree = MemoTree()
        self.tree.setColumnCount(2)
        self.parent_item = QTreeWidgetItem()
        self.parent_item.setData(0, NOTE_ID_ROLE, 10)
        self.child_item = QTreeWidgetItem()
        self.child_item.setData(0, NOTE_ID_ROLE, 11)
        self.parent_item.addChild(self.child_item)
        self.other = QTreeWidgetItem()
        self.other.setData(0, NOTE_ID_ROLE, 20)
        self.tree.addTopLevelItem(self.parent_item)
        self.tree.addTopLevelItem(self.other)

    def tearDown(self):
        self.tree.deleteLater()

    def _target(self, where, item):
        with (
            patch.object(MemoTree, "dropIndicatorPosition", return_value=where),
            patch.object(MemoTree, "itemAt", return_value=item),
        ):
            return self.tree._drop_target(QPoint(0, 0), self.other)

    def test_dropping_on_a_note_puts_it_inside(self):
        where = QAbstractItemView.DropIndicatorPosition.OnItem
        self.assertEqual(self._target(where, self.parent_item), (10, 1))

    def test_dropping_above_a_note_keeps_the_same_level(self):
        where = QAbstractItemView.DropIndicatorPosition.AboveItem
        self.assertEqual(self._target(where, self.child_item), (10, 0))

    def test_dropping_below_a_note_goes_after_it(self):
        where = QAbstractItemView.DropIndicatorPosition.BelowItem
        self.assertEqual(self._target(where, self.child_item), (10, 1))

    def test_dropping_on_empty_space_lifts_it_to_the_top(self):
        where = QAbstractItemView.DropIndicatorPosition.OnViewport
        self.assertEqual(self._target(where, None), (TOP_LEVEL_PARENT, 2))


if __name__ == "__main__":
    unittest.main()
