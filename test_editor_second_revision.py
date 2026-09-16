"""편집기 머리 영역 2차 수정 계획(10._편집기_2차_수정계획)의 완료 기준.

1차 구현은 위젯 폭만 검사하고 테마를 입히지 않아 실제 창에서 깨졌다.  배치를
보는 검사는 모두 앱 스타일시트(scaled_stylesheet)를 입힌 상태에서 실행한다.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox

from alert_notes.block_identity import is_section_break
from alert_notes.format_preset_strip import preset_sample_icon
from alert_notes.panel import AlertNotesPanel
from alert_notes.rich_memo_edit import INDENT_WIDTH
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel
from ui_theme import scaled_stylesheet


class _PanelCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "memo.db")
        self.note_id = self.store.create_note("개발", "test\n둘째 줄")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def panel(self, editor_width=515, scale=1.0, note_id=None):
        panel = AlertNotesPanel(self.store)
        panel.setStyleSheet(scaled_stylesheet(scale))
        panel.resize(max(1080, editor_width + 560), 820)
        panel.update_responsive_layout(panel.width())
        panel.show()
        panel.show_note(note_id or self.note_id)
        if scale != 1.0:
            panel.apply_ui_scale(scale)
        panel.editor.setFixedWidth(editor_width)
        self.app.processEvents()
        return panel

    def assert_inside(self, parent, widgets, label=""):
        for widget in widgets:
            if not widget.isVisible():
                continue
            pos = widget.mapTo(parent, QPoint(0, 0))
            self.assertTrue(
                parent.rect().contains(QRect(pos, widget.size())),
                f"{label} {widget.objectName() or type(widget).__name__} {pos} {widget.size()}",
            )


class TitleRowTest(_PanelCase):
    def test_title_field_stays_104_and_row_order_has_no_gap(self):
        for width in (515, 620, 780):
            with self.subTest(width=width):
                panel = self.panel(width)
                editor = panel.editor
                self.assertEqual(editor.title_edit.width(), 104)
                row = editor.title_row
                order = [row.itemAt(i).widget() for i in range(row.count())
                         if row.itemAt(i).widget() and not row.itemAt(i).widget().isHidden()]
                self.assertIs(order[order.index(editor.title_edit) + 1], editor.category_button)
                self.assertIs(order[order.index(editor.category_button) + 1], editor.import_backup_button)
                self.assertIs(order[order.index(editor.import_backup_button) + 1], editor.fold_current_button)
                self.assertIs(order[order.index(editor.fold_current_button) + 1], editor.fold_all_button)
                # 남는 폭은 줄 맨 끝(마지막 항목 = stretch)에만 생긴다.
                self.assertIsNone(row.itemAt(row.count() - 1).widget())
                gap = editor.import_backup_button.x() - (editor.category_button.x() + editor.category_button.width())
                self.assertLessEqual(gap, row.spacing() + 1)
                self.assert_inside(editor, order, f"{width}px")
                self.assertLessEqual(editor.category_button.width(), editor.CATEGORY_CHIP_MAX_WIDTH)
                close_alert_panel(panel, self.app)

    def test_import_backup_is_icon_with_same_menu(self):
        panel = self.panel()
        button = panel.editor.import_backup_button
        self.assertEqual(button.text(), "")
        self.assertFalse(button.icon().isNull())
        self.assertEqual((button.width(), button.height()), (28, 28))
        self.assertEqual(
            [action.text() for action in button.menu().actions() if not action.isSeparator()],
            ["클립보드 구조 가져오기", "파일 가져오기", "전체 메모 백업", "전체 메모 복원"],
        )
        close_alert_panel(panel, self.app)

    def test_fold_buttons_act_immediately_and_keep_body_focus(self):
        panel = self.panel()
        editor = panel.editor
        body = editor.content_edit
        body.setPlainText("Head\nbody\nHead2\nbody2")
        for number in (0, 2):
            cursor = QTextCursor(body.document().findBlockByNumber(number))
            body.setTextCursor(cursor)
            body.apply_heading2()
        self.app.processEvents()
        editor._sync_fold_buttons()
        self.assertTrue(editor.fold_current_button.isEnabled())
        self.assertIsNone(editor.fold_current_button.menu())
        body.setFocus()
        body.setTextCursor(QTextCursor(body.document().findBlockByNumber(0)))
        with patch.object(QMenu, "popup") as popup, patch.object(QMenu, "exec") as exec_:
            editor.fold_current_button.click()
            self.app.processEvents()
            self.assertEqual(popup.call_count + exec_.call_count, 0)
        self.assertFalse(body.document().findBlockByNumber(1).isVisible())
        self.assertTrue(body.hasFocus())
        # 본문 줄에서 누르면 그 줄을 품은 제목을 접는다(Q8-A).
        body.setTextCursor(QTextCursor(body.document().findBlockByNumber(3)))
        editor.fold_current_button.click()
        self.app.processEvents()
        self.assertFalse(body.document().findBlockByNumber(3).isVisible())
        editor._sync_fold_buttons()
        self.assertTrue(editor.fold_all_button.isChecked())
        editor.fold_all_button.click()
        self.app.processEvents()
        self.assertTrue(body.document().findBlockByNumber(1).isVisible())
        self.assertTrue(body.document().findBlockByNumber(3).isVisible())
        close_alert_panel(panel, self.app)

    def test_fold_buttons_are_disabled_without_headings_or_toggles(self):
        panel = self.panel()
        self.assertFalse(panel.editor.fold_current_button.isEnabled())
        self.assertFalse(panel.editor.fold_all_button.isEnabled())
        close_alert_panel(panel, self.app)


class CategoryAndDeadlineTest(_PanelCase):
    def test_top_level_memo_has_no_location_row_and_child_shows_breadcrumb_only(self):
        panel = self.panel()
        editor = panel.editor
        self.assertFalse(editor.location_host.isVisible())
        self.assertTrue(editor.category_button.isVisible())
        self.assertIs(editor.category_button.parentWidget(), editor)
        child = self.store.create_note("하위", "")
        if hasattr(self.store, "move_note"):
            self.store.move_note(child, self.note_id)
        else:
            self.store.set_note_parent(child, self.note_id)
        panel.show_note(child)
        self.app.processEvents()
        self.assertTrue(editor.location_host.isVisible())
        self.assertFalse(editor.location_host.isAncestorOf(editor.category_button))
        close_alert_panel(panel, self.app)

    def test_long_category_name_is_elided_with_full_tooltip(self):
        category_id = self.store.create_category("프로젝트 정기 회의 자료 모음") if hasattr(
            self.store, "create_category") else self.store.add_category("프로젝트 정기 회의 자료 모음")
        self.store.set_note_category(self.note_id, int(category_id))
        panel = self.panel()
        button = panel.editor.category_button
        self.assertLessEqual(button.width(), 90)
        self.assertTrue(button.text().endswith("▾"))
        self.assertIn("…", button.text())
        self.assertIn("프로젝트 정기 회의 자료 모음", button.toolTip())
        close_alert_panel(panel, self.app)

    def test_deadline_chip_shows_value_only_with_urgency_colour(self):
        panel = self.panel()
        editor = panel.editor
        chip = editor.property_chips.buttons["deadline"]
        self.assertEqual(chip.text(), "📌 D-Day")
        cases = (
            (16, "later"), (2, "soon"), (-3, "past"),
        )
        for days, state in cases:
            with self.subTest(days=days):
                target = datetime.now() + timedelta(days=days)
                self.store.update_note(self.note_id, d_day_at=target.strftime("%Y%m%d2359"), d_day_label="출시")
                panel.show_note(self.note_id)
                self.app.processEvents()
                editor._refresh_deadline_badge()
                self.assertTrue(chip.text().startswith("📌 D"))
                self.assertNotIn("출시", chip.text())
                self.assertIn("출시", chip.toolTip())
                self.assertEqual(chip.property("deadlineState"), state)
                self.assertFalse(editor.deadline_badge.isVisible())
        editor.property_chips.set_narrow(True)
        self.assertTrue(chip.text().startswith("📌 D"))
        self.assertNotEqual(chip.text(), "📌 D-Day")
        close_alert_panel(panel, self.app)


class ChipAndFormatPanelTest(_PanelCase):
    def test_chip_row_is_compact_and_separator_is_light(self):
        panel = self.panel()
        chips = panel.editor.property_chips
        self.assertLessEqual(chips.layout().sizeHint().width(), 380)
        for button in chips.buttons.values():
            self.assertEqual(button.height(), 28)
            need = button.fontMetrics().horizontalAdvance(button.text())
            self.assertLessEqual(need, button.width())
        image = panel.editor.grab().toImage()
        separator = chips.format_separator
        point = separator.mapTo(panel.editor, QPoint(0, separator.height() // 2))
        colour = QColor(image.pixelColor(point.x(), point.y()))
        self.assertGreater(colour.lightness(), 180)
        close_alert_panel(panel, self.app)

    def test_size_and_font_fields_show_their_text(self):
        panel = self.panel()
        panel.editor.property_chips.buttons["format"].click()
        self.app.processEvents()
        toolbar = panel.editor.format_toolbar
        for value in (8, 10, 72):
            toolbar.size_box.setValue(value)
            self.app.processEvents()
            line = toolbar.size_box.lineEdit()
            self.assertGreaterEqual(line.width(), line.fontMetrics().horizontalAdvance(str(value)) + 2)
        for index in range(toolbar.line_spacing_box.count()):
            text = toolbar.line_spacing_box.itemText(index)
            self.assertLessEqual(
                toolbar.line_spacing_box.fontMetrics().horizontalAdvance(text),
                toolbar.line_spacing_box.width() - 14 - 7,
                text,
            )
        toolbar.font_box.setCurrentText("Segoe UI Variable")
        toolbar._show_font_name_from_start()
        QTest.qWait(10)
        self.assertEqual(toolbar.font_box.lineEdit().cursorPosition(), 0)
        close_alert_panel(panel, self.app)

    def test_second_row_has_separator_before_grouped_presets_and_gear_icon(self):
        panel = self.panel()
        toolbar = panel.editor.format_toolbar
        row = toolbar.second_layout
        index = row.indexOf(toolbar.preset_strip)
        self.assertEqual(row.itemAt(index - 1).widget().objectName(), "formatGroupLine")
        self.assertIs(row.itemAt(index - 2).widget(), toolbar.default_button)
        self.assertEqual(toolbar.preset_strip.width(), 26 * 3 + 2)
        self.assertEqual(toolbar.preset_settings_button.text(), "")
        self.assertFalse(toolbar.preset_settings_button.icon().isNull())
        close_alert_panel(panel, self.app)

    def test_settings_submenu_titles_follow_renamed_presets(self):
        panel = self.panel()
        toolbar = panel.editor.format_toolbar
        with patch("alert_notes.text_format_toolbar.QInputDialog.getText", return_value=("강조", True)):
            toolbar.rename_preset(1)
        toolbar.preset_settings_menu.aboutToShow.emit()
        titles = [action.menu().title() for action in toolbar.preset_settings_menu.actions() if action.menu()]
        self.assertEqual(titles[0], "강조")
        close_alert_panel(panel, self.app)

    def test_white_preset_glyph_has_grey_outline_inside_the_letter(self):
        saved = {
            "family": "Malgun Gothic", "size": 12, "color": "#ffffff",
            "bold": True, "italic": False, "underline": False, "strike": False,
        }
        image = preset_sample_icon(saved, 2, self.panel_size()).pixmap(22, 22).toImage()
        grey = 0
        for y in range(3, 18):
            for x in range(3, 17):
                colour = image.pixelColor(x, y)
                if colour.alpha() > 120 and abs(colour.red() - 0x94) < 40 and abs(colour.blue() - 0xb8) < 40:
                    grey += 1
        self.assertGreater(grey, 6)
        # 네모 테두리(모서리 픽셀)는 더 이상 그리지 않는다.
        self.assertLess(image.pixelColor(1, 1).alpha(), 60)

    @staticmethod
    def panel_size():
        from PyQt6.QtCore import QSize
        return QSize(22, 22)

    def test_rows_fit_with_theme_at_supported_widths_and_zoom(self):
        for scale, width in ((1.0, 515), (1.0, 620), (1.25, 644), (1.5, 773)):
            with self.subTest(scale=scale, width=width):
                panel = self.panel(width, scale)
                editor = panel.editor
                editor.property_chips.buttons["format"].click()
                self.app.processEvents()
                toolbar = editor.format_toolbar
                available = toolbar.contentsRect().width()
                for index in (0, 1):
                    self.assertLessEqual(toolbar.layout().itemAt(index).layout().sizeHint().width(), available)
                self.assert_inside(toolbar, [
                    toolbar.font_box, toolbar.size_box, toolbar.line_spacing_box, toolbar.color_button,
                    *toolbar.color_buttons.values(), *toolbar.style_buttons.values(), toolbar.image_button,
                    toolbar.default_button, toolbar.preset_strip, toolbar.preset_settings_button,
                ], f"{scale}x")
                close_alert_panel(panel, self.app)

    def test_open_panel_adds_at_most_76px(self):
        panel = self.panel()
        editor = panel.editor
        closed = editor.body_host.mapTo(editor, QPoint(0, 0)).y()
        editor.property_chips.buttons["format"].click()
        self.app.processEvents()
        opened = editor.body_host.mapTo(editor, QPoint(0, 0)).y()
        self.assertLessEqual(opened - closed, 76)
        close_alert_panel(panel, self.app)


class SelectionBarTest(_PanelCase):
    def _select(self, body, start=0, end=4):
        cursor = body.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        body.setTextCursor(cursor)
        body.text_format_bar.sync()
        self.app.processEvents()

    def test_more_button_is_replaced_by_size_spacing_and_colours(self):
        panel = self.panel()
        body = panel.editor.content_edit
        self._select(body)
        bar = body.text_format_bar
        self.assertFalse(hasattr(bar, "more_button"))
        for widget in (bar.size_box, bar.line_spacing_box, bar.color_button, *bar.color_buttons.values()):
            self.assertTrue(widget.isVisible())
        self.assert_inside(bar, [bar.close_button, bar.size_box, *bar.color_buttons.values()], "bar")
        close_alert_panel(panel, self.app)

    def test_values_sync_both_ways_and_apply_to_selection(self):
        panel = self.panel()
        toolbar = panel.editor.format_toolbar
        body = panel.editor.content_edit
        self._select(body)
        bar = body.text_format_bar
        bar.size_box.setValue(14)
        self.app.processEvents()
        self.assertEqual(toolbar.size_box.value(), 14)
        self.assertEqual(body.textCursor().charFormat().fontPointSize(), 14)
        toolbar.apply_color(QColor("#d00000"))
        self.app.processEvents()
        self.assertIn("#2563eb", bar.color_buttons["red"].styleSheet())
        bar.color_buttons["blue"].click()
        self.app.processEvents()
        self.assertEqual(toolbar.current_color.name(), "#0057d9")
        toolbar.size_box.setValue(11)
        toolbar._sync_from_format(body.currentCharFormat())
        self.assertEqual(bar.size_box.value(), toolbar.size_box.value())
        close_alert_panel(panel, self.app)

    def test_empty_preset_click_does_not_stay_checked(self):
        panel = self.panel()
        toolbar = panel.editor.format_toolbar
        toolbar.clear_saved_preset(3)
        body = panel.editor.content_edit
        self._select(body)
        bar = body.text_format_bar
        with patch.object(QMenu, "popup"), patch.object(QMessageBox, "information") as info:
            bar.preset_strip.buttons[3].click()
            self.app.processEvents()
        self.assertEqual(info.call_count, 0)
        self.assertFalse(bar.preset_strip.buttons[3].isChecked())
        close_alert_panel(panel, self.app)


class IndentAndHeadingSectionTest(_PanelCase):
    def body(self, panel, text=""):
        body = panel.editor.content_edit
        body.setFocus()
        body.clear()
        if text:
            QTest.keyClicks(body, text)
        return body

    def dump(self, body):
        block = body.document().begin()
        rows = []
        while block.isValid():
            rows.append((block.text(), block.isVisible(), is_section_break(block)))
            block = block.next()
        return rows

    def test_one_tab_is_twenty_pixels(self):
        panel = self.panel()
        body = panel.editor.content_edit
        self.assertEqual(INDENT_WIDTH, 20)
        self.assertEqual(body.document().indentWidth(), 20)
        body.setPlainText("a\nb\nc")
        body._shift_indent(body.document().findBlockByNumber(1), 1)
        body._shift_indent(body.document().findBlockByNumber(2), 1)
        body._shift_indent(body.document().findBlockByNumber(2), 1)
        self.app.processEvents()
        xs = [body.cursorRect(QTextCursor(body.document().findBlockByNumber(i))).x() for i in range(3)]
        self.assertAlmostEqual(xs[1] - xs[0], 20, delta=1)
        self.assertAlmostEqual(xs[2] - xs[1], 20, delta=1)
        close_alert_panel(panel, self.app)

    def _folded_heading(self, panel):
        body = self.body(panel, "Head")
        body.apply_heading2()
        QTest.keyClick(body, Qt.Key.Key_Return)
        QTest.keyClicks(body, "body")
        cursor = body.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        body.setTextCursor(cursor)
        body.toggle_current_fold()
        self.app.processEvents()
        return body

    def test_click_below_folded_heading_writes_on_a_visible_line(self):
        panel = self.panel()
        body = self._folded_heading(panel)
        QTest.mouseClick(body.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(200, 300))
        self.app.processEvents()
        QTest.keyClicks(body, "OUT")
        self.assertIn(("OUT", True, True), self.dump(body))
        close_alert_panel(panel, self.app)

    def test_ctrl_end_never_leaves_caret_on_hidden_line(self):
        panel = self.panel()
        body = self._folded_heading(panel)
        QTest.keyClick(body, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        QTest.qWait(5)
        self.assertTrue(body.textCursor().block().isVisible())
        QTest.keyClick(body, Qt.Key.Key_Return)
        QTest.keyClicks(body, "OUT")
        self.app.processEvents()
        self.assertIn(("OUT", True, True), self.dump(body))
        self.assertIn(("body", False, False), self.dump(body))
        close_alert_panel(panel, self.app)

    def test_shift_tab_ends_section_and_survives_save_then_backspace_undoes(self):
        panel = self.panel()
        body = self.body(panel, "Head")
        body.apply_heading2()
        QTest.keyClick(body, Qt.Key.Key_Return)
        QTest.keyClicks(body, "body")
        QTest.keyClick(body, Qt.Key.Key_Return)
        QTest.keyClicks(body, "other")
        QTest.keyClick(body, Qt.Key.Key_Backtab)
        self.app.processEvents()
        cursor = body.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        body.setTextCursor(cursor)
        body.toggle_current_fold()
        self.app.processEvents()
        self.assertEqual(self.dump(body), [("Head", True, False), ("body", False, False), ("other", True, True)])
        content = body.content()
        self.assertIn("tomadesk-section-breaks-v1", content)
        body.set_content(content)
        self.app.processEvents()
        self.assertEqual(self.dump(body)[2], ("other", True, True))
        last = QTextCursor(body.document().lastBlock())
        body.setTextCursor(last)
        QTest.keyClick(body, Qt.Key.Key_Backspace)
        self.app.processEvents()
        self.assertEqual(self.dump(body)[2], ("other", False, False))
        close_alert_panel(panel, self.app)

    def test_notes_without_breaks_fold_exactly_as_before(self):
        panel = self.panel()
        body = self.body(panel, "Head")
        body.apply_heading2()
        QTest.keyClick(body, Qt.Key.Key_Return)
        QTest.keyClicks(body, "one")
        QTest.keyClick(body, Qt.Key.Key_Return)
        QTest.keyClicks(body, "two")
        cursor = body.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        body.setTextCursor(cursor)
        body.toggle_current_fold()
        self.app.processEvents()
        self.assertEqual(self.dump(body), [("Head", True, False), ("one", False, False), ("two", False, False)])
        self.assertNotIn("tomadesk-section-breaks-v1", body.content())
        close_alert_panel(panel, self.app)


if __name__ == "__main__":
    unittest.main()
