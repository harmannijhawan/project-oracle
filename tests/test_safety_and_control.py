import pytest

from engine.control import (ActionController, ActionKind, ActionSource, Command, ExecStatus,
                            PermissionPolicy, RecordingInputAdapter, RiskLevel, effective_risk)
from engine.safety import SafetyConfig, SafetyController, SafetyState, StopReason


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def make(clock=None, **policy):
    clock = clock or Clock()
    safety = SafetyController(config=SafetyConfig(), clock=clock)
    adapter = RecordingInputAdapter()
    ctrl = ActionController(safety, adapter, PermissionPolicy(**policy) if policy else None, clock=clock)
    return clock, safety, adapter, ctrl


def click(label=None, source=ActionSource.DWELL, **kw):
    return Command(kind=ActionKind.CLICK, source=source, x=10, y=20, target_label=label, **kw)


def test_dwell_click_executes_when_active():
    _, _, adapter, ctrl = make()
    assert ctrl.execute(click()).status is ExecStatus.EXECUTED
    assert adapter.calls == [("click", 10, 20)]


def test_emergency_stop_blocks_everything_and_cancels_pending():
    _, safety, adapter, ctrl = make()
    pid = ctrl.begin_pending(click())
    safety.emergency_stop(StopReason.USER_SHORTCUT)
    assert ctrl.commit_pending(pid).status is ExecStatus.CANCELLED
    assert ctrl.execute(click()).status is ExecStatus.DENIED
    assert adapter.calls == []


def test_emergency_stop_releases_held_mouse_button():
    _, safety, adapter, ctrl = make()
    ctrl.execute(Command(kind=ActionKind.DRAG_START, source=ActionSource.USER_EXPLICIT, x=1, y=1))
    assert adapter.button_down
    safety.emergency_stop()
    assert not adapter.button_down


def test_stop_works_even_if_hook_raises():
    _, safety, _, _ = make()
    safety.register_cancel_hook(lambda: 1 / 0)
    safety.emergency_stop()
    assert safety.state is SafetyState.STOPPED


def test_resume_requires_explicit_confirmation():
    _, safety, _, _ = make()
    safety.emergency_stop()
    assert not safety.manual_resume(confirmed=False)
    assert safety.state is SafetyState.STOPPED
    assert safety.manual_resume(confirmed=True)
    assert safety.is_execution_allowed()


def test_camera_timeout_auto_pauses_and_resume_needs_healthy_camera():
    clock, safety, _, ctrl = make()
    safety.report_camera_frame()
    clock.t = 5.0
    safety.tick()
    assert safety.state is SafetyState.AUTO_PAUSED and safety.reason is StopReason.CAMERA_FAILURE
    assert ctrl.execute(click()).status is ExecStatus.DENIED
    assert not safety.manual_resume(confirmed=True)  # still no frames
    safety.report_camera_frame()
    assert safety.manual_resume(confirmed=True)


def test_sustained_poor_tracking_auto_pauses_but_blips_do_not():
    clock, safety, _, _ = make()
    safety.report_tracking_quality(0.1)
    clock.t = 0.5
    safety.report_tracking_quality(0.1)
    assert safety.is_execution_allowed()
    clock.t = 0.9
    safety.report_tracking_quality(0.9)  # recovered; timer resets
    clock.t = 1.0
    safety.report_tracking_quality(0.1)
    clock.t = 2.0
    safety.report_tracking_quality(0.1)
    assert safety.is_execution_allowed()
    clock.t = 3.0
    safety.report_tracking_quality(0.1)
    assert safety.state is SafetyState.AUTO_PAUSED


def test_user_stop_outranks_auto_pause():
    _, safety, _, _ = make()
    safety.report_camera_error("boom")
    safety.emergency_stop()
    assert safety.state is SafetyState.STOPPED


def test_inferred_source_can_never_execute():
    _, _, adapter, ctrl = make()
    r = ctrl.execute(click(source=ActionSource.INFERRED))
    assert r.status is ExecStatus.DENIED and adapter.calls == []


def test_risky_label_escalates_to_high_and_needs_confirmation():
    _, _, adapter, ctrl = make()
    cmd = click("Delete all files", source=ActionSource.USER_EXPLICIT)
    assert effective_risk(cmd) is RiskLevel.HIGH
    assert ctrl.execute(cmd).status is ExecStatus.NEEDS_CONFIRMATION
    ctrl.request_confirmation(cmd)
    assert ctrl.execute(cmd).status is ExecStatus.NEEDS_CONFIRMATION  # requested but not approved
    assert ctrl.approve(cmd.id)
    assert ctrl.execute(cmd).status is ExecStatus.EXECUTED
    assert ctrl.execute(cmd).status is ExecStatus.NEEDS_CONFIRMATION  # single use
    assert len(adapter.calls) == 1


def test_high_risk_by_dwell_is_denied_even_with_confirmation_record():
    _, _, _, ctrl = make()
    cmd = click("Send", source=ActionSource.DWELL)
    ctrl.request_confirmation(cmd)
    ctrl.approve(cmd.id)
    assert ctrl.execute(cmd).status is ExecStatus.DENIED


def test_confirmation_expires():
    clock, _, _, ctrl = make()
    cmd = click("Purchase", source=ActionSource.USER_EXPLICIT)
    ctrl.request_confirmation(cmd)
    ctrl.approve(cmd.id)
    clock.t = 100
    assert ctrl.execute(cmd).status is ExecStatus.NEEDS_CONFIRMATION


@pytest.mark.parametrize("kind", [ActionKind.DELETE_FILE, ActionKind.EXECUTE_COMMAND, ActionKind.PURCHASE,
                                   ActionKind.INSTALL_SOFTWARE, ActionKind.SEND_MESSAGE])
def test_destructive_kinds_are_unsupported_even_when_confirmed(kind):
    _, _, _, ctrl = make()
    cmd = Command(kind=kind, source=ActionSource.USER_EXPLICIT)
    ctrl.request_confirmation(cmd)
    ctrl.approve(cmd.id)
    assert ctrl.execute(cmd).status is ExecStatus.UNSUPPORTED


def test_disabled_kind_is_denied_and_type_text_off_by_default():
    _, _, adapter, ctrl = make()
    cmd = Command(kind=ActionKind.TYPE_TEXT, source=ActionSource.USER_EXPLICIT, text="hello")
    assert ctrl.execute(cmd).status is ExecStatus.DENIED
    assert adapter.calls == []


def test_rate_limit_stops_click_storm():
    _, _, adapter, ctrl = make(max_actions_per_second=3)
    statuses = [ctrl.execute(click()).status for _ in range(6)]
    assert statuses.count(ExecStatus.EXECUTED) == 3
    assert len(adapter.calls) == 3


def test_command_validation():
    with pytest.raises(ValueError):
        Command(kind=ActionKind.CLICK, source=ActionSource.DWELL)
    with pytest.raises(ValueError):
        Command(kind=ActionKind.CLICK, source=ActionSource.DWELL, x=1, y=1, bogus=1)
