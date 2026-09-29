from pathlib import Path

from storage_config import application_dir, load_storage_paths


APP_NAME = "TomaDesk"
APP_VERSION = "0.1.2"


def app_dir() -> Path:
    """Return the application code directory (safe with Korean paths)."""
    return application_dir()


BASE_DIR = app_dir()
DATA_DIR, BACKUP_DIR = load_storage_paths(BASE_DIR)
DB_PATH = DATA_DIR / "hotkeys.db"
