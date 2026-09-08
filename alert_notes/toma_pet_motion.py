"""Codex GPT pet animation timing and pointer reaction contract."""

from __future__ import annotations

import ctypes
import math
import sys
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QCursor

from .toma_pet_assets import ACTION_ROWS, TomaSpriteAtlas


@dataclass(frozen=True)
class AnimationSpec:
    frame_durations: tuple[int, ...]


# Timings extracted from the current Codex GPT pet runtime.  Project-facing
# names retain the older Python API while mapping to Codex states 1:1.
ANIMATION_SPECS = {
    "idle": AnimationSpec((280, 110, 110, 140, 140, 320)),
    "running_right": AnimationSpec((120, 120, 120, 120, 120, 120, 120, 220)),
    "running_left": AnimationSpec((120, 120, 120, 120, 120, 120, 120, 220)),
    "waving": AnimationSpec((140, 140, 140, 280)),
    "jumping": AnimationSpec((140, 140, 140, 140, 280)),
    "failed": AnimationSpec((140, 140, 140, 140, 140, 140, 140, 240)),
    "waiting": AnimationSpec((150, 150, 150, 150, 150, 260)),
    "working": AnimationSpec((120, 120, 120, 120, 120, 220)),
    "reviewing": AnimationSpec((150, 150, 150, 150, 150, 280)),
}

DEFAULT_REACTION_CYCLES = 3
SLOW_IDLE_MULTIPLIER = 6
POINTER_RADIUS = 260


def windows_reduced_motion() -> bool:
    """Return the Windows client-animation accessibility preference."""
    if sys.platform != "win32":
        return False
    enabled = ctypes.c_int(1)
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
    except (AttributeError, OSError):
        return False
    return bool(ok) and not bool(enabled.value)


