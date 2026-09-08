"""Bootstrap configuration for the user-selectable unified data folder."""

import filecmp
import json
import os
import shutil
import sys
from pathlib import Path


CONFIG_NAME = "storage_paths.json"
APP_STORAGE_NAME = "CodexShortcutLauncher"


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bootstrap_config_file() -> Path:
    return user_storage_root() / CONFIG_NAME


def user_storage_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / APP_STORAGE_NAME


def fallback_storage_dir() -> Path:
    """Writable location for when the application folder is read-only.

    Installing under ``C:\\Program Files`` leaves no write permission beside the
    EXE, so first launch there would otherwise fail outright.
    """
    return user_storage_root() / "data"


def default_storage_paths(app_directory: Path | None = None) -> tuple[Path, Path]:
    """Data and backups share one folder; the pair is kept for call-site clarity."""
    root = Path(app_directory) if app_directory is not None else application_dir()
    data_dir = root / "data"
    return data_dir, data_dir


def load_storage_paths(
    app_directory: Path | None = None,
    config_file: Path | None = None,
) -> tuple[Path, Path]:
    defaults = default_storage_paths(app_directory)
    path = Path(config_file) if config_file is not None else bootstrap_config_file()
    if not path.is_file():
        return defaults
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        data_dir = _configured_path(values.get("data_dir"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return defaults
    data_dir = data_dir or defaults[0]
    return data_dir, data_dir


def save_storage_paths(
    data_dir: Path,
    backup_dir: Path | None = None,
    config_file: Path | None = None,
) -> Path:
    path = Path(config_file) if config_file is not None else bootstrap_config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    # backup_dir is accepted for callers that still pass it, but backups now live
    # in the data folder, so only that one path is persisted.
    values = {"data_dir": str(Path(data_dir).resolve())}
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return path


def migrate_legacy_storage(
    data_dir: Path,
    backup_dir: Path | None = None,
    config_file: Path | None = None,
    legacy_root: Path | None = None,
) -> bool:
    """Merge the former data/backup layout into one data directory."""
    config = Path(config_file) if config_file is not None else bootstrap_config_file()
    legacy = Path(legacy_root) if legacy_root is not None else config.parent
    legacy_data = legacy / "data"
    legacy_backup = legacy / "backup"
    destination_data = Path(data_dir)
    previous_backup = _legacy_configured_backup(config)
    sibling_backup = destination_data.parent / "backup"
    changed = False
    destination_data.mkdir(parents=True, exist_ok=True)

    source_db = legacy_data / "hotkeys.db"
    destination_db = destination_data / "hotkeys.db"
    if (
        source_db.is_file()
        and not destination_db.exists()
        and not same_path(legacy_data, destination_data)
    ):
        shutil.copy2(source_db, destination_db)
        changed = True

    sources = [legacy_backup, sibling_backup]
    if backup_dir is not None:
        sources.append(Path(backup_dir))
    if previous_backup is not None:
        sources.append(previous_backup)
    seen: set[str] = set()
    for source_dir in sources:
        key = os.path.normcase(str(source_dir.resolve()))
        if key in seen or same_path(source_dir, destination_data) or not source_dir.is_dir():
            continue
        seen.add(key)
        for source in source_dir.iterdir():
            if source.is_file() and _copy_file_without_overwrite(source, destination_data):
                changed = True

    if previous_backup is not None:
        save_storage_paths(destination_data, config_file=config)
        changed = True
    return changed


def _legacy_configured_backup(config: Path) -> Path | None:
    if not config.is_file():
        return None
    try:
        values = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return _configured_path(values.get("backup_dir"))


def _copy_file_without_overwrite(source: Path, destination_dir: Path) -> bool:
    target = destination_dir / source.name
    if not target.exists():
        shutil.copy2(source, target)
        return True
    if filecmp.cmp(source, target, shallow=False):
        return False
    index = 1
    while True:
        candidate = destination_dir / f"{source.stem}_이전{index}{source.suffix}"
        if not candidate.exists():
            shutil.copy2(source, candidate)
            return True
        if filecmp.cmp(source, candidate, shallow=False):
            return False
        index += 1


def _configured_path(value) -> Path | None:
    text = str(value or "").strip()
    return Path(text).expanduser() if text else None


def same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def merge_storage_files(source_dir: Path, destination_dir: Path) -> int:
    """Copy non-database files into the unified data folder without loss."""
    source = Path(source_dir)
    destination = Path(destination_dir)
    if same_path(source, destination) or not source.is_dir():
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in source.iterdir():
        name = item.name.casefold()
        if (
            item.is_file()
            and item.suffix.casefold() != ".db"
            and not name.endswith(("-journal", "-wal", "-shm", ".tmp"))
        ):
            copied += int(_copy_file_without_overwrite(item, destination))
    return copied
