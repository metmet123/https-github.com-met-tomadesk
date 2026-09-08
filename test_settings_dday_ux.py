"""요약 한 번 클릭 · D-Day 칩 · 설정창 손보기."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication, QMessageBox, QScrollArea

import main_window
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.today_summary import SummaryList, TodaySummaryPanel
from hotkey_builder import HotkeyBuilder
from qt_test_support import close_main_window, destroy_widget
from settings_dialog import HOTKEY_DEFAULTS, SettingsDialog
from store import Store
from ui_theme import scaled_stylesheet


class _TrackingHotkeys:
    def __init__(self, _window_id):
        self.registered = {}

    def register(self, hotkey_id, hotkey, callback):
        self.registered[hotkey_id] = (hotkey, callback)

    def unregister(self, hotkey_id):
        self.registered.pop(hotkey_id, None)

    def unregister_all(self):
        self.registered.clear()

    def handle_native_event(self, _message):
        return False


class _FakeRecorder:
    ignore_click = None

    def stop(self):
        return []


def click(app, view, point: QPoint) -> None:
    """사람이 한 번 누르는 것과 같은 순서로 누르고 뗀다."""
    where = QPointF(point)
    globally = QPointF(view.mapToGlobal(point))
    for kind in (
        QMouseEvent.Type.MouseButtonPress,
        QMouseEvent.Type.MouseButtonRelease,
    ):
        QApplication.sendEvent(view, QMouseEvent(
            kind, where, globally, Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ))
    app.processEvents()


class SummaryClickTest(unittest.TestCase):
    """오늘 요약 목록은 한 번 누르면 열린다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.note_id = self.store.create_note("본예산", "내용")
        self.store.set_deadline(self.note_id, "209912312359", "본예산", False)
        self.panel = TodaySummaryPanel(self.store)
        self.panel.resize(320, 620)
        self.panel.show()
        self.app.processEvents()
        self.opened: list[int] = []
        self.panel.note_open_requested.connect(self.opened.append)

    def tearDown(self):
        self.panel.shutdown()
        destroy_widget(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _row(self):
        return self.panel.deadline_list.item(0)

    def test_one_click_opens_the_memo(self):
        item = self._row()
        click(self.app, self.panel.deadline_list.viewport(),
              self.panel.deadline_list.visualItemRect(item).center())
        self.assertEqual(self.opened, [self.note_id])

    def test_the_check_box_only_stops_the_count(self):
        item = self._row()
        box = self.panel.deadline_list.check_box_rect(item)
        self.assertFalse(box.isEmpty(), "체크칸 자리를 못 찾았습니다")
        click(self.app, self.panel.deadline_list.viewport(), box.center())
        self.assertEqual(self.opened, [], "체크칸을 눌렀는데 메모가 열렸습니다")
        self.assertTrue(str(self.store.note(self.note_id)["d_day_done_at"] or ""))

    def test_the_notice_line_opens_nothing(self):
        self.panel.reminder_list.setCurrentRow(0)
        item = self.panel.reminder_list.item(0)
        self.assertIsNone(item.data(Qt.ItemDataRole.UserRole))
        click(self.app, self.panel.reminder_list.viewport(),
              self.panel.reminder_list.visualItemRect(item).center())
        self.assertEqual(self.opened, [])

    def test_a_schedule_line_asks_for_the_calendar(self):
        wanted: list[int] = []
        self.panel.schedule_open_requested.connect(wanted.append)
        self.panel.schedule_list.chosen.emit(7)
        self.assertEqual(wanted, [7])

    def test_every_summary_list_answers_one_click(self):
        for widget in (
            self.panel.deadline_list, self.panel.schedule_list, self.panel.reminder_list,
        ):
            self.assertIsInstance(widget, SummaryList)
            self.assertEqual(
                widget.viewport().cursor().shape(), Qt.CursorShape.PointingHandCursor,
            )


class MainWindowFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "hotkeys.db")
        self.patches = [
            patch.object(main_window, "Store", return_value=self.store),
            patch.object(main_window, "HotkeyManager", _TrackingHotkeys),
            patch.object(main_window, "WindowsHookRecorder", _FakeRecorder),
            patch.object(main_window, "save_storage_paths"),
        ]
        for item in self.patches:
            item.start()
        self.window = main_window.MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        close_main_window(self.window, self.app)
        for item in reversed(self.patches):
            item.stop()
        self.store.close()
        self.temp.cleanup()


