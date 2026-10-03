"""Opt-in, local-folder handoff for Telegram records downloaded from Drive.

This module never talks to Google or Telegram. A folder selected on this PC
may be a synced Drive folder, but its sync/authentication remains external.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from .hub_drive_ingress import import_telegram_folder
from .hub_telegram_replies import publish_terminal_replies


CONFIG_NAME = "hub_telegram_folder.json"
REPLY_START_NAME = "hub_telegram_reply_start.txt"
_FIELDS = {"version", "enabled", "folder", "bot_id", "user_id", "chat_id"}
_MAX_CONFIG_BYTES = 4096
_MAX_ID = 2**53 - 1  # Apps Script stores these IDs as JavaScript safe integers.


def _positive_id(value: object) -> bool:
    return type(value) is int and 0 < value <= _MAX_ID


def validate_config(value: object, *, require_folder: bool = False) -> dict:
    if (not isinstance(value, dict) or set(value) != _FIELDS
            or type(value["version"]) is not int or value["version"] != 1
            or type(value["enabled"]) is not bool
            or not all(_positive_id(value[key]) for key in ("bot_id", "user_id", "chat_id"))):
        raise ValueError("Telegram 수신 폴더 설정이 올바르지 않습니다.")
    folder = value["folder"]
    if not isinstance(folder, str) or not folder.strip() or len(folder) > 1000:
        raise ValueError("Telegram 수신 폴더 경로가 올바르지 않습니다.")
    path = Path(folder)
    if not path.is_absolute() or path == Path(path.anchor) or path.is_symlink():
        raise ValueError("Telegram 수신 폴더는 실제 하위 폴더를 선택해 주세요.")
    if require_folder and not path.is_dir():
        raise ValueError("Telegram 수신 폴더를 찾을 수 없습니다.")
    return dict(value)


class HubFolderSync:
    """Scan complete records periodically; the Action ledger makes retries safe."""

    def __init__(self, store):
        self.store = store
        self.config_path = Path(store.path).parent / CONFIG_NAME
        self.reply_start_path = Path(store.path).parent / REPLY_START_NAME

    def load(self) -> dict | None:
        path = self.config_path
        if path.is_symlink():
            raise ValueError("Telegram 수신 설정 파일을 읽을 수 없습니다.")
        if not path.exists():
            return None
        if not path.is_file():
            raise ValueError("Telegram 수신 설정 파일을 읽을 수 없습니다.")
        with path.open("rb") as source:
            raw = source.read(_MAX_CONFIG_BYTES + 1)
        if len(raw) > _MAX_CONFIG_BYTES:
            raise ValueError("Telegram 수신 설정 파일이 너무 큽니다.")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Telegram 수신 설정 파일을 읽을 수 없습니다.") from exc
        return validate_config(value)

    def save(self, value: dict) -> None:
        config = validate_config(value, require_folder=bool(value.get("enabled")) if isinstance(value, dict) else False)
        try:
            previous = self.load()
        except (ValueError, OSError):
            previous = None
        destination = self.config_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_CONFIG_BYTES:
            raise ValueError("Telegram 수신 설정 파일이 너무 큽니다.")
        reset_replies = config["enabled"] and (
            previous is None or not previous["enabled"] or
            any(previous[key] != config[key] for key in
                ("folder", "bot_id", "user_id", "chat_id"))
        )
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".hub_telegram_",
                                             suffix=".tmp", delete=False) as temporary:
                temp_path = Path(temporary.name)
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            # A failed cutoff write must not activate a new pairing with an
            # old cutoff, which could publish historical replies to it.
            if reset_replies:
                self._write_reply_start(datetime.now(timezone.utc))
            os.replace(temp_path, destination)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _write_reply_start(self, started: datetime) -> None:
        destination = self.reply_start_path
        staged = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".hub_reply_start_",
                                             suffix=".tmp", delete=False) as stream:
                staged = Path(stream.name)
                stream.write(started.isoformat().encode("ascii"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staged, destination)
            staged = None
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    def ensure_replies_started(self) -> datetime | None:
        config = self.load()
        if not config or not config["enabled"]:
            return None
        path = self.reply_start_path
        if path.is_symlink():
            raise ValueError("Telegram 회신 시작 기록을 읽을 수 없습니다.")
        if not path.exists():
            self._write_reply_start(datetime.now(timezone.utc))
        if not path.is_file() or path.stat().st_size > 64:
            raise ValueError("Telegram 회신 시작 기록을 읽을 수 없습니다.")
        try:
            started = datetime.fromisoformat(path.read_text(encoding="ascii"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Telegram 회신 시작 기록을 읽을 수 없습니다.") from exc
        if started.tzinfo is None or started.utcoffset() != timezone.utc.utcoffset(started):
            raise ValueError("Telegram 회신 시작 시각이 올바르지 않습니다.")
        return started

    def disable(self) -> None:
        config = self.load()
        if config and config["enabled"]:
            config["enabled"] = False
            self.save(config)

    def scan(self) -> dict:
        config = self.load()
        if not config or not config["enabled"]:
            return {"state": "off", "new": 0, "files": 0, "checked_at_utc": None}
        validate_config(config, require_folder=True)
        reply_start = self.ensure_replies_started()
        before = self.store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0]
        receipts = import_telegram_folder(
            self.store, Path(config["folder"]), bot_id=config["bot_id"],
            allowed_user_id=config["user_id"], allowed_chat_id=config["chat_id"],
        )
        reply_files = publish_terminal_replies(
            self.store, Path(config["folder"]), bot_id=config["bot_id"],
            user_id=config["user_id"], chat_id=config["chat_id"],
            not_before_utc=reply_start,
        )
        after = self.store.conn.execute("SELECT COUNT(*) FROM hub_actions").fetchone()[0]
        return {
            "state": "ok", "new": after - before, "files": len(receipts),
            "reply_files": reply_files,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
