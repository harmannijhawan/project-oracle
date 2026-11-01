"""Validated message and settings schemas (pydantic). Everything crossing the API boundary is typed."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from engine.safety.hotkey import parse_shortcut


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Settings(Strict):
    dwell_s: float = Field(1.0, ge=0.3, le=5.0)
    dwell_radius_px: float = Field(60.0, ge=15, le=300)
    smoothing: float = Field(1.0, ge=0.1, le=5.0)  # One-Euro min_cutoff: lower = steadier
    deadzone_px: float = Field(6.0, ge=0, le=60)
    min_quality: float = Field(0.5, ge=0.2, le=0.95)
    emergency_shortcut: str = "Ctrl+Alt+Shift+Q"
    cursor_control: bool = False  # off until the user turns it on
    dwell_click: bool = False  # off until the user turns it on
    gestures_enabled: bool = False
    enabled_actions: list[str] = Field(default_factory=lambda: ["move_cursor", "highlight", "scroll", "show_suggestion",
                                                                 "click", "switch_window", "drag_start", "drag_end"])
    camera_index: int = Field(0, ge=0, le=16)
    abstain_below: float = Field(0.65, ge=0.5, le=0.95)

    @field_validator("emergency_shortcut")
    @classmethod
    def _valid_shortcut(cls, v: str) -> str:
        parse_shortcut(v)
        return v


class SettingsPatch(Strict):
    dwell_s: float | None = Field(None, ge=0.3, le=5.0)
    dwell_radius_px: float | None = Field(None, ge=15, le=300)
    smoothing: float | None = Field(None, ge=0.1, le=5.0)
    deadzone_px: float | None = Field(None, ge=0, le=60)
    min_quality: float | None = Field(None, ge=0.2, le=0.95)
    emergency_shortcut: str | None = None
    cursor_control: bool | None = None
    dwell_click: bool | None = None
    gestures_enabled: bool | None = None
    enabled_actions: list[str] | None = None
    camera_index: int | None = Field(None, ge=0, le=16)
    abstain_below: float | None = Field(None, ge=0.5, le=0.95)

    @field_validator("emergency_shortcut")
    @classmethod
    def _valid_shortcut(cls, v: str | None) -> str | None:
        if v is not None:
            parse_shortcut(v)
        return v


class StartTracking(Strict):
    camera_index: int | None = Field(None, ge=0, le=16)
    simulate: bool = False


class CalibrationTarget(Strict):
    tx: float = Field(ge=0.0, le=1.0)
    ty: float = Field(ge=0.0, le=1.0)


class Resume(Strict):
    confirmed: bool


class ControlToggle(Strict):
    enabled: bool


class Feedback(Strict):
    suggestion_key: str = Field(max_length=64)
    outcome: Literal["confirmed", "rejected", "corrected"]
    corrected_to_key: str | None = Field(None, max_length=64)


class NewTrial(Strict):
    session_id: str
    option_a: str = Field(min_length=1, max_length=100)
    option_b: str = Field(min_length=1, max_length=100)


class Answer(Strict):
    side: Literal["left", "right"]


class DeleteRequest(Strict):
    confirm: Literal["DELETE"]


# ---- WebSocket client messages (discriminated union) -----------------------------------------
class WsEmergencyStop(Strict):
    type: Literal["emergency_stop"]


class WsResume(Strict):
    type: Literal["resume"]
    confirmed: bool


class WsCursorControl(Strict):
    type: Literal["set_cursor_control"]
    enabled: bool


class WsFeedback(Strict):
    type: Literal["feedback"]
    suggestion_key: str = Field(max_length=64)
    outcome: Literal["confirmed", "rejected"]


class WsPing(Strict):
    type: Literal["ping"]


ClientMessage = Annotated[Union[WsEmergencyStop, WsResume, WsCursorControl, WsFeedback, WsPing], Field(discriminator="type")]
