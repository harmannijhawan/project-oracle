"""Honest evaluation: chronological session split, baselines, intervals and significance tests.

Nothing here hardcodes an accuracy: every number is computed from stored trials. The verdict
text only says a face model "beats" a baseline when an exact test supports it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import binomtest

from engine.storage import Database

from .personal_model import PersonalModel, train_personal_model


@dataclass(frozen=True)
class TrialRecord:
    trial_id: str
    session_id: str
    session_started: float
    left: str
    right: str
    features: np.ndarray
    chose_right: int


def load_records(db: Database) -> list[TrialRecord]:
    rows = db.query("""SELECT t.*, s.started_at FROM trials t JOIN sessions s ON s.id = t.session_id
                       WHERE t.label IS NOT NULL AND t.features_json IS NOT NULL
                       ORDER BY s.started_at, t.idx""")
    return [TrialRecord(r["id"], r["session_id"], r["started_at"], r["left_option"], r["right_option"],
                        np.array(json.loads(r["features_json"])), int(r["label"] == "right")) for r in rows]


def chronological_session_split(records: list[TrialRecord], n_test_sessions: int = 1
                                ) -> tuple[list[TrialRecord], list[TrialRecord]]:
    """The latest ``n_test_sessions`` sessions are reserved for independent testing."""
    order = sorted({(r.session_started, r.session_id) for r in records})
    if len(order) < n_test_sessions + 2:
        raise ValueError(f"need at least {n_test_sessions + 2} sessions (2 train + {n_test_sessions} test)")
    test_ids = {sid for _, sid in order[-n_test_sessions:]}
    train = [r for r in records if r.session_id not in test_ids]
    test = [r for r in records if r.session_id in test_ids]
    assert not {r.session_id for r in train} & {r.session_id for r in test}
    return train, test


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return float(max(0, c - h)), float(min(1, c + h))


@dataclass
class PredictorResult:
    name: str
    n_answered: int
    n_correct: int
    n_abstained: int
    accuracy: float
    ci95: tuple[float, float]
    p_vs_chance: float  # two-sided exact binomial vs 0.5

    @property
    def coverage(self) -> float:
        total = self.n_answered + self.n_abstained
        return self.n_answered / total if total else 0.0


@dataclass
class EvaluationReport:
    n_train: int
    n_test: int
    train_sessions: int
    test_sessions: int
    selected_model: str
    results: dict[str, PredictorResult]
    p_face_vs_context: float
    verdict: str
    cv_scores: dict = field(default_factory=dict)


def _result(name: str, correct: list[bool], abstained: int = 0) -> PredictorResult:
    n, k = len(correct), int(sum(correct))
    p = binomtest(k, n, 0.5).pvalue if n else 1.0
    return PredictorResult(name, n, k, abstained, k / n if n else 0.0, wilson(k, n), float(p))


class _ContextOnly:
    """Predicts using only *what the options are* (no face data): picks the historically preferred option."""

    def __init__(self, train: list[TrialRecord]) -> None:
        wins: dict[str, list[int]] = {}
        for r in train:
            chosen, other = (r.right, r.left) if r.chose_right else (r.left, r.right)
            wins.setdefault(chosen, [0, 0])[0] += 1
            wins[chosen][1] += 1
            wins.setdefault(other, [0, 0])[1] += 1
        self.rate = {k: (w + 1) / (n + 2) for k, (w, n) in wins.items()}  # Laplace-smoothed pick rate

    def predict_right(self, r: TrialRecord) -> int:
        return int(self.rate.get(r.right, 0.5) >= self.rate.get(r.left, 0.5))


def evaluate_personal_model(train: list[TrialRecord], test: list[TrialRecord], seed: int = 0,
                            abstain_below: float = 0.65) -> tuple[PersonalModel, EvaluationReport]:
    X = np.stack([r.features for r in train])
    model = train_personal_model(X, np.array([r.chose_right for r in train]),
                                 np.array([r.session_id for r in train]), seed, abstain_below)
    rng = np.random.default_rng(seed)
    ctx = _ContextOnly(train)

    random_ok = [bool(rng.integers(0, 2) == r.chose_right) for r in test]
    ctx_ok = [ctx.predict_right(r) == r.chose_right for r in test]
    face_pred = [model.predict(r.features) for r in test]
    answered = [(p, r) for p, r in zip(face_pred, test) if not p.abstain]
    face_ok = [(p.side == "right") == bool(r.chose_right) for p, r in answered]
    face_all_ok = [((p.p_right >= 0.5) == bool(r.chose_right)) for p, r in zip(face_pred, test)]

    results = {
        "random": _result("random", random_ok),
        "context_only": _result("context_only", ctx_ok),
        "face_all_trials": _result("face_all_trials", face_all_ok),
        "face_with_abstention": _result("face_with_abstention", face_ok, len(test) - len(answered)),
    }
    # exact McNemar: do face and context-only differ in correctness on the same test trials?
    only_face = sum(f and not c for f, c in zip(face_all_ok, ctx_ok))
    only_ctx = sum(c and not f for f, c in zip(face_all_ok, ctx_ok))
    p_diff = float(binomtest(only_face, only_face + only_ctx, 0.5).pvalue) if only_face + only_ctx else 1.0

    face = results["face_all_trials"]
    if face.p_vs_chance < 0.05 and face.accuracy > 0.5 and p_diff < 0.05 and only_face > only_ctx:
        verdict = ("Face features predicted held-out choices better than chance and better than the "
                   "context-only baseline. This reflects measurable behavioural signal in this participant "
                   "(for example head or gaze drift toward a preferred side), not access to thoughts.")
    elif face.p_vs_chance < 0.05 and face.accuracy > 0.5:
        verdict = "Better than chance, but not demonstrably better than the context-only baseline."
    else:
        verdict = "No evidence that face features predict choices better than chance on the held-out sessions."
    report = EvaluationReport(len(train), len(test), len({r.session_id for r in train}),
                              len({r.session_id for r in test}), model.name, results, p_diff, verdict, model.cv_scores)
    return model, report
