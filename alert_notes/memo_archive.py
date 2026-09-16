from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

from .sqlite_store import (
    ATTACHMENT_COLUMNS, CATEGORY_COLUMNS, HISTORY_COLUMNS, NOTE_COLUMNS, REMINDER_COLUMNS, SERIES_COLUMNS,
)
from .sync_identity import new_sync_id, utc_now_ms
from .link_rewrite import rewrite_internal_links


ARCHIVE_FORMAT = "tomadesk-memo-archive"
ARCHIVE_VERSION = 2
LEGACY_ARCHIVE_VERSION = 1
CORE_MEMO_TABLES = ("notes", "note_attachments", "reminder_series", "reminders", "reminder_history")
MEMO_TABLES = CORE_MEMO_TABLES + (
    "memo_categories", "sync_tombstones", "memo_annotations", "memo_templates", "memo_versions",
)
ANNOTATION_COLUMNS = (
    "id", "sync_id", "memo_id", "block_id", "start_offset", "end_offset", "quote",
    "context_before", "context_after", "comment", "location_status", "revision",
    "created_at_utc", "modified_at_utc", "origin_device_id",
)
TEMPLATE_COLUMNS = (
    "id", "sync_id", "name", "trigger", "sort_order", "payload_version", "payload_json",
    "revision", "created_at_utc", "modified_at_utc", "origin_device_id",
)
VERSION_COLUMNS = (
    "id", "sync_id", "memo_id", "payload_hash", "payload_json", "kind", "important",
    "created_at_utc", "origin_device_id",
)
MAX_ARCHIVE_ENTRIES = 100_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class MemoArchivePreview:
    exported_at: str
    active_notes: int
    trashed_notes: int
    attachments: int
    reminders: int
    path: Path


@dataclass(frozen=True)
class MemoRestoreResult:
    notes: int
    attachments: int
    reminders: int
    cleared_hotkeys: int


