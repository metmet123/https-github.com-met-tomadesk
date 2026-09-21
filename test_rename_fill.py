import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QTableWidgetSelectionRange
from rename_fill import extend_series
from file_rename_table import FileRenameWindow
from rename_engine import RenameEngine

APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("seeds,count,expected", [
    (["1"], 3, ["2", "3", "4"]),
    (["09"], 3, ["10", "11", "12"]),
    (["099"], 2, ["100", "101"]),
    (["테스트1"], 2, ["테스트2", "테스트3"]),
    (["문서-01"], 2, ["문서-02", "문서-03"]),
    (["2", "4"], 3, ["6", "8", "10"]),
    (["002", "004"], 2, ["006", "008"]),
    (["9", "10"], 2, ["11", "12"]),
    (["6", "4"], 3, ["2", "0", "-2"]),
    (["-02", "-01"], 3, ["00", "01", "02"]),
    (["+01"], 2, ["+02", "+03"]),
    (["  문서001  "], 2, ["  문서002  ", "  문서003  "]),
    ([" a ", " b "], 3, [" a ", " b ", " a "]),
    (["", ""], 2, ["", ""]),
    ([" "], 2, [" ", " "]),
    (["1", "", "3"], 4, ["1", "", "3", "1"]),
    (["a1", "b2"], 3, ["a1", "b2", "a1"]),
    (["1", "3", "5"], 2, ["7", "9"]),
    (["1", "3", "6"], 3, ["1", "3", "6"]),
    (["01", "01"], 2, ["01", "01"]),
    (["한글", "한글"], 2, ["한글", "한글"]),
    (["1.5"], 2, ["1.5", "1.5"]),
    (["1,000"], 2, ["1,000", "1,000"]),
])
def test_series(seeds, count, expected):
    assert extend_series(seeds, count) == expected


def test_oversized_pasted_text_is_preserved_without_integer_inference():
    value = "9" * 5000
    assert extend_series([value], 2) == [value, value]


@pytest.fixture
def window(tmp_path):
    folder = tmp_path / "files"
    folder.mkdir()
    paths = [folder / f"file{i}.txt" for i in range(35)]
    for path in paths:
        path.write_text("original", encoding="utf-8")
    widget = FileRenameWindow(engine=RenameEngine(tmp_path / "journal" / "history.sqlite3"))
    widget.add_paths(paths)
    widget.resize(860, 680)
    widget.show()
    APP.processEvents()
    yield widget
    widget.close()
    assert sorted(folder.iterdir()) == sorted(paths)
    assert all(p.read_text(encoding="utf-8") == "original" for p in paths)
    assert not widget.engine.history()


def select(window, top, bottom=None, left=1, right=None):
    bottom = top if bottom is None else bottom
    right = left if right is None else right
    window.table.clearSelection()
    window.table.setCurrentCell(top, left)
    window.table.setRangeSelected(QTableWidgetSelectionRange(top, left, bottom, right), True)
    APP.processEvents()


def endpoint(table, row, column=1):
    return table.visualRect(table.model().index(row, column)).center()


def start_drag(window):
    handle = window.table.handle_rect()
    assert not handle.isEmpty()
    QTest.mousePress(window.table.viewport(), Qt.MouseButton.LeftButton, pos=handle.center())
    assert window.table._fill_area


