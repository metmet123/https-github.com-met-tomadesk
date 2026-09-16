"""Real input paths and regressions missed by the original Phase 1-3 tests."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QContextMenuEvent, QMouseEvent, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMenu

from alert_notes.panel import AlertNotesPanel
from alert_notes.rich_memo_edit import (
    HEADING_FOLDED_PREFIX, HEADING_STYLES, PAGE_MARK, RichMemoTextEdit,
)
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def event(kind, point, buttons, modifiers=Qt.KeyboardModifier.NoModifier):
    button = Qt.MouseButton.LeftButton
    return QMouseEvent(kind, QPointF(point), QPointF(point), button, buttons,
                       modifiers)


def block_texts(editor):
    return [block.text() for block in editor._iter_blocks()]


class MemoRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.widgets = []

    def tearDown(self):
        for widget in reversed(self.widgets):
            destroy_widget(widget, self.app)
        self.store.close()
        self.temp.cleanup()

    def editor(self, content=""):
        editor = RichMemoTextEdit(self.store)
        editor.resize(620, 400)
        editor.setPlainText(content)
        editor.show()
        self.app.processEvents()
        self.widgets.append(editor)
        return editor

    def test_page_click_opens_but_drag_to_another_page_selects_text(self):
        editor = self.editor()
        editor.setHtml(
            f'<p><a href="toma-note://101">{PAGE_MARK}첫쪽</a></p>'
            f'<p><a href="toma-note://102">{PAGE_MARK}둘째</a></p>'
        )
        opened = []
        editor.page_open_requested.connect(opened.append)
        first = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(0))).center()
        second = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(1))).center()
        editor.mousePressEvent(event(QMouseEvent.Type.MouseButtonPress, first,
                                     Qt.MouseButton.LeftButton))
        editor.mouseMoveEvent(event(QMouseEvent.Type.MouseMove, second,
                                    Qt.MouseButton.LeftButton))
        editor.mouseReleaseEvent(event(QMouseEvent.Type.MouseButtonRelease, second,
                                       Qt.MouseButton.NoButton))
        self.assertEqual(opened, [])
        self.assertTrue(editor.textCursor().hasSelection())
        editor.mousePressEvent(event(QMouseEvent.Type.MouseButtonPress, first,
                                     Qt.MouseButton.LeftButton))
        editor.mouseReleaseEvent(event(QMouseEvent.Type.MouseButtonRelease, first,
                                       Qt.MouseButton.NoButton))
        self.assertEqual(opened, [101])

    def test_viewport_dispatch_preserves_page_drag_selection(self):
        editor = self.editor()
        editor.setHtml(
            f'<p><a href="toma-note://101">{PAGE_MARK}첫쪽</a></p>'
            f'<p><a href="toma-note://102">{PAGE_MARK}둘째</a></p>'
        )
        opened = []
        editor.page_open_requested.connect(opened.append)
        first = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(0))).center()
        second = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(1))).center()
        for kind, point, buttons in (
            (QMouseEvent.Type.MouseButtonPress, first, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseMove, second, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseButtonRelease, second, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(editor.viewport(), event(kind, point, buttons))
        self.assertEqual(opened, [])
        self.assertTrue(editor.textCursor().hasSelection())

    def test_blank_heading_levels_type_and_round_trip_with_fold(self):
        for level, (size, _spacing, _top, _bottom) in HEADING_STYLES.items():
            with self.subTest(level=level):
                editor = self.editor()
                editor.apply_heading(level)
                editor.insertPlainText(f"제목{level}")
                QTest.keyClick(editor, Qt.Key.Key_Return)
                editor.insertPlainText("내용")
                first = editor.document().findBlockByNumber(0)
                probe = QTextCursor(first)
                probe.movePosition(QTextCursor.MoveOperation.NextCharacter,
                                   QTextCursor.MoveMode.KeepAnchor)
                self.assertEqual(probe.charFormat().fontPointSize(), size)
                self.assertEqual(first.blockFormat().headingLevel(), level)
                editor.fold_heading(first)
                saved = editor.content()
                reopened = self.editor()
                reopened.set_content(saved)
                first = reopened.document().findBlockByNumber(0)
                self.assertEqual(reopened.heading_level(first), level)
                self.assertTrue(reopened._heading_is_folded(first))
                self.assertFalse(first.text().startswith(HEADING_FOLDED_PREFIX))
                self.assertFalse(reopened.document().findBlockByNumber(1).isVisible())
                self.assertTrue(reopened.fold_heading(first))
                self.assertTrue(reopened.document().findBlockByNumber(1).isVisible())

    def test_single_and_noncontiguous_toggle_group_undo_is_one_step(self):
        for selected in ((1,), (1, 3)):
            with self.subTest(selected=selected):
                editor = self.editor("가\n나\n다\n라")
                before = block_texts(editor)
                for index in selected:
                    editor.block_selection.toggle(
                        editor.document().findBlockByNumber(index), include_family=False,
                    )
                self.assertTrue(editor.block_commands.execute("group_toggle"))
                self.assertTrue(any(value.startswith("▾ ") for value in block_texts(editor)))
                editor.undo()
                self.assertEqual(block_texts(editor), before)
                editor.redo()
                self.assertEqual(sum(value.startswith("▾ ") for value in block_texts(editor)),
                                 len(selected))

    def test_old_default_size_folded_heading_is_recovered_on_open(self):
        editor = self.editor(f"{HEADING_FOLDED_PREFIX}예전 제목\n내용")
        first = editor.document().begin()
        fmt = first.blockFormat()
        fmt.setLeftMargin(18)
        fmt.setTopMargin(12)
        fmt.setBottomMargin(6)
        QTextCursor(first).setBlockFormat(fmt)
        reopened = self.editor()
        reopened.set_content(editor.content())
        heading = reopened.document().begin()
        self.assertEqual(reopened.heading_level(heading), 1)
        self.assertEqual(heading.blockFormat().headingLevel(), 1)
        probe = QTextCursor(heading)
        probe.setPosition(heading.position() + len(HEADING_FOLDED_PREFIX))
        probe.movePosition(QTextCursor.MoveOperation.NextCharacter,
                           QTextCursor.MoveMode.KeepAnchor)
        self.assertEqual(probe.charFormat().fontPointSize(), 22)
        self.assertFalse(heading.next().isVisible())
        self.assertTrue(reopened.fold_heading(heading))
        self.assertTrue(heading.next().isVisible())
        baseline = reopened.toPlainText()
        reopened.insertPlainText("추가")
        reopened.undo()
        self.assertEqual(reopened.toPlainText(), baseline)
        self.assertEqual(reopened.document().begin().blockFormat().headingLevel(), 1)

    def test_selection_bar_is_below_viewport_and_plain_click_clears_it(self):
        editor = self.editor("첫째\n둘째")
        editor.block_selection.select_only(editor.document().begin(), include_family=False)
        self.app.processEvents()
        self.assertTrue(editor.block_action_bar.isVisible())
        self.assertGreaterEqual(editor.block_action_bar.geometry().top(),
                                editor.viewport().geometry().bottom())
        point = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(1))).center()
        editor.mousePressEvent(event(QMouseEvent.Type.MouseButtonPress, point,
                                     Qt.MouseButton.LeftButton))
        editor.mouseReleaseEvent(event(QMouseEvent.Type.MouseButtonRelease, point,
                                       Qt.MouseButton.NoButton))
        self.assertEqual(editor.block_selection.count(), 0)
        self.assertFalse(editor.block_action_bar.isVisible())

    def test_alt_drag_additive_then_plain_character_drag_changes_mode(self):
        editor = self.editor("가나다라\n둘째 줄\n셋째 줄\n넷째 줄")
        first = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(0))).center()
        third = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(2))).center()
        alt = Qt.KeyboardModifier.AltModifier
        editor.mousePressEvent(event(QMouseEvent.Type.MouseButtonPress, first,
                                     Qt.MouseButton.LeftButton, alt))
        editor.mouseMoveEvent(event(QMouseEvent.Type.MouseMove, third,
                                    Qt.MouseButton.LeftButton, alt))
        editor.mouseReleaseEvent(event(QMouseEvent.Type.MouseButtonRelease, third,
                                       Qt.MouseButton.NoButton, alt))
        self.assertEqual(editor.block_selection.count(), 3)
        fourth = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(3))).center()
        editor.mousePressEvent(event(QMouseEvent.Type.MouseButtonPress, fourth,
                                     Qt.MouseButton.LeftButton, alt))
        editor.mouseReleaseEvent(event(QMouseEvent.Type.MouseButtonRelease, fourth,
                                       Qt.MouseButton.NoButton, alt))
        self.assertEqual(editor.block_selection.count(), 4)

        left = QTextCursor(editor.document())
        left.setPosition(1)
        right = QTextCursor(editor.document())
        right.setPosition(3)
        start = editor.cursorRect(left).center()
        end = editor.cursorRect(right).center()
        editor.mousePressEvent(event(QMouseEvent.Type.MouseButtonPress, start,
                                     Qt.MouseButton.LeftButton))
        editor.mouseMoveEvent(event(QMouseEvent.Type.MouseMove, end,
                                    Qt.MouseButton.LeftButton))
        editor.mouseReleaseEvent(event(QMouseEvent.Type.MouseButtonRelease, end,
                                       Qt.MouseButton.NoButton))
        self.assertEqual(editor.block_selection.count(), 0)
        self.assertEqual(editor.textCursor().selectedText(), "나다")

    def test_alt_c_feedback_and_real_escape_shortcut(self):
        editor = self.editor("가나다")
        with patch("alert_notes.rich_memo_edit.QToolTip.showText") as feedback:
            cursor = editor.textCursor()
            cursor.setPosition(0)
            cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
            editor.setTextCursor(cursor)
            editor._copy_or_apply_character_format()
            self.assertEqual(feedback.call_args.args[1], "복사된 서식이 없습니다")
            cursor.clearSelection()
            editor.setTextCursor(cursor)
            editor._copy_or_apply_character_format()
            self.assertEqual(feedback.call_args.args[1], "서식 복사됨")
            cursor = editor.textCursor()
            cursor.setPosition(0)
            cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
            editor.setTextCursor(cursor)
            editor._copy_or_apply_character_format()
            self.assertEqual(feedback.call_args.args[1], "서식 적용됨")

        panel = AlertNotesPanel(self.store)
        panel.resize(1100, 750)
        panel.show()
        self.widgets.append(panel)
        body = panel.editor.content_edit
        body.block_selection.select_only(body.document().begin(), include_family=False)
        body.setFocus()
        self.app.processEvents()
        QTest.keyClick(body, Qt.Key.Key_Escape)
        self.assertEqual(body.block_selection.count(), 0)

    def test_right_click_switches_block_target_and_menu_avoids_editor(self):
        editor = self.editor("첫째\n둘째\n셋째")
        editor.block_selection.toggle(editor.document().findBlockByNumber(0),
                                      include_family=False)
        editor.block_selection.toggle(editor.document().findBlockByNumber(2),
                                      include_family=False)
        point = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(0))).center()
        with patch.object(QMenu, "exec", return_value=None) as execute:
            editor.contextMenuEvent(QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse, point, editor.mapToGlobal(point)))
            self.assertEqual(editor.block_selection.count(), 2)
            outside = execute.call_args.args[0]
            editor_right = editor.mapToGlobal(editor.rect().topRight()).x()
            self.assertGreater(outside.x(), editor_right)

        middle = editor.cursorRect(QTextCursor(editor.document().findBlockByNumber(1))).center()
        with patch.object(QMenu, "exec", return_value=None):
            editor.contextMenuEvent(QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse, middle, editor.mapToGlobal(middle)))
        self.assertEqual([block.text() for block in editor.block_selection.blocks()], ["둘째"])

    def test_heading_body_and_unlink_clear_persisted_heading_level(self):
        editor = self.editor("제목\n내용")
        editor.setTextCursor(QTextCursor(editor.document().begin()))
        editor.apply_heading1()
        self.assertEqual(editor.document().begin().blockFormat().headingLevel(), 1)
        editor.block_selection.select_only(editor.document().begin(), include_family=False)
        self.assertTrue(editor.block_commands.execute("body"))
        self.assertEqual(editor.document().begin().blockFormat().headingLevel(), 0)
        editor.apply_heading2()
        editor.block_selection.clear()
        editor.block_selection.select_only(editor.document().begin(), include_family=False)
        self.assertTrue(editor.block_commands.execute("unlink_features"))
        self.assertEqual(editor.document().begin().blockFormat().headingLevel(), 0)

    def test_noncontiguous_move_and_delete_are_one_undo(self):
        for command, expected in (
            ("move_up", ["나", "가", "라", "다", "마"]),
            ("move_down", ["가", "다", "나", "마", "라"]),
            ("delete", ["가", "다", "마"]),
        ):
            with self.subTest(command=command):
                editor = self.editor("가\n나\n다\n라\n마")
                before = block_texts(editor)
                for index in (1, 3):
                    editor.block_selection.toggle(
                        editor.document().findBlockByNumber(index), include_family=False,
                    )
                self.assertTrue(editor.block_commands.execute(command))
                self.assertEqual(block_texts(editor), expected)
                editor.undo()
                self.assertEqual(block_texts(editor), before)


if __name__ == "__main__":
    unittest.main()
