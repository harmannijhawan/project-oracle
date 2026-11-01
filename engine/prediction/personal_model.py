"""Personalised choice-prediction models: LR vs Random Forest vs Gradient Boosting.

One isolated model set per participant (one local database / model dir per user).
Model selection uses cross-validation grouped by *session*; the final report is computed on
later, never-seen sessions (see ``engine.prediction.evaluation``). A deep temporal network is a
documented later experiment and is intentionally not enabled until there is enough data.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from engine.storage import Database

MIN_TRIALS = 40
MIN_TRAIN_SESSIONS = 2


class InsufficientData(ValueError):
    pass


def candidate_models(seed: int = 0) -> dict[str, object]:
    return {
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000)),
        "random_forest": RandomForestClassifier(n_estimators=200, min_samples_leaf=3, random_state=seed, n_jobs=1),
        "gradient_boosting": GradientBoostingClassifier(n_estimators=80, max_depth=2, learning_rate=0.08,
                                                        subsample=0.8, random_state=seed),
    }


@dataclass(frozen=True)
class Prediction:
    side: str | None  # "left" | "right" | None when abstaining
    p_right: float
    confidence: float  # probability of the predicted side (calibrated if model.calibrated)
    abstain: bool
    reason: str


@dataclass
class PersonalModel:
    name: str
    estimator: object
    feature_dim: int
    train_mean: np.ndarray
    train_std: np.ndarray
    calibrated: bool
    abstain_below: float = 0.65
    ood_z_max: float = 8.0
    cv_scores: dict[str, dict[str, float]] = field(default_factory=dict)

    def predict(self, x: np.ndarray, quality: float = 1.0, min_quality: float = 0.5) -> Prediction:
        x = np.asarray(x, float).ravel()
        if x.shape[0] != self.feature_dim or not np.isfinite(x).all():
            return Prediction(None, 0.5, 0.5, True, "invalid features")
        if quality < min_quality:
            return Prediction(None, 0.5, 0.5, True, "tracking quality too low")
        z = np.abs((x - self.train_mean) / self.train_std)
        if z.max() > self.ood_z_max:
            return Prediction(None, 0.5, 0.5, True, "features outside the range seen in training")
        p_right = float(self.estimator.predict_proba(x[None, :])[0, 1])  # type: ignore[attr-defined]
        side = "right" if p_right >= 0.5 else "left"
        conf = max(p_right, 1 - p_right)
        if conf < self.abstain_below:
            return Prediction(None, p_right, conf, True, f"confidence {conf:.2f} below {self.abstain_below:.2f}")
        return Prediction(side, p_right, conf, False, "ok")


def train_personal_model(X: np.ndarray, y: np.ndarray, groups: np.ndarray, seed: int = 0,
                         abstain_below: float = 0.65) -> PersonalModel:
    """X: (n, d) trial features; y: 1 if participant chose the RIGHT option; groups: session ids."""
    X, y, groups = np.asarray(X, float), np.asarray(y, int), np.asarray(groups)
    if len(X) < MIN_TRIALS:
        raise InsufficientData(f"need at least {MIN_TRIALS} labelled trials, have {len(X)}")
    n_sessions = len(set(groups.tolist()))
    if n_sessions < MIN_TRAIN_SESSIONS:
        raise InsufficientData(f"need at least {MIN_TRAIN_SESSIONS} training sessions, have {n_sessions}")
    if len(set(y.tolist())) < 2:
        raise InsufficientData("labels contain a single class")
    splits = list(GroupKFold(n_splits=min(5, n_sessions)).split(X, y, groups))

    scores: dict[str, dict[str, float]] = {}
    for name, est in candidate_models(seed).items():
        losses, accs = [], []
        for tr, te in splits:
            if len(set(y[tr].tolist())) < 2:
                continue
            m = _clone(est).fit(X[tr], y[tr])
            p = np.clip(m.predict_proba(X[te])[:, 1], 1e-6, 1 - 1e-6)
            losses.append(log_loss(y[te], p, labels=[0, 1]))
            accs.append(float(((p >= 0.5) == y[te]).mean()))
        if losses:
            scores[name] = {"cv_log_loss": float(np.mean(losses)), "cv_accuracy": float(np.mean(accs))}
    if not scores:
        raise InsufficientData("cross-validation folds had a single class")
    best = min(scores, key=lambda k: (scores[k]["cv_log_loss"], -scores[k]["cv_accuracy"]))

    est = _clone(candidate_models(seed)[best])
    calibrated = False
    try:
        est = CalibratedClassifierCV(est, method="sigmoid", cv=splits).fit(X, y)
        calibrated = True
    except ValueError:
        est = est.fit(X, y)  # fall back to the uncalibrated model; flagged in metadata
    std = X.std(axis=0)
    std[std < 1e-9] = 1.0
    return PersonalModel(best, est, X.shape[1], X.mean(axis=0), std, calibrated, abstain_below, cv_scores=scores)


def _clone(est: object) -> object:
    from sklearn.base import clone
    return clone(est)


class ModelRegistry:
    """Versioned model files with checksums. joblib files are pickles: only load files this app wrote
    (the SHA-256 recorded in the database is verified before every load)."""

    def __init__(self, directory: str | Path, db: Database) -> None:
        self.dir, self.db = Path(directory), db
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, model: PersonalModel, extra: dict | None = None) -> int:
        version = (self.db.query("SELECT COALESCE(MAX(version), 0) FROM model_versions")[0][0]) + 1
        path = self.dir / f"personal_model_v{version}.joblib"
        joblib.dump(model, path)
        meta = {"name": model.name, "calibrated": model.calibrated, "cv_scores": model.cv_scores,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **(extra or {})}
        self.db.execute("INSERT INTO model_versions(version, created_at, path, metadata_json) VALUES(?,?,?,?)",
                        (version, time.time(), str(path), json.dumps(meta)))
        return version

    def versions(self) -> list[dict]:
        return [{"version": r["version"], "created_at": r["created_at"], **json.loads(r["metadata_json"])}
                for r in self.db.query("SELECT * FROM model_versions ORDER BY version")]

    def load(self, version: int | None = None) -> PersonalModel:
        rows = self.db.query("SELECT * FROM model_versions " + ("WHERE version = ?" if version else "ORDER BY version DESC LIMIT 1"),
                             (version,) if version else ())
        if not rows:
            raise FileNotFoundError("no trained model")
        path = Path(rows[0]["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != json.loads(rows[0]["metadata_json"])["sha256"]:
            raise ValueError("model file checksum mismatch; refusing to load")
        return joblib.load(path)

    def delete_all(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db.execute("DELETE FROM model_versions")
