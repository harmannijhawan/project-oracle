"""Facial feature extraction from MediaPipe Face Landmarker landmarks (478 points, with iris).

All distances are normalised by inter-ocular distance so features are invariant to the
user's distance from the camera. Head pose here is a geometric approximation from
landmarks; when MediaPipe's facial transformation matrix is available prefer it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# MediaPipe FaceMesh indices
L_EYE = dict(outer=33, inner=133, upper1=160, upper2=158, lower1=144, lower2=153)
R_EYE = dict(outer=263, inner=362, upper1=387, upper2=385, lower1=373, lower2=380)
L_IRIS, R_IRIS = 468, 473
L_BROW, R_BROW = (105, 66), (334, 296)
L_BROW_INNER, R_BROW_INNER = 107, 336
MOUTH_UP, MOUTH_LOW, MOUTH_L, MOUTH_R = 13, 14, 61, 291
NOSE_TIP, CHIN, FOREHEAD, CHEEK_L, CHEEK_R = 1, 152, 10, 234, 454

FEATURE_NAMES = [
    "ear_left", "ear_right", "brow_raise_left", "brow_raise_right", "brow_furrow",
    "mouth_open", "mouth_width", "jaw_open", "yaw", "pitch", "roll",
    "iris_x_left", "iris_y_left", "iris_x_right", "iris_y_right",
]


def _d(p: np.ndarray, a: int, b: int) -> float:
    return float(np.linalg.norm(p[a, :2] - p[b, :2]))


def _ear(p: np.ndarray, e: dict[str, int]) -> float:
    horiz = _d(p, e["outer"], e["inner"])
    return (_d(p, e["upper1"], e["lower1"]) + _d(p, e["upper2"], e["lower2"])) / (2 * horiz + 1e-9)


def _iris_rel(p: np.ndarray, iris: int, e: dict[str, int]) -> tuple[float, float]:
    """Iris centre relative to the eye corners/lids, in [-1, 1] roughly. The core gaze signal."""
    outer, inner = p[e["outer"], :2], p[e["inner"], :2]
    axis = inner - outer
    length = np.linalg.norm(axis) + 1e-9
    u = axis / length
    if u[0] < 0:  # orient left->right in the image so +x means "iris toward image right" for both eyes
        u = -u
    centre = (outer + inner) / 2
    off = p[iris, :2] - centre
    x = float(off @ u) / (length / 2)
    perp = np.array([-u[1], u[0]])
    y = float(off @ perp) / (length / 2)
    return x, y


def head_pose_from_landmarks(p: np.ndarray) -> tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees, approximate. Positive yaw = face turned toward image right."""
    cl, cr, nose, chin, fore = p[CHEEK_L, :2], p[CHEEK_R, :2], p[NOSE_TIP, :2], p[CHIN, :2], p[FOREHEAD, :2]
    mid = (cl + cr) / 2
    width = np.linalg.norm(cr - cl) + 1e-9
    yaw = math.degrees(math.asin(float(np.clip((nose[0] - mid[0]) / (width / 2), -1, 1))))
    face_h = np.linalg.norm(chin - fore) + 1e-9
    vmid = (chin[1] + fore[1]) / 2
    pitch = math.degrees(math.asin(float(np.clip((nose[1] - vmid) / (face_h / 2), -1, 1))))
    roll = math.degrees(math.atan2(cr[1] - cl[1], cr[0] - cl[0]))
    return yaw, pitch, roll


def extract_frame_features(p: np.ndarray) -> dict[str, float]:
    """p: (N>=468, 2|3) normalised landmarks. Returns FEATURE_NAMES -> value (iris needs N>=478)."""
    p = np.asarray(p, float)
    if p.ndim != 2 or p.shape[0] < 478 or p.shape[1] < 2:
        raise ValueError("expected landmarks of shape (>=478, 2|3) including iris points")
    iod = _d(p, L_EYE["outer"], R_EYE["outer"]) + 1e-9
    brow_l = np.mean([p[i, 1] for i in L_BROW]); brow_r = np.mean([p[i, 1] for i in R_BROW])
    eye_l_y = np.mean([p[L_EYE["upper1"], 1], p[L_EYE["upper2"], 1]])
    eye_r_y = np.mean([p[R_EYE["upper1"], 1], p[R_EYE["upper2"], 1]])
    yaw, pitch, roll = head_pose_from_landmarks(p)
    ixl, iyl = _iris_rel(p, L_IRIS, L_EYE)
    ixr, iyr = _iris_rel(p, R_IRIS, R_EYE)
    return {
        "ear_left": _ear(p, L_EYE), "ear_right": _ear(p, R_EYE),
        "brow_raise_left": float(eye_l_y - brow_l) / iod, "brow_raise_right": float(eye_r_y - brow_r) / iod,
        "brow_furrow": _d(p, L_BROW_INNER, R_BROW_INNER) / iod,
        "mouth_open": _d(p, MOUTH_UP, MOUTH_LOW) / iod, "mouth_width": _d(p, MOUTH_L, MOUTH_R) / iod,
        "jaw_open": _d(p, NOSE_TIP, CHIN) / iod,
        "yaw": yaw, "pitch": pitch, "roll": roll,
        "iris_x_left": ixl, "iris_y_left": iyl, "iris_x_right": ixr, "iris_y_right": iyr,
    }


