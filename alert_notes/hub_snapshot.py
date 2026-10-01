"""Default-private, read-only Snapshot v1 for optional external channels.

Only schedules explicitly enabled in the local visibility table are projected.
This module never uploads data and never exports notes, details, or attachments.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _utc_stamp(value: str | None) -> str:
    if value is None:
        return _utc_now()
    if not isinstance(value, str):
        raise ValueError("Snapshot 생성 시각은 UTC 문자열이어야 합니다.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Snapshot 생성 시각이 잘못되었습니다.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Snapshot 생성 시각은 UTC여야 합니다.")
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class HubSnapshotStore:
    def __init__(self, store):
        self.store = store

    def set_schedule_visible(self, schedule_id: int, visible: bool) -> str:
        """Record an explicit local choice; return a stable opaque public item ID."""
        return self.set_visible_many({schedule_id: visible})[schedule_id]

    def list_schedule_choices(self) -> list[dict]:
        """Local-only chooser rows. Nothing in this view is exported by itself."""
        rows = self.store.conn.execute(
            "SELECT s.id,s.title,s.item_type,s.start_at,s.all_day,s.status,"
            "COALESCE(v.enabled,0) AS visible "
            "FROM schedule_items AS s LEFT JOIN hub_visible_schedule AS v ON v.schedule_id=s.id "
            "WHERE s.deleted_at='' ORDER BY s.start_at,s.id"
        ).fetchall()
        return [
            {"id": row["id"], "title": row["title"], "kind": row["item_type"],
             "start_at": row["start_at"], "all_day": bool(row["all_day"]),
             "status": row["status"],
             "visible": bool(row["visible"])}
            for row in rows
        ]

    def set_visible_many(self, changes: dict[int, bool]) -> dict[int, str]:
        """Commit all explicit visibility choices together or none of them."""
        if not isinstance(changes, dict) or any(
            type(schedule_id) is not int or schedule_id < 1 or type(visible) is not bool
            for schedule_id, visible in changes.items()
        ):
            raise ValueError("일정 공개 설정이 잘못되었습니다.")
        if not changes:
            return {}
        conn = self.store.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = {}
            for schedule_id, visible in changes.items():
                item = conn.execute(
                    "SELECT id FROM schedule_items WHERE id=? AND deleted_at=''", (schedule_id,),
                ).fetchone()
                if item is None:
                    raise ValueError("존재하지 않거나 삭제된 일정입니다.")
                existing = conn.execute(
                    "SELECT external_id FROM hub_visible_schedule WHERE schedule_id=?", (schedule_id,),
                ).fetchone()
                external_id = str(existing["external_id"]) if existing else uuid4().hex
                if existing:
                    conn.execute(
                        "UPDATE hub_visible_schedule SET enabled=? WHERE schedule_id=?",
                        (int(visible), schedule_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO hub_visible_schedule(schedule_id,external_id,enabled,created_at_utc) "
                        "VALUES(?,?,?,?)",
                        (schedule_id, external_id, int(visible), _utc_now()),
                    )
                result[schedule_id] = external_id
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return result

    def build(self, *, generated_at_utc: str | None = None) -> dict:
        """Build a minimal snapshot without changing the database."""
        stamp = _utc_stamp(generated_at_utc)
        rows = self.store.conn.execute(
            "SELECT v.external_id,s.title,s.item_type,s.start_at,s.end_at,s.all_day,"
            "s.status,s.count_as_dday,s.updated_at "
            "FROM hub_visible_schedule AS v JOIN schedule_items AS s ON s.id=v.schedule_id "
            "WHERE v.enabled=1 AND s.deleted_at='' ORDER BY s.start_at,v.external_id"
        ).fetchall()
        items = []
        for row in rows:
            item = {
                "id": row["external_id"],
                "title": row["title"],
                "kind": row["item_type"],
                "start_at": row["start_at"],
                "end_at": row["end_at"],
                "all_day": bool(row["all_day"]),
                "status": row["status"],
                "count_as_dday": bool(row["count_as_dday"]),
            }
            # Keep the revision tied to the complete visible projection, not the
            # one-minute calendar timestamp resolution alone.
            revision_input = json.dumps(
                [item, row["updated_at"]], sort_keys=True, ensure_ascii=False,
                separators=(",", ":"),
            )
            item["revision"] = hashlib.sha256(revision_input.encode("utf-8")).hexdigest()[:24]
            items.append(item)
        revision_input = json.dumps(items, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        source_revision = hashlib.sha256(revision_input.encode("utf-8")).hexdigest()
        return {
            "schema_version": 1,
            "generated_at_utc": stamp,
            "server_id": self.store.device_id,
            "source_revision": source_revision,
            "visibility": "explicit_allowlist_v1",
            "items": items,
        }

    def publish_local(self, destination: Path, *, generated_at_utc: str | None = None) -> dict:
        """Atomically replace a local export; on failure keep the previous version."""
        if self.store.conn.in_transaction:
            raise ValueError("저장 중인 변경이 있습니다. 저장을 마친 뒤 Snapshot을 게시해 주세요.")
        target = Path(destination)
        if not target.parent.is_dir():
            raise ValueError("Snapshot 저장 폴더가 없습니다.")
        snapshot = self.build(generated_at_utc=generated_at_utc)
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        staged = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent,
                prefix=".tomadesk-snapshot-", suffix=".tmp", delete=False,
            ) as stream:
                staged = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staged, target)
        except Exception:
            if staged is not None:
                try:
                    staged.unlink(missing_ok=True)
                except OSError:
                    pass  # Preserve the original publication error.
            raise
        return snapshot
