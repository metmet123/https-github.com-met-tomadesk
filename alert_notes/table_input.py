"""Keyboard selection and dialogs for rich memo tables."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QTextCursor, QTextFormat, QTextLength
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QMessageBox, QSpinBox, QVBoxLayout,
)

from .table_edit import active_cells, clear_contents, remove, set_width
from .table_style import split_cell


def select_current_cell(editor) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table, row, _rows, column, _columns = active
    editor._table_selected_cell = (table.firstPosition(), row, column)
    editor._table_selection_anchor = (table.firstPosition(), row, column)
    editor._table_selection_endpoint = (row, column)
    editor.viewport().update()
    editor.setFocus()
    return True


def clear_cell_selection(editor) -> None:
    if getattr(editor, "_table_selected_cell", None) is not None:
        editor._table_selected_cell = None
        editor.viewport().update()
    editor._table_selection_anchor = None
    editor._table_selection_endpoint = None


def extend_cell_selection(editor, key: Qt.Key) -> bool:
    anchor = getattr(editor, "_table_selection_anchor", None)
    endpoint = getattr(editor, "_table_selection_endpoint", None)
    table = editor.current_table()
    if anchor is None or endpoint is None or table is None or table.firstPosition() != anchor[0]:
        return False
    row, column = endpoint
    if key == Qt.Key.Key_Up:
        row -= 1
    elif key == Qt.Key.Key_Down:
        row += 1
    elif key == Qt.Key.Key_Left:
        column -= 1
    elif key == Qt.Key.Key_Right:
        column += 1
    else:
        return False
    row = max(0, min(row, table.rows() - 1))
    column = max(0, min(column, table.columns() - 1))
    if (row, column) == endpoint:
        return True
    editor._table_selection_endpoint = (row, column)
    first_row, last_row = sorted((anchor[1], row))
    first_column, last_column = sorted((anchor[2], column))
    first = table.cellAt(first_row, first_column)
    last = table.cellAt(last_row, last_column)
    cursor = first.firstCursorPosition()
    cursor.setPosition(last.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    editor._table_selected_cell = None if cursor.hasComplexSelection() else anchor
    editor.viewport().update()
    return True


def selected_cell_rect(editor) -> QRectF | None:
    selected = getattr(editor, "_table_selected_cell", None)
    if selected is None:
        return None
    table = editor.current_table()
    if table is None or table.firstPosition() != selected[0]:
        return None
    _, row, column = selected
    cell = table.cellAt(row, column)
    if not cell.isValid():
        return None
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


def delete_selected(editor) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table, row, rows, column, columns = active
    if not editor.textCursor().hasComplexSelection() and getattr(editor, "_table_selected_cell", None) is None:
        return False
    if columns != table.columns() and rows != table.rows():
        clear_contents(editor)
        clear_cell_selection(editor)
        return True
    dialog = QMessageBox(editor)
    dialog.setWindowTitle("선택한 셀 지우기")
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setText("선택한 셀을 지웁니다. 내용만 지우고 셀 모양은 남겨 둘까요?")
    keep = dialog.addButton("남김", QMessageBox.ButtonRole.AcceptRole)
    delete = dialog.addButton("지우기", QMessageBox.ButtonRole.DestructiveRole)
    dialog.addButton("취소", QMessageBox.ButtonRole.RejectRole)
    dialog.exec()
    clicked = dialog.clickedButton()
    if clicked == keep:
        clear_contents(editor)
    elif clicked == delete:
        if columns == table.columns():
            remove(editor, "row")
        else:
            remove(editor, "column")
    clear_cell_selection(editor)
    return True


def backspace_selected(editor) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    if not editor.textCursor().hasComplexSelection() and getattr(editor, "_table_selected_cell", None) is None:
        return False
    clear_contents(editor)
    clear_cell_selection(editor)
    return True


def show_split_dialog(editor) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table, row, _rows, column, _columns = active
    cell = table.cellAt(row, column)
    dialog = QDialog(editor)
    dialog.setWindowTitle("셀 나누기")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("나눌 줄과 칸 개수를 지정하세요."))
    form = QFormLayout()
    row_option = QCheckBox("줄 개수", dialog)
    row_count = QSpinBox(dialog)
    row_count.setRange(1, 20)
    row_count.setValue(max(2, cell.rowSpan()))
    row_option.setChecked(cell.rowSpan() > 1 or cell.rowSpan() * cell.columnSpan() == 1)
    row_count.setEnabled(row_option.isChecked())
    row_option.toggled.connect(row_count.setEnabled)
    column_option = QCheckBox("칸 개수", dialog)
    column_count = QSpinBox(dialog)
    column_count.setRange(1, 20)
    column_count.setValue(max(2, cell.columnSpan()))
    column_option.setChecked(cell.columnSpan() > 1)
    column_count.setEnabled(column_option.isChecked())
    column_option.toggled.connect(column_count.setEnabled)
    form.addRow(row_option, row_count)
    form.addRow(column_option, column_count)
    layout.addLayout(form)
    equal_rows = QCheckBox("줄 높이를 같게 나누기", dialog)
    equal_rows.setEnabled(row_option.isChecked())
    row_option.toggled.connect(equal_rows.setEnabled)
    layout.addWidget(equal_rows)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dialog,
    )
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("나누기")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return True
    handled, error = split_cell(
        editor,
        row_count.value() if row_option.isChecked() else 1,
        column_count.value() if column_option.isChecked() else 1,
        equal_rows.isChecked() and row_option.isChecked(),
    )
    if error:
        QMessageBox.information(editor, "셀 나누기", error)
    clear_cell_selection(editor)
    return handled


def resize_selected(editor, key: Qt.Key) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table, row, rows, column, columns = active
    if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
        constraints = table.format().columnWidthConstraints()
        if len(constraints) == table.columns() and all(
            item.type() == QTextLength.Type.FixedLength for item in constraints
        ):
            widths = [float(item.rawValue()) for item in constraints]
        else:
            first_row = min(row, table.rows() - 1)
            starts = [editor.cursorRect(table.cellAt(first_row, index).firstCursorPosition()).left()
                      for index in range(table.columns())]
            frame = editor.document().documentLayout().frameBoundingRect(table)
            right = frame.right() - editor.horizontalScrollBar().value()
            widths = [max(48.0, float(b - a)) for a, b in zip(starts, [*starts[1:], right])]
        base = max(48.0, widths[column])
        ratio = max(0.5, (base + (-8 if key == Qt.Key.Key_Left else 8)) / base)
        for index in range(column, column + columns):
            widths[index] = max(48.0, widths[index] * ratio)
        return set_width(editor, "drag", widths)

    if key not in (Qt.Key.Key_Up, Qt.Key.Key_Down):
        return False
    target_rows = range(row, row + rows)
    frame = editor.document().documentLayout().frameBoundingRect(table)
    def row_top(index: int) -> float:
        first = table.cellAt(index, 0)
        fmt = first.format().toTableCellFormat()
        padding = (float(fmt.topPadding()) if fmt.hasProperty(QTextFormat.Property.TableCellTopPadding)
                   else float(table.format().cellPadding()))
        return float(editor.cursorRect(first.firstCursorPosition()).top()) - padding

    tops = [row_top(index) for index in range(table.rows())]
    bottoms = [*tops[1:], float(frame.bottom() - editor.verticalScrollBar().value())]
    heights = [max(16.0, bottom - top) for top, bottom in zip(tops, bottoms)]
    reference_height = heights[row]
    ratio = max(0.5, (reference_height + (-4 if key == Qt.Key.Key_Up else 4)) / reference_height)
    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    try:
        for current_row in target_rows:
            for current_column in range(table.columns()):
                cell = table.cellAt(current_row, current_column)
                if not cell.isValid() or cell.row() != current_row or cell.column() != current_column:
                    continue
                fmt = cell.format().toTableCellFormat()
                default_padding = float(table.format().cellPadding())
                top_padding = (float(fmt.topPadding()) if fmt.hasProperty(QTextFormat.Property.TableCellTopPadding)
                               else default_padding)
                bottom_padding = (float(fmt.bottomPadding())
                                  if fmt.hasProperty(QTextFormat.Property.TableCellBottomPadding)
                                  else default_padding)
                delta = heights[current_row] * (ratio - 1.0)
                new_bottom = max(0.0, bottom_padding + delta)
                fmt.setBottomPadding(new_bottom)
                if bottom_padding + delta < 0.0:
                    fmt.setTopPadding(max(0.0, top_padding + bottom_padding + delta))
                cell.setFormat(fmt)
    finally:
        transaction.endEditBlock()
    return True
