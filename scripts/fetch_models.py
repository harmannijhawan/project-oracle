"""Download the MediaPipe Face Landmarker model into models/ (build-time only; runtime is fully offline)."""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
DEST = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"


def main() -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists() and DEST.stat().st_size > 1_000_000:
        print(f"already present: {DEST}")
        return 0
    urllib.request.urlretrieve(URL, DEST)
    digest = hashlib.sha256(DEST.read_bytes()).hexdigest()
    if DEST.stat().st_size < 1_000_000:
        print("download looks truncated", file=sys.stderr)
        return 1
    print(f"downloaded {DEST} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
