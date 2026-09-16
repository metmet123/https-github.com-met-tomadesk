import errno
import sqlite3
import sys
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from app_icon import application_icon
from app_config import APP_NAME
from main_window import MainWindow
from single_instance import SingleInstanceGuard
from storage_config import fallback_storage_dir, save_storage_paths
from store import Store


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon = application_icon()
    app.setWindowIcon(icon)
    guard = SingleInstanceGuard("Local\\CodexShortcutLauncher_7B09D579")
    if not guard.acquire():
        QMessageBox.information(None, APP_NAME, "TomaDesk가 이미 실행 중입니다.")
        return 0
    try:
        store = _open_store_with_recovery()
        if store is None:
            return 1
        _install_exception_hook(store.data_dir / "tomadesk_error.log")
        window = MainWindow(store)
        window.setWindowIcon(icon)
        window.show_initial_state()
        return app.exec()
    finally:
        guard.release()


def _install_exception_hook(log_path: Path) -> None:
    """Keep an unexpected Qt slot exception visible and leave a local diagnostic."""
    target = Path(log_path)

    def report(exc_type, exc_value, exc_traceback) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(f"\n[{datetime.now().isoformat(timespec='seconds')}]\n{details}")
        except OSError:
            pass
        message = "예기치 않은 오류가 발생했습니다. 프로그램을 닫기 전에 작업 상태를 확인해 주세요."
        if target:
            message += f"\n\n오류 기록: {target}"
        try:
            QMessageBox.critical(None, "TomaDesk 오류", message)
        except Exception:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = report


def _open_store_with_recovery() -> Store | None:
    try:
        return Store()
    except (OSError, sqlite3.Error) as exc:
        if _is_permission_error(exc):
            store = _open_store_in_fallback()
            if store is not None:
                return store
        answer = QMessageBox.question(
            None,
            "데이터 폴더 선택",
            "프로그램이 있는 폴더에 데이터를 저장할 수 없습니다.\n"
            f"{exc}\n\n다른 데이터 폴더를 선택하시겠습니까?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
    data_path = QFileDialog.getExistingDirectory(None, "데이터 폴더 선택", str(Path.home()))
    if not data_path:
        return None
    data_dir = Path(data_path)
    try:
        save_storage_paths(data_dir)
        return Store(data_dir=data_dir)
    except (OSError, sqlite3.Error) as exc:
        QMessageBox.critical(None, "저장 위치 설정 실패", str(exc))
        return None


def _is_permission_error(exc: BaseException) -> bool:
    """Tell "the folder is read-only" apart from "the database is broken"."""
    if isinstance(exc, PermissionError):
        return True
    return getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM, errno.EROFS)


def _open_store_in_fallback() -> Store | None:
    """Move to the per-user folder so an EXE under Program Files still runs."""
    data_dir = fallback_storage_dir()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        store = Store(data_dir=data_dir)
        save_storage_paths(data_dir)
    except (OSError, sqlite3.Error):
        return None
    QMessageBox.information(
        None,
        "데이터 폴더 안내",
        "프로그램이 있는 폴더에 저장할 수 없어 아래 폴더를 사용합니다.\n\n"
        f"{data_dir}\n\n설정 화면에서 다른 폴더로 바꿀 수 있습니다.",
    )
    return store


if __name__ == "__main__":
    raise SystemExit(main())
