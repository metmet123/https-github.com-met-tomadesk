"""Explicitly opted-in publication of a minimal snapshot to a synced folder."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .hub_snapshot import HubSnapshotStore


CONFIG_NAME = "hub_snapshot_folder.json"
SNAPSHOT_NAME = "tomadesk_snapshot_v1.json"
_MAX_CONFIG_BYTES = 4096
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
_REFRESH_AFTER = timedelta(minutes=5)


def validate_snapshot_config(value: object, *, require_folder: bool = False) -> dict:
    if (not isinstance(value, dict) or set(value) != {"version", "enabled", "folder"}
            or type(value["version"]) is not int or value["version"] != 1
            or type(value["enabled"]) is not bool):
        raise ValueError("Snapshot 게시 설정이 올바르지 않습니다.")
    folder = value["folder"]
    if not isinstance(folder, str) or len(folder) > 1000:
        raise ValueError("Snapshot 게시 폴더 경로가 올바르지 않습니다.")
    if not folder.strip() and not value["enabled"]:
        return dict(value)
    if not folder.strip():
        raise ValueError("Snapshot 게시 폴더 경로가 올바르지 않습니다.")
    path = Path(folder)
    if not path.is_absolute() or path == Path(path.anchor) or path.is_symlink():
        raise ValueError("Snapshot 게시에는 실제 하위 폴더를 선택해 주세요.")
    if require_folder and not path.is_dir():
        raise ValueError("Snapshot 게시 폴더를 찾을 수 없습니다.")
    return dict(value)


class HubSnapshotSync:
    def __init__(self, store):
        self.store = store
        self.config_path = Path(store.path).parent / CONFIG_NAME
        self.snapshot = HubSnapshotStore(store)

    def load(self) -> dict | None:
        path = self.config_path
        if path.is_symlink():
            raise ValueError("Snapshot 게시 설정 파일을 읽을 수 없습니다.")
        if not path.exists():
            return None
        if not path.is_file() or path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ValueError("Snapshot 게시 설정 파일을 읽을 수 없습니다.")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Snapshot 게시 설정 파일을 읽을 수 없습니다.") from exc
        return validate_snapshot_config(value)

    def save(self, value: dict) -> None:
        config = validate_snapshot_config(
            value, require_folder=bool(value.get("enabled")) if isinstance(value, dict) else False,
        )
        encoded = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_CONFIG_BYTES:
            raise ValueError("Snapshot 게시 설정이 너무 큽니다.")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        staged = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.config_path.parent, prefix=".hub_snapshot_",
                                             suffix=".tmp", delete=False) as stream:
                staged = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staged, self.config_path)
            staged = None
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    def publish_if_due(self, *, now: datetime | None = None) -> dict:
        config = self.load()
        if not config or not config["enabled"]:
            return {"state": "off", "published": False, "item_count": 0}
        validate_snapshot_config(config, require_folder=True)
        if self.store.conn.in_transaction:
            raise ValueError("저장 중인 변경이 있습니다. Snapshot 게시를 기다립니다.")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() != timedelta(0):
            raise ValueError("Snapshot 게시 시각은 UTC여야 합니다.")
        folder = Path(config["folder"])
        target = folder / SNAPSHOT_NAME
        if target.is_symlink():
            raise ValueError("Snapshot 게시 대상이 올바르지 않습니다.")
        snapshot = self.snapshot.build(generated_at_utc=current.isoformat())
        if len(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")) > _MAX_SNAPSHOT_BYTES:
            raise ValueError("조회 Snapshot이 게시 한도를 넘었습니다.")
        if target.exists():
            if not target.is_file() or target.stat().st_size > _MAX_SNAPSHOT_BYTES:
                raise ValueError("기존 Snapshot 파일을 확인할 수 없습니다.")
            try:
                previous = json.loads(target.read_text(encoding="utf-8"))
                previous_time = datetime.fromisoformat(
                    previous["generated_at_utc"].replace("Z", "+00:00"),
                )
            except (UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError("기존 Snapshot 파일을 확인할 수 없습니다.") from exc
            if (not isinstance(previous, dict) or set(previous) != {
                    "schema_version", "generated_at_utc", "server_id",
                    "source_revision", "visibility", "items"}
                    or previous.get("schema_version") != 1
                    or previous.get("visibility") != "explicit_allowlist_v1"
                    or previous.get("server_id") != snapshot["server_id"]
                    or previous_time.tzinfo is None or previous_time.utcoffset() != timedelta(0)):
                raise ValueError("기존 Snapshot 파일과 PC의 식별자가 일치하지 않습니다.")
            item_fields = {"id", "title", "kind", "start_at", "end_at", "all_day",
                           "status", "count_as_dday", "revision"}
            if (not isinstance(previous.get("items"), list)
                    or any(not isinstance(item, dict) or set(item) != item_fields
                           for item in previous["items"])):
                raise ValueError("기존 Snapshot 파일을 확인할 수 없습니다.")
            prior_items = json.dumps(previous["items"], sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"))
            if hashlib.sha256(prior_items.encode("utf-8")).hexdigest() != previous.get("source_revision"):
                raise ValueError("기존 Snapshot 파일의 검증값이 일치하지 않습니다.")
            if (previous.get("source_revision") == snapshot["source_revision"]
                    and timedelta(0) <= current - previous_time < _REFRESH_AFTER):
                return {"state": "ok", "published": False,
                        "item_count": len(snapshot["items"]),
                        "generated_at_utc": previous["generated_at_utc"]}
        self.snapshot.publish_local(target, generated_at_utc=current.isoformat())
        return {"state": "ok", "published": True, "item_count": len(snapshot["items"]),
                "generated_at_utc": snapshot["generated_at_utc"]}
