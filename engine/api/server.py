"""Backend entry point: ``python -m engine.api.server --port N`` (token via ORACLE_TOKEN env)."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import secrets
import sys
from pathlib import Path

import uvicorn

from engine.safety import StopReason
from engine.safety.hotkey import GlobalHotkey

from .app import create_app
from .service import OracleService


def default_data_dir() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))
    return Path(base or Path.home()) / "ORACLE"


def build_service(data_dir: Path) -> OracleService:
    from engine.screen_context import default_provider

    adapter = None
    if sys.platform == "win32":
        from engine.control.input_adapter import WindowsInputAdapter

        adapter = WindowsInputAdapter()
    return OracleService(data_dir, adapter=adapter, screen=default_provider())


def camera_factory(index: int, service: OracleService):  # type: ignore[no-untyped-def]
    from engine.camera.capture import CameraSource

    return CameraSource(index, on_error=service.on_camera_error)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--data-dir", type=Path, default=default_data_dir())
    args = ap.parse_args(argv)
    token = os.environ.get("ORACLE_TOKEN") or secrets.token_urlsafe(32)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[logging.handlers.RotatingFileHandler(args.data_dir / "backend.log", maxBytes=2_000_000, backupCount=3)])
    service = build_service(args.data_dir)
    hotkey = GlobalHotkey(service.settings.emergency_shortcut, lambda: service.emergency_stop(StopReason.USER_SHORTCUT))
    registered = hotkey.start()
    logging.info("backend hotkey %s registered=%s", service.settings.emergency_shortcut, registered)
    app = create_app(service, token, camera_factory)
    config = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", ws_max_size=1 << 16)
    server = uvicorn.Server(config)
    import threading

    def announce() -> None:
        import time

        while not server.started:
            time.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        print(f"ORACLE_READY {port} hotkey={'ok' if registered else 'unavailable'}", flush=True)

    threading.Thread(target=announce, daemon=True).start()
    try:
        server.run()
    finally:
        hotkey.stop()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
