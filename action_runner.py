import json
import os
import re
import time
import webbrowser
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from input_controller import (
    click,
    clipboard_sequence_number,
    drag,
    scroll,
    send_alt_tab,
    send_hotkey,
    send_unicode_text,
    send_virtual_key,
    wait_for_clipboard_change,
    wait_for_modifier_release,
)
from macro_playback_config import (
    validate_playback_speed,
    validate_repeat_count,
    validate_timing_mode,
)
from stop_monitor import StopHotkeyMonitor
from window_restore import restore_minimized_target


class ActionRunner:
    def __init__(self, stop_hotkey: str = "Ctrl+Alt+Esc"):
        self.stop_requested = False
        self.stop_monitor = StopHotkeyMonitor(stop_hotkey)

    def set_stop_hotkey(self, hotkey: str) -> None:
        self.stop_monitor.set_hotkey(hotkey)

    def stop(self) -> None:
        self.stop_requested = True

    def _stop_requested(self) -> bool:
        return self.stop_requested or self.stop_monitor.pressed()

    def _raise_if_stopped(self) -> None:
        if self._stop_requested():
            self.stop_requested = True
            raise RuntimeError("사용자가 반복작업을 중지했습니다.")

    def _wait(self, seconds) -> None:
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            self._raise_if_stopped()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.01, remaining))

    def run(self, row) -> str:
        self.stop_requested = False
        payload = json.loads(row["payload"] or "{}")
        handlers = {
            "text": self._run_text,
            "url": self._run_url,
            "path": self._run_path,
            "macro": self._run_macro,
        }
        handler = handlers.get(row["action_type"])
        if handler is None:
            raise ValueError("지원하지 않는 작업 유형입니다.")
        result = handler(payload)
        if row["action_type"] == "macro":
            return f"실행 완료 · {result}회 반복"
        return "실행 완료"

    def _run_text(self, payload: dict) -> None:
        self._paste_text(payload.get("text", ""), bool(payload.get("press_enter", True)))

    def _run_url(self, payload: dict) -> None:
        url = payload.get("url", "").strip()
        if not url:
            raise ValueError("URL이 비어 있습니다.")
        webbrowser.open(url)

    def _run_path(self, payload: dict) -> None:
        target = payload.get("path", "").strip()
        if not target or not Path(target).exists():
            raise ValueError("파일 또는 폴더 경로를 확인해 주세요.")
        if bool(payload.get("restore_if_minimized", False)) and restore_minimized_target(target):
            return
        os.startfile(target)

    def _run_macro(self, payload: dict) -> int:
        steps = payload.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError("매크로 단계 형식이 올바르지 않습니다.")
        timing_mode = validate_timing_mode(payload.get("timing_mode", "scaled"))
        repeat_count = validate_repeat_count(payload.get("repeat_count", 1))
        speed = 1.0 if timing_mode == "recorded" else payload.get("playback_speed", 1.0)
        for _iteration in range(repeat_count):
            self._raise_if_stopped()
            if timing_mode == "fixed":
                self._run_macro_with_fixed_delay(steps, payload.get("fixed_delay_seconds", 0.3))
            else:
                self._run_macro_with_speed(steps, speed)
        return repeat_count

    def _run_macro_with_speed(self, steps: list[dict], speed) -> None:
        factor = validate_playback_speed(speed)
        for step in steps:
            self._raise_if_stopped()
            if step.get("type") == "wait":
                adjusted = dict(step)
                adjusted["seconds"] = float(step.get("seconds", 0.3)) / factor
                self._run_step(adjusted)
            else:
                self._run_step(step, playback_speed=factor)

    def _run_macro_with_fixed_delay(self, steps: list[dict], seconds) -> None:
        """Run meaningful steps with one user-selected gap between each step."""
        try:
            delay = float(seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("고정 대기 시간 형식이 올바르지 않습니다.") from exc
        if not 0.1 <= delay <= 60:
            raise ValueError("고정 대기 시간은 0.10~60.00초여야 합니다.")
        actions = [step for step in steps if step.get("type") != "wait"]
        for index, step in enumerate(actions):
            self._raise_if_stopped()
            if index:
                self._wait(delay)
            self._run_step(step)

    def _run_step(self, step: dict, playback_speed: float = 1.0) -> None:
        kind = step.get("type")
        if kind == "click":
            click(int(step.get("x", 0)), int(step.get("y", 0)), str(step.get("button", "left")))
        elif kind == "drag":
            completed = drag(int(step.get("start_x", 0)), int(step.get("start_y", 0)),
                             int(step.get("end_x", 0)), int(step.get("end_y", 0)),
                             _fast_drag_duration(step.get("duration", 0.2), playback_speed),
                             self._stop_requested)
            if not completed:
                self._raise_if_stopped()
        elif kind == "wheel":
            scroll(
                int(step.get("delta", 0)),
                str(step.get("axis", "vertical")),
                int(step.get("x", 0)),
                int(step.get("y", 0)),
            )
        elif kind == "wait":
            self._wait(float(step.get("seconds", 0.3)))
        elif kind == "text":
            self._type_recorded_text(step.get("text", ""), bool(step.get("press_enter", False)))
        elif kind == "key":
            if _is_alt_tab_step(step):
                send_alt_tab()
                return
            if step.get("vk") is not None:
                vk = int(step["vk"])
                modifiers = [int(value) for value in step.get("modifier_vks", [])]
                if vk in {0x10, 0x11, 0x12, 0x5B, 0x5C, *range(0xA0, 0xA6)} and not modifiers:
                    return
                clipboard_before_copy = clipboard_sequence_number() if _is_copy_step(vk, modifiers) else 0
                if modifiers:
                    send_virtual_key(vk, modifiers)
                else:
                    send_virtual_key(vk)
                if clipboard_before_copy:
                    wait_for_clipboard_change(clipboard_before_copy)
            else:
                self._run_legacy_key_step(str(step.get("key", "Enter")))
        else:
            raise ValueError(f"지원하지 않는 매크로 단계입니다: {kind}")

    def _run_legacy_key_step(self, key: str) -> None:
        """Replay old JSON safely, including recorder artifacts from older builds."""
        match = re.search(r"(?:^|\+)VK_([0-9A-Fa-f]{2})$", key)
        if match:
            vk = int(match.group(1), 16)
            # Old recorder versions accidentally saved left/right modifiers
            # as independent keys. They have no standalone macro action.
            if vk in {0x10, 0x11, 0x12, 0x5B, 0x5C, *range(0xA0, 0xA6)}:
                return
            send_virtual_key(vk)
            return
        send_hotkey(key)

    def _paste_text(self, text: str, press_enter: bool) -> None:
        # WM_HOTKEY can arrive before Ctrl/Alt/Shift/Win key-up messages.
        # Pasting before they are released changes Ctrl+V into another shortcut.
        wait_for_modifier_release()
        clipboard = QApplication.clipboard()
        old_text = clipboard.text()
        clipboard.setText(text)
        time.sleep(0.05)
        send_hotkey("Ctrl+V")
        if press_enter:
            send_hotkey("Enter")
        QTimer.singleShot(300, lambda: clipboard.setText(old_text))

    def _type_recorded_text(self, text: str, press_enter: bool) -> None:
        """Replay recorder text directly so it never turns into an extra paste."""
        wait_for_modifier_release()
        send_unicode_text(text)
        if press_enter:
            send_hotkey("Enter")


def _fast_drag_duration(recorded_duration, playback_speed: float = 1.0) -> float:
    """Use the fastest safe drag duration, leaving room for following waits."""
    try:
        recorded = float(recorded_duration)
        speed = float(playback_speed)
    except (TypeError, ValueError):
        recorded, speed = 0.2, 1.0
    speed = max(0.5, min(speed, 10.0))
    # Keep a substantial speed-up without making browser/grid selections skip
    # intermediate pointer movement.  Macro steps remain synchronous, so any
    # following wait begins only after the mouse button has been released.
    return min(0.35, max(0.12, recorded * 0.35 / speed))


def _is_copy_step(vk: int, modifiers: list[int]) -> bool:
    return int(vk) == 0x43 and 0x11 in {int(value) for value in modifiers}


def _is_alt_tab_step(step: dict) -> bool:
    key = str(step.get("key", "")).replace(" ", "").upper()
    if key == "ALT+TAB":
        return True
    try:
        modifiers = {int(value) for value in step.get("modifier_vks", [])}
        return int(step.get("vk", -1)) == 0x09 and 0x12 in modifiers
    except (TypeError, ValueError):
        return False
