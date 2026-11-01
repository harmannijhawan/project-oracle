"""Dwell selection: fire only after gaze rests inside a radius for the configured time."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DwellState:
    progress: float  # 0..1
    fired: bool
    anchor: tuple[float, float] | None


class DwellDetector:
    def __init__(self, duration_s: float = 1.0, radius_px: float = 60.0, cooldown_s: float = 1.0) -> None:
        self.duration_s, self.radius_px, self.cooldown_s = duration_s, radius_px, cooldown_s
        self._anchor: tuple[float, float] | None = None
        self._start = 0.0
        self._cooldown_until = -math.inf

    def reset(self) -> None:
        self._anchor = None

    def update(self, x: float, y: float, t: float, tracking_ok: bool = True) -> DwellState:
        if not tracking_ok:  # never accumulate dwell through a tracking loss
            self.reset()
            return DwellState(0.0, False, None)
        if t < self._cooldown_until:
            return DwellState(0.0, False, None)
        if self._anchor is None or math.dist(self._anchor, (x, y)) > self.radius_px:
            self._anchor, self._start = (x, y), t
            return DwellState(0.0, False, self._anchor)
        progress = min((t - self._start) / self.duration_s, 1.0)
        if progress >= 1.0:
            anchor = self._anchor
            self._anchor = None
            self._cooldown_until = t + self.cooldown_s  # no immediate repeat on the same spot
            return DwellState(1.0, True, anchor)
        return DwellState(progress, False, self._anchor)
