"""Cell formatting and safe merge/split commands for QTextTable."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCursor, QTextFormat, QTextTableFormat

from .table_edit import active_cells


def _cells(active):
    table, row, rows, column, columns = active
    seen = set()
    for r in range(row, row + rows):
        for c in range(column, column + columns):
            cell = table.cellAt(r, c)
            key = (cell.row(), cell.column())
            if cell.isValid() and key not in seen:
                seen.add(key)
                yield cell


def _edit(editor, action) -> None:
    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    try:
        action()
    finally:
        transaction.endEditBlock()
    editor.setFocus()


def align_cells(editor, alignment: Qt.AlignmentFlag) -> bool:
    active = active_cells(editor)
    if active is None:
        return False

    def apply():
        for cell in _cells(active):
            block = cell.firstCursorPosition().block()
            end = cell.lastCursorPosition().position()
            while block.isValid() and block.position() <= end:
                cursor = QTextCursor(block)
                fmt = block.blockFormat()
                fmt.setAlignment(alignment)
                cursor.setBlockFormat(fmt)
                block = block.next()

    _edit(editor, apply)
    return True


def background_cells(editor, color: str) -> bool:
    active = active_cells(editor)
    if active is None:
        return False

    def apply():
        for cell in _cells(active):
            fmt = cell.format().toTableCellFormat()
            fmt.setBackground(QColor(color))
            cell.setFormat(fmt)

    _edit(editor, apply)
    return True


def padding_cells(editor, pixels: float) -> bool:
    active = active_cells(editor)
    if active is None:
        return False

    def apply():
        for cell in _cells(active):
            fmt = cell.format().toTableCellFormat()
            fmt.setPadding(float(pixels))
            cell.setFormat(fmt)

    _edit(editor, apply)
    return True


def toggle_header(editor) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table = active[0]
    make_header = not bool(table.format().headerRowCount())

    def apply():
        fmt = QTextTableFormat(table.format())
        fmt.setHeaderRowCount(1 if make_header else 0)
        table.setFormat(fmt)
        for column in range(table.columns()):
            cell = table.cellAt(0, column)
            cell_fmt = cell.format().toTableCellFormat()
            if make_header:
                cell_fmt.setBackground(QColor("#f1f5f9"))
            elif cell_fmt.background().color().name() == "#f1f5f9":
                cell_fmt.clearBackground()
            cell.setFormat(cell_fmt)

    _edit(editor, apply)
    return True


def merge_cells(editor) -> tuple[bool, str | None]:
    active = active_cells(editor)
    if active is None:
        return False, None
    table, row, rows, column, columns = active
    if rows * columns <= 1:
        return True, "병합할 셀을 두 개 이상 사각형으로 선택해 주세요."
    for r in range(row, row + rows):
        for c in range(column, column + columns):
            cell = table.cellAt(r, c)
            if (not cell.isValid() or cell.row() != r or cell.column() != c
                    or cell.rowSpan() != 1 or cell.columnSpan() != 1):
                return True, "이미 병합된 셀과 겹쳐 문서를 변경하지 않았습니다."
    _edit(editor, lambda: table.mergeCells(row, column, rows, columns))
    editor.setTextCursor(table.cellAt(row, column).firstCursorPosition())
    return True, None


def split_cell(editor, rows: int | None = None, columns: int | None = None,
               equal_rows: bool = False) -> tuple[bool, str | None]:
    active = active_cells(editor)
    if active is None:
        return False, None
    table, row, _rows, column, _columns = active
    cell = table.cellAt(row, column)
    old_rows, old_columns = cell.rowSpan(), cell.columnSpan()
    rows = old_rows if rows is None else int(rows)
    columns = old_columns if columns is None else int(columns)
    if rows < 1 or columns < 1 or rows > 20 or columns > 20 or rows * columns < 2:
        return True, "줄 또는 칸을 2개 이상, 최대 20개까지 지정해 주세요."
    merged = old_rows > 1 or old_columns > 1
    if merged and (rows != old_rows or columns != old_columns):
        return True, "병합된 셀은 현재 병합된 줄·칸 개수로만 나눌 수 있습니다."
    if not merged:
        # A QTextTable is one rectangular grid. Add grid lines through the
        # selected cell, then merge every other affected cell back together.
        for r in range(table.rows()):
            for c in range(table.columns()):
                other = table.cellAt(r, c)
                if other.row() != r or other.column() != c or other.rowSpan() != 1 or other.columnSpan() != 1:
                    return True, "다른 병합 셀이 있는 표에서는 새 줄·칸 나누기를 지원하지 않습니다."

    def apply():
        if merged:
            table.splitCell(row, column, 1, 1)
        else:
            if columns > 1:
                table.insertColumns(column + 1, columns - 1)
                for other_row in range(table.rows() - 1, -1, -1):
                    if other_row != row:
                        table.mergeCells(other_row, column, 1, columns)
            if rows > 1:
                table.insertRows(row + 1, rows - 1)
                for other_column in range(table.columns() - 1, -1, -1):
                    if not column <= other_column < column + columns:
                        table.mergeCells(row, other_column, rows, 1)
    _edit(editor, apply)
    if equal_rows and rows > 1:
        # Layout positions are valid only after the structural edit block ends.
        # Join the padding changes back to that same undo step.
        def top(index: int) -> float:
            target = table.cellAt(index, column)
            fmt = target.format().toTableCellFormat()
            padding = (float(fmt.topPadding()) if fmt.hasProperty(QTextFormat.Property.TableCellTopPadding)
                       else float(table.format().cellPadding()))
            return float(editor.cursorRect(target.firstCursorPosition()).top()) - padding

        positions = [top(index) for index in range(row, row + rows)]
        after = row + rows
        if after < table.rows():
            positions.append(top(after))
        else:
            frame = editor.document().documentLayout().frameBoundingRect(table)
            positions.append(float(frame.bottom() - editor.verticalScrollBar().value()))
        heights = [max(0.0, b - a) for a, b in zip(positions, positions[1:])]
        tallest = max(heights)
        transaction = QTextCursor(editor.document())
        transaction.joinPreviousEditBlock()
        try:
            for offset, height in enumerate(heights):
                if tallest - height < 1.0:
                    continue
                for target_column in range(column, column + columns):
                    target = table.cellAt(row + offset, target_column)
                    fmt = target.format().toTableCellFormat()
                    current = (float(fmt.bottomPadding())
                               if fmt.hasProperty(QTextFormat.Property.TableCellBottomPadding)
                               else float(table.format().cellPadding()))
                    fmt.setBottomPadding(current + tallest - height)
                    target.setFormat(fmt)
        finally:
            transaction.endEditBlock()
    editor.setTextCursor(table.cellAt(row, column).firstCursorPosition())
    return True, None
