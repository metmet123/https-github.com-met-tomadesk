import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from shortcut_overlay import (
    GROUP_ACTIONS,
    GROUP_COMMON,
    GROUP_CONTENT,
    ShortcutOverlay,
    ShortcutOverlayEntry,
)


_APP = QApplication.instance() or QApplication([])


def _app():
    return _APP


def _fixture_entries():
    groups = (GROUP_COMMON, GROUP_CONTENT, GROUP_ACTIONS)
    entries = [
        ShortcutOverlayEntry(groups[index % 3], f"성공 {index}", f"Ctrl+Alt+F{index}")
        for index in range(30)
    ]
    entries.extend(
        ShortcutOverlayEntry(GROUP_COMMON, f"실패 {index}", f"Alt+실패{index}", registered=False)
        for index in range(3)
    )
    entries.extend(
        ShortcutOverlayEntry(GROUP_ACTIONS, f"비활성 {index}", f"Alt+꺼짐{index}", active=False)
        for index in range(2)
    )
    return entries


def _close(overlay):
    overlay.hide()
    overlay.deleteLater()
    _app().processEvents()


def test_only_active_successes_are_listed_and_failure_count_is_summarized():
    overlay = ShortcutOverlay()
    try:
        overlay.set_entries(_fixture_entries())

        assert len(overlay.listed_entries) == 30
        assert len(overlay.item_buttons) == 30
        assert overlay.failure_label.text() == "등록 실패 3개"
        shown = "\n".join(button.text() for button in overlay.item_buttons)
        assert "Alt+실패" not in shown
        assert "Alt+꺼짐" not in shown
        assert "Alt+실패" not in overlay.failure_label.text()
    finally:
        _close(overlay)


def test_overlay_does_not_open_for_excluded_foreground_app():
    overlay = ShortcutOverlay()
    try:
        assert not overlay.open_overlay(_fixture_entries(), excluded_app=True)
        assert not overlay.isVisible()
    finally:
        _close(overlay)


def test_overlay_does_not_open_during_recording_or_playback():
    for state in ({"recording": True}, {"playback": True}):
        overlay = ShortcutOverlay()
        try:
            assert not overlay.open_overlay(_fixture_entries(), **state)
            assert not overlay.isVisible()
        finally:
            _close(overlay)


def test_escape_closes_overlay():
    app = _app()
    overlay = ShortcutOverlay()
    try:
        assert overlay.open_overlay(_fixture_entries(), available_geometry=QRect(0, 0, 1366, 768))
        app.processEvents()
        QTest.keyClick(overlay, Qt.Key.Key_Escape)
        app.processEvents()
        assert not overlay.isVisible()
    finally:
        _close(overlay)


def test_focus_loss_closes_overlay():
    app = _app()
    overlay = ShortcutOverlay()
    try:
        assert overlay.open_overlay(_fixture_entries(), available_geometry=QRect(0, 0, 1366, 768))
        app.processEvents()
        QApplication.sendEvent(overlay, QEvent(QEvent.Type.WindowDeactivate))
        app.processEvents()
        assert not overlay.isVisible()
    finally:
        _close(overlay)


def test_1366_by_768_geometry_stays_on_screen_and_long_content_scrolls():
    app = _app()
    screen = QRect(0, 0, 1366, 768)
    overlay = ShortcutOverlay()
    try:
        assert overlay.open_overlay(_fixture_entries(), available_geometry=screen)
        app.processEvents()
        geometry = overlay.geometry()
        assert screen.contains(geometry.topLeft())
        assert screen.contains(geometry.bottomRight())
        assert overlay.scroll.viewport().height() <= overlay.scroll.widget().sizeHint().height()
        assert overlay.scroll.horizontalScrollBar().maximum() == 0
    finally:
        _close(overlay)
