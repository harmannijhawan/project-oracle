"""Independent global emergency-stop hotkey (Win32 RegisterHotKey) living inside the backend.

Electron registers its own shortcut as well; this one keeps working if the UI process dies.
It depends only on the SafetyController (no models, no camera).
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

MODS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
SPECIAL = {"esc": 0x1B, "escape": 0x1B, "pause": 0x13, "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
           "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B, "space": 0x20}
WM_HOTKEY, MOD_NOREPEAT = 0x0312, 0x4000


def parse_shortcut(spec: str) -> tuple[int, int]:
    """'Ctrl+Alt+Shift+Q' -> (modifier_flags, virtual_key). Requires >= 1 modifier (or an F-key/Pause/Esc)."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty shortcut")
    *mods, key = parts
    flags = 0
    for m in mods:
        if m not in MODS:
            raise ValueError(f"unknown modifier {m!r}")
        flags |= MODS[m]
    if key in SPECIAL:
        vk = SPECIAL[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"unsupported key {key!r}")
    if flags == 0 and not (key in SPECIAL and key != "space"):
        raise ValueError("a single plain key would break normal typing; add a modifier")
    return flags, vk


class GlobalHotkey:
    def __init__(self, spec: str, on_trigger: Callable[[], None]) -> None:
        self.spec, self.on_trigger = spec, on_trigger
        self.flags, self.vk = parse_shortcut(spec)  # validates on every platform
        self.registered = False
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()

    def start(self) -> bool:
        """Returns True if the OS accepted the hotkey. No-op (False) off Windows."""
        if sys.platform != "win32":
            return False
        self._thread = threading.Thread(target=self._run, name="oracle-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(2)
        return self.registered

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._tid = kernel32.GetCurrentThreadId()
        self.registered = bool(user32.RegisterHotKey(None, 1, self.flags | MOD_NOREPEAT, self.vk))
        self._ready.set()
        if not self.registered:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    self.on_trigger()
                except Exception:
                    pass
        user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if sys.platform == "win32" and self._tid:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # type: ignore[attr-defined]
