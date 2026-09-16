"""Pure title marker rules shared by the memo list and title suggestions."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterable, Mapping
import unicodedata


ZWJ = "\u200d"
_PREFIX = re.compile(r"^\[\s*([^\[\]\r\n]{1,20}?)\s*\]")


@dataclass(frozen=True)
class TitleValueCount:
    key: str
    display: str
    count: int
    latest_updated_at: str


def _is_extend(character: str) -> bool:
    code = ord(character)
    return (
        unicodedata.category(character) in {"Mn", "Mc", "Me"}
        or code in {0xFE0E, 0xFE0F}
        or 0x1F3FB <= code <= 0x1F3FF
        or 0xE0020 <= code <= 0xE007F
    )


def _is_regional_indicator(character: str) -> bool:
    return 0x1F1E6 <= ord(character) <= 0x1F1FF


def leading_title_symbol(title: str) -> str | None:
    """Return one leading symbol grapheme, ignoring whitespace.

    Only Unicode So markers qualify. Variation selectors, skin tones, flags
    and ZWJ emoji stay together as the displayed grapheme.
    """

    text = str(title or "").lstrip()
    if not text or unicodedata.category(text[0]) != "So":
        return None

    cluster = [text[0]]
    index = 1
    if _is_regional_indicator(text[0]) and index < len(text) and _is_regional_indicator(text[index]):
        cluster.append(text[index])
        index += 1

    while index < len(text):
        character = text[index]
        if _is_extend(character):
            cluster.append(character)
            index += 1
            continue
        if character == ZWJ and index + 1 < len(text):
            cluster.extend((character, text[index + 1]))
            index += 2
            continue
        break
    return "".join(cluster)


def title_symbol_key(symbol: str) -> str:
    """Ignore presentation selectors and skin tones while keeping the shape."""

    return "".join(
        character for character in str(symbol or "")
        if ord(character) not in {0xFE0E, 0xFE0F}
        and not 0x1F3FB <= ord(character) <= 0x1F3FF
    )


def leading_title_prefix(title: str) -> str | None:
    """Return the inner text of the first intentional leading ``[prefix]``."""

    text = str(title or "").lstrip()
    while symbol := leading_title_symbol(text):
        text = text[len(symbol):].lstrip()
    match = _PREFIX.match(text)
    if match is None:
        return None
    inner = match.group(1).strip()
    return inner or None


def title_prefix_key(inner: str) -> str:
    """Use canonical spelling and case-insensitive matching for prefixes."""

    return unicodedata.normalize("NFC", str(inner or "")).casefold()


def count_title_values(
    rows: Iterable[Mapping[str, object]],
    extractor: Callable[[str], str | None],
    key_func: Callable[[str], str],
) -> list[TitleValueCount]:
    """Count markers, retaining the newest spelling for each comparison key.

    ``updated_at`` is the existing sortable local timestamp. Equal timestamps
    keep the first row's spelling, so callers can supply their stable row order.
    """

    values: dict[str, TitleValueCount] = {}
    for row in rows:
        display = extractor(str(row["title"] or ""))
        if display is None:
            continue
        key = key_func(display)
        if not key:
            continue
        updated_at = str(row["updated_at"] or "")
        previous = values.get(key)
        if previous is None:
            values[key] = TitleValueCount(key, display, 1, updated_at)
        else:
            newer = updated_at > previous.latest_updated_at
            values[key] = TitleValueCount(
                key,
                display if newer else previous.display,
                previous.count + 1,
                updated_at if newer else previous.latest_updated_at,
            )
    ordered = sorted(values.values(), key=lambda value: value.key)
    ordered.sort(key=lambda value: value.latest_updated_at, reverse=True)
    ordered.sort(key=lambda value: value.count, reverse=True)
    return ordered
