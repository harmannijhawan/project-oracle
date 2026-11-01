"""Multi-monitor geometry. Calibration is per monitor; output is virtual-desktop pixels."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Monitor:
    id: str
    left: int
    top: int
    width: int
    height: int
    primary: bool = False

    @property
    def right(self) -> int: return self.left + self.width
    @property
    def bottom(self) -> int: return self.top + self.height

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def to_pixels(self, nx: float, ny: float) -> tuple[int, int]:
        """Normalised (0..1, clamped) -> virtual-desktop pixel on this monitor."""
        nx, ny = min(max(nx, 0.0), 1.0), min(max(ny, 0.0), 1.0)
        return (self.left + round(nx * (self.width - 1)), self.top + round(ny * (self.height - 1)))

    def to_normalised(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.left) / self.width, (y - self.top) / self.height


def monitor_at(monitors: list[Monitor], x: float, y: float) -> Monitor | None:
    return next((m for m in monitors if m.contains(x, y)), None)


def enumerate_monitors() -> list[Monitor]:
    """Real monitors on Windows via EnumDisplayMonitors; a single 1920x1080 fallback elsewhere."""
    import sys

    if sys.platform != "win32":
        return [Monitor("fallback", 0, 0, 1920, 1080, primary=True)]
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    found: list[Monitor] = []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    proc_t = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                                ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _rect, _lp):  # type: ignore[no-untyped-def]
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcMonitor
        found.append(Monitor(f"mon{len(found)}", r.left, r.top, r.right - r.left, r.bottom - r.top,
                             primary=bool(info.dwFlags & 1)))
        return 1

    user32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
    return found or [Monitor("fallback", 0, 0, 1920, 1080, primary=True)]
