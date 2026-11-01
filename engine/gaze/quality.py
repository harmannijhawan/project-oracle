"""Tracking-quality score in [0, 1] from observable signals (no model involved)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class QualityInputs:
    face_detected: bool
    eye_openness: float  # mean EAR (0 closed .. ~0.35 open)
    yaw_deg: float
    pitch_deg: float
    face_width_frac: float  # face width / frame width


class QualityMonitor:
    def __init__(self, window: int = 15, max_yaw: float = 35.0, max_pitch: float = 30.0) -> None:
        self._points: deque[tuple[float, float]] = deque(maxlen=window)
        self.max_yaw, self.max_pitch = max_yaw, max_pitch

    def update(self, q: QualityInputs, gaze_feature_xy: tuple[float, float] | None = None) -> float:
        if not q.face_detected:
            self._points.clear()
            return 0.0
        score = 1.0
        if q.eye_openness < 0.12:  # eyes (nearly) closed: iris unreliable
            score *= 0.3
        score *= max(0.0, 1.0 - max(0.0, abs(q.yaw_deg) - self.max_yaw * 0.5) / (self.max_yaw * 0.5))
        score *= max(0.0, 1.0 - max(0.0, abs(q.pitch_deg) - self.max_pitch * 0.5) / (self.max_pitch * 0.5))
        if q.face_width_frac < 0.15:  # too far: few pixels on the eyes
            score *= q.face_width_frac / 0.15
        if gaze_feature_xy is not None:
            self._points.append(gaze_feature_xy)
            if len(self._points) >= 8:
                spread = float(np.std(np.array(self._points), axis=0).mean())
                if spread > 0.05:  # raw iris signal too noisy
                    score *= max(0.2, 1.0 - (spread - 0.05) * 10)
        return float(min(max(score, 0.0), 1.0))
