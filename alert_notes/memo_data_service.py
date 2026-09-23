from __future__ import annotations

from hashlib import sha256
import base64
import binascii
import json
import re
import difflib

from .sync_identity import new_sync_id, utc_now_ms
from .rich_text import display_plain_text_from_content


_NOTE_V1 = re.compile(r"toma-note://([1-9][0-9]*)", re.IGNORECASE)
_NOTE_V2 = re.compile(r"toma-note://v2/([0-9a-fA-F-]{36})", re.IGNORECASE)
_BLOCK_V1 = re.compile(r"toma-block://v1/([1-9][0-9]*)/([0-9a-fA-F-]{36})", re.IGNORECASE)
_BLOCK_V2 = re.compile(r"toma-block://v2/([0-9a-fA-F-]{36})/([0-9a-fA-F-]{36})", re.IGNORECASE)


class MemoDataService:
    """Transaction boundary for data that will later cross devices."""

    def __init__(self, store):
        self.store = store
        self.conn = store.conn

    # Categories stay exposed through the repository for older callers; new UI
    # can use this boundary without knowing table details.
    def categories(self):
        return self.store.categories()

    def set_note_category(self, note_id: int, category_id: int | None) -> None:
        self.store.set_note_category(note_id, category_id)

    # ---------------------------------------------------------- backlinks --
    def rebuild_backlinks(self) -> list[dict]:
        by_local = {int(row["id"]): str(row["sync_id"]) for row in self.conn.execute("SELECT id,sync_id FROM notes")}
        # Cache parsing only, not rows or query results: renames, trash/restore,
        # external writes and transaction rollbacks must be visible immediately.
        if by_local != getattr(self, "_backlink_local_ids", None):
            self._backlink_targets = {}
            self._backlink_local_ids = by_local
        cache = self._backlink_targets
        live_ids = set()
        found: list[dict] = []
        for source in self.conn.execute("SELECT id,sync_id,title,content FROM notes WHERE deleted_at='' "):
            source_id = int(source["id"])
            live_ids.add(source_id)
            content = str(source["content"] or "")
            seen: set[tuple[str, str]] = set()
            cached = cache.get(source_id)
            if cached is None or cached[0] != content:
                targets = [(by_local.get(int(match.group(1)), ""), "") for match in _NOTE_V1.finditer(content)]
                targets += [(match.group(1), "") for match in _NOTE_V2.finditer(content)]
                targets += [(by_local.get(int(match.group(1)), ""), match.group(2)) for match in _BLOCK_V1.finditer(content)]
                targets += [(match.group(1), match.group(2)) for match in _BLOCK_V2.finditer(content)]
                cache[source_id] = (content, targets)
            else:
                targets = cached[1]
            for memo_sync_id, block_id in targets:
                key = (memo_sync_id, block_id)
                if not memo_sync_id or key in seen:
                    continue
                seen.add(key)
                found.append({
                    "source_memo_id": int(source["id"]), "source_sync_id": str(source["sync_id"]),
                    "source_title": str(source["title"]), "target_sync_id": memo_sync_id,
                    "target_block_id": block_id,
                })
        self._backlink_targets = {key: value for key, value in cache.items() if key in live_ids}
        return found

    def backlinks_for(self, memo_sync_id: str) -> list[dict]:
        return [row for row in self.rebuild_backlinks() if row["target_sync_id"] == str(memo_sync_id)]

    # --------------------------------------------------------- annotations --
    def annotations(self, note_id: int):
        return list(self.conn.execute(
            "SELECT * FROM memo_annotations WHERE memo_id=? ORDER BY created_at_utc,id", (int(note_id),)
        ))

    def annotation(self, annotation_id: int):
        return self.conn.execute("SELECT * FROM memo_annotations WHERE id=?", (int(annotation_id),)).fetchone()

    def restore_annotation(self, snapshot: dict) -> int:
        values = dict(snapshot)
        sync_id = str(values["sync_id"])
        existing = self.conn.execute("SELECT id FROM memo_annotations WHERE sync_id=?", (sync_id,)).fetchone()
        columns = [
            "sync_id", "memo_id", "block_id", "start_offset", "end_offset", "quote",
            "context_before", "context_after", "comment", "location_status", "revision",
            "created_at_utc", "modified_at_utc", "origin_device_id",
        ]
        with self.conn:
            if existing is None:
                marks = ",".join("?" for _ in columns)
                cursor = self.conn.execute(
                    f"INSERT INTO memo_annotations({','.join(columns)}) VALUES({marks})",
                    [values[key] for key in columns],
                )
                result = int(cursor.lastrowid)
            else:
                assignments = ",".join(f"{key}=?" for key in columns[1:])
                self.conn.execute(
                    f"UPDATE memo_annotations SET {assignments} WHERE sync_id=?",
                    [*[values[key] for key in columns[1:]], sync_id],
                )
                result = int(existing["id"])
            self.conn.execute("DELETE FROM sync_tombstones WHERE entity_type='annotation' AND sync_id=?", (sync_id,))
        return result

    def add_annotation(
        self, note_id: int, comment: str, *, block_id: str = "", start_offset: int = 0,
        end_offset: int = 0, quote: str = "", context_before: str = "", context_after: str = "",
    ) -> int:
        text = str(comment or "").strip()
        if not text:
            raise ValueError("주석 내용을 입력하세요.")
        stamp = utc_now_ms()
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO memo_annotations(sync_id,memo_id,block_id,start_offset,end_offset,quote,"
                "context_before,context_after,comment,location_status,revision,created_at_utc,modified_at_utc,origin_device_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,'resolved',1,?,?,?)",
                (new_sync_id(), int(note_id), str(block_id), int(start_offset), int(end_offset),
                 str(quote), str(context_before), str(context_after), text, stamp, stamp, self.store.device_id),
            )
            self.store._touch_note(note_id)
        return int(cursor.lastrowid)

    def update_annotation(self, annotation_id: int, comment: str) -> None:
        text = str(comment or "").strip()
        if not text:
            raise ValueError("주석 내용을 입력하세요.")
        row = self.conn.execute("SELECT memo_id FROM memo_annotations WHERE id=?", (int(annotation_id),)).fetchone()
        if row is None:
            return
        with self.conn:
            self.conn.execute(
                "UPDATE memo_annotations SET comment=?,revision=revision+1,modified_at_utc=?,origin_device_id=? WHERE id=?",
                (text, utc_now_ms(), self.store.device_id, int(annotation_id)),
            )
            self.store._touch_note(int(row["memo_id"]))

    def delete_annotation(self, annotation_id: int) -> None:
        row = self.conn.execute("SELECT * FROM memo_annotations WHERE id=?", (int(annotation_id),)).fetchone()
        if row is None:
            return
        with self.conn:
            self.store._write_tombstone("annotation", row["sync_id"], int(row["revision"]) + 1)
            self.conn.execute("DELETE FROM memo_annotations WHERE id=?", (int(annotation_id),))
            self.store._touch_note(int(row["memo_id"]))

    def resolve_annotation(
        self, annotation_id: int, plain_text: str,
        block_ranges: dict[str, tuple[int, int]] | None = None,
    ) -> str:
        row = self.conn.execute("SELECT * FROM memo_annotations WHERE id=?", (int(annotation_id),)).fetchone()
        if row is None:
            return "missing"
        text = str(plain_text or "")
        quote = str(row["quote"] or "")
        before = str(row["context_before"] or "")
        after = str(row["context_after"] or "")
        block_range = (block_ranges or {}).get(str(row["block_id"] or ""))
        if quote:
            positions = [match.start() for match in re.finditer(re.escape(quote), text)]
            if block_range is not None:
                inside = [position for position in positions if block_range[0] <= position <= block_range[1]]
                if inside:
                    positions = inside
        else:
            # An annotation on an empty paragraph has a zero-width anchor.  Its
            # surrounding text can still recover the boundary after edits.
            positions = [block_range[0]] if block_range is not None else list(range(len(text) + 1))

        def context_score(position: int) -> tuple[int, int]:
            end = position + len(quote)
            before_score = 0
            for size in range(1, min(len(before), position) + 1):
                if text[position - size:position] == before[-size:]:
                    before_score = size
            after_score = 0
            for size in range(1, min(len(after), len(text) - end) + 1):
                if text[end:end + size] == after[:size]:
                    after_score = size
                else:
                    break
            return before_score + after_score, int(before_score == len(before)) + int(after_score == len(after))

        resolved_position: int | None = None
        if len(positions) == 1 and (quote or block_range is not None):
            resolved_position = positions[0]
        elif positions:
            ranked = sorted(((context_score(position), position) for position in positions), reverse=True)
            if ranked[0][0][0] > 0 and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
                resolved_position = ranked[0][1]
        status = "resolved" if resolved_position is not None else "needs_review"
        new_start = int(row["start_offset"]) if resolved_position is None else resolved_position
        new_end = int(row["end_offset"]) if resolved_position is None else resolved_position + len(quote)
        changed = (
            new_start != int(row["start_offset"]) or new_end != int(row["end_offset"])
            or status != str(row["location_status"])
        )
        if changed:
            with self.conn:
                self.conn.execute(
                    "UPDATE memo_annotations SET start_offset=?,end_offset=?,location_status=?,"
                    "revision=revision+1,modified_at_utc=?,origin_device_id=? WHERE id=?",
                    (new_start, new_end, status, utc_now_ms(), self.store.device_id, int(annotation_id)),
                )
                self.store._touch_note(int(row["memo_id"]))
        return status

    # ----------------------------------------------------------- templates --
    def templates(self):
        return list(self.conn.execute("SELECT * FROM memo_templates ORDER BY sort_order,name,id"))

    def available_templates(self):
        """Show shipped examples without inserting rows into a user's database."""
        from .builtin_templates import builtin_rows

        return [*builtin_rows(), *self.templates()]

    def save_template(self, name: str, trigger: str, payload: dict, payload_version: int = 1) -> int:
        clean_name = str(name or "").strip()
        clean_trigger = str(trigger or "").strip().lstrip("/")
        if not clean_name or not clean_trigger:
            raise ValueError("템플릿 이름과 호출어를 입력하세요.")
        self._validate_template_payload(payload)
        try:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("템플릿 저장 형식에 지원하지 않는 값이 있습니다.") from exc
        stamp = utc_now_ms()
        order = int(self.conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM memo_templates").fetchone()[0])
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO memo_templates(sync_id,name,trigger,sort_order,payload_version,payload_json,revision,"
                "created_at_utc,modified_at_utc,origin_device_id) VALUES(?,?,?,?,?,?,1,?,?,?)",
                (new_sync_id(), clean_name, clean_trigger, order, int(payload_version), encoded,
                 stamp, stamp, self.store.device_id),
            )
        return int(cursor.lastrowid)

    @staticmethod
    def _validate_template_payload(payload: dict) -> None:
        if not isinstance(payload, dict):
            raise ValueError("템플릿 저장 형식이 올바르지 않습니다.")
        allowed = {"version", "kind", "html", "text", "blocks", "pages", "attachments"}
        try:
            version = int(payload.get("version", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("템플릿 버전이 올바르지 않습니다.") from exc
        if set(payload) - allowed or payload.get("kind") != "blocks" or version != 1:
            raise ValueError("지원하지 않는 템플릿 항목이 포함되어 있습니다.")
        if not isinstance(payload.get("html", ""), str) or not isinstance(payload.get("text", ""), str):
            raise ValueError("템플릿 본문 형식이 올바르지 않습니다.")
        if not isinstance(payload.get("blocks", []), list) or not isinstance(payload.get("attachments", []), list):
            raise ValueError("템플릿 블록 또는 첨부 형식이 올바르지 않습니다.")
        for block in payload.get("blocks", []):
            if not isinstance(block, dict) or set(block) - {"indent", "heading", "user_state"}:
                raise ValueError("지원하지 않는 블록 정보가 포함되어 있습니다.")
        pages = payload.get("pages", {})
        if not isinstance(pages, dict) or set(pages) - {
            "version", "roots", "notes", "attachments", "annotations",
        }:
            raise ValueError("지원하지 않는 페이지 정보가 포함되어 있습니다.")
        if "roots" in pages and not isinstance(pages["roots"], list):
            raise ValueError("템플릿 페이지 목록이 올바르지 않습니다.")
        page_note_keys = {
            "id", "title", "content", "postit", "postit_visible", "postit_startup",
            "postit_display_mode", "always_on_top", "color", "opacity",
            "background_transparency", "input_locked", "d_day_at", "d_day_label",
            "d_day_alert", "d_day_done_at", "monthly_rule", "monthly_shown_for",
            "hotkey", "hotkey_action", "created_at", "updated_at", "deleted_at",
            "parent_id", "sort_order", "embedded", "pinned", "sync_id", "revision",
            "modified_at_utc", "origin_device_id", "category_id", "conflict_of_sync_id",
        }
        annotation_keys = {
            "id", "sync_id", "memo_id", "block_id", "start_offset", "end_offset",
            "quote", "context_before", "context_after", "comment", "location_status",
            "revision", "created_at_utc", "modified_at_utc", "origin_device_id",
        }
        for rows, keys, label in (
            (pages.get("notes", []), page_note_keys, "페이지"),
            (pages.get("annotations", []), annotation_keys, "주석"),
        ):
            if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) - keys for row in rows):
                raise ValueError(f"지원하지 않는 {label} 정보가 포함되어 있습니다.")

        def inspect(value, key: str = "") -> None:
            if key.casefold() in {"path", "file_path", "local_path", "archive_path"}:
                raise ValueError("템플릿에는 로컬 파일 경로를 저장할 수 없습니다.")
            if isinstance(value, dict):
                for child_key, child in value.items():
                    if not isinstance(child_key, str):
                        raise ValueError("템플릿 항목 이름이 올바르지 않습니다.")
                    inspect(child, child_key)
            elif isinstance(value, list):
                for child in value:
                    inspect(child, key)
            elif not isinstance(value, (str, int, float, bool, type(None))):
                raise ValueError("템플릿에는 Qt 객체나 지원하지 않는 값을 저장할 수 없습니다.")
            if isinstance(value, str) and key.casefold() in {"html", "content"}:
                for match in re.finditer(
                    r"\b(?:href|src)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
                    value, re.IGNORECASE | re.DOTALL,
                ):
                    target = next(part for part in match.groups() if part is not None).strip()
                    if re.match(r"(?:file:|[A-Za-z]:[\\/])", target, re.IGNORECASE):
                        raise ValueError("템플릿에는 로컬 파일 경로를 저장할 수 없습니다.")

        inspect(payload)
        attachment_groups = [payload.get("attachments", []), pages.get("attachments", [])]
        attachment_keys = {
            "id", "note_id", "mime_type", "data_base64", "width", "height", "created_at",
            "sync_id", "revision", "modified_at_utc", "origin_device_id",
        }
        for attachments in attachment_groups:
            if not isinstance(attachments, list):
                raise ValueError("템플릿 첨부 형식이 올바르지 않습니다.")
            for attachment in attachments:
                if (
                    not isinstance(attachment, dict) or set(attachment) - attachment_keys
                    or "data_base64" not in attachment
                ):
                    raise ValueError("템플릿 첨부 데이터가 올바르지 않습니다.")
                try:
                    base64.b64decode(str(attachment["data_base64"]), validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ValueError("템플릿 첨부 데이터가 올바르지 않습니다.") from exc

    def reorder_templates(self, ordered_ids) -> None:
        stamp = utc_now_ms()
        with self.conn:
            for order, template_id in enumerate(ordered_ids, 1):
                self.conn.execute(
                    "UPDATE memo_templates SET sort_order=?,revision=revision+1,modified_at_utc=?,origin_device_id=? WHERE id=?",
                    (order, stamp, self.store.device_id, int(template_id)),
                )

    def update_template(self, template_id: int, *, name: str, trigger: str) -> None:
        clean_name = str(name or "").strip()
        clean_trigger = str(trigger or "").strip().lstrip("/")
        if not clean_name or not clean_trigger:
            raise ValueError("템플릿 이름과 호출어를 입력하세요.")
        with self.conn:
            self.conn.execute(
                "UPDATE memo_templates SET name=?,trigger=?,revision=revision+1,modified_at_utc=?,origin_device_id=? WHERE id=?",
                (clean_name, clean_trigger, utc_now_ms(), self.store.device_id, int(template_id)),
            )

    def delete_template(self, template_id: int) -> None:
        row = self.conn.execute("SELECT * FROM memo_templates WHERE id=?", (int(template_id),)).fetchone()
        if row is None:
            return
        with self.conn:
            self.store._write_tombstone("template", row["sync_id"], int(row["revision"]) + 1)
            self.conn.execute("DELETE FROM memo_templates WHERE id=?", (int(template_id),))

    # ------------------------------------------------------------ versions --
    def _snapshot_payload(self, note_id: int) -> dict:
        note = self.conn.execute("SELECT * FROM notes WHERE id=?", (int(note_id),)).fetchone()
        if note is None:
            raise ValueError("메모를 찾을 수 없습니다.")
        return {
            "version": 1,
            "note": {key: note[key] for key in note.keys() if key not in {"id", "revision", "modified_at_utc", "origin_device_id"}},
            "attachments": [
                {
                    "source_local_id": int(row["id"]),
                    **{
                        key: row[key]
                        for key in row.keys()
                        if key not in {"id", "note_id", "revision", "modified_at_utc", "origin_device_id"}
                    },
                }
                for row in self.store.note_attachments(note_id)
            ],
        }

    def create_version(self, note_id: int, kind: str = "auto", important: bool = False, force: bool = False) -> int | None:
        payload = self._snapshot_payload(note_id)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = sha256(encoded.encode("utf-8")).hexdigest()
        latest = self.conn.execute(
            "SELECT payload_hash FROM memo_versions WHERE memo_id=? ORDER BY created_at_utc DESC,id DESC LIMIT 1",
            (int(note_id),),
        ).fetchone()
        if not force and latest is not None and str(latest["payload_hash"]) == digest:
            return None
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO memo_versions(sync_id,memo_id,payload_hash,payload_json,kind,important,created_at_utc,origin_device_id) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (new_sync_id(), int(note_id), digest, encoded, str(kind), int(bool(important)), utc_now_ms(), self.store.device_id),
            )
            automatic = self.conn.execute(
                "SELECT id FROM memo_versions WHERE memo_id=? AND kind IN ('auto','session_start') AND important=0 "
                "ORDER BY created_at_utc DESC,id DESC", (int(note_id),)
            ).fetchall()
            for row in automatic[30:]:
                self.conn.execute("DELETE FROM memo_versions WHERE id=?", (int(row["id"]),))
        return int(cursor.lastrowid)

    def snapshot_hash(self, note_id: int) -> str:
        encoded = json.dumps(
            self._snapshot_payload(note_id), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return sha256(encoded.encode("utf-8")).hexdigest()

    def versions(self, note_id: int):
        return list(self.conn.execute(
            "SELECT * FROM memo_versions WHERE memo_id=? ORDER BY created_at_utc DESC,id DESC", (int(note_id),)
        ))

    def version_payload(self, version_id: int) -> dict:
        row = self.conn.execute("SELECT payload_json FROM memo_versions WHERE id=?", (int(version_id),)).fetchone()
        if row is None:
            raise ValueError("버전을 찾을 수 없습니다.")
        return json.loads(str(row["payload_json"]))

    def version_diff(self, version_id: int) -> str:
        row = self.conn.execute("SELECT memo_id FROM memo_versions WHERE id=?", (int(version_id),)).fetchone()
        if row is None:
            raise ValueError("버전을 찾을 수 없습니다.")
        target = self.version_payload(version_id)["note"]
        current = self._snapshot_payload(int(row["memo_id"]))["note"]
        before = display_plain_text_from_content(str(target.get("content") or "")).splitlines()
        after = display_plain_text_from_content(str(current.get("content") or "")).splitlines()
        return "\n".join(difflib.unified_diff(before, after, fromfile="선택 버전", tofile="현재", lineterm=""))

    def restore_impacts(self, version_id: int) -> list[str]:
        row = self.conn.execute("SELECT memo_id FROM memo_versions WHERE id=?", (int(version_id),)).fetchone()
        if row is None:
            raise ValueError("버전을 찾을 수 없습니다.")
        current = self._snapshot_payload(int(row["memo_id"]))
        target = self.version_payload(version_id)
        impacts = []
        current_links = set(_NOTE_V1.findall(str(current["note"].get("content") or ""))) | set(_NOTE_V2.findall(str(current["note"].get("content") or "")))
        target_links = set(_NOTE_V1.findall(str(target["note"].get("content") or ""))) | set(_NOTE_V2.findall(str(target["note"].get("content") or "")))
        lost_links = current_links - target_links
        if lost_links:
            impacts.append(f"링크 {len(lost_links)}개가 현재 본문에서 사라집니다.")
        current_files = {str(item.get("sync_id") or "") for item in current.get("attachments", [])}
        target_files = {str(item.get("sync_id") or "") for item in target.get("attachments", [])}
        if current_files - target_files:
            impacts.append(f"첨부 {len(current_files - target_files)}개의 연결이 사라질 수 있습니다.")
        return impacts

    def set_version_important(self, version_id: int, important: bool) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE memo_versions SET important=? WHERE id=?", (int(bool(important)), int(version_id))
            )

    def restore_version(self, version_id: int) -> None:
        row = self.conn.execute("SELECT * FROM memo_versions WHERE id=?", (int(version_id),)).fetchone()
        if row is None:
            raise ValueError("버전을 찾을 수 없습니다.")
        note_id = int(row["memo_id"])
        payload = json.loads(str(row["payload_json"]))
        before = self._snapshot_payload(note_id)
        before_json = json.dumps(before, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        before_hash = sha256(before_json.encode("utf-8")).hexdigest()
        allowed = {
            "title", "content", "postit", "postit_visible", "postit_startup", "postit_display_mode",
            "always_on_top", "color", "opacity", "background_transparency", "input_locked",
            "d_day_at", "d_day_label", "d_day_alert", "d_day_done_at", "monthly_rule",
            "monthly_shown_for", "hotkey", "hotkey_action", "deleted_at", "parent_id", "sort_order",
            "embedded", "pinned", "category_id", "conflict_of_sync_id",
        }
        values = {key: value for key, value in dict(payload["note"]).items() if key in allowed}
        target_attachments = list(payload.get("attachments") or [])
        if not all(isinstance(item, dict) and str(item.get("sync_id") or "") for item in target_attachments):
            raise ValueError("버전의 첨부 관계가 올바르지 않습니다.")
        self.conn.commit()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "INSERT INTO memo_versions(sync_id,memo_id,payload_hash,payload_json,kind,important,created_at_utc,origin_device_id) "
                "VALUES(?,?,?,?, 'before_restore',1,?,?)",
                (new_sync_id(), note_id, before_hash, before_json, utc_now_ms(), self.store.device_id),
            )
            current_attachments = {
                str(item["sync_id"]): item for item in self.store.note_attachments(note_id)
            }
            target_sync_ids: set[str] = set()
            local_id_map: dict[int, int] = {}
            stamp = utc_now_ms()
            for item in target_attachments:
                sync_id = str(item["sync_id"])
                target_sync_ids.add(sync_id)
                existing = self.conn.execute(
                    "SELECT * FROM note_attachments WHERE sync_id=?", (sync_id,)
                ).fetchone()
                if existing is not None and int(existing["note_id"]) != note_id:
                    raise ValueError("같은 UUID의 첨부가 다른 메모에 연결되어 있습니다.")
                fields = (
                    str(item.get("mime_type") or "application/octet-stream"),
                    str(item.get("data_base64") or ""),
                    int(item.get("width") or 0),
                    int(item.get("height") or 0),
                    str(item.get("created_at") or self.store._now_key()),
                )
                if existing is None:
                    cursor = self.conn.execute(
                        "INSERT INTO note_attachments(note_id,mime_type,data_base64,width,height,created_at,"
                        "sync_id,revision,modified_at_utc,origin_device_id) VALUES(?,?,?,?,?,?,?,1,?,?)",
                        (note_id, *fields, sync_id, stamp, self.store.device_id),
                    )
                    restored_local_id = int(cursor.lastrowid)
                else:
                    restored_local_id = int(existing["id"])
                    self.conn.execute(
                        "UPDATE note_attachments SET mime_type=?,data_base64=?,width=?,height=?,created_at=?,"
                        "revision=revision+1,modified_at_utc=?,origin_device_id=? WHERE id=?",
                        (*fields, stamp, self.store.device_id, restored_local_id),
                    )
                source_local_id = int(item.get("source_local_id") or 0)
                if source_local_id > 0:
                    local_id_map[source_local_id] = restored_local_id
                self.conn.execute(
                    "DELETE FROM sync_tombstones WHERE entity_type='attachment' AND sync_id=?", (sync_id,)
                )
            for sync_id, attachment in current_attachments.items():
                if sync_id in target_sync_ids:
                    continue
                self.store._write_tombstone(
                    "attachment", sync_id, int(attachment["revision"]) + 1, stamp
                )
                self.conn.execute("DELETE FROM note_attachments WHERE id=?", (int(attachment["id"]),))
            content = str(values.get("content") or "")
            for old_id, restored_id in local_id_map.items():
                content = re.sub(
                    rf"toma-note-image://(?:attachment/)?{old_id}(?![0-9])",
                    f"toma-note-image://attachment/{restored_id}",
                    content,
                    flags=re.IGNORECASE,
                )
            if "content" in values:
                values["content"] = content
            self.store._touch_note(note_id, values)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
