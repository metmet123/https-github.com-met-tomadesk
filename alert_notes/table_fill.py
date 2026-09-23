"""Drag-to-fill for simple memo table values and formulas."""

from __future__ import annotations

import re

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QTextCursor
from .table_edit import active_cells
from .table_formula import parse_formula, series_values, shifted_formula
from .table_calculation import _replace_cell, set_formula, stored_formula


def _embedded_content(cell) -> bool:
    cursor = cell.firstCursorPosition()
    cursor.setPosition(cell.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
    html = cursor.selection().toHtml()
    return bool(re.search(r"<img\b|<a\b", html, re.I))


def _cell_rect(editor, table, row: int, column: int) -> QRectF:
    cell = table.cellAt(row, column)
    padding = float(table.format().cellPadding())
    first = editor.cursorRect(cell.firstCursorPosition())
    frame = editor.document().documentLayout().frameBoundingRect(table)
    next_column = column + cell.columnSpan()
    next_row = row + cell.rowSpan()
    right = (editor.cursorRect(table.cellAt(row, next_column).firstCursorPosition()).left() - padding
             if next_column < table.columns() else frame.right() - editor.horizontalScrollBar().value())
    bottom = (editor.cursorRect(table.cellAt(next_row, column).firstCursorPosition()).top() - padding
              if next_row < table.rows() else frame.bottom() - editor.verticalScrollBar().value())
    return QRectF(first.left() - padding, first.top() - padding,
                  max(1.0, right - first.left() + padding),
                  max(1.0, bottom - first.top() + padding))


def fill_handle(editor) -> QRectF | None:
    active = active_cells(editor)
    if active is None:
        return None
    table, row, rows, column, columns = active
    cell = table.cellAt(row + rows - 1, column + columns - 1)
    if not cell.isValid() or cell.rowSpan() != 1 or cell.columnSpan() != 1:
        return None
    rect = _cell_rect(editor, table, row + rows - 1, column + columns - 1)
    return QRectF(rect.right() - 4, rect.bottom() - 4, 8, 8)


def begin_fill(editor, point) -> bool:
    handle = fill_handle(editor)
    active = active_cells(editor)
    if (handle is None or active is None or not handle.adjusted(-3, -3, 3, 3).contains(
            float(point.x()), float(point.y()))):
        return False
    table, row, rows, column, columns = active
    editor._table_fill_drag = (table, row, rows, column, columns, None)
    editor.viewport().update()
    return True


def update_fill(editor, point) -> bool:
    drag = getattr(editor, "_table_fill_drag", None)
    if drag is None:
        return False
    table, row, rows, column, columns, _ = drag
    target_cursor = editor.cursorForPosition(point)
    target_table = target_cursor.currentTable()
    target = target_table.cellAt(target_cursor) if target_table is not None else None
    if (target_table is not None and target_table.firstPosition() == table.firstPosition()
            and target is not None and target.isValid()):
        editor._table_fill_drag = (table, row, rows, column, columns, (target.row(), target.column()))
    else:
        editor._table_fill_drag = (table, row, rows, column, columns, None)
    editor.viewport().update()
    return True


def finish_fill(editor, point) -> tuple[bool, str | None]:
    drag = getattr(editor, "_table_fill_drag", None)
    if drag is None:
        return False, None
    update_fill(editor, point)
    table, row, rows, column, columns, target = editor._table_fill_drag
    editor._table_fill_drag = None
    editor.viewport().update()
    if target is None:
        return True, None
    target_row, target_column = target
    last_row, last_column = row + rows - 1, column + columns - 1
    if target_column >= column and target_column <= last_column and target_row > last_row:
        axis, count = "down", target_row - last_row
    elif target_row >= row and target_row <= last_row and target_column > last_column:
        axis, count = "right", target_column - last_column
    else:
        return True, "현재는 선택 범위의 아래쪽 또는 오른쪽으로 채울 수 있습니다."
    if count * (columns if axis == "down" else rows) > 1000:
        return True, "한 번에 채울 수 있는 셀은 1,000개까지입니다."

    targets = []
    if axis == "down":
        for current_column in range(column, column + columns):
            sources = [table.cellAt(current_row, current_column) for current_row in range(row, row + rows)]
            if any(item.firstCursorPosition().block() != item.lastCursorPosition().block()
                   or (stored_formula(item) is None and _embedded_content(item)) for item in sources):
                return True, "이미지·링크·여러 문단이 있는 셀은 자동채우기를 지원하지 않습니다."
            values = [item.firstCursorPosition().block().text() for item in sources]
            generated = series_values(values, count)
            formula = stored_formula(sources[-1])
            for index in range(count):
                target_cell = table.cellAt(last_row + index + 1, current_column)
                targets.append((target_cell, last_row + index + 1, current_column,
                                shifted_formula(formula, index + 1, 0) if formula else None,
                                generated[index]))
    else:
        for current_row in range(row, row + rows):
            sources = [table.cellAt(current_row, current_column) for current_column in range(column, column + columns)]
            if any(item.firstCursorPosition().block() != item.lastCursorPosition().block()
                   or (stored_formula(item) is None and _embedded_content(item)) for item in sources):
                return True, "이미지·링크·여러 문단이 있는 셀은 자동채우기를 지원하지 않습니다."
            values = [item.firstCursorPosition().block().text() for item in sources]
            generated = series_values(values, count)
            formula = stored_formula(sources[-1])
            for index in range(count):
                target_cell = table.cellAt(current_row, last_column + index + 1)
                targets.append((target_cell, current_row, last_column + index + 1,
                                shifted_formula(formula, 0, index + 1) if formula else None,
                                generated[index]))

    pending_formulas = {(target_row, target_column) for _cell, target_row, target_column, formula, _value
                        in targets if formula}
    inspected_references = 0
    for cell, target_row, target_column, formula, value in targets:
        if not cell.isValid() or cell.row() != target_row or cell.column() != target_column:
            return True, "표 밖이나 병합 셀에는 채울 수 없습니다."
        if cell.firstCursorPosition().block() != cell.lastCursorPosition().block():
            return True, "여러 문단이 있는 셀은 자동채우기로 덮어쓰지 않습니다."
        if _embedded_content(cell):
            return True, "이미지·링크가 있는 셀은 자동채우기로 덮어쓰지 않습니다."
        if formula:
            try:
                _name, first_row, last_row, first_col, last_col = parse_formula(formula)
            except ValueError as exc:
                return True, str(exc)
            if last_row >= table.rows() or last_col >= table.columns():
                return True, "채운 수식이 표 밖을 참조합니다."
            inspected_references += (last_row - first_row + 1) * (last_col - first_col + 1)
            if inspected_references > 10_000:
                return True, "한 번에 계산할 수 있는 셀 수를 넘었습니다."
            if first_row <= target_row <= last_row and first_col <= target_column <= last_col:
                return True, "채운 수식이 자기 셀을 참조합니다."
            for source_row in range(first_row, last_row + 1):
                for source_column in range(first_col, last_col + 1):
                    if ((source_row, source_column) in pending_formulas
                            or stored_formula(table.cellAt(source_row, source_column)) is not None):
                        return True, "다른 수식 셀을 참조하는 중첩 계산은 지원하지 않습니다."

    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    changed = False
    try:
        for cell, target_row, target_column, formula, value in targets:
            if formula:
                handled, error = set_formula(editor, table, target_row, target_column, formula)
                if not handled:
                    raise ValueError(error or "수식을 채울 수 없습니다.")
                editor._has_table_formulas = True
            else:
                _replace_cell(cell, value)
            changed = True
    except ValueError as exc:
        transaction.endEditBlock()
        if changed:
            editor.document().undo()
        return True, str(exc)
    transaction.endEditBlock()
    return True, None


def fill_target_rect(editor) -> QRectF | None:
    drag = getattr(editor, "_table_fill_drag", None)
    if drag is None or drag[-1] is None:
        return None
    table, _row, _rows, _column, _columns, target = drag
    return _cell_rect(editor, table, *target)
