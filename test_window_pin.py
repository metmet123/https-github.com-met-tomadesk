from settings_dialog import HOTKEY_DEFAULTS, HOTKEY_FIELDS
from types import SimpleNamespace
from main_window import (
    MainWindow,
    WINDOW_PIN_HOTKEY,
    WINDOW_PIN_HOTKEY_ID,
    WINDOW_PIN_HOTKEY_SETTING,
)
from window_pin import HWND_NOTOPMOST, HWND_TOPMOST, WindowPinController


class FakeWindowApi:
    def __init__(self):
        self.foreground = 101
        self.live = {101, 202}
        self.classes = {101: "Chrome_WidgetWin_1", 202: "XLMAIN"}
        self.titles = {101: "브라우저", 202: "엑셀"}
        self.calls = []

    def foreground_window(self):
        return self.foreground

    def is_window(self, hwnd):
        return hwnd in self.live

    def window_class(self, hwnd):
        return self.classes.get(hwnd, "")

    def window_title(self, hwnd):
        return self.titles.get(hwnd, "")

    def set_topmost(self, hwnd, pinned):
        self.calls.append((hwnd, HWND_TOPMOST if pinned else HWND_NOTOPMOST))
        return True


def test_toggle_twice_restores_original_state():
    api = FakeWindowApi()
    controller = WindowPinController(api)

    first = controller.toggle_foreground()
    second = controller.toggle_foreground()

    assert (first.changed, first.pinned) == (True, True)
    assert (second.changed, second.pinned) == (True, False)
    assert api.calls == [(101, HWND_TOPMOST), (101, HWND_NOTOPMOST)]
    assert controller.pinned_count == 0


def test_desktop_taskbar_and_own_postit_are_ignored():
    api = FakeWindowApi()
    controller = WindowPinController(api, is_own_postit=lambda hwnd: hwnd == 202)

    for window_class in ("Progman", "WorkerW", "Shell_TrayWnd"):
        api.classes[101] = window_class
        result = controller.toggle(101)
        assert not result.changed

    result = controller.toggle(202)
    assert not result.changed
    assert "포스트잇" in result.message
    assert api.calls == []


def test_closed_windows_are_pruned_from_memory():
    api = FakeWindowApi()
    counts = []
    controller = WindowPinController(api, count_changed=counts.append)
    controller.toggle(101)

    api.live.remove(101)

    assert controller.pinned_count == 0
    assert counts == [1, 0]


def test_shutdown_releases_all_live_windows_and_discards_closed_ones():
    api = FakeWindowApi()
    controller = WindowPinController(api)
    controller.toggle(101)
    controller.toggle(202)
    api.live.remove(202)

    assert controller.shutdown() == 1
    assert controller.pinned_count == 0
    assert api.calls[-1] == (101, HWND_NOTOPMOST)


def test_disabling_controller_releases_pinned_windows():
    api = FakeWindowApi()
    controller = WindowPinController(api)
    controller.toggle(101)

    controller.set_enabled(False)

    assert controller.pinned_count == 0
    assert api.calls[-1] == (101, HWND_NOTOPMOST)
    assert not controller.toggle(101).changed


def test_settings_include_window_pin_hotkey_default():
    assert ("window_pin_hotkey", "창 고정/해제") in HOTKEY_FIELDS
    assert HOTKEY_DEFAULTS["window_pin_hotkey"] == "Ctrl+Alt+T"
    assert WINDOW_PIN_HOTKEY_SETTING == "window_pin_hotkey"
    assert WINDOW_PIN_HOTKEY == "Ctrl+Alt+T"
    assert WINDOW_PIN_HOTKEY_ID < 1000
    assert callable(MainWindow.toggle_foreground_window_pin)


def test_tray_tooltip_keeps_existing_detail_and_adds_pin_count():
    class TrayIcon:
        def setToolTip(self, text):
            self.text = text

    target = SimpleNamespace(
        tray_icon=TrayIcon(),
        _tray_detail_text="D-2 보고서",
        window_pin=SimpleNamespace(pinned_count=2),
    )

    MainWindow._refresh_tray_tooltip(target)

    assert target.tray_icon.text.endswith("D-2 보고서\n고정된 창 2개")
