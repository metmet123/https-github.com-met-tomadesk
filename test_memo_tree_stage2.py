"""메모 층 나누기 2단계 — 메모 표의 부모·순서 칸 테스트.

화면은 그대로 두고 저장소만 바꾸는 단계라, 여기서는 창을 하나도 띄우지 않는다.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from alert_notes.sqlite_store import TOP_LEVEL_PARENT, NoteReminderStore


LEGACY_NOTES = """
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'New note', content TEXT NOT NULL DEFAULT '',
    postit INTEGER NOT NULL DEFAULT 0,
    always_on_top INTEGER NOT NULL DEFAULT 1,
    color TEXT NOT NULL DEFAULT 'vanilla', opacity INTEGER NOT NULL DEFAULT 100,
    input_locked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


class NoteTreeColumnsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = NoteReminderStore(self.root / "notes.db", "새 메모")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _columns(self):
        return {str(row[1]) for row in self.store.conn.execute("PRAGMA table_info(notes)")}

    def test_a_new_database_has_the_two_columns(self):
        self.assertIn("parent_id", self._columns())
        self.assertIn("sort_order", self._columns())

    def test_a_new_note_starts_at_the_top_level(self):
        note_id = self.store.create_note("취미", "")
        row = self.store.note(note_id)
        self.assertEqual(int(row["parent_id"]), TOP_LEVEL_PARENT)
        self.assertEqual(int(row["sort_order"]), 0)

    def test_the_list_is_still_flat(self):
        parent = self.store.create_note("취미", "")
        child = self.store.create_note("드라마", "")
        self.store.set_note_parent(child, parent)
        ids = {int(row["id"]) for row in self.store.notes()}
        self.assertEqual(ids, {parent, child}, "목록이 지금과 달라지면 안 됩니다")


