"""Nine-point calibration: eye/head feature vector -> normalised monitor coordinates.

Model: ridge-regularised polynomial regression (degree 2). Accuracy is *measured*
by leave-one-out cross-validation on the calibration points and reported in
pixels / degrees-free units; nothing here claims a precision it has not measured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np


def nine_point_targets(margin: float = 0.08) -> list[tuple[float, float]]:
    """3x3 grid in normalised monitor space, inset from the edges."""
    xs = (margin, 0.5, 1 - margin)
    return [(x, y) for y in xs for x in xs]


def _poly(features: np.ndarray) -> np.ndarray:
    f = np.atleast_2d(features)
    n, d = f.shape
    cols = [np.ones((n, 1)), f]
    for i in range(d):
        for j in range(i, d):
            cols.append((f[:, i] * f[:, j])[:, None])
    return np.hstack(cols)


@dataclass
class CalibrationReport:
    n_samples: int
    loo_mean_error_px: float
    loo_p90_error_px: float
    monitor_diagonal_px: float

    @property
    def relative_error(self) -> float:
        return self.loo_mean_error_px / self.monitor_diagonal_px


class CalibrationError(ValueError):
    pass


class GazeCalibration:
    def __init__(self, ridge: float = 1e-2) -> None:
        self.ridge = ridge
        self.mean: np.ndarray | None = None
        self.std: np.ndarray | None = None
        self.weights: np.ndarray | None = None
        self.report: CalibrationReport | None = None

    @property
    def is_fitted(self) -> bool:
        return self.weights is not None

    def _design(self, features: np.ndarray) -> np.ndarray:
        assert self.mean is not None and self.std is not None
        return _poly((np.atleast_2d(features) - self.mean) / self.std)

    def _solve(self, a: np.ndarray, y: np.ndarray) -> np.ndarray:
        reg = self.ridge * np.eye(a.shape[1])
        reg[0, 0] = 0.0  # do not penalise the intercept
        return np.linalg.solve(a.T @ a + reg, a.T @ y)

    def fit(self, features: np.ndarray, targets: np.ndarray, monitor_size_px: tuple[int, int],
            min_samples: int = 27) -> CalibrationReport:
        """features: (n, d) averaged per-sample eye/head vectors; targets: (n, 2) normalised."""
        features, targets = np.asarray(features, float), np.asarray(targets, float)
        if features.ndim != 2 or targets.shape != (features.shape[0], 2):
            raise CalibrationError("features must be (n, d) and targets (n, 2)")
        if not np.isfinite(features).all():
            raise CalibrationError("features contain NaN/inf")
        if len(features) < min_samples:
            raise CalibrationError(f"need at least {min_samples} samples, got {len(features)}")
        if len({tuple(t) for t in targets.round(4)}) < 5:
            raise CalibrationError("calibration needs at least 5 distinct screen targets")
        self.mean = features.mean(axis=0)
        self.std = features.std(axis=0)
        self.std[self.std < 1e-9] = 1.0
        a = self._design(features)
        self.weights = self._solve(a, targets)

        # Leave-one-*target*-out so repeated samples of the same dot cannot leak.
        w, h = monitor_size_px
        scale = np.array([w, h], float)
        errs: list[float] = []
        keys = [tuple(t) for t in targets.round(4)]
        for key in set(keys):
            test = np.array([k == key for k in keys])
            if test.all() or (~test).sum() < a.shape[1]:
                continue
            wt = self._solve(a[~test], targets[~test])
            pred = a[test] @ wt
            errs.extend(np.linalg.norm((pred - targets[test]) * scale, axis=1))
        if not errs:
            raise CalibrationError("not enough data for validation")
        self.report = CalibrationReport(len(features), float(np.mean(errs)), float(np.percentile(errs, 90)),
                                        float(np.hypot(w, h)))
        return self.report

    def predict(self, features: np.ndarray) -> tuple[float, float]:
        if not self.is_fitted:
            raise CalibrationError("not calibrated")
        out = self._design(features) @ self.weights  # type: ignore[operator]
        return float(out[0, 0]), float(out[0, 1])

    # ---- persistence ----------------------------------------------------------
    def to_json(self) -> str:
        if not self.is_fitted:
            raise CalibrationError("not calibrated")
        return json.dumps({"ridge": self.ridge, "mean": self.mean.tolist(), "std": self.std.tolist(),  # type: ignore[union-attr]
                           "weights": self.weights.tolist(),  # type: ignore[union-attr]
                           "report": self.report.__dict__ if self.report else None})

    @classmethod
    def from_json(cls, raw: str) -> "GazeCalibration":
        d = json.loads(raw)
        cal = cls(d["ridge"])
        cal.mean, cal.std, cal.weights = (np.array(d[k]) for k in ("mean", "std", "weights"))
        if d.get("report"):
            cal.report = CalibrationReport(**d["report"])
        return cal
