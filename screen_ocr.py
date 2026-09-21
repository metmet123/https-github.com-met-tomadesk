"""Local Windows OCR; note writes require an explicit, reviewed save action."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
import threading
from datetime import datetime
from ocr_notes import OcrNoteReview, deadline_candidates, note_content

from PyQt6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QTextCursor
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class OcrUnavailable(RuntimeError):
    pass


def preferred_language(tags):
    """Installed Korean first, English fallback; never silently pick another language."""
    for prefix in ("ko", "en"):
        for tag in tags:
            if tag.lower().split("-")[0] == prefix:
                return tag
    raise OcrUnavailable("Windows 한국어 또는 영어 OCR 언어팩이 필요합니다.")


class WindowsOcrBackend:
    @staticmethod
    def _types():
        try:
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
            # Projections for returned collections and async operations must be bundled too.
            import winrt.windows.foundation.collections  # noqa: F401
            import winrt.windows.foundation  # noqa: F401
            import winrt.windows.storage.streams  # noqa: F401
            return OcrEngine, Language, SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
        except (ImportError, OSError) as exc:
            raise OcrUnavailable("OCR 구성 요소가 없습니다. requirements.txt의 Windows OCR 패키지를 설치해 주세요.") from exc

    def availability(self):
        try:
            engine, *_ = self._types()
            tag = preferred_language([item.language_tag for item in engine.available_recognizer_languages])
            return True, "Windows 내장 OCR 사용 가능 · " + tag
        except OcrUnavailable as exc:
            return False, str(exc)
        except Exception:
            return False, "Windows OCR을 초기화하지 못했습니다. 언어팩과 Windows 환경을 확인해 주세요."

    def recognize(self, image):
        async def run():
            engine_type, language_type, bitmap_type, pixel_format, alpha_mode = self._types()
            tag = preferred_language([item.language_tag for item in engine_type.available_recognizer_languages])
            engine = engine_type.try_create_from_language(language_type(tag))
            if engine is None:
                raise OcrUnavailable("선택한 Windows OCR 언어를 초기화하지 못했습니다.")
            if image.isNull():
                raise OcrUnavailable("읽을 화면 영역이 없습니다.")
            limit = engine_type.max_image_dimension
            if image.width() > limit or image.height() > limit:
                raise OcrUnavailable(f"선택 영역이 OCR 최대 크기({limit}px)를 넘었습니다. 영역을 줄여 주세요.")
            # Windows is little endian: Qt ARGB32 bytes are B,G,R,A.
            bgra = image.convertToFormat(QImage.Format.Format_ARGB32)
            data = bytearray(bgra.constBits().asstring(bgra.sizeInBytes()))
            bitmap = bitmap_type(pixel_format.BGRA8, bgra.width(), bgra.height(), alpha_mode.IGNORE)
            try:
                from winrt.windows.storage.streams import Buffer
                buffer = Buffer(len(data))
                buffer.length = len(data)
                memoryview(buffer)[:] = data
                bitmap.copy_from_buffer(buffer)
                result = await engine.recognize_async(bitmap)
                return "\n".join(line.text for line in result.lines)
            finally:
                bitmap.close()
        return asyncio.run(run())


@dataclass
class ScreenFrame:
    geometry: QRect
    image: QImage


def capture_screens():
    frames = []
    for screen in QGuiApplication.screens():
        image = screen.grabWindow(0).toImage()
        if image.isNull():
            raise OcrUnavailable("화면을 캡처하지 못했습니다. 보호된 화면이나 원격 환경을 확인해 주세요.")
        image.setDevicePixelRatio(1.0)
        frames.append(ScreenFrame(QRect(screen.geometry()), image))
    if not frames:
        raise OcrUnavailable("사용 가능한 화면이 없습니다.")
    return frames


def compose_region(frames, selection, max_pixels=32_000_000):
    """Map each screen's logical rectangle to its actual captured pixel size.

    Mixed-DPI screens use independent X/Y ratios. Gaps in Qt's virtual desktop
    remain white, rather than stretching another monitor into that gap.
    """
    selection = selection.normalized()
    pieces = [(f, f.geometry.intersected(selection)) for f in frames]
    pieces = [(f, r) for f, r in pieces if not r.isEmpty()]
    if not pieces or selection.width() < 2 or selection.height() < 2:
        raise OcrUnavailable("글자가 있는 영역을 조금 더 크게 선택해 주세요.")
    scale = max(max(f.image.width() / f.geometry.width(), f.image.height() / f.geometry.height()) for f, _ in pieces)
    width, height = math.ceil(selection.width() * scale), math.ceil(selection.height() * scale)
    if width * height > max_pixels:
        raise OcrUnavailable("선택 영역이 너무 큽니다. 영역을 줄여 주세요.")
    result = QImage(width, height, QImage.Format.Format_RGB32)
    if result.isNull():
        raise OcrUnavailable("화면 영역을 처리할 메모리가 부족합니다.")
    result.fill(Qt.GlobalColor.white)
    painter = QPainter(result)
    try:
        for frame, region in pieces:
            sx, sy = frame.image.width() / frame.geometry.width(), frame.image.height() / frame.geometry.height()
            source = QRectF((region.x() - frame.geometry.x()) * sx, (region.y() - frame.geometry.y()) * sy,
                            region.width() * sx, region.height() * sy)
            target = QRectF((region.x() - selection.x()) * scale, (region.y() - selection.y()) * scale,
                            region.width() * scale, region.height() * scale)
            painter.drawImage(target, frame.image, source)
    finally:
        painter.end()
    return result


class RegionOverlay(QWidget):
    def __init__(self, controller, frame):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.controller = controller
        self.frame = frame
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(frame.geometry)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(self.rect(), self.frame.image)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 105))
        if self.controller.selection is not None:
            rect = self.controller.selection.translated(-self.geometry().topLeft()).intersected(self.rect())
            if not rect.isEmpty():
                painter.save()
                painter.setClipRect(rect)
                painter.drawImage(self.rect(), self.frame.image)
                painter.restore()
                painter.setPen(QPen(QColor("#4ba3ff"), 2))
                painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(20, 30, "글자를 읽을 영역을 끌어서 선택 · Esc 취소")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.controller.origin = event.globalPosition().toPoint()
            self.controller.update_selection(event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.RightButton:
            self.controller.cancel()

    def mouseMoveEvent(self, event):
        if self.controller.origin is not None:
            self.controller.update_selection(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.controller.origin is not None:
            self.controller.update_selection(event.globalPosition().toPoint())
            self.controller.finish_selection()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.controller.cancel()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.controller.selecting:
            self.controller.cancel()
        event.accept()


class OcrResultDialog(QDialog):
    retry_requested = pyqtSignal()

    def __init__(self, parent=None, save_note=None, on_saved=None):
        super().__init__(parent)
        self._save_note = save_note
        self._on_saved = on_saved
        self._result_ready = False
        self._saved = False
        self._saving = False
        self._dismissed = False
        self.recognized_at = datetime.now()
        self._candidates = []
        self.setWindowTitle("화면 글자 따기")
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("인식 결과를 확인하고 수정할 수 있습니다.")
        layout.addWidget(self.editor)
        note_row = QHBoxLayout()
        self.memo_button = QPushButton("메모로 만들기")
        self.memo_button.clicked.connect(lambda: self.save_as_note(False))
        note_row.addWidget(self.memo_button)
        self.deadline_button = QPushButton("D-Day로 만들기")
        self.deadline_button.clicked.connect(lambda: self.save_as_note(True))
        note_row.addWidget(self.deadline_button)
        self.dismiss_button = QPushButton("날짜 제안 숨기기")
        self.dismiss_button.clicked.connect(self.dismiss_suggestion)
        note_row.addWidget(self.dismiss_button)
        note_row.addStretch()
        layout.addLayout(note_row)
        row = QHBoxLayout()
        self.copy_button = QPushButton("복사")
        self.copy_button.clicked.connect(self.copy_text)
        row.addWidget(self.copy_button)
        join = QPushButton("줄바꿈을 공백으로")
        join.clicked.connect(self.join_lines)
        row.addWidget(join)
        original = QPushButton("인식 원문 복원")
        original.clicked.connect(lambda: self.editor.setPlainText(self.original))
        row.addWidget(original)
        retry = QPushButton("다시 인식")
        retry.clicked.connect(self.retry_requested.emit)
        row.addWidget(retry)
        close = QPushButton("닫기")
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self.original = ""
        self.editor.textChanged.connect(lambda: self.copy_button.setEnabled(bool(self.editor.toPlainText().strip())))
        self.copy_button.setEnabled(False)
        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(200)
        self._parse_timer.timeout.connect(self.refresh_note_actions)
        self.editor.textChanged.connect(self._text_changed)
        self.refresh_note_actions()

    def display(self, text, error=False):
        self._result_ready = not error
        self._saved = self._saving = self._dismissed = False
        self.recognized_at = datetime.now()
        self.original = "" if error else text
        self.editor.setPlainText(self.original)
        if error:
            self.status.setText(text)
        elif text.strip():
            self.copy_text()
        else:
            self.status.setText("인식된 글자가 없습니다. 기존 클립보드는 유지했습니다.")
        self.refresh_note_actions()
        self.show()
        self.raise_()
        self.activateWindow()

    def copy_text(self):
        text = self.editor.toPlainText()
        if text.strip():
            QApplication.clipboard().setText(text)
            self.status.setText("클립보드에 복사했습니다. 내용을 수정한 뒤 다시 복사할 수 있습니다.")

    def join_lines(self):
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(self.editor.toPlainText().replace("\n", " "))
        cursor.endEditBlock()
        self.status.setText("줄바꿈을 공백으로 바꿨습니다. 확인 후 복사를 누르세요.")

    def _text_changed(self):
        self.deadline_button.setEnabled(False)
        self._parse_timer.start()

    def refresh_note_actions(self):
        self._parse_timer.stop()
        text = self.editor.toPlainText()
        available = self._save_note is not None and self._result_ready and not self._saved and not self._saving and bool(text.strip())
        self.memo_button.setEnabled(available)
        self._candidates = deadline_candidates(text, self.recognized_at) if available and not self._dismissed else []
        self.deadline_button.setVisible(bool(self._candidates))
        self.deadline_button.setEnabled(bool(self._candidates))
        self.dismiss_button.setVisible(bool(self._candidates))

    def dismiss_suggestion(self):
        self._dismissed = True
        self.refresh_note_actions()

    def save_as_note(self, with_deadline=False):
        self.refresh_note_actions()
        if not self.memo_button.isEnabled() or (with_deadline and not self._candidates):
            return
        text = self.editor.toPlainText()
        self._saving = True
        review = OcrNoteReview(text, self._candidates if with_deadline else (), self)
        try:
            if review.exec() != QDialog.DialogCode.Accepted:
                if with_deadline:
                    self._dismissed = True
                return
            title, body, due = review.values()
            try:
                note_id = self._save_note(title, note_content(body), d_day_at=due)
            except Exception:
                self.status.setText("저장하지 못했습니다. 인식 내용은 유지했습니다. 저장 위치를 확인한 뒤 다시 시도하세요.")
                return
            # Mark success before UI refresh: a refresh failure must not retry INSERT.
            self._saved = True
            self.status.setText(f"새 메모를 저장했습니다 (번호 {note_id}). 같은 인식 결과는 중복 저장하지 않습니다.")
            try:
                if self._on_saved is not None:
                    self._on_saved(note_id)
            except Exception:
                self.status.setText(f"메모 {note_id}는 저장됐지만 목록 갱신에 실패했습니다. 메모 목록을 다시 열어 주세요.")
        finally:
            review.deleteLater()
            self._saving = False
            self.refresh_note_actions()


class ScreenOcrController(QObject):
    """Only the worker touches WinRT; Qt widgets/clipboard stay on the GUI thread.

    Daemon worker carries no QObject reference. On cancel/exit its eventual
    result is discarded; no QThread can be destroyed while still running.
    """
    def __init__(self, parent=None, backend=None, capture=None, can_start=None, save_note=None, on_saved=None):
        super().__init__(parent)
        self.backend = backend or WindowsOcrBackend()
        self.capture = capture or capture_screens
        self.can_start = can_start or (lambda: True)
        self.dialog = OcrResultDialog(parent, save_note=save_note, on_saved=on_saved)
        self.dialog.retry_requested.connect(self.retry)
        self.dialog.finished.connect(lambda _: self.cancel())
        self.frames = []
        self.overlays = []
        self.origin = None
        self.selection = None
        self.selecting = False
        self.pending = False
        self._worker = None
        self._outcome = None
        self._cancelled = False
        self._closed = False
        self._starting = False
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._poll)
        QGuiApplication.instance().applicationStateChanged.connect(self._application_state)

    @property
    def busy(self):
        return self.selecting or self.pending or self._starting

    def start(self):
        if self._closed or self.busy or not self.can_start():
            return False
        ready, message = self.backend.availability()
        if not ready:
            self.dialog.display(message, error=True)
            return False
        self.dialog.hide()
        self._starting = True
        # Let hidden result window leave the compositor before taking a snapshot.
        QTimer.singleShot(120, self._begin_capture)
        return True

    def _begin_capture(self):
        if self._closed or not self._starting:
            return
        self._starting = False
        if not self.can_start():
            return
        try:
            self.frames = self.capture()
            if not self.frames:
                raise OcrUnavailable("사용 가능한 화면이 없습니다.")
            self.origin = self.selection = None
            self.selecting = True
            self.overlays = [RegionOverlay(self, frame) for frame in self.frames]
            for overlay in self.overlays:
                overlay.show()
                overlay.raise_()
            self.overlays[0].activateWindow()
        except Exception as exc:
            self._clear_overlays()
            self.dialog.display(str(exc) if isinstance(exc, OcrUnavailable) else "화면을 캡처하지 못했습니다.", error=True)

    def update_selection(self, point):
        if self.origin is not None:
            self.selection = QRect(self.origin, point).normalized()
            for overlay in self.overlays:
                overlay.update()

    def _clear_overlays(self):
        self.selecting = False
        overlays, self.overlays = self.overlays, []
        for overlay in overlays:
            overlay.hide()
            overlay.close()
            overlay.deleteLater()
        self.frames = []
        self.origin = self.selection = None

    def finish_selection(self):
        try:
            image = compose_region(self.frames, self.selection or QRect())
        except Exception as exc:
            self._clear_overlays()
            self.dialog.display(str(exc) if isinstance(exc, OcrUnavailable) else "선택 영역을 처리하지 못했습니다.", error=True)
            return
        self._clear_overlays()
        self.recognize_image(image)

    def recognize_image(self, image):
        if self.pending or self._closed:
            return False
        self.pending = True
        self._cancelled = False
        self.dialog.display("글자를 읽고 있습니다. 닫으면 결과를 버립니다.", error=True)
        # Independent handoff box: worker never calls or owns a Qt object.
        outcome = []
        backend = self.backend
        def work():
            try:
                outcome.append((backend.recognize(image), False))
            except Exception as exc:
                outcome.append((str(exc) if isinstance(exc, OcrUnavailable) else "글자 인식에 실패했습니다. 영역과 Windows 언어팩을 확인해 주세요.", True))
        self._outcome = outcome
        self._worker = threading.Thread(target=work, daemon=True, name="tomadesk-local-ocr")
        self._worker.start()
        self.timer.start()
        return True

    def _poll(self):
        if self._worker is None or self._worker.is_alive():
            return
        self.timer.stop()
        self.pending = False
        result = self._outcome
        self._outcome = self._worker = None
        if not self._closed and not self._cancelled and result:
            self.dialog.display(*result[0])

    def retry(self):
        if not self.busy:
            self.start()

    def _application_state(self, state):
        if state == Qt.ApplicationState.ApplicationInactive and self.selecting:
            self.cancel()

    def cancel(self):
        self._starting = False
        self._cancelled = True
        self._clear_overlays()

    def shutdown(self):
        self._closed = True
        self.cancel()
        self.timer.stop()
        self.dialog.hide()
