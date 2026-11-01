"""Camera capture thread -> landmarks. Latest-frame-wins so latency never accumulates."""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from engine.face.landmarker import FaceLandmarker


@dataclass
class CameraInfo:
    index: int
    ok: bool
    detail: str = ""


def probe_cameras(max_index: int = 4) -> list[CameraInfo]:
    import cv2

    out = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(i)
        ok = cap.isOpened()
        cap.release()
        if ok:
            out.append(CameraInfo(i, True))
    return out


class CameraSource:
    """Implements ``LandmarkSource`` for a real webcam. Frames stay in memory and are never persisted."""

    def __init__(self, index: int = 0, width: int = 640, height: int = 480, fps: int = 30,
                 landmarker: FaceLandmarker | None = None, on_error: Callable[[str], None] | None = None) -> None:
        import cv2

        self._cv2 = cv2
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera {index} (is it in use, disconnected, or blocked by Windows privacy settings?)")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.landmarker = landmarker or FaceLandmarker()
        self.on_error = on_error
        self._latest: tuple[np.ndarray | None, float] | None = None
        self._seq = 0
        self._read_seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._loop, name="oracle-camera", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        fails = 0
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if not ok:
                fails += 1
                if fails > 30:
                    if self.on_error:
                        self.on_error("camera stopped delivering frames")
                    return
                time.sleep(0.03)
                continue
            fails = 0
            t = time.monotonic() - self._t0
            try:
                lm = self.landmarker.detect(frame, t)
            except Exception as exc:  # model failure must pause, not crash
                if self.on_error:
                    self.on_error(f"landmark detection failed: {exc!r}")
                return
            with self._lock:
                self._latest, self._seq = (lm, t), self._seq + 1

    def read(self) -> tuple[np.ndarray | None, float] | None:
        with self._lock:
            if self._seq == self._read_seq:
                return None
            self._read_seq = self._seq
            return self._latest

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.cap.release()
        self.landmarker.close()
