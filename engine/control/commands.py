"""Typed, validated commands and risk classification.

Nothing in ORACLE (including any model) can reach the keyboard or mouse except
by constructing a ``Command`` and passing it through ``ActionController``.
"""

from __future__ import annotations

import enum
import re
import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskLevel(enum.IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class ActionKind(str, enum.Enum):
    # low
    MOVE_CURSOR = "move_cursor"
    HIGHLIGHT = "highlight"
    SCROLL = "scroll"
    SHOW_SUGGESTION = "show_suggestion"
    LAUNCH_APP = "launch_app"  # only allow-listed, explicitly selected apps
    # medium
    CLICK = "click"
    SWITCH_WINDOW = "switch_window"
    TYPE_TEXT = "type_text"
    CHANGE_SETTING = "change_setting"
    DRAG_START = "drag_start"
    DRAG_END = "drag_end"
    # high (always need explicit confirmation; most are not executable at all)
    DELETE_FILE = "delete_file"
    SEND_MESSAGE = "send_message"
    PURCHASE = "purchase"
    INSTALL_SOFTWARE = "install_software"
    CHANGE_SECURITY_SETTING = "change_security_setting"
    EXECUTE_COMMAND = "execute_command"
    SUBMIT_FORM = "submit_form"


BASE_RISK: dict[ActionKind, RiskLevel] = {
    ActionKind.MOVE_CURSOR: RiskLevel.LOW,
    ActionKind.HIGHLIGHT: RiskLevel.LOW,
    ActionKind.SCROLL: RiskLevel.LOW,
    ActionKind.SHOW_SUGGESTION: RiskLevel.LOW,
    ActionKind.LAUNCH_APP: RiskLevel.LOW,
    ActionKind.CLICK: RiskLevel.MEDIUM,
    ActionKind.SWITCH_WINDOW: RiskLevel.MEDIUM,
    ActionKind.TYPE_TEXT: RiskLevel.MEDIUM,
    ActionKind.CHANGE_SETTING: RiskLevel.MEDIUM,
    ActionKind.DRAG_START: RiskLevel.MEDIUM,
    ActionKind.DRAG_END: RiskLevel.MEDIUM,
    ActionKind.DELETE_FILE: RiskLevel.HIGH,
    ActionKind.SEND_MESSAGE: RiskLevel.HIGH,
    ActionKind.PURCHASE: RiskLevel.HIGH,
    ActionKind.INSTALL_SOFTWARE: RiskLevel.HIGH,
    ActionKind.CHANGE_SECURITY_SETTING: RiskLevel.HIGH,
    ActionKind.EXECUTE_COMMAND: RiskLevel.HIGH,
    ActionKind.SUBMIT_FORM: RiskLevel.HIGH,
}

# Element labels that escalate a plain click to HIGH risk. Conservative on purpose:
# a false escalation costs one confirmation, a missed one costs a consequential action.
_HIGH_RISK_LABEL = re.compile(
    r"\b(delete|remove|erase|format|uninstall|install|send|submit|pay|purchase|buy|"
    r"checkout|place order|confirm order|sign out|log ?out|empty recycle|"
    r"run as administrator|allow|grant|firewall|security|password|transfer|wire)\b",
    re.IGNORECASE,
)


class ActionSource(str, enum.Enum):
    USER_EXPLICIT = "user_explicit"  # deliberate UI click / hotkey in ORACLE itself
    DWELL = "dwell"  # user-configured dwell selection
    GESTURE = "gesture"  # user-configured deliberate gesture (e.g. long blink)
    INFERRED = "inferred"  # produced by prediction; may only be *suggested*


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: ActionKind
    source: ActionSource
    x: Optional[int] = None
    y: Optional[int] = None
    dx: Optional[int] = Field(default=None, ge=-5000, le=5000)
    dy: Optional[int] = Field(default=None, ge=-5000, le=5000)
    text: Optional[str] = Field(default=None, max_length=500)
    target_id: Optional[str] = Field(default=None, max_length=200)
    target_label: Optional[str] = Field(default=None, max_length=300)
    app_path: Optional[str] = Field(default=None, max_length=500)
    window_handle: Optional[int] = None

    @model_validator(mode="after")
    def _check_shape(self) -> "Command":
        pointer = {ActionKind.MOVE_CURSOR, ActionKind.CLICK, ActionKind.DRAG_START, ActionKind.DRAG_END}
        if self.kind in pointer and (self.x is None or self.y is None):
            raise ValueError(f"{self.kind.value} requires x and y")
        if self.kind is ActionKind.SCROLL and self.dy is None and self.dx is None:
            raise ValueError("scroll requires dx or dy")
        if self.kind is ActionKind.TYPE_TEXT and not self.text:
            raise ValueError("type_text requires text")
        if self.kind is ActionKind.LAUNCH_APP and not self.app_path:
            raise ValueError("launch_app requires app_path")
        if self.kind is ActionKind.SWITCH_WINDOW and self.window_handle is None:
            raise ValueError("switch_window requires window_handle")
        return self


def effective_risk(command: Command) -> RiskLevel:
    """Base risk of the kind, escalated by what the target looks like."""
    risk = BASE_RISK[command.kind]
    label = " ".join(filter(None, [command.target_label, command.text if command.kind is ActionKind.CLICK else None]))
    if command.kind in {ActionKind.CLICK, ActionKind.TYPE_TEXT, ActionKind.CHANGE_SETTING} and label:
        if _HIGH_RISK_LABEL.search(label):
            return RiskLevel.HIGH
    return risk
