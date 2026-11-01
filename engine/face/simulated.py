"""Synthetic landmark generator for tests and the explicit ``--simulate`` dev mode.

NOT used in production tracking. It builds a geometric face (same indices as MediaPipe) so the real
feature/gaze code can be exercised without a webcam. Gaze is encoded as iris offset.
"""

from __future__ import annotations

import itertools
import threading
import time

import numpy as np

from engine.features import face_features as ff


def synthetic_landmarks(eye_open: float = 0.3, mouth_open: float = 0.05, yaw_shift: float = 0.0,
                        iris_dx: float = 0.0, iris_dy: float = 0.0) -> np.ndarray:
    p = np.zeros((478, 3))

    def eye(e: dict, cx: float, iris: int, sign: int) -> None:
        w = 0.06
        p[e["outer"], :2] = (cx - sign * w, 0.4)
        p[e["inner"], :2] = (cx + sign * w, 0.4)
        h = eye_open * w
        for k in ("upper1", "upper2"):
            p[e[k], :2] = (cx, 0.4 - h)
        for k in ("lower1", "lower2"):
            p[e[k], :2] = (cx, 0.4 + h)
        p[iris, :2] = (cx + iris_dx * w, 0.4 + iris_dy * w)

    eye(ff.L_EYE, 0.38, ff.L_IRIS, -1)
    eye(ff.R_EYE, 0.62, ff.R_IRIS, 1)
    for i in ff.L_BROW + ff.R_BROW:
        p[i, :2] = (0.4, 0.33)
    p[ff.L_BROW_INNER, :2] = (0.46, 0.34)
    p[ff.R_BROW_INNER, :2] = (0.54, 0.34)
    p[ff.MOUTH_UP, :2] = (0.5, 0.65)
    p[ff.MOUTH_LOW, :2] = (0.5, 0.65 + mouth_open)
    p[ff.MOUTH_L, :2] = (0.44, 0.65)
    p[ff.MOUTH_R, :2] = (0.56, 0.65)
    p[ff.NOSE_TIP, :2] = (0.5 + yaw_shift, 0.52)
    p[ff.CHIN, :2] = (0.5, 0.8)
    p[ff.FOREHEAD, :2] = (0.5, 0.25)
    p[ff.CHEEK_L, :2] = (0.3, 0.5)
    p[ff.CHEEK_R, :2] = (0.7, 0.5)
    return p


def gaze_to_iris(tx: float, ty: float) -> tuple[float, float]:
    """The linear iris model the simulator uses for a normalised screen target."""
    return (tx - 0.5) * 1.2, (ty - 0.5) * 0.8


class SimulatedLandmarkSource:
    """``LandmarkSource`` whose 'user' looks wherever ``look_at`` says. Thread-safe."""

    def __init__(self, fps: float = 60.0) -> None:
        self._target = (0.5, 0.5)
        self._face = True
        self._lock = threading.Lock()
        self._t = itertools.count()
        self._dt = 1.0 / fps
        self._last = 0.0

    def look_at(self, tx: float, ty: float) -> None:
        with self._lock:
            self._target = (tx, ty)

    def set_face_present(self, present: bool) -> None:
        with self._lock:
            self._face = present

    def read(self) -> tuple[np.ndarray | None, float] | None:
        now = time.monotonic()
        if now - self._last < self._dt:
            return None
        self._last = now
        with self._lock:
            tx, ty = self._target
            present = self._face
        t = next(self._t) * self._dt
        if not present:
            return None, t
        dx, dy = gaze_to_iris(tx, ty)
        return synthetic_landmarks(iris_dx=dx, iris_dy=dy), t

    def close(self) -> None:
        pass
