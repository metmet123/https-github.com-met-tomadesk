"""Drive downloader tests use an in-memory API, never a Google account."""
import hashlib
import json

import pytest

from alert_notes.hub_google_drive import (
    DriveAuthorizationRequired, download_drive_folder, saved_drive_service,
)


def _record(number=1):
    return json.dumps({
        "schema_version": 1, "transport": "telegram", "bot_id": 101,
        "update_id": number, "received_at_utc": "2026-10-02T01:02:03Z",
        "message": {
            "date": 1790902800, "text": "내일 회신",
            "from": {"id": 202, "is_bot": False},
            "chat": {"id": 303, "type": "private"},
        },
    }, ensure_ascii=False).encode("utf-8")


class _Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeFiles:
    def __init__(self, blobs, *, page_size=100):
        self.blobs = blobs
        self.page_size = page_size
        self.downloads = []
        self.queries = []

    def list(self, **kwargs):
        self.queries.append(kwargs)
        offset = int(kwargs["pageToken"] or 0)
        keys = sorted(self.blobs)
        batch = keys[offset:offset + self.page_size]
        metadata = []
        for file_id in batch:
            name, content = self.blobs[file_id]
            metadata.append({
                "id": file_id, "name": name, "mimeType": "text/plain",
                "size": str(len(content)),
                "md5Checksum": hashlib.md5(content).hexdigest(),
            })
        next_token = str(offset + self.page_size) if offset + self.page_size < len(keys) else None
        return _Request({"files": metadata, "nextPageToken": next_token})

    def get_media(self, *, fileId):
        self.downloads.append(fileId)
        return _Request(self.blobs[fileId][1])


class FakeService:
    def __init__(self, files):
        self.api = files

    def files(self):
        return self.api


def test_paginated_download_and_retry_do_not_duplicate_or_overwrite(tmp_path):
    blobs = {
        "file_id_0001": ("telegram_101_0.json", _record(0)),
        "file_id_0002": ("telegram_101_1.json", _record(1)),
    }
    files = FakeFiles(blobs, page_size=1)
    result = download_drive_folder(FakeService(files), "folder_id_101", tmp_path, bot_id=101)
    assert result == {"listed": 2, "downloaded": 2}
    assert len(files.queries) == 2
    assert files.queries[0]["q"] == "'folder_id_101' in parents and trashed = false"
    assert (tmp_path / "telegram_101_0.json").read_bytes() == _record(0)
    assert download_drive_folder(FakeService(files), "folder_id_101", tmp_path, bot_id=101) == {
        "listed": 2, "downloaded": 0,
    }
    assert len(files.downloads) == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_conflicting_local_file_is_preserved(tmp_path):
    path = tmp_path / "telegram_101_1.json"
    path.write_bytes(b"original")
    files = FakeFiles({"file_id_0001": (path.name, _record())})
    with pytest.raises(ValueError, match="충돌"):
        download_drive_folder(FakeService(files), "folder_id_101", tmp_path, bot_id=101)
    assert path.read_bytes() == b"original"
    assert files.downloads == []


def test_remote_metadata_or_content_error_does_not_create_file(tmp_path):
    files = FakeFiles({"file_id_0001": ("telegram_101_1.json", _record())})
    original_list = files.list

    def bad_checksum(**kwargs):
        result = original_list(**kwargs)
        result.result["files"][0]["md5Checksum"] = "0" * 32
        return result

    files.list = bad_checksum
    with pytest.raises(ValueError, match="검증값"):
        download_drive_folder(FakeService(files), "folder_id_101", tmp_path, bot_id=101)
    assert not (tmp_path / "telegram_101_1.json").exists()


def test_later_remote_error_keeps_earlier_complete_file_for_retry(tmp_path):
    files = FakeFiles({
        "file_id_0001": ("telegram_101_1.json", _record(1)),
        "file_id_0002": ("telegram_101_2.json", _record(2)),
    }, page_size=1)
    original_list = files.list

    def corrupt_second(**kwargs):
        result = original_list(**kwargs)
        if kwargs["pageToken"] == "1":
            result.result["files"][0]["md5Checksum"] = "0" * 32
        return result

    files.list = corrupt_second
    with pytest.raises(ValueError, match="검증값"):
        download_drive_folder(FakeService(files), "folder_id_101", tmp_path, bot_id=101)
    assert (tmp_path / "telegram_101_1.json").read_bytes() == _record(1)
    assert not (tmp_path / "telegram_101_2.json").exists()
    files.list = original_list
    assert download_drive_folder(FakeService(files), "folder_id_101", tmp_path, bot_id=101) == {
        "listed": 2, "downloaded": 1,
    }


def test_other_bot_file_is_not_downloaded(tmp_path):
    files = FakeFiles({"file_id_0001": ("telegram_999_1.json", _record())})
    assert download_drive_folder(FakeService(files), "folder_id_101", tmp_path, bot_id=101) == {
        "listed": 0, "downloaded": 0,
    }
    assert files.downloads == []


def test_missing_token_never_opens_login(tmp_path):
    with pytest.raises(DriveAuthorizationRequired):
        saved_drive_service(tmp_path / "missing-token.json")