class DeadlineChipTest(MainWindowFixture):
    """위쪽 칩은 가장 임박한 D-Day 메모로 가는 문이다."""

    def _make_deadline(self, title: str, due: str) -> int:
        note_id = self.window.note_store.create_note(title, "내용")
        self.window.note_store.set_deadline(note_id, due, title, False)
        return note_id

    def test_the_chip_opens_the_nearest_memo(self):
        far = self._make_deadline("먼 일", "209912312359")
        near = self._make_deadline("가까운 일", "202609081200")
        self.window.refresh_deadline_indicators()
        self.assertEqual(self.window._nearest_deadline_id, near)
        self.window._open_deadline_summary()
        self.app.processEvents()
        self.assertEqual(self.window.alert_panel.current_id, near)
        self.assertNotEqual(self.window.alert_panel.current_id, far)
        self.assertEqual(self.window.alert_panel.tabs.currentIndex(), 0)

    def test_the_chip_shows_how_many_more_are_waiting(self):
        self._make_deadline("먼 일", "209912312359")
        self._make_deadline("가까운 일", "202609081200")
        self.window.refresh_deadline_indicators()
        self.assertIn("+1", self.window.deadline_chip.text())

    def test_no_deadline_leaves_nothing_to_open(self):
        self.window.refresh_deadline_indicators()
        self.assertIsNone(self.window._nearest_deadline_id)
        self.assertFalse(self.window.deadline_chip.isVisible())
        self.window._open_deadline_summary()  # 아무 일도 없어야 한다
        self.app.processEvents()