def gaze_feature_vector(f: dict[str, float]) -> np.ndarray:
    """Input to GazeCalibration: mean iris offset + head pose (head movement shifts the mapping)."""
    return np.array([(f["iris_x_left"] + f["iris_x_right"]) / 2, (f["iris_y_left"] + f["iris_y_right"]) / 2,
                     f["yaw"] / 30.0, f["pitch"] / 30.0])


@dataclass
class BlinkEvent:
    start: float
    duration: float
    deliberate: bool


class BlinkDetector:
    """EAR-threshold blink detection. Involuntary blinks are ~0.1-0.4 s; a *deliberate*
    gesture must exceed ``deliberate_min_s`` so ordinary blinking never triggers anything."""

    def __init__(self, closed_ratio: float = 0.6, deliberate_min_s: float = 0.6, max_s: float = 3.0) -> None:
        self.closed_ratio, self.deliberate_min_s, self.max_s = closed_ratio, deliberate_min_s, max_s
        self.open_ear: float | None = None  # personal open-eye level (EMA)
        self._closed_at: float | None = None

    def update(self, ear: float, t: float) -> BlinkEvent | None:
        if self.open_ear is None:
            self.open_ear = ear
        threshold = self.open_ear * self.closed_ratio
        if ear < threshold:
            if self._closed_at is None:
                self._closed_at = t
            return None
        self.open_ear = 0.98 * self.open_ear + 0.02 * ear  # adapt only while open
        if self._closed_at is None:
            return None
        dur, start, self._closed_at = t - self._closed_at, self._closed_at, None
        if dur > self.max_s:  # eyes were closed (or tracking lost), not a blink
            return None
        return BlinkEvent(start, dur, dur >= self.deliberate_min_s)


@dataclass
class PersonalBaseline:
    """Welford running mean/std per feature -> z-scores relative to *this* person."""

    n: int = 0
    mean: np.ndarray = field(default_factory=lambda: np.zeros(len(FEATURE_NAMES)))
    m2: np.ndarray = field(default_factory=lambda: np.zeros(len(FEATURE_NAMES)))

    def update(self, vec: np.ndarray) -> None:
        self.n += 1
        delta = vec - self.mean
        self.mean = self.mean + delta / self.n
        self.m2 = self.m2 + delta * (vec - self.mean)

    @property
    def std(self) -> np.ndarray:
        return np.sqrt(self.m2 / max(self.n - 1, 1))

    def is_ready(self, min_samples: int = 150) -> bool:
        return self.n >= min_samples

    def zscore(self, vec: np.ndarray) -> np.ndarray:
        if self.n < 2:
            raise ValueError("baseline has too few samples")
        return (vec - self.mean) / np.maximum(self.std, 1e-6)

    def to_dict(self) -> dict:
        return {"n": self.n, "mean": self.mean.tolist(), "m2": self.m2.tolist(), "names": FEATURE_NAMES}

    @classmethod
    def from_dict(cls, d: dict) -> "PersonalBaseline":
        if d.get("names") != FEATURE_NAMES:
            raise ValueError("baseline was built with a different feature set")
        return cls(d["n"], np.array(d["mean"]), np.array(d["m2"]))


def vector(f: dict[str, float]) -> np.ndarray:
    return np.array([f[name] for name in FEATURE_NAMES])


WINDOW_STAT_NAMES = [f"{n}__{s}" for n in FEATURE_NAMES for s in ("mean", "std", "min", "max", "slope")] + [
    "blink_count", "blink_rate_hz", "path_length"]


def summarise_window(frames: np.ndarray, timestamps: np.ndarray, blink_count: int = 0) -> np.ndarray:
    """Temporal summary of a (T, F) window of z-scored frames -> fixed-length vector."""
    frames, timestamps = np.asarray(frames, float), np.asarray(timestamps, float)
    if frames.ndim != 2 or frames.shape[1] != len(FEATURE_NAMES) or len(frames) < 3:
        raise ValueError("window needs >= 3 frames of the full feature set")
    dur = max(float(timestamps[-1] - timestamps[0]), 1e-6)
    tc = timestamps - timestamps.mean()
    slope = (tc[:, None] * (frames - frames.mean(axis=0))).sum(axis=0) / max((tc ** 2).sum(), 1e-9)
    stats = np.stack([frames.mean(0), frames.std(0), frames.min(0), frames.max(0), slope], axis=1).ravel()
    path = float(np.linalg.norm(np.diff(frames, axis=0), axis=1).sum())
    return np.concatenate([stats, [blink_count, blink_count / dur, path]])
