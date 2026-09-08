"""메모 목록 접기 단축키와, 다른 프로그램보다 먼저 잡는 전역 단축키."""

import ctypes
import os
import tempfile
import unittest
from ctypes import wintypes
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from hotkey_defs import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, WM_HOTKEY, HotkeyError
from hotkey_hook import (
    LLKHF_INJECTED, WM_KEYDOWN, WM_KEYUP, HotkeyMatcher, KeyboardHook, _KeyboardHookData,
)
from hotkey_manager import HotkeyManager
from hotkey_parser import can_intercept, parse_hotkey
from qt_test_support import close_alert_panel


class FoldShortcutTest(unittest.TestCase):
    """메모 목록 모두 접기·펼치기 단축키."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.parent_id = self.store.create_note("취미", "")
        self.child_id = self.store.create_note("드라마", "")
        self.store.set_note_parent(self.child_id, self.parent_id)
        self.panel = AlertNotesPanel(self.store)
        self.panel.resize(1200, 700)
        self.panel.show()
        self.panel.refresh()
        self.app.processEvents()
        self.list_panel = self.panel.list_panel

    def tearDown(self):
        close_alert_panel(self.panel, self.app)
        self.store.close()
        self.temp.cleanup()

    def _parent_item(self):
        return self.list_panel._item_for(self.parent_id)

    def test_the_shortcut_is_the_one_written_on_the_button(self):
        self.assertEqual(
            self.list_panel.fold_shortcut.key(),
            QKeySequence(self.list_panel.FOLD_ALL_SHORTCUT),
        )
        self.assertIn(
            self.list_panel.FOLD_ALL_SHORTCUT, self.list_panel.fold_button.toolTip(),
        )

    def test_it_only_listens_while_this_window_is_in_front(self):
        self.assertEqual(
            self.list_panel.fold_shortcut.context(), Qt.ShortcutContext.WindowShortcut,
        )

    def test_it_does_not_take_the_body_toggle_shortcut(self):
        self.assertNotEqual(
            QKeySequence(self.list_panel.FOLD_ALL_SHORTCUT),
            self.panel.editor.fold_all_shortcut.key(),
        )

    def test_pressing_it_folds_and_unfolds_everything(self):
        self._parent_item().setExpanded(True)
        self.list_panel.fold_shortcut.activated.emit()
        self.app.processEvents()
        self.assertFalse(self._parent_item().isExpanded())
        self.list_panel.fold_shortcut.activated.emit()
        self.app.processEvents()
        self.assertTrue(self._parent_item().isExpanded())

    def test_the_button_word_follows_the_shortcut(self):
        self._parent_item().setExpanded(True)
        self.list_panel.fold_shortcut.activated.emit()
        self.app.processEvents()
        self.assertEqual(self.list_panel.fold_button.text(), "모두 펼치기")

    def test_a_hidden_list_does_not_answer(self):
        self._parent_item().setExpanded(True)
        self.list_panel.hide()
        self.app.processEvents()
        self.list_panel.fold_shortcut.activated.emit()
        self.assertTrue(self._parent_item().isExpanded(), "감춘 목록이 접혔습니다")


class InterceptRuleTest(unittest.TestCase):
    """무엇을 먼저 가져가도 되는가."""

    def test_ordinary_combinations_are_taken_first(self):
        for text in ("Ctrl+Alt+N", "Alt+1", "Ctrl+Shift+F9", "Win+Alt+Space"):
            self.assertTrue(can_intercept(parse_hotkey(text)), text)

    def test_the_copy_and_paste_keys_are_left_alone(self):
        for text in ("Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Ctrl+S", "Ctrl+A"):
            self.assertFalse(can_intercept(parse_hotkey(text)), text)

    def test_what_windows_keeps_for_itself_is_left_alone(self):
        self.assertFalse(can_intercept(parse_hotkey("Ctrl+Shift+Esc")))

    def test_adding_another_modifier_makes_it_ours_again(self):
        # Ctrl+Shift+C 는 복사가 아니다.  막을 이유가 없다.
        self.assertTrue(can_intercept(parse_hotkey("Ctrl+Shift+C")))


class MatcherTest(unittest.TestCase):
    """맡아 둔 조합을 고르는 표."""

    def setUp(self):
        self.matcher = HotkeyMatcher()
        self.matcher.claim(7, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("N"))

    def test_the_exact_combination_matches(self):
        self.assertEqual(self.matcher.match(ord("N"), MOD_CONTROL | MOD_ALT), 7)

    def test_one_extra_modifier_is_somebody_elses_shortcut(self):
        self.assertIsNone(
            self.matcher.match(ord("N"), MOD_CONTROL | MOD_ALT | MOD_SHIFT),
        )

    def test_a_missing_modifier_does_not_match(self):
        self.assertIsNone(self.matcher.match(ord("N"), MOD_CONTROL))

    def test_letting_go_stops_the_match(self):
        self.matcher.release(7)
        self.assertIsNone(self.matcher.match(ord("N"), MOD_CONTROL | MOD_ALT))
        self.assertEqual(len(self.matcher), 0)


class HookDecisionTest(unittest.TestCase):
    """갈고리 안에서 내리는 판단.  실제로 걸지는 않는다."""

    def setUp(self):
        self.hook = KeyboardHook(0)
        self.hook.matcher.claim(11, MOD_CONTROL | MOD_ALT, ord("N"))
        self.pressed = MOD_CONTROL | MOD_ALT

    def _event(self, vk: int, flags: int = 0) -> int:
        self.data = _KeyboardHookData(vkCode=vk, scanCode=0, flags=flags, time=0, dwExtraInfo=0)
        return ctypes.addressof(self.data)

    def test_a_claimed_key_is_taken(self):
        self.assertEqual(
            self.hook._decide(WM_KEYDOWN, self._event(ord("N")), lambda: self.pressed), 11,
        )

    def test_another_key_passes_through(self):
        self.assertIsNone(
            self.hook._decide(WM_KEYDOWN, self._event(ord("M")), lambda: self.pressed),
        )

    def test_keys_our_own_macros_type_are_left_alone(self):
        self.assertIsNone(
            self.hook._decide(
                WM_KEYDOWN, self._event(ord("N"), LLKHF_INJECTED), lambda: self.pressed,
            ),
            "반복작업이 만든 키를 우리가 다시 잡았습니다",
        )

    def test_the_modifier_itself_is_never_taken(self):
        self.assertIsNone(
            self.hook._decide(WM_KEYDOWN, self._event(0x11), lambda: self.pressed),
        )

    def test_the_release_of_a_taken_key_is_swallowed_once(self):
        self.hook._decide(WM_KEYDOWN, self._event(ord("N")), lambda: self.pressed)
        self.assertTrue(self.hook._swallow_release(WM_KEYUP, self._event(ord("N"))))
        self.assertFalse(self.hook._swallow_release(WM_KEYUP, self._event(ord("N"))))


class _FakeHook:
    """갈고리를 건 척한다.  시험이 진짜 키보드를 건드리지 않게."""

    started = True

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.matcher = HotkeyMatcher()
        self.running = False
        self.stopped = 0

    def start(self, timeout: float = 1.0) -> bool:
        self.running = bool(self.started)
        return self.running

    def stop(self) -> None:
        self.running = False
        self.stopped += 1


class ManagerTest(unittest.TestCase):
    """등록은 갈고리로, 안 되는 것만 Windows 로."""

    def setUp(self):
        _FakeHook.started = True
        self.hooks: list[_FakeHook] = []
        self.manager = HotkeyManager(0, hook_factory=self._make_hook)
        self.manager._user32 = MagicMock()
        self.manager._user32.RegisterHotKey.return_value = 1

    def tearDown(self):
        _FakeHook.started = True

    def _make_hook(self, hwnd):
        hook = _FakeHook(hwnd)
        self.hooks.append(hook)
        return hook

    def test_an_ordinary_hotkey_is_taken_before_other_programs(self):
        self.manager.register(1, "Ctrl+Alt+N", lambda: None)
        self.assertEqual(self.manager.priority_ids(), {1})
        self.manager._user32.RegisterHotKey.assert_not_called()
        self.assertEqual(
            self.hooks[0].matcher.match(ord("N"), MOD_CONTROL | MOD_ALT), 1,
        )

    def test_the_copy_key_is_still_left_to_windows(self):
        self.manager.register(2, "Ctrl+C", lambda: None)
        self.assertEqual(self.manager.priority_ids(), set())
        self.manager._user32.RegisterHotKey.assert_called_once()

    def test_one_hook_serves_every_hotkey(self):
        self.manager.register(1, "Ctrl+Alt+N", lambda: None)
        self.manager.register(2, "Ctrl+Alt+M", lambda: None)
        self.assertEqual(len(self.hooks), 1)
        self.assertEqual(len(self.hooks[0].matcher), 2)

    def test_letting_go_releases_the_claim(self):
        self.manager.register(1, "Ctrl+Alt+N", lambda: None)
        self.manager.unregister(1)
        self.assertEqual(self.manager.priority_ids(), set())
        self.assertEqual(len(self.hooks[0].matcher), 0)
        self.manager._user32.UnregisterHotKey.assert_not_called()

    def test_a_windows_registered_key_is_released_the_old_way(self):
        self.manager.register(2, "Ctrl+C", lambda: None)
        self.manager.unregister(2)
        self.manager._user32.UnregisterHotKey.assert_called_once()

    def test_when_the_hook_cannot_be_hung_windows_takes_over(self):
        _FakeHook.started = False
        self.manager.register(1, "Ctrl+Alt+N", lambda: None)
        self.assertEqual(self.manager.priority_ids(), set())
        self.manager._user32.RegisterHotKey.assert_called_once()

    def test_a_failed_hook_is_not_retried_for_every_key(self):
        _FakeHook.started = False
        self.manager.register(1, "Ctrl+Alt+N", lambda: None)
        self.manager.register(2, "Ctrl+Alt+M", lambda: None)
        self.assertEqual(len(self.hooks), 1, "실패한 갈고리를 또 걸었습니다")

    def test_windows_refusal_is_still_reported(self):
        self.manager._user32.RegisterHotKey.return_value = 0
        with self.assertRaises(HotkeyError):
            self.manager.register(2, "Ctrl+C", lambda: None)

    def test_closing_the_program_takes_the_hook_down(self):
        self.manager.register(1, "Ctrl+Alt+N", lambda: None)
        self.manager.shutdown()
        self.assertEqual(self.hooks[0].stopped, 1)
        self.assertEqual(self.manager.priority_ids(), set())

    def test_the_message_from_the_hook_runs_the_action(self):
        fired = []
        self.manager.register(1, "Ctrl+Alt+N", lambda: fired.append(True))
        message = wintypes.MSG()
        message.message = WM_HOTKEY
        message.wParam = 1
        self.assertTrue(self.manager.handle_native_event(ctypes.addressof(message)))
        self.assertEqual(fired, [True])

    def test_another_message_is_left_alone(self):
        message = wintypes.MSG()
        message.message = 0x0100
        self.assertFalse(self.manager.handle_native_event(ctypes.addressof(message)))


if __name__ == "__main__":
    unittest.main()
