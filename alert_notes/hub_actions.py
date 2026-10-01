"""Local Action/Receipt v1 core. No network receiver or cloud credentials live here.

An authenticated channel adapter may pass validated envelopes to this store. The
external event, Organizer capture, and receipt are committed in one SQLite
transaction, so retrying after a crash cannot create a second capture.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from .memo_organizer_store import OrganizerStore


_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_SOURCE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_SEOUL = timezone(timedelta(hours=9))
_REQUIRED = {
    "schema_version", "action_id", "source", "source_event_id",
    "source_sent_at_utc", "received_at_utc", "base_timezone", "kind", "payload",
}


class ActionConflictError(ValueError):
    """An existing action or source event ID has been reused with new content."""


def _utc_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field}은 UTC 시각 문자열이어야 합니다.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 형식이 잘못되었습니다.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field}은 UTC 시각이어야 합니다.")
    return parsed


def _validate_action(value: object) -> tuple[dict, datetime]:
    if not isinstance(value, dict) or set(value) != _REQUIRED:
        raise ValueError("Action v1 필드를 확인해 주세요.")
    action = dict(value)
    if type(action["schema_version"]) is not int or action["schema_version"] != 1:
        raise ValueError("지원하지 않는 Action 버전입니다.")
    if not isinstance(action["action_id"], str) or not _ID.fullmatch(action["action_id"]):
        raise ValueError("Action ID가 잘못되었습니다.")
    if not isinstance(action["source"], str) or not _SOURCE.fullmatch(action["source"]):
        raise ValueError("Action 출처가 잘못되었습니다.")
    if not isinstance(action["source_event_id"], str) or not _ID.fullmatch(action["source_event_id"]):
        raise ValueError("출처 이벤트 ID가 잘못되었습니다.")
    sent = _utc_datetime(action["source_sent_at_utc"], "source_sent_at_utc")
    received = _utc_datetime(action["received_at_utc"], "received_at_utc")
    action["source_sent_at_utc"] = sent.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    action["received_at_utc"] = received.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if action["base_timezone"] != "Asia/Seoul":
        raise ValueError("Action v1은 Asia/Seoul 기준일만 지원합니다.")
    if action["kind"] != "capture_text":
        raise ValueError("지원하지 않는 Action 종류입니다.")
    payload = action["payload"]
    if not isinstance(payload, dict) or set(payload) != {"text"} or not isinstance(payload["text"], str):
        raise ValueError("수집할 원문이 잘못되었습니다.")
    if not payload["text"].strip() or len(payload["text"]) > 20_000:
        raise ValueError("수집할 원문은 1~20,000자로 입력해 주세요.")
    return action, sent


def _event_hash(action: dict) -> str:
    # Adapter retries may choose a new action ID or receive time. Neither changes
    # the identity/content of the original source event.
    stable = {key: value for key, value in action.items()
              if key not in {"action_id", "received_at_utc"}}
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class HubActionStore:
    """Transactional, local-only ingress for capture_text and its receipt."""

    def __init__(self, store):
        self.store = store
        self.organizer = OrganizerStore(store)

    @staticmethod
    def _receipt(row) -> dict:
        return {
            "schema_version": 1,
            "action_id": row["action_id"], "state": row["state"],
            "processed_at_utc": row["processed_at_utc"],
            "result_ref": row["result_ref"], "error_code": row["error_code"],
            "capture_id": row["capture_id"], "applied_count": row["applied_count"],
            "result": {
                "capture_id": row["capture_id"],
                "applied_count": row["applied_count"],
            },
        }

    def receipt(self, action_id: str) -> dict:
        row = self.store.conn.execute(
            "SELECT * FROM hub_actions WHERE action_id=?", (action_id,),
        ).fetchone()
        if row is None:
            raise KeyError(action_id)
        return self._receipt(row)

    def receive(self, value: object) -> dict:
        """Accept one trusted adapter's Action; never publish this as an open HTTP API."""
        action, sent = _validate_action(value)
        digest = _event_hash(action)
        conn = self.store.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            matches = conn.execute(
                "SELECT * FROM hub_actions WHERE action_id=? OR (source=? AND source_event_id=?)",
                (action["action_id"], action["source"], action["source_event_id"]),
            ).fetchall()
            if matches:
                if len(matches) != 1 or any(
                    row["source"] != action["source"]
                    or row["source_event_id"] != action["source_event_id"]
                    or row["envelope_hash"] != digest for row in matches
                ):
                    raise ActionConflictError("같은 Action 또는 출처 이벤트 ID의 내용이 바뀌었습니다.")
                result = self._receipt(matches[0])
            else:
                capture_id = self.organizer.capture_external(
                    action["payload"]["text"], sent.astimezone(_SEOUL).date(),
                    action_id=action["action_id"], source=action["source"],
                    source_event_id=action["source_event_id"],
                )
                conn.execute(
                    "INSERT INTO hub_actions(action_id,source,source_event_id,envelope_hash,"
                    "action_json,state,capture_id,created_at_utc) VALUES(?,?,?,?,?,?,?,?)",
                    (action["action_id"], action["source"], action["source_event_id"],
                     digest, json.dumps(action, ensure_ascii=False, sort_keys=True),
                     "awaiting_review", capture_id, _now_utc()),
                )
                result = self.receipt(action["action_id"])
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise

    def apply_review(self, action_id: str, edited: list[dict], *, allow_duplicates=False) -> dict:
        """Apply reviewed candidates and final receipt in one DB transaction."""
        if not edited:
            raise ValueError("적용할 항목이 없습니다. 거부하려면 reject를 사용해 주세요.")
        conn = self.store.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM hub_actions WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            if row["state"] == "applied":
                result = self._receipt(row)
            elif row["state"] != "awaiting_review":
                raise ActionConflictError("이미 종료된 요청입니다.")
            else:
                try:
                    capture = self.organizer.get_capture(row["capture_id"])
                except StopIteration as exc:
                    raise ActionConflictError("영수증의 수집함 원문을 찾을 수 없습니다.") from exc
                if capture.get("external") != {
                    "action_id": row["action_id"], "source": row["source"],
                    "source_event_id": row["source_event_id"],
                }:
                    raise ActionConflictError("영수증과 수집함의 연결이 일치하지 않습니다.")
                by_id = {item["id"]: item for item in capture["items"]}
                if any(
                    value.get("kind", by_id.get(value.get("id"), {}).get("kind")) == "review"
                    for value in edited
                ):
                    raise ValueError("확인 필요 항목은 종류를 정한 뒤 반영해 주세요.")
                count = self.organizer.apply(
                    row["capture_id"], edited, allow_duplicates=allow_duplicates,
                    manage_transaction=False,
                )
                if count == 0:
                    raise ValueError("새로 적용한 항목이 없습니다. 최신 수집함을 다시 확인해 주세요.")
                conn.execute(
                    "UPDATE hub_actions SET state='applied',result_ref=?,processed_at_utc=?,applied_count=? "
                    "WHERE action_id=?",
                    ("capture:" + row["capture_id"], _now_utc(), count, action_id),
                )
                result = self.receipt(action_id)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise

    def reject(self, action_id: str) -> dict:
        conn = self.store.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM hub_actions WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            if row["state"] == "applied":
                raise ActionConflictError("이미 적용된 요청은 거부할 수 없습니다.")
            if row["state"] == "awaiting_review":
                conn.execute(
                    "UPDATE hub_actions SET state='rejected',error_code='user_rejected',"
                    "processed_at_utc=? WHERE action_id=?", (_now_utc(), action_id),
                )
            result = self.receipt(action_id)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
