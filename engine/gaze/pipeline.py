"""Gaze -> cursor pipeline with a pluggable estimator (future: dedicated eye-tracker)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from engine.safety import SafetyController

from .calibration import GazeCalibration
from .dwell import DwellDetector, DwellState
from .filters import PointFilter
from .monitors import Monitor


class GazeEstimator(Protocol):
    """Swap-in point for better algorithms or eye-tracking hardware."""

    def estimate(self, features: np.ndarray) -> tuple[float, float]:
        """Return normalised (0..1) monitor coordinates."""


class CalibratedEstimator:
    def __init__(self, calibration: GazeCalibration) -> None:
        self.calibration = calibration

    def estimate(self, features: np.ndarray) -> tuple[float, float]:
        return self.calibration.predict(features)


@dataclass(frozen=True)
class GazeSample:
    x: int
    y: int
    quality: float
    reliable: bool
    dwell: DwellState


class GazeCursorPipeline:
    def __init__(self, estimator: GazeEstimator, monitor: Monitor, safety: SafetyController,
                 smoothing_cutoff: float = 1.0, dwell: DwellDetector | None = None,
                 min_quality: float = 0.5, deadzone_px: float = 6.0) -> None:
        self.estimator, self.monitor, self.safety = estimator, monitor, safety
        self.filter = PointFilter(smoothing_cutoff)
        self.dwell = dwell or DwellDetector()
        self.min_quality = min_quality
        self.deadzone_px = deadzone_px
        self._last: tuple[int, int] | None = None

    def process(self, features: np.ndarray | None, quality: float, t: float) -> GazeSample | None:
        """Returns None when there is nothing trustworthy to act on."""
        self.safety.report_tracking_quality(quality)
        reliable = features is not None and quality >= self.min_quality and self.safety.is_execution_allowed()
        if not reliable:
            self.dwell.reset()
            self.filter.reset()  # avoid a cursor jump when tracking returns
            return None
        nx, ny = self.estimator.estimate(features)  # type: ignore[arg-type]
        fx, fy = self.filter(nx, ny, t)
        px, py = self.monitor.to_pixels(fx, fy)
        if self._last and abs(px - self._last[0]) <= self.deadzone_px and abs(py - self._last[1]) <= self.deadzone_px:
            px, py = self._last  # hold position inside the jitter dead-zone
        self._last = (px, py)
        return GazeSample(px, py, quality, True, self.dwell.update(px, py, t))
