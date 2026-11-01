"""OS input adapters. The controller depends only on the ``InputAdapter`` protocol."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Protocol


class InputAdapter(Protocol):
    def move_cursor(self, x: int, y: int) -> None: ...
    def click(self, x: int, y: int) -> None: ...
    def scroll(self, dx: int, dy: int) -> None: ...
    def type_text(self, text: str) -> None: ...
    def mouse_down(self, x: int, y: int) -> None: ...
    def mouse_up(self, x: int, y: int) -> None: ...
    def focus_window(self, handle: int) -> None: ...
    def launch_app(self, path: str) -> None: ...
    def release_all(self) -> None:
        """Release any held button/key. Called on every emergency stop."""


# Kinds the adapter can physically perform. Anything else is UNSUPPORTED by design:
# there is intentionally no way to delete files or run shell commands through ORACLE.
@dataclass
class RecordingInputAdapter:
    """Deterministic adapter for tests and simulated hardware harnesses."""

    calls: list[tuple] = field(default_factory=list)
    button_down: bool = False

    def move_cursor(self, x: int, y: int) -> None: self.calls.append(("move", x, y))
    def click(self, x: int, y: int) -> None: self.calls.append(("click", x, y))
    def scroll(self, dx: int, dy: int) -> None: self.calls.append(("scroll", dx, dy))
    def type_text(self, text: str) -> None: self.calls.append(("type", text))
    def focus_window(self, handle: int) -> None: self.calls.append(("focus", handle))
    def launch_app(self, path: str) -> None: self.calls.append(("launch", path))

    def mouse_down(self, x: int, y: int) -> None:
        self.button_down = True
        self.calls.append(("down", x, y))

    def mouse_up(self, x: int, y: int) -> None:
        self.button_down = False
        self.calls.append(("up", x, y))

    def release_all(self) -> None:
        if self.button_down:
            self.button_down = False
            self.calls.append(("release_all",))


class WindowsInputAdapter:
    """Win32 implementation (SetCursorPos / SendInput).

    Hardware-dependent: written against the documented Win32 API but must be
    validated on a real Windows 11 machine (see docs/HARDWARE_VALIDATION.md).
    """

    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_HWHEEL = 0x01000

    def __init__(self, allowed_apps: set[str] | None = None) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsInputAdapter is only available on Windows")
        import ctypes

        self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        self._ctypes = ctypes
        self._down = False
        self._allowed = {os.path.normcase(os.path.abspath(p)) for p in (allowed_apps or set())}

    def move_cursor(self, x: int, y: int) -> None:
        self._user32.SetCursorPos(int(x), int(y))

    def click(self, x: int, y: int) -> None:
        self.move_cursor(x, y)
        self._user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        self._user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def mouse_down(self, x: int, y: int) -> None:
        self.move_cursor(x, y)
        self._user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        self._down = True

    def mouse_up(self, x: int, y: int) -> None:
        self.move_cursor(x, y)
        self._user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        self._down = False

    def scroll(self, dx: int, dy: int) -> None:
        if dy:
            self._user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, self._ctypes.c_uint(dy).value, 0)
        if dx:
            self._user32.mouse_event(self.MOUSEEVENTF_HWHEEL, 0, 0, self._ctypes.c_uint(dx).value, 0)

    def type_text(self, text: str) -> None:
        ctypes = self._ctypes
        wintypes = ctypes.wintypes if hasattr(ctypes, "wintypes") else __import__("ctypes.wintypes").wintypes

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class MOUSEINPUT(ctypes.Structure):  # sizes the union correctly
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        KEYEVENTF_UNICODE, KEYEVENTF_KEYUP = 0x0004, 0x0002
        for ch in text:
            for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                inp = INPUT(type=1, u=_U(ki=KEYBDINPUT(0, ord(ch), flags, 0, 0)))
                self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def focus_window(self, handle: int) -> None:
        self._user32.SetForegroundWindow(int(handle))

    def launch_app(self, path: str) -> None:
        resolved = os.path.normcase(os.path.abspath(path))
        if resolved not in self._allowed:
            raise PermissionError(f"{path} is not on the launch allow-list")
        os.startfile(resolved)  # type: ignore[attr-defined]

    def release_all(self) -> None:
        if self._down:
            self._user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            self._down = False
