"""Focused, disposable-data checks for noncontiguous memo selection and F11."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QTextCharFormat, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionSpinBox
from PyQt6.QtWidgets import QToolButton

from alert_notes.panel import AlertNotesPanel
from alert_notes.rich_memo_edit import RichMemoTextEdit
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


def selected(document, start, end):
    cursor = QTextCursor(document)
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    return cursor


def mouse(kind, point, buttons, modifiers):
    return QMouseEvent(kind, QPointF(point), QPointF(point), Qt.MouseButton.LeftButton,
                       buttons, modifiers)


class CharacterRangeTest(unittest.TestCase):
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

    def editor(self, text="abcdefghij"):
        editor = RichMemoTextEdit(self.store)
        editor.resize(600, 400)
        editor.setPlainText(text)
        editor.show()
        self.app.processEvents()
        self.widgets.append(editor)
        return editor

    def test_range_merge_keyboard_and_single_undo_for_format(self):
        editor = self.editor()
        editor.character_selection.add_cursor(selected(editor.document(), 1, 3))
        editor.character_selection.add_cursor(selected(editor.document(), 6, 8))
        editor.character_selection.add_cursor(selected(editor.document(), 2, 4))
        self.assertEqual(editor.character_selection.ranges(), [(1, 4), (6, 8)])
        self.assertTrue(editor.character_action_bar.isVisible())
        before = editor.toPlainText()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#b91c1c"))
        editor.apply_character_format(fmt)
        self.assertEqual(editor.toPlainText(), before)
        self.assertEqual(selected(editor.document(), 1, 2).charFormat().foreground().color(),
                         QColor("#b91c1c"))
        self.assertNotEqual(selected(editor.document(), 4, 5).charFormat().foreground().color(),
                            QColor("#b91c1c"))
        editor.undo()
        self.assertNotEqual(selected(editor.document(), 1, 2).charFormat().foreground().color(),
                            QColor("#b91c1c"))
        editor.redo()
        self.assertEqual(selected(editor.document(), 6, 7).charFormat().foreground().color(),
                         QColor("#b91c1c"))
        editor.setTextCursor(selected(editor.document(), 8, 10))
        self.assertTrue(editor.add_current_character_selection())
        self.assertEqual(editor.character_selection.ranges(), [(1, 4), (6, 10)])

    def test_ctrl_drag_adds_range_and_plain_click_clears(self):
        editor = self.editor("first line\nsecond line")
        first = selected(editor.document(), 0, 0)
        first.setPosition(0)
        end = selected(editor.document(), 6, 6)
        end.setPosition(6)
        a = editor.cursorRect(first).center()
        b = editor.cursorRect(end).center()
        ctrl = Qt.KeyboardModifier.ControlModifier
        for kind, point, buttons in (
            (QMouseEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseMove, b, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseButtonRelease, b, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(editor.viewport(), mouse(kind, point, buttons, ctrl))
        self.assertEqual(editor.character_selection.count(), 1)
        second = editor.document().findBlockByNumber(1)
        c = editor.cursorRect(QTextCursor(second)).center()
        d_cursor = QTextCursor(second)
        d_cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, n=6)
        d = editor.cursorRect(d_cursor).center()
        for kind, point, buttons in (
            (QMouseEvent.Type.MouseButtonPress, c, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseMove, d, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseButtonRelease, d, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(editor.viewport(), mouse(kind, point, buttons, ctrl))
        self.assertEqual(editor.character_selection.count(), 2)
        QApplication.sendEvent(editor.viewport(), mouse(
            QMouseEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ))
        self.assertEqual(editor.character_selection.count(), 0)

    def test_short_ctrl_click_keeps_page_link_and_plain_caret(self):
        editor = self.editor()
        editor.setHtml('<p><a href="toma-note://101">📄 페이지</a></p><p>일반 글자</p>')
        opened = []
        editor.page_open_requested.connect(opened.append)
        ctrl = Qt.KeyboardModifier.ControlModifier
        page = editor.cursorRect(QTextCursor(editor.document().firstBlock())).center()
        for kind, buttons in (
            (QMouseEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(editor.viewport(), mouse(kind, page, buttons, ctrl))
        self.assertEqual(opened, [101])
        plain = editor.document().findBlockByNumber(1)
        target = QTextCursor(plain)
        target.movePosition(QTextCursor.MoveOperation.NextCharacter, n=2)
        point = editor.cursorRect(target).center()
        for kind, buttons in (
            (QMouseEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(editor.viewport(), mouse(kind, point, buttons, ctrl))
        self.assertEqual(editor.textCursor().position(),
                         editor.cursorForPosition(point).position())
        self.assertEqual(editor.character_selection.count(), 0)

    def test_size_step_stops_after_release_and_keeps_spinbox_focus(self):
        panel = AlertNotesPanel(self.store)
        panel.resize(1100, 780)
        panel.show()
        self.app.processEvents()
        self.widgets.append(panel)
        editor = panel.editor.content_edit
        editor.setPlainText("first second third")
        editor.character_selection.add_cursor(selected(editor.document(), 0, 5))
        editor.character_selection.add_cursor(selected(editor.document(), 13, 18))
        box = panel.editor.format_toolbar.size_box
        box.setFocus()
        self.app.processEvents()
        self.assertTrue(box.hasFocus(), f"initial focus={QApplication.focusWidget()}")
        start = box.value()
        # 크기 칸에는 위아래 화살표가 없다(2차 수정 Q6).  ↑ 키로 단계를 올리고,
        # 손을 뗀 뒤에는 더 바뀌지 않는지 본다.
        values = []
        box.valueChanged.connect(values.append)
        QTest.keyClick(box, Qt.Key.Key_Up)
        QTest.keyClick(box, Qt.Key.Key_Up)
        self.assertTrue(box.hasFocus(), f"key focus={QApplication.focusWidget()}")
        self.app.processEvents()
        released = box.value()
        self.assertGreater(released, start)
        self.assertTrue(box.hasFocus() or box.isAncestorOf(QApplication.focusWidget()),
                        f"focus={QApplication.focusWidget()} box={box} values={values}")
        self.assertTrue(values)
        QTest.qWait(450)
        self.assertEqual(box.value(), released)
        self.assertEqual(values[-1], released)
        self.assertEqual(selected(editor.document(), 0, 1).charFormat().fontPointSize(), released)
        self.assertEqual(selected(editor.document(), 13, 14).charFormat().fontPointSize(), released)
        self.assertNotEqual(selected(editor.document(), 6, 7).charFormat().fontPointSize(), released)
        box.lineEdit().selectAll()
        QTest.keyClicks(box.lineEdit(), "15")
        self.app.processEvents()
        self.assertEqual(box.value(), 15)
        self.assertTrue(box.hasFocus() or box.isAncestorOf(QApplication.focusWidget()))

    def test_reverse_range_and_narrow_action_bar(self):
        editor = self.editor("first line\nsecond line")
        reverse = QTextCursor(editor.document())
        reverse.setPosition(15)
        reverse.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
        self.assertTrue(editor.character_selection.add_cursor(reverse))
        self.assertEqual(editor.character_selection.ranges(), [(2, 15)])
        editor.resize(240, 350)
        self.app.processEvents()
        bar = editor.character_action_bar
        self.assertTrue(bar.isVisible())
        self.assertEqual(bar.width(), editor.width() - 2 * editor.frameWidth())
        self.assertTrue(all(button.geometry().right() <= bar.width()
                            for button in bar.findChildren(QToolButton)))

    def test_unlink_only_selected_anchor_text(self):
        editor = self.editor()
        editor.setHtml('<p><a href="https://example.com">abcdef</a> tail</p>')
        editor.character_selection.add_cursor(selected(editor.document(), 1, 3))
        editor.character_selection.add_cursor(selected(editor.document(), 4, 6))
        self.assertTrue(editor.unlink_selected_character_ranges())
        self.assertTrue(selected(editor.document(), 0, 1).charFormat().isAnchor())
        self.assertFalse(selected(editor.document(), 1, 2).charFormat().isAnchor())
        self.assertTrue(selected(editor.document(), 3, 4).charFormat().isAnchor())
        self.assertFalse(selected(editor.document(), 4, 5).charFormat().isAnchor())
        editor.undo()
        self.assertTrue(selected(editor.document(), 1, 2).charFormat().isAnchor())
        self.assertTrue(selected(editor.document(), 4, 5).charFormat().isAnchor())
        editor.character_action_bar.findChildren(QToolButton)[0].click()
        self.assertFalse(selected(editor.document(), 1, 2).charFormat().isAnchor())

    def test_inline_unlink_does_not_unembed_a_page(self):
        parent = self.store.create_note("부모")
        page = self.store.create_child_note(parent, "페이지", embedded=True)
        editor = self.editor()
        editor.setHtml(
            f'<p><a href="toma-note://{page}">📄 페이지</a></p>'
            '<p><a href="https://example.com">일반 링크</a></p>'
        )
        editor.character_selection.add_cursor(selected(
            editor.document(), 0, editor.document().characterCount() - 1,
        ))
        self.assertTrue(editor.unlink_selected_character_ranges())
        first = editor.document().firstBlock()
        self.assertEqual(editor.page_id_of_block(first), page)
        self.assertTrue(int(self.store.note(page)["embedded"]))
        second = first.next()
        self.assertFalse(selected(editor.document(), second.position(),
                                  second.position() + 1).charFormat().isAnchor())

    def test_keyboard_addition_and_structural_commands_stay_separate(self):
        panel = AlertNotesPanel(self.store)
        panel.resize(1100, 780)
        panel.show()
        self.app.processEvents()
        self.widgets.append(panel)
        editor = panel.editor.content_edit
        editor.setPlainText("one two three")
        editor.setTextCursor(selected(editor.document(), 0, 3))
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key.Key_M,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(editor.character_selection.ranges(), [(0, 3)])
        self.assertFalse(panel.editor.format_toolbar.bullet_button.isEnabled())
        self.assertFalse(editor.block_commands.execute("delete"))
        editor.apply_heading(1)
        editor.toggle_bullet_list()
        self.assertFalse(editor.apply_line_spacing(1.5))
        self.assertEqual(editor.heading_level(editor.document().firstBlock()), 0)
        self.assertIsNone(editor.textCursor().currentList())
        self.assertEqual(editor.toPlainText(), "one two three")
        panel.editor.format_toolbar.apply_color(QColor("#2563eb"))
        self.assertEqual(selected(editor.document(), 0, 1).charFormat().foreground().color(),
                         QColor("#2563eb"))
        self.assertNotEqual(selected(editor.document(), 4, 5).charFormat().foreground().color(),
                            QColor("#2563eb"))
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.assertEqual(editor.character_selection.count(), 0)
        self.assertTrue(panel.editor.format_toolbar.bullet_button.isEnabled())

    def test_fullscreen_reclaims_body_height_and_restores_controls(self):
        panel = AlertNotesPanel(self.store)
        panel.resize(1150, 800)
        panel.show()
        self.app.processEvents()
        self.widgets.append(panel)
        body = panel.editor.content_edit
        normal = body.height()
        changes = []
        panel.editor_fullscreen_changed.connect(changes.append)
        panel.toggle_editor_fullscreen(True)
        self.app.processEvents()
        self.app.processEvents()
        # 상위 메모는 위치 줄이 원래 없어서(카테고리는 제목 옆) 되찾는 높이는
        # 여백만큼이다.  줄어들지 않고 늘어나기만 하면 된다.
        self.assertFalse(panel.editor.location_host.isVisible())
        self.assertGreater(body.height() - normal, 0)
        self.assertFalse(panel.status_label.isVisible())
        self.assertTrue(panel.editor.fullscreen_button.isVisible())
        QTest.keyClick(body, Qt.Key.Key_F11)
        self.app.processEvents()
        self.assertFalse(panel.editor_fullscreen)
        self.assertTrue(panel.status_label.isVisible())
        self.assertFalse(panel.list_panel.action_status.isVisible())
        self.assertEqual(changes, [True, False])


if __name__ == "__main__":
    unittest.main()
