import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import builtins
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from screen_ocr import (OcrResultDialog, OcrUnavailable, ScreenFrame, ScreenOcrController,
                        WindowsOcrBackend, compose_region, preferred_language)

APP = QApplication.instance() or QApplication([])


def picture(width=300, height=100, color="white"):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    return image


def wait_until(predicate):
    for _ in range(250):
        if predicate():
            return
        QTest.qWait(20)
    assert predicate(), "worker did not finish"


@pytest.mark.parametrize("tags,expected", [(["en-US", "ko-KR"], "ko-KR"), (["ko", "en"], "ko"),
                                          (["ja", "en-GB"], "en-GB"), (["EN-US"], "EN-US")])
def test_language_priority(tags, expected):
    assert preferred_language(tags) == expected


@pytest.mark.parametrize("tags", [[], ["ja-JP"], ["kok", "eng"]])
def test_no_supported_language(tags):
    with pytest.raises(OcrUnavailable, match="언어팩"):
        preferred_language(tags)


def test_missing_package_disables_only_ocr():
    with patch.object(WindowsOcrBackend, "_types", side_effect=OcrUnavailable("구성 요소 없음")):
        assert WindowsOcrBackend().availability() == (False, "구성 요소 없음")


def test_real_import_boundary_handles_missing_projection():
    original_import = builtins.__import__
    def blocked(name, *args, **kwargs):
        if name.startswith("winrt"):
            raise ImportError("test missing projection")
        return original_import(name, *args, **kwargs)
    with patch("builtins.__import__", side_effect=blocked):
        ready, message = WindowsOcrBackend().availability()
        assert not ready and "구성 요소" in message


@pytest.mark.parametrize("size", [(0, 0), (101, 10), (10, 101)])
def test_backend_rejects_empty_or_native_oversized_image(size):
    engine = SimpleNamespace(available_recognizer_languages=[SimpleNamespace(language_tag="ko")],
                             max_image_dimension=100, try_create_from_language=lambda tag: object())
    with patch.object(WindowsOcrBackend, "_types", return_value=(engine, str, None, None, None)):
        with pytest.raises(OcrUnavailable):
            WindowsOcrBackend().recognize(picture(*size))


def test_engine_creation_failure_is_explained():
    engine = SimpleNamespace(available_recognizer_languages=[SimpleNamespace(language_tag="ko")],
                             try_create_from_language=lambda tag: None)
    with patch.object(WindowsOcrBackend, "_types", return_value=(engine, str, None, None, None)):
        with pytest.raises(OcrUnavailable, match="초기화"):
            WindowsOcrBackend().recognize(picture())


def test_backend_missing_languages_and_runtime_failure():
    engine = SimpleNamespace(available_recognizer_languages=[])
    with patch.object(WindowsOcrBackend, "_types", return_value=(engine,)):
        assert "언어팩" in WindowsOcrBackend().availability()[1]
    with patch.object(WindowsOcrBackend, "_types", side_effect=RuntimeError("private details")):
        ready, message = WindowsOcrBackend().availability()
        assert not ready and "private details" not in message


def test_mixed_dpi_negative_origin_maps_pixels_without_stretching_gaps():
    frames = [ScreenFrame(QRect(-100, 0, 100, 100), picture(125, 125, "red")),
              ScreenFrame(QRect(20, 0, 100, 100), picture(150, 150, "blue"))]
    result = compose_region(frames, QRect(-50, 10, 120, 20))
    assert (result.width(), result.height()) == (180, 30)
    assert result.pixelColor(0, 0) == QColor("red")
    assert result.pixelColor(80, 0) == QColor("white")
    assert result.pixelColor(110, 0) == QColor("blue")


def test_actual_pixel_crop_nonuniform_ratios():
    image = picture(200, 150, "red")
    painter = QPainter(image)
    painter.fillRect(QRect(100, 75, 100, 75), QColor("blue"))
    painter.end()
    result = compose_region([ScreenFrame(QRect(100, -100, 100, 100), image)], QRect(150, -50, 50, 50))
    assert (result.width(), result.height()) == (100, 100)
    assert result.pixelColor(50, 50) == QColor("blue")


@pytest.mark.parametrize("selection", [QRect(), QRect(0, 0, 1, 1), QRect(500, 500, 10, 10)])
def test_empty_or_offscreen_selection(selection):
    with pytest.raises(OcrUnavailable):
        compose_region([ScreenFrame(QRect(0, 0, 100, 100), picture(100, 100))], selection)


