"""Basic QTextTable editing shared by memo editor windows and post-its."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QTextCursor, QTextLength, QTextTableFormat
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMenu, QToolButton, QToolTip


def active_cells(editor):
    cursor = editor.textCursor()
    table = cursor.currentTable()
    if table is None:
        return None
    if cursor.hasComplexSelection():
        row, rows, column, columns = cursor.selectedTableCells()
        if rows > 0 and columns > 0:
            return table, row, rows, column, columns
    cell = table.cellAt(cursor)
    if not cell.isValid():
        return None
    return table, cell.row(), 1, cell.column(), 1


def select(editor, scope: str) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table, row, rows, column, columns = active
    if scope == "row":
        column, columns = 0, table.columns()
    elif scope == "column":
        row, rows = 0, table.rows()
    elif scope != "cell":
        return False
    first = table.cellAt(row, column)
    last = table.cellAt(row + rows - 1, column + columns - 1)
    cursor = first.firstCursorPosition()
    cursor.setPosition(last.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    editor.setFocus()
    return True


def clear_contents(editor) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table, row, rows, column, columns = active
    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    try:
        for r in range(row + rows - 1, row - 1, -1):
            for c in range(column + columns - 1, column - 1, -1):
                cell = table.cellAt(r, c)
                target = cell.firstCursorPosition()
                target.setPosition(cell.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
                target.removeSelectedText()
    finally:
        transaction.endEditBlock()
    editor.setTextCursor(table.cellAt(row, column).firstCursorPosition())
    editor.setFocus()
    return True


def insert(editor, axis: str, before: bool) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table, row, rows, column, columns = active
    index = (row if before else row + rows) if axis == "row" else (column if before else column + columns)
    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    try:
        if axis == "row":
            table.insertRows(index, 1)
        elif axis == "column":
            table.insertColumns(index, 1)
        else:
            return False
    finally:
        transaction.endEditBlock()
    target = table.cellAt(index if axis == "row" else row, index if axis == "column" else column)
    editor.setTextCursor(target.firstCursorPosition())
    editor.setFocus()
    return True


def remove(editor, axis: str) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table, row, rows, column, columns = active
    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    try:
        if axis == "table" or (axis == "row" and rows == table.rows()) or (axis == "column" and columns == table.columns()):
            before = max(0, table.firstPosition() - 1)
            table.removeRows(0, table.rows())
            target = QTextCursor(editor.document())
            target.setPosition(min(before, editor.document().characterCount() - 1))
        elif axis == "row":
            table.removeRows(row, rows)
            target = table.cellAt(min(row, table.rows() - 1), min(column, table.columns() - 1)).firstCursorPosition()
        elif axis == "column":
            table.removeColumns(column, columns)
            target = table.cellAt(min(row, table.rows() - 1), min(column, table.columns() - 1)).firstCursorPosition()
        else:
            return False
    finally:
        transaction.endEditBlock()
    editor.setTextCursor(target)
    editor.setFocus()
    return True


def outside_paragraph(editor, before: bool) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table = active[0]
    cursor = QTextCursor(editor.document())
    cursor.setPosition(max(0, table.firstPosition() - 1) if before else table.lastPosition() + 1)
    cursor.beginEditBlock()
    try:
        cursor.insertBlock()
    finally:
        cursor.endEditBlock()
    editor.setTextCursor(cursor)
    editor.setFocus()
    return True


def set_width(editor, mode: str, widths: list[float] | None = None) -> bool:
    active = active_cells(editor)
    if active is None:
        return False
    table = active[0]
    fmt = QTextTableFormat(table.format())
    fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
    if mode == "even":
        value = 100.0 / table.columns()
        fmt.setColumnWidthConstraints([
            QTextLength(QTextLength.Type.PercentageLength, value) for _ in range(table.columns())
        ])
    elif mode == "fit":
        fmt.clearColumnWidthConstraints()
    elif mode == "drag" and widths is not None and len(widths) == table.columns():
        fmt.setColumnWidthConstraints([
            QTextLength(QTextLength.Type.FixedLength, max(48.0, width)) for width in widths
        ])
    else:
        return False
    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    try:
        table.setFormat(fmt)
    finally:
        transaction.endEditBlock()
    editor.setFocus()
    return True


def column_boundary(editor, point):
    table = editor.cursorForPosition(point).currentTable()
    if table is None or table.columns() < 2:
        return None
    frame = editor.document().documentLayout().frameBoundingRect(table)
    top = frame.top() - editor.verticalScrollBar().value()
    bottom = frame.bottom() - editor.verticalScrollBar().value()
    if not top <= point.y() <= bottom:
        return None
    cell = table.cellAt(editor.cursorForPosition(point))
    if not cell.isValid():
        return None
    padding = float(table.format().cellPadding())
    for column in range(1, table.columns()):
        boundary = editor.cursorRect(table.cellAt(cell.row(), column).firstCursorPosition()).left() - padding
        if abs(point.x() - boundary) <= 5:
            starts = [editor.cursorRect(table.cellAt(cell.row(), index).firstCursorPosition()).left()
                      for index in range(table.columns())]
            right = frame.right() - editor.horizontalScrollBar().value()
            widths = [max(48.0, float(b - a)) for a, b in zip(starts, [*starts[1:], right])]
            return table.firstPosition(), column, boundary, widths
    return None


class TableActionBar(QFrame):
    """One compact row in the editor's reserved bottom area."""

    HEIGHT = 38

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setObjectName("tableActionBar")
        self.setAccessibleName("표 도구")
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(
            "QFrame#tableActionBar{background:#f8fafc;border-top:1px solid #cbd5e1;}"
            "QToolButton{color:#172033;border:1px solid transparent;border-radius:5px;"
            "padding:3px 7px;min-height:25px;}"
            "QToolButton:hover{background:#e2e8f0;border-color:#cbd5e1;}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(4)
        for label, name, axis in (("행 +", "아래에 행 삽입", "row"), ("열 +", "오른쪽에 열 삽입", "column")):
            button = QToolButton(self)
            button.setText(label)
            button.setAccessibleName(name)
            button.setToolTip(name)
            button.clicked.connect(lambda _checked=False, direction=axis: insert(editor, direction, False))
            row.addWidget(button)
        self.more_button = QToolButton(self)
        self.more_button.setText("표 ▾")
        self.more_button.setAccessibleName("표 작업 더보기")
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.more_button)
        self.more_menu.aboutToShow.connect(lambda: populate_menu(self.more_menu, editor))
        self.more_button.setMenu(self.more_menu)
        row.addWidget(self.more_button)
        row.addStretch(1)
        self.hide()

    def sync(self) -> None:
        editor = self.editor
        visible = bool(editor.current_table() and not editor.block_selection.count()
                       and not editor.character_selection.count() and not editor.text_format_bar.is_reserved)
        if not visible:
            self.hide()
            editor._sync_selection_bar_height()
            return
        editor._sync_selection_bar_height()
        frame = editor.frameWidth()
        self.setGeometry(frame, editor.height() - frame - self.HEIGHT,
                         max(0, editor.width() - frame * 2), self.HEIGHT)
        self.show()
        self.raise_()


