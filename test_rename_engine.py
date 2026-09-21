from pathlib import Path
import os
import subprocess
import sys
import pytest
from rename_engine import RenameEngine, RenameError, validate, windows_move, identity, parent_identity


@pytest.fixture
def files(tmp_path):
    folder = tmp_path / "files"
    folder.mkdir()
    paths = [folder / name for name in ("a.txt", "b.txt", "c.txt")]
    for i, path in enumerate(paths):
        path.write_text(f"content-{i}", encoding="utf-8")
    return paths


@pytest.fixture
def engine(tmp_path):
    return RenameEngine(tmp_path / "journal" / "history.sqlite3")


@pytest.mark.parametrize("name", ["CON.txt", "com¹.txt", "aux.foo.txt", "bad?.txt", "bad\t.txt", "bad\n.txt", "bad.txt.", "bad.txt ", "../bad.txt", "bad.csv", "a" * 256 + ".txt"])
def test_invalid_names(files, name):
    assert 0 in validate(files[:1], [name])


def test_conflict_propagation_and_independent_row(files):
    # b cannot vacate to c (not participating); a cannot replace b either.
    assert set(validate(files, ["b.txt", "c.txt", None])) == {0, 1}
    assert set(validate(files, ["same.txt", "SAME.txt", "other.txt"])) == {0, 1}
    assert not validate(files, ["b.txt", "a.txt", None])
    assert not validate(files[:1], ["A.txt"])


def test_real_swap_undo_and_case_only(files, engine):
    batch = engine.execute(engine.prepare(files, ["b.txt", "a.txt", None]))
    assert batch["state"] == "complete"
    assert batch["groups"][0]["state"] == "done"
    assert files[0].read_text() == "content-1"
    assert files[1].read_text() == "content-0"
    reopened = RenameEngine(engine.path)
    reopened.undo()
    assert files[0].read_text() == "content-0"
    assert files[1].read_text() == "content-1"
    assert not reopened.undo_candidate()
    reopened.execute(reopened.prepare(files[:1], ["A.txt"]))
    assert "A.txt" in [p.name for p in files[0].parent.iterdir()]
    reopened.undo()
    assert "a.txt" in [p.name for p in files[0].parent.iterdir()]


def test_never_overwrite_native_move(files):
    with pytest.raises(OSError):
        windows_move(str(files[0]), str(files[1]), identity(files[0]), parent_identity(files[0]))
    assert files[0].read_text() == "content-0"
    assert files[1].read_text() == "content-1"


def test_external_edit_and_collision_preflight(files, engine):
    rows = engine.prepare(files[:1], ["new.txt"])
    files[0].write_text("external edit")
    with pytest.raises(RenameError):
        engine.execute(rows)
    assert files[0].read_text() == "external edit"
    assert not engine.history()
    rows = engine.prepare(files[:1], ["new.txt"])
    target = files[0].with_name("new.txt")
    target.write_text("collision")
    with pytest.raises(RenameError):
        engine.execute(rows)
    assert target.read_text() == "collision"


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_failure_at_each_swap_move_rolls_back(files, engine, fail_at):
    calls = 0
    def failing(source, target, expected, parent):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise PermissionError("locked")
        windows_move(source, target, expected, parent)
    engine.move = failing
    batch = engine.execute(engine.prepare(files, ["b.txt", "a.txt", "new.txt"]))
    assert batch["groups"][0]["state"] == "rolled_back"
    assert batch["groups"][1]["state"] == "done"
    assert files[0].read_text() == "content-0"
    assert files[1].read_text() == "content-1"
    assert files[2].with_name("new.txt").read_text() == "content-2"
    assert not list(files[0].parent.glob(".td-*"))


def test_recovery_failure_blocks_new_work_and_then_retries(files, engine):
    calls = 0
    def failing(source, target, expected, parent):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise PermissionError("still locked")
        windows_move(source, target, expected, parent)
    engine.move = failing
    batch = engine.execute(engine.prepare(files, ["b.txt", "a.txt", "new.txt"]))
    assert batch["state"] == "recovery_required"
    assert batch["groups"][1]["state"] == "pending"
    with pytest.raises(RenameError):
        engine.execute(engine.prepare([files[2]], ["third.txt"]))
    recovered = RenameEngine(engine.path)
    recovered.recover()
    assert not recovered.pending()
    assert [p.read_text() for p in files] == ["content-0", "content-1", "content-2"]


