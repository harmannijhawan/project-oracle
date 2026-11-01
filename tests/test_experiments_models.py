import numpy as np
import pytest

from engine.experiments import ProtocolError, TrialManager
from engine.prediction import (InsufficientData, ModelRegistry, chronological_session_split,
                               evaluate_personal_model, load_records, train_personal_model, wilson)
from engine.storage import Database

D = 6


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self):
        self.t += 1.0
        return self.t


def run_sessions(db, n_sessions, trials_each, signal, seed=0, clock=None):
    """Simulate participants. signal=0 -> choices independent of features (pure noise)."""
    rng = np.random.default_rng(seed)
    tm = TrialManager(db, seed=seed, clock=clock or Clock())
    for _ in range(n_sessions):
        sid = tm.start_session()
        for _ in range(trials_each):
            t = tm.new_trial(sid, "icon_a", "icon_b")
            latent = rng.normal()
            feats = rng.normal(0, 1, D); feats[0] += signal * latent  # feature 0 carries the preference
            tm.add_features(t.id, feats)
            pred = {"p_right": 0.5}  # placeholder; real predictions come from the model
            tm.lock_prediction(t.id, pred)
            right = rng.random() < 1 / (1 + np.exp(-2.5 * latent)) if signal else rng.random() < 0.5
            tm.reveal_label(t.id, "right" if right else "left")
    return tm


def test_block_randomisation_balances_sides():
    db = Database(); tm = TrialManager(db, seed=3)
    sid = tm.start_session()
    sides = [tm.new_trial(sid, "A", "B").left for _ in range(40)]
    assert sides.count("A") == 20
    assert all(sides[i:i + 4].count("A") == 2 for i in range(0, 40, 4))


def test_prediction_must_be_locked_before_label_and_features_freeze():
    db = Database(); tm = TrialManager(db, clock=Clock())
    sid = tm.start_session(); t = tm.new_trial(sid, "A", "B")
    with pytest.raises(ProtocolError): tm.lock_prediction(t.id, {"p": 0.6})  # no features yet
    tm.add_features(t.id, np.ones(D))
    with pytest.raises(ProtocolError): tm.reveal_label(t.id, "left")  # answer before lock
    tm.lock_prediction(t.id, {"p": 0.6})
    with pytest.raises(ProtocolError): tm.add_features(t.id, np.zeros(D))  # frozen
    with pytest.raises(ProtocolError): tm.lock_prediction(t.id, {"p": 0.9})  # no re-lock
    tm.reveal_label(t.id, "right")
    with pytest.raises(ProtocolError): tm.reveal_label(t.id, "left")
    assert tm.verify_commitment(t.id) and tm.audit_all() == []


def test_tampering_with_locked_prediction_is_detected():
    db = Database(); tm = TrialManager(db, clock=Clock())
    sid = tm.start_session(); t = tm.new_trial(sid, "A", "B")
    tm.add_features(t.id, np.ones(D)); tm.lock_prediction(t.id, {"p": 0.6}); tm.reveal_label(t.id, "left")
    db.execute("UPDATE trials SET prediction_json = ? WHERE id = ?", ('{"p": 0.99}', t.id))
    assert not tm.verify_commitment(t.id) and tm.audit_all() == [t.id]


def test_split_is_chronological_and_session_disjoint():
    db = Database(); run_sessions(db, 5, 10, 1.0)
    train, test = chronological_session_split(load_records(db), 1)
    assert {r.session_id for r in train}.isdisjoint({r.session_id for r in test})
    assert max(r.session_started for r in train) < min(r.session_started for r in test)
    with pytest.raises(ValueError):
        chronological_session_split(load_records(db)[:20], 1)


def test_model_finds_real_signal_on_independent_session():
    db = Database(); run_sessions(db, 8, 30, signal=2.0, seed=1)
    train, test = chronological_session_split(load_records(db), 2)
    model, rep = evaluate_personal_model(train, test, seed=1)
    face = rep.results["face_all_trials"]
    assert face.accuracy > 0.6 and face.p_vs_chance < 0.05
    assert rep.n_test == 60 and rep.test_sessions == 2
    assert rep.results["context_only"].p_vs_chance > 0.01  # context carries no signal here


def test_pure_noise_is_reported_as_no_evidence():
    """The system must not fabricate accuracy when there is nothing to learn."""
    false_claims = 0
    for seed in range(6):
        db = Database(); run_sessions(db, 8, 30, signal=0.0, seed=100 + seed)
        train, test = chronological_session_split(load_records(db), 2)
        _, rep = evaluate_personal_model(train, test, seed=seed)
        assert rep.results["face_all_trials"].ci95[0] < 0.5  # never claims a lower bound above chance
        false_claims += not rep.verdict.startswith("No evidence")
    assert false_claims <= 1  # ~5% nominal false-positive rate


def test_abstention_on_low_confidence_bad_quality_and_ood():
    db = Database(); run_sessions(db, 6, 25, signal=1.5, seed=4)
    train, _ = chronological_session_split(load_records(db), 1)
    X = np.stack([r.features for r in train])
    m = train_personal_model(X, np.array([r.chose_right for r in train]), np.array([r.session_id for r in train]))
    assert m.predict(np.zeros(D), quality=0.1).abstain
    assert "outside" in m.predict(np.full(D, 50.0)).reason
    assert m.predict(np.zeros(D + 1)).reason == "invalid features"
    confident = m.predict(np.array([3.0, 0, 0, 0, 0, 0]))
    assert (not confident.abstain) and confident.side == "right"


def test_insufficient_data_refused():
    with pytest.raises(InsufficientData):
        train_personal_model(np.zeros((10, D)), np.zeros(10), np.zeros(10))


def test_registry_versions_checksum_and_deletion(tmp_path):
    db = Database(); run_sessions(db, 5, 20, signal=1.5, seed=5)
    train, _ = chronological_session_split(load_records(db), 1)
    m = train_personal_model(np.stack([r.features for r in train]), np.array([r.chose_right for r in train]),
                             np.array([r.session_id for r in train]))
    reg = ModelRegistry(tmp_path / "models", db)
    assert reg.save(m) == 1 and reg.save(m, {"note": "retrained"}) == 2
    assert [v["version"] for v in reg.versions()] == [1, 2]
    assert reg.load(1).name == m.name
    p = tmp_path / "models" / "personal_model_v1.joblib"
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(ValueError):
        reg.load(1)
    reg.delete_all()
    assert reg.versions() == [] and not list((tmp_path / "models").iterdir())


def test_wilson_interval_sane():
    lo, hi = wilson(60, 100)
    assert 0.5 < lo < 0.6 < hi < 0.7
    assert wilson(0, 0) == (0.0, 1.0)
