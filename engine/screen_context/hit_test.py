"""Map a gaze point (with known error radius) to ranked candidate elements."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import ScreenSnapshot, UIElement


@dataclass(frozen=True)
class Candidate:
    element: UIElement
    distance_px: float  # 0 when the gaze point is inside the element
    contained: bool
    likelihood: float  # spatial likelihood in (0, 1], before any priors


class ElementIndex:
    """Spatial lookup over interactive elements of one snapshot.

    Occlusion is handled with window z-order: an element in a window that is covered by a
    higher window at the gaze point is dropped. Among overlapping elements the smallest wins
    (a button inside a toolbar beats the toolbar).
    """

    def __init__(self, snapshot: ScreenSnapshot) -> None:
        self.snapshot = snapshot
        self.elements = [e for e in snapshot.elements if e.interactive]

    def at(self, x: float, y: float, error_px: float = 60.0, limit: int = 6) -> list[Candidate]:
        """Candidates within ``error_px`` (the *measured* gaze error), best first."""
        top = self.snapshot.window_at(x, y)
        sigma = max(error_px, 1.0)
        out: list[Candidate] = []
        for e in self.elements:
            d = e.rect.distance_to(x, y)
            if d > 2.5 * sigma:
                continue
            if top is not None and e.window_handle != top.handle and e.z_order > top.z_order and d == 0:
                continue  # covered by a window above
            contained = d == 0
            like = 1.0 if contained else math.exp(-0.5 * (d / sigma) ** 2)
            out.append(Candidate(e, d, contained, like))
        # contained first, then smaller area (more specific), then nearer
        out.sort(key=lambda c: (not c.contained, c.element.rect.area if c.contained else c.distance_px, c.distance_px))
        return out[:limit]
