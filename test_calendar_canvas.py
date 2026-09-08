"""좌표 기반 시간표(캔버스) 테스트.

표 위젯 시절에는 확인할 수 없던 것들 — 분 단위 위치, 겹침 나란히 놓기,
15분 스냅, 모서리로 길이 바꾸기 — 이 여기 모여 있다.
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from alert_notes.calendar_canvas import (
    DAY_MINUTES, MIN_MINUTES, SNAP_MINUTES, CalendarCanvas, snap,
)
from qt_test_support import destroy_widget


def row(item_id, title, start, end, category="sky"):
    return {
        "id": item_id, "occurrence_at": start, "title": title, "category": category,
        "status": "pending", "item_type": "event",
        "display_start_at": start, "display_end_at": end, "source_reminder_id": None,
    }


def key(code, modifiers=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, code, modifiers)


class SnapTest(unittest.TestCase):
    def test_rounds_to_the_nearest_quarter(self):
        self.assertEqual(snap(0), 0)
        self.assertEqual(snap(7), 0)
        self.assertEqual(snap(8), 15)
        self.assertEqual(snap(14 * 60 + 7), 14 * 60)
        self.assertEqual(snap(14 * 60 + 8), 14 * 60 + 15)

    def test_precise_mode_keeps_the_minute(self):
        self.assertEqual(snap(14 * 60 + 7, 1), 14 * 60 + 7)

    def test_stays_inside_the_day(self):
        self.assertEqual(snap(-40), 0)
        self.assertEqual(snap(DAY_MINUTES + 200), DAY_MINUTES)


class CanvasLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = CalendarCanvas()
        self.canvas.resize(900, 600)
        self.canvas.show()

    def tearDown(self):
        destroy_widget(self.canvas, self.app)

    def render(self, *rows, days=1):
        self.canvas.render_range(date(2026, 9, 3), date(2026, 9, 3 + days), list(rows))
        self.app.processEvents()
        return {block.title: block for block in self.canvas.blocks()}

    def test_block_sits_at_its_exact_minute(self):
        blocks = self.render(row(1, "팀 회의", "202609031030", "202609031115"))
        rect = blocks["팀 회의"].rect()
        # 10시 줄 꼭대기(600)가 아니라 10:30 자리에 놓인다.
        self.assertEqual(int(rect.y()), 10 * 60 + 30)
        self.assertEqual(int(rect.height()), 45)

    def test_overlapping_blocks_split_the_width(self):
        blocks = self.render(
            row(1, "리뷰", "202609031130", "202609031230"),
            row(2, "통화", "202609031200", "202609031300", "mint"),
        )
        left, right = blocks["리뷰"].rect(), blocks["통화"].rect()
        self.assertLessEqual(left.right(), right.left() + 1)
        self.assertAlmostEqual(left.width(), right.width(), delta=2)

    def test_a_lone_block_keeps_the_whole_column(self):
        blocks = self.render(
            row(1, "아침", "202609030900", "202609031000"),
            row(2, "리뷰", "202609031130", "202609031230"),
            row(3, "통화", "202609031200", "202609031300", "mint"),
        )
        # 겹치지 않는 일정까지 반 폭이 되면 안 된다.
        self.assertGreater(blocks["아침"].rect().width(), blocks["리뷰"].rect().width() * 1.5)

    def test_zero_length_item_still_has_a_grabbable_height(self):
        blocks = self.render(row(1, "점검", "202609031000", "202609031000"))
        self.assertGreaterEqual(int(blocks["점검"].rect().height()), MIN_MINUTES)

    def test_rect_for_range_points_at_that_time(self):
        self.render(row(1, "회의", "202609031000", "202609031100"))
        rect = self.canvas.rect_for_range(datetime(2026, 9, 3, 10, 0), datetime(2026, 9, 3, 11, 0))
        self.assertIsNotNone(rect)
        self.assertGreater(rect.height(), 0)
        # 다른 날은 이 화면에 없다.
        self.assertIsNone(
            self.canvas.rect_for_range(datetime(2026, 9, 9, 10, 0), datetime(2026, 9, 9, 11, 0))
        )

    def test_datetime_at_covers_both_ends_of_the_day(self):
        self.render()
        self.assertEqual(self.canvas.datetime_at(0, 0), datetime(2026, 9, 3, 0, 0))
        self.assertEqual(self.canvas.datetime_at(0, DAY_MINUTES), datetime(2026, 9, 4, 0, 0))

    def test_week_view_puts_each_day_in_its_own_column(self):
        blocks = self.render(
            row(1, "월요일 일", "202609030900", "202609031000"),
            row(2, "수요일 일", "202609050900", "202609051000"),
            days=7,
        )
        self.assertLess(blocks["월요일 일"].rect().x(), blocks["수요일 일"].rect().x())


class CanvasInteractionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = CalendarCanvas()
        self.canvas.resize(900, 600)
        self.canvas.show()
        self.canvas.render_range(
            date(2026, 9, 3), date(2026, 9, 4),
            [row(1, "회의", "202609031000", "202609031100")],
        )
        self.app.processEvents()
        self.block = self.canvas.blocks()[0]
        self.block.setSelected(True)
        self.moved = []
        self.resized = []
        self.canvas.scheduleMoved.connect(lambda *args: self.moved.append(args))
        self.canvas.scheduleResized.connect(lambda *args: self.resized.append(args))

    def tearDown(self):
        destroy_widget(self.canvas, self.app)

    def test_arrow_keys_move_by_a_quarter_hour(self):
        self.assertTrue(self.canvas.handle_key(key(Qt.Key.Key_Down)))
        self.assertEqual(self.block.start, datetime(2026, 9, 3, 10, SNAP_MINUTES))
        self.assertEqual(self.block.end, datetime(2026, 9, 3, 11, SNAP_MINUTES))
        self.assertEqual(len(self.moved), 1)
        # 옛 시각과 새 시각을 함께 알려야 되돌릴 수 있다.
        _id, _occurrence, old_start, _old_end, new_start, _new_end = self.moved[0]
        self.assertEqual(old_start, datetime(2026, 9, 3, 10, 0))
        self.assertEqual(new_start, datetime(2026, 9, 3, 10, 15))

    def test_alt_moves_by_a_single_minute(self):
        self.canvas.handle_key(key(Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier))
        self.assertEqual(self.block.start, datetime(2026, 9, 3, 9, 59))

    def test_shift_arrow_changes_the_length(self):
        self.assertTrue(
            self.canvas.handle_key(key(Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier))
        )
        self.assertEqual(self.block.start, datetime(2026, 9, 3, 10, 0), "시작은 그대로여야 합니다")
        self.assertEqual(self.block.end, datetime(2026, 9, 3, 11, SNAP_MINUTES))
        self.assertEqual(len(self.resized), 1)

    def test_length_never_shrinks_below_the_minimum(self):
        for _ in range(10):
            self.canvas.handle_key(key(Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier))
        self.assertGreaterEqual((self.block.end - self.block.start).total_seconds() / 60, MIN_MINUTES)

    def test_enter_opens_the_selected_block(self):
        opened = []
        self.canvas.scheduleActivated.connect(lambda *args: opened.append(args))
        self.assertTrue(self.canvas.handle_key(key(Qt.Key.Key_Return)))
        self.assertEqual(opened, [(1, "202609031000")])

    def test_locked_blocks_do_not_move(self):
        self.block.locked = True
        self.assertFalse(self.canvas.handle_key(key(Qt.Key.Key_Down)))
        self.assertEqual(self.block.start, datetime(2026, 9, 3, 10, 0))

    def test_grabbing_a_block_keeps_it_where_it_was(self):
        """잡기만 하고 놓으면 시간이 그대로여야 한다.

        예전에는 누른 지점의 절대 좌표를 그대로 빼면서 블록이 자정으로 튀었다.
        """
        rect = self.block.rect()
        grab = rect.top() + 20        # 블록 안쪽 아무 데나
        self.block.begin_press(grab, edge=False)
        self.block.drag_to(grab)
        self.assertEqual(self.block.start, datetime(2026, 9, 3, 10, 0))
        self.assertEqual(self.block.end, datetime(2026, 9, 3, 11, 0))

    def test_dragging_moves_by_the_distance_travelled(self):
        rect = self.block.rect()
        grab = rect.top() + 20
        self.block.begin_press(grab, edge=False)
        self.block.drag_to(grab + 90)   # 90분 아래로
        self.assertEqual(self.block.start, datetime(2026, 9, 3, 11, 30))
        self.assertEqual(self.block.end, datetime(2026, 9, 3, 12, 30))

    def test_dragging_the_bottom_edge_only_changes_the_end(self):
        rect = self.block.rect()
        self.block.begin_press(rect.bottom() - 2, edge=True)
        self.block.drag_to(rect.bottom() + 45)
        self.assertEqual(self.block.start, datetime(2026, 9, 3, 10, 0))
        self.assertEqual(self.block.end, datetime(2026, 9, 3, 11, 45))

    def test_a_block_never_leaves_the_day(self):
        rect = self.block.rect()
        self.block.begin_press(rect.top() + 5, edge=False)
        self.block.drag_to(rect.top() + 5 - 5000)
        self.assertEqual(self.block.start, datetime(2026, 9, 3, 0, 0))
        self.block.drag_to(rect.top() + 5 + 5000)
        self.assertEqual(self.block.end, datetime(2026, 9, 4, 0, 0))

    def test_range_selection_reports_real_times(self):
        picked = []
        self.canvas.rangeSelected.connect(lambda start, end: picked.append((start, end)))
        self.canvas.range_selected(0, 14 * 60 + 30, 15 * 60 + 45)
        self.assertEqual(
            picked, [(datetime(2026, 9, 3, 14, 30), datetime(2026, 9, 3, 15, 45))]
        )


if __name__ == "__main__":
    unittest.main()
