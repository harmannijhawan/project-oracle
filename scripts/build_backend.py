"""Freeze the Python engine into backend-dist/oracle-engine/ (onedir) with PyInstaller.

Run from the repository root on the target OS (Windows for the shipped installer):

    python scripts/fetch_models.py
    python scripts/build_backend.py

The face-landmarker model is bundled so the installed app is fully offline.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "face_landmarker.task"


def main() -> int:
    if not MODEL.is_file():
        print(f"missing {MODEL}; run scripts/fetch_models.py first", file=sys.stderr)
        return 1
    import PyInstaller.__main__ as pyi

    out = ROOT / "backend-dist"
    shutil.rmtree(out, ignore_errors=True)
    sep = os.pathsep
    args = [
        str(ROOT / "scripts" / "backend_entry.py"),
        "--name", "oracle-engine",
        "--onedir",
        "--noconfirm",
        "--console",  # Electron spawns it hidden; a console build keeps stdout (ORACLE_READY) readable
        "--distpath", str(out),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT),
        "--add-data", f"{MODEL}{sep}models",
        "--collect-all", "mediapipe",
        "--collect-submodules", "engine",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "websockets",
        "--collect-submodules", "sklearn",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pytest",
    ]
    if sys.platform == "win32":
        args += ["--collect-all", "uiautomation", "--collect-all", "comtypes"]
    pyi.run(args)
    exe = out / "oracle-engine" / ("oracle-engine.exe" if sys.platform == "win32" else "oracle-engine")
    if not exe.is_file():
        print(f"build did not produce {exe}", file=sys.stderr)
        return 1
    print(f"built {exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
