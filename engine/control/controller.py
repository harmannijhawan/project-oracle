"""Deterministic action controller: typed commands + permissions + safety gate."""

from __future__ import annotations

import enum
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from engine.safety import SafetyController

from .commands import ActionKind, ActionSource, Command, RiskLevel, effective_risk
from .input_adapter import InputAdapter


class ExecStatus(str, enum.Enum):
    EXECUTED = "executed"
    DENIED = "denied"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CANCELLED = "cancelled"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass(frozen=True)
class ExecResult:
    status: ExecStatus
    reason: str
    risk: RiskLevel
    command_id: str


@dataclass
class PermissionPolicy:
    """User-editable permissions. Defaults are conservative."""

    enabled_kinds: set[ActionKind] = field(default_factory=lambda: {
        ActionKind.MOVE_CURSOR, ActionKind.HIGHLIGHT, ActionKind.SCROLL, ActionKind.SHOW_SUGGESTION,
        ActionKind.CLICK, ActionKind.SWITCH_WINDOW, ActionKind.DRAG_START, ActionKind.DRAG_END,
    })
    max_actions_per_second: float = 5.0
    confirmation_ttl_s: float = 30.0


# Kinds with a physical implementation. HIGH-risk kinds are intentionally absent:
# even a confirmed request cannot delete files, pay, install or run commands via ORACLE.
EXECUTABLE_KINDS = {
    ActionKind.MOVE_CURSOR, ActionKind.SCROLL, ActionKind.CLICK, ActionKind.TYPE_TEXT,
    ActionKind.DRAG_START, ActionKind.DRAG_END, ActionKind.SWITCH_WINDOW, ActionKind.LAUNCH_APP,
    ActionKind.HIGHLIGHT, ActionKind.SHOW_SUGGESTION, ActionKind.CHANGE_SETTING,
}
UI_ONLY_KINDS = {ActionKind.HIGHLIGHT, ActionKind.SHOW_SUGGESTION}


@dataclass
class _Confirmation:
    command_id: str
    expires_at: float
    approved: bool = False


class ActionController:
    def __init__(
        self,
        safety: SafetyController,
        adapter: InputAdapter,
        policy: PermissionPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        audit: Callable[[Command, ExecResult], None] | None = None,
    ) -> None:
        self.safety = safety
        self.adapter = adapter
        self.policy = policy or PermissionPolicy()
        self.clock = clock
        self._audit = audit
        self._lock = threading.RLock()
        self._pending: dict[str, Command] = {}
        self._confirmations: dict[str, _Confirmation] = {}
        self._recent: deque[float] = deque(maxlen=64)
        safety.register_cancel_hook(self.cancel_all)

    # ---- confirmation (called only from explicit user interaction in the UI) ----------
    def request_confirmation(self, command: Command) -> str:
        with self._lock:
            self._confirmations[command.id] = _Confirmation(command.id, self.clock() + self.policy.confirmation_ttl_s)
        return command.id

    def approve(self, command_id: str) -> bool:
        with self._lock:
            conf = self._confirmations.get(command_id)
            if conf is None or self.clock() > conf.expires_at:
                return False
            conf.approved = True
            return True

    # ---- pending (e.g. dwell countdown) ----------------------------------------------------
    def begin_pending(self, command: Command) -> str:
        with self._lock:
            self._pending[command.id] = command
        return command.id

    def commit_pending(self, command_id: str) -> ExecResult:
        with self._lock:
            command = self._pending.pop(command_id, None)
        if command is None:
            return ExecResult(ExecStatus.CANCELLED, "no longer pending", RiskLevel.LOW, command_id)
        return self.execute(command)

    def cancel_all(self) -> None:
        with self._lock:
            self._pending.clear()
            self._confirmations.clear()
        try:
            self.adapter.release_all()
        except Exception:
            pass

    # ---- execution -------------------------------------------------------------------------
    def execute(self, command: Command) -> ExecResult:
        result = self._decide_and_run(command)
        if self._audit:
            try:
                self._audit(command, result)
            except Exception:
                pass
        return result

    def _decide_and_run(self, command: Command) -> ExecResult:
        risk = effective_risk(command)

        def res(status: ExecStatus, reason: str) -> ExecResult:
            return ExecResult(status, reason, risk, command.id)

        # 1. Safety gate is checked first and again immediately before the side effect.
        if not self.safety.is_execution_allowed():
            return res(ExecStatus.DENIED, f"safety controller is {self.safety.state.value}")
        # 2. Predictions may only be suggested, never executed.
        if command.source is ActionSource.INFERRED and command.kind not in UI_ONLY_KINDS:
            return res(ExecStatus.DENIED, "inferred intent cannot execute actions; user confirmation required")
        # 3. Capability: no physical implementation => never executable.
        if command.kind not in EXECUTABLE_KINDS:
            return res(ExecStatus.UNSUPPORTED, f"{command.kind.value} is not executable through ORACLE")
        # 4. User permissions.
        if command.kind not in self.policy.enabled_kinds and command.kind not in UI_ONLY_KINDS:
            return res(ExecStatus.DENIED, f"{command.kind.value} is disabled in permissions")
        # 5. Risk gating.
        if risk is RiskLevel.HIGH:
            if command.source is not ActionSource.USER_EXPLICIT:
                return res(ExecStatus.DENIED, "high-risk actions require an explicit user action")
            if not self._consume_confirmation(command.id):
                return res(ExecStatus.NEEDS_CONFIRMATION, "high-risk action needs explicit confirmation")
        # 6. Rate limit (protects against dwell/click storms).
        if risk >= RiskLevel.MEDIUM and not self._rate_ok():
            return res(ExecStatus.DENIED, "rate limit exceeded")
        # 7. Final safety re-check, then perform.
        if not self.safety.is_execution_allowed():
            return res(ExecStatus.CANCELLED, "stopped before execution")
        try:
            self._perform(command)
        except PermissionError as exc:
            return res(ExecStatus.DENIED, str(exc))
        except Exception as exc:
            return res(ExecStatus.FAILED, repr(exc))
        return res(ExecStatus.EXECUTED, "ok")

    def _consume_confirmation(self, command_id: str) -> bool:
        with self._lock:
            conf = self._confirmations.get(command_id)
            if conf is None or not conf.approved or self.clock() > conf.expires_at:
                return False
            del self._confirmations[command_id]  # single use
            return True

    def _rate_ok(self) -> bool:
        now = self.clock()
        with self._lock:
            window = [t for t in self._recent if now - t < 1.0]
            if len(window) >= self.policy.max_actions_per_second:
                return False
            self._recent.append(now)
            return True

    def _perform(self, c: Command) -> None:
        a = self.adapter
        match c.kind:
            case ActionKind.MOVE_CURSOR: a.move_cursor(c.x, c.y)  # type: ignore[arg-type]
            case ActionKind.CLICK: a.click(c.x, c.y)  # type: ignore[arg-type]
            case ActionKind.SCROLL: a.scroll(c.dx or 0, c.dy or 0)
            case ActionKind.TYPE_TEXT: a.type_text(c.text or "")
            case ActionKind.DRAG_START: a.mouse_down(c.x, c.y)  # type: ignore[arg-type]
            case ActionKind.DRAG_END: a.mouse_up(c.x, c.y)  # type: ignore[arg-type]
            case ActionKind.SWITCH_WINDOW: a.focus_window(c.window_handle)  # type: ignore[arg-type]
            case ActionKind.LAUNCH_APP: a.launch_app(c.app_path)  # type: ignore[arg-type]
            case _: pass  # UI-only kinds (highlight/suggestion) have no OS side effect
