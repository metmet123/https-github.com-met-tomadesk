"""승인 시안: 고정 크기·상세 페이지·컨트롤 가림·배율 검증."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from datetime import datetime
from tempfile import TemporaryDirectory
import unittest

from PyQt6.QtCore import QDate, QPoint, QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFrame, QWidget, QVBoxLayout, QLayout, QPushButton
from alert_notes.schedule_popover import StandaloneSchedulePopover
from alert_notes.categories import save_schedule_categories, schedule_categories
from alert_notes.calendar import CalendarPanel
from ui_theme import scaled_stylesheet
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import destroy_widget


class ScheduleUiStage34Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.popover = StandaloneSchedulePopover(self.store)

    def tearDown(self):
        destroy_widget(self.popover, self.app)
        self.store.close()
        self.temp.cleanup()

    def capture(self, suffix):
        folder = os.environ.get("TOMADESK_STAGE34_CAPTURES")
        if folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            self.assertTrue(self.popover.grab().save(str(target / f"schedule-{suffix}.png")))

    def assert_inside(self, widget):
        if not widget.isVisible():
            return  # 시간 모드의 반대 동작만 보이는 새 UI
        rect = QRect(widget.mapTo(self.popover, QPoint()), widget.size())
        self.assertTrue(self.popover.rect().contains(rect), f"{widget.objectName()}: {rect}")
        self.assertFalse(widget.visibleRegion().isEmpty(), widget.objectName())
        self.assertTrue(widget.visibleRegion().boundingRect().contains(widget.rect()),
                        f"clipped {widget.objectName()}: {widget.visibleRegion().boundingRect()} / {widget.rect()}")

    def test_compact_form_measured_rows_and_five_categories(self):
        p = self.popover
        p.open_at_current_time(1.0)
        self.app.processEvents()
        self.assertEqual(p.form.width(), 336)
        self.assertEqual(p.escape_button.height(), 28)
        self.assertEqual(p.title_edit.height(), 36)
        self.assertEqual(p.time_summary_button.height(), 30)
        self.assertEqual(p.time_chip.height(), 26)
        self.assertEqual(p.none_reminder_button.height(), 28)
        self.assertEqual(p.repeat_chip.height(), 26)
        self.assertFalse(p.parse_label.isVisible())
        self.assertEqual(len(p.category_chips), 5)
        self.assertFalse(p.category_overflow_button.isVisible())
        self.assertEqual({chip.y() for chip in p.category_chips.values()},
                         {next(iter(p.category_chips.values())).y()})
        self.assertTrue(all(chip.height() == 24 for chip in p.category_chips.values()))
        self.assertLessEqual(p.full_edit_button.parentWidget().height(), 44)
        self.assertEqual(p.save_button.height(), 32)
        self.assertEqual(p.full_edit_button.height(), 28)
        self.assertLessEqual(abs(p.form.height() - p.shell_layout.sizeHint().height()), 2)
        compact = p.form.height()
        p.time_summary_button.click()
        self.app.processEvents()
        self.assertTrue(p.time_row.isVisible())
        self.assertGreater(p.form.height(), compact)
        self.assertLessEqual(abs(p.form.height() - p.shell_layout.sizeHint().height()), 2)

    def test_scales_and_detail_page_preserve_size_footer_and_draft(self):
        p = self.popover
        for scale in (1.0, 1.25, 1.5):
            with self.subTest(scale=scale):
                p.open_at_current_time(scale)
                self.app.processEvents()
                size, save_y, title_y = p.size(), p.save_button.mapTo(p, QPoint()).y(), p.title_edit.mapTo(p, QPoint()).y()
                self.capture(f"{scale}-empty")
                p.title_edit.setText("10.2. 10~18시 견학 5분전")
                self.app.processEvents()
                self.assertGreaterEqual(p.height(), size.height())
                self.assertEqual(p.title_edit.mapTo(p, QPoint()).y(), title_y)
                self.assertEqual(p.parse_label.text(), "10월 2일 · 10:00–18:00\n10:00의 5분 전 알람 · 09:55")
                for widget in (p.title_edit, p.parse_label, p.point_chip, p.time_chip, p.duration_chip,
                               p.at_time_button, p.five_before_button, p.reminder_edit, p.reminder_chip,
                               p.save_button, *p.category_chips.values()):
                    self.assert_inside(widget)
                for button in (p.point_chip, p.time_chip, p.duration_chip):
                    self.assertLessEqual(button.fontMetrics().horizontalAdvance(button.text()) + 8,
                                         button.width(), button.text())
                self.assertFalse(p.parse_label.isVisible())
                self.assertEqual(p.title_edit.toolTip(), p.parse_label.toolTip())
                self.capture(f"{scale}-parsed")
                before = p.values()
                for _ in range(3):
                    p.reminder_chip.click()
                    self.app.processEvents()
                    self.assertGreater(p.height(), size.height())
                    self.assertEqual(p.width(), size.width())
                    self.assertTrue(p.reminder_details.isVisible())
                    self.assertTrue(p.title_edit.isVisible())
                    self.assert_inside(p.reminder_date_edit)
                    self.assert_inside(p.reminder_time_edit)
                    self.capture(f"{scale}-details")
                    p.reminder_chip.click()
                    self.app.processEvents()
                    self.assertEqual(p.values(), before)
                    self.assertFalse(p.reminder_details.isVisible())
                    self.assertEqual(p.title_edit.mapTo(p, QPoint()).y(), title_y)
                print(f"STAGE34 scale={scale} size={size.width()}x{size.height()} save_y={save_y} title_y={title_y}")
                for chip, field in ((p.time_summary_button, p.time_row), (p.repeat_chip, p.repeat_combo),
                                    (p.memo_chip, p.memo_edit), (p.dday_chip, p.dday_hint)):
                    chip.click()
                    self.app.processEvents()
                    self.assertIs(p._active_detail, field)
                    self.assertGreater(p.height(), size.height())
                    self.assertEqual(p.width(), size.width())
                    self.assertTrue(p.title_edit.isVisible())
                    self.assert_inside(field)
                    if field is p.time_row:
                        for editor in (p.start_time_edit, p.end_time_edit):
                            self.assert_inside(editor)
                    self.capture(f"{scale}-{field.objectName() or type(field).__name__}")
                    chip.click()

    def test_only_one_extra_page_and_escape_preserves_settings(self):
        p = self.popover
        p.open_at_current_time()
        p.title_edit.setText("회의")
        p.repeat_chip.click()
        self.assertIs(p._active_detail, p.repeat_combo)
        p._escape_requested()
        self.assertIsNone(p._active_detail)
        self.assertTrue(p.repeat_chip.isChecked())
        p.memo_chip.click()
        p.memo_edit.setPlainText("준비물")
        self.assertFalse(p.repeat_combo.isVisible())
        p.memo_chip.click()
        self.assertEqual(p.memo_chip.text(), "+ 메모")
        self.assertEqual(p.values()["details"], "준비물")
        p.memo_chip.click()
        self.assertIs(p._active_detail, p.memo_edit)
        self.assertEqual(p.memo_edit.toPlainText(), "준비물")
        p.clear_detail_button.click()
        self.assertEqual(p.values()["details"], "")
        self.assertTrue(p.title_edit.isVisible())
        p.reminder_chip.click()
        QTest.keyClick(p.reminder_date_edit, Qt.Key.Key_Escape)
        self.assertIsNone(p._active_detail)
        self.assertTrue(p.isVisible())

    def test_manual_alarm_summary_updates_without_natural_language(self):
        p = self.popover
        p.open_at_current_time()
        p._select_main_reminder(5, True)
        self.assertTrue(p.parse_label.text().startswith("알림 "))
        self.assertNotIn("읽음", p.parse_label.text())
        self.assertEqual(p.five_before_button.text(), "5분")
        self.assertTrue(p.five_before_button.isChecked())

    def test_compact_rows_do_not_overlap_or_clip_at_supported_scales(self):
        p = self.popover
        for scale in (1.0, 1.25, 1.5):
            with self.subTest(scale=scale):
                p.open_at_current_time(scale)
                self.app.processEvents()
                for layout in (p.category_row, p.extras_layout):
                    controls = [layout.itemAt(i).widget() for i in range(layout.count())]
                    controls = [w for w in controls if w is not None and w.isVisible()]
                    rects = [QRect(w.mapTo(p.body, QPoint()), w.size()) for w in controls]
                    for widget, rect in zip(controls, rects):
                        self.assertTrue(p.body.rect().contains(rect), widget.text())
                        reserve = 22 if widget in p.category_chips.values() else 14
                        self.assertLessEqual(
                            widget.fontMetrics().horizontalAdvance(widget.text()) + reserve,
                            widget.width(), widget.text(),
                        )
                    for i, first in enumerate(rects):
                        for second in rects[i + 1:]:
                            self.assertFalse(first.intersects(second), (first, second))
                self.assertFalse(p.parse_label.isVisible())
                self.assertEqual(p.save_button.toolTip(), "일정 저장 (Ctrl+S)")
        p.form.setFixedWidth(300)
        p._render_category_chips()
        margins = p.shell_layout.contentsMargins()
        self.assertEqual(p._category_render_budget, 300 - margins.left() - margins.right()
                         - p.category_icon.sizeHint().width() - p.category_row.spacing())
        self.assertLessEqual(
            sum(p.category_row.itemAt(i).widget().width()
                for i in range(p.category_row.count())
                if p.category_row.itemAt(i).widget() is not None),
            p._category_render_budget + p.category_icon.width(),
        )

    def test_fast_alarm_buttons_preserve_multiple_choices(self):
        p = self.popover
        p.open_at_current_time()
        # 시간을 정하지 않은 빠른 일정 창은 알림 없이 시작한다.
        self.assertEqual(p._reminder_values(), [])
        p.at_time_button.click()
        p.five_before_button.click()
        self.assertEqual(p._reminder_values(), [0, 5])
        p.at_time_button.click()
        self.assertEqual(p._reminder_values(), [5])

    def test_final_popover_header_segments_alerts_and_category_overflow(self):
        rows = schedule_categories(self.store)
        rows.append({"id": "extra", "name": "추가", "color": "sky", "aliases": []})
        save_schedule_categories(self.store, rows)
        p = self.popover
        p.reload_categories()
        p.open_at_current_time()
        p._set_range(datetime(2026, 9, 28, 14, 5), datetime(2026, 9, 28, 15, 5))
        self.app.processEvents()

        self.assertEqual(p.heading.text(), "새 일정")
        self.assertEqual(p.range_label.text(), "9/28 (월)")
        self.assertEqual(p.escape_button.text(), "×")
        self.assertEqual(p.escape_button.toolTip(), "Esc")
        self.assertTrue(p.title_edit.hasFocus())
        self.assertEqual(p.title_edit.font().pixelSize(), 15)
        self.assertTrue(p.title_edit.font().bold())
        self.assertFalse(hasattr(p, "time_heading"))
        self.assertFalse(hasattr(p, "alarm_label"))
        self.assertFalse(p.date_edit.isVisible())

        self.assertEqual(p.time_summary_button.text(), "14:05 - 15:05 ▾")
        self.assertEqual(p.duration_label.text(), "1시간")
        p.time_summary_button.click()
        self.assertIs(p._active_detail, p.time_row)
        self.assertTrue(p.start_time_edit.isVisible())
        self.assertTrue(p.end_time_edit.isVisible())
        self.assertIn("▴", p.time_summary_button.text())
        p.time_summary_button.click()
        self.assertIn("▾", p.time_summary_button.text())

        self.assertTrue(p.time_chip.isVisible())
        self.assertTrue(p.duration_chip.isVisible())
        self.assertTrue(p.point_chip.isVisible())
        self.assertTrue(p.time_chip.isChecked())
        p.duration_chip.click()
        self.assertTrue(p.duration_chip.isChecked())
        self.assertIs(p._active_detail, p.duration_row)
        p.point_chip.click()
        self.assertTrue(p.point_chip.isChecked())
        self.assertEqual(p.values()["time_mode"], "point")

        # 시각이 있는 새 일정은 정각 알림으로 시작한다.
        self.assertFalse(p.none_reminder_button.isChecked())
        self.assertTrue(p.at_time_button.isChecked())
        p.at_time_button.click()
        p.ten_before_button.click()
        self.assertEqual(p.values()["reminders"], [10])
        self.assertFalse(p.none_reminder_button.isChecked())
        p.none_reminder_button.click()
        self.assertEqual(p.values()["reminders"], [])
        self.assertTrue(p.none_reminder_button.isChecked())

        self.assertTrue(p.category_overflow_button.text().startswith("+"))
        self.assertEqual(p.category_overflow_button.menu().actions()[-1].text(), "관리")
        remaining_action = next(
            action for action in p.category_overflow_button.menu().actions()
            if action.isCheckable()
        )
        remaining_id = next(
            row["id"] for row in p._category_specs if row["name"] == remaining_action.text()
        )
        remaining_action.trigger()
        self.assertEqual(p._category, remaining_id)
        self.assertEqual([p.repeat_chip.text(), p.memo_chip.text(), p.dday_chip.text()],
                         ["+ 반복", "+ 메모", "+ D-Day"])
        self.assertEqual(p.body_layout.spacing(), 7)
        self.assertEqual(p.full_edit_button.text(), "전체 편집 ↗")
        self.assertEqual(p.save_button.text(), "저장")
        self.assertTrue(any(w.objectName() == "popoverFooter" for w in p.findChildren(QWidget)))

        p.escape_button.click()
        self.assertFalse(p.isVisible())

    def test_long_custom_category_is_elided_without_losing_full_name(self):
        rows = schedule_categories(self.store)
        rows[0]["name"] = "이호조 결재올리기 업무"
        save_schedule_categories(self.store, rows)
        p = self.popover
        p.reload_categories()
        p.open_at_current_time()
        self.app.processEvents()
        chip = p.category_chips[rows[0]["id"]]
        self.assertIn("…", chip.text())
        self.assertIn(rows[0]["name"], chip.toolTip())
        # 글자·색 점·여백이 잘리지 않는 폭: 스타일이 적용된 실제 필요 폭 이상이어야 한다.
        self.assertLessEqual(chip.sizeHint().width(), chip.width())

    def test_selecting_category_keeps_visible_chip_count(self):
        """칩을 눌러도 첫 표시 때와 같은 개수·순서가 유지되고 넘침 버튼 문구가 잘리지 않는다."""
        rows = schedule_categories(self.store)
        for row, name in zip(rows, ["이호조", "인사랑", "교육", "제출", "기타"]):
            row["name"] = name
        save_schedule_categories(self.store, rows)
        p = self.popover
        p.reload_categories()
        p.open_at_current_time()
        self.app.processEvents()
        initial = list(p.category_chips)
        self.assertEqual(5, len(initial))
        for key in initial:
            p.category_chips[key].click()
            self.app.processEvents()
            self.assertEqual(initial, list(p.category_chips))
            self.assertTrue(p.category_chips[key].isChecked())
        # 칩이 더 많아 넘침 버튼이 보일 때 "+N ▾" 문구가 잘리지 않아야 한다.
        rows.append({**rows[-1], "id": "extra", "name": "추가"})
        save_schedule_categories(self.store, rows)
        p.reload_categories()
        self.app.processEvents()
        more = p.category_overflow_button
        self.assertTrue(more.text().startswith("+"))
        self.assertLessEqual(more.sizeHint().width(), more.width())

    def test_inline_reclick_duration_and_small_screen(self):
        p = self.popover
        p.open_at_current_time()
        p.title_edit.setText("다다음주 9시 회의")
        self.app.processEvents()
        compact = p.height()
        title_y = p.title_edit.mapTo(p, QPoint()).y()
        p.time_summary_button.click()
        self.app.processEvents()
        self.assertTrue(p.title_edit.isVisible())
        self.assertGreater(p.height(), compact)
        self.assertEqual(p.title_edit.mapTo(p, QPoint()).y(), title_y)
        self.assertIn("▴", p.time_summary_button.text())
        p.time_summary_button.click()
        self.assertIsNone(p._active_detail)
        self.assertEqual(p.height(), compact)
        p.duration_chip.click()
        self.assertTrue(p.duration_row.isVisible())
        next(b for b in p.duration_row.findChildren(QPushButton) if b.text() == "1시간 30분").click()
        self.assertEqual((p._end - p._start).total_seconds(), 5400)
        p.duration_chip.click()
        self.assertEqual(p.height(), compact)
        p.memo_chip.click()
        p.memo_edit.setPlainText("준비물")
        p.memo_chip.click()
        self.assertIsNone(p._active_detail)
        self.assertEqual(p.values()["details"], "준비물")
        p.dday_chip.click()
        self.assertTrue(p.dday_chip.isChecked())
        p.clear_detail_button.click()
        self.assertFalse(p.dday_chip.isChecked())
        p._standalone_bounds = QRect(0, 0, 600, 480)
        p.reminder_chip.click()
        self.app.processEvents()
        self.assertLessEqual(p.height(), 464)
        self.assertTrue(p._standalone_bounds.contains(p.geometry()))
        self.assertGreater(p.body_scroll.verticalScrollBar().maximum(), 0)
        self.assert_inside(p.save_button)
        p._escape_requested()
        self.assertTrue(p.isVisible())
        self.assertIsNone(p._active_detail)

    def test_recognition_summary_and_token_cancellation(self):
        p = self.popover
        p.open_at_current_time()
        p.title_edit.setText("테스트 9.10. 9~3시 5분 전")
        self.assertEqual(p.parse_label.text(), "9월 10일 · 09:00–15:00\n09:00의 5분 전 알람 · 08:55")
        self.assertEqual(p.parse_label.toolTip(), p.parse_label.text())
        alarm = next(s for s in p._parsed.spans if s.kind == "reminder")
        p._cancel_parsed_token(alarm.start, alarm.end, alarm.kind)
        # 읽은 알림을 취소하면 기본 정각 알림으로 돌아간다.
        self.assertEqual(p.parse_label.text(), "9월 10일 · 09:00–15:00\n09:00의 정각 알람 · 09:00")
        self.assertIn("5분 전", p.parsed_title())
        p.title_edit.setText("일반 제목")
        # 시간 표현이 사라지면 정각 기본 알림도 함께 빠진다.
        self.assertEqual(p.parse_label.text(), "")

    def test_recognition_summary_point_after_and_minutes(self):
        p = self.popover
        p.open_at_current_time()
        p.title_edit.setText("회의 18시 5분 후")
        self.assertEqual(p.parse_label.text(), "18:00\n18:00의 5분 후 알람 · 18:05")
        # 오전·오후 없는 지난 아침 시각은 저녁으로 읽으므로 오전을 적는다.
        p.title_edit.setText("회의 오전 9시 30분 알람")
        self.assertIn("09:30", p.parse_label.text())
        self.assertIn("정각 알람", p.parse_label.text())

    def test_chip_trim_geometry_cursor_and_relative_cancel(self):
        p = self.popover
        p.open_at_current_time()
        edit = p.title_edit
        edit.setText("회의 이틀후 9~10시 5분 전")
        self.app.processEvents()
        spans = edit.token_spans()
        self.assertEqual([s.text for s in spans], ["이틀후", "9~10시", "5분 전"])
        before = [edit.token_rect(s) for s in spans]
        edit.setCursorPosition(0)
        self.app.processEvents()
        after = [edit.token_rect(s) for s in spans]
        for a, b in zip(before, after):
            self.assertLessEqual(abs(a.x() - b.x()), 1)
            self.assertLess(a.height(), edit.height())
        date_span = spans[0]
        QTest.mouseDClick(edit, Qt.MouseButton.LeftButton, pos=edit.token_rect(date_span).center())
        self.assertIn("이틀후", p.parsed_title())
        self.assertNotIn("date", {s.kind for s in edit.token_spans()})
        self.assertNotIn("월", p.parse_label.text())

    def test_multiple_alarm_summary_keeps_full_tooltip_and_fixed_height(self):
        p = self.popover
        p.open_at_current_time()
        p.title_edit.setText("내일 9시 회의")
        height = p.parse_label.height()
        p._set_reminder_values([5, 10, -5])
        p._update_alarm_summary()
        self.assertIn("외 2개", p.parse_label.text())
        self.assertIn("08:50", p.parse_label.toolTip())
        self.assertIn("09:05", p.parse_label.toolTip())
        self.assertEqual(height, p.parse_label.height())

    def test_embedded_calendar_scales_widths_edit_and_details(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        panel = CalendarPanel(self.store)
        layout.addWidget(panel)
        standalone = self.popover
        try:
            self.popover = p = panel.schedule_popover
            for scale, expected_width in ((1.0, 336), (1.25, 372), (1.5, 408)):
                panel.setStyleSheet(scaled_stylesheet(scale))
                for width in (480, 800, 1100):
                    host.resize(width, 800)
                    host.show()
                    panel.update_responsive_layout(width)
                    panel._new_schedule(datetime(2026, 10, 2, 10))
                    p.title_edit.setText("10.2. 10~18시 견학 5분전")
                    self.app.processEvents()
                    self.assertEqual(host.width(), width)
                    self.assertEqual(p.width(), expected_width)
                    compact_height = p.height()
                    for editing in (False, True):
                        if editing:
                            p.save()
                            self.assertTrue(p.open_item(p.item_id))
                            p.place_near(QRect(width - 30, 760, 10, 10), bounds=panel._visible_bounds())
                            p.show()
                            self.app.processEvents()
                        self.assertTrue(panel._visible_bounds().contains(p.geometry()))
                        for widget in (p.title_edit, p.reminder_edit, p.dday_chip, p.save_button,
                                       *p.category_chips.values()):
                            self.assert_inside(widget)
                        before = p.values()
                        save_y = p.save_button.mapTo(p, QPoint()).y()
                        for chip, field in ((p.reminder_chip, p.reminder_details),
                                            (p.time_summary_button, p.time_row), (p.memo_chip, p.memo_edit)):
                            chip.click()
                            self.app.processEvents()
                            self.assert_inside(field)
                            self.assertEqual(p.width(), expected_width)
                            self.assertGreater(p.height(), compact_height)
                            self.assertTrue(p.title_edit.isVisible())
                            chip.click()
                            self.app.processEvents()
                            self.assertEqual(p.width(), expected_width)
                            self.assertFalse(field.isVisible())
                        self.assertEqual(p.values(), before)
                        self.capture(f"embedded-{scale}-{width}-{'edit' if editing else 'new'}")
                    print(f"EMBEDDED scale={scale} host={host.width()}x{host.height()} visible={panel._visible_bounds().getRect()} popup={p.width()}x{p.height()} save_y={save_y}")
        finally:
            self.popover = standalone
            destroy_widget(host, self.app)


if __name__ == "__main__":
    unittest.main()
