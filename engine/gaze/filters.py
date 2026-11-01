"""One-Euro filter (Casiez et al. 2012): low lag on saccades, strong smoothing at fixations."""

from __future__ import annotations

import math


class _LowPass:
    def __init__(self) -> None:
        self.value: float | None = None

    def __call__(self, x: float, alpha: float) -> float:
        self.value = x if self.value is None else alpha * x + (1 - alpha) * self.value
        return self.value


class OneEuroFilter:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.02, d_cutoff: float = 1.0) -> None:
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self._x, self._dx = _LowPass(), _LowPass()
        self._prev: float | None = None
        self._t: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self) -> None:
        self.__init__(self.min_cutoff, self.beta, self.d_cutoff)  # type: ignore[misc]

    def __call__(self, x: float, t: float) -> float:
        if self._t is None or t <= self._t:
            self._t, self._prev = t, x
            return self._x(x, 1.0)
        dt = t - self._t
        dx = (x - (self._prev or x)) / dt
        edx = self._dx(dx, self._alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        self._t, self._prev = t, x
        return self._x(x, self._alpha(cutoff, dt))


class PointFilter:
    """2-D wrapper. ``min_cutoff`` is the user-facing smoothing knob (lower = steadier)."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.02) -> None:
        self.fx, self.fy = OneEuroFilter(min_cutoff, beta), OneEuroFilter(min_cutoff, beta)

    def reset(self) -> None:
        self.fx.reset()
        self.fy.reset()

    def __call__(self, x: float, y: float, t: float) -> tuple[float, float]:
        return self.fx(x, t), self.fy(y, t)
