"""Conservative Windows rename transactions with durable, recoverable intent.

No replace, unlink or content writes are used for user files. SQLite history is
separate from restorable app data. Pending operations are never auto-pruned.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import re
import sqlite3
import stat
import uuid


class RenameError(Exception):
    pass


def key(path):
    return os.path.abspath(path).casefold()


def name_error(path, name):
    if not name or name in {".", ".."}:
        return "이름이 비어 있습니다."
    if any(ord(c) < 32 or c in '\\/:*?"<>|' for c in name):
        return "금지 문자 또는 탭/줄바꿈이 있습니다."
    if name.endswith((" ", ".")):
        return "이름 끝 공백/마침표는 사용할 수 없습니다."
    stem = name.split(".")[0].rstrip(" ").upper()
    if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem):
        return "Windows 예약 이름입니다."
    try:
        if len(name.encode("utf-16-le")) // 2 > 255 or len(str(path.with_name(name)).encode("utf-16-le")) // 2 >= 260:
            return "지원 경로 길이(260자 미만)를 초과합니다."
    except UnicodeError:
        return "지원하지 않는 유니코드 문자입니다."
    if Path(name).suffix != path.suffix:
        return "확장자는 변경할 수 없습니다."
    return ""


def source_error(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return "일반 파일이 아닙니다."
        if info.st_nlink != 1:
            return "하드 링크 파일은 지원하지 않습니다."
        if not info.st_ino:
            return "안정적인 파일 식별자를 얻지 못했습니다."
        if str(path).startswith("\\\\"):
            return "네트워크/확장 경로는 지원하지 않습니다."
        if os.name == "nt":
            import win32file
            if win32file.GetDriveType(path.anchor) == 4:
                return "네트워크 드라이브는 지원하지 않습니다."
        for parent in (path, *path.parents):
            if getattr(parent.lstat(), "st_file_attributes", 0) & 0x400 or parent.is_symlink():
                return "심볼릭 링크/재분석 경로는 지원하지 않습니다."
        if len(str(path.parent / (".td-" + "0" * 32 + ".tmp")).encode("utf-16-le")) // 2 >= 260:
            return "안전한 임시 이름을 만들 경로 길이가 부족합니다."
    except (OSError, ValueError) as exc:
        return f"원본을 확인할 수 없습니다: {exc}"
    return ""


def validate(paths, names):
    if len(paths) != len(names):
        raise RenameError("파일과 이름 개수가 다릅니다.")
    paths = [Path(p).absolute() for p in paths]
    errors, targets = {}, {}
    active = {i for i, (p, n) in enumerate(zip(paths, names)) if n is not None and n != p.name}
    sources = {}
    for i in active:
        p, name = paths[i], names[i]
        error = name_error(p, name) or source_error(p)
        if error:
            errors[i] = error
        else:
            targets[i] = p.with_name(name)
        sources.setdefault(key(p), []).append(i)
    for indices in sources.values():
        if len(indices) > 1:
            for i in indices:
                errors[i] = "같은 원본 파일이 여러 번 지정되었습니다."
    destinations = {}
    for i, target in targets.items():
        destinations.setdefault(key(target), []).append(i)
    for indices in destinations.values():
        if len(indices) > 1:
            for i in indices:
                errors[i] = "같은 폴더의 목표 이름이 중복됩니다."
    # Invalid sources will not vacate their names. Propagate this along chains.
    while True:
        previous = dict(errors)
        moving = {key(paths[i]) for i in active if i not in errors}
        for i, target in targets.items():
            if i not in errors and os.path.lexists(target) and key(target) not in moving:
                errors[i] = "목표 이름에 다른 파일/폴더가 있거나 이동할 수 없는 행이 있습니다."
        if previous == errors:
            break
    return errors


def _stream_identity(stream):
    before = os.fstat(stream.fileno())
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    after = os.fstat(stream.fileno())
    fields = lambda s: [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink]
    if fields(before) != fields(after) or after.st_nlink != 1:
        raise RenameError("파일을 읽는 동안 변경되었거나 하드 링크입니다.")
    return fields(after) + [digest.hexdigest()]


def identity(path):
    error = source_error(Path(path))
    if error:
        raise RenameError(error)
    with open(path, "rb") as stream:
        return _stream_identity(stream)


def parent_identity(path):
    info = Path(path).parent.stat()
    return [info.st_dev, info.st_ino]


def windows_move(source, target, expected, parent):
    """Lock the actual source against writes/deletion, verify it, rename by handle.

    FileRenameInfo.ReplaceIfExists is FALSE: a late target collision fails too.
    This module deliberately has no POSIX overwrite-prone rename fallback.
    """
    if os.name != "nt":
        raise RenameError("실제 이름 변경은 Windows에서만 지원합니다.")
    import msvcrt
    import win32file
    if key(Path(source).parent) != key(Path(target).parent):
        raise RenameError("폴더 간 이동은 지원하지 않습니다.")
    if parent_identity(source) != parent or source_error(Path(source)):
        raise RenameError("원본 폴더 또는 파일 상태가 변경되었습니다.")
    # DELETE | GENERIC_READ; share read only. Existing write/delete handles fail.
    handle = win32file.CreateFile(str(source), 0x80010000, 1, None, 3, 0x00200000, None)
    fd = msvcrt.open_osfhandle(handle.Detach(), os.O_RDONLY | os.O_BINARY)
    with os.fdopen(fd, "rb") as stream:
        if _stream_identity(stream) != expected:
            raise RenameError("파일 내용/식별자가 실행 기록과 달라 중단했습니다.")
        class RenameInfo(ctypes.Structure):
            _fields_ = [("flags", wintypes.DWORD), ("root", wintypes.HANDLE),
                        ("length", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]
        encoded = str(Path(target).absolute()).encode("utf-16-le")
        buffer = ctypes.create_string_buffer(max(ctypes.sizeof(RenameInfo), RenameInfo.name.offset + len(encoded) + 2))
        info = RenameInfo.from_buffer(buffer)
        info.flags = 0
        info.root = None
        info.length = len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.name.offset, encoded, len(encoded))
        api = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
        api.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        api.restype = wintypes.BOOL
        if not api(msvcrt.get_osfhandle(stream.fileno()), 3, buffer, len(buffer)):
            raise ctypes.WinError(ctypes.get_last_error())


class RenameEngine:
    def __init__(self, journal, move=windows_move, checkpoint=None):
        self.path = Path(journal)
        self.move = move
        self.checkpoint = checkpoint or (lambda event, batch: None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS rename_runs (id TEXT PRIMARY KEY, created TEXT NOT NULL, payload TEXT NOT NULL)")

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=2)
        conn.execute("PRAGMA synchronous=FULL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @contextmanager
    def _lock(self):
        import msvcrt
        with open(str(self.path) + ".lock", "a+b") as stream:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RenameError("다른 이름 변경 작업이 진행 중입니다.") from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def _save(self, batch):
        with self._db() as conn:
            conn.execute("INSERT OR REPLACE INTO rename_runs VALUES(?, ?, ?)",
                         (batch["id"], batch["created"], json.dumps(batch, ensure_ascii=False)))
        self.checkpoint("saved", batch)

    def history(self):
        with self._db() as conn:
            rows = conn.execute("SELECT payload FROM rename_runs ORDER BY created DESC, rowid DESC").fetchall()
        history = [json.loads(row[0]) for row in rows]
        if any(batch.get("version") != 1 for batch in history):
            raise RenameError("지원하지 않는 실행 기록 버전입니다. 자동 변경을 중단합니다.")
        return history

    def pending(self):
        return [batch for batch in self.history() if batch["state"] != "complete"]

    def prepare(self, paths, names, skip_invalid=False):
        errors = validate(paths, names)
        if errors and not skip_invalid:
            raise RenameError("문제 행을 수정하거나 문제 행 제외를 선택하세요.")
        rows = []
        for i, (path, name) in enumerate(zip(paths, names)):
            path = Path(path).absolute()
            if i in errors or name is None or name == path.name:
                continue
            if self.path.parent.resolve() == path.parent.resolve():
                raise RenameError("실행 일지 폴더의 파일은 변경할 수 없습니다.")
            rows.append(dict(row=i, src=str(path), dst=str(path.with_name(name)),
                             tmp=str(path.with_name(".td-" + uuid.uuid4().hex + ".tmp")),
                             identity=identity(path), parent=parent_identity(path)))
        return rows

    @staticmethod
    def _groups(rows):
        remaining = list(rows)
        groups = []
        while remaining:
            group = [remaining.pop(0)]
            occupied = {key(group[0]["src"]), key(group[0]["dst"])}
            while True:
                found = [r for r in remaining if {key(r["src"]), key(r["dst"])} & occupied]
                if not found:
                    break
                for row in found:
                    remaining.remove(row)
                    group.append(row)
                    occupied.update((key(row["src"]), key(row["dst"])))
            groups.append(dict(state="pending", rows=group, error=""))
        return groups

    def execute(self, rows):
        with self._lock():
            return self._execute(rows)

    def _execute(self, rows, kind="execute", parent=None):
        if self.pending():
            raise RenameError("미완료 기록이 있습니다. 복구 확인 후 다시 실행하세요.")
        if not rows:
            raise RenameError("변경할 파일이 없습니다.")
        errors = validate([r["src"] for r in rows], [Path(r["dst"]).name for r in rows])
        if errors:
            raise RenameError("실행 직전 검사 실패: " + "; ".join(errors.values()))
        for row in rows:
            if identity(row["src"]) != row["identity"] or parent_identity(row["src"]) != row["parent"]:
                raise RenameError("미리보기 후 파일/폴더가 변경되었습니다.")
            if os.path.lexists(row["tmp"]):
                raise RenameError("임시 이름에 다른 파일이 있습니다.")
        batch = dict(version=1, id=uuid.uuid4().hex, created=datetime.now(timezone.utc).isoformat(),
                     state="running", kind=kind, parent=parent, groups=self._groups(rows))
        self._save(batch)  # Durable complete intent BEFORE the first rename.
        for group in batch["groups"]:
            group["state"] = "running"
            self._save(batch)
            try:
                for row in group["rows"]:
                    self._move(batch, row, row["src"], row["tmp"])
                for row in group["rows"]:
                    self._move(batch, row, row["tmp"], row["dst"])
                group["state"] = "done"
                self._save(batch)
            except Exception as exc:
                group["error"] = str(exc)
                try:
                    self._rollback(batch, group)
                except Exception as recovery:
                    group["state"] = "recovery_required"
                    group["error"] += " / 복구 필요: " + str(recovery)
                self._save(batch)
                if group["state"] == "recovery_required":
                    break  # Do not start new work while unresolved files remain.
        batch["state"] = "complete" if all(g["state"] in {"done", "rolled_back"} for g in batch["groups"]) else "recovery_required"
        self._save(batch)
        return batch

    def _move(self, batch, row, source, target):
        batch["intent"] = dict(source=source, target=target)
        self._save(batch)
        self.move(source, target, row["identity"], row["parent"])
        self.checkpoint("moved", batch)  # Crash here: recovery finds actual identity.
        batch["intent"] = None
        self._save(batch)

    def _locations(self, group):
        candidates = {}
        for row in group["rows"]:
            if parent_identity(row["src"]) != row["parent"]:
                raise RenameError("폴더 식별자가 변경되었습니다.")
            wanted = {key(row[n]) for n in ("src", "dst", "tmp")}
            for entry in Path(row["src"]).parent.iterdir():
                if key(entry) in wanted:
                    candidates[key(entry)] = entry
        locations = []
        for row in group["rows"]:
            matches = []
            for path in candidates.values():
                try:
                    info = path.stat()
                    if [info.st_dev, info.st_ino] == row["identity"][:2]:
                        if identity(path) != row["identity"]:
                            raise RenameError("외부 편집이 감지되어 자동 복구를 중단했습니다.")
                        matches.append(str(path))
                except FileNotFoundError:
                    continue
            if len(matches) != 1:
                raise RenameError("원본 파일을 유일하게 찾을 수 없습니다. 기록 경로를 확인하세요.")
            locations.append(matches[0])
        return locations

    def _rollback(self, batch, group):
        locations = self._locations(group)
        if all(loc == row["src"] for loc, row in zip(locations, group["rows"])):
            group["state"] = "rolled_back"
            return
        owned = {key(p) for p in locations}
        for row in group["rows"]:
            for dest in (row["src"], row["tmp"]):
                if os.path.lexists(dest) and key(dest) not in owned:
                    raise RenameError("복구 경로에 다른 파일이 있습니다. 덮어쓰지 않습니다.")
        for row, current in zip(group["rows"], locations):
            if key(current) != key(row["tmp"]):
                self._move(batch, row, current, row["tmp"])
        for row in group["rows"]:
            self._move(batch, row, row["tmp"], row["src"])
        group["state"] = "rolled_back"

    def recover(self):
        with self._lock():
            batches = self.pending()
            for batch in batches:
                for group in batch["groups"]:
                    if group["state"] == "pending":
                        group["state"] = "rolled_back"
                    elif group["state"] not in {"done", "rolled_back"}:
                        try:
                            self._rollback(batch, group)
                        except Exception as exc:
                            group["state"] = "recovery_required"
                            group["error"] = str(exc)
                    self._save(batch)
                batch["state"] = "complete" if all(g["state"] in {"done", "rolled_back"} for g in batch["groups"]) else "recovery_required"
                self._save(batch)
            return batches

    def undo_candidate(self):
        history = self.history()
        undone = {r["original_group"] for b in history if b["kind"] == "undo"
                  for g in b["groups"] if g["state"] == "done" for r in g["rows"]}
        runs = [b for b in history if b["kind"] == "execute" and b["state"] == "complete"][:10]
        for batch in runs:
            rows = []
            for i, group in enumerate(batch["groups"]):
                group_id = batch["id"] + ":" + str(i)
                if group["state"] == "done" and group_id not in undone:
                    rows.extend(dict(r, src=r["dst"], dst=r["src"],
                                     tmp=str(Path(r["src"]).with_name(".td-" + uuid.uuid4().hex + ".tmp")),
                                     original_group=group_id) for r in group["rows"])
            if rows:
                return rows
        return []

    def undo(self, expected_run=None):
        with self._lock():
            rows = self.undo_candidate()
            if expected_run is not None and {r["original_group"] for r in rows} != expected_run:
                raise RenameError("확인하는 동안 실행 이력이 바뀌었습니다.")
            return self._execute(rows, kind="undo")
