# PROJECT ORACLE - Architecture

ORACLE is a local-first Windows desktop interface controlled by gaze and facial movement from an ordinary webcam.
It separates four things that must never be confused: **where the user looks** (attention), **what they might
want** (inference), **what they explicitly confirm** (consent) and **what actually happens** (action).
It is not mind reading: facial signals are measured behaviour, and every prediction reports uncertainty and may abstain.

## 1. System overview

```
 Electron main (TypeScript)                    Python backend (FastAPI, 127.0.0.1 only)
 +-------------------------+   HTTP + WS    +-------------------------------------------------+
 | backend-manager         |<-------------->| api/app.py   token-auth REST + WebSocket        |
 | safety-manager (hotkey) |   token        | api/service.py  OracleService (orchestrator)    |
 | preload (contextBridge) |                |   camera/  -> face/ -> features/ -> gaze/        |
 +-----------+-------------+                |   screen_context/ (Engine C)                    |
             | contextBridge                |   brain/ (Engine D)                              |
 +-----------v-------------+                |   control/ (typed commands, permissions)         |
 | React renderer (Vite)   |                |   safety/ (independent stop)                     |
 | 10 pages, WS client     |                |   experiments/ prediction/ storage/ (SQLite)     |
 +-------------------------+                +-------------------------------------------------+
```

## 2. The four engines

| Engine | Package | Responsibility |
|---|---|---|
| A - Eye | `gaze/`, `camera/`, `face/` | webcam -> landmarks -> iris/head features -> 9-point calibration -> normalised screen point -> One-Euro smoothing -> dead-zone -> dwell. Measured leave-one-target-out calibration error is reported in pixels. Estimator is a `Protocol` so better algorithms or hardware trackers plug in. |
| B - Face | `features/`, `experiments/`, `prediction/` | feature extraction, personal baseline (Welford), window summaries, randomised choice trials with commit-before-reveal locking, LR/RF/GB selection with session-grouped CV, calibration, abstention, honest evaluation vs random and context-only baselines. A temporal NN is a documented later experiment (not enabled: too little data to justify it). |
| C - Vision | `screen_context/` | Windows UI Automation snapshot (foreground window, interactive elements, rectangles, app/process), hit-testing of gaze to elements, snapshot cache, OpenCV region fallback for apps with poor accessibility. All local. |
| D - Brain | `brain/` | deterministic, explainable ranking of candidate interactions from gaze geometry, dwell, tracking quality, personal history, rejections. Produces suggestions with evidence + confidence + ambiguity flag. It never executes anything. |

## 3. Data flow (one frame)
1. `camera.CameraSource` grabs a frame; `face.FaceLandmarker` (MediaPipe Face Landmarker, 478 pts) returns landmarks.
2. `features.extract_frame_features` -> feature dict; `QualityMonitor` -> quality in [0,1]; `SafetyController.report_camera_frame`.
3. `GazeCursorPipeline.process` -> filtered pixel + `DwellState` (or `None` if unreliable; also reports quality to Safety).
4. `ScreenContext` snapshot (cached) -> `ElementIndex.at(x, y)` candidates.
5. `OracleBrain.observe` -> ranked `Suggestion`s (never an action).
6. If the user enabled cursor control, `ActionController.execute(MOVE_CURSOR)`. If dwell fired on a target, the brain's
   `command_for(..., source=DWELL)` is passed through the controller (permissions, risk, rate limit, safety re-check).
7. State + suggestions are broadcast to the UI over WebSocket. The user confirms/rejects; both outcomes are stored and
   feed back into history.

## 4. Electron <-> Python
* Electron main spawns the backend (`backend-manager.ts`) on a random free port with a random 256-bit token passed via env.
* Backend binds `127.0.0.1` only, requires the token (header or WS query) and checks the WS `Origin`.
* Renderer talks only through `contextBridge` (`preload.ts`): `contextIsolation: true`, `nodeIntegration: false`,
  `sandbox: true`, strict CSP, navigation and `window.open` blocked. The renderer gets backend URL+token via IPC.
* All client messages are validated by pydantic discriminated unions (`api/schemas.py`); invalid input returns an error event.

