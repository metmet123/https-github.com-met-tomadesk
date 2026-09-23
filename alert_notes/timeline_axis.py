"""Invertible timeline coordinates. Stored schedule times never change."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TimelineAxis:
    compressed: bool = False
    scale: float = 1.0

    def y(self, minute: float) -> float:
        if not self.compressed:
            return minute
        if minute < 540:
            return minute / 3 * self.scale
        if minute <= 1080:
            return (180 + minute - 540) * self.scale
        return (720 + (minute - 1080) / 3) * self.scale

    def minute(self, y: float) -> float:
        if not self.compressed:
            return y
        y /= self.scale
        if y < 180:
            return y * 3
        if y <= 720:
            return 540 + y - 180
        return 1080 + (y - 720) * 3