class SettingsWindowTest(MainWindowFixture):
    """설정창을 띄운 채로 다른 창도 쓸 수 있어야 한다."""

    def tearDown(self):
        dialog = getattr(self.window, "_settings_dialog", None)
        if dialog is not None:
            dialog.reject()
            self.app.processEvents()
        super().tearDown()

    def test_the_settings_window_blocks_nothing(self):
        self.window.show_settings()
        self.app.processEvents()
        dialog = self.window._settings_dialog
        self.assertIsNotNone(dialog)
        self.assertFalse(dialog.isModal())
        self.assertEqual(dialog.windowModality(), Qt.WindowModality.NonModal)
        self.assertIsNone(
            QApplication.activeModalWidget(), "다른 창을 막는 창이 떠 있습니다",
        )

    def test_the_search_window_can_be_used_beside_it(self):
        self.window.show_settings()
        self.window.show_memo_search()
        self.app.processEvents()
        search = self.window._memo_search_dialog
        self.assertTrue(search.isVisible())
        # 막는 창이 없으니 검색칸에 그대로 글자를 넣을 수 있다.
        self.assertIsNone(QApplication.activeModalWidget())
        search.search_edit.setText("본")
        self.assertEqual(search.search_edit.text(), "본")
        search.close()

    def test_opening_it_twice_keeps_one_window(self):
        self.window.show_settings()
        first = self.window._settings_dialog
        self.window.show_settings()
        self.assertIs(self.window._settings_dialog, first)

    def test_saving_applies_the_choice_without_waiting(self):
        self.window.show_settings()
        dialog = self.window._settings_dialog
        dialog.startup_combo.setCurrentIndex(dialog.startup_combo.findData("tray"))
        with (
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "warning") as warning,
        ):
            dialog._validate_and_accept()
            self.app.processEvents()
        warning.assert_not_called()
        self.assertEqual(self.window.startup_mode, "tray")
        self.assertEqual(self.store.setting("startup_mode", ""), "tray")

    def test_closing_it_lets_the_window_go(self):
        self.window.show_settings()
        self.window._settings_dialog.reject()
        self.app.processEvents()
        self.assertIsNone(self.window._settings_dialog)

    def test_empty_schedule_postit_hotkey_is_not_registered(self):
        self.assertEqual(self.window.schedule_postit_hotkey, "")
        self.assertNotIn(
            main_window.SCHEDULE_POSTIT_HOTKEY_ID,
            self.window.hotkeys.registered,
        )

    def test_user_schedule_postit_hotkey_is_saved_and_registered(self):
        self.window.show_settings()
        dialog = self.window._settings_dialog
        dialog.schedule_postit_hotkey_builder.setText("Ctrl+Alt+8")
        with (
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "warning") as warning,
        ):
            dialog._validate_and_accept()
            self.app.processEvents()
        warning.assert_not_called()
        self.assertEqual(self.window.schedule_postit_hotkey, "Ctrl+Alt+8")
        self.assertEqual(
            self.window.note_store.setting("schedule_postit_hotkey", ""),
            "Ctrl+Alt+8",
        )
        self.assertEqual(
            self.window.hotkeys.registered[main_window.SCHEDULE_POSTIT_HOTKEY_ID][0],
            "Ctrl+Alt+8",
        )

    def test_user_schedule_postit_hotkey_can_be_cleared_and_unregistered(self):
        self.window.show_settings()
        first = self.window._settings_dialog
        first.schedule_postit_hotkey_builder.setText("Ctrl+Alt+8")
        with (
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "warning") as warning,
        ):
            first._validate_and_accept()
            self.app.processEvents()
        warning.assert_not_called()
        self.assertIn(main_window.SCHEDULE_POSTIT_HOTKEY_ID, self.window.hotkeys.registered)

        self.window.show_settings()
        second = self.window._settings_dialog
        second.schedule_postit_hotkey_builder.setText("")
        with (
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "warning") as warning,
        ):
            second._validate_and_accept()
            self.app.processEvents()
        warning.assert_not_called()
        self.assertEqual(self.window.schedule_postit_hotkey, "")
        self.assertEqual(self.window.note_store.setting("schedule_postit_hotkey", "missing"), "")
        self.assertNotIn(main_window.SCHEDULE_POSTIT_HOTKEY_ID, self.window.hotkeys.registered)

    def test_tray_action_toggles_the_schedule_postit(self):
        action = next(
            item
            for item in self.window.tray_icon.contextMenu().actions()
            if item.text() == "일정 포스트잇"
        )
        postit = self.window.alert_panel.schedule_postit
        self.assertFalse(postit.isVisible())
        action.trigger()
        self.app.processEvents()
        self.assertTrue(postit.isVisible())
        action.trigger()
        self.app.processEvents()
        self.assertFalse(postit.isVisible())


