"""Limited table formulas that survive QTextDocument HTML round trips."""

from __future__ import annotations

from urllib.parse import quote, unquote

from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor

from .table_edit import active_cells
from .table_formula import cell_address, evaluate, parse_formula


FORMULA_URL = "toma-formula://"


def _cell_text(cell) -> str:
    first = cell.firstCursorPosition()
    last = cell.lastCursorPosition()
    block = first.block()
    if block.position() != last.block().position():
        return ""
    return block.text()


def stored_formula(cell) -> str | None:
    if not cell.isValid() or not _cell_text(cell):
        return None
    cursor = cell.firstCursorPosition()
    cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
    href = cursor.charFormat().anchorHref()
    return unquote(href[len(FORMULA_URL):]) if href.startswith(FORMULA_URL) else None


def _replace_cell(cell, value: str, formula: str | None = None) -> None:
    cursor = cell.firstCursorPosition()
    cursor.setPosition(cell.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
    base = QTextCharFormat(cursor.charFormat())
    cursor.removeSelectedText()
    base.setAnchor(bool(formula))
    base.setAnchorHref(FORMULA_URL + quote(formula, safe="") if formula else "")
    if formula:
        base.setForeground(QColor("#172033"))
        base.setFontUnderline(False)
    cursor.insertText(value, base)


def set_formula(editor, table, row: int, column: int, formula: str) -> tuple[bool, str | None]:
    try:
        name, first_row, last_row, first_col, last_col = parse_formula(formula)
        if first_row <= row <= last_row and first_col <= column <= last_col:
            raise ValueError("수식이 자기 셀을 참조합니다.")
        if last_row >= table.rows() or last_col >= table.columns():
            raise ValueError("표 밖의 셀을 참조합니다.")
        if (last_row - first_row + 1) * (last_col - first_col + 1) > 10_000:
            raise ValueError("한 번에 계산할 수 있는 셀 수를 넘었습니다.")
        for source_row in range(first_row, last_row + 1):
            for source_column in range(first_col, last_col + 1):
                if stored_formula(table.cellAt(source_row, source_column)) is not None:
                    raise ValueError("다른 수식 셀을 참조하는 중첩 계산은 지원하지 않습니다.")
        result = evaluate(table, formula)
    except ValueError as exc:
        return False, str(exc)
    target = table.cellAt(row, column)
    if not target.isValid() or target.firstCursorPosition().block() != target.lastCursorPosition().block():
        return False, "여러 문단이 있는 셀에는 수식을 넣을 수 없습니다."
    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    try:
        _replace_cell(target, result, formula)
    finally:
        transaction.endEditBlock()
    editor._has_table_formulas = True
    pending = getattr(editor, "_table_formula_edit", None)
    if pending is not None and pending[:3] == (table.firstPosition(), row, column):
        editor._table_formula_edit = None
    editor.setTextCursor(table.cellAt(row, column).firstCursorPosition())
    return True, None


def commit_typed_formula(editor) -> tuple[bool, str | None]:
    active = active_cells(editor)
    if active is None:
        return False, None
    table, row, rows, column, columns = active
    if rows != 1 or columns != 1:
        return False, None
    formula = _cell_text(table.cellAt(row, column))
    if not formula.startswith("="):
        return False, None
    return set_formula(editor, table, row, column, formula)


def edit_formula(editor) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table, row, _rows, column, _columns = active
    cell = table.cellAt(row, column)
    formula = stored_formula(cell)
    if formula is None:
        return False
    editor._table_formula_edit = (table.firstPosition(), row, column, formula)
    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    try:
        _replace_cell(cell, formula)
    finally:
        transaction.endEditBlock()
    editor.setTextCursor(table.cellAt(row, column).lastCursorPosition())
    return True


def cancel_formula_edit(editor) -> bool:
    pending = getattr(editor, "_table_formula_edit", None)
    if pending is None:
        return False
    key, row, column, formula = pending
    editor._table_formula_edit = None
    table = editor.current_table()
    if table is not None and table.firstPosition() == key:
        set_formula(editor, table, row, column, formula)
    return True


def formula_from_mouse_range(editor, source_table, source_row: int, source_column: int) -> tuple[bool, str | None]:
    selection = active_cells(editor)
    if selection is None or selection[0].firstPosition() != source_table.firstPosition():
        return False, None
    _, row, rows, column, columns = selection
    target = source_table.cellAt(source_row, source_column)
    prefix = _cell_text(target)
    if not prefix or not prefix.startswith("=") or not prefix.rstrip().endswith("("):
        return False, None
    first = cell_address(row, column)
    last = cell_address(row + rows - 1, column + columns - 1)
    formula = prefix + first + (":" + last if last != first else "") + ")"
    return set_formula(editor, source_table, source_row, source_column, formula)


def block_calculation(editor, name: str) -> tuple[bool, str | None]:
    active = active_cells(editor)
    if active is None:
        return False, None
    table, row, rows, column, columns = active
    if rows * columns < 2:
        return True, "셀을 두 개 이상 선택해 주세요."
    candidates = []
    if rows > 1 and columns == 1 and row + rows < table.rows():
        candidates.append((row + rows, column))
    if column + columns < table.columns():
        candidates.append((row, column + columns))
    if row + rows < table.rows() and (row + rows, column) not in candidates:
        candidates.append((row + rows, column))
    empty = [(r, c) for r, c in candidates if table.cellAt(r, c).isValid()
             and not _cell_text(table.cellAt(r, c)).strip()]
    if not empty:
        return True, "선택 범위 오른쪽이나 아래에 결과를 넣을 빈 셀이 필요합니다."
    target_row, target_column = empty[0]
    start = cell_address(row, column)
    end = cell_address(row + rows - 1, column + columns - 1)
    return set_formula(editor, table, target_row, target_column, f"={name}({start}:{end})")


def _tables(frame):
    item = frame.begin()
    while not item.atEnd():
        child = item.currentFrame()
        if child is not None:
            if hasattr(child, "cellAt") and hasattr(child, "rows"):
                yield child
            yield from _tables(child)
        item += 1


def recalculate(editor) -> None:
    if getattr(editor, "_table_recalculating", False):
        return
    editor._table_recalculating = True
    try:
        for table in _tables(editor.document().rootFrame()):
            for row in range(table.rows()):
                for column in range(table.columns()):
                    cell = table.cellAt(row, column)
                    if not cell.isValid() or cell.row() != row or cell.column() != column:
                        continue
                    formula = stored_formula(cell)
                    if formula is None:
                        continue
                    try:
                        result = evaluate(table, formula)
                    except ValueError:
                        continue
                    if _cell_text(cell) != result:
                        transaction = QTextCursor(editor.document())
                        transaction.beginEditBlock()
                        try:
                            _replace_cell(cell, result, formula)
                        finally:
                            transaction.endEditBlock()
    finally:
        editor._table_recalculating = False
