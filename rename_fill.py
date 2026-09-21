"""Pure, string-preserving downward series generation (no file operations)."""
import re


def _number(text):
    if len(text) > 1024:
        return None  # Preserve oversized pasted text without costly inference.
    if re.fullmatch(r"[ \t]*[+-]?[0-9]+[.,][0-9]+[ \t]*", text):
        return None  # Decimal/thousands notation is text, not a suffix series.
    # Signs are numeric only for an otherwise numeric cell: '문서-01' has
    # prefix '문서-' and positive suffix 01, not the integer -1.
    match = re.fullmatch(r"([ \t]*)([+-]?)([0-9]+)([ \t]*)", text)
    if match:
        prefix, sign, digits, suffix = match.groups()
        number = int(sign + digits)
        return prefix, suffix, number, len(digits) if len(digits) > 1 and digits[0] == "0" else 0, sign == "+", True
    match = re.fullmatch(r"(.*?)([0-9]+)([ \t]*)", text)
    if match:
        prefix, digits, suffix = match.groups()
        return prefix, suffix, int(digits), len(digits) if len(digits) > 1 and digits[0] == "0" else 0, False, False
    return None


def extend_series(seeds, count):
    """Continue a uniform integer suffix series, otherwise repeat the pattern.

    No stripping/coercion of cells. Unrelated text/blank seeds are cycled exactly.
    Decimal/date semantics are not inferred; only final ASCII integer digits.
    """
    if not seeds or count < 0:
        raise ValueError("시작 값과 올바른 채우기 개수가 필요합니다.")
    try:
        parsed = [_number(value) for value in seeds]
    except ValueError:  # Python's large integer conversion limit: copy as text.
        parsed = [None]
    if all(item is not None for item in parsed):
        first = parsed[0]
        compatible = all((p[0], p[1], p[4], p[5]) == (first[0], first[1], first[4], first[5]) for p in parsed)
        step = parsed[1][2] - first[2] if len(parsed) > 1 else 1
        compatible = compatible and all(b[2] - a[2] == step for a, b in zip(parsed, parsed[1:]))
        if compatible:
            width = max(p[3] for p in parsed)
            result = []
            for i in range(1, count + 1):
                number = parsed[-1][2] + step * i
                sign = "-" if number < 0 else "+" if first[4] else ""
                result.append(first[0] + sign + str(abs(number)).zfill(width) + first[1])
            return result
    return [seeds[i % len(seeds)] for i in range(count)]
