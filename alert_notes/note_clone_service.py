from __future__ import annotations

import html as html_module
import re


PAGE_MARK = "📄 "


_ANCHOR_RE = re.compile(
    r"(<a\b[^>]*\bhref=(['\"])toma-note://(\d+)\2[^>]*>)(.*?)(</a>)",
    re.IGNORECASE | re.DOTALL,
)
_IMAGE_RE = re.compile(r"toma-note-image://(?:attachment/)?(\d+)", re.IGNORECASE)


def _anchor_text(value: str) -> str:
    return html_module.unescape(re.sub(r"<[^>]+>", "", value))


def rewrite_cloned_content(content: str, note_ids: dict[int, int], attachment_ids: dict[int, int]) -> str:
    """Rewrite cloned page and attachment ownership without retargeting memo links."""

    def replace_anchor(match):
        old_id = int(match.group(3))
        visible = _anchor_text(match.group(4)).lstrip()
        # Page lines are ownership links and follow a deep clone.  Ordinary
        # memo links are references, so they intentionally keep their target.
        if old_id not in note_ids or not visible.startswith(PAGE_MARK):
            return match.group(0)
        opening = re.sub(
            r"toma-note://\d+", f"toma-note://{note_ids[old_id]}", match.group(1),
            flags=re.IGNORECASE,
        )
        return opening + match.group(4) + match.group(5)

    rewritten = _ANCHOR_RE.sub(replace_anchor, str(content or ""))
    return _IMAGE_RE.sub(
        lambda match: (
            f"toma-note-image://attachment/{attachment_ids[int(match.group(1))]}"
            if int(match.group(1)) in attachment_ids else match.group(0)
        ),
        rewritten,
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
        notes, attachments = [], []
        for root_id in roots:
            for note_id in [root_id, *self.store.note_descendants(root_id)]:
                row = self.store.note(note_id)
                if row is None:
                    continue
                notes.append({key: row[key] for key in columns})
                attachments.extend(dict(item) for item in self.store.note_attachments(note_id))
        return {"version": 1, "roots": roots, "notes": notes, "attachments": attachments}

    def clone(self, snapshot: dict, root_parents: dict[int, int] | None = None,
              rename_roots: bool = False) -> dict:
        root_parents = {int(k): int(v) for k, v in (root_parents or {}).items()}
        source_notes = list(snapshot.get("notes") or [])
        if not source_notes:
            return {"version": 1, "roots": [], "notes": [], "attachments": [], "id_map": {}}
        roots = [int(value) for value in snapshot.get("roots") or []]
        available = set(self._note_columns())
        id_map: dict[int, int] = {}
        attachment_map: dict[int, int] = {}
        inserted_notes, inserted_attachments = [], []
        stamp = self.store._now_key()
        with self.store.conn:
            # Allocate the whole ID graph first, then rewrite cross-links.
            for source in source_notes:
                old_id = int(source["id"])
                cursor = self.store.conn.execute(
                    "INSERT INTO notes(title,content,created_at,updated_at) VALUES(?,?,?,?)",
                    (str(source.get("title") or self.store.default_title), "", stamp, stamp),
                )
                id_map[old_id] = int(cursor.lastrowid)
            for source_attachment in snapshot.get("attachments") or []:
                old_note = int(source_attachment["note_id"])
                if old_note not in id_map:
                    continue
                cursor = self.store.conn.execute(
                    "INSERT INTO note_attachments(note_id,mime_type,data_base64,width,height,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (id_map[old_note], source_attachment["mime_type"], source_attachment["data_base64"],
                     int(source_attachment["width"]), int(source_attachment["height"]), stamp),
                )
                attachment_map[int(source_attachment["id"])] = int(cursor.lastrowid)
            used_titles = {
                str(row[0]) for row in self.store.conn.execute(
                    "SELECT title FROM notes WHERE deleted_at=''"
                )
            }
            for source in source_notes:
                old_id = int(source["id"])
                values = {key: source[key] for key in source if key in available and key != "id"}
                values.update(self.RESET_VALUES)
                values["created_at"] = stamp
                values["updated_at"] = stamp
                values["sort_order"] = 0 if old_id in roots else int(source.get("sort_order") or 0)
                parent = int(source.get("parent_id") or 0)
                values["parent_id"] = root_parents.get(old_id, id_map.get(parent, parent))
                values["content"] = rewrite_cloned_content(
                    str(source.get("content") or ""), id_map, attachment_map,
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
            "id_map": id_map,
        }

    def remove_batch(self, batch: dict) -> None:
        ids = [int(row["id"]) for row in batch.get("notes") or []]
        attachment_ids = [int(row["id"]) for row in batch.get("attachments") or []]
        if not ids and not attachment_ids:
            return
        with self.store.conn:
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
                    "INSERT INTO note_attachments(note_id,mime_type,data_base64,width,height,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (int(destination_note_id), source["mime_type"], source["data_base64"],
                     int(source["width"]), int(source["height"]), stamp),
                )
                new_id = int(cursor.lastrowid)
                id_map[int(source["id"])] = new_id
                inserted.append(dict(self.store.attachment(new_id)))
        return inserted, id_map

    def restore_batch(self, batch: dict) -> None:
        notes = list(batch.get("notes") or [])
        attachments = list(batch.get("attachments") or [])
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