class SettingsRoomTest(unittest.TestCase):
    """설정창의 빈 자리 정리."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(scaled_stylesheet(1.0))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dialog = SettingsDialog(HOTKEY_DEFAULTS, "window", Path(self.temp.name))
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.dialog, self.app)
        self.temp.cleanup()

    def _heading(self):
        return self.dialog.hotkey_card.layout().itemAt(0).widget()

    def test_the_heading_no_longer_swallows_the_empty_space(self):
        heading = self._heading()
        self.assertEqual(heading.text(), "단축키")
        self.assertLessEqual(heading.height(), heading.sizeHint().height() + 8)

    def test_the_first_row_sits_right_under_the_heading(self):
        heading = self._heading()
        first = self.dialog.hotkey_field_widgets[0]
        gap = first.mapTo(self.dialog.hotkey_card, QPoint()).y() - heading.geometry().bottom()
        self.assertLessEqual(gap, 20, "머리글과 첫 줄 사이가 아직 비어 있습니다")

    def test_a_hotkey_row_got_shorter(self):
        builder = self.dialog.hotkey_builders["main_open_hotkey"]
        self.assertLessEqual(builder.height(), 36)
        self.assertGreaterEqual(builder.height(), 28, "누르기 어려울 만큼 낮습니다")

    def test_the_hotkey_card_hugs_its_rows(self):
        card = self.dialog.hotkey_card
        self.assertLessEqual(card.height() - card.sizeHint().height(), 24)

    def test_the_two_columns_are_about_the_same_height(self):
        left = self.dialog.main_panel.height()
        right = self.dialog.startup_card.parentWidget().height()
        self.assertLessEqual(abs(left - right), 4, "두 칸 높이가 어긋납니다")

    def test_the_deadline_choices_moved_beside_the_hotkeys(self):
        self.assertIs(self.dialog.deadline_card.parentWidget(), self.dialog.schedule_page)
        self.assertEqual(self.dialog._deadline_columns, 3)

    def test_the_four_approved_categories_are_tabs(self):
        self.assertEqual(self.dialog.settings_tabs.count(), 4)
        self.assertEqual(
            [self.dialog.settings_tabs.tabText(index) for index in range(4)],
            ["단축키", "일정·D-Day", "프로그램", "데이터"],
        )

    def test_the_schedule_postit_and_deadline_cards_share_one_page(self):
        self.assertIs(
            self.dialog.schedule_postit_card.parentWidget(), self.dialog.schedule_page
        )

    def test_category_pages_do_not_add_internal_scroll_areas(self):
        self.assertEqual(self.dialog.settings_tabs.findChildren(QScrollArea), [])

    def test_schedule_value_controls_ignore_mouse_wheel_even_when_focused(self):
        controls = (
            self.dialog.schedule_postit_view_combo,
            self.dialog.schedule_postit_max_rows,
            self.dialog.schedule_postit_completion_combo,
        )
        for control in controls:
            before = (
                control.currentIndex()
                if hasattr(control, "currentIndex")
                else control.value()
            )
            control.setFocus()
            event = QWheelEvent(
                QPointF(4, 4), QPointF(4, 4), QPoint(), QPoint(0, 120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            QApplication.sendEvent(control, event)
            after = (
                control.currentIndex()
                if hasattr(control, "currentIndex")
                else control.value()
            )
            self.assertEqual(after, before)

    def test_schedule_hotkey_defaults_to_empty_and_values_preserve_it(self):
        self.assertEqual(self.dialog.schedule_postit_hotkey_builder.text(), "")
        self.assertEqual(self.dialog.values()["schedule_postit_preferences"].hotkey, "")

    def test_schedule_hotkey_conflict_keeps_the_existing_empty_value(self):
        self.dialog._action_hotkeys = {"Ctrl+Alt+8"}
        self.dialog.schedule_postit_hotkey_builder.setText("Ctrl+Alt+8")
        with patch.object(QMessageBox, "information") as notice:
            self.dialog._validate_and_accept()
        self.assertTrue(notice.called)
        self.assertEqual(
            self.dialog.values()["schedule_postit_preferences"].hotkey,
            "",
        )

    def test_schedule_hotkey_rejects_windows_reserved_combinations(self):
        self.dialog.schedule_postit_hotkey_builder.setText("Win+L")
        with patch.object(QMessageBox, "information") as notice:
            self.dialog._validate_and_accept()
        self.assertTrue(notice.called)
        self.assertEqual(
            self.dialog.values()["schedule_postit_preferences"].hotkey,
            "",
        )

    def test_the_window_opens_shorter_than_before(self):
        self.assertLessEqual(self.dialog.height(), 830)
        self.assertGreaterEqual(self.dialog.height(), self.dialog.sizeHint().height())


class OptionalHotkeyBuilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_allow_empty_is_opt_in(self):
        required = HotkeyBuilder()
        required.setText("")
        optional = HotkeyBuilder()
        optional.setAllowEmpty(True)
        optional.setText("")
        self.assertEqual(required.text(), "Ctrl")
        self.assertEqual(optional.text(), "")
        required.deleteLater()
        optional.deleteLater()


if __name__ == "__main__":
    unittest.main()
