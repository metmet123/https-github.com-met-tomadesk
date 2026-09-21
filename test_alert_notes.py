import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, QTime, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QBoxLayout, QMessageBox, QStyle, QStyleOptionSpinBox, QWidget

import main_window
from alert_notes.database_bundle import export_database_bundle, import_database_bundle
from alert_notes.compact_datetime import parse_compact_date, parse_compact_time
from alert_notes.datetime_input import CompactDateEdit, CompactTimeEdit, DateTimeInput
from alert_notes.panel import AlertNotesPanel
from alert_notes.service import AlertService
from alert_notes.sqlite_store import (
    NOTE_COLUMNS, REMINDER_COLUMNS, SETTING_COLUMNS, DATETIME_FMT, NoteReminderStore,
)
from alert_notes.toma_pet_alert import TomaPetAlertDialog
from alert_notes.toma_pet_assets import FRAME_HEIGHT, FRAME_WIDTH, TomaSpriteAtlas
from alert_notes.window_geometry import WindowGeometryController
from ui_theme import scaled_stylesheet
from qt_test_support import close_alert_panel, close_main_window
from store import COLUMNS, TABLES, Store


class _FakeHotkeys:
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


class AlertNoteStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_note_crud_search_and_postit_state(self):
        note_id = self.store.create_note("회의", "자료 확인")
        self.store.update_note(
            note_id, postit=True, always_on_top=False, color="mint", opacity=80, input_locked=True
        )
        row = self.store.note(note_id)
        self.assertEqual((row["title"], row["color"], row["opacity"]), ("회의", "mint", 80))
        self.assertEqual([item["id"] for item in self.store.notes("자료")], [note_id])
        self.store.delete_note(note_id)
        self.assertIsNone(self.store.note(note_id))

    def test_compact_datetime_parsers(self):
        self.assertEqual(parse_compact_date("20260805").isoformat(), "2026-08-05")
        self.assertEqual(parse_compact_date("2026-08-05").isoformat(), "2026-08-05")
        self.assertIsNone(parse_compact_date("20260230"))
        self.assertEqual(parse_compact_time("930").strftime("%H:%M"), "09:30")
        self.assertEqual(parse_compact_time("9").strftime("%H:%M"), "09:00")
        self.assertIsNone(parse_compact_time("2460"))

    def test_single_reminder_replaces_snoozes_and_completes(self):
        note_id = self.store.create_note("알림")
        first = self.store.set_reminder(note_id, "202608041000", "첫 알림")
        second = self.store.set_reminder(note_id, "202608041100", "변경 알림")
        self.assertEqual(first, second)
        self.assertEqual(self.store.note(note_id)["reminder_due_at"], "202608041100")
        self.assertEqual(len(self.store.due_reminders("202608041200")), 1)
        self.store.snooze_reminder(first, 10)
        self.assertEqual(len(self.store.due_reminders("999912312359")), 1)
        self.store.complete_reminder(first)
        self.assertIsNone(self.store.note(note_id)["reminder_id"])

    def test_pinned_note_accepts_reminder_and_delete_cascades(self):
        note_id = self.store.create_note("고정 알림")
        self.store.update_note(note_id, postit=True)
        self.store.set_reminder(note_id, "202608041500", "내용")
        self.assertIsNotNone(self.store.note(note_id)["reminder_id"])
        self.store.delete_note(note_id)
        count = self.store.conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
        self.assertEqual(count, 1)
        self.store.restore_note(note_id)
        self.assertIsNotNone(self.store.note(note_id)["reminder_id"])

    def test_schedule_range_and_create_note_with_reminder(self):
        first = self.store.create_note_with_reminder("오전 회의", "자료 확인", "202608050930")
        self.store.create_note_with_reminder("다음 날", "", "202608060900")
        rows = self.store.list_schedule_items("202608050000", "202608060000")
        self.assertEqual([int(row["note_id"]) for row in rows], [first])
        self.assertEqual(rows[0]["note_title"], "오전 회의")


class BundleBackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.hotkeys = Store(root / "hotkeys.db")
        self.notes = NoteReminderStore(root / "alert_notes.db")

    def tearDown(self):
        self.hotkeys.close()
        self.notes.close()
        self.temp.cleanup()

    def test_bundle_roundtrip_restores_both_databases(self):
        self.hotkeys.save_action({"name": "작업", "hotkey": "Ctrl+1", "action_type": "text", "payload": {}, "active": True})
        note_id = self.notes.create_note("메모", "내용")
        path = Path(self.temp.name) / "bundle.json"
        export_database_bundle(
            {"hotkeys": (self.hotkeys.conn, TABLES), "alert_notes": (self.notes.conn, ("notes", "reminders", "settings"))},
            path,
        )
        self.hotkeys.delete_action(1)
        self.notes.delete_note(note_id)
        restored = import_database_bundle(
            {
                "hotkeys": (self.hotkeys.conn, COLUMNS),
                "alert_notes": (self.notes.conn, {"notes": list(NOTE_COLUMNS), "reminders": list(REMINDER_COLUMNS), "settings": list(SETTING_COLUMNS)}),
            }, path, legacy_name="hotkeys",
        )
        self.assertEqual(restored, {"hotkeys", "alert_notes"})
        self.assertEqual(len(self.hotkeys.actions()), 1)
        self.assertEqual(self.notes.note(note_id)["content"], "내용")

    def test_legacy_backup_preserves_current_notes(self):
        note_id = self.notes.create_note("보존")
        path = Path(self.temp.name) / "legacy.json"
        path.write_text(json.dumps({"tables": {table: [] for table in TABLES}}), encoding="utf-8")
        restored = import_database_bundle(
            {"hotkeys": (self.hotkeys.conn, COLUMNS), "alert_notes": (self.notes.conn, {"notes": list(NOTE_COLUMNS)})},
            path, legacy_name="hotkeys",
        )
        self.assertEqual(restored, {"hotkeys"})
        self.assertIsNotNone(self.notes.note(note_id))


class AlertNoteQtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_toma_pet_assets_and_legacy_reminder_actions(self):
        atlas = TomaSpriteAtlas()
        self.assertEqual(atlas.action_frame("idle", 0).size().width(), FRAME_WIDTH)
        self.assertEqual(atlas.look_frame(15).size().height(), FRAME_HEIGHT)
        reminder = {"id": 12, "note_id": 7, "note_title": "알림", "note_content": "내용", "memo": ""}
        dialog = TomaPetAlertDialog(reminder, False)
        completed = []
        dialog.completed.connect(completed.append)
        dialog.play_action("jumping")
        self.assertEqual(dialog.current_action, "jumping")
        self.assertEqual(len(dialog.pet._menu.actions()), 9)
        dialog._complete()
        self.assertEqual(completed, [12])

    def test_toma_pet_schedule_snooze_keeps_notification_identity(self):
        reminder = {
            "notification_id": 22, "occurrence_at": "202608101000", "item_id": 5,
            "note_id": None, "title": "일정", "details": "확인", "start_at": "202608101000",
        }
        dialog = TomaPetAlertDialog(reminder, True)
        snoozed = []
        dialog.snoozed.connect(lambda notification_id, minutes: snoozed.append((notification_id, minutes)))
        dialog._snooze(30)
        self.assertEqual(snoozed, [(22, 30)])

    def test_panel_creates_saves_reminder_and_postit(self):
        panel = AlertNotesPanel(self.store)
        panel.create_note()
        panel.editor.title_edit.setText("회의 준비")
        panel.editor.content_edit.setPlainText("자료 확인")
        panel.editor.postit_check.setChecked(True)
        panel.save_note(panel.editor.values())
        self.assertIn(panel.current_id, panel.postits)
        future = (datetime.now() + timedelta(minutes=30)).strftime(DATETIME_FMT)
        panel.set_reminder(future)
        self.assertEqual(self.store.note(panel.current_id)["reminder_due_at"], future)
        close_alert_panel(panel, self.app)

    def test_panel_switches_orientation_for_narrow_width(self):
        panel = AlertNotesPanel(self.store)
        panel.update_responsive_layout(800)
        self.assertEqual(panel.splitter.orientation(), Qt.Orientation.Vertical)
        self.assertFalse(panel.editor_remainder.isVisible())
        self.assertEqual(panel.calendar.mode, "day")
        self.assertEqual(panel.calendar.root_layout.direction(), QBoxLayout.Direction.TopToBottom)
        panel.update_responsive_layout(1200)
        self.assertEqual(panel.splitter.orientation(), Qt.Orientation.Horizontal)
        close_alert_panel(panel, self.app)

    def test_editor_has_compact_default_width_and_draggable_right_boundary(self):
        self.app.setStyleSheet(scaled_stylesheet(1.0))
        self.store.create_note("레이아웃 확인")
        panel = AlertNotesPanel(self.store)
        panel.resize(1920, 982)
        panel.update_responsive_layout(1920)
        panel.show()
        self.app.processEvents()
        panel.editor.summary_button.click()
        self.app.processEvents()

        sizes = panel.splitter.sizes()
        self.assertEqual(len(sizes), 3)
        self.assertGreaterEqual(sizes[0], 500)
        self.assertLessEqual(sizes[0], 630)
        self.assertGreaterEqual(sizes[1], 850)
        self.assertGreater(sizes[2], 0)
        self.assertLessEqual(sizes[2], 360)
        self.assertEqual(panel.splitter.handleWidth(), 7)
        self.assertEqual(
            panel.splitter.handle(1).accessibleName(),
            "메모 목록과 편집 영역 너비 조절선",
        )
        self.assertEqual(panel.splitter.handle(1).cursor().shape(), Qt.CursorShape.SplitHCursor)
        self.assertEqual(panel.splitter.handle(2).accessibleName(), "메모 편집 영역 너비 조절선")
        self.assertEqual(panel.splitter.handle(2).cursor().shape(), Qt.CursorShape.SplitHCursor)
        self.assertGreaterEqual(panel.editor.content_edit.minimumHeight(), 320)
        self.assertGreaterEqual(panel.editor.content_edit.height(), 320)
        self.assertFalse(panel.editor_scroll.horizontalScrollBar().isVisible())
        self.assertFalse(panel.editor_scroll.verticalScrollBar().isVisible())

        editor = panel.editor
        self.assertEqual(editor.datetime_input.quick_buttons, [])
        self.assertFalse(editor.datetime_input.hint.isVisible())
        self.assertTrue(editor.isAncestorOf(editor.datetime_input.summary))
        self.assertFalse(editor.reminder_details.isVisible())
        self.assertEqual(editor.reminder_toggle.accessibleName(), "알림 예약 펼치기")
        editor.property_chips.buttons["reminder"].click()
        self.app.processEvents()
        self.assertTrue(editor.reminder_details.isVisible())
        self.assertEqual(editor.reminder_toggle.accessibleName(), "알림 예약 접기")
        self.assertFalse(editor.recurrence.summary_label.isVisible())
        self.assertFalse(editor.recurrence.next_label.isVisible())
        quick_buttons = list(editor.quick_buttons.values())
        self.assertEqual(len({button.y() for button in quick_buttons}), 1)
        self.assertFalse(editor.hotkey_body.isVisible())
        editor.property_chips.buttons["hotkey"].click()
        self.app.processEvents()
        self.assertTrue(editor.hotkey_body.isVisible())
        self.assertTrue(editor.manual_save_button.isHidden())

        original_editor_width = sizes[1]
        handle = panel.splitter.handle(2)
        start = handle.rect().center()
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(handle, start + QPoint(80, 0), 20)
        QTest.mouseRelease(
            handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(80, 0),
        )
        self.app.processEvents()
        self.assertGreater(panel.splitter.sizes()[1], original_editor_width)
        close_alert_panel(panel, self.app)

    def test_memo_splitter_proportions_persistence_and_editor_reflow(self):
        self.store.create_note("비율 확인", "내용")
        panel = AlertNotesPanel(self.store)
        panel.resize(1920, 982)
        panel.update_responsive_layout(1920)
        panel.show()
        self.app.processEvents()
        panel.editor.summary_button.click()
        self.app.processEvents()

        original_sizes = panel.splitter.sizes()
        original_list_width = original_sizes[0]
        handle = panel.splitter.handle(1)
        start = handle.rect().center()
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(handle, start + QPoint(60, 0), 20)
        QTest.mouseRelease(
            handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(60, 0),
        )
        self.app.processEvents()
        self.assertGreater(panel.splitter.sizes()[0], original_list_width)

        table = panel.list_panel.table
        widths = [table.columnWidth(column) for column in range(table.columnCount())]
        expected = [
            weight / sum(panel.list_panel.COLUMN_WEIGHTS)
            for weight in panel.list_panel.COLUMN_WEIGHTS
        ]
        actual = [width / sum(widths) for width in widths]
        for actual_ratio, expected_ratio in zip(actual, expected):
            self.assertAlmostEqual(actual_ratio, expected_ratio, delta=0.02)
        self.assertLessEqual(abs(sum(widths) - table.viewport().width()), 1)

        available = panel.splitter.width() - (panel.splitter.handleWidth() * 2)
        panel.splitter.setSizes([620, 700, max(1, available - 1320)])
        panel._save_horizontal_splitter_ratios()
        saved = json.loads(self.store.setting(panel.SPLITTER_RATIO_SETTING))
        self.assertEqual(len(saved), 3)
        self.assertAlmostEqual(sum(saved), 1.0, delta=0.00001)

        panel.splitter.setSizes([max(480, available - 920), 560, 360])
        self.app.processEvents()
        editor = panel.editor
        self.assertLess(editor.width(), 620)
        toolbar_row = editor.format_toolbar.second_layout
        default_index = toolbar_row.indexOf(editor.format_toolbar.default_button)
        self.assertEqual(toolbar_row.itemAt(default_index + 1).widget().objectName(), "formatGroupLine")
        self.assertIs(toolbar_row.itemAt(default_index + 2).widget(), editor.format_toolbar.preset_strip)
        self.assertIs(toolbar_row.itemAt(default_index + 3).widget(), editor.format_toolbar.preset_settings_button)
        self.assertFalse(editor.format_toolbar.preset_settings_button.icon().isNull())
        self.assertTrue(editor.manual_save_button.isHidden())
        editor.property_chips.buttons["reminder"].click()
        editor.reminder_toggle.setChecked(True)
        self.app.processEvents()
        for button in editor.quick_buttons.values():
            self.assertLessEqual(button.width(), button.sizeHint().width() + 2)
            self.assertGreaterEqual(button.height(), 34)
        self.assertEqual(panel.editor_scroll.horizontalScrollBar().maximum(), 0)

        close_alert_panel(panel, self.app)

        restored = AlertNotesPanel(self.store)
        restored.resize(1920, 982)
        restored.update_responsive_layout(1920)
        restored.show()
        self.app.processEvents()
        restored.editor.summary_button.click()
        self.app.processEvents()
        restored_ratios = [size / sum(restored.splitter.sizes()) for size in restored.splitter.sizes()]
        for actual_ratio, saved_ratio in zip(restored_ratios, saved):
            self.assertAlmostEqual(actual_ratio, saved_ratio, delta=0.02)
        restored.shutdown()
        close_alert_panel(restored, self.app)

    def test_compact_date_and_time_keyboard_input(self):
        date_edit = CompactDateEdit()
        for text in ("20260805", "2026-08-05", "2026/08/05", "2026.08.05"):
            date_edit.lineEdit().setFocus()
            date_edit.lineEdit().selectAll()
            QTest.keyClicks(date_edit.lineEdit(), text)
            QTest.keyClick(date_edit.lineEdit(), Qt.Key.Key_Return)
            self.assertEqual(date_edit.date().toString("yyyy-MM-dd"), "2026-08-05")
        self.app.clipboard().setText("20260806")
        QTest.keyClick(date_edit.lineEdit(), Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(date_edit.date().toString("yyyy-MM-dd"), "2026-08-06")
        time_edit = CompactTimeEdit()
        for text, expected in (("930", "09:30"), ("9", "09:00"), ("1500", "15:00"), ("18:30", "18:30")):
            time_edit.lineEdit().setFocus()
            time_edit.lineEdit().selectAll()
            QTest.keyClicks(time_edit.lineEdit(), text)
            QTest.keyClick(time_edit.lineEdit(), Qt.Key.Key_Return)
            self.assertEqual(time_edit.time().toString("HH:mm"), expected)

    def test_date_click_selects_all_and_summary_marks_past_time(self):
        value_input = DateTimeInput()
        value_input.show()
        self.app.processEvents()
        QTest.mouseClick(value_input.date_edit.lineEdit(), Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(value_input.date_edit.lineEdit().hasSelectedText())
        value_input.set_datetime(datetime.now() - timedelta(minutes=1))
        self.assertEqual(value_input.summary.text(), "현재보다 이후 시간을 선택하세요")
        self.assertTrue(value_input.summary.property("invalid"))
        value_input.set_datetime(datetime.now() + timedelta(minutes=10))
        self.assertTrue(value_input.summary.text().startswith("오늘 "))
        self.assertFalse(value_input.summary.property("invalid"))
        value_input.close()

    def test_reminder_reset_preserves_memo_and_quick_button_waits_for_save(self):
        self.store.create_note("알림 입력")
        panel = AlertNotesPanel(self.store)
        panel.show()
        self.app.processEvents()
        editor = panel.editor
        editor.content_edit.setPlainText("지우면 안 되는 본문")
        saved = []
        editor.reminder_save_requested.connect(saved.append)
        editor.quick_buttons[5].click()
        self.assertEqual(saved, [])
        self.assertGreaterEqual(editor.datetime_input.datetime(), datetime.now() + timedelta(minutes=4))
        editor.quick_buttons[60].click()
        first_hour = editor.datetime_input.datetime()
        editor.quick_buttons[60].click()
        self.assertEqual(editor.datetime_input.datetime(), first_hour + timedelta(minutes=60))
        editor.clear_input_button.click()
        self.assertEqual(editor.clear_input_button.text(), "초기화")
        self.assertEqual(editor.content_edit.toPlainText(), "지우면 안 되는 본문")
        reset_gap = (editor.datetime_input.datetime() - datetime.now()).total_seconds()
        self.assertGreaterEqual(reset_gap, 8 * 60)
        self.assertLessEqual(reset_gap, 10 * 60)
        self.assertEqual(editor.reminder_save_hint.text(), "알림 저장 버튼으로 저장")
        editor.time_shortcuts[0].activated.emit()
        self.assertEqual(len(saved), 1)
        editor.content_edit.setFocus()
        QTest.keyClick(
            editor.content_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier,
        )
        # Ctrl+Enter no longer saves an alert, including while the panel is closed.
        self.assertEqual(len(saved), 1)
        close_alert_panel(panel, self.app)

    def test_reminder_details_state_persists_and_manual_time_resets_quick_accumulation(self):
        panel = AlertNotesPanel(self.store)
        panel.show()
        self.app.processEvents()
        editor = panel.editor
        self.assertFalse(editor.reminder_toggle.isChecked())
        editor.reminder_toggle.setChecked(True)
        self.assertEqual(self.store.setting(editor.REMINDER_COLLAPSED_SETTING), "false")
        editor.reminder_toggle.setChecked(False)
        self.assertEqual(self.store.setting(editor.REMINDER_COLLAPSED_SETTING), "true")

        editor.quick_buttons[60].click()
        first = editor.datetime_input.datetime()
        editor.datetime_input.set_datetime(first + timedelta(minutes=15))
        editor.quick_buttons[60].click()
        expected = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=60)
        self.assertAlmostEqual(
            (editor.datetime_input.datetime() - expected).total_seconds(), 0, delta=60,
        )
        close_alert_panel(panel, self.app)

        restored = AlertNotesPanel(self.store)
        self.assertFalse(restored.editor.reminder_toggle.isChecked())
        close_alert_panel(restored, self.app)

    def test_recurrence_end_controls_expand_only_after_selection(self):
        self.store.create_note("반복 UI")
        panel = AlertNotesPanel(self.store)
        panel.show()
        self.app.processEvents()
        controls = panel.editor.recurrence
        self.assertEqual(controls.rule_combo.currentText(), "반복 안 함")
        self.assertFalse(controls.end_controls.isVisible())
        panel.editor.property_chips.buttons["reminder"].click()
        panel.editor.reminder_toggle.setChecked(True)
        controls.rule_combo.setCurrentIndex(controls.rule_combo.findData("daily"))
        self.app.processEvents()
        self.assertTrue(controls.end_controls.isVisible())
        close_alert_panel(panel, self.app)

    def test_editor_value_controls_ignore_mouse_wheel(self):
        self.store.create_note("휠 잠금")
        panel = AlertNotesPanel(self.store)
        panel.show()
        self.app.processEvents()
        editor = panel.editor

        controls = (
            editor.format_toolbar.font_box, editor.format_toolbar.size_box,
            editor.datetime_input.date_edit, editor.datetime_input.time_edit,
            editor.recurrence.rule_combo, editor.recurrence.end_combo,
            editor.recurrence.end_date, editor.opacity_combo, editor.hotkey_action_combo,
        )
        for control in controls:
            before = (
                control.currentIndex() if hasattr(control, "currentIndex")
                else control.date() if hasattr(control, "date")
                else control.time() if hasattr(control, "time")
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
                control.currentIndex() if hasattr(control, "currentIndex")
                else control.date() if hasattr(control, "date")
                else control.time() if hasattr(control, "time")
                else control.value()
            )
            self.assertEqual(after, before, control.accessibleName() or type(control).__name__)
        close_alert_panel(panel, self.app)

    def test_editor_palette_spin_buttons_recurrence_and_quick_labels(self):
        self.store.create_note("편집 UI")
        panel = AlertNotesPanel(self.store)
        panel.resize(1280, 900)
        panel.show()
        self.app.processEvents()
        editor = panel.editor

        toolbar = editor.format_toolbar
        self.assertEqual(sorted(toolbar.preset_buttons), [1, 2, 3])
        self.assertFalse(hasattr(editor, "preset_layout"))
        self.assertGreaterEqual(toolbar.second_layout.indexOf(toolbar.preset_strip), 0)
        self.assertEqual(toolbar.color_button.text(), "")
        self.assertFalse(toolbar.image_button.icon().isNull())
        self.assertEqual(toolbar.image_button.toolTip(), "이미지 삽입")
        format_buttons = [
            *toolbar.style_buttons.values(), toolbar.bullet_button,
            toolbar.checklist_button, toolbar.image_button,
        ]
        self.assertEqual(len({(button.width(), button.height()) for button in format_buttons}), 1)
        self.assertLessEqual(toolbar.font_box.width(), toolbar.COMPACT_FONT_BOX_MAX_WIDTH)
        bold_button = toolbar.style_buttons["bold"]
        self.assertNotIn("✓", bold_button.text())
        bold_button.click()
        self.assertTrue(bold_button.isChecked())
        self.assertNotIn("✓", bold_button.text())
        self.assertIn("선택됨", bold_button.accessibleName())
        bold_button.click()
        self.assertFalse(bold_button.isChecked())
        self.assertNotIn("✓", bold_button.text())
        self.assertEqual(
            {(button.width(), button.height()) for button in toolbar.preset_buttons.values()}, {(26, 26)},
        )
        self.assertFalse(any(button.isChecked() for button in toolbar.preset_buttons.values()))
        toolbar.apply_preset(1)
        self.assertTrue(toolbar.preset_buttons[1].isChecked())
        toolbar.style_buttons["italic"].click()
        self.assertFalse(any(button.isChecked() for button in toolbar.preset_buttons.values()))
        self.assertEqual(len(toolbar.palette_buttons), 20)
        self.assertEqual([button.text() for button in toolbar.color_buttons.values()], ["", "", ""])
        toolbar.color_button.click()
        self.app.processEvents()
        self.assertTrue(toolbar.color_menu.isVisible())
        toolbar.palette_buttons["#e11d48"].click()
        self.assertEqual(toolbar.current_color.name(), "#e11d48")
        self.assertFalse(toolbar.color_menu.isVisible())

        def spin_rect(control, subcontrol):
            option = QStyleOptionSpinBox()
            control.initStyleOption(option)
            return control.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, subcontrol, control)

        # 크기 칸은 화살표 없이 숫자만 보인다(2차 수정 Q6).  ↑ 키로 한 단계 올린다.
        toolbar.size_box.setValue(10)
        self.assertEqual(toolbar.size_box.buttonSymbols(), toolbar.size_box.ButtonSymbols.NoButtons)
        toolbar.size_box.setFocus()
        QTest.keyClick(toolbar.size_box, Qt.Key.Key_Up)
        self.assertEqual(toolbar.size_box.value(), 11)

        editor.datetime_input.time_edit.setTime(QTime(10, 0))
        time_up = spin_rect(editor.datetime_input.time_edit, QStyle.SubControl.SC_SpinBoxUp)
        QTest.mouseMove(editor.datetime_input.time_edit, time_up.center())
        self.assertEqual(editor.datetime_input.time_edit.cursor().shape(), Qt.CursorShape.ArrowCursor)
        QTest.mouseClick(editor.datetime_input.time_edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, time_up.center())
        self.assertEqual(editor.datetime_input.time_edit.time().toString("HH:mm"), "10:10")

        editor.recurrence.rule_buttons["daily"].click()
        self.assertEqual(editor.recurrence.rule().rule_type, "daily")
        self.assertTrue(editor.recurrence.rule_buttons["daily"].isChecked())
        self.assertEqual(
            sum(button.isChecked() for button in editor.recurrence.rule_buttons.values()), 1,
        )
        editor.recurrence.end_buttons["count"].click()
        self.app.processEvents()
        self.assertEqual(editor.recurrence.end_combo.currentData(), "count")
        self.assertFalse(editor.recurrence.end_count.isHidden())
        self.assertTrue(editor.recurrence.end_date.isHidden())
        before_count = editor.recurrence.end_count.value()
        QTest.mouseClick(editor.recurrence.end_count, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         spin_rect(editor.recurrence.end_count, QStyle.SubControl.SC_SpinBoxUp).center())
        self.assertEqual(editor.recurrence.end_count.value(), before_count + 1)

        for button in editor.quick_buttons.values():
            self.assertGreaterEqual(button.minimumHeight(), 34)
            self.assertLessEqual(button.maximumHeight(), 42)
        self.assertEqual(len({button.y() for button in editor.quick_buttons.values()}), 1)
        quick_buttons = list(editor.quick_buttons.values())
        quick_gaps = [
            following.x() - previous.geometry().right() - 1
            for previous, following in zip(quick_buttons, quick_buttons[1:])
        ]
        self.assertLessEqual(max(quick_gaps) - min(quick_gaps), 1)
        self.assertEqual(quick_buttons[0].x(), 0)
        self.assertEqual(quick_buttons[-1].geometry().right(), editor.reminder_details.width() - 1)

        editor.hotkey_toggle.setChecked(True)
        editor.hotkey_enabled.setChecked(True)
        editor.hotkey_action_buttons["postit"].click()
        self.assertEqual(editor.hotkey_action_combo.currentData(), "postit")
        self.assertEqual(
            sum(button.isChecked() for button in editor.hotkey_action_buttons.values()), 1,
        )
        close_alert_panel(panel, self.app)

    def test_calendar_tab_and_quick_note_creation(self):
        panel = AlertNotesPanel(self.store)
        self.assertEqual(panel.tabs.count(), 4)
        self.assertEqual(panel.tabs.tabText(1), "캘린더")
        self.assertEqual(panel.tabs.tabText(2), "알림내역")
        self.assertEqual(panel.tabs.tabText(3), "메모 정리")
        future = datetime.now() + timedelta(days=1)
        panel.calendar.quick_card.select_slot(future)
        panel.calendar.title_edit.setText("캘린더 메모")
        panel.calendar.content_edit.setText("내용")
        panel.calendar._create_note()
        self.assertIsNotNone(self.store.note(panel.current_id)["reminder_id"])
        self.assertEqual(self.store.note(panel.current_id)["title"], "캘린더 메모")
        self.assertEqual(panel.tabs.currentIndex(), 0)
        close_alert_panel(panel, self.app)

    def test_alert_service_queues_due_reminders_one_at_a_time(self):
        first_note = self.store.create_note("첫 알림")
        second_note = self.store.create_note("둘째 알림")
        self.store.set_reminder(first_note, "200001010900", "첫째")
        self.store.set_reminder(second_note, "200001010901", "둘째")
        opened = []
        service = AlertService(self.store, opened.append)
        service.check_now()
        self.assertIsNotNone(service.active_dialog)
        self.assertEqual(len(service.queue), 1)
        first_id = service.active_dialog.reminder_id
        service.active_dialog._complete()
        self.app.processEvents()
        self.assertIsNotNone(service.active_dialog)
        self.assertNotEqual(service.active_dialog.reminder_id, first_id)
        service.stop()

    def test_geometry_roundtrip(self):
        values = {}
        window = QWidget()
        controller = WindowGeometryController(window, lambda key, default="": values.get(key, default), values.__setitem__, "test")
        window.resize(360, 240)
        controller.save()
        self.assertTrue(values["test"])
        other = QWidget()
        restore = WindowGeometryController(other, lambda key, default="": values.get(key, default), values.__setitem__, "test")
        restore.restore()
        self.assertEqual(other.size(), window.size())
        window.close()
        other.close()

    def test_main_window_has_two_workspaces(self):
        hotkeys = Store(Path(self.temp.name) / "hotkeys.db")
        with patch.object(main_window, "HotkeyManager", _FakeHotkeys), patch.object(main_window, "WindowsHookRecorder", _FakeRecorder):
            window = main_window.MainWindow(hotkeys)
            self.assertEqual(window.main_pages.count(), 2)
            window.alert_mode_button.click()
            self.assertEqual(window.main_pages.currentIndex(), 1)
            close_main_window(window, self.app)
        hotkeys.close()


if __name__ == "__main__":
    unittest.main()