def test_oversized_selection_is_rejected_before_allocation():
    with pytest.raises(OcrUnavailable, match="너무 큽니다"):
        compose_region([ScreenFrame(QRect(0, 0, 100, 100), picture(100, 100))], QRect(0, 0, 100, 100), max_pixels=10)


def test_result_edit_copy_restore_and_empty_preserves_clipboard():
    dialog = OcrResultDialog()
    try:
        dialog.display("한글 001\nHello")
        assert APP.clipboard().text() == "한글 001\nHello"
        dialog.editor.setPlainText("수정")
        assert APP.clipboard().text() != "수정"
        dialog.copy_text()
        assert APP.clipboard().text() == "수정"
        assert dialog.original == "한글 001\nHello"
        dialog.display("")
        assert APP.clipboard().text() == "수정"
        assert not dialog.copy_button.isEnabled()
        dialog.display("error", error=True)
        assert APP.clipboard().text() == "수정" and not dialog.editor.toPlainText()
    finally:
        dialog.close()


def test_result_line_cleanup_is_explicit_undoable_and_keeps_original():
    dialog = OcrResultDialog()
    try:
        dialog.display(" 001\n\n원문 ")
        dialog.join_lines()
        assert dialog.editor.toPlainText() == " 001  원문 "
        assert APP.clipboard().text() == dialog.original == " 001\n\n원문 "
        dialog.editor.undo()
        assert dialog.editor.toPlainText() == dialog.original
    finally:
        dialog.close()


@pytest.fixture
def controller():
    backend = SimpleNamespace(availability=lambda: (True, "ok"), recognize=lambda image: "인식 123")
    controller = ScreenOcrController(backend=backend, capture=lambda: [ScreenFrame(QRect(0, 0, 300, 100), picture())])
    yield controller
    controller.shutdown()
    if controller.pending:
        wait_until(lambda: not controller._worker.is_alive())
    controller.dialog.deleteLater()
    controller.deleteLater()
    APP.processEvents()


def test_worker_result_copied_and_no_duplicate_job(controller):
    assert controller.recognize_image(picture())
    assert not controller.recognize_image(picture())
    wait_until(lambda: not controller.pending)
    assert APP.clipboard().text() == "인식 123"


def test_close_during_recognition_discards_late_result(controller):
    gate = threading.Event()
    controller.backend.recognize = lambda image: (gate.wait(2), "late")[1]
    APP.clipboard().setText("keep")
    controller.recognize_image(picture())
    controller.dialog.close()
    gate.set()
    wait_until(lambda: not controller.pending)
    assert APP.clipboard().text() == "keep"
    assert not controller.dialog.isVisible()


def test_shutdown_worker_does_not_touch_clipboard(controller):
    gate = threading.Event()
    controller.backend.recognize = lambda image: (gate.wait(2), "late")[1]
    APP.clipboard().setText("keep")
    controller.recognize_image(picture())
    controller.shutdown()
    gate.set()
    wait_until(lambda: not controller._worker.is_alive())
    controller._poll()
    assert APP.clipboard().text() == "keep"


def test_worker_error_keeps_clipboard_and_allows_retry(controller):
    def fail(image):
        raise RuntimeError("private path")
    controller.backend.recognize = fail
    APP.clipboard().setText("keep")
    controller.recognize_image(picture())
    wait_until(lambda: not controller.pending)
    assert APP.clipboard().text() == "keep"
    assert "실패" in controller.dialog.status.text()
    assert "private path" not in controller.dialog.status.text()
    controller.backend.recognize = lambda image: "retry"
    controller.recognize_image(picture())
    wait_until(lambda: not controller.pending)
    assert APP.clipboard().text() == "retry"


def test_capture_delay_cancel_and_reentrancy(controller):
    assert controller.start()
    assert not controller.start()
    controller.cancel()
    QTest.qWait(160)
    assert not controller.overlays and not controller.busy


def test_capture_and_retry_recheck_start_guard(controller):
    controller.can_start = lambda: False
    assert not controller.start()
    controller._starting = True
    controller._begin_capture()
    assert not controller.overlays and not controller.frames


def test_hotkey_ids_are_unique():
    import main_window
    ids = [value for key, value in vars(main_window).items() if key.endswith("HOTKEY_ID")]
    assert len(ids) == len(set(ids))


def test_selection_mouse_reverse_drag_and_escape(controller):
    controller._starting = True
    controller._begin_capture()
    overlay = controller.overlays[0]
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(150, 60))
    controller.update_selection(QPoint(20, 10))
    assert controller.selection == QRect(QPoint(150, 60), QPoint(20, 10)).normalized()
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    assert not controller.overlays and not controller.frames and not controller.busy


