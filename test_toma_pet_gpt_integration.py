import hashlib
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QLabel

from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.service import AlertService
from alert_notes.toma_pet_alert import TomaPetAlertDialog
from alert_notes.toma_pet_assets import TomaSpriteAtlas, asset_directory
from alert_notes.toma_pet_motion import ANIMATION_SPECS, TomaMotionPlayer
from alert_notes.toma_pet_window import TomaPetController, TomaSpriteLabel
from settings_dialog import SettingsDialog


class TomaPetGptIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_project_asset_is_byte_identical_to_current_gpt_pet(self):
        gpt_asset = Path.home() / ".codex" / "pets" / "toma" / "spritesheet.webp"
        if not gpt_asset.is_file():
            self.skipTest("현재 GPT펫 원본이 설치되어 있지 않습니다.")
        project_asset = asset_directory() / "spritesheet.webp"
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(digest(project_asset), digest(gpt_asset))

    def test_exact_gpt_timing_and_three_cycles_then_slow_idle(self):
        self.assertEqual(ANIMATION_SPECS["idle"].frame_durations, (280, 110, 110, 140, 140, 320))
        self.assertEqual(ANIMATION_SPECS["reviewing"].frame_durations, (150, 150, 150, 150, 150, 280))
        target = QLabel()
        target.setFixedSize(144, 156)
        player = TomaMotionPlayer(target, TomaSpriteAtlas(), reduced_motion=False)
        player.play("reviewing")
        player.frame_timer.stop()
        for _ in range(18):
            player._advance_frame()
            player.frame_timer.stop()
        self.assertEqual(player.current_action, "idle")
        self.assertTrue(player.slow_idle)
        player.stop()

    def test_paused_pet_allows_alert_completion_then_returns_to_pause(self):
        target = QLabel()
        target.setFixedSize(144, 156)
        player = TomaMotionPlayer(target, TomaSpriteAtlas(), reduced_motion=False)
        player.set_paused(True)
        player.play("reviewing", override_pause=True)
        player.frame_timer.stop()
        for _ in range(18):
            player._advance_frame()
            player.frame_timer.stop()
        self.assertTrue(player.paused)
        self.assertEqual(player.current_action, "idle")
        self.assertFalse(player.frame_timer.isActive())
        player.stop()

    def test_alert_has_nine_snooze_buttons_in_five_plus_four_rows(self):
        reminder = {
            "id": 1, "note_id": 2, "note_title": "예산안 검토",
            "note_content": "오늘까지 수정된 내용을 확인해 주세요.",
            "memo": "", "occurrence_kind": "single", "due_at": "202608251200",
        }
        dialog = TomaPetAlertDialog(reminder, False, modifier="Alt")
        self.assertEqual(list(dialog.quick_snooze_buttons), [5, 30, 60, 120, 180, 240, 300, 360, 1440])
        grid = dialog.quick_snooze_buttons[5].parentWidget().layout().itemAt(4).layout()
        self.assertIs(grid.itemAtPosition(0, 4).widget(), dialog.quick_snooze_buttons[180])
        self.assertIs(grid.itemAtPosition(1, 3).widget(), dialog.quick_snooze_buttons[1440])
        self.assertEqual(dialog.quick_snooze_buttons[5].text(), "5분\nAlt+Q")
        values = []
        dialog.snoozed.connect(lambda _id, minutes: values.append(minutes))
        dialog.quick_snooze_buttons[300].click()
        self.assertEqual(values, [300])
        dialog.close()

    def test_edit_acknowledges_alert_and_opens_note(self):
        reminder = {
            "id": 3, "note_id": 7, "note_title": "메모",
            "note_content": "내용", "memo": "", "occurrence_kind": "single",
            "due_at": "202608251200",
        }
        dialog = TomaPetAlertDialog(reminder, False)
        completed, opened = [], []
        dialog.completed.connect(completed.append)
        dialog.note_open_requested.connect(opened.append)
        edit = next(button for button in dialog.findChildren(type(dialog.quick_snooze_buttons[5])) if button.accessibleName() == "메모편집")
        edit.click()
        self.assertEqual(completed, [3])
        self.assertEqual(opened, [7])
        dialog.close()

    def test_pet_preferences_are_independent_and_persisted(self):
        controller = TomaPetController(self.store, lambda: None, lambda: None)
        self.assertTrue(controller.alert_enabled)
        self.assertFalse(controller.persistent_enabled)
        controller.set_preferences(False, True)
        self.app.processEvents()
        self.assertFalse(controller.alert_enabled)
        self.assertTrue(controller.persistent_enabled)
        self.assertTrue(controller.window.isVisible())
        controller.set_preferences(True, False)
        self.assertTrue(controller.alert_enabled)
        self.assertFalse(controller.window.isVisible())
        controller.stop()

    def test_alert_setting_falls_back_and_persistent_pet_is_not_duplicated(self):
        note_id = self.store.create_note("알림", "내용")
        self.store.set_reminder(note_id, "200001010900", "확인")
        reminder = self.store.due_reminders()[0]
        controller = TomaPetController(self.store, lambda: None, lambda: None)
        service = AlertService(self.store, lambda _note_id: None, pet_controller=controller)
        controller.set_preferences(False, True)
        self.app.processEvents()
        self.assertIsNone(service._create_pet_alert(reminder, False))
        controller.set_preferences(True, True)
        dialog = service._create_pet_alert(reminder, False)
        self.assertIsNotNone(dialog)
        self.assertIsNone(dialog.pet)
        self.assertIs(dialog.persistent_pet, controller.window)
        dialog.close()
        service.stop()
        controller.stop()

    def test_settings_value_controls_ignore_wheel_and_drag(self):
        dialog = SettingsDialog({}, "window", Path(self.temp.name), pet_alert_enabled=False, pet_persistent_enabled=True)
        values = dialog.values()
        self.assertFalse(values["toma_pet_alert_enabled"])
        self.assertTrue(values["toma_pet_persistent_enabled"])
        combo: QComboBox = dialog.startup_combo
        before = combo.currentIndex()
        wheel = QWheelEvent(
            QPointF(4, 4), QPointF(4, 4), QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(combo, wheel)
        self.assertEqual(combo.currentIndex(), before)
        drag = QMouseEvent(
            QMouseEvent.Type.MouseMove, QPointF(8, 8), QPointF(8, 8), QPointF(8, 8),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(combo, drag)
        self.assertTrue(drag.isAccepted())
        dialog.pet_position_reset_button.click()
        self.assertTrue(dialog.values()["reset_toma_pet_position"])
        dialog.close()

    def test_pet_drag_starts_only_after_four_pixels(self):
        pet = TomaSpriteLabel()
        starts = []
        pet.drag_started.connect(starts.append)
        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(2, 2), QPointF(100, 100),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        pet.mousePressEvent(press)
        small_move = QMouseEvent(
            QMouseEvent.Type.MouseMove, QPointF(4, 4), QPointF(103, 103),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        pet.mouseMoveEvent(small_move)
        self.assertEqual(starts, [])
        threshold_move = QMouseEvent(
            QMouseEvent.Type.MouseMove, QPointF(6, 2), QPointF(104, 100),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        pet.mouseMoveEvent(threshold_move)
        self.assertEqual(starts, [QPoint(100, 100)])
        pet.close()


if __name__ == "__main__":
    unittest.main()
