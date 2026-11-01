# PROJECT ORACLE - build status

Last verified: 46 automated tests passing (`pytest`) on the Python engine core.

This is NOT yet a finished or releasable desktop app. There is no installer and no downloadable build.

## Built and tested (synthetic data only)
- Safety: independent emergency stop, auto-pause on camera loss / poor tracking, manual resume
- Control: typed commands, risk levels, permissions, confirmation gate, rate limit, no destructive actions
- Gaze: 9-point calibration (measured error), One-Euro smoothing, dwell, quality score, multi-monitor mapping
- Features: face landmark features, blink detector, personal baseline, window summaries
- Experiments: commit-before-reveal trial protocol with tamper detection
- Prediction: LR / RF / GB selection with session-grouped CV, calibration, abstention, honest evaluation
- Storage: local SQLite, personal data deletion, versioned model files with checksums

## Not built yet
- Engine C: Windows screen understanding (UI Automation)
- Engine D: ORACLE Brain (decision layer)
- FastAPI / WebSocket backend service
- Camera capture + MediaPipe wiring
- Electron + React desktop UI, emergency-stop hotkey, tray
- Windows installer / release build

## Not validated
- Anything on real hardware: webcam gaze accuracy, WindowsInputAdapter (Win32), multi-monitor
- Real-world accuracy of any prediction model (tests use simulated participants)
