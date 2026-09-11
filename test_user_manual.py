"""사용 설명서 창이 실제로 읽히는 상태인지 검사한다.

설명서는 화면 그림에 기대는 기능이라 파일이 빠지거나 좌표가 어긋나면
사용자가 바로 알아차린다.  그림 존재, 번호와 설명 개수, 넘기기, 섹션 이동,
실제 단축키 치환을 확인한다.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

from qt_test_support import destroy_widget
from user_manual import IMAGE_DIR, AnnotatedShot, MarkerNote, UserManualDialog
from user_manual_content import MANUAL_SECTIONS, slide_list


class UserManualContentTest(unittest.TestCase):
    def test_every_slide_has_a_picture_on_disk(self):
        for _section, slide in slide_list():
            path = IMAGE_DIR / slide["image"]
            self.assertTrue(path.exists(), f"그림이 없습니다: {path}")

    def test_markers_stay_inside_the_picture(self):
        for _section, slide in slide_list():
            for marker in slide["markers"]:
                self.assertGreaterEqual(marker["x"], 0.0)
                self.assertLessEqual(marker["x"], 1.0)
                self.assertGreaterEqual(marker["y"], 0.0)
                self.assertLessEqual(marker["y"], 1.0)

    def test_every_marker_says_what_it_is_and_what_it_does(self):
        for _section, slide in slide_list():
            self.assertTrue(slide["markers"], f"번호가 없는 장: {slide['title']}")
            for marker in slide["markers"]:
                self.assertTrue(marker["title"].strip())
                self.assertTrue(marker["body"].strip())

    def test_sections_are_not_empty(self):
        for section in MANUAL_SECTIONS:
            self.assertTrue(section["title"].strip())
            self.assertTrue(section["slides"])


class UserManualDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = UserManualDialog(hotkeys={"main_open": "Ctrl+Alt+K"})
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.dialog, self.app)

    def _page_widgets(self, kind):
        page = self.dialog.scroll.widget()
        return page.findChildren(kind)

    def test_opens_on_the_first_slide(self):
        self.assertEqual(self.dialog.step_label.text(), f"1 / {len(self.dialog._slides)}")
        self.assertFalse(self.dialog.prev_button.isEnabled())
        self.assertTrue(self.dialog.next_button.isEnabled())
        self.assertTrue(self.dialog.section_buttons[0].isChecked())

    def test_numbers_on_the_picture_match_the_notes_below(self):
        for index in range(len(self.dialog._slides)):
            self.dialog._go(index)
            self.app.processEvents()
            _section, slide = self.dialog._slides[index]
            shots = self._page_widgets(AnnotatedShot)
            self.assertEqual(len(shots), 1)
            self.assertEqual(len(shots[0]._markers), len(slide["markers"]))
            self.assertEqual(len(self._page_widgets(MarkerNote)), len(slide["markers"]))

    def test_next_and_previous_walk_the_whole_manual(self):
        last = len(self.dialog._slides) - 1
        for _step in range(last + 3):
            self.dialog.next_button.click()
        self.assertEqual(self.dialog._index, last)
        self.assertFalse(self.dialog.next_button.isEnabled())
        for _step in range(last + 3):
            self.dialog.prev_button.click()
        self.assertEqual(self.dialog._index, 0)

    def test_section_button_jumps_to_that_section(self):
        self.dialog.section_buttons[-1].click()
        self.app.processEvents()
        section_index, _slide = self.dialog._slides[self.dialog._index]
        self.assertEqual(section_index, len(MANUAL_SECTIONS) - 1)
        self.assertTrue(self.dialog.section_buttons[-1].isChecked())
        self.assertFalse(self.dialog.section_buttons[0].isChecked())

    def test_shows_the_hotkey_the_user_actually_uses(self):
        pages = []
        for index in range(len(self.dialog._slides)):
            self.dialog._go(index)
            self.app.processEvents()
            pages.append(self._page_text())
        joined = "\n".join(pages)
        # 설정에서 바꾼 키가 그대로 나오고, 자리표시자는 남지 않는다.
        self.assertIn("Ctrl+Alt+K", joined)
        self.assertNotIn("{main_open}", joined)
        self.assertNotIn("{record_stop}", joined)

    def _page_text(self) -> str:
        page = self.dialog.scroll.widget()
        return "\n".join(label.text() for label in page.findChildren(QLabel))


if __name__ == "__main__":
    unittest.main()