def export_memo_archive(store, path: Path) -> Path:
    target = Path(path)
    if target.suffix.casefold() != ".tomamemo":
        target = target.with_suffix(".tomamemo")
    target.parent.mkdir(parents=True, exist_ok=True)
    tables = {
        table: [dict(row) for row in store.conn.execute(f"SELECT * FROM {table}")]
        for table in MEMO_TABLES
    }
    note_sync = {int(row["id"]): str(row.get("sync_id") or "") for row in tables["notes"]}
    category_sync = {int(row["id"]): str(row.get("sync_id") or "") for row in tables["memo_categories"]}
    for row in tables["notes"]:
        row["parent_sync_id"] = note_sync.get(int(row.get("parent_id") or 0), "")
        row["category_sync_id"] = category_sync.get(int(row["category_id"])) if row.get("category_id") is not None else ""
    for row in tables["note_attachments"]:
        row["note_sync_id"] = note_sync.get(int(row["note_id"]), "")
    attachments = []
    binary_entries: list[tuple[str, bytes]] = []
    for row in tables["note_attachments"]:
        try:
            payload = base64.b64decode(str(row.pop("data_base64")), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"첨부파일 {row.get('id')} 데이터를 읽을 수 없습니다.") from exc
        archive_path = f"attachments/{int(row['id'])}.bin"
        row.update(
            archive_path=archive_path,
            sha256=sha256(payload).hexdigest(),
            size=len(payload),
        )
        attachments.append(row)
        binary_entries.append((archive_path, payload))
    tables["note_attachments"] = attachments
    active = sum(not str(row.get("deleted_at") or "") for row in tables["notes"])
    manifest = {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "counts": {
            "active_notes": active,
            "trashed_notes": len(tables["notes"]) - active,
            "attachments": len(attachments),
            "reminders": len(tables["reminders"]),
        },
        "tables": tables,
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, payload in binary_entries:
            archive.writestr(name, payload)
    return target


def inspect_memo_archive(path: Path) -> MemoArchivePreview:
    manifest, _attachments = _read_archive(Path(path))
    counts = manifest["counts"]
    return MemoArchivePreview(
        str(manifest["exported_at"]), int(counts["active_notes"]),
        int(counts["trashed_notes"]), int(counts["attachments"]),
        int(counts["reminders"]), Path(path),
    )


def restore_memo_archive(store, path: Path, mode: str, hotkey_validator=None) -> MemoRestoreResult:
    if mode not in {"merge", "replace"}:
        raise ValueError("복원 방식이 올바르지 않습니다.")
    manifest, attachment_payloads = _read_archive(Path(path))
    tables = manifest["tables"]
    conn = store.conn
    cleared_hotkeys = 0
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if mode == "replace":
            conn.execute("DELETE FROM schedule_items WHERE source_reminder_id IS NOT NULL")
            conn.execute("UPDATE schedule_items SET note_id=NULL WHERE note_id IS NOT NULL")
            conn.execute(
                "DELETE FROM settings WHERE key LIKE 'memo_draft_%' OR key='memo_recent_notes'"
            )
            replacement_tables = [
                "reminder_history", "reminders", "reminder_series", "memo_annotations",
                "memo_versions", "note_attachments", "notes",
            ]
            if int(manifest.get("version", 1)) >= 2:
                replacement_tables.extend(("memo_templates", "memo_categories", "sync_tombstones"))
            for table in replacement_tables:
                conn.execute(f"DELETE FROM {table}")

        note_map: dict[int, int] = {}
        note_sync_map: dict[str, str] = {}
        attachment_map: dict[int, int] = {}
        series_map: dict[int, int] = {}
        category_map: dict[int, int] = {}
        category_by_sync = {str(row["sync_id"]): int(row["id"]) for row in store.categories()}
        category_by_name = {str(row["name"]).casefold(): int(row["id"]) for row in store.categories()}
        for source in tables.get("memo_categories", []):
            old_id = int(source["id"])
            sync_id = str(source.get("sync_id") or "")
            name = str(source.get("name") or "").strip()
            existing = category_by_sync.get(sync_id) or category_by_name.get(name.casefold())
            if existing is not None:
                category_map[old_id] = existing
                continue
            values = dict(source)
            if mode == "merge":
                values.pop("id", None)
            if not sync_id:
                values["sync_id"] = new_sync_id()
            values.setdefault("revision", 1)
            values.setdefault("created_at_utc", utc_now_ms())
            values.setdefault("modified_at_utc", values["created_at_utc"])
            values.setdefault("origin_device_id", store.device_id)
            category_map[old_id] = _insert_row(conn, "memo_categories", CATEGORY_COLUMNS, values)
        used_titles = {
            str(row[0]).strip().casefold()
            for row in conn.execute("SELECT title FROM notes")
        }
        for source in tables["notes"]:
            old_id = int(source["id"])
            values = dict(source)
            values["parent_id"] = 0
            old_category = source.get("category_id")
            values["category_id"] = category_map.get(int(old_category)) if old_category not in (None, "") else None
            values["content"] = str(values.get("content") or "")
            if not str(values.get("sync_id") or ""):
                values.update(
                    sync_id=new_sync_id(), revision=1, modified_at_utc=utc_now_ms(),
                    origin_device_id=store.device_id,
                )
            if mode == "merge":
                values.pop("id", None)
                values["title"] = _unique_title(used_titles, str(values.get("title") or "새 메모"))
                original_sync_id = str(values.get("sync_id") or "")
                if original_sync_id and conn.execute(
                    "SELECT 1 FROM notes WHERE sync_id=?", (original_sync_id,)
                ).fetchone():
                    values["conflict_of_sync_id"] = original_sync_id
                    values["sync_id"] = new_sync_id()
                    values["revision"] = 1
                    values["modified_at_utc"] = utc_now_ms()
                    values["origin_device_id"] = store.device_id
            hotkey = str(values.get("hotkey") or "").strip()
            if hotkey and hotkey_validator is not None:
                try:
                    hotkey_validator(hotkey, note_id=None)
                except Exception:
                    values["hotkey"] = ""
                    cleared_hotkeys += 1
            new_id = _insert_row(conn, "notes", NOTE_COLUMNS, values)
            note_map[old_id] = new_id
            old_sync_id = str(source.get("sync_id") or "")
            if old_sync_id:
                note_sync_map[old_sync_id] = str(values.get("sync_id") or old_sync_id)
            used_titles.add(str(values.get("title") or "").strip().casefold())

        for source in tables["note_attachments"]:
            old_id = int(source["id"])
            values = dict(source)
            values["note_id"] = note_map[int(source["note_id"])]
            values["data_base64"] = base64.b64encode(attachment_payloads[old_id]).decode("ascii")
            if not str(values.get("sync_id") or ""):
                values.update(
                    sync_id=new_sync_id(), revision=1, modified_at_utc=utc_now_ms(),
                    origin_device_id=store.device_id,
                )
            for key in ("archive_path", "sha256", "size"):
                values.pop(key, None)
            if mode == "merge":
                values.pop("id", None)
                if values.get("sync_id") and conn.execute(
                    "SELECT 1 FROM note_attachments WHERE sync_id=?", (str(values["sync_id"]),)
                ).fetchone():
                    values["sync_id"] = new_sync_id()
                    values["revision"] = 1
                    values["modified_at_utc"] = utc_now_ms()
                    values["origin_device_id"] = store.device_id
            attachment_map[old_id] = _insert_row(conn, "note_attachments", ATTACHMENT_COLUMNS, values)

        for source in tables["notes"]:
            old_id = int(source["id"])
            new_id = note_map[old_id]
            parent = int(source.get("parent_id") or 0)
            content = _rewrite_content(
                str(source.get("content") or ""), note_map, attachment_map, note_sync_map,
            )
            conn.execute(
                "UPDATE notes SET parent_id=?,content=? WHERE id=?",
                (note_map.get(parent, 0), content, new_id),
            )

        for source in tables.get("sync_tombstones", []):
            values = dict(source)
            selected = ["entity_type", "sync_id", "revision", "deleted_at_utc", "origin_device_id"]
            columns = ",".join(selected)
            conn.execute(
                f"INSERT INTO sync_tombstones({columns}) VALUES(?,?,?,?,?) "
                "ON CONFLICT(entity_type,sync_id) DO UPDATE SET revision=MAX(revision,excluded.revision),"
                "deleted_at_utc=excluded.deleted_at_utc,origin_device_id=excluded.origin_device_id",
                [values.get(key, "") for key in selected],
            )

        for table, columns in (("memo_annotations", ANNOTATION_COLUMNS), ("memo_versions", VERSION_COLUMNS)):
            for source in tables.get(table, []):
                values = dict(source)
                values["memo_id"] = note_map[int(source["memo_id"])]
                if mode == "merge":
                    values.pop("id", None)
                    if values.get("sync_id") and conn.execute(
                        f"SELECT 1 FROM {table} WHERE sync_id=?", (str(values["sync_id"]),)
                    ).fetchone():
                        values["sync_id"] = new_sync_id()
                _insert_row(conn, table, columns, values)

        for source in tables.get("memo_templates", []):
            values = dict(source)
            if mode == "merge":
                values.pop("id", None)
                if conn.execute(
                    "SELECT 1 FROM memo_templates WHERE sync_id=? OR name=? COLLATE NOCASE OR trigger=? COLLATE NOCASE",
                    (str(values.get("sync_id") or ""), str(values.get("name") or ""), str(values.get("trigger") or "")),
                ).fetchone():
                    base = str(values.get("name") or "템플릿")
                    values["name"] = _unique_title(
                        {str(row[0]).casefold() for row in conn.execute("SELECT name FROM memo_templates")}, base,
                    )
                    values["trigger"] = f"{str(values.get('trigger') or 'template')}-{new_sync_id()[:8]}"
                    values["sync_id"] = new_sync_id()
            _insert_row(conn, "memo_templates", TEMPLATE_COLUMNS, values)

        for source in tables["reminder_series"]:
            old_id = int(source["id"])
            values = dict(source)
            note_id = source.get("note_id")
            values["note_id"] = note_map.get(int(note_id)) if note_id not in (None, "") else None
            if mode == "merge":
                values.pop("id", None)
            series_map[old_id] = _insert_row(conn, "reminder_series", SERIES_COLUMNS, values)

        for source in tables["reminders"]:
            values = dict(source)
            values["note_id"] = note_map[int(source["note_id"])]
            series_id = source.get("series_id")
            values["series_id"] = series_map.get(int(series_id)) if series_id not in (None, "") else None
            if mode == "merge":
                values.pop("id", None)
            _insert_row(conn, "reminders", REMINDER_COLUMNS, values)

        for source in tables["reminder_history"]:
            values = dict(source)
            note_id = source.get("note_id")
            series_id = source.get("series_id")
            values["note_id"] = note_map.get(int(note_id)) if note_id not in (None, "") else None
            values["series_id"] = series_map.get(int(series_id)) if series_id not in (None, "") else None
            if mode == "merge":
                values.pop("id", None)
            _insert_row(conn, "reminder_history", HISTORY_COLUMNS, values)
        # 알림의 일정 투영도 같은 트랜잭션 안에서 다시 만든다.  이 표는 아카이브에
        # 넣지 않으므로 중복 없이 현재 알림 ID에 맞춰 생성된다.
        store.schedules.migrate_legacy_reminders()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    for name in ("_rich_document_registry", "_rich_document_views"):
        if hasattr(store, name):
            setattr(store, name, {})
    return MemoRestoreResult(
        len(tables["notes"]), len(tables["note_attachments"]),
        len(tables["reminders"]), cleared_hotkeys,
    )


def _read_archive(path: Path) -> tuple[dict, dict[int, bytes]]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise ValueError("백업 파일의 항목 수가 비정상적으로 많습니다.")
            if sum(max(0, info.file_size) for info in infos) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError("백업 파일을 풀었을 때 크기가 허용 범위를 초과합니다.")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise ValueError("백업 파일의 항목 구성이 올바르지 않습니다.")
            for name in names:
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts or "\\" in name:
                    raise ValueError("백업 파일에 안전하지 않은 경로가 있습니다.")
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise ValueError("백업 목록 정보가 비정상적으로 큽니다.")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            _validate_manifest(manifest)
            expected_names = {"manifest.json"} | {
                str(row["archive_path"])
                for row in manifest["tables"]["note_attachments"]
            }
            if set(names) != expected_names:
                raise ValueError("백업 파일에 알 수 없는 항목이 있습니다.")
            payloads: dict[int, bytes] = {}
            for row in manifest["tables"]["note_attachments"]:
                archive_path = str(row["archive_path"])
                if archive_path not in names or not archive_path.startswith("attachments/"):
                    raise ValueError("첨부파일 항목이 누락되었습니다.")
                payload = archive.read(archive_path)
                if len(payload) != int(row["size"]) or sha256(payload).hexdigest() != row["sha256"]:
                    raise ValueError("첨부파일 무결성 검증에 실패했습니다.")
                payloads[int(row["id"])] = payload
            return manifest, payloads
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("올바른 TomaDesk 메모 백업 파일이 아닙니다.") from exc


def _validate_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_FORMAT:
        raise ValueError("TomaDesk 메모 백업 형식이 아닙니다.")
    if manifest.get("version") not in {LEGACY_ARCHIVE_VERSION, ARCHIVE_VERSION}:
        raise ValueError("지원하지 않는 메모 백업 버전입니다.")
    if not isinstance(manifest.get("exported_at"), str):
        raise ValueError("백업 생성 시각이 없습니다.")
    tables = manifest.get("tables")
    counts = manifest.get("counts")
    if not isinstance(tables, dict) or any(not isinstance(tables.get(table), list) for table in CORE_MEMO_TABLES):
        raise ValueError("백업 데이터 표가 누락되었습니다.")
    for table in MEMO_TABLES:
        tables.setdefault(table, [])
    if not isinstance(counts, dict) or any(
        key not in counts for key in ("active_notes", "trashed_notes", "attachments", "reminders")
    ):
        raise ValueError("백업 개수 정보가 누락되었습니다.")
    note_ids = _unique_ids(tables["notes"], "메모")
    attachment_ids = _unique_ids(tables["note_attachments"], "첨부파일")
    series_ids = _unique_ids(tables["reminder_series"], "반복 알림")
    _unique_ids(tables["reminders"], "알림")
    _unique_ids(tables["reminder_history"], "알림 이력")
    parent_by_id = {}
    for row in tables["notes"]:
        parent = int(row.get("parent_id") or 0)
        if parent and parent not in note_ids:
            raise ValueError("메모 부모 관계가 손상되었습니다.")
        parent_by_id[int(row["id"])] = parent
    for start in note_ids:
        seen: set[int] = set()
        current = start
        while current:
            if current in seen:
                raise ValueError("메모 부모 관계에 순환 참조가 있습니다.")
            seen.add(current)
            current = parent_by_id[current]
    for row in tables["note_attachments"]:
        if int(row.get("note_id") or 0) not in note_ids or int(row["id"]) not in attachment_ids:
            raise ValueError("첨부파일의 메모 관계가 손상되었습니다.")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256") or "")):
            raise ValueError("첨부파일 해시가 올바르지 않습니다.")
    for row in tables["reminder_series"]:
        note_id = row.get("note_id")
        if note_id not in (None, "") and int(note_id) not in note_ids:
            raise ValueError("반복 알림의 메모 관계가 손상되었습니다.")
    for table in ("reminders", "reminder_history"):
        for row in tables[table]:
            note_id, series_id = row.get("note_id"), row.get("series_id")
            if table == "reminders" and int(note_id or 0) not in note_ids:
                raise ValueError("알림의 메모 관계가 손상되었습니다.")
            if note_id not in (None, "") and int(note_id) not in note_ids:
                raise ValueError("알림 이력의 메모 관계가 손상되었습니다.")
            if series_id not in (None, "") and int(series_id) not in series_ids:
                raise ValueError("알림의 반복 관계가 손상되었습니다.")
    expected_counts = {
        "active_notes": sum(not str(row.get("deleted_at") or "") for row in tables["notes"]),
        "trashed_notes": sum(bool(str(row.get("deleted_at") or "")) for row in tables["notes"]),
        "attachments": len(tables["note_attachments"]),
        "reminders": len(tables["reminders"]),
    }
    try:
        counts_match = all(int(counts[key]) == value for key, value in expected_counts.items())
    except (TypeError, ValueError) as exc:
        raise ValueError("백업 개수 정보가 올바르지 않습니다.") from exc
    if not counts_match:
        raise ValueError("백업 개수 정보와 실제 데이터가 일치하지 않습니다.")


def _unique_ids(rows: list[dict], label: str) -> set[int]:
    try:
        values = [int(row["id"]) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} ID가 올바르지 않습니다.") from exc
    if len(values) != len(set(values)) or any(value <= 0 for value in values):
        raise ValueError(f"{label} ID가 중복되었거나 올바르지 않습니다.")
    return set(values)


def _insert_row(conn, table: str, columns, values: dict) -> int:
    available = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    selected = [column for column in columns if column in available and column in values]
    if not selected:
        raise ValueError(f"복원할 {table} 데이터가 없습니다.")
    placeholders = ",".join("?" for _ in selected)
    cursor = conn.execute(
        f"INSERT INTO {table}({','.join(selected)}) VALUES({placeholders})",
        [values[column] for column in selected],
    )
    return int(values.get("id") or cursor.lastrowid)


def _unique_title(used: set[str], wanted: str) -> str:
    base = wanted.strip() or "새 메모"
    if base.casefold() not in used:
        return base
    index = 2
    while f"{base} ({index})".casefold() in used:
        index += 1
    return f"{base} ({index})"


def _rewrite_content(
    content: str, note_map: dict[int, int], attachment_map: dict[int, int],
    note_sync_map: dict[str, str] | None = None,
) -> str:
    return rewrite_internal_links(
        content, note_ids=note_map, note_sync_ids=note_sync_map,
        attachment_ids=attachment_map,
    )