@pytest.mark.parametrize("crash_at", [1, 2, 3, 4])
def test_actual_process_exit_after_each_move_recover(files, engine, crash_at):
    script = """
import os, sys
from pathlib import Path
from rename_engine import RenameEngine
count = 0
def crash(event, batch):
    global count
    if event == 'moved':
        count += 1
        if count == int(sys.argv[3]): os._exit(73)
engine = RenameEngine(Path(sys.argv[1]), checkpoint=crash)
folder = Path(sys.argv[2])
engine.execute(engine.prepare([folder/'a.txt', folder/'b.txt'], ['b.txt','a.txt']))
"""
    child = subprocess.run([sys.executable, "-c", script, str(engine.path), str(files[0].parent), str(crash_at)], timeout=30)
    assert child.returncode == 73
    assert engine.pending()
    engine.recover()
    assert not engine.pending()
    assert [p.read_text() for p in files] == ["content-0", "content-1", "content-2"]
    assert not list(files[0].parent.glob(".td-*"))


def test_undo_refuses_modified_file_and_new_occupant(files, engine):
    engine.execute(engine.prepare(files[:1], ["new.txt"]))
    new = files[0].with_name("new.txt")
    new.write_text("external")
    with pytest.raises(RenameError):
        engine.undo()
    assert new.read_text() == "external"
    assert not files[0].exists()


def test_actual_windows_file_lock(files, engine):
    import win32file
    rows = engine.prepare(files[:1], ["new.txt"])
    handle = win32file.CreateFile(str(files[0]), 0x80000000, 1, None, 3, 0, None)
    try:
        batch = engine.execute(rows)
        assert batch["groups"][0]["state"] == "rolled_back"
        assert files[0].read_text() == "content-0"
    finally:
        handle.Close()


def test_competing_engine_lock(engine):
    other = RenameEngine(engine.path)
    with engine._lock():
        with pytest.raises(RenameError):
            other.recover()


def test_skip_invalid_only_uses_independent_valid_rows(files, engine):
    rows = engine.prepare(files, ["b.txt", "c.txt", "NUL.txt"], skip_invalid=True)
    assert not rows
    rows = engine.prepare(files, ["bad?.txt", None, "new.txt"], skip_invalid=True)
    assert [r["row"] for r in rows] == [2]


@pytest.mark.parametrize("crash_at", list(range(1, 13)))
def test_actual_exit_at_each_journal_commit(files, engine, crash_at):
    script = """
import os, sys
from pathlib import Path
from rename_engine import RenameEngine
count = 0
def crash(event, batch):
    global count
    if event == 'saved':
        count += 1
        if count == int(sys.argv[3]): os._exit(74)
engine = RenameEngine(Path(sys.argv[1]), checkpoint=crash)
folder = Path(sys.argv[2])
engine.execute(engine.prepare([folder/'a.txt', folder/'b.txt'], ['b.txt','a.txt']))
"""
    child = subprocess.run([sys.executable, "-c", script, str(engine.path), str(files[0].parent), str(crash_at)], timeout=30)
    assert child.returncode == 74
    committed = engine.history()[0]["groups"][0]["state"] == "done"
    engine.recover()
    assert not engine.pending()
    assert [p.read_text() for p in files[:2]] == (["content-1", "content-0"] if committed else ["content-0", "content-1"])
    assert not list(files[0].parent.glob(".td-*"))


@pytest.mark.parametrize("crash_at", [1, 2, 3, 4])
def test_process_exit_during_undo_can_recover_then_retry(files, engine, crash_at):
    engine.execute(engine.prepare(files[:2], ["b.txt", "a.txt"]))
    script = """
import os, sys
from rename_engine import RenameEngine
count = 0
def crash(event, batch):
    global count
    if event == 'moved':
        count += 1
        if count == int(sys.argv[2]): os._exit(75)
RenameEngine(sys.argv[1], checkpoint=crash).undo()
"""
    child = subprocess.run([sys.executable, "-c", script, str(engine.path), str(crash_at)], timeout=30)
    assert child.returncode == 75
    engine.recover()
    assert [p.read_text() for p in files[:2]] == ["content-1", "content-0"]
    engine.undo()
    assert [p.read_text() for p in files[:2]] == ["content-0", "content-1"]


