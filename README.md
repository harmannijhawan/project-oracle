# project-oracle
PROJECT ORACLE: local-first, eye-controlled and face-intelligent Windows desktop interface (Electron, React, Python, MediaPipe).

## Desktop app and installer

The Windows app lives in `desktop/` (Electron main process in `desktop/electron/`, React UI in `desktop/src/`).
Electron starts the Python engine (`engine/api/server.py`) on a random loopback port with a per-run token, proxies
every REST call from the UI through the main process, and runs its own independent safety net (global emergency
shortcuts, an engine watchdog, stop on screen lock or suspend).

Development (two terminals, Python 3.11+ and Node 20+):

```
pip install -e ".[dev]" && python scripts/fetch_models.py
cd desktop && npm install
npm run dev                          # Vite on http://localhost:5173
ORACLE_DEV_URL=http://localhost:5173 npx electron .   # after: npm run build:electron
```

Build the installer locally on Windows:

```
python scripts/fetch_models.py
python scripts/build_backend.py      # PyInstaller -> backend-dist/oracle-engine/
cd desktop && npm install && npm run dist   # -> desktop/release/Project-Oracle-Setup.exe
```

### Publishing the installer (GitHub Actions)

The workflows are stored in `ci/` because pushing to `.github/workflows/` needs a token with the `workflow` scope.
Enable them once:

```
mkdir -p .github/workflows
git mv ci/ci.yml ci/release.yml .github/workflows/
git commit -m "Enable workflows" && git push
```

Then push a tag (`git tag v0.1.0 && git push origin v0.1.0`) or run **Build Windows installer** from the Actions tab
with a tag name. It runs the engine tests, freezes the engine with PyInstaller, builds the NSIS installer and
publishes `Project-Oracle-Setup.exe` plus a SHA-256 file as a GitHub Release, which is what the download page links
to. The installer is not code-signed, so Windows SmartScreen will warn on first run.
