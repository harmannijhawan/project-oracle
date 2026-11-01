"""Personal interaction history (confirmed / rejected outcomes), persisted in SQLite."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from engine.storage import Database


@dataclass(frozen=True)
class Stats:
    confirmed: int
    rejected: int

    @property
    def total(self) -> int:
        return self.confirmed + self.rejected


class InteractionHistory:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time) -> None:
        self.db, self.clock = db, clock

    def record(self, app: str | None, element_key: str, control_type: str | None, action_kind: str,
               outcome: str, confidence: float | None) -> None:
        if outcome not in ("confirmed", "rejected", "corrected"):
            raise ValueError("outcome must be confirmed, rejected or corrected")
        self.db.execute("INSERT INTO interactions(ts, app, element_key, control_type, action_kind, outcome, confidence)"
                        " VALUES(?,?,?,?,?,?,?)",
                        (self.clock(), app, element_key, control_type, action_kind, outcome, confidence))

    def element_stats(self, element_key: str) -> Stats:
        r = self.db.query("SELECT SUM(outcome='confirmed'), SUM(outcome='rejected') FROM interactions "
                          "WHERE element_key = ?", (element_key,))[0]
        return Stats(int(r[0] or 0), int(r[1] or 0))

    def type_stats(self, control_type: str) -> Stats:
        r = self.db.query("SELECT SUM(outcome='confirmed'), SUM(outcome='rejected') FROM interactions "
                          "WHERE control_type = ?", (control_type,))[0]
        return Stats(int(r[0] or 0), int(r[1] or 0))

    def seconds_since_rejection(self, element_key: str) -> float | None:
        r = self.db.query("SELECT MAX(ts) FROM interactions WHERE element_key = ? AND outcome = 'rejected'",
                          (element_key,))[0][0]
        return None if r is None else self.clock() - r

    def recent(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM interactions ORDER BY id DESC LIMIT ?", (limit,))]
