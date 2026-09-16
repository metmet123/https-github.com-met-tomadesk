from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4


def new_sync_id() -> str:
    """Return the stable wire identifier used outside one local database."""
    return str(uuid4())


def utc_now_ms() -> str:
    """UTC timestamp with millisecond precision and an explicit Z suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def valid_sync_id(value: object) -> bool:
    try:
        return UUID(str(value)).version == 4
    except (ValueError, TypeError, AttributeError):
        return False
