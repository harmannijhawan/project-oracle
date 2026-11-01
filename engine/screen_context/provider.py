"""Screen providers. ``ScreenProvider`` is the seam between Windows UI Automation and tests."""

from __future__ import annotations

import sys
import time
from typing import Protocol

from .model import Rect, ScreenSnapshot, UIElement, WindowInfo


class ScreenProvider(Protocol):
    def snapshot(self) -> ScreenSnapshot: ...


class StaticScreenProvider:
    """Deterministic provider for tests and simulation."""

    def __init__(self, snapshot: ScreenSnapshot | None = None) -> None:
        self._snap = snapshot or ScreenSnapshot(time.monotonic())

    def set(self, snapshot: ScreenSnapshot) -> None:
        self._snap = snapshot

    def snapshot(self) -> ScreenSnapshot:
        return self._snap


class CachedProvider:
    """Wraps a slow provider; UIA tree walks are expensive so reuse a snapshot for ``ttl_s``."""

    def __init__(self, inner: ScreenProvider, ttl_s: float = 0.5, clock=time.monotonic) -> None:
        self.inner, self.ttl_s, self.clock = inner, ttl_s, clock
        self._snap: ScreenSnapshot | None = None
        self._at = -1e9

    def invalidate(self) -> None:
        self._at = -1e9

    def snapshot(self) -> ScreenSnapshot:
        now = self.clock()
        if self._snap is None or now - self._at > self.ttl_s:
            try:
                self._snap, self._at = self.inner.snapshot(), now
            except Exception:
                if self._snap is None:
                    raise
        return self._snap


class UIAutomationProvider:
    """Windows UI Automation via the ``uiautomation`` package.

    Walks the foreground window (bounded depth/count) and lists top-level windows. Hardware/OS
    dependent: validated on Windows 11 only (docs/HARDWARE_VALIDATION.md). Local only.
    """

    def __init__(self, max_elements: int = 400, max_depth: int = 12) -> None:
        if sys.platform != "win32":
            raise RuntimeError("UIAutomationProvider is only available on Windows")
        import uiautomation as auto  # type: ignore[import-not-found]

        self._auto = auto
        self.max_elements, self.max_depth = max_elements, max_depth

    def _rect(self, ctrl) -> Rect | None:  # type: ignore[no-untyped-def]
        r = ctrl.BoundingRectangle
        if r is None or r.right <= r.left or r.bottom <= r.top:
            return None
        return Rect(int(r.left), int(r.top), int(r.right), int(r.bottom))

    def snapshot(self) -> ScreenSnapshot:
        auto = self._auto
        snap = ScreenSnapshot(time.monotonic())
        fg = auto.GetForegroundControl()
        fg_handle = fg.NativeWindowHandle if fg else 0
        for z, w in enumerate(auto.GetRootControl().GetChildren()):
            rect = self._rect(w)
            if rect is None or w.IsOffscreen:
                continue
            handle = int(w.NativeWindowHandle or 0)
            snap.windows.append(WindowInfo(handle, w.Name or "", _process_name(w), rect, z,
                                           foreground=bool(fg_handle) and handle == int(fg_handle)))
        top = fg.GetTopLevelControl() if fg else None
        if top is not None:
            self._walk(top, snap, int(top.NativeWindowHandle or 0), _process_name(top),
                       next((w.z_order for w in snap.windows if w.foreground), 0))
        return snap

    def _walk(self, root, snap: ScreenSnapshot, handle: int, app: str, z: int) -> None:  # type: ignore[no-untyped-def]
        stack = [(root, 0)]
        while stack and len(snap.elements) < self.max_elements:
            ctrl, depth = stack.pop()
            try:
                rect = self._rect(ctrl)
                ctype = ctrl.ControlTypeName.replace("Control", "")
                if rect is not None and not ctrl.IsOffscreen:
                    snap.elements.append(UIElement(f"{handle}:{len(snap.elements)}", ctrl.Name or "", ctype, rect, app,
                                                   handle, ctrl.AutomationId or "", bool(ctrl.IsEnabled), z, depth))
                if depth < self.max_depth:
                    stack.extend((c, depth + 1) for c in reversed(ctrl.GetChildren()))
            except Exception:
                continue  # elements can vanish mid-walk


def _process_name(ctrl) -> str:  # type: ignore[no-untyped-def]
    try:
        import psutil  # type: ignore[import-not-found]
        return psutil.Process(ctrl.ProcessId).name()
    except Exception:
        return f"pid{getattr(ctrl, 'ProcessId', 0)}"


def default_provider() -> ScreenProvider:
    """UIA on Windows; an empty static provider elsewhere (the UI reports 'unavailable')."""
    if sys.platform == "win32":
        try:
            return CachedProvider(UIAutomationProvider())
        except Exception:
            pass
    return StaticScreenProvider()
