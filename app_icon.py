import sys
from pathlib import Path

from PyQt6.QtGui import QIcon


ICON_FILENAME = "토마2_icon.ico"


def icon_path() -> Path:
    """Locate the shared application icon in source and one-file builds."""
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_dir / ICON_FILENAME


def application_icon() -> QIcon:
    path = icon_path()
    return QIcon(str(path)) if path.is_file() else QIcon()
