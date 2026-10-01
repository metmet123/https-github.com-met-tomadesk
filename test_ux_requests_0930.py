"""2026-09-30 요청: 드롭박스 눌러 넘기기, 단축키 사용안함, 메모 목록 단축키, 정각 알림 기본값."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox

import main_window
from alert_notes.schedule_popover import StandaloneSchedulePopover
from alert_notes.sqlite_store import NoteReminderStore
from combo_click_cycle import arrow_rect, install_combo_click_cycle
from hotkey_builder import HotkeyBuilder
from qt_test_support import close_main_window, destroy_widget
from settings_dialog import HOTKEY_DEFAULTS, REQUIRED_HOTKEYS, SettingsDialog
from store import Store


class _FakeHotkeyManager:
    def __init__(self, _window_id):
        pass

    def register(self, *_args):
        pass

    def unregister_all(self):
        pass

    def handle_native_event(self, _message):
        return False


class _FakeRecorder:
    ignore_click = None

    def stop(self):
        return []


class ComboClickCycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        install_combo_click_cycle(cls.app)

    def setUp(self):
        self.combo = QComboBox()
        self.combo.addItems(["1년", "6개월", "1개월"])
        self.combo.resize(160, 30)
        self.combo.show()
        self.app.processEvents()

    def tearDown(self):
        self.combo.hidePopup()
        destroy_widget(self.combo, self.app)

    def click_text(self, combo=None):
        combo = combo or self.combo
        QTest.mouseClick(combo, Qt.MouseButton.LeftButton, pos=QPoint(12, combo.height() // 2))
        self.app.processEvents()

    def test_text_click_moves_to_next_item_and_wraps(self):
        activated = []
        self.combo.activated.connect(activated.append)
        self.click_text()
        self.assertEqual(self.combo.currentText(), "6개월")
        self.click_text()
        self.click_text()
        self.assertEqual(self.combo.currentText(), "1년")
        self.assertEqual(activated, [1, 2, 0])
        self.assertIsNone(QApplication.activePopupWidget())

    def test_arrow_click_still_opens_list(self):
        QTest.mouseClick(self.combo, Qt.MouseButton.LeftButton, pos=arrow_rect(self.combo).center())
        self.app.processEvents()
        self.assertEqual(self.combo.currentIndex(), 0)
        self.assertTrue(self.combo.view().isVisible())

    def test_disabled_items_are_skipped(self):
        model = self.combo.model()
        self.assertIsInstance(model, QStandardItemModel)
        model.item(1).setEnabled(False)
        self.click_text()
        self.assertEqual(self.combo.currentText(), "1개월")

    def test_editable_and_hotkey_combos_are_left_alone(self):
        editable = QComboBox()
        editable.setEditable(True)
        editable.addItems(["가", "나"])
        editable.show()
        builder = HotkeyBuilder()
        builder.setText("Ctrl+Alt+N")
        builder.show()
        self.app.processEvents()
        try:
            QTest.mouseClick(editable.lineEdit(), Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
            self.assertEqual(editable.currentIndex(), 0)
            self.click_text(builder.first_modifier)
            self.assertEqual(builder.first_modifier.currentText(), "Ctrl")
            builder.first_modifier.hidePopup()
        finally:
            destroy_widget(editable, self.app)
            destroy_widget(builder, self.app)


class SettingsDisableHotkeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dialog = SettingsDialog(dict(HOTKEY_DEFAULTS), "window", Path(self.temp.name))

    def tearDown(self):
        destroy_widget(self.dialog, self.app)
        self.temp.cleanup()

    def test_disable_button_sits_left_of_default_and_clears_hotkey(self):
        self.assertEqual(set(self.dialog.hotkey_disable_buttons),
                         set(self.dialog.hotkey_builders) - REQUIRED_HOTKEYS)
        button = self.dialog.hotkey_disable_buttons["quick_memo_hotkey"]
        reset = self.dialog.hotkey_reset_buttons["quick_memo_hotkey"]
        row = button.parentWidget().layout().itemAt(0).layout()
        widgets = [row.itemAt(i).widget() for i in range(row.count())]
        self.assertLess(widgets.index(button), widgets.index(reset))
        self.assertEqual(button.text(), "사용안함")
        button.click()
        self.assertEqual(self.dialog.hotkey_builders["quick_memo_hotkey"].text(), "")
        self.assertEqual(self.dialog.values()["quick_memo_hotkey"], "")
        reset.click()
        self.assertEqual(self.dialog.values()["quick_memo_hotkey"], "Ctrl+Alt+N")

    def test_stop_hotkeys_cannot_be_disabled(self):
        for key in REQUIRED_HOTKEYS:
            self.assertNotIn(key, self.dialog.hotkey_disable_buttons)
            self.assertEqual(self.dialog.hotkey_builders[key].first_modifier.findText("지정안함"), -1)

    def test_quick_memo_field_is_labelled_memo_list(self):
        self.assertEqual(self.dialog.hotkey_builders["quick_memo_hotkey"].accessibleName(), "메모 목록 열기")


class StoredEmptyHotkeyTest(unittest.TestCase):
    def test_empty_setting_stays_disabled_but_stop_keys_fall_back(self):
        fake = SimpleNamespace(store=SimpleNamespace(setting=lambda _key, _fallback: ""))
        self.assertEqual(main_window.MainWindow._hotkey_from_store(fake, "quick_memo_hotkey", "Ctrl+Alt+N"), "")
        self.assertEqual(
            main_window.MainWindow._hotkey_from_store(fake, "record_stop_hotkey", "Ctrl+Alt+F12", allow_empty=False),
            "Ctrl+Alt+F12",
        )


class MemoListHotkeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp_dir.name) / "ui-test.db")
        self.patches = [
            patch.object(main_window, "Store", return_value=self.store),
            patch.object(main_window, "HotkeyManager", _FakeHotkeyManager),
            patch.object(main_window, "WindowsHookRecorder", _FakeRecorder),
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
        self.store.conn.close()
        self.temp_dir.cleanup()

    def test_hotkey_opens_memo_list_instead_of_quick_memo(self):
        registered = []
        self.window.hotkeys = SimpleNamespace(
            unregister_all=lambda: None,
            register=lambda _id, hotkey, callback: registered.append((hotkey, callback)),
            # 창에 Windows 메시지가 오면 nativeEvent가 부른다.  없으면 PyQt가 프로세스를 끝낸다.
            handle_native_event=lambda _message: False,
        )
        self.window.register_hotkeys(False)
        callback = dict(registered)[self.window.quick_memo_hotkey]
        self.assertEqual(callback, self.window.show_memo_list)

        self.window._switch_workspace(0)
        self.window.alert_panel.toggle_memo_list(True)
        self.window.hide()
        self.window.show_memo_list()
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.main_pages.currentIndex(), 1)
        self.assertEqual(self.window.alert_panel.tabs.currentIndex(), 0)
        self.assertFalse(self.window.alert_panel.memo_list_hidden)
        self.assertTrue(self.window.alert_panel.list_panel.isVisible())
        self.assertIsNone(self.window._quick_memo_dialog)


class DefaultAtTimeReminderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.popover = StandaloneSchedulePopover(self.store)

    def tearDown(self):
        destroy_widget(self.popover, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_timed_new_schedule_defaults_to_at_time_alarm(self):
        p = self.popover
        p.open_new(datetime(2026, 10, 1, 14, 0), datetime(2026, 10, 1, 15, 0))
        self.assertEqual(p.values()["reminders"], [0])
        self.assertTrue(p.at_time_button.isChecked())

    def test_all_day_drops_default_and_timed_restores_it(self):
        p = self.popover
        p.open_new(datetime(2026, 10, 1, 14, 0), datetime(2026, 10, 1, 15, 0))
        p._apply_duration(0)
        self.assertTrue(p.values()["all_day"])
        self.assertEqual(p.values()["reminders"], [])
        p._apply_duration(60)
        self.assertEqual(p.values()["reminders"], [0])

    def test_user_choice_and_parsed_alarm_win(self):
        p = self.popover
        p.open_new(datetime(2026, 10, 1, 14, 0), datetime(2026, 10, 1, 15, 0))
        p.none_reminder_button.click()
        p._apply_duration(90)
        self.assertEqual(p.values()["reminders"], [])
        p.open_new(datetime(2026, 10, 1, 14, 0), datetime(2026, 10, 1, 15, 0))
        p.title_edit.setText("회의 내일 3시 10분 전")
        self.assertEqual(p.values()["reminders"], [10])

    def test_existing_schedule_without_alarm_is_unchanged(self):
        item_id = self.store.schedules.save_item({
            "title": "기존 일정", "details": "", "item_type": "event",
            "start_at": "202610011400", "end_at": "202610011500",
            "all_day": False, "category": "lavender", "reminders": [],
        })
        self.assertTrue(self.popover.open_item(item_id))
        self.assertEqual(self.popover.values()["reminders"], [])


class StandaloneUntitledScheduleTest(unittest.TestCase):
    """빠른 일정 창(Ctrl+Alt+A)도 시간만 적으면 ‘제목없음’으로 저장한다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.popover = StandaloneSchedulePopover(self.store)
        self.popover.open_at_current_time()

    def tearDown(self):
        destroy_widget(self.popover, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_time_only_title_saves_untitled_with_alarm(self):
        saved = []
        self.popover.saved.connect(saved.append)
        self.popover.title_edit.setText("내일 3시")
        self.assertTrue(self.popover.save())
        item = self.store.schedules.item(saved[0])
        self.assertEqual(item["title"], "제목없음")
        self.assertEqual(datetime.strptime(item["start_at"], "%Y%m%d%H%M").hour, 15)
        self.assertEqual(self.store.schedules.notifications(saved[0]), [0])

    def test_no_default_alarm_until_a_time_is_given(self):
        p = self.popover
        self.assertEqual(p.values()["reminders"], [])
        p.title_edit.setText("보고서 정리")
        self.assertEqual(p.values()["reminders"], [])
        p.title_edit.setText("보고서 정리 3시")
        self.assertEqual(p.values()["reminders"], [0])
        p.title_edit.setText("보고서 정리")
        self.assertEqual(p.values()["reminders"], [])

    def test_untouched_empty_popover_still_asks_for_title(self):
        with patch("alert_notes.schedule_popover.QMessageBox.warning") as warning:
            self.assertFalse(self.popover.save())
        warning.assert_called_once()
        self.assertEqual(self.store.schedules.items_for_range("200001010000", "209912312359"), [])

    def test_calendar_popover_keeps_requiring_a_title(self):
        from alert_notes.schedule_popover import SchedulePopover
        popover = SchedulePopover(self.store)
        try:
            popover.open_new(datetime(2026, 10, 2, 9, 0))
            popover.title_edit.setText("내일 3시")
            with patch("alert_notes.schedule_popover.QMessageBox.warning"):
                self.assertFalse(popover.save())
        finally:
            destroy_widget(popover, self.app)


class AmbiguousPastMorningTest(unittest.TestCase):
    """오전·오후 없이 적은 7~11시가 이미 지났으면 오늘 저녁으로 읽는다."""

    def parse(self, text):
        from alert_notes.ko_schedule_parser import parse
        now = datetime(2026, 10, 1, 11, 32)
        return parse(text, now=now, relative_base=now)

    def test_past_bare_morning_hour_moves_to_evening(self):
        self.assertEqual(self.parse("회의 9시").start, datetime(2026, 10, 1, 21, 0))
        self.assertEqual(self.parse("회의 9:30").start, datetime(2026, 10, 1, 21, 30))
        ranged = self.parse("회의 9시~11시")
        self.assertEqual((ranged.start, ranged.end),
                         (datetime(2026, 10, 1, 21, 0), datetime(2026, 10, 1, 23, 0)))

    def test_explicit_or_future_or_dated_times_stay(self):
        self.assertEqual(self.parse("회의 오전 9시").start, datetime(2026, 10, 1, 9, 0))
        self.assertEqual(self.parse("회의 아침 9시").start, datetime(2026, 10, 1, 9, 0))
        self.assertEqual(self.parse("내일 9시 회의").start, datetime(2026, 10, 2, 9, 0))
        self.assertEqual(self.parse("회의 3시").start, datetime(2026, 10, 1, 15, 0))
        self.assertEqual(self.parse("회의 12시").start, datetime(2026, 10, 1, 12, 0))
        self.assertEqual(self.parse("매일 9시 약").start, datetime(2026, 10, 1, 9, 0))


class PopoverEnterAndCtrlSTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.popover = StandaloneSchedulePopover(self.store)
        self.popover.open_at_current_time()

    def tearDown(self):
        destroy_widget(self.popover, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_enter_in_title_saves(self):
        saved = []
        self.popover.saved.connect(saved.append)
        self.popover.title_edit.setText("내일 3시 팀 회의")
        QTest.keyClick(self.popover.title_edit, Qt.Key.Key_Return)
        self.assertEqual(len(saved), 1)
        self.assertEqual(self.store.schedules.item(saved[0])["title"], "팀 회의")

    def test_past_time_is_flagged_in_title_tooltip(self):
        p = self.popover
        p.open_new(datetime(2020, 1, 1, 9, 0), datetime(2020, 1, 1, 10, 0))
        p.title_edit.setText("회의 3시")
        self.assertIn("지난 시각", p.title_edit.toolTip())
        p.open_new(datetime(2099, 1, 1, 9, 0), datetime(2099, 1, 1, 10, 0))
        p.title_edit.setText("회의 3시")
        self.assertNotIn("지난 시각", p.title_edit.toolTip())

    def test_ctrl_s_saves_without_confirmation_box(self):
        saved = []
        self.popover.saved.connect(saved.append)
        self.popover.title_edit.setText("내일 3시 팀 회의")
        with patch("alert_notes.schedule_popover.QMessageBox.information") as info:
            self.popover.save_shortcut.activated.emit()
        info.assert_not_called()
        self.assertEqual(len(saved), 1)


class DailyRepeatHiddenTest(unittest.TestCase):
    """매일 반복 일정은 할 일 목록·캘린더에 그리지 않는다(알림·검색은 유지)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from datetime import date
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.today = date.today()
        stamp = self.today.strftime("%Y%m%d")
        base = {"details": "", "item_type": "task", "all_day": False, "category": "lavender"}
        self.daily_id = self.store.schedules.save_item(dict(
            base, title="매일 약 먹기", start_at=f"{stamp}0900", end_at=f"{stamp}0901",
            recurrence_rule={"frequency": "daily", "interval": 1}, reminders=[0],
        ))
        self.weekly_id = self.store.schedules.save_item(dict(
            base, title="주간 보고", start_at=f"{stamp}1000", end_at=f"{stamp}1001",
            recurrence_rule={"frequency": "weekly", "interval": 1}, reminders=[0],
        ))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_calendar_skips_daily_repeat(self):
        from alert_notes.calendar import CalendarPanel
        panel = CalendarPanel(self.store)
        try:
            titles = [item["title"] for item in panel._filtered_schedule_items(
                self.today, self.today + timedelta(days=7))]
            self.assertNotIn("매일 약 먹기", titles)
            self.assertIn("주간 보고", titles)
        finally:
            destroy_widget(panel, self.app)

    def test_today_summary_and_postit_skip_daily_repeat(self):
        from alert_notes.schedule_postit_model import SchedulePostitModel
        from alert_notes.schedule_postit_settings import SchedulePostitPreferences
        from alert_notes.today_summary import TodaySummaryPanel
        titles = [item.title for item in SchedulePostitModel(self.store).items(
            self.today, SchedulePostitPreferences(), today=self.today)]
        self.assertNotIn("매일 약 먹기", titles)
        self.assertIn("주간 보고", titles)
        summary = TodaySummaryPanel(self.store)
        try:
            summary.refresh()
            rows = [summary.schedule_list.item(i).text() for i in range(summary.schedule_list.count())]
            self.assertFalse(any("매일 약 먹기" in row for row in rows))
            self.assertTrue(any("주간 보고" in row for row in rows))
        finally:
            destroy_widget(summary, self.app)

    def test_daily_repeat_still_exists_for_alarms_and_search(self):
        rows = self.store.schedules.items_for_range(
            self.today.strftime("%Y%m%d0000"), self.today.strftime("%Y%m%d2359"))
        self.assertIn(self.daily_id, [int(row["id"]) for row in rows])
        self.assertEqual(self.store.schedules.notifications(self.daily_id), [0])


class AlertQuickScheduleTest(unittest.TestCase):
    """알림 말풍선 아래 빠른 일정 입력.  빠른 일정 창과 같은 해석으로 저장한다."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from alert_notes.toma_pet_alert import TomaPetAlertDialog
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        reminder = {
            "notification_id": 22, "occurrence_at": "202610011000", "item_id": 5,
            "note_id": None, "title": "불용물품 - 조사계", "details": "", "start_at": "202610011000",
        }
        self.dialog = TomaPetAlertDialog(reminder, True, store=self.store)
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self):
        destroy_widget(self.dialog, self.app)
        self.store.close()
        self.temp.cleanup()

    def test_quick_input_has_focus_when_alert_opens(self):
        self.dialog.activateWindow()
        for _ in range(5):
            self.app.processEvents()
        self.assertIs(self.dialog.focusWidget(), self.dialog.quick_input)

    def test_enter_on_empty_quick_input_confirms_alert(self):
        completed = []
        self.dialog.completed.connect(completed.append)
        QTest.keyClick(self.dialog.quick_input, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(completed, [22])
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.store.schedules.items_for_range("200001010000", "209912312359"), [])

    def test_failed_quick_save_keeps_alert_open(self):
        completed = []
        self.dialog.completed.connect(completed.append)
        self.dialog.quick_input.setText("내일 10/5 회의")
        QTest.keyClick(self.dialog.quick_input, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(completed, [])
        self.assertTrue(self.dialog.isVisible())
        self.assertTrue(self.dialog.quick_status.isVisibleTo(self.dialog))

    def test_enter_saves_parsed_schedule_and_closes_alert(self):
        saved = []
        completed = []
        self.dialog.completed.connect(completed.append)
        self.dialog.quick_schedule_saved.connect(saved.append)
        self.dialog.quick_input.setText("내일 3시 팀 회의")
        self.assertIn("15:00", self.dialog.quick_time_button.text())
        QTest.keyClick(self.dialog.quick_input, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(len(saved), 1)
        item = self.store.schedules.item(saved[0])
        self.assertEqual(item["title"], "팀 회의")
        start = datetime.strptime(item["start_at"], "%Y%m%d%H%M")
        self.assertEqual(start.hour, 15)
        self.assertEqual(start.date(), (datetime.now() + timedelta(days=1)).date())
        self.assertEqual(self.store.schedules.notifications(saved[0]), [0])
        # 적은 일정을 저장한 뒤 알림은 ‘확인’과 같이 닫힌다.
        self.assertEqual(completed, [22])
        self.assertFalse(self.dialog.isVisible())

    def test_time_only_saves_untitled_schedule_with_alarm(self):
        saved = []
        self.dialog.quick_schedule_saved.connect(saved.append)
        self.dialog.quick_input.setText("내일 3시")
        item_id = self.dialog.save_quick_schedule()
        self.assertEqual(saved, [item_id])
        item = self.store.schedules.item(item_id)
        self.assertEqual(item["title"], "제목없음")
        self.assertEqual(datetime.strptime(item["start_at"], "%Y%m%d%H%M").hour, 15)
        self.assertEqual(self.store.schedules.notifications(item_id), [0])
        self.assertEqual(self.dialog.quick_input.text(), "")
        self.assertTrue(self.dialog.isVisible())

    def test_empty_input_saves_nothing(self):
        self.dialog.quick_input.setText("   ")
        self.assertIsNone(self.dialog.save_quick_schedule())
        self.assertTrue(self.dialog.quick_status.isVisibleTo(self.dialog))
        self.assertEqual(self.store.schedules.items_for_range("200001010000", "209912312359"), [])

    def test_enter_outside_quick_input_confirms_alert(self):
        completed = []
        self.dialog.completed.connect(completed.append)
        QTest.keyClick(self.dialog, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(completed, [22])
        self.assertFalse(self.dialog.isVisible())

    def test_action_buttons_have_no_extra_vertical_room(self):
        from PyQt6.QtWidgets import QPushButton
        for name in ("tomaAlertPrimaryButton", "tomaAlertSecondaryButton"):
            button = self.dialog.findChild(QPushButton, name)
            self.assertEqual(button.height(), 30)

    def test_without_store_the_input_is_not_shown(self):
        from alert_notes.toma_pet_alert import TomaPetAlertDialog
        dialog = TomaPetAlertDialog({"id": 1, "note_id": 2, "note_title": "메모", "note_content": "", "memo": ""}, False)
        try:
            self.assertFalse(hasattr(dialog, "quick_input"))
        finally:
            destroy_widget(dialog, self.app)


if __name__ == "__main__":
    unittest.main()
