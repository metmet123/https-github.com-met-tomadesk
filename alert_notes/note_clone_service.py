from __future__ import annotations

from .block_identity import renew_content_ids, stored_ids
from .link_rewrite import rewrite_internal_links
from .sync_identity import new_sync_id, utc_now_ms


def rewrite_cloned_content(
    content: str, note_ids: dict[int, int], attachment_ids: dict[int, int],
    note_sync_ids: dict[str, str] | None = None,
    block_ids_by_local: dict[int, dict[str, str]] | None = None,
    block_ids_by_sync: dict[str, dict[str, str]] | None = None,
) -> str:
    """Regenerate block IDs and remap links inside the supplied clone graph."""

    renewed = renew_content_ids(str(content or ""))
    own_map = dict(zip(stored_ids(str(content or "")), stored_ids(renewed)))
    local_blocks = dict(block_ids_by_local or {})
    # Direct callers clone one content value and may link to their own blocks.
    # The graph clone supplies complete maps and overwrites this fallback.
    if len(note_ids) == 1:
        local_blocks.setdefault(next(iter(note_ids)), own_map)
    return rewrite_internal_links(
        renewed, note_ids=note_ids, note_sync_ids=note_sync_ids,
        attachment_ids=attachment_ids, block_ids_by_local=local_blocks,
        block_ids_by_sync=block_ids_by_sync,
    )