class TomaMotionPlayer(QObject):
    """Drive one sprite label using the exact GPT pet frame cadence."""

    state_changed = pyqtSignal(str)

    def __init__(self, target, atlas: TomaSpriteAtlas | None = None, parent=None, *, reduced_motion=None):
        super().__init__(parent or target)
        self.target = target
        self.atlas = atlas or TomaSpriteAtlas()
        self.reduced_motion = windows_reduced_motion() if reduced_motion is None else bool(reduced_motion)
        self.current_action = "idle"
        self.frame_index = 0
        self.completed_cycles = 0
        self.target_cycles: int | None = None
        self.slow_idle = True
        self.paused = False
        self._pause_override_active = False
        self.dragging = False
        self._hovered = False
        self._showing_look = False
        self.frame_timer = QTimer(self)
        self.frame_timer.setSingleShot(True)
        self.frame_timer.timeout.connect(self._advance_frame)
        self.pointer_timer = QTimer(self)
        self.pointer_timer.setInterval(60)
        self.pointer_timer.timeout.connect(self._update_pointer_reaction)
        self.pointer_timer.start()
        self._render_action_frame()
        self._schedule_current_frame()

    def play(self, action: str, cycles: int = DEFAULT_REACTION_CYCLES, *, override_pause: bool = False) -> None:
        resolved = action if action in ANIMATION_SPECS and action in ACTION_ROWS else "idle"
        if self.paused and not override_pause:
            return
        self._pause_override_active = bool(self.paused and override_pause)
        self.current_action = resolved
        self.frame_index = 0
        self.completed_cycles = 0
        self.target_cycles = max(1, int(cycles)) if resolved != "idle" else None
        self.slow_idle = resolved == "idle"
        self._showing_look = False
        self.state_changed.emit(resolved)
        self.frame_timer.stop()
        self._render_action_frame()
        if self.reduced_motion and resolved != "idle":
            self.frame_timer.start(700)
        else:
            self._schedule_current_frame()

    def play_loop(self, action: str) -> None:
        resolved = action if action in ANIMATION_SPECS and action in ACTION_ROWS else "idle"
        if self.paused:
            return
        self.current_action = resolved
        self.frame_index = 0
        self.completed_cycles = 0
        self.target_cycles = None
        self.slow_idle = resolved == "idle"
        self._showing_look = False
        self.state_changed.emit(resolved)
        self.frame_timer.stop()
        self._render_action_frame()
        self._schedule_current_frame()

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self.frame_timer.stop()
        if self.paused:
            self.current_action = "idle"
            self.frame_index = 0
            self.target.setPixmap(self._scaled(self.atlas.neutral_frame()))
            self.state_changed.emit("paused")
        else:
            self._enter_slow_idle()

    def begin_drag(self, direction: str) -> None:
        self.dragging = True
        if not self.paused:
            self.play_loop("running_right" if direction == "right" else "running_left")

    def update_drag_direction(self, direction: str) -> None:
        if not self.dragging or self.paused:
            return
        action = "running_right" if direction == "right" else "running_left"
        if self.current_action != action:
            self.play_loop(action)

    def end_drag(self) -> None:
        self.dragging = False
        if self.paused:
            self.target.setPixmap(self._scaled(self.atlas.neutral_frame()))
        else:
            self._enter_slow_idle()

    def stop(self) -> None:
        self.frame_timer.stop()
        self.pointer_timer.stop()

    def _advance_frame(self) -> None:
        if self.paused and not self._pause_override_active:
            return
        if self.reduced_motion and self.current_action != "idle":
            self._enter_slow_idle(static=True)
            return
        spec = ANIMATION_SPECS[self.current_action]
        self.frame_index += 1
        if self.frame_index >= len(spec.frame_durations):
            self.frame_index = 0
            if self.current_action != "idle":
                self.completed_cycles += 1
                if self.target_cycles is not None and self.completed_cycles >= self.target_cycles:
                    self._enter_slow_idle()
                    return
        self._render_action_frame()
        self._schedule_current_frame()

    def _enter_slow_idle(self, *, static: bool = False) -> None:
        self.current_action = "idle"
        self.frame_index = 0
        self.completed_cycles = 0
        self.target_cycles = None
        self.slow_idle = True
        self._showing_look = False
        self._pause_override_active = False
        self.state_changed.emit("idle")
        if static or self.reduced_motion or self.paused:
            self.frame_timer.stop()
            self.target.setPixmap(self._scaled(self.atlas.neutral_frame()))
            return
        self._render_action_frame()
        self._schedule_current_frame()

    def _schedule_current_frame(self) -> None:
        duration = ANIMATION_SPECS[self.current_action].frame_durations[self.frame_index]
        if self.current_action == "idle" and self.slow_idle:
            duration *= SLOW_IDLE_MULTIPLIER
        self.frame_timer.start(duration)

    def _render_action_frame(self) -> None:
        frame = self.atlas.action_frame(self.current_action, self.frame_index)
        self.target.setPixmap(self._scaled(frame))

    def _update_pointer_reaction(self) -> None:
        if self.paused or self.dragging or not self.target.isVisible():
            return
        center = self.target.mapToGlobal(self.target.rect().center())
        cursor = QCursor.pos()
        hovered = self.target.rect().contains(self.target.mapFromGlobal(cursor))
        if hovered and not self._hovered and self.current_action == "idle":
            self._hovered = True
            self.play("jumping")
            return
        self._hovered = hovered
        if hovered or self.current_action != "idle":
            return
        distance = math.hypot(cursor.x() - center.x(), cursor.y() - center.y())
        if distance <= POINTER_RADIUS:
            angle = (math.degrees(math.atan2(cursor.x() - center.x(), -(cursor.y() - center.y()))) + 360) % 360
            self.target.setPixmap(self._scaled(self.atlas.look_frame(round(angle / 22.5) % 16)))
            self._showing_look = True
        elif self._showing_look:
            self._showing_look = False
            self._render_action_frame()

    def _scaled(self, pixmap):
        return pixmap.scaled(
            self.target.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
