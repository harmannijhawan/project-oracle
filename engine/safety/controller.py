"""Independent emergency-stop controller.

This module deliberately imports nothing from the gaze, face, prediction or
brain packages. It must keep working when every model is broken. Stopping
requires only a method call, which is wired to a global keyboard shortcut
(Electron), a persistent on-screen button, and automatic health monitors.

Resuming is never automatic: ``manual_resume`` needs an explicit confirmation.
"""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field
from typing import Callable


class SafetyState(str, enum.Enum):
    ACTIVE = "active"
    STOPPED = "stopped"  # user-initiated emergency stop
    AUTO_PAUSED = "auto_paused"  # health-initiated pause


class StopReason(str, enum.Enum):
    USER_SHORTCUT = "user_shortcut"
    USER_BUTTON = "user_button"
    CAMERA_FAILURE = "camera_failure"
    TRACKING_QUALITY = "tracking_quality"
    BACKEND_ERROR = "backend_error"
    EXTERNAL = "external"


@dataclass(frozen=True)
class SafetyEvent:
    timestamp: float
    kind: str  # "stop" | "auto_pause" | "resume" | "resume_refused"
    reason: str
    detail: str = ""


@dataclass
class SafetyConfig:
    camera_timeout_s: float = 2.0  # no frame for this long => camera failure
    tracking_min_quality: float = 0.5
    tracking_grace_s: float = 1.5  # sustained poor quality before auto-pause
    resume_requires_healthy: bool = True


CancelHook = Callable[[], None]
EventListener = Callable[[SafetyEvent], None]


@dataclass
class SafetyController:
    config: SafetyConfig = field(default_factory=SafetyConfig)
    clock: Callable[[], float] = time.monotonic
    _state: SafetyState = SafetyState.ACTIVE
    _reason: StopReason | None = None
    _events: list[SafetyEvent] = field(default_factory=list)
    _cancel_hooks: list[CancelHook] = field(default_factory=list)
    _listeners: list[EventListener] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _last_frame_at: float | None = None
    _poor_since: float | None = None
    _last_quality: float | None = None

    # ---- registration -------------------------------------------------
    def register_cancel_hook(self, hook: CancelHook) -> None:
        """Hooks run synchronously on every stop (cancel pending, release input)."""
        with self._lock:
            self._cancel_hooks.append(hook)

    def add_listener(self, listener: EventListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    # ---- state ----------------------------------------------------------
    @property
    def state(self) -> SafetyState:
        return self._state

    @property
    def reason(self) -> StopReason | None:
        return self._reason

    def is_execution_allowed(self) -> bool:
        return self._state is SafetyState.ACTIVE

    @property
    def events(self) -> list[SafetyEvent]:
        with self._lock:
            return list(self._events)

    # ---- stopping ---------------------------------------------------------
    def emergency_stop(self, reason: StopReason = StopReason.USER_SHORTCUT, detail: str = "") -> None:
        """Idempotent, never raises. A user stop outranks an automatic pause."""
        with self._lock:
            already_stopped = self._state is SafetyState.STOPPED
            self._state = SafetyState.STOPPED
            self._reason = reason
            if not already_stopped:
                self._record("stop", reason.value, detail)
        self._run_cancel_hooks()

    def auto_pause(self, reason: StopReason, detail: str = "") -> None:
        with self._lock:
            if self._state is not SafetyState.ACTIVE:
                return
            self._state = SafetyState.AUTO_PAUSED
            self._reason = reason
            self._record("auto_pause", reason.value, detail)
        self._run_cancel_hooks()

    def _run_cancel_hooks(self) -> None:
        for hook in list(self._cancel_hooks):
            try:
                hook()
            except Exception as exc:  # a failing hook must never block the stop
                self._record("stop", "cancel_hook_error", repr(exc))

    # ---- health monitors ----------------------------------------------------
    def report_camera_frame(self) -> None:
        with self._lock:
            self._last_frame_at = self.clock()

    def report_camera_error(self, detail: str = "") -> None:
        self.auto_pause(StopReason.CAMERA_FAILURE, detail or "camera reported an error")

    def report_tracking_quality(self, quality: float) -> None:
        now = self.clock()
        with self._lock:
            self._last_quality = quality
            if quality >= self.config.tracking_min_quality:
                self._poor_since = None
                return
            if self._poor_since is None:
                self._poor_since = now
            sustained = now - self._poor_since >= self.config.tracking_grace_s
        if sustained:
            self.auto_pause(StopReason.TRACKING_QUALITY, f"quality {quality:.2f} below threshold")

    def tick(self) -> None:
        """Call periodically (e.g. 10 Hz) to detect a silently dead camera."""
        with self._lock:
            last = self._last_frame_at
        if last is not None and self.clock() - last > self.config.camera_timeout_s:
            self.auto_pause(StopReason.CAMERA_FAILURE, "no camera frames received")

    def _healthy(self) -> tuple[bool, str]:
        if self._last_frame_at is not None and self.clock() - self._last_frame_at > self.config.camera_timeout_s:
            return False, "camera is not delivering frames"
        if self._last_quality is not None and self._last_quality < self.config.tracking_min_quality:
            return False, "tracking quality is still below threshold"
        return True, ""

    # ---- resume -------------------------------------------------------------
    def manual_resume(self, confirmed: bool) -> bool:
        """Explicit manual resume. Returns True only if the system is ACTIVE afterwards."""
        with self._lock:
            if self._state is SafetyState.ACTIVE:
                return True
            if not confirmed:
                self._record("resume_refused", "not_confirmed")
                return False
            if self._state is SafetyState.AUTO_PAUSED and self.config.resume_requires_healthy:
                ok, why = self._healthy()
                if not ok:
                    self._record("resume_refused", "unhealthy", why)
                    return False
            self._state = SafetyState.ACTIVE
            self._reason = None
            self._poor_since = None
            self._record("resume", "manual")
            return True

    # ---- internals --------------------------------------------------------------
    def _record(self, kind: str, reason: str, detail: str = "") -> None:
        event = SafetyEvent(self.clock(), kind, reason, detail)
        self._events.append(event)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                pass
