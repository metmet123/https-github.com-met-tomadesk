"""PC-local configuration and explicit OAuth boundary for Drive downloads."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .hub_folder_sync import HubFolderSync
from .hub_google_drive import (
    _validate_folder_id, authorize_drive, download_drive_folder, saved_drive_service,
)


CONFIG_NAME = "hub_google_drive.json"
TOKEN_NAME = "hub_google_token.json"
_FIELDS = {"version", "enabled", "folder_id", "oauth_client_file"}
_MAX_CONFIG_BYTES = 4096


def validate_drive_config(value: object, *, require_client: bool = False) -> dict:
    if (not isinstance(value, dict) or set(value) != _FIELDS
            or type(value["version"]) is not int or value["version"] != 1
            or type(value["enabled"]) is not bool):
        raise ValueError("Google Drive 수신 설정이 올바르지 않습니다.")
    _validate_folder_id(value["folder_id"])
    raw = value["oauth_client_file"]
    if not isinstance(raw, str) or not raw or len(raw) > 1000:
        raise ValueError("Google OAuth 클라이언트 파일 경로가 올바르지 않습니다.")
    client = Path(raw)
    if not client.is_absolute() or client.is_symlink() or (require_client and not client.is_file()):
        raise ValueError("Google OAuth 클라이언트 JSON을 찾을 수 없습니다.")
    return dict(value)


class HubGoogleSync:
    def __init__(self, store):
        self.folder_sync = HubFolderSync(store)
        parent = Path(store.path).parent
        self.config_path = parent / CONFIG_NAME
        self.token_path = parent / TOKEN_NAME

    def load(self) -> dict | None:
        path = self.config_path
        if path.is_symlink():
            raise ValueError("Google Drive 수신 설정 파일을 읽을 수 없습니다.")
        if not path.exists():
            return None
        if not path.is_file():
            raise ValueError("Google Drive 수신 설정 파일을 읽을 수 없습니다.")
        with path.open("rb") as source:
            raw = source.read(_MAX_CONFIG_BYTES + 1)
        if len(raw) > _MAX_CONFIG_BYTES:
            raise ValueError("Google Drive 수신 설정 파일이 너무 큽니다.")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Google Drive 수신 설정 파일을 읽을 수 없습니다.") from exc
        return validate_drive_config(value)

    def save(self, value: dict) -> None:
        config = validate_drive_config(
            value, require_client=bool(value.get("enabled")) if isinstance(value, dict) else False,
        )
        encoded = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_CONFIG_BYTES:
            raise ValueError("Google Drive 수신 설정 파일이 너무 큽니다.")
        destination = self.config_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".hub_drive_config_",
                                             suffix=".tmp", delete=False) as temporary:
                temp_path = Path(temporary.name)
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temp_path, destination)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def disable(self) -> None:
        config = self.load()
        if config and config["enabled"]:
            config["enabled"] = False
            self.save(config)

    def authorize(self) -> None:
        config = self.load()
        if config is None:
            raise ValueError("Google Drive 수신 폴더를 먼저 설정해 주세요.")
        validate_drive_config(config, require_client=True)
        authorize_drive(Path(config["oauth_client_file"]), self.token_path)

    def scan(self, *, service=None) -> dict:
        config = self.load()
        if not config or not config["enabled"]:
            return {"state": "off", "listed": 0, "downloaded": 0}
        local = self.folder_sync.load()
        if not local or not local["enabled"]:
            raise ValueError("PC 로컬 수신 폴더를 먼저 켜 주세요.")
        validate_drive_config(config, require_client=True)
        live_service = service if service is not None else saved_drive_service(self.token_path)
        result = download_drive_folder(
            live_service, config["folder_id"], Path(local["folder"]), bot_id=local["bot_id"],
        )
        return {"state": "ok", **result}
