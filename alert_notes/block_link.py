"""Versioned intra-memo links to one stable block identity."""

from __future__ import annotations

import re
from uuid import UUID


_V1_URL = re.compile(r"^toma-block://v1/([1-9][0-9]*)/([0-9a-fA-F-]{36})$", re.IGNORECASE)
_V2_URL = re.compile(r"^toma-block://v2/([0-9a-fA-F-]{36})/([0-9a-fA-F-]{36})$", re.IGNORECASE)


def block_url(memo_id: int | str, block_id: str) -> str:
    identity = UUID(str(block_id))
    if identity.version != 4:
        raise ValueError("A UUIDv4 block identity is required")
    try:
        local_id = int(memo_id)
    except (TypeError, ValueError):
        local_id = 0
    if local_id > 0:
        return f"toma-block://v1/{local_id}/{identity}"
    memo_identity = UUID(str(memo_id))
    if memo_identity.version != 4:
        raise ValueError("A UUIDv4 memo identity is required")
    return f"toma-block://v2/{memo_identity}/{identity}"


def parse_block_url(value: str) -> tuple[int | str, str] | None:
    text = str(value or "")
    match = _V1_URL.fullmatch(text)
    version = 1
    if match is None:
        match = _V2_URL.fullmatch(text)
        version = 2
    if match is None:
        return None
    try:
        identity = UUID(match.group(2))
    except ValueError:
        return None
    if identity.version != 4:
        return None
    if version == 1:
        return int(match.group(1)), str(identity)
    try:
        memo_identity = UUID(match.group(1))
    except ValueError:
        return None
    return (str(memo_identity), str(identity)) if memo_identity.version == 4 else None
