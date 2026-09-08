"""단축키 작업 화면 자리 정리 — ID 감춤, 상태 점, 단추 줄 걷기, 실패 알림."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

import main_window
from hotkey_manager import HotkeyError
from qt_test_support import close_main_window
from store import Store
from ui_polish import RegistrationDotDelegate, RegistrationStateItem


class _FailingHotkeys:
    """정해 둔 조합 하나만 등록에 실패하는 가짜 등록기."""

    fail_text = ""

    def __init__(self, _window_id):
        self.registered = {}

    def register(self, hotkey_id, hotkey, callback):
        if self.fail_text and hotkey == self.fail_text:
            raise HotkeyError("이미 쓰는 조합입니다")
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


class TaskListRoomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        _FailingHotkeys.fail_text = ""
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "hotkeys.db")
        self.patches = [
            patch.object(main_window, "Store", return_value=self.store),
            patch.object(main_window, "HotkeyManager", _FailingHotkeys),
            patch.object(main_window, "WindowsHookRecorder", _FakeRecorder),
        ]
        for item in self.patches:
            item.start()
        self.window = main_window.MainWindow()
        self.window.resize(1420, 760)
        self.window.show()
        self.action_id = self._add("비번1", "Alt+1")
        self.window.refresh()
        self.app.processEvents()

    def tearDown(self):
        _FailingHotkeys.fail_text = ""
        close_main_window(self.window, self.app)
        for item in reversed(self.patches):
            item.stop()
        self.store.close()
        self.temp.cleanup()

    def _add(self, name: str, hotkey: str) -> int:
        return self.store.save_action({
            "name": name, "hotkey": hotkey, "action_type": "text",
            "payload": {"text": "내용", "press_enter": False}, "active": True,
        })

    # ------------------------------------------------------------- ID 열 --
    def test_the_id_column_is_out_of_sight(self):
        self.assertTrue(self.window.table.isColumnHidden(main_window.ID_COLUMN))
        self.assertEqual(self.window.table.columnWidth(main_window.ID_COLUMN), 0)

    def test_the_row_is_still_found_by_its_id(self):
        self.assertEqual(self.window._selected_action_ids(), [])
        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(self.window._selected_action_ids(), [self.action_id])

    def test_searching_no_longer_matches_the_hidden_number(self):
        # 이름에도 단축키에도 없는 숫자여야 ID 로 걸리는지 알 수 있다.
        other = self._add("검색 대상", "Ctrl+Alt+G")
        self.window.refresh()
        self.app.processEvents()
        self.window.action_search.setText(str(other))
        self.app.processEvents()
        rows = range(self.window.table.rowCount())
        self.assertTrue(
            all(self.window.table.isRowHidden(row) for row in rows), "감춘 ID 로 걸렸습니다",
        )
        self.window.action_search.setText("검색")
        self.app.processEvents()
        self.assertEqual(
            sum(not self.window.table.isRowHidden(row) for row in rows), 1,
        )

    # -------------------------------------------------------------- 상태 --
    def test_the_status_header_is_one_word(self):
        self.assertEqual(self.window.table.horizontalHeaderItem(6).text(), "상태")

    def test_the_status_is_a_dot_and_the_word_stays_in_the_tooltip(self):
        self.window.register_hotkeys(False)
        item = self.window.table.item(0, 6)
        self.assertIsInstance(item, RegistrationStateItem)
        self.assertEqual(item.text(), "●")
        self.assertEqual(item.status(), "등록됨")
        self.assertIn("등록됨", item.toolTip())
        self.assertEqual(item.data(Qt.ItemDataRole.AccessibleTextRole), "등록됨")

    def test_a_switched_off_action_shows_an_empty_dot(self):
        self.store.set_actions_active([self.action_id], False)
        self.window.refresh()
        self.window.register_hotkeys(False)
        item = self.window.table.item(0, 6)
        self.assertEqual(item.text(), "○")
        self.assertEqual(item.status(), "비활성")

    def test_the_dot_keeps_its_own_colour_when_the_row_is_picked(self):
        self.assertIsInstance(
            self.window.table.itemDelegateForColumn(6), RegistrationDotDelegate,
        )

    def test_the_status_column_still_sorts_by_state(self):
        self.window.table.setSortingEnabled(False)
        first, second = RegistrationStateItem("등록됨"), RegistrationStateItem("등록 실패")
        self.assertLess(first, second)
        self.assertFalse(second < first)
        self.window.table.setSortingEnabled(True)

    def test_the_status_column_is_narrow(self):
        self.assertLessEqual(self.window.table.columnWidth(6), 60)

    # ------------------------------------------------------- 걷어 낸 줄 --
    def test_the_button_bars_are_gone(self):
        for name in (
            "bulk_action_toolbar", "selection_summary", "registration_bar",
            "hotkey_registration_summary", "editor_context",
        ):
            self.assertFalse(hasattr(self.window, name), f"{name} 가 아직 있습니다")

    def test_delete_sits_left_of_the_new_button(self):
        delete = self.window.delete_action_button
        new = self.window.new_action_button
        self.assertLess(delete.mapTo(self.window, QPoint()).x(), new.mapTo(self.window, QPoint()).x())
        self.assertEqual(delete.mapTo(self.window, QPoint()).y(), new.mapTo(self.window, QPoint()).y())

    def test_the_list_starts_higher_up(self):
        self.assertLess(self.window.table.y(), 200)
        self.assertLess(self.window.table.y(), self.window.action_search.y() + 100)

    def test_the_row_menu_keeps_what_the_bar_used_to_do(self):
        self.assertEqual(
            [action.text() for action in self.window.row_menu.actions() if action.text()],
            ["활성", "비활성", "실행 테스트", "삭제", "단축키 다시 등록", "실패 상세"],
        )

    def test_the_menu_wakes_up_with_the_checked_rows(self):
        self.assertFalse(self.window.activate_selected_action.isEnabled())
        self.assertFalse(self.window.test_action_action.isEnabled())
        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(self.window.activate_selected_action.isEnabled())
        self.assertTrue(self.window.deactivate_selected_action.isEnabled())
        self.assertTrue(self.window.test_action_action.isEnabled())

    def test_the_menu_still_runs_the_test(self):
        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        with patch.object(self.window.runner, "run", return_value="테스트 성공") as run:
            self.window.test_action_action.trigger()
        self.assertEqual(int(run.call_args.args[0]["id"]), self.action_id)

    # -------------------------------------------------------- 실패 알림 --
    def test_nothing_is_said_while_everything_registers(self):
        self.window.register_hotkeys(False)
        self.assertFalse(self.window.registration_notice.isVisible())
        self.assertIn("등록 완료", self.window.status.text())

    def test_the_failure_line_sits_beside_the_editor_title(self):
        _FailingHotkeys.fail_text = "Alt+1"
        self.window.register_hotkeys(False)
        self.app.processEvents()
        notice = self.window.registration_notice
        self.assertTrue(notice.isVisible())
        self.assertIn("실패 1개", notice.text())
        self.assertIn("실패 상세", notice.text())
        self.assertNotIn("등록 완료", notice.text())
        # 노란 띠는 같은 말을 되풀이하지 않는다.
        self.assertFalse(self.window.status.isVisible())
        self.assertGreater(
            notice.mapTo(self.window, QPoint()).x(),
            self.window.form_panel.mapTo(self.window, QPoint()).x(),
        )

    def test_the_failure_link_is_green_and_opens_the_list(self):
        _FailingHotkeys.fail_text = "Alt+1"
        self.window.register_hotkeys(False)
        self.assertIn("#157347", self.window.registration_notice.text())
        with patch.object(main_window.QMessageBox, "warning") as warning:
            self.window.registration_notice.linkActivated.emit("#failures")
        warning.assert_called_once()
        self.assertIn("비번1", warning.call_args.args[2])

    def test_the_line_goes_away_once_it_registers(self):
        _FailingHotkeys.fail_text = "Alt+1"
        self.window.register_hotkeys(False)
        self.assertTrue(self.window.registration_notice.isVisible())
        _FailingHotkeys.fail_text = ""
        with patch.object(QMessageBox, "information"):
            self.window.retry_registration_action.trigger()
        self.assertFalse(self.window.registration_notice.isVisible())
        self.assertEqual(self.window.table.item(0, 6).status(), "등록됨")


if __name__ == "__main__":
    unittest.main()
