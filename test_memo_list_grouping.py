import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from alert_notes.memo_list import MemoListPanel
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore, TOP_LEVEL_PARENT
from qt_test_support import close_alert_panel, destroy_widget


class MemoListGroupingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.ids = [
            self.store.create_note("[TD]메모기능 개선 계획"),
            self.store.create_note("[TD]새 메모"),
            self.store.create_note("[TD] 완료"),
            self.store.create_note("다른 메모"),
        ]
        self.panel = MemoListPanel(self.store)
        self.panel.resize(700, 520)
        self.panel.set_rows(self.store.notes())
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_shift_click_checks_the_visible_range(self):
        items = [self.panel.table.topLevelItem(index) for index in range(3)]
        QTest.mouseClick(
            self.panel.table.viewport(), Qt.MouseButton.LeftButton,
            pos=self.panel.table.visualItemRect(items[0]).center(),
        )
        QTest.mouseClick(
            self.panel.table.viewport(), Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            self.panel.table.visualItemRect(items[2]).center(),
        )
        self.assertEqual(len(self.panel.checked_ids()), 3)
        self.assertTrue(self.panel.group_button.isVisible())

    def test_group_button_suggests_the_common_bracket_prefix(self):
        requested = []
        self.panel.group_requested.connect(lambda ids, title: requested.append((ids, title)))
        for note_id in self.ids[:3]:
            self.panel._item_for(note_id).setCheckState(0, Qt.CheckState.Checked)
        self.panel.group_button.click()
        self.assertEqual(set(requested[0][0]), set(self.ids[:3]))
        self.assertEqual(requested[0][1], "[TD]")

    def test_repeated_shift_keeps_anchor_and_shrinks_range(self):
        tree = self.panel.table
        items = [tree.topLevelItem(i) for i in range(4)]
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(items[0]).center())
        for endpoint, count in ((3, 4), (1, 2), (2, 3)):
            QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                             tree.visualItemRect(items[endpoint]).center())
            self.assertEqual(len(self.panel.checked_ids()), count)

    def test_collapsed_children_are_not_shift_selected(self):
        child = self.store.create_child_note(self.ids[0], "숨긴 하위")
        self.panel.set_rows(self.store.notes())
        tree = self.panel.table
        parent = self.panel._item_for(self.ids[0])
        parent.setExpanded(False)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(parent).center())
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                         tree.visualItemRect(tree.topLevelItem(3)).center())
        self.assertNotIn(child, self.panel.checked_ids())

    def test_other_chord_does_not_fold_and_focus_loss_cancels(self):
        from PyQt6.QtCore import QEvent
        self.store.create_child_note(self.ids[0], "하위")
        self.panel.set_rows(self.store.notes())
        tree = self.panel.table
        item = self.panel._item_for(self.ids[0])
        tree.setCurrentItem(item)
        item.setExpanded(False)
        for cancel in (False, True):
            QTest.keyPress(tree, Qt.Key.Key_Control)
            QTest.keyPress(tree, Qt.Key.Key_Shift, Qt.KeyboardModifier.ControlModifier)
            if cancel:
                QApplication.sendEvent(tree, QEvent(QEvent.Type.FocusOut))
            else:
                QApplication.sendEvent(tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_K,
                    Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
            QTest.keyRelease(tree, Qt.Key.Key_Shift, Qt.KeyboardModifier.ControlModifier)
            QTest.keyRelease(tree, Qt.Key.Key_Control)
            self.assertFalse(item.isExpanded())

    def test_filtered_move_is_blocked_with_reason(self):
        tree = self.panel.table
        tree.setCurrentItem(tree.topLevelItem(0))
        tree.setDragEnabled(False)
        moved, reasons = [], []
        tree.reorder_requested.connect(lambda *args: moved.append(args))
        tree.reorder_blocked.connect(reasons.append)
        QTest.keyClick(tree, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(moved, [])
        self.assertTrue(reasons)

    def test_multiple_move_preserves_relative_order(self):
        tree = self.panel.table
        items = [tree.topLevelItem(i) for i in range(4)]
        ids = [int(i.data(0, Qt.ItemDataRole.UserRole)) for i in items]
        for i in items[:2]:
            i.setCheckState(0, Qt.CheckState.Checked)
        tree.setCurrentItem(items[0])
        moved = []
        tree.siblings_reordered.connect(lambda parent, order: moved.append((parent, order)))
        QTest.keyClick(tree, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(moved, [(TOP_LEVEL_PARENT, [ids[2], ids[0], ids[1], ids[3]])])

    def test_pinned_boundary_blocks_move(self):
        from alert_notes.memo_list import PINNED_ROLE
        tree = self.panel.table
        first = tree.topLevelItem(0)
        first.setData(0, PINNED_ROLE, True)
        tree.setCurrentItem(first)
        moved = []
        tree.reorder_requested.connect(lambda *args: moved.append(args))
        QTest.keyClick(tree, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(moved, [])

    def test_cross_parent_dialog_cancel_changes_nothing(self):
        child = self.store.create_child_note(self.ids[0], "하위")
        main = AlertNotesPanel(self.store)
        try:
            before = [dict(r) for r in self.store.notes()]
            with patch("alert_notes.panel.QInputDialog.getItem", return_value=("", False)) as dialog:
                self.assertIsNone(main.group_selected_notes([child, self.ids[1]], "묶음"))
                dialog.assert_called_once()
            self.assertEqual([dict(r) for r in self.store.notes()], before)
        finally:
            close_alert_panel(main, self.app)

    def test_registered_fold_all_shortcut_does_not_fold_twice_on_release(self):
        from PyQt6.QtCore import QEvent
        self.store.create_child_note(self.ids[0], "하위")
        self.panel.set_rows(self.store.notes())
        tree = self.panel.table
        item = self.panel._item_for(self.ids[0])
        tree.setCurrentItem(item)
        item.setExpanded(False)
        QTest.keyPress(tree, Qt.Key.Key_Control)
        QTest.keyPress(tree, Qt.Key.Key_Shift, Qt.KeyboardModifier.ControlModifier)
        QApplication.sendEvent(tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        self.assertTrue(item.isExpanded())
        QTest.keyRelease(tree, Qt.Key.Key_Shift, Qt.KeyboardModifier.ControlModifier)
        QTest.keyRelease(tree, Qt.Key.Key_Control)
        self.assertTrue(item.isExpanded())

    def test_compact_group_action_and_inline_escape(self):
        from PyQt6.QtCore import QPoint, QRect
        from PyQt6.QtWidgets import QLineEdit
        from ui_theme import scaled_stylesheet
        p = self.panel
        p.setStyleSheet(scaled_stylesheet(1.0))
        p.resize(480, 667)
        for value in self.ids[:3]:
            p._item_for(value).setCheckState(0, Qt.CheckState.Checked)
        self.app.processEvents()
        rect = QRect(p.group_button.mapTo(p, QPoint()), p.group_button.size())
        self.assertTrue(p.rect().contains(rect))
        self.assertTrue(p.group_button.isVisible())
        folder = os.environ.get("TOMADESK_STAGE34_CAPTURES")
        if folder:
            self.assertTrue(p.grab().save(str(Path(folder) / "memo-selected.png")))
        group = self.store.group_notes(self.ids[:3], "[TD]")
        p.set_rows(self.store.notes())
        p._item_for(group).setExpanded(True)
        p.begin_inline_rename(group)
        self.app.processEvents()
        editor = p.table.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.setText("취소할 제목")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(self.store.note(group)["title"], "[TD]")
        self.assertIsNone(p._inline_editing_id)
        if folder:
            self.assertTrue(p.grab().save(str(Path(folder) / "memo-grouped.png")))
        print(f"MEMO_STAGE34 size={p.width()}x{p.height()} group_action={rect.getRect()}")

    def test_cross_parent_group_requires_destination_and_is_atomic(self):
        child = self.store.create_child_note(self.ids[0], "하위")
        before = [dict(r) for r in self.store.notes()]
        with self.assertRaises(ValueError):
            self.store.group_notes([child, self.ids[1]])
        self.assertEqual([dict(r) for r in self.store.notes()], before)
        with patch.object(self.store, "_write_sort_order", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                self.store.group_notes([child, self.ids[1]], parent_id=TOP_LEVEL_PARENT)
        self.assertEqual([dict(r) for r in self.store.notes()], before)
        group = self.store.group_notes([child, self.ids[1]], parent_id=TOP_LEVEL_PARENT)
        self.assertEqual([int(r["id"]) for r in self.store.child_notes(group)], [child, self.ids[1]])

    def test_multiple_reorder_keeps_checked_current_expansion_and_scroll(self):
        destroy_widget(self.panel, self.app)
        self.panel = None
        child = self.store.create_child_note(self.ids[0], "하위")
        main = AlertNotesPanel(self.store)
        try:
            main.show()
            self.app.processEvents()
            tree = main.list_panel.table
            before = [int(r["id"]) for r in self.store.child_notes(TOP_LEVEL_PARENT)]
            parent = main.list_panel._item_for(self.ids[0])
            parent.setExpanded(True)
            tree.setCurrentItem(parent)
            for value in before[:2]:
                main.list_panel._item_for(value).setCheckState(0, Qt.CheckState.Checked)
            scroll = tree.verticalScrollBar().value()
            QTest.keyClick(tree, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
            self.app.processEvents()
            self.assertEqual([int(r["id"]) for r in self.store.child_notes(0)],
                             [before[2], before[0], before[1], before[3]])
            self.assertEqual(set(main.list_panel.checked_ids()), set(before[:2]))
            self.assertTrue(main.list_panel._item_for(self.ids[0]).isExpanded())
            self.assertEqual(tree.currentItem().data(0, Qt.ItemDataRole.UserRole), self.ids[0])
            self.assertEqual(tree.verticalScrollBar().value(), scroll)
            self.assertEqual(self.store.note(child)["parent_id"], self.ids[0])
        finally:
            close_alert_panel(main, self.app)

    def test_modifier_only_ctrl_shift_toggles_the_current_parent(self):
        child = self.store.create_child_note(self.ids[0], "하위")
        self.panel.set_rows(self.store.notes())
        parent = self.panel._item_for(self.ids[0])
        self.assertIsNotNone(self.panel._item_for(child))
        self.panel.table.setCurrentItem(parent)
        parent.setExpanded(False)
        QTest.keyPress(self.panel.table, Qt.Key.Key_Control)
        QTest.keyPress(
            self.panel.table, Qt.Key.Key_Shift,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyRelease(
            self.panel.table, Qt.Key.Key_Shift,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyRelease(self.panel.table, Qt.Key.Key_Control)
        self.assertTrue(parent.isExpanded())

    def test_ctrl_down_requests_one_sibling_step(self):
        moved = []
        self.panel.note_moved.connect(lambda *args: moved.append(args))
        first = self.panel.table.topLevelItem(0)
        self.panel.table.setCurrentItem(first)
        QApplication.sendEvent(
            self.panel.table,
            QKeyEvent(
                QKeyEvent.Type.KeyPress, Qt.Key.Key_Down,
                Qt.KeyboardModifier.ControlModifier,
            ),
        )
        self.assertEqual(moved, [(int(first.data(0, Qt.ItemDataRole.UserRole)), TOP_LEVEL_PARENT, 1)])

    def test_grouping_preserves_category_and_avoids_double_moving_children(self):
        category_id = int(self.store.categories()[0]["id"])
        for note_id in self.ids[:3]:
            self.store.set_note_category(note_id, category_id)
        child = self.store.create_child_note(self.ids[0], "이미 하위")
        group_id = self.store.group_notes([self.ids[0], child, self.ids[1], self.ids[2]], "[TD]")
        group = self.store.note(group_id)
        self.assertEqual(group["category_id"], category_id)
        self.assertEqual(group["parent_id"], TOP_LEVEL_PARENT)
        children = [int(row["id"]) for row in self.store.child_notes(group_id)]
        self.assertEqual(children, self.ids[:3])
        self.assertEqual(self.store.note(child)["parent_id"], self.ids[0])

    def test_full_panel_groups_and_saves_inline_parent_title(self):
        destroy_widget(self.panel, self.app)
        self.panel = None
        main = AlertNotesPanel(self.store)
        try:
            main.show()
            self.app.processEvents()
            group_id = main.group_selected_notes(self.ids[:3], "[TD]")
            self.assertIsNotNone(group_id)
            item = main.list_panel._item_for(group_id)
            self.assertTrue(item.isExpanded())
            item.setText(main.list_panel.TITLE_COLUMN, "[TD] 업무 묶음")
            self.app.processEvents()
            self.assertEqual(self.store.note(group_id)["title"], "[TD] 업무 묶음")
            self.assertEqual(
                [int(row["parent_id"]) for row in (self.store.note(value) for value in self.ids[:3])],
                [group_id, group_id, group_id],
            )
        finally:
            close_alert_panel(main, self.app)

    def test_full_panel_ctrl_down_persists_the_new_sibling_order(self):
        destroy_widget(self.panel, self.app)
        self.panel = None
        main = AlertNotesPanel(self.store)
        try:
            main.show()
            self.app.processEvents()
            before = [int(row["id"]) for row in self.store.child_notes(TOP_LEVEL_PARENT)]
            current = main.list_panel._item_for(before[0])
            main.list_panel.table.setCurrentItem(current)
            QApplication.sendEvent(
                main.list_panel.table,
                QKeyEvent(
                    QKeyEvent.Type.KeyPress, Qt.Key.Key_Down,
                    Qt.KeyboardModifier.ControlModifier,
                ),
            )
            self.app.processEvents()
            after = [int(row["id"]) for row in self.store.child_notes(TOP_LEVEL_PARENT)]
            self.assertEqual(after[:2], [before[1], before[0]])
            self.assertEqual(
                int(main.list_panel.table.currentItem().data(0, Qt.ItemDataRole.UserRole)),
                before[0],
            )
        finally:
            close_alert_panel(main, self.app)


if __name__ == "__main__":
    unittest.main()
