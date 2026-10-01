import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLayout, QMessageBox, QVBoxLayout, QWidget

from alert_notes.calendar import CalendarPanel
from alert_notes.schedule_editor import ScheduleEditor
from alert_notes.schedule_popover import StandaloneSchedulePopover
from alert_notes.schedule_recurrence import DATETIME_FMT, normalize_rule
from alert_notes.sqlite_store import NoteReminderStore
from main_window import MainWindow
from qt_test_support import destroy_widget
from ui_theme import scaled_stylesheet


class ScheduleEditorStage3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "notes.db"
        self.store = NoteReminderStore(self.path, "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _item(self, title: str, item_type: str) -> int:
        return self.store.schedules.save_item({
            "title": title,
            "item_type": item_type,
            "start_at": "202609081000",
            "end_at": "202609081100",
        })

    def test_calendar_uses_compact_schedule_and_full_task_entry(self):
        panel = CalendarPanel(self.store)
        panel.resize(1200, 760)
        panel.show()
        self.app.processEvents()

        QTest.mouseClick(panel.new_task_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(panel._drawer_open)
        self.assertEqual(panel.schedule_editor._editor_kind, "task")
        self.assertEqual(panel.schedule_editor.heading.text(), "새 할 일")
        self.assertFalse(panel.schedule_editor.form.isRowVisible(panel.schedule_editor.end_edit))

        panel._close_drawer()
        QTest.mouseClick(panel.new_schedule_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(panel._drawer_open)
        self.assertTrue(panel.schedule_popover.isVisible())
        self.assertEqual(panel.schedule_popover.heading.text(), "새 일정")
        self.assertIsNone(panel.schedule_popover.item_id)
        panel.schedule_popover.title_edit.setText("간단 일정 저장 확인")
        QTest.mouseClick(panel.schedule_popover.save_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        saved = self.store.schedules.item(panel.schedule_popover.item_id)
        self.assertEqual(saved["title"], "간단 일정 저장 확인")
        self.assertEqual(saved["item_type"], "event")
        destroy_widget(panel, self.app)

    def test_quick_schedule_shortcut_opens_only_standalone_popover(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        calls = []
        popover = MagicMock()
        window = SimpleNamespace(
            open_today_schedule=lambda: calls.append("today"),
            note_store=self.store,
            _ui_scale=1.0,
            _quick_schedule_popover=None,
            _standalone_schedule_saved=lambda _item_id: None,
            _standalone_schedule_full_edit=lambda _values: None,
        )
        with patch("main_window.StandaloneSchedulePopover", return_value=popover) as create:
            MainWindow.show_quick_schedule(window)
            MainWindow.show_quick_schedule(window)
        create.assert_called_once_with(self.store)
        self.assertEqual(popover.open_at_current_time.call_count, 2)
        popover.open_at_current_time.assert_called_with(1.0)
        self.assertEqual(calls, [])

    def test_standalone_compact_popover_relative_input_and_save(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            popover.open_at_current_time()
            self.app.processEvents()
            self.assertTrue(popover.isVisible())
            self.assertIsNone(popover.parentWidget())
            reference = popover._relative_base
            popover.title_edit.setText("1시간 후 회의")
            self.assertEqual(popover.current_range()[0], reference + timedelta(hours=1))
            self.assertEqual(popover.parsed_title(), "회의")
            QTest.mouseClick(popover.save_button, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertFalse(popover.isVisible())
            saved = self.store.schedules.item(popover.item_id)
            self.assertEqual(saved["title"], "회의")
            self.assertEqual(saved["start_at"], (reference + timedelta(hours=1)).strftime(DATETIME_FMT))
        finally:
            destroy_widget(popover, self.app)

    def test_quick_alarm_stays_available_when_details_are_closed(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            popover.open_at_current_time()
            self.app.processEvents()
            compact_size = popover.size()
            self.assertFalse(popover.reminder_chip.isChecked())
            self.assertTrue(popover.at_time_button.isVisible())
            self.assertTrue(popover.five_before_button.isVisible())
            QTest.mouseClick(popover.at_time_button, Qt.MouseButton.LeftButton)
            QTest.mouseClick(popover.five_before_button, Qt.MouseButton.LeftButton)
            popover.reminder_edit.setText("30")
            self.assertEqual(popover.values()["reminders"], [0, 5, 30])
            popover.reminder_shortcuts[2].activated.emit()
            self.assertEqual(popover.values()["reminders"], [0, 5, 30, 60])
            popover.title_edit.setFocus()
            QTest.keyClick(popover.title_edit, Qt.Key.Key_Q, Qt.KeyboardModifier.AltModifier)
            self.app.processEvents()
            self.assertEqual(popover.values()["reminders"], [0, 30, 60])
            popover.reminder_chip.setChecked(True)
            self.app.processEvents()
            self.assertGreaterEqual(popover.height(), compact_size.height())
            self.assertEqual(popover.body_scroll.verticalScrollBar().maximum(), 0)
            self.assertTrue(popover.reminder_details.isVisible())
            popover.reminder_chip.setChecked(False)
            self.app.processEvents()
            self.assertFalse(popover.reminder_details.isVisible())
            self.assertEqual(popover.body_scroll.verticalScrollBar().maximum(), 0)
            self.assertTrue(popover.title_edit.isVisible())
        finally:
            destroy_widget(popover, self.app)

    def test_title_enter_saves_quick_schedule(self):
        # 2026-10-01: 제목 칸 Enter는 저장이다.
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            popover = StandaloneSchedulePopover(self.store)
            try:
                popover.open_at_current_time()
                popover.title_edit.setText("Enter 저장")
                popover.title_edit.setFocus()
                self.app.processEvents()
                self.assertEqual(popover.reminder_edit.placeholderText(), "예: 10, 5, 3분 전")
                QTest.keyClick(popover.title_edit, key)
                self.app.processEvents()
                self.assertFalse(popover.isVisible())
                self.assertIsNotNone(popover.item_id)
            finally:
                destroy_widget(popover, self.app)
        self.assertEqual(
            self.store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0], 2
        )

    def test_single_time_and_range_update_chips_alarm_and_saved_mode(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            popover.open_at_current_time()
            popover.title_edit.setText("내일 4시 회의")
            self.app.processEvents()
            self.assertTrue(popover.point_chip.isChecked())
            self.assertEqual(popover.duration_label.text(), "종료 없음")
            self.assertNotIn("내일", popover.time_summary_button.text())
            self.assertIn("16:00", popover.parse_label.text())
            self.assertEqual(popover.time_chip.text(), "종료 시각")
            self.assertEqual(popover.reminder_time_edit.time().toString("HH:mm"), "16:00")
            self.assertEqual(popover.values()["time_mode"], "point")
            self.assertEqual(popover.values()["end_at"], popover._start.strftime("%Y%m%d") + "1601")
            popover.reminder_chip.setChecked(True)
            self.app.processEvents()
            self.assertEqual(popover.reminder_time_edit.time().toString("HH:mm"), "16:00")
            popover.reminder_chip.setChecked(False)
            QTest.mouseClick(popover.time_chip, Qt.MouseButton.LeftButton)
            self.assertEqual(popover.values()["time_mode"], "range")
            self.assertEqual(popover.values()["end_at"], popover._start.strftime("%Y%m%d") + "1700")
            QTest.mouseClick(popover.point_chip, Qt.MouseButton.LeftButton)
            self.assertEqual(popover.values()["time_mode"], "point")
            QTest.mouseClick(popover.save_button, Qt.MouseButton.LeftButton)
            saved = self.store.schedules.item(popover.item_id)
            self.assertEqual(saved["time_mode"], "point")
            self.assertEqual(saved["end_at"], saved["start_at"][:-2] + "01")
            popover.open_item(popover.item_id)
            self.assertTrue(popover.point_chip.isChecked())
            self.assertEqual(popover.time_chip.text(), "종료 시각")
            popover.title_edit.setText("내일 4시~5시 회의")
            self.assertEqual(popover.values()["time_mode"], "range")
            self.assertTrue(popover.time_chip.isChecked())
            popover.title_edit.setText("내일 5시 회의")
            self.assertEqual(popover.duration_label.text(), "종료 없음")
            self.assertIn("17:00", popover.parse_label.text())
            self.assertTrue(popover.point_chip.isChecked())
            self.assertEqual(popover.reminder_time_edit.time().toString("HH:mm"), "17:00")
        finally:
            destroy_widget(popover, self.app)

    def test_alarm_buttons_and_shortcuts_can_combine(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            popover.open_at_current_time()
            QTest.mouseClick(popover.at_time_button, Qt.MouseButton.LeftButton)
            QTest.mouseClick(popover.five_before_button, Qt.MouseButton.LeftButton)
            self.assertEqual(popover.values()["reminders"], [0, 5])
            popover.reminder_chip.setChecked(True)
            QTest.mouseClick(popover.reminder_preset_buttons[30], Qt.MouseButton.LeftButton)
            QTest.mouseClick(popover.reminder_preset_buttons[60], Qt.MouseButton.LeftButton)
            self.assertEqual(popover.values()["reminders"], [0, 5, 30, 60])
            popover.reminder_shortcuts[0].activated.emit()
            self.assertGreater(len(popover.values()["reminders"]), 1)
        finally:
            destroy_widget(popover, self.app)

    def test_detail_page_keeps_size_without_clipping_footer(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            popover.open_at_current_time(1.5)
            compact_height = popover.height()
            popover.title_edit.setText("내일 4시 회의")
            for chip in (popover.repeat_chip, popover.memo_chip, popover.dday_chip):
                chip.click()
            self.app.processEvents()
            self.assertGreater(popover.height(), compact_height)
            self.assertTrue(popover.dday_hint.isVisible())
            self.assertFalse(popover.memo_edit.isVisible())
            self.assertEqual(popover.body_scroll.verticalScrollBar().maximum(), 0)
            self.assertLess(
                popover.dday_hint.mapTo(popover, popover.dday_hint.rect().bottomLeft()).y(),
                popover.save_button.mapTo(popover, popover.save_button.rect().topLeft()).y(),
            )
            self.assertGreaterEqual(popover.save_button.width(), popover.save_button.sizeHint().width())
            self.assertEqual(popover.save_button.toolTip(), "일정 저장 (Ctrl+S)")
        finally:
            destroy_widget(popover, self.app)

    def test_ctrl_s_saves_without_confirmation(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            popover.open_at_current_time()
            popover.title_edit.setText("Ctrl+S 저장")
            popover.at_time_button.setChecked(True)
            popover.reminder_edit.setFocus()
            self.app.processEvents()
            with patch("alert_notes.schedule_popover.QMessageBox.information") as notice:
                QTest.keyClick(popover.reminder_edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
                self.app.processEvents()
            # 2026-10-01: Ctrl+S도 저장 버튼처럼 확인 창 없이 저장한다.
            self.assertEqual(notice.call_count, 0)
            self.assertFalse(popover.isVisible())
            self.assertEqual(self.store.schedules.notifications(popover.item_id), [0])
        finally:
            destroy_widget(popover, self.app)

    def test_alarm_details_date_time_weekdays_and_saved_values_reopen(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            start = datetime(2026, 9, 22, 15, 42)
            popover.open_new(start, start + timedelta(hours=1))
            popover.show()
            self.app.processEvents()
            popover.reminder_chip.setChecked(True)
            popover.reminder_time_edit.setTime(popover.reminder_time_edit.time().addSecs(10 * 60))
            # 시작 이후도 유효한 알림이다. 기존 '이후 불가' 정책을 대체한다.
            self.assertEqual(popover.values()["reminders"], [-10])
            self.assertFalse(popover._detail_alarm_invalid)
            popover.reminder_time_edit.setTime(popover.reminder_time_edit.time().addSecs(-40 * 60))
            popover.reminder_repeat_buttons["weekdays"].click()
            self.assertEqual(popover.values()["reminders"], [30])
            self.assertEqual(popover.values()["recurrence_rule"]["weekdays"], [0, 1, 2, 3, 4])
            popover.title_edit.setText("반복 알림")
            self.assertTrue(popover.save())
            item_id = popover.item_id
            self.assertEqual(self.store.schedules.notifications(item_id), [30])
            self.assertTrue(popover.open_item(item_id))
            self.assertEqual(popover.values()["reminders"], [30])
            self.assertTrue(popover.reminder_repeat_buttons["weekdays"].isChecked())
        finally:
            destroy_widget(popover, self.app)

    def test_popover_save_preserves_repeat_memo_and_dday_link(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            start = datetime(2026, 9, 28, 14, 5)
            popover.open_new(start, start + timedelta(hours=1))
            popover.show()
            popover.title_edit.setText("통합 기능 보존")
            popover.repeat_chip.click()
            popover.repeat_combo.setCurrentIndex(popover.repeat_combo.findData("daily"))
            popover.memo_chip.click()
            popover.memo_edit.setPlainText("준비 메모")
            popover.memo_chip.click()
            popover.dday_chip.click()

            self.assertTrue(popover.save())
            item = self.store.schedules.item(popover.item_id)
            self.assertEqual(item["details"], "준비 메모")
            self.assertIsNotNone(item["note_id"])
            self.assertEqual(normalize_rule(item["recurrence_rule"])["frequency"], "daily")
            note = self.store.note(int(item["note_id"]))
            self.assertEqual(note["d_day_at"], "202609281405")
            self.assertEqual(note["d_day_label"], "통합 기능 보존")
        finally:
            destroy_widget(popover, self.app)

    def test_standalone_header_drag_keeps_layout_and_position(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            popover.open_at_current_time()
            self.app.processEvents()
            original = popover.pos()
            title_rect = popover.title_edit.geometry()
            QTest.mousePress(popover.heading, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
            QTest.mouseMove(popover.heading, QPoint(38, 18))
            QTest.mouseRelease(popover.heading, Qt.MouseButton.LeftButton, pos=QPoint(38, 18))
            self.app.processEvents()
            self.assertNotEqual(popover.pos(), original)
            moved = popover.pos()
            self.assertEqual(popover.title_edit.geometry(), title_rect)
            QTest.mousePress(popover, Qt.MouseButton.LeftButton, pos=QPoint(190, 24))
            QTest.mouseMove(popover, QPoint(210, 30))
            QTest.mouseRelease(popover, Qt.MouseButton.LeftButton, pos=QPoint(210, 30))
            self.app.processEvents()
            self.assertNotEqual(popover.pos(), moved)
            moved = popover.pos()
            popover.title_edit.setText("1시간 후 회의")
            self.app.processEvents()
            self.assertEqual(popover.pos(), moved)
            popover.dismiss()
            popover.open_at_current_time()
            self.app.processEvents()
            self.assertEqual(popover.pos(), moved)
            bounds = popover._standalone_bounds
            popover._manual_position = QPoint(bounds.right() + 500, bounds.bottom() + 500)
            popover._position()
            self.assertTrue(bounds.contains(popover.geometry().bottomRight()))
            popover.escape_button.click()
            self.assertFalse(popover.isVisible())
        finally:
            destroy_widget(popover, self.app)

    def test_standalone_uses_the_existing_popover_theme_at_current_scale(self):
        popover = StandaloneSchedulePopover(self.store)
        try:
            popover.open_at_current_time(1.0)
            self.assertEqual(popover.styleSheet(), scaled_stylesheet(1.0))
            self.assertIn("QFrame#schedulePopover", popover.styleSheet())
            self.assertIn("QLineEdit#popoverTitleEdit:focus", popover.styleSheet())
            popover.open_at_current_time(1.25)
            self.assertEqual(popover.styleSheet(), scaled_stylesheet(1.25))
        finally:
            destroy_widget(popover, self.app)

    def test_calendar_slot_alone_sets_relative_time_reference(self):
        panel = CalendarPanel(self.store)
        panel.resize(1200, 760)
        panel.show()
        self.app.processEvents()
        slot = datetime(2026, 9, 8, 10)
        panel._canvas_range(slot, slot + timedelta(minutes=90))
        panel.schedule_popover.title_edit.setText("1시간 후 회의")
        self.assertEqual(panel.schedule_popover.current_range()[0], slot + timedelta(hours=1))
        self.assertEqual(panel.schedule_popover.current_range()[1], slot + timedelta(hours=2, minutes=30))
        panel._new_schedule(slot)
        reference = panel.schedule_popover._relative_base
        self.assertEqual(reference.date(), datetime.now().date())
        panel.schedule_popover.title_edit.setText("1시간 후 회의")
        self.assertEqual(panel.schedule_popover.current_range()[0], reference + timedelta(hours=1))
        destroy_widget(panel, self.app)

    def test_both_entry_buttons_fit_before_opening_a_narrow_editor(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        panel = CalendarPanel(self.store)
        layout.addWidget(panel)
        host.setMinimumSize(0, 0)
        host.resize(680, 760)
        host.show()
        panel.update_responsive_layout(680)
        self.app.processEvents()

        # Secondary creation is intentionally moved to the overflow menu.
        for button in (panel.new_schedule_button, panel.header_overflow):
            left = button.mapTo(host, QPoint()).x()
            self.assertGreaterEqual(left, 0)
            self.assertLessEqual(left + button.width(), host.width())
            self.assertTrue(button.isVisible())
        destroy_widget(host, self.app)

    def test_task_form_has_one_deadline_and_persists_dday_choice(self):
        editor = ScheduleEditor(self.store)
        editor.new_item(
            datetime(2026, 9, 8, 18, 0),
            datetime(2026, 9, 8, 19, 0),
            item_type="task",
        )
        editor.title_edit.setText("보고서 제출")
        editor.count_as_dday_check.setChecked(True)
        self.assertFalse(editor.form.isRowVisible(editor.type_combo))
        self.assertFalse(editor.form.isRowVisible(editor.end_edit))
        self.assertEqual(editor.form.labelForField(editor.start_edit).text(), "마감")
        QTest.mouseClick(editor.save_button, Qt.MouseButton.LeftButton)

        saved = self.store.schedules.item(editor.item_id)
        self.assertEqual(saved["item_type"], "task")
        self.assertEqual(saved["start_at"], "202609081800")
        self.assertEqual(saved["end_at"], "202609081900")
        self.assertEqual(saved["count_as_dday"], 1)
        destroy_widget(editor, self.app)

    def test_saved_kind_reopens_the_matching_fixed_form(self):
        task_id = self._item("할 일", "task")
        event_id = self._item("일정", "event")
        editor = ScheduleEditor(self.store)

        editor.load_item(task_id)
        self.assertEqual(editor._editor_kind, "task")
        self.assertEqual(editor.heading.text(), "할 일 편집")
        self.assertFalse(editor.form.isRowVisible(editor.end_edit))
        editor.load_item(event_id)
        self.assertEqual(editor._editor_kind, "event")
        self.assertEqual(editor.heading.text(), "일정 편집")
        self.assertTrue(editor.form.isRowVisible(editor.end_edit))
        self.assertFalse(editor.count_as_dday_check.isVisible())
        destroy_widget(editor, self.app)

    def test_existing_task_from_quick_popover_keeps_its_kind_in_full_edit(self):
        task_id = self._item("빠른 할 일", "task")
        panel = CalendarPanel(self.store)
        panel.schedule_popover.open_item(task_id)
        self.assertEqual(panel.schedule_popover.values()["item_type"], "task")
        panel._open_full_editor(panel.schedule_popover.values())
        self.assertEqual(panel.schedule_editor._editor_kind, "task")
        self.assertFalse(panel.schedule_editor.form.isRowVisible(panel.schedule_editor.end_edit))
        destroy_widget(panel, self.app)

    def test_unknown_stored_kind_is_not_automatically_converted(self):
        item_id = self._item("종류 확인", "event")
        self.store.conn.execute(
            "UPDATE schedule_items SET item_type='unknown' WHERE id=?", (item_id,)
        )
        self.store.conn.commit()
        editor = ScheduleEditor(self.store)
        with patch.object(QMessageBox, "warning") as warning:
            editor.load_item(item_id)
        warning.assert_called_once()
        raw = self.store.conn.execute(
            "SELECT item_type FROM schedule_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        self.assertEqual(raw, "unknown")
        destroy_widget(editor, self.app)

    def test_additive_dday_column_upgrade_is_backed_up(self):
        self.store.close()
        connection = sqlite3.connect(self.path)
        connection.execute("ALTER TABLE schedule_items DROP COLUMN count_as_dday")
        connection.commit()
        connection.close()

        self.store = NoteReminderStore(self.path, "새 메모")
        self.assertIsNotNone(self.store.upgrade_backup_path)
        backup = sqlite3.connect(self.store.upgrade_backup_path)
        try:
            old_columns = {
                row[1] for row in backup.execute("PRAGMA table_info(schedule_items)")
            }
        finally:
            backup.close()
        new_columns = {
            row[1] for row in self.store.conn.execute("PRAGMA table_info(schedule_items)")
        }
        self.assertNotIn("count_as_dday", old_columns)
        self.assertIn("count_as_dday", new_columns)

    def test_additive_time_mode_upgrade_preserves_old_schedule(self):
        item_id = self._item("기존 범위 일정", "event")
        self.store.close()
        connection = sqlite3.connect(self.path)
        connection.execute("ALTER TABLE schedule_items DROP COLUMN time_mode")
        connection.commit()
        connection.close()

        self.store = NoteReminderStore(self.path, "새 메모")
        self.assertIsNotNone(self.store.upgrade_backup_path)
        self.assertEqual(self.store.schedules.item(item_id)["title"], "기존 범위 일정")
        self.assertEqual(self.store.schedules.item(item_id)["time_mode"], "range")


if __name__ == "__main__":
    unittest.main()
