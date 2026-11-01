"""Controlled choice-prediction trials with commit-before-reveal prediction locking.

Protocol per trial:
  1. ``new_trial``      options are placed left/right using balanced block randomisation
  2. ``add_features``   face-feature window recorded during deliberation
  3. ``lock_prediction`` prediction + SHA-256 commitment stored with a timestamp
  4. ``reveal_label``   the participant's real choice is recorded -- refused unless step 3 happened first

Features are rejected after locking, and labels are rejected before it, so a prediction can
never be influenced by the answer. ``verify_commitment`` lets analysis re-check every trial.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import uuid
from dataclasses import dataclass
from typing import Callable

import numpy as np

from engine.storage import Database


class ProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Trial:
    id: str
    session_id: str
    idx: int
    left: str
    right: str


class TrialManager:
    def __init__(self, db: Database, seed: int | None = None, clock: Callable[[], float] = time.time) -> None:
        self.db, self.clock = db, clock
        self._rng = random.Random(seed)
        self._block: dict[str, list[bool]] = {}  # session -> remaining "first option on left" flags

    def start_session(self, kind: str = "choice", notes: str = "") -> str:
        sid = uuid.uuid4().hex
        self.db.execute("INSERT INTO sessions(id, started_at, kind, notes) VALUES(?,?,?,?)",
                        (sid, self.clock(), kind, notes))
        return sid

    def _next_first_on_left(self, session_id: str) -> bool:
        if not self._block.get(session_id):
            flags = [True, False] * 2  # blocks of 4 keep left/right balanced within every 4 trials
            self._rng.shuffle(flags)
            self._block[session_id] = flags
        return self._block[session_id].pop()

    def new_trial(self, session_id: str, option_a: str, option_b: str) -> Trial:
        if option_a == option_b:
            raise ProtocolError("options must differ")
        if not self.db.query("SELECT 1 FROM sessions WHERE id = ?", (session_id,)):
            raise ProtocolError("unknown session")
        idx = self.db.query("SELECT COUNT(*) FROM trials WHERE session_id = ?", (session_id,))[0][0]
        left, right = (option_a, option_b) if self._next_first_on_left(session_id) else (option_b, option_a)
        tid = uuid.uuid4().hex
        self.db.execute("INSERT INTO trials(id, session_id, idx, options_json, left_option, right_option, created_at)"
                        " VALUES(?,?,?,?,?,?,?)",
                        (tid, session_id, idx, json.dumps([option_a, option_b]), left, right, self.clock()))
        return Trial(tid, session_id, idx, left, right)

    def _row(self, trial_id: str):
        rows = self.db.query("SELECT * FROM trials WHERE id = ?", (trial_id,))
        if not rows:
            raise ProtocolError("unknown trial")
        return rows[0]

    def add_features(self, trial_id: str, features: np.ndarray) -> None:
        row = self._row(trial_id)
        if row["locked_at"] is not None:
            raise ProtocolError("prediction already locked; features can no longer change")
        vec = np.asarray(features, float)
        if not np.isfinite(vec).all():
            raise ProtocolError("features contain NaN/inf")
        self.db.execute("UPDATE trials SET features_json = ? WHERE id = ?", (json.dumps(vec.tolist()), trial_id))

    @staticmethod
    def _commitment(trial_id: str, prediction_json: str, locked_at: float, features_json: str) -> str:
        return hashlib.sha256(f"{trial_id}|{prediction_json}|{locked_at!r}|{features_json}".encode()).hexdigest()

    def lock_prediction(self, trial_id: str, prediction: dict) -> str:
        row = self._row(trial_id)
        if row["label"] is not None:
            raise ProtocolError("label already revealed")
        if row["locked_at"] is not None:
            raise ProtocolError("prediction already locked")
        if row["features_json"] is None:
            raise ProtocolError("record features before locking a prediction")
        pj, now = json.dumps(prediction, sort_keys=True), self.clock()
        digest = self._commitment(trial_id, pj, now, row["features_json"])
        self.db.execute("UPDATE trials SET prediction_json=?, locked_at=?, prediction_hash=? WHERE id=?",
                        (pj, now, digest, trial_id))
        return digest

    def reveal_label(self, trial_id: str, chosen_side: str) -> None:
        if chosen_side not in ("left", "right"):
            raise ProtocolError("chosen_side must be 'left' or 'right'")
        row = self._row(trial_id)
        if row["locked_at"] is None:
            raise ProtocolError("cannot record an answer before the prediction is locked")
        if row["label"] is not None:
            raise ProtocolError("label already recorded")
        now = self.clock()
        if now < row["locked_at"]:
            raise ProtocolError("clock moved backwards; refusing to record label")
        self.db.execute("UPDATE trials SET label=?, revealed_at=? WHERE id=?", (chosen_side, now, trial_id))

    def verify_commitment(self, trial_id: str) -> bool:
        row = self._row(trial_id)
        if row["locked_at"] is None:
            return False
        ok = self._commitment(trial_id, row["prediction_json"], row["locked_at"], row["features_json"]) == row["prediction_hash"]
        return ok and (row["label"] is None or row["revealed_at"] >= row["locked_at"])

    def audit_all(self) -> list[str]:
        """Trial ids whose lock-before-reveal guarantee cannot be verified."""
        return [r["id"] for r in self.db.query("SELECT id FROM trials WHERE label IS NOT NULL")
                if not self.verify_commitment(r["id"])]
