"""Publish terminal Telegram receipts into the opted-in synced Drive folder.

Files contain only IDs and a terminal state, never the user's message or bot
token. The Apps Script poller sends them and leaves a sent marker in Drive.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timedelta


_EVENT_ID = re.compile(r"bot:([1-9][0-9]*):update:(0|[1-9][0-9]*)\Z")
_MAX_REPLY_BYTES = 2048
_MAX_INCOMING_BYTES = 128 * 1024


def _reply_bytes(row, *, bot_id: int, chat_id: int) -> tuple[str, bytes]:
    match = _EVENT_ID.fullmatch(row["source_event_id"])
    if not match or int(match.group(1)) != bot_id:
        raise ValueError("Telegram 영수증의 봇·업데이트 ID가 올바르지 않습니다.")
    update_id = int(match.group(2))
    state = row["state"]
    if state not in {"applied", "rejected"} or not isinstance(row["processed_at_utc"], str):
        raise ValueError("Telegram 영수증이 완료 상태가 아닙니다.")
    count = row["applied_count"]
    if type(count) is not int or count < 0 or (state == "applied" and count == 0):
        raise ValueError("Telegram 영수증의 반영 개수가 올바르지 않습니다.")
    record = {
        "schema_version": 1, "transport": "telegram_reply", "bot_id": bot_id,
        "update_id": update_id, "chat_id": chat_id, "state": state,
        "applied_count": count, "processed_at_utc": row["processed_at_utc"],
    }
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_REPLY_BYTES:
        raise ValueError("Telegram 영수증이 너무 큽니다.")
    return f"reply_{bot_id}_{update_id}_{state}.json", encoded


def _paired_incoming(folder: Path, *, bot_id: int, update_id: int,
                     user_id: int, chat_id: int) -> bool:
    path = folder / f"telegram_{bot_id}_{update_id}.json"
    if path.is_symlink() or not path.is_file():
        return False
    if path.stat().st_size > _MAX_INCOMING_BYTES:
        raise ValueError("Telegram 수신 파일이 너무 큽니다.")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Telegram 수신 파일을 읽을 수 없습니다.") from exc
    if not isinstance(record, dict) or not isinstance(record.get("message"), dict):
        raise ValueError("Telegram 수신 파일 형식이 올바르지 않습니다.")
    message = record["message"]
    sender, chat = message.get("from"), message.get("chat")
    return (type(record.get("bot_id")) is int and record["bot_id"] == bot_id
            and type(record.get("update_id")) is int and record["update_id"] == update_id
            and isinstance(sender, dict) and type(sender.get("id")) is int
            and sender["id"] == user_id and sender.get("is_bot") is False
            and isinstance(chat, dict) and type(chat.get("id")) is int
            and chat["id"] == chat_id and chat.get("type") == "private")


def publish_terminal_replies(store, folder: Path, *, bot_id: int,
                             user_id: int, chat_id: int,
                             not_before_utc: datetime | None = None) -> int:
    """Write immutable reply files, retrying safely after local/Drive failures.

    The selected incoming folder is already a local Drive-synced directory.
    Existing files are never overwritten, including a sent marker made by the
    Apps Script poller. Delivery over Telegram itself cannot be exactly-once.
    """
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Telegram 수신 폴더가 올바르지 않습니다.")
    rows = store.conn.execute(
        "SELECT source_event_id,state,applied_count,processed_at_utc FROM hub_actions "
        "WHERE source='telegram' AND state IN ('applied','rejected') "
        "ORDER BY created_at_utc,action_id"
    ).fetchall()
    created = 0
    for row in rows:
        if not_before_utc is not None:
            try:
                processed = datetime.fromisoformat(row["processed_at_utc"].replace("Z", "+00:00"))
            except (AttributeError, ValueError) as exc:
                raise ValueError("Telegram 영수증의 처리 시각이 올바르지 않습니다.") from exc
            if processed.tzinfo is None or processed.utcoffset() != timedelta(0):
                raise ValueError("Telegram 영수증의 처리 시각은 UTC여야 합니다.")
            if processed < not_before_utc:
                continue
        match = _EVENT_ID.fullmatch(row["source_event_id"])
        if match and int(match.group(1)) != bot_id:
            continue  # Historical receipts for a previously paired bot.
        if match and not _paired_incoming(folder, bot_id=bot_id,
                                          update_id=int(match.group(2)),
                                          user_id=user_id, chat_id=chat_id):
            continue  # Never send another paired user's old receipt.
        name, encoded = _reply_bytes(row, bot_id=bot_id, chat_id=chat_id)
        destination = folder / name
        sent_marker = folder / ("sent_" + name)
        for path in (destination, sent_marker):
            if path.is_symlink():
                raise ValueError("Telegram 회신 파일 형식이 올바르지 않습니다.")
            if path.exists():
                if not path.is_file() or path.stat().st_size > _MAX_REPLY_BYTES or path.read_bytes() != encoded:
                    raise ValueError("Telegram 회신 파일이 기존 영수증과 충돌합니다.")
        if destination.exists() or sent_marker.exists():
            continue
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".telegram_reply_",
                                             suffix=".tmp", delete=False) as temporary:
                temp_path = Path(temporary.name)
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            # Do not replace a file that appeared while the temp was written.
            if destination.exists() or sent_marker.exists():
                raise ValueError("Telegram 회신 파일이 동시에 생성되었습니다.")
            os.replace(temp_path, destination)
            temp_path = None
            created += 1
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    return created