## 5. Camera pipeline
OpenCV `VideoCapture` (DirectShow on Windows) in a worker thread, latest-frame-wins so latency never accumulates,
MediaPipe Face Landmarker in VIDEO mode, 30 fps target. Camera error or >2 s without frames -> `SafetyController` auto-pause.
Frames are processed in memory and never written to disk or sent anywhere. Only landmark-derived values reach the UI.

## 6. Facial feature pipeline
Distances normalised by inter-ocular distance; EAR for eyelid openness; brow raise/furrow; mouth/jaw opening; geometric head pose;
iris offset in eye frame. `PersonalBaseline` converts to per-person z-scores; `summarise_window` produces fixed-length temporal stats
(mean/std/min/max/slope per feature, blink count/rate, path length).

## 7. Personalised learning
One database + model directory per user. Trials: balanced block randomisation, features frozen at lock, SHA-256 commitment over
(trial, prediction, timestamp, features), label refused before lock, `audit_all()` re-verifies. Training uses `GroupKFold` by session,
selection by CV log-loss, sigmoid calibration, abstention below a confidence threshold, out-of-distribution and low-quality abstention.
Evaluation reserves the latest sessions, compares random / context-only / face-only and reports Wilson CIs and exact tests.
Models are versioned with SHA-256 checksums verified before load.

## 8. Gaze estimation and honest limits
Webcam gaze is typically several degrees (often hundreds of pixels on a desktop monitor) of error after calibration, sensitive to head
movement, lighting and glasses. ORACLE therefore: measures its own error per calibration, exposes it in the UI, feeds it to the brain as
the spatial uncertainty, targets large controls, uses dwell (not precise clicking), and pauses when quality drops. No accuracy figure is
hardcoded anywhere.

## 9. Windows control
Only `ActionController` can reach `InputAdapter`. Commands are typed (pydantic, `extra=forbid`). Risk = base risk of kind, escalated by
target label (delete/send/pay/...). HIGH risk needs `USER_EXPLICIT` source plus a single-use, expiring, approved confirmation, and the
destructive kinds (delete file, shell command, purchase, install, send) have **no implementation** and are UNSUPPORTED even if confirmed.
Inferred intent may only produce suggestions/highlights. Typing is off by default. Launch only from an allow-list. Rate-limited.

## 10. Emergency stop
`SafetyController` imports nothing from models. Triggers: global hotkey (Electron `globalShortcut` **and** an independent Win32
`RegisterHotKey` thread inside the backend), always-visible UI button, REST/WS call, camera failure, sustained tracking loss, backend error.
Stopping cancels pending commands, releases held mouse buttons, blocks all execution, and is logged. Resume is manual and confirmed;
auto-pause resume additionally requires healthy camera/tracking. A facial gesture is never the only stop.

## 11. Storage
SQLite (WAL) in `%APPDATA%/ORACLE`: settings, safety events, action log, interactions, sessions, trials, model versions, baseline.
`delete_personal_data()` wipes personal tables in one transaction; model files deleted with `ModelRegistry.delete_all()`.

## 12. Privacy
No network calls in normal operation, no telemetry, no cloud AI. Backend listens on loopback with a per-launch token. Video is never persisted.
Personal data deletion from Settings. Uninstall guidance lists the data folder.

## 13. Error handling
Typed errors (`StorageError`, `ProtocolError`, `CalibrationError`, `InsufficientData`) map to structured API errors. A processing exception
auto-pauses and surfaces the error instead of killing the loop silently. Backend crash -> Electron restarts it with backoff and the UI shows
"backend offline" while the Electron-side hotkey keeps working. Database failure disables learning features but never the safety controller.

## 14. Testing
pytest: unit tests for every module, synthetic studies for the ML claims, end-to-end tests that drive the real service/API with a synthetic
landmark source (calibration, dwell click, emergency stop, camera loss, trial locking, auth, WebSocket). Windows-only code (Win32 input,
UI Automation, hotkey, real camera, MediaPipe) sits behind adapters with a checklist in `docs/HARDWARE_VALIDATION.md`. Renderer:
`tsc --noEmit` + `vite build`. Packaging is verified by CI on `windows-latest`.

## 15. Packaging
PyInstaller `--onedir` backend (`scripts/build_backend.py`) with the Face Landmarker model bundled; Electron renderer built with Vite;
`electron-builder` NSIS installer includes the backend as `extraResources`. GitHub Actions workflow `build-windows.yml` runs tests,
builds, uploads the installer and publishes a GitHub Release.