def populate_menu(menu: QMenu, editor) -> None:
    menu.clear()
    if active_cells(editor) is None:
        return
    groups = (
        (("셀 선택", lambda: select(editor, "cell")),
         ("행 선택", lambda: select(editor, "row")),
         ("열 선택", lambda: select(editor, "column"))),
        (("내용만 지우기", lambda: clear_contents(editor)),
         ("행 삭제", lambda: remove(editor, "row")),
         ("열 삭제", lambda: remove(editor, "column")),
         ("표 삭제", lambda: remove(editor, "table"))),
        (("위에 행 삽입", lambda: insert(editor, "row", True)),
         ("아래에 행 삽입", lambda: insert(editor, "row", False)),
         ("왼쪽에 열 삽입", lambda: insert(editor, "column", True)),
         ("오른쪽에 열 삽입", lambda: insert(editor, "column", False))),
        (("표 앞에 입력", lambda: outside_paragraph(editor, True)),
         ("표 뒤에 입력", lambda: outside_paragraph(editor, False))),
        (("열 너비 균등 분배", lambda: set_width(editor, "even")),
         ("본문 폭에 맞춤", lambda: set_width(editor, "fit"))),
    )
    for index, group in enumerate(groups):
        if index:
            menu.addSeparator()
        for label, callback in group:
            menu.addAction(label, callback)
    from .table_clipboard import excel_mime, paste_range
    from .table_input import show_split_dialog
    from .table_style import (
        align_cells, background_cells, merge_cells, padding_cells, split_cell, toggle_header,
    )

    def announce(result):
        _handled, error = result
        if error:
            QToolTip.showText(QCursor.pos(), error, editor)

    def copy_excel():
        mime = excel_mime(editor)
        if mime is not None:
            QApplication.clipboard().setMimeData(mime)

    def paste_excel():
        handled, error = paste_range(editor, QApplication.clipboard().mimeData())
        if not handled:
            error = "클립보드에 사각 표 범위가 없습니다."
        announce((handled, error))

    menu.addSeparator()
    menu.addAction("엑셀 범위 복사", copy_excel)
    menu.addAction("엑셀 범위 붙여넣기", paste_excel)
    formatting = menu.addMenu("셀 서식")
    for label, alignment in (("왼쪽 정렬", Qt.AlignmentFlag.AlignLeft),
                             ("가운데 정렬", Qt.AlignmentFlag.AlignHCenter),
                             ("오른쪽 정렬", Qt.AlignmentFlag.AlignRight)):
        formatting.addAction(label, lambda _checked=False, value=alignment: align_cells(editor, value))
    background = formatting.addMenu("배경색")
    for label, color in (("흰색", "#ffffff"), ("연회색", "#f1f5f9"),
                         ("연노랑", "#fef3c7"), ("연파랑", "#dbeafe")):
        background.addAction(label, lambda _checked=False, value=color: background_cells(editor, value))
    padding = formatting.addMenu("안쪽 여백")
    for amount in (2, 4, 8):
        padding.addAction(f"{amount}px", lambda _checked=False, value=amount: padding_cells(editor, value))
    formatting.addAction("첫 행 머리글 켜기/끄기", lambda: toggle_header(editor))
    merge = menu.addMenu("병합·분할")
    merge.addAction("선택 셀 병합", lambda: announce(merge_cells(editor)))
    split = merge.addAction("현재 셀 분할 (내용은 첫 셀에 남음)")
    split.setToolTip("분할은 구조만 나눕니다. 병합 전 내용 배치는 Undo로 복원할 수 있습니다.")
    split.triggered.connect(lambda: show_split_dialog(editor))
    active = active_cells(editor)
    if active is not None and active[2] * active[4] > 1:
        from .table_calculation import block_calculation

        calculations = menu.addMenu("블록 계산식")
        for label, name in (("블록 합계", "SUM"), ("블록 평균", "AVERAGE"), ("블록 곱", "PRODUCT")):
            calculations.addAction(
                label, lambda _checked=False, function=name: announce(block_calculation(editor, function)),
            )
