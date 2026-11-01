"""MediaPipe Face Landmarker wrapper -> (478, 3) normalised landmarks, or None when no face."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Protocol

import numpy as np


class LandmarkSource(Protocol):
    """Anything that yields landmarks per frame: the real camera, a replay, or a simulator."""

    def read(self) -> tuple[np.ndarray | None, float] | None:
        """Return (landmarks_or_None, timestamp_s), or None if no new frame is available."""

    def close(self) -> None: ...


def find_model_path() -> Path:
    candidates = [os.environ.get("ORACLE_MODEL_PATH", ""), str(Path(getattr(sys, "_MEIPASS", ".")) / "models" / "face_landmarker.task"),
                  str(Path(__file__).resolve().parents[2] / "models" / "face_landmarker.task")]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    raise FileNotFoundError("face_landmarker.task not found; run scripts/fetch_models.py (build step) or set ORACLE_MODEL_PATH")


class FaceLandmarker:
    def __init__(self, model_path: str | Path | None = None) -> None:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        opts = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path or find_model_path())),
            running_mode=vision.RunningMode.VIDEO, num_faces=1, min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5, min_tracking_confidence=0.5)
        self._lm = vision.FaceLandmarker.create_from_options(opts)
        self._last_ms = -1

    def detect(self, frame_bgr: np.ndarray, t_s: float) -> np.ndarray | None:
        import cv2

        ms = max(int(t_s * 1000), self._last_ms + 1)  # VIDEO mode needs strictly increasing timestamps
        self._last_ms = ms
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        res = self._lm.detect_for_video(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb), ms)
        if not res.face_landmarks:
            return None
        pts = res.face_landmarks[0]
        return np.array([[p.x, p.y, p.z] for p in pts], dtype=float)

    def close(self) -> None:
        self._lm.close()