class LegacyUpgradeTest(unittest.TestCase):
    """칸이 없던 기존 메모 파일을 열었을 때."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "notes.db"
        conn = sqlite3.connect(self.path)
        conn.executescript(LEGACY_NOTES)
        conn.executemany(
            "INSERT INTO notes(title,content,created_at,updated_at) VALUES(?,?,?,?)",
            [("옛 메모 1", "본문", "202601010900", "202601010900"),
             ("옛 메모 2", "본문", "202601010901", "202601010901")],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_opening_it_adds_the_columns_and_keeps_every_note_on_top(self):
        store = NoteReminderStore(self.path, "새 메모")
        try:
            rows = store.notes()
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                [int(row["parent_id"]) for row in rows], [TOP_LEVEL_PARENT] * 2,
                "기존 메모가 어딘가의 하위로 들어갔습니다",
            )
            self.assertEqual({str(row["title"]) for row in rows}, {"옛 메모 1", "옛 메모 2"})
        finally:
            store.close()

    def test_it_makes_a_backup_before_changing_anything(self):
        store = NoteReminderStore(self.path, "새 메모")
        try:
            backup = store.upgrade_backup_path
            self.assertIsNotNone(backup, "칸을 늘리기 전에 백업을 뜨지 않았습니다")
            self.assertTrue(Path(backup).exists())
            saved = sqlite3.connect(backup)
            try:
                columns = {str(row[1]) for row in saved.execute("PRAGMA table_info(notes)")}
                self.assertNotIn("parent_id", columns, "백업이 바꾼 뒤의 모습입니다")
                self.assertEqual(
                    saved.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 2,
                )
            finally:
                saved.close()
        finally:
            store.close()


class NoteTreeMovesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.hobby = self.store.create_note("취미", "")
        self.drama = self.store.create_note("드라마", "")
        self.game = self.store.create_note("게임", "")
        self.diary = self.store.create_note("일기", "")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _titles(self, parent_id=TOP_LEVEL_PARENT):
        return [str(row["title"]) for row in self.store.child_notes(parent_id)]

    def test_moving_a_note_inside_another_one(self):
        self.assertTrue(self.store.set_note_parent(self.drama, self.hobby))
        self.assertEqual(self._titles(self.hobby), ["드라마"])
        self.assertNotIn("드라마", self._titles())

    def test_a_note_cannot_go_inside_itself(self):
        self.assertFalse(self.store.set_note_parent(self.hobby, self.hobby))
        self.assertEqual(int(self.store.note(self.hobby)["parent_id"]), TOP_LEVEL_PARENT)

    def test_a_note_cannot_go_inside_its_own_child(self):
        self.store.set_note_parent(self.drama, self.hobby)
        self.assertFalse(
            self.store.set_note_parent(self.hobby, self.drama),
            "취미를 그 안의 드라마 밑으로 넣으면 목록이 무한히 돕니다",
        )
        self.assertEqual(int(self.store.note(self.hobby)["parent_id"]), TOP_LEVEL_PARENT)

    def test_dragging_fixes_the_order(self):
        self.store.set_note_parent(self.drama, self.hobby)
        self.store.set_note_parent(self.game, self.hobby)
        self.store.reorder_notes(self.hobby, [self.game, self.drama])
        self.assertEqual(self._titles(self.hobby), ["게임", "드라마"])
        # 끌어 옮긴 뒤에는 수정 시간이 바뀌어도 그 자리를 지킨다.
        self.store.update_note(self.drama, title="드라마")
        self.assertEqual(self._titles(self.hobby), ["게임", "드라마"])

    def test_untouched_notes_still_follow_the_edit_time(self):
        self.store.set_note_parent(self.drama, self.hobby)
        self.store.set_note_parent(self.game, self.hobby)
        # 끌어 옮긴 적이 없는 상태로 되돌리고, 손댄 시각만 갈라 놓는다.
        self.store.conn.execute("UPDATE notes SET sort_order=0 WHERE parent_id=?", (self.hobby,))
        self.store.conn.execute(
            "UPDATE notes SET updated_at='202609040910' WHERE id=?", (self.drama,))
        self.store.conn.execute(
            "UPDATE notes SET updated_at='202609040900' WHERE id=?", (self.game,))
        self.store.conn.commit()
        self.assertEqual(self._titles(self.hobby), ["드라마", "게임"])

    def test_descendants_go_down_every_level(self):
        self.store.set_note_parent(self.drama, self.hobby)
        self.store.set_note_parent(self.game, self.drama)
        self.assertEqual(
            sorted(self.store.note_descendants(self.hobby)), sorted([self.drama, self.game]),
        )


class NoteTreeTrashTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NoteReminderStore(Path(self.temp.name) / "notes.db", "새 메모")
        self.hobby = self.store.create_note("취미", "")
        self.drama = self.store.create_note("드라마", "")
        self.episode = self.store.create_note("1화", "")
        self.store.set_note_parent(self.drama, self.hobby)
        self.store.set_note_parent(self.episode, self.drama)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _live(self):
        return {str(row["title"]) for row in self.store.notes()}

    def test_deleting_a_parent_takes_its_children_along(self):
        self.store.delete_note(self.hobby)
        self.assertEqual(self._live(), set())
        self.assertEqual(
            {str(row["title"]) for row in self.store.trashed_notes()},
            {"취미", "드라마", "1화"},
        )

    def test_restoring_a_parent_brings_the_whole_bundle_back(self):
        self.store.delete_note(self.hobby)
        self.store.restore_note(self.hobby)
        self.assertEqual(self._live(), {"취미", "드라마", "1화"})
        self.assertEqual(int(self.store.note(self.drama)["parent_id"]), self.hobby)
        self.assertEqual(int(self.store.note(self.episode)["parent_id"]), self.drama)

    def test_deleting_a_child_leaves_the_parent_alone(self):
        self.store.delete_note(self.drama)
        self.assertEqual(self._live(), {"취미"})

    def test_a_child_restored_alone_comes_back_to_the_top(self):
        self.store.delete_note(self.hobby)
        self.store.restore_note(self.drama)
        restored = self.store.note(self.drama)
        self.assertIsNotNone(restored, "되살린 메모가 목록에 없습니다")
        self.assertEqual(
            int(restored["parent_id"]), TOP_LEVEL_PARENT,
            "부모가 아직 휴지통인데 그 밑으로 되살아나 어디에도 보이지 않습니다",
        )

    def test_purging_a_parent_lifts_a_leftover_child(self):
        """부모 번호만 남고 그 메모는 사라진 상태에 대한 안전장치.

        지금 규칙(하위까지 함께 버리고 함께 되살림)에서는 잘 생기지 않지만,
        이 상태가 되면 하위 메모가 어디에도 뜨지 않으므로 맨 위로 올려 둔다.
        """
        self.store.delete_note(self.drama)
        self.store.conn.execute(
            "UPDATE notes SET deleted_at='202001010000' WHERE id=?", (self.drama,))
        self.store.conn.execute(
            "UPDATE notes SET deleted_at='' WHERE id=?", (self.episode,))
        self.store.conn.commit()
        self.store.purge_expired_trash(days=7)
        self.assertIsNone(self.store.note(self.drama))
        self.assertEqual(int(self.store.note(self.episode)["parent_id"]), TOP_LEVEL_PARENT)


if __name__ == "__main__":
    unittest.main()