def test_selection_release_runs_ocr(controller):
    controller._starting = True
    controller._begin_capture()
    overlay = controller.overlays[0]
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(20, 10))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(150, 60))
    assert not controller.overlays and not controller.frames
    wait_until(lambda: not controller.pending)
    assert APP.clipboard().text() == "인식 123"


def test_focus_loss_cancels_selection(controller):
    controller._starting = True
    controller._begin_capture()
    controller._application_state(Qt.ApplicationState.ApplicationInactive)
    assert not controller.busy and not controller.overlays


def test_capture_failure_and_unavailable_do_not_capture(controller):
    def fail():
        raise OcrUnavailable("캡처 실패")
    controller.capture = fail
    controller._starting = True
    controller._begin_capture()
    assert controller.dialog.status.text() == "캡처 실패"
    assert not controller.frames and not controller.busy
    controller.backend.availability = lambda: (False, "언어팩 필요")
    assert not controller.start()
    assert controller.dialog.status.text() == "언어팩 필요"


def test_main_window_recording_playback_exclusion_guards():
    from main_window import MainWindow
    from unittest.mock import Mock
    controller = Mock()
    fake = SimpleNamespace(_recording=False, _macro_playing=False, excluded_apps=[], screen_ocr=controller)
    with patch("main_window.foreground_application", return_value=None), patch("main_window.is_app_excluded", return_value=False):
        MainWindow.show_screen_ocr(fake)
        fake._recording = True
        MainWindow.show_screen_ocr(fake)
        fake._recording = False
        fake._macro_playing = True
        MainWindow.show_screen_ocr(fake)
        assert controller.start.call_count == 1
    fake._macro_playing = False
    with patch("main_window.foreground_application", return_value=None), patch("main_window.is_app_excluded", return_value=True):
        MainWindow.show_screen_ocr(fake)
    assert controller.start.call_count == 1


def test_ocr_hotkey_persist_registration_and_conflicts():
    from test_settings_dday_ux import SettingsWindowTest
    from main_window import SCREEN_OCR_HOTKEY_ID, SHORTCUT_OVERLAY_HOTKEY_ID
    case = SettingsWindowTest()
    case.setUpClass()
    case.setUp()
    try:
        case.window.show_settings()
        dialog = case.window._settings_dialog
        assert "OCR" in dialog.ocr_status.text()
        dialog.hotkey_builders["screen_ocr_hotkey"].setText("Ctrl+Alt+Shift+O")
        with patch.object(QMessageBox, "information"), patch.object(QMessageBox, "warning") as warning:
            dialog._validate_and_accept()
        assert not warning.called
        assert case.store.setting("screen_ocr_hotkey", "unset") == "Ctrl+Alt+Shift+O"
        assert SCREEN_OCR_HOTKEY_ID in case.window.hotkeys.registered
        assert case.window.hotkeys.registered[SHORTCUT_OVERLAY_HOTKEY_ID][0] == "Ctrl+Alt+H"
        with pytest.raises(ValueError):
            case.window._validate_unique_hotkey("Ctrl+Alt+Shift+O", None)
        with pytest.raises(ValueError):
            case.window._validate_content_hotkey("Ctrl+Alt+Shift+O")
    finally:
        case.tearDown()


@pytest.mark.skipif(os.environ.get("TOMADESK_NATIVE_OCR_TEST") != "1", reason="opt-in Windows OCR fixture")
def test_native_windows_ocr_on_generated_image_in_worker():
    backend = WindowsOcrBackend()
    assert backend.availability()[0], backend.availability()[1]
    # Offscreen Qt has no system font database; load a real glyph source.
    font_id = QFontDatabase.addApplicationFont(os.path.join(os.environ["WINDIR"], "Fonts", "malgun.ttf"))
    assert font_id >= 0
    image = picture(1000, 220)
    painter = QPainter(image)
    painter.setPen(QColor("black"))
    painter.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 32))
    painter.drawText(30, 65, "토마데스크 한글 인식")
    painter.drawText(30, 145, "Hello Windows 12345")
    painter.end()
    result, errors = [], []
    def work():
        try:
            result.append(backend.recognize(image))
        except Exception as exc:
            errors.append(repr(exc))
    worker = threading.Thread(target=work)
    worker.start()
    worker.join(20)
    assert not worker.is_alive()
    assert not errors, errors
    QFontDatabase.removeApplicationFont(font_id)
    # Native OCR is not exact transcription: Korean recognition can confuse
    # Latin l/I. Assert the Korean and numeric fixture, not perfect English.
    assert "12345" in result[0] and "토마데스크" in result[0], result
