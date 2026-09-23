"""Rectangular table values for Excel without changing internal block copies."""

from __future__ import annotations

import csv
import html
import io
from html.parser import HTMLParser

from PyQt6.QtCore import QMimeData
from PyQt6.QtGui import QTextCursor

from .table_edit import active_cells


class _HtmlTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.merged = False
        self.nested = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            if self.depth:
                self.nested = True
            self.depth += 1
        elif self.depth == 1 and tag == "tr":
            self.row = []
        elif self.depth == 1 and tag in {"td", "th"} and self.row is not None:
            attributes = dict(attrs)
            for name in ("rowspan", "colspan"):
                try:
                    self.merged |= int(attributes.get(name) or 1) > 1
                except ValueError:
                    self.merged = True
            self.cell = []
        elif self.cell is not None and tag == "br":
            self.cell.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "table" and self.depth:
            self.depth -= 1
        elif tag in {"td", "th"} and self.depth == 1 and self.cell is not None:
            self.row.append("".join(self.cell).rstrip("\n"))
            self.cell = None
        elif tag == "tr" and self.depth == 1 and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag in {"p", "div"} and self.cell is not None:
            self.cell.append("\n")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def _cell_text(cell) -> str:
    cursor = cell.firstCursorPosition()
    cursor.setPosition(cell.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
    return cursor.selectedText().replace("\u2029", "\n")


def selected_values(editor) -> list[list[str]] | None:
    active = active_cells(editor)
    if active is None:
        return None
    table, row, rows, column, columns = active
    return [[_cell_text(table.cellAt(r, c)) for c in range(column, column + columns)]
            for r in range(row, row + rows)]


def _tsv(values: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\r\n")
    writer.writerows(values)
    return output.getvalue()


def _excel_html(values: list[list[str]]) -> str:
    lines = ['<html><body><table>']
    for row in values:
        lines.append("<tr>")
        for value in row:
            # Excel's HTML clipboard treats this cell as text, including 001.
            content = html.escape(value).replace("\n", "<br>")
            lines.append('<td style="mso-number-format:\\@">' + content + "</td>")
        lines.append("</tr>")
    lines.append("</table></body></html>")
    return "".join(lines)


def excel_mime(editor) -> QMimeData | None:
    values = selected_values(editor)
    if values is None:
        return None
    mime = QMimeData()
    mime.setText(_tsv(values))
    mime.setHtml(_excel_html(values))
    return mime


def augment_range_mime(editor, mime: QMimeData) -> None:
    """Add Excel formats after the original HTML is saved in BLOCK_MIME."""
    if not editor.textCursor().hasComplexSelection():
        return
    rectangular = excel_mime(editor)
    if rectangular is not None:
        mime.setText(rectangular.text())
        mime.setHtml(rectangular.html())


def _rows_from_mime(source: QMimeData):
    raw = source.text()
    parser = _HtmlTable()
    if source.hasHtml():
        parser.feed(source.html())
    if parser.nested or parser.merged:
        return None, "병합되거나 중첩된 원본 표는 범위로 붙여넣을 수 없습니다."
    if parser.rows:
        rows = parser.rows
    else:
        if "\t" not in raw:
            return None, None
        try:
            rows = list(csv.reader(io.StringIO(raw, newline=""), delimiter="\t"))
        except csv.Error:
            return None, "클립보드 표 범위를 읽을 수 없습니다."
    if not rows:
        return None, "클립보드 표 범위가 비어 있습니다."
    width = max(len(row) for row in rows)
    if width == 0:
        return None, "클립보드 표 범위가 비어 있습니다."
    return [row + [""] * (width - len(row)) for row in rows], None


def paste_range(editor, source: QMimeData) -> tuple[bool, str | None]:
    """Return (handled, error). Reject merged targets before editing anything."""
    active = active_cells(editor)
    if active is None:
        return False, None
    values, error = _rows_from_mime(source)
    if values is None:
        return error is not None, error
    table, row, _selected_rows, column, _selected_columns = active
    end_row, end_column = row + len(values), column + len(values[0])
    for r in range(row, min(end_row, table.rows())):
        for c in range(column, min(end_column, table.columns())):
            cell = table.cellAt(r, c)
            if (not cell.isValid() or cell.row() != r or cell.column() != c
                    or cell.rowSpan() != 1 or cell.columnSpan() != 1):
                return True, "병합된 대상 셀과 겹쳐 문서를 변경하지 않았습니다."
    transaction = QTextCursor(editor.document())
    transaction.beginEditBlock()
    try:
        if end_row > table.rows():
            table.appendRows(end_row - table.rows())
        if end_column > table.columns():
            table.appendColumns(end_column - table.columns())
        for row_offset, values_row in enumerate(values):
            for column_offset, value in enumerate(values_row):
                cell = table.cellAt(row + row_offset, column + column_offset)
                target = cell.firstCursorPosition()
                target.setPosition(cell.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
                target.removeSelectedText()
                target.insertText(value)
    finally:
        transaction.endEditBlock()
    editor.setTextCursor(table.cellAt(row, column).firstCursorPosition())
    editor.setFocus()
    return True, None