class NoteCloneService:
    """Deep-copy notes and their attachments as a reversible database batch."""

    RESET_VALUES = {
        "postit_visible": 0,
        "postit_startup": 0,
        "d_day_at": "",
        "d_day_label": "",
        "d_day_alert": 0,
        "d_day_done_at": "",
        "monthly_rule": "",
        "monthly_shown_for": "",
        "hotkey": "",
        "hotkey_action": "open",
        "pinned": 0,
        "deleted_at": "",
    }

    def __init__(self, store):
        self.store = store

    def _note_columns(self) -> list[str]:
        return [str(row[1]) for row in self.store.conn.execute("PRAGMA table_info(notes)")]

    def snapshot(self, root_ids) -> dict:
        requested = [int(value) for value in root_ids]
        requested_set = set(requested)
        roots = []
        for note_id in requested:
            ancestors = {int(row["id"]) for row in self.store.note_path(note_id)[:-1]}
            if not ancestors.intersection(requested_set) and note_id not in roots:
                roots.append(note_id)
        columns = self._note_columns()
        notes, attachments, annotations = [], [], []
        for root_id in roots:
            for note_id in [root_id, *self.store.note_descendants(root_id)]:
                row = self.store.note(note_id)
                if row is None:
                    continue
                notes.append({key: row[key] for key in columns})
                attachments.extend(dict(item) for item in self.store.note_attachments(note_id))
                annotations.extend(dict(item) for item in self.store.memo_data.annotations(note_id))
        return {"version": 1, "roots": roots, "notes": notes, "attachments": attachments,
                "annotations": annotations}

    def clone(self, snapshot: dict, root_parents: dict[int, int] | None = None,
              rename_roots: bool = False) -> dict:
        root_parents = {int(k): int(v) for k, v in (root_parents or {}).items()}
        source_notes = list(snapshot.get("notes") or [])
        if not source_notes:
            return {"version": 1, "roots": [], "notes": [], "attachments": [], "id_map": {}}
        roots = [int(value) for value in snapshot.get("roots") or []]
        available = set(self._note_columns())
        id_map: dict[int, int] = {}
        sync_map: dict[str, str] = {}
        attachment_map: dict[int, int] = {}
        inserted_notes, inserted_attachments, inserted_annotations = [], [], []
        stamp = self.store._now_key()
        sync_stamp = utc_now_ms()
        block_maps: dict[int, dict[str, str]] = {}
        with self.store.conn:
            # Allocate the whole ID graph first, then rewrite cross-links.
            for source in source_notes:
                old_id = int(source["id"])
                cursor = self.store.conn.execute(
                    "INSERT INTO notes(title,content,created_at,updated_at,sync_id,revision,modified_at_utc,origin_device_id) "
                    "VALUES(?,?,?,?,?,1,?,?)",
                    (str(source.get("title") or self.store.default_title), "", stamp, stamp,
                     new_sync_id(), sync_stamp, self.store.device_id),
                )
                id_map[old_id] = int(cursor.lastrowid)
                old_sync = str(source.get("sync_id") or "")
                if old_sync:
                    sync_map[old_sync] = str(self.store.conn.execute(
                        "SELECT sync_id FROM notes WHERE id=?", (id_map[old_id],)
                    ).fetchone()[0])
            for source_attachment in snapshot.get("attachments") or []:
                old_note = int(source_attachment["note_id"])
                if old_note not in id_map:
                    continue
                cursor = self.store.conn.execute(
                    "INSERT INTO note_attachments(note_id,mime_type,data_base64,width,height,created_at,sync_id,revision,modified_at_utc,origin_device_id) "
                    "VALUES(?,?,?,?,?,?,?,1,?,?)",
                    (id_map[old_note], source_attachment["mime_type"], source_attachment["data_base64"],
                     int(source_attachment["width"]), int(source_attachment["height"]), stamp,
                     new_sync_id(), sync_stamp, self.store.device_id),
                )
                attachment_map[int(source_attachment["id"])] = int(cursor.lastrowid)
            used_titles = {
                str(row[0]) for row in self.store.conn.execute(
                    "SELECT title FROM notes WHERE deleted_at=''"
                )
            }
            renewed_content: dict[int, str] = {}
            for source in source_notes:
                old_id = int(source["id"])
                original = str(source.get("content") or "")
                renewed_content[old_id] = renew_content_ids(original)
                block_maps[old_id] = dict(zip(stored_ids(original), stored_ids(renewed_content[old_id])))
            sync_block_maps = {
                str(source.get("sync_id") or ""): block_maps[int(source["id"])]
                for source in source_notes if str(source.get("sync_id") or "")
            }
            for source in source_notes:
                old_id = int(source["id"])
                values = {key: source[key] for key in source if key in available and key not in {
                    "id", "sync_id", "revision", "modified_at_utc", "origin_device_id", "conflict_of_sync_id",
                }}
                values.update(self.RESET_VALUES)
                values["created_at"] = stamp
                values["updated_at"] = stamp
                values["sort_order"] = 0 if old_id in roots else int(source.get("sort_order") or 0)
                parent = int(source.get("parent_id") or 0)
                values["parent_id"] = root_parents.get(old_id, id_map.get(parent, parent))
                values["content"] = rewrite_internal_links(
                    renewed_content[old_id], note_ids=id_map, note_sync_ids=sync_map,
                    attachment_ids=attachment_map, block_ids_by_local=block_maps,
                    block_ids_by_sync=sync_block_maps,
                )
                if rename_roots and old_id in roots:
                    base = f"{str(source.get('title') or self.store.default_title)} - 복사본"
                    title, suffix = base, 2
                    while title in used_titles:
                        title = f"{base} ({suffix})"
                        suffix += 1
                    values["title"] = title
                    used_titles.add(title)
                fields = list(values)
                self.store.conn.execute(
                    f"UPDATE notes SET {','.join(f'{key}=?' for key in fields)} WHERE id=?",
                    [*(values[key] for key in fields), id_map[old_id]],
                )
            for source in snapshot.get("annotations") or []:
                old_note = int(source["memo_id"])
                if old_note not in id_map:
                    continue
                cursor = self.store.conn.execute(
                    "INSERT INTO memo_annotations(sync_id,memo_id,block_id,start_offset,end_offset,quote,"
                    "context_before,context_after,comment,location_status,revision,created_at_utc,modified_at_utc,origin_device_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,'resolved',1,?,?,?)",
                    (new_sync_id(), id_map[old_note], block_maps.get(old_note, {}).get(str(source.get("block_id") or ""), ""),
                     int(source.get("start_offset") or 0), int(source.get("end_offset") or 0),
                     str(source.get("quote") or ""), str(source.get("context_before") or ""),
                     str(source.get("context_after") or ""), str(source.get("comment") or ""),
                     sync_stamp, sync_stamp, self.store.device_id),
                )
                inserted_annotations.append(dict(self.store.memo_data.annotation(int(cursor.lastrowid))))
            # List clones sit directly after each source root. Embedded page
            # clones use an explicit destination parent and keep child order.
            by_parent: dict[int, list[int]] = {}
            for old_id in roots:
                source = next(item for item in source_notes if int(item["id"]) == old_id)
                parent = root_parents.get(old_id, int(source.get("parent_id") or 0))
                by_parent.setdefault(parent, []).append(old_id)
            for parent, old_roots in by_parent.items():
                new_roots = {id_map[value] for value in old_roots}
                siblings = [
                    int(row["id"]) for row in self.store.child_notes(parent)
                    if int(row["id"]) not in new_roots
                ]
                offset = 0
                for old_id in old_roots:
                    new_id = id_map[old_id]
                    try:
                        index = siblings.index(old_id) + 1 + offset
                    except ValueError:
                        index = len(siblings)
                    siblings.insert(index, new_id)
                    offset += 1
                self.store._write_sort_order(siblings)
            for row in self.store.conn.execute(
                f"SELECT * FROM notes WHERE id IN ({','.join('?' for _ in id_map)}) ORDER BY id",
                tuple(id_map.values()),
            ):
                inserted_notes.append(dict(row))
            if attachment_map:
                for row in self.store.conn.execute(
                    f"SELECT * FROM note_attachments WHERE id IN ({','.join('?' for _ in attachment_map)}) ORDER BY id",
                    tuple(attachment_map.values()),
                ):
                    inserted_attachments.append(dict(row))
        return {
            "version": 1,
            "roots": [id_map[value] for value in roots if value in id_map],
            "notes": inserted_notes,
            "attachments": inserted_attachments,
            "annotations": inserted_annotations,
            "id_map": id_map,
        }

    def remove_batch(self, batch: dict) -> None:
        ids = [int(row["id"]) for row in batch.get("notes") or []]
        attachment_ids = [int(row["id"]) for row in batch.get("attachments") or []]
        annotation_ids = [int(row["id"]) for row in batch.get("annotations") or []]
        if not ids and not attachment_ids and not annotation_ids:
            return
        with self.store.conn:
            if annotation_ids:
                self.store.conn.execute(
                    f"DELETE FROM memo_annotations WHERE id IN ({','.join('?' for _ in annotation_ids)})",
                    annotation_ids,
                )
            if attachment_ids:
                self.store.conn.execute(
                    f"DELETE FROM note_attachments WHERE id IN ({','.join('?' for _ in attachment_ids)})",
                    attachment_ids,
                )
            if ids:
                self.store.conn.execute(
                    f"DELETE FROM notes WHERE id IN ({','.join('?' for _ in ids)})", ids,
                )

    def clone_attachments(self, attachments, destination_note_id: int) -> tuple[list[dict], dict[int, int]]:
        inserted, id_map = [], {}
        stamp = self.store._now_key()
        with self.store.conn:
            for source in attachments or []:
                cursor = self.store.conn.execute(
                    "INSERT INTO note_attachments(note_id,mime_type,data_base64,width,height,created_at,sync_id,revision,modified_at_utc,origin_device_id) "
                    "VALUES(?,?,?,?,?,?,?,1,?,?)",
                    (int(destination_note_id), source["mime_type"], source["data_base64"],
                     int(source["width"]), int(source["height"]), stamp,
                     new_sync_id(), utc_now_ms(), self.store.device_id),
                )
                new_id = int(cursor.lastrowid)
                id_map[int(source["id"])] = new_id
                inserted.append(dict(self.store.attachment(new_id)))
        return inserted, id_map

    def restore_batch(self, batch: dict) -> None:
        notes = list(batch.get("notes") or [])
        attachments = list(batch.get("attachments") or [])
        annotations = list(batch.get("annotations") or [])
        if not notes:
            return
        with self.store.conn:
            for row in notes:
                fields = list(row)
                self.store.conn.execute(
                    f"INSERT INTO notes({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",
                    [row[key] for key in fields],
                )
            for row in attachments:
                fields = list(row)
                self.store.conn.execute(
                    f"INSERT INTO note_attachments({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",
                    [row[key] for key in fields],
                )
            for row in annotations:
                fields = list(row)
                self.store.conn.execute(
                    f"INSERT INTO memo_annotations({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",
                    [row[key] for key in fields],
                )