def test_late_target_collision_preserved_and_original_restored(files, engine):
    target = files[0].with_name("new.txt")
    count = 0
    def collision(source, dest, expected, parent):
        nonlocal count
        count += 1
        if count == 2:
            target.write_text("late foreign file")
        windows_move(source, dest, expected, parent)
    engine.move = collision
    result = engine.execute(engine.prepare(files[:1], ["new.txt"]))
    assert result["groups"][0]["state"] == "rolled_back"
    assert files[0].read_text() == "content-0"
    assert target.read_text() == "late foreign file"


def test_recovery_never_overwrites_recreated_source(files, engine):
    class Crash(BaseException):
        pass
    def crash(event, batch):
        if event == "moved":
            raise Crash()
    engine.checkpoint = crash
    with pytest.raises(Crash):
        engine.execute(engine.prepare(files[:1], ["new.txt"]))
    files[0].write_text("foreign replacement")
    recovered = RenameEngine(engine.path)
    recovered.recover()
    assert recovered.pending()
    assert files[0].read_text() == "foreign replacement"
    temporary = Path(recovered.pending()[0]["groups"][0]["rows"][0]["tmp"])
    assert temporary.read_text() == "content-0"


def test_journal_unwritable_does_not_move_files(files, engine, monkeypatch):
    rows = engine.prepare(files[:1], ["new.txt"])
    def fail(*_):
        raise OSError("disk full")
    monkeypatch.setattr(engine, "_save", fail)
    with pytest.raises(OSError):
        engine.execute(rows)
    assert files[0].read_text() == "content-0"


def test_content_hash_rejects_same_size_same_mtime_change(files, engine):
    rows = engine.prepare(files[:1], ["new.txt"])
    info = files[0].stat()
    files[0].write_text("CONTENT-0")
    os.utime(files[0], ns=(info.st_atime_ns, info.st_mtime_ns))
    with pytest.raises(RenameError):
        engine.execute(rows)


def test_hardlinks_and_folder_target_rejected(files):
    link = files[0].with_name("link.txt")
    os.link(files[0], link)
    assert 0 in validate(files[:1], ["new.txt"])
    folder = files[1].with_name("folder.txt")
    folder.mkdir()
    assert 0 in validate([files[1]], [folder.name])


@pytest.mark.parametrize("crash_at", [1, 2, 3, 4])
def test_recovery_itself_can_be_interrupted_and_repeated(files, engine, crash_at):
    class Crash(BaseException):
        pass
    count = 0
    def initial_crash(event, batch):
        nonlocal count
        if event == "moved":
            count += 1
            if count == 3:
                raise Crash()
    engine.checkpoint = initial_crash
    with pytest.raises(Crash):
        engine.execute(engine.prepare(files[:2], ["b.txt", "a.txt"]))
    # At this point a is at b and b is at its temp. Recovery needs 3 moves.
    count = 0
    def recovery_crash(event, batch):
        nonlocal count
        if event == "saved":
            count += 1
            if count == crash_at:
                raise Crash()
    recovering = RenameEngine(engine.path, checkpoint=recovery_crash)
    with pytest.raises(Crash):
        recovering.recover()
    reopened = RenameEngine(engine.path)
    reopened.recover()
    assert not reopened.pending()
    assert [p.read_text() for p in files[:2]] == ["content-0", "content-1"]


def test_undo_does_not_replace_new_file_at_old_name(files, engine):
    engine.execute(engine.prepare(files[:1], ["new.txt"]))
    files[0].write_text("foreign")
    with pytest.raises(RenameError):
        engine.undo()
    assert files[0].read_text() == "foreign"
    assert files[0].with_name("new.txt").read_text() == "content-0"


def test_connected_chain_execute_and_undo(files, engine):
    result = engine.execute(engine.prepare(files[:2], ["b.txt", "new.txt"]))
    assert len(result["groups"]) == 1
    assert files[1].read_text() == "content-0"
    assert files[1].with_name("new.txt").read_text() == "content-1"
    engine.undo()
    assert [p.read_text() for p in files] == ["content-0", "content-1", "content-2"]


def test_mapped_network_drive_rejected(files, monkeypatch):
    monkeypatch.setattr("win32file.GetDriveType", lambda anchor: 4)
    assert "네트워크" in validate(files[:1], ["new.txt"])[0]
