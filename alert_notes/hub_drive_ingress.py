"""Convert one minimal Drive transport record into the local Hub Action ledger.

The caller is responsible for downloading records from the private Drive
folder. This module makes no network requests and never accepts credentials.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re

from .hub_actions import HubActionStore
from .hub_telegram import text_action


_FIELDS = {"schema_version", "transport", "bot_id", "update_id", "received_at_utc", "message"}
_FILE_NAME = re.compile(r"telegram_([1-9][0-9]*)_(0|[1-9][0-9]*)\.json\Z")
# Up to 20,000 Unicode code points can occupy 80 KiB in UTF-8, plus JSON.
_MAX_RECORD_BYTES = 128 * 1024


def receive_telegram_record(store, record: object, *, bot_id: int,
                            allowed_user_id: int, allowed_chat_id: int) -> dict:
    """Store a paired text update once; retries return the same receipt."""
    if not isinstance(record, dict) or set(record) != _FIELDS:
        raise ValueError("Telegram 전달 기록 형식이 잘못되었습니다.")
    if record["schema_version"] != 1 or type(record["schema_version"]) is not int:
        raise ValueError("지원하지 않는 Telegram 전달 기록 버전입니다.")
    if record["transport"] != "telegram" or type(record["bot_id"]) is not int or record["bot_id"] != bot_id:
        raise ValueError("연결된 Telegram 봇의 기록이 아닙니다.")
    received = record["received_at_utc"]
    if not isinstance(received, str):
        raise ValueError("Telegram 수신 시각이 잘못되었습니다.")
    try:
        received_at = datetime.fromisoformat(received.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Telegram 수신 시각이 잘못되었습니다.") from exc
    if received_at.tzinfo is None or received_at.utcoffset() != timedelta(0):
        raise ValueError("Telegram 수신 시각은 UTC여야 합니다.")
    action = text_action(
        {"update_id": record["update_id"], "message": record["message"]},
        bot_id=bot_id,
        allowed_user_id=allowed_user_id,
        allowed_chat_id=allowed_chat_id,
        received_at_utc=received_at,
    )
    return HubActionStore(store).receive(action)


def import_telegram_folder(store, folder: Path, *, bot_id: int,
                           allowed_user_id: int, allowed_chat_id: int) -> list[dict]:
    """Import complete files from a locally available Drive folder, without deleting them.

    Re-scanning is intentional: the Action ledger deduplicates retries. A bad
    record stops the scan so an operator can inspect it; earlier imports remain
    safely committed. This function does not sync, authenticate, or poll Drive.
    """
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Telegram 수신 폴더가 올바르지 않습니다.")
    receipts = []
    for path in sorted(folder.iterdir(), key=lambda item: item.name):
        match = _FILE_NAME.fullmatch(path.name)
        if not match:
            continue
        # A reused inbox may still contain files from a previously paired bot.
        # Only the current bot's files belong to this scan; otherwise an old
        # record can stop every later poll before new messages are imported.
        if int(match.group(1)) != bot_id:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("Telegram 수신 파일 형식이 올바르지 않습니다.")
        with path.open("rb") as source:
            raw = source.read(_MAX_RECORD_BYTES + 1)
        if len(raw) > _MAX_RECORD_BYTES:
            raise ValueError("Telegram 수신 파일이 너무 큽니다.")
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Telegram 수신 파일을 읽을 수 없습니다.") from exc
        if (not isinstance(record, dict) or type(record.get("bot_id")) is not int
                or type(record.get("update_id")) is not int
                or record["bot_id"] != int(match.group(1))
                or record["update_id"] != int(match.group(2))):
            raise ValueError("Telegram 수신 파일 이름과 내용이 일치하지 않습니다.")
        receipts.append(receive_telegram_record(
            store, record, bot_id=bot_id, allowed_user_id=allowed_user_id,
            allowed_chat_id=allowed_chat_id,
        ))
    return receipts
