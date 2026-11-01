"""Screen model: windows and interactive elements in virtual-desktop pixels."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

INTERACTIVE_TYPES = {
    "Button", "Hyperlink", "MenuItem", "TabItem", "CheckBox", "RadioButton", "ComboBox", "ListItem",
    "TreeItem", "Edit", "Document", "ScrollBar", "Slider", "SplitButton", "Thumb", "TitleBar", "Region",
}
TEXT_INPUT_TYPES = {"Edit", "Document", "ComboBox"}


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int: return max(self.right - self.left, 0)
    @property
    def height(self) -> int: return max(self.bottom - self.top, 0)
    @property
    def area(self) -> int: return self.width * self.height
    @property
    def center(self) -> tuple[float, float]: return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def distance_to(self, x: float, y: float) -> float:
        """Euclidean distance from a point to the rectangle (0 inside)."""
        dx = max(self.left - x, 0, x - self.right)
        dy = max(self.top - y, 0, y - self.bottom)
        return (dx * dx + dy * dy) ** 0.5


@dataclass(frozen=True)
class UIElement:
    id: str
    name: str
    control_type: str
    rect: Rect
    app: str = ""
    window_handle: int = 0
    automation_id: str = ""
    enabled: bool = True
    z_order: int = 0  # 0 = topmost window
    depth: int = 0
    source: str = "uia"  # "uia" | "vision"

    @property
    def interactive(self) -> bool:
        return self.enabled and self.control_type in INTERACTIVE_TYPES and self.rect.area > 0

    @property
    def accepts_text(self) -> bool:
        return self.control_type in TEXT_INPUT_TYPES

    @property
    def key(self) -> str:
        """Stable identity across snapshots (position-independent) for learning."""
        raw = f"{self.app}|{self.control_type}|{self.automation_id or self.name}".lower()
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    app: str
    rect: Rect
    z_order: int = 0
    foreground: bool = False


@dataclass
class ScreenSnapshot:
    taken_at: float
    windows: list[WindowInfo] = field(default_factory=list)
    elements: list[UIElement] = field(default_factory=list)

    @property
    def foreground(self) -> WindowInfo | None:
        return next((w for w in self.windows if w.foreground), None)

    def window_at(self, x: float, y: float) -> WindowInfo | None:
        hits = [w for w in self.windows if w.rect.contains(x, y)]
        return min(hits, key=lambda w: w.z_order) if hits else None
