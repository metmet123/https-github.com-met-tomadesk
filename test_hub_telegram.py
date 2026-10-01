"""Telegram adapter fixtures never call Telegram or use real account identifiers."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from alert_notes.hub_actions import HubActionStore
from alert_notes.hub_telegram import TelegramRejected, text_action
from alert_notes.memo_organizer_store import OrganizerStore
from alert_notes.sqlite_store import NoteReminderStore


SENT = int(datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc).timestamp())
RECEIVED = datetime(2026, 10, 1, 16, 1, tzinfo=timezone.utc)


def update(update_id=123, text="내일 회신"):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 75,
            "from": {"id": 42, "is_bot": False},
            "chat": {"id": 42, "type": "private"},
            "date": SENT,
            "text": text,
        },
    }


def convert(value, *, bot_id=7):
    return text_action(value, bot_id=bot_id, allowed_user_id=42, allowed_chat_id=42,
                       received_at_utc=RECEIVED)


def test_private_text_maps_to_stable_action_and_sender_time(tmp_path):
    with patch("socket.socket", side_effect=AssertionError("network forbidden")):
        first = convert(update())
    second = convert(update())
    assert first == second
    assert first["source_event_id"] == "bot:7:update:123"
    assert first["payload"] == {"text": "내일 회신"}
    assert first["source_sent_at_utc"] == "2026-10-01T16:00:00Z"
    assert first["received_at_utc"] == "2026-10-01T16:01:00Z"
    assert first["action_id"] != convert(update(update_id=124))["action_id"]
    assert first["action_id"] != convert(update(), bot_id=8)["action_id"]
    store = NoteReminderStore(tmp_path / "telegram-adapter.db")
    try:
        hub = HubActionStore(store)
        receipt = hub.receive(first)
        assert hub.receive(second) == receipt
        assert hub.receive(convert(update(update_id=124)))["capture_id"] != receipt["capture_id"]
        assert hub.receive(convert(update(), bot_id=8))["capture_id"] != receipt["capture_id"]
        captured = OrganizerStore(store).get_capture(receipt["capture_id"])
        assert captured["base"] == "2026-10-02"
        assert captured["items"][0]["day"] == "2026-10-03"
    finally:
        store.close()


@pytest.mark.parametrize("change,code", [
    (lambda x: x["message"]["chat"].update(type="group"), "chat_not_allowed"),
    (lambda x: x["message"]["chat"].update(id=43), "chat_not_allowed"),
    (lambda x: x["message"]["from"].update(id=43), "user_not_allowed"),
    (lambda x: x["message"]["from"].update(is_bot=True), "user_not_allowed"),
    (lambda x: x["message"]["from"].pop("is_bot"), "user_not_allowed"),
    (lambda x: x["message"]["from"].update(is_bot="false"), "user_not_allowed"),
    (lambda x: x["message"].update(forward_origin={"type": "user"}), "forward_not_supported"),
    (lambda x: x["message"].update(business_connection_id="other"), "unsupported_context"),
    (lambda x: x["message"].update(text="/today"), "command_not_supported"),
    (lambda x: x["message"].pop("text"), "text_only"),
    (lambda x: x["message"].update(date="bad"), "invalid_message_date"),
    (lambda x: x.update(update_id=True), "invalid_update"),
    (lambda x: x.update(message=None), "unsupported_update"),
])
def test_unsupported_or_unpaired_updates_fail_closed(change, code):
    value = deepcopy(update())
    change(value)
    with pytest.raises(TelegramRejected) as error:
        convert(value)
    assert error.value.code == code


def test_adapter_requires_pairing_and_utc_receive_time():
    with pytest.raises(ValueError):
        text_action(update(), bot_id=7, allowed_user_id=0, allowed_chat_id=42)
    with pytest.raises(ValueError):
        text_action(update(), bot_id=0, allowed_user_id=42, allowed_chat_id=42)
    with pytest.raises(ValueError):
        text_action(update(), bot_id=7, allowed_user_id=42, allowed_chat_id=42,
                    received_at_utc=datetime(2026, 10, 1, 16, 1))
