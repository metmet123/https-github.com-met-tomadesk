import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication, QLabel

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel


class CompactFormatToolbarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "memo.db")
        self.note_id = self.store.create_note("두 줄 서식", "폭과 높이 검사")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _panel(self, editor_width=515):
        panel = AlertNotesPanel(self.store)
        panel.resize(max(1080, editor_width + 520), 820)
        panel.update_responsive_layout(panel.width())
        panel.show()
        panel.show_note(self.note_id)
        panel.editor.setFixedWidth(editor_width)
        self.app.processEvents()
        return panel

    def test_labels_are_replaced_with_tooltips_and_accessible_names(self):
        panel = self._panel()
        toolbar = panel.editor.format_toolbar
        first = toolbar.layout().itemAt(0).layout()
        direct_labels = [
            item.widget() for index in range(first.count())
            if (item := first.itemAt(index)).widget() is not None
            and isinstance(item.widget(), QLabel)
        ]
        self.assertEqual(direct_labels, [])
        for control, name in (
            (toolbar.font_box, "글씨체"),
            (toolbar.size_box, "글자 크기"),
            (toolbar.line_spacing_box, "줄 간격"),
        ):
            self.assertEqual(control.accessibleName(), name)
            self.assertEqual(control.toolTip(), name)
        self.assertEqual(toolbar.size_box.width(), toolbar.SIZE_BOX_WIDTH)
        self.assertEqual(toolbar.line_spacing_box.width(), toolbar.LINE_SPACING_BOX_WIDTH)
        self.assertEqual(toolbar.font_box.width(), 150)
        close_alert_panel(panel, self.app)

    def test_icons_and_control_sizes_follow_compact_contract(self):
        panel = self._panel()
        toolbar = panel.editor.format_toolbar
        editor = panel.editor
        # 접기 단추는 서식 패널을 떠나 제목 줄의 26px 두 단추가 되었다.
        self.assertFalse(hasattr(toolbar, "fold_button"))
        for button in (editor.fold_current_button, editor.fold_all_button):
            self.assertFalse(button.icon().isNull())
            self.assertEqual((button.width(), button.height()), (26, 26))
            self.assertIsNone(button.menu())
        self.assertEqual(toolbar.size_box.buttonSymbols(), toolbar.size_box.ButtonSymbols.NoButtons)
        self.assertEqual(toolbar.preset_settings_button.text(), "")
        self.assertFalse(toolbar.preset_settings_button.icon().isNull())
        self.assertFalse(toolbar.default_button.icon().isNull())
        self.assertEqual((toolbar.default_button.width(), toolbar.default_button.height()), (28, 28))
        self.assertEqual((toolbar.preset_settings_button.width(), toolbar.preset_settings_button.height()), (28, 28))
        for button in (
            *toolbar.style_buttons.values(), toolbar.bullet_button, toolbar.checklist_button,
            toolbar.image_button,
        ):
            self.assertEqual((button.width(), button.height()), (28, 28))
        self.assertIs(toolbar.insert_button, editor.function_button)
        self.assertEqual(toolbar.insert_button.size(), editor.fold_current_button.size())
        close_alert_panel(panel, self.app)

    def test_two_rows_fit_and_controls_are_not_clipped_at_supported_widths(self):
        for width in (515, 620, 780):
            with self.subTest(width=width):
                panel = self._panel(width)
                editor = panel.editor
                editor.property_chips.buttons["format"].click()
                self.app.processEvents()
                toolbar = editor.format_toolbar
                available = toolbar.contentsRect().width()
                first = toolbar.layout().itemAt(0).layout()
                second = toolbar.layout().itemAt(1).layout()
                self.assertLessEqual(first.sizeHint().width(), available)
                self.assertLessEqual(second.sizeHint().width(), available)
                controls = [
                    toolbar.font_box, toolbar.size_box, toolbar.line_spacing_box,
                    toolbar.color_button, *toolbar.color_buttons.values(),
                    *toolbar.style_buttons.values(), toolbar.bullet_button,
                    toolbar.checklist_button,
                    toolbar.image_button, toolbar.default_button, toolbar.preset_strip,
                    toolbar.preset_settings_button,
                ]
                for control in controls:
                    self.assertTrue(control.isVisible(), control.objectName())
                    pos = control.mapTo(toolbar, QPoint(0, 0))
                    self.assertTrue(toolbar.rect().contains(QRect(pos, control.size())),
                                    f"{width}px: {control.objectName()} {pos} {control.size()}")
                close_alert_panel(panel, self.app)

    def test_open_height_is_at_most_76_and_closed_panel_uses_no_space(self):
        panel = self._panel(515)
        editor = panel.editor
        baseline = editor.body_host.mapTo(editor, QPoint(0, 0)).y()
        editor.property_chips.buttons["format"].click()
        self.app.processEvents()
        opened = editor.body_host.mapTo(editor, QPoint(0, 0)).y()
        self.assertLessEqual(opened - baseline, 76)
        self.assertTrue(editor.format_panel.isVisible())
        editor.property_chips.buttons["format"].click()
        self.app.processEvents()
        self.assertFalse(editor.format_panel.isVisible())
        self.assertEqual(editor.body_host.mapTo(editor, QPoint(0, 0)).y(), baseline)
        close_alert_panel(panel, self.app)


if __name__ == "__main__":
    unittest.main()
