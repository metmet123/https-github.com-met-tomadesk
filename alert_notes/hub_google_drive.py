"""Bounded, read-only Drive downloader for the Telegram Hub inbox.

No network or OAuth flow runs on import. Live authentication is an explicit
user action; the regular poller only reuses a previously approved token.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_FOLDER_ID = re.compile(r"[A-Za-z0-9_-]{10,128}\Z")
_FILE_NAME = re.compile(r"telegram_([1-9][0-9]*)_(0|[1-9][0-9]*)\.json\Z")
_MD5 = re.compile(r"[0-9a-fA-F]{32}\Z")
_MAX_RECORD_BYTES = 128 * 1024
_MAX_PAGES = 100


class DriveAuthorizationRequired(ValueError):
    """No usable saved OAuth grant exists; never open a browser implicitly."""


def _validate_folder_id(folder_id: str) -> str:
    if not isinstance(folder_id, str) or not _FOLDER_ID.fullmatch(folder_id):
        raise ValueError("Google Drive 수신 폴더 ID가 올바르지 않습니다.")
    return folder_id


def _read_existing(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("기존 Telegram 수신 파일 형식이 올바르지 않습니다.")
    with path.open("rb") as source:
        content = source.read(_MAX_RECORD_BYTES + 1)
    if len(content) > _MAX_RECORD_BYTES:
        raise ValueError("기존 Telegram 수신 파일이 너무 큽니다.")
    return content


def download_drive_folder(service, folder_id: str, local_folder: Path, *, bot_id: int) -> dict:
    """Download matching immutable records; never delete/overwrite local files.

    ``service`` is a Drive v3 client (or a test double). Every completed file
    is committed independently, so retrying after a later error is safe.
    """
    folder_id = _validate_folder_id(folder_id)
    if type(bot_id) is not int or bot_id <= 0:
        raise ValueError("Telegram 봇 ID가 올바르지 않습니다.")
    local_folder = Path(local_folder)
    if local_folder.is_symlink() or not local_folder.is_dir():
        raise ValueError("PC 로컬 수신 폴더를 찾을 수 없습니다.")
    files_api = service.files()
    page_token = None
    seen_tokens = set()
    listed = 0
    downloaded = 0
    for _page in range(_MAX_PAGES):
        response = files_api.list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken,files(id,name,mimeType,size,md5Checksum)",
            pageSize=100,
            pageToken=page_token,
        ).execute()
        if not isinstance(response, dict) or not isinstance(response.get("files"), list):
            raise ValueError("Google Drive 파일 목록 형식이 올바르지 않습니다.")
        for metadata in response["files"]:
            if not isinstance(metadata, dict):
                raise ValueError("Google Drive 파일 정보 형식이 올바르지 않습니다.")
            name = metadata.get("name")
            match = _FILE_NAME.fullmatch(name) if isinstance(name, str) else None
            if not match or int(match.group(1)) != bot_id:
                continue
            listed += 1
            file_id = metadata.get("id")
            mime = metadata.get("mimeType")
            size = metadata.get("size")
            digest = metadata.get("md5Checksum")
            if (not isinstance(file_id, str) or not _FOLDER_ID.fullmatch(file_id)
                    or mime not in ("text/plain", "application/json")
                    or not isinstance(size, str) or not size.isascii() or not size.isdecimal()
                    or not 0 < int(size) <= _MAX_RECORD_BYTES
                    or not isinstance(digest, str) or not _MD5.fullmatch(digest)):
                raise ValueError("Google Drive 수신 파일의 크기·형식·검증값이 올바르지 않습니다.")
            destination = local_folder / name
            if destination.exists() or destination.is_symlink():
                existing = _read_existing(destination)
                if hashlib.md5(existing).hexdigest().lower() != digest.lower():
                    raise ValueError("같은 이름의 로컬 수신 파일과 Drive 파일이 충돌합니다.")
                continue
            content = files_api.get_media(fileId=file_id).execute()
            if not isinstance(content, bytes) or len(content) != int(size) or len(content) > _MAX_RECORD_BYTES:
                raise ValueError("Google Drive 수신 파일의 실제 크기가 다릅니다.")
            if hashlib.md5(content).hexdigest().lower() != digest.lower():
                raise ValueError("Google Drive 수신 파일 검증값이 일치하지 않습니다.")
            try:
                record = json.loads(content.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("Google Drive 수신 파일의 JSON 형식이 올바르지 않습니다.") from exc
            if (not isinstance(record, dict) or type(record.get("bot_id")) is not int
                    or type(record.get("update_id")) is not int
                    or record["bot_id"] != bot_id or record["update_id"] != int(match.group(2))):
                raise ValueError("Google Drive 수신 파일 이름과 내용이 일치하지 않습니다.")
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(dir=local_folder, prefix=".hub_drive_",
                                                 suffix=".tmp", delete=False) as temporary:
                    temp_path = Path(temporary.name)
                    temporary.write(content)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                # Link is create-if-absent and atomic. Replacing a user's
                # existing local record would conceal a conflict.
                try:
                    os.link(temp_path, destination)
                    downloaded += 1
                except FileExistsError:
                    if _read_existing(destination) != content:
                        raise ValueError("같은 이름의 로컬 수신 파일과 Drive 파일이 충돌합니다.")
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
        next_token = response.get("nextPageToken")
        if next_token is None:
            return {"listed": listed, "downloaded": downloaded}
        if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
            raise ValueError("Google Drive 페이지 정보가 올바르지 않습니다.")
        seen_tokens.add(next_token)
        page_token = next_token
    raise ValueError("Google Drive 수신 파일이 너무 많아 한 번에 확인할 수 없습니다.")


def saved_drive_service(token_path: Path):
    """Build a Drive client from an existing grant; never initiate login."""
    token_path = Path(token_path)
    if token_path.is_symlink() or not token_path.is_file():
        raise DriveAuthorizationRequired("Google Drive 연결 승인이 필요합니다.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise DriveAuthorizationRequired("Google Drive 라이브러리를 설치해야 합니다.") from exc
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), [DRIVE_SCOPE])
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _write_token(token_path, creds.to_json())
        if not creds.valid or not creds.has_scopes([DRIVE_SCOPE]):
            raise DriveAuthorizationRequired("Google Drive 연결 승인이 필요합니다.")
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except DriveAuthorizationRequired:
        raise
    except Exception as exc:
        raise DriveAuthorizationRequired("Google Drive 연결을 갱신할 수 없습니다.") from exc


def authorize_drive(client_file: Path, token_path: Path) -> None:
    """Interactive desktop OAuth; call only after an explicit user click."""
    client_file = Path(client_file)
    token_path = Path(token_path)
    if not client_file.is_file() or client_file.is_symlink():
        raise ValueError("Google OAuth 데스크톱 클라이언트 JSON을 찾을 수 없습니다.")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise DriveAuthorizationRequired("Google Drive 라이브러리를 설치해야 합니다.") from exc
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), [DRIVE_SCOPE])
    credentials = flow.run_local_server(port=0)
    if not credentials.valid or not credentials.has_scopes([DRIVE_SCOPE]):
        raise DriveAuthorizationRequired("Google Drive 읽기 승인이 완료되지 않았습니다.")
    _write_token(token_path, credentials.to_json())


def _write_token(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".hub_google_", suffix=".tmp", delete=False) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