def test_mouse_drag_commits_only_on_release_single_undo(window):
    window.table.item(0, 1).setText("001")
    select(window, 0)
    before = window._snapshot()
    history = len(window._undo)
    start_drag(window)
    target = endpoint(window.table, 4)
    QTest.mouseMove(window.table.viewport(), target)
    assert window._snapshot() == before
    QTest.mouseRelease(window.table.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert [window.table.item(r, 1).text() for r in range(5)] == ["001", "002", "003", "004", "005"]
    assert len(window._undo) == history + 1
    window.undo()
    assert window._snapshot() == before
    window.redo()
    assert window.table.item(4, 1).text() == "005"


def test_two_row_multicolumn_drag_and_preview(window):
    window._apply_cells([(0, 1, "이름"), (1, 1, "이름"), (0, 2, "02"), (1, 2, "04")])
    select(window, 0, 1, 1, 2)
    start_drag(window)
    target = endpoint(window.table, 4, 2)
    QTest.mouseMove(window.table.viewport(), target)
    QTest.mouseRelease(window.table.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert window.table.item(4, 1).text() == "이름"
    assert window.table.item(4, 2).text() == "10"
    assert window.table.item(4, 4).text() == "이름10.txt"


@pytest.mark.parametrize("cancel", ["escape", "outside", "up", "hide", "change"])
def test_cancel_never_applies_cells(window, cancel):
    window.table.item(1, 1).setText("01")
    select(window, 1)
    before = window._snapshot()
    start_drag(window)
    target = endpoint(window.table, 4)
    QTest.mouseMove(window.table.viewport(), target)
    if cancel == "escape":
        QTest.keyClick(window.table, Qt.Key.Key_Escape)
    elif cancel == "outside":
        QTest.mouseRelease(window.table.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(-10, 100))
    elif cancel == "up":
        QTest.mouseRelease(window.table.viewport(), Qt.MouseButton.LeftButton, pos=endpoint(window.table, 0))
    elif cancel == "hide":
        window.hide()
    else:
        window.change_columns(1)  # Model mutation cancels an in-progress drag.
        before = window._snapshot()
    assert not window.table._fill_area
    QTest.mouseRelease(window.table.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert window._snapshot() == before
    assert not window.table._scroll_timer.isActive()


def test_readonly_disjoint_hidden_filtered_areas_have_no_handle(window):
    select(window, 0, left=0)
    assert window.table.handle_rect().isEmpty()
    select(window, 0, left=4)
    assert window.table.handle_rect().isEmpty()
    select(window, 0)
    window.table.setRangeSelected(QTableWidgetSelectionRange(2, 1, 2, 1), True)
    assert window.table.handle_rect().isEmpty()
    select(window, 0)
    window.table.setRowHidden(3, True)
    assert window.table.handle_rect().isEmpty()
    window.table.setRowHidden(3, False)
    window.problems_only.setChecked(True)
    select(window, 0)
    assert window.table.handle_rect().isEmpty()


def test_autoscroll_and_clamped_last_row(window):
    window.table.item(0, 1).setText("1")
    select(window, 0)
    start_drag(window)
    bounds = window.table.viewport().rect()
    point = QPoint(endpoint(window.table, 0).x(), bounds.bottom() - 1)
    QTest.mouseMove(window.table.viewport(), point)
    for _ in range(60):
        window.table._scroll_fill()
    assert window.table.verticalScrollBar().value() > 0
    QTest.mouseRelease(window.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert window.table.item(34, 1).text() == "35"


def test_existing_values_are_replaced_atomically_and_ctrl_d_stays_copy(window):
    window._apply_cells([(0, 1, "01"), (1, 1, "keep"), (2, 1, "keep")])
    before = window._snapshot()
    window.fill_series(0, 0, 1, 1, 2)
    assert window.table.item(2, 1).text() == "03"
    window.undo()
    assert window._snapshot() == before
    select(window, 0, 2)
    window.fill_down()
    assert window.table.item(2, 1).text() == "01"


def test_reordered_rows_and_changed_column_count(window):
    paths = list(window.paths)
    window.table.verticalHeader().moveSection(0, 2)
    window.change_columns(1)
    window.table.item(0, 4).setText("9")
    window.fill_series(0, 0, 4, 4, 2)
    assert window.paths[:3] == [paths[1], paths[2], paths[0]]
    assert window.table.item(2, 4).text() == "11"
    assert window.table.item(2, 5).text() == "11.txt"


def test_no_motion_no_history_and_out_of_bounds_direct_fill(window):
    window.table.item(0, 1).setText("1")
    select(window, 0)
    history = len(window._undo)
    handle = window.table.handle_rect().center()
    start_drag(window)
    QTest.mouseRelease(window.table.viewport(), Qt.MouseButton.LeftButton, pos=handle)
    assert len(window._undo) == history
    before = window._snapshot()
    window.fill_series(0, 0, 0, 1, 3)
    window.fill_series(0, 0, 1, 1, 100)
    window.table.setRowHidden(2, True)
    window.fill_series(0, 0, 1, 1, 3)
    assert window._snapshot() == before


def test_drawn_handle_is_visible_and_editing_hides_it(window):
    window.table.item(0, 1).setText("001")
    select(window, 0)
    rect = window.table.handle_rect()
    pixmap = window.table.viewport().grab()
    ratio = pixmap.devicePixelRatio()
    pixel = pixmap.toImage().pixelColor(int(rect.center().x() * ratio), int(rect.center().y() * ratio))
    assert pixel.name() == "#2563eb"
    window.table.editItem(window.table.item(0, 1))
    APP.processEvents()
    assert window.table.handle_rect().isEmpty()


def test_toggle_filter_mid_drag_cancels_without_writes(window):
    window.table.item(0, 1).setText("1")
    select(window, 0)
    before = window._snapshot()
    start_drag(window)
    QTest.mouseMove(window.table.viewport(), endpoint(window.table, 3))
    window.problems_only.setChecked(True)
    assert not window.table._fill_area
    assert window._snapshot() == before
