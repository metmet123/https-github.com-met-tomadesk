"""Small, bounded spreadsheet formulas for rich memo tables."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re


_CELL = re.compile(r"^(\$?)([A-Z]+)(\$?)([1-9][0-9]*)$", re.I)
_FORMULA = re.compile(
    r"^=(SUM|AVERAGE|PRODUCT)\s*\(\s*(\$?[A-Z]+\$?[1-9][0-9]*)"
    r"(?:\s*:\s*(\$?[A-Z]+\$?[1-9][0-9]*))?\s*\)$", re.I,
)
_NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$")
_THOUSANDS = re.compile(r"^[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]*)?$")


def cell_address(row: int, column: int) -> str:
    if row < 0 or column < 0:
        raise ValueError("셀 좌표가 올바르지 않습니다.")
    letters = ""
    column += 1
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row + 1}"


def _parse_cell(value: str) -> tuple[int, int, bool, bool]:
    match = _CELL.fullmatch(value.strip())
    if match is None:
        raise ValueError("셀 주소는 A1 형식으로 입력해 주세요.")
    fixed_column, letters, fixed_row, number = match.groups()
    column = 0
    for letter in letters.upper():
        column = column * 26 + ord(letter) - 64
    return int(number) - 1, column - 1, bool(fixed_row), bool(fixed_column)


def parse_formula(formula: str) -> tuple[str, int, int, int, int]:
    if len(formula) > 256:
        raise ValueError("수식은 256자까지 입력할 수 있습니다.")
    match = _FORMULA.fullmatch(formula.strip())
    if match is None:
        raise ValueError("SUM, AVERAGE, PRODUCT와 A1:B2 범위만 지원합니다.")
    name, first, last = match.groups()
    row_a, col_a, _, _ = _parse_cell(first)
    row_b, col_b, _, _ = _parse_cell(last or first)
    return name.upper(), min(row_a, row_b), max(row_a, row_b), min(col_a, col_b), max(col_a, col_b)


def _number(value: str) -> Decimal | None:
    text = str(value or "").strip()
    if "," in text and not _THOUSANDS.fullmatch(text):
        return None
    text = text.replace(",", "")
    if len(text) > 128:
        return None
    if not text or not _NUMBER.fullmatch(text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def calculate(values, name: str) -> str:
    numbers = [number for value in values if (number := _number(value)) is not None]
    if name == "SUM":
        result = sum(numbers, Decimal(0))
    elif name == "AVERAGE":
        result = sum(numbers, Decimal(0)) / len(numbers) if numbers else Decimal(0)
    elif name == "PRODUCT":
        result = Decimal(1)
        for number in numbers:
            result *= number
        if not numbers:
            result = Decimal(0)
    else:
        raise ValueError("지원하지 않는 계산입니다.")
    if not result.is_finite():
        raise ValueError("계산 결과가 올바르지 않습니다.")
    return format(result.normalize(), "f")


def evaluate(table, formula: str) -> str:
    name, first_row, last_row, first_col, last_col = parse_formula(formula)
    if last_row >= table.rows() or last_col >= table.columns():
        raise ValueError("표 밖의 셀을 참조합니다.")
    if (last_row - first_row + 1) * (last_col - first_col + 1) > 10_000:
        raise ValueError("한 번에 계산할 수 있는 셀 수를 넘었습니다.")
    values = []
    for row in range(first_row, last_row + 1):
        for column in range(first_col, last_col + 1):
            values.append(table.cellAt(row, column).firstCursorPosition().block().text())
    return calculate(values, name)


def shifted_formula(formula: str, row_delta: int, column_delta: int) -> str:
    if len(formula) > 256:
        raise ValueError("채울 수 없는 수식입니다.")
    match = _FORMULA.fullmatch(formula.strip())
    if match is None:
        raise ValueError("채울 수 없는 수식입니다.")

    def shift(value: str) -> str:
        row, col, fixed_row, fixed_col = _parse_cell(value)
        row += 0 if fixed_row else row_delta
        col += 0 if fixed_col else column_delta
        if row < 0 or col < 0:
            raise ValueError("채운 수식이 표 밖을 참조합니다.")
        address = cell_address(row, col)
        match = _CELL.fullmatch(address)
        assert match is not None
        return ("$" if fixed_col else "") + match.group(2) + ("$" if fixed_row else "") + match.group(4)

    name, first, last = match.groups()
    return f"={name.upper()}({shift(first)}{':' + shift(last) if last else ''})"


def series_values(seeds: list[str], count: int) -> list[str]:
    """Continue dates/numbers, or repeat text; never coerce leading-zero text."""
    if not seeds or count < 0 or count > 1000:
        raise ValueError("채우기 시작 셀과 개수가 필요합니다.")
    if len(seeds) > 1:
        try:
            dates = [date.fromisoformat(item) for item in seeds]
            step = dates[-1] - dates[-2]
            if all(b - a == step for a, b in zip(dates, dates[1:])):
                return [(dates[-1] + step * index).isoformat() for index in range(1, count + 1)]
        except (ValueError, OverflowError):
            pass
    elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", seeds[0]):
        try:
            initial = date.fromisoformat(seeds[0])
            return [(initial + timedelta(days=index)).isoformat() for index in range(1, count + 1)]
        except (ValueError, OverflowError):
            pass
    numbers = [_number(value) for value in seeds]
    if all(value is not None for value in numbers) and all(
        not re.fullmatch(r"0[0-9]+", text.strip()) for text in seeds
    ):
        step = numbers[-1] - numbers[-2] if len(numbers) > 1 else Decimal(1)
        if all(b - a == step for a, b in zip(numbers, numbers[1:])):
            return [format((numbers[-1] + step * index).normalize(), "f") for index in range(1, count + 1)]
    return [seeds[index % len(seeds)] for index in range(count)]
