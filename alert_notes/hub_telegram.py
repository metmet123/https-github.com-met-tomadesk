"""Pure Telegram Update -> Action v1 adapter; it never calls the Bot API.

Only updates already fetched by a trusted receiver should reach this function.
It still checks the paired private user/chat and rejects unsupported content.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5


class TelegramRejected(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


def text_action(update: object, *, bot_id: int, allowed_user_id: int, allowed_chat_id: int,
                received_at_utc: datetime | None = None) -> dict:
    """Map one paired private text message to a deterministic capture Action."""
    if not all(_positive_id(value) for value in (bot_id, allowed_user_id, allowed_chat_id)):
        raise ValueError("연결된 Telegram 봇·계정 ID가 필요합니다.")
    if (not isinstance(update, dict) or type(update.get("update_id")) is not int
            or update["update_id"] < 0):
        raise TelegramRejected("invalid_update")
    message = update.get("message")
    if not isinstance(message, dict):
        raise TelegramRejected("unsupported_update")
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        raise TelegramRejected("invalid_message")
    if chat.get("type") != "private" or not _positive_id(chat.get("id")) or chat.get("id") != allowed_chat_id:
        raise TelegramRejected("chat_not_allowed")
    if (not _positive_id(sender.get("id")) or sender.get("id") != allowed_user_id
            or sender.get("is_bot") is not False):
        raise TelegramRejected("user_not_allowed")
    if message.get("business_connection_id") or message.get("sender_chat"):
        raise TelegramRejected("unsupported_context")
    if message.get("forward_origin") or message.get("is_automatic_forward"):
        raise TelegramRejected("forward_not_supported")
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        raise TelegramRejected("text_only")
    if text.lstrip().startswith("/"):
        raise TelegramRejected("command_not_supported")
    if len(text) > 20_000:
        raise TelegramRejected("text_too_long")
    timestamp = message.get("date")
    if type(timestamp) is not int or timestamp < 0:
        raise TelegramRejected("invalid_message_date")
    try:
        sent = datetime.fromtimestamp(timestamp, timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise TelegramRejected("invalid_message_date") from exc
    received = received_at_utc or datetime.now(timezone.utc)
    if received.tzinfo is None or received.utcoffset() != timezone.utc.utcoffset(received):
        raise ValueError("received_at_utc은 UTC 시각이어야 합니다.")
    update_id = update["update_id"]
    # update_id belongs to a bot, not to all Telegram bots globally. Including
    # the public bot ID avoids collisions after replacing the paired bot.
    source_event_id = f"bot:{bot_id}:update:{update_id}"
    return {
        "schema_version": 1,
        "action_id": str(uuid5(NAMESPACE_URL, f"tomadesk:telegram:{source_event_id}")),
        "source": "telegram",
        "source_event_id": source_event_id,
        "source_sent_at_utc": sent.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "received_at_utc": received.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "base_timezone": "Asia/Seoul",
        "kind": "capture_text",
        "payload": {"text": text},
    }
