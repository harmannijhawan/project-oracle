"""ORACLE Brain: deterministic, explainable ranking of candidate interactions.

The brain *recommends*; it never executes. Output is a ``Decision`` with ranked ``Suggestion``s,
evidence for each, a calibrated-by-construction confidence (a normalised share, discounted by
tracking quality) and an explicit ambiguity flag. Looking, considering and select-ready are
different phases: looking at something never selects it.

Scoring (per candidate element i):
    score_i = spatial_i * prior_i * suppress_i * (1 + dwell_gain * dwell)
    p_i     = score_i / (sum(score) + none_weight)       # none_weight = "just looking / nothing intended"
    conf_i  = p_i * quality_factor
Priors come from the user's own confirmed/rejected history (Laplace smoothed, backing off to the
control type). A rejected element is suppressed and recovers over ``reject_halflife_s``.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from engine.control import ActionKind, ActionSource, Command, RiskLevel, effective_risk
from engine.screen_context import Candidate, ElementIndex, ScreenSnapshot

from .history import InteractionHistory


@dataclass(frozen=True)
class BrainConfig:
    none_weight: float = 0.35
    dwell_gain: float = 2.0
    min_confidence: float = 0.45  # below this a suggestion is "weak" and never select-ready
    ambiguity_margin: float = 0.15
    reject_halflife_s: float = 120.0
    reject_strength: float = 0.9  # fraction suppressed immediately after one rejection
    history_weight: float = 1.0
    min_quality: float = 0.5
    max_suggestions: int = 4


@dataclass(frozen=True)
class FaceSignal:
    """Only deliberate, user-configured gestures may influence selection."""

    deliberate_blink: bool = False
    gestures_enabled: bool = False


@dataclass(frozen=True)
class Evidence:
    name: str
    value: float
    detail: str


@dataclass(frozen=True)
class Suggestion:
    element_key: str
    element_id: str
    label: str
    app: str
    control_type: str
    action: ActionKind
    x: int
    y: int
    probability: float
    confidence: float
    risk: RiskLevel
    needs_confirmation: bool
    evidence: tuple[Evidence, ...]
    window_handle: int = 0


@dataclass(frozen=True)
class Decision:
    phase: str  # "idle" | "looking" | "considering" | "select_ready" | "paused"
    suggestions: tuple[Suggestion, ...]
    ambiguous: bool
    reason: str
    select_target: Suggestion | None = None


def _default_action(c: Candidate, snapshot: ScreenSnapshot) -> ActionKind:
    e = c.element
    fg = snapshot.foreground
    if e.control_type == "ScrollBar":
        return ActionKind.SCROLL
    if fg is not None and e.window_handle and e.window_handle != fg.handle:
        return ActionKind.SWITCH_WINDOW
    return ActionKind.CLICK


class OracleBrain:
    def __init__(self, history: InteractionHistory, config: BrainConfig | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.history, self.cfg, self.clock = history, config or BrainConfig(), clock
        self.log: deque[dict] = deque(maxlen=200)  # understandable action history
        self._rejected_session: dict[str, float] = {}

    # ---- priors ------------------------------------------------------------------------------
    def _prior(self, key: str, control_type: str) -> tuple[float, str]:
        e, t = self.history.element_stats(key), self.history.type_stats(control_type)
        type_rate = (t.confirmed + 1) / (t.total + 2)
        a = 2.0  # pseudo-count pulling element rate toward its control type's rate
        rate = (e.confirmed + a * type_rate) / (e.total + a)
        weight = 0.5 + self.cfg.history_weight * (rate - 0.5)  # 0.5 neutral
        return max(weight, 0.05) * 2.0, f"{e.confirmed} confirmed / {e.rejected} rejected for this element"

    def _suppression(self, key: str) -> tuple[float, str]:
        since = self.history.seconds_since_rejection(key)
        local = self._rejected_session.get(key)
        if local is not None:
            since = min(since, self.clock() - local) if since is not None else self.clock() - local
        if since is None:
            return 1.0, "not rejected recently"
        factor = 1.0 - self.cfg.reject_strength * math.exp(-math.log(2) * max(since, 0) / self.cfg.reject_halflife_s)
        return max(factor, 0.02), f"rejected {since:.0f}s ago"

    # ---- main entry --------------------------------------------------------------------------
    def observe(self, index: ElementIndex, x: float, y: float, gaze_error_px: float, dwell_progress: float,
                quality: float, face: FaceSignal | None = None, tracking_allowed: bool = True) -> Decision:
        cfg = self.cfg
        if not tracking_allowed:
            return Decision("paused", (), False, "safety controller is not active")
        if quality < cfg.min_quality:
            return Decision("idle", (), False, f"tracking quality {quality:.2f} is below {cfg.min_quality:.2f}")
        cands = index.at(x, y, gaze_error_px)
        if not cands:
            return Decision("idle", (), False, "no interactive element near the gaze point")

        scored: list[tuple[float, Candidate, list[Evidence]]] = []
        for c in cands:
            key = c.element.key
            prior, prior_detail = self._prior(key, c.element.control_type)
            supp, supp_detail = self._suppression(key)
            score = c.likelihood * prior * supp * (1 + cfg.dwell_gain * dwell_progress)
            if c.element.source == "vision":
                score *= 0.6  # unnamed CV regions are less trustworthy than UIA elements
            ev = [Evidence("spatial", c.likelihood, "gaze inside element" if c.contained
                           else f"{c.distance_px:.0f}px from element (gaze error ~{gaze_error_px:.0f}px)"),
                  Evidence("dwell", dwell_progress, f"dwell {dwell_progress * 100:.0f}% complete"),
                  Evidence("history", prior, prior_detail), Evidence("rejection", supp, supp_detail)]
            if c.element.source == "vision":
                ev.append(Evidence("source", 0.6, "found by screen analysis, no accessibility name"))
            scored.append((score, c, ev))

        total = sum(s for s, _, _ in scored) + cfg.none_weight
        qf = min(1.0, quality)
        suggestions: list[Suggestion] = []
        for score, c, ev in sorted(scored, key=lambda t: -t[0])[: cfg.max_suggestions]:
            p = score / total
            action = _default_action(c, index.snapshot)
            cx, cy = (int(v) for v in c.element.rect.center)
            probe = Command(kind=action, source=ActionSource.DWELL, x=cx, y=cy, dx=None if action != ActionKind.SCROLL else 0,
                            dy=None if action != ActionKind.SCROLL else -120, target_label=c.element.name or None,
                            window_handle=c.element.window_handle if action == ActionKind.SWITCH_WINDOW else None)
            risk = effective_risk(probe)
            suggestions.append(Suggestion(c.element.key, c.element.id, c.element.name or f"<{c.element.control_type}>",
                                          c.element.app, c.element.control_type, action, cx, cy, p, p * qf, risk,
                                          risk >= RiskLevel.HIGH, tuple(ev), c.element.window_handle))
        top = suggestions[0]
        second = suggestions[1].probability if len(suggestions) > 1 else 0.0
        ambiguous = len(suggestions) > 1 and (top.probability - second) < cfg.ambiguity_margin and second > 0.2

        gesture = face is not None and face.gestures_enabled and face.deliberate_blink
        if dwell_progress >= 1.0 or gesture:
            if ambiguous:
                return Decision("considering", tuple(suggestions), True, "ambiguous: several elements are equally likely")
            if top.confidence < cfg.min_confidence:
                return Decision("considering", tuple(suggestions), False, f"confidence {top.confidence:.2f} too low to select")
            return Decision("select_ready", tuple(suggestions), False, "dwell complete" if not gesture else "deliberate blink",
                            select_target=top)
        phase = "considering" if dwell_progress >= 0.3 else "looking"
        return Decision(phase, tuple(suggestions), ambiguous, "ambiguous" if ambiguous else "gathering evidence")

    # ---- learning ----------------------------------------------------------------------------
    def record_outcome(self, s: Suggestion, outcome: str, corrected_to: Suggestion | None = None) -> None:
        """User feedback. 'confirmed' -> reinforce; 'rejected' -> suppress; 'corrected' -> reject s, confirm other."""
        if outcome == "corrected" and corrected_to is None:
            raise ValueError("a correction needs the intended element")
        self.history.record(s.app, s.element_key, s.control_type, s.action.value,
                            "rejected" if outcome == "corrected" else outcome, s.confidence)
        if outcome in ("rejected", "corrected"):
            self._rejected_session[s.element_key] = self.clock()
        if outcome == "corrected" and corrected_to is not None:
            self.history.record(corrected_to.app, corrected_to.element_key, corrected_to.control_type,
                                corrected_to.action.value, "confirmed", corrected_to.confidence)
        self.log.appendleft({"ts": self.clock(), "outcome": outcome, "label": s.label, "app": s.app,
                             "action": s.action.value, "confidence": round(s.confidence, 3),
                             "corrected_to": corrected_to.label if corrected_to else None,
                             "evidence": [f"{e.name}: {e.detail}" for e in s.evidence]})

    # ---- command construction (still gated by ActionController) ---------------------------------
    @staticmethod
    def command_for(s: Suggestion, source: ActionSource) -> Command:
        """Typed command for a suggestion. ``INFERRED`` is downgraded to a harmless highlight."""
        if source is ActionSource.INFERRED:
            return Command(kind=ActionKind.HIGHLIGHT, source=source, x=s.x, y=s.y, target_label=s.label)
        kw: dict = {"x": s.x, "y": s.y, "target_label": s.label or None, "target_id": s.element_id[:200]}
        if s.action is ActionKind.SCROLL:
            kw.update(dx=0, dy=-120)
        if s.action is ActionKind.SWITCH_WINDOW:
            kw["window_handle"] = s.window_handle
        return Command(kind=s.action, source=source, **kw)
