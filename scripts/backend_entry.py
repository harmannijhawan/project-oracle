"""PyInstaller entry point. server.py uses package-relative imports, so it cannot be the entry script itself."""

import multiprocessing

from engine.api.server import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
