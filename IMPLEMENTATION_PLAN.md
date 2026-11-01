# PROJECT ORACLE - Implementation plan and status

Legend: DONE = implemented and covered by automated tests in the dev sandbox (Linux, no webcam). WIN = needs validation on real
Windows hardware (see `docs/HARDWARE_VALIDATION.md`).

| Phase | Scope | Order | Acceptance | Status |
|---|---|---|---|---|
| 1 Foundation | storage, safety, control, settings, logging | 1 | safety + control + storage tests | DONE |
| 2 Eye | landmarks, features, calibration, filter, dwell, quality, monitors | 2 | calibration error measured, pause on loss | DONE (synthetic) / WIN (webcam accuracy) |
| 3 Face | baseline, trials, locking, models, evaluation | 3 | no false claims on noise, leakage tests | DONE (synthetic) |
| 4 Vision | screen model, hit-testing, UIA provider, fallback | 4 | hit-test ranking tests | DONE (logic) / WIN (UIA on real apps) |
| 5 Brain | scoring, history, rejection memory, ambiguity | 5 | explainable ranking tests, never executes | DONE |
| 6 Backend | FastAPI + WS, schemas, orchestrator, camera, hotkey | 6 | API tests with simulated source | DONE (simulated) / WIN (camera, MediaPipe, hotkey) |
| 7 Desktop | Electron main/preload/backend-manager/safety-manager, React 10 pages | 7 | `tsc` + `vite build` pass | see docs/DEVLOG.md |
| 8 Integration | end-to-end simulated session, fault injection | 8 | e2e tests | DONE (simulated) |
| 9 Packaging | PyInstaller, electron-builder, GitHub Actions release | 9 | CI green on windows-latest | see docs/DEVLOG.md |

Dependencies: Python >= 3.11 (numpy, scipy, scikit-learn, fastapi, uvicorn, pydantic, opencv-python, mediapipe, uiautomation[win]);
Node 20+ (electron, electron-builder, react, vite, tailwind). Development log: `docs/DEVLOG.md`.

A release is only marked final when the WIN items have been validated by a person on Windows; until then releases are pre-releases.
