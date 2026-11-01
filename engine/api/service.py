"""OracleService: the single orchestrator that wires every engine together.

Thread model: one tracking thread calls ``process_landmarks``; API threads call the other methods.
Shared state is guarded by ``self._lock``. The SafetyController has its own lock and is never blocked
by anything in here.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

import numpy as np

from engine.brain import BrainConfig, Decision, FaceSignal, InteractionHistory, OracleBrain, Suggestion
from engine.control import (ActionController, ActionKind, ActionSource, Command, ExecResult, InputAdapter,
                            PermissionPolicy, RecordingInputAdapter)
from engine.experiments import ProtocolError, TrialManager
from engine.face.landmarker import LandmarkSource
from engine.features import (FEATURE_NAMES, BlinkDetector, PersonalBaseline, extract_frame_features,
                             gaze_feature_vector, summarise_window, vector)
from engine.features import face_features as ff
from engine.gaze import (CalibratedEstimator, CalibrationError, DwellDetector, GazeCalibration, GazeCursorPipeline,
                         Monitor, QualityInputs, QualityMonitor, enumerate_monitors, nine_point_targets)
from engine.prediction import (InsufficientData, ModelRegistry, PersonalModel, chronological_session_split,
                               evaluate_personal_model, load_records)
from engine.safety import SafetyConfig, SafetyController, SafetyEvent, SafetyState, StopReason
from engine.screen_context import ElementIndex, ScreenProvider, StaticScreenProvider
from engine.storage import Database

from .schemas import Settings, SettingsPatch

DEFAULT_GAZE_ERROR_PX = 150.0  # used until a calibration has *measured* its own error


def jsonable(o: Any) -> Any:
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {f.name: jsonable(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if isinstance(o, enum.Enum):
        return o.value
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    return o


class _Capture:
    def __init__(self, target: tuple[float, float], needed: int) -> None:
        self.target, self.needed = target, needed
        self.vectors: list[np.ndarray] = []
        self.done = threading.Event()


class OracleService:
    def __init__(self, data_dir: str | Path, adapter: InputAdapter | None = None, screen: ScreenProvider | None = None,
                 monitors: list[Monitor] | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.db = Database(self.data_dir / "oracle.db")
        self.settings = Settings(**self._load_settings())
        self.monitors = monitors or enumerate_monitors()
        self.monitor = next((m for m in self.monitors if m.primary), self.monitors[0])
        self.safety = SafetyController(SafetyConfig(tracking_min_quality=self.settings.min_quality), clock=clock)
        self.safety.add_listener(self._on_safety_event)
        self.adapter = adapter or RecordingInputAdapter()
        self.controller = ActionController(self.safety, self.adapter, self._policy(), audit=self._audit)
        self.history = InteractionHistory(self.db)
        self.brain = OracleBrain(self.history, BrainConfig(min_quality=self.settings.min_quality))
        self.screen = screen or StaticScreenProvider()
        self.trials = TrialManager(self.db)
        self.registry = ModelRegistry(self.data_dir / "models", self.db)
        self.model: PersonalModel | None = None
        self.last_evaluation: dict | None = None
        self.baseline = self._load_baseline()
        self.baseline_collecting = False
        self.calibration: GazeCalibration | None = self._load_calibration()
        self._cal_samples: list[tuple[np.ndarray, tuple[float, float]]] = []
        self._capture: _Capture | None = None
        self.quality_monitor = QualityMonitor()
        self.blink = BlinkDetector()
        self.pipeline: GazeCursorPipeline | None = None
        self._trial_window: dict[str, list[tuple[float, np.ndarray]]] = {}
        self._trial_blinks: dict[str, int] = {}
        self._active_trials: set[str] = set()
        self._lock = threading.RLock()
        self._listeners: list[Callable[[dict], None]] = []
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._source: LandmarkSource | None = None
        self.latest: dict = {"phase": "idle", "suggestions": [], "reason": "tracking not started"}
        self.gaze: dict | None = None
        self.quality = 0.0
        self.face_present = False
        self.recent_actions: deque[dict] = deque(maxlen=50)
        self._suggestions_by_key: dict[str, Suggestion] = {}
        self._last_decision_at = 0.0
        self.last_error: str | None = None
        self._rebuild_pipeline()
        try:
            self.model = self.registry.load()
        except Exception:
            self.model = None

    # ---- events ---------------------------------------------------------------------------
    def subscribe(self, cb: Callable[[dict], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def emit(self, event: dict) -> None:
        for cb in list(self._listeners):
            try:
                cb(event)
            except Exception:
                pass

    def _on_safety_event(self, e: SafetyEvent) -> None:
        try:
            self.db.log_safety_event(time.time(), e.kind, e.reason, e.detail)
        except Exception:
            pass  # a database failure must never affect safety
        self.emit({"type": "safety", "event": jsonable(e), "state": self.safety.state.value})

    def _audit(self, command: Command, result: ExecResult) -> None:
        item = {"ts": time.time(), "kind": command.kind.value, "source": command.source.value, "label": command.target_label,
                "status": result.status.value, "reason": result.reason, "risk": int(result.risk)}
        self.recent_actions.appendleft(item)
        try:
            self.db.log_action(command.model_dump_json(), result.status.value, result.reason, int(result.risk))
        except Exception:
            pass
        self.emit({"type": "action", "action": item})

    # ---- settings / persistence -------------------------------------------------------------
    def _load_settings(self) -> dict:
        try:
            return {k: v for k, v in self.db.all_settings().items() if k in Settings.model_fields}
        except Exception:
            return {}

    def _policy(self) -> PermissionPolicy:
        kinds = {ActionKind(k) for k in self.settings.enabled_actions if k in ActionKind._value2member_map_}
        return PermissionPolicy(enabled_kinds=kinds)

    def update_settings(self, patch: SettingsPatch) -> Settings:
        data = {**self.settings.model_dump(), **patch.model_dump(exclude_none=True)}
        new = Settings(**data)
        with self._lock:
            self.settings = new
            for k, v in new.model_dump().items():
                self.db.set_setting(k, v)
            self.controller.policy = self._policy()
            self.safety.config.tracking_min_quality = new.min_quality
            self.brain.cfg = dataclasses.replace(self.brain.cfg, min_quality=new.min_quality)
            self._rebuild_pipeline()
        self.emit({"type": "settings", "settings": new.model_dump()})
        return new

    def _load_calibration(self) -> GazeCalibration | None:
        raw = self.db.get_setting("calibration")
        try:
            return GazeCalibration.from_json(raw) if raw else None
        except Exception:
            return None

    def _load_baseline(self) -> PersonalBaseline:
        rows = self.db.query("SELECT json FROM baseline WHERE id = 1")
        try:
            return PersonalBaseline.from_dict(json.loads(rows[0][0])) if rows else PersonalBaseline()
        except Exception:
            return PersonalBaseline()

    def _rebuild_pipeline(self) -> None:
        s = self.settings
        if self.calibration is None or not self.calibration.is_fitted:
            self.pipeline = None
            return
        self.pipeline = GazeCursorPipeline(CalibratedEstimator(self.calibration), self.monitor, self.safety,
                                           smoothing_cutoff=s.smoothing,
                                           dwell=DwellDetector(s.dwell_s, s.dwell_radius_px), min_quality=s.min_quality,
                                           deadzone_px=s.deadzone_px)

    def gaze_error_px(self) -> float:
        rep = self.calibration.report if self.calibration else None
        return max(rep.loo_mean_error_px, 25.0) if rep else DEFAULT_GAZE_ERROR_PX

    # ---- safety API ---------------------------------------------------------------------------
    def emergency_stop(self, reason: StopReason = StopReason.USER_BUTTON) -> None:
        self.safety.emergency_stop(reason)

    def resume(self, confirmed: bool) -> bool:
        ok = self.safety.manual_resume(confirmed)
        self.emit({"type": "safety_state", "state": self.safety.state.value})
        return ok

    # ---- tracking loop --------------------------------------------------------------------------
    def start_tracking(self, source: LandmarkSource) -> None:
        self.stop_tracking()
        self._source, self._stop_evt = source, threading.Event()
        self.last_error = None
        self._thread = threading.Thread(target=self._loop, name="oracle-tracking", daemon=True)
        self._thread.start()
        self.emit({"type": "tracking", "running": True})

    def stop_tracking(self) -> None:
        self._stop_evt.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._thread = None
        if self._source is not None:
            try:
                self._source.close()
            except Exception:
                pass
            self._source = None
        self.face_present, self.quality, self.gaze = False, 0.0, None
        self.emit({"type": "tracking", "running": False})

    @property
    def tracking(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def on_camera_error(self, detail: str) -> None:
        self.last_error = detail
        self.safety.report_camera_error(detail)

    def _loop(self) -> None:
        last_tick = 0.0
        while not self._stop_evt.is_set():
            try:
                item = self._source.read() if self._source else None
            except Exception as exc:
                self.on_camera_error(f"camera read failed: {exc!r}")
                break
            now = time.monotonic()
            if now - last_tick > 0.1:
                self.safety.tick()
                last_tick = now
            if item is None:
                time.sleep(0.004)
                continue
            try:
                self.process_landmarks(*item)
            except Exception as exc:  # never let a processing bug kill the loop silently: pause and surface it
                self.last_error = f"processing error: {exc!r}"
                self.safety.auto_pause(StopReason.BACKEND_ERROR, self.last_error)
                self.emit({"type": "error", "message": self.last_error})

    # ---- per-frame processing ---------------------------------------------------------------------
    def process_landmarks(self, lm: np.ndarray | None, t: float) -> dict | None:
        self.safety.report_camera_frame()
        if lm is None:
            self.face_present, self.quality = False, 0.0
            self.quality_monitor.update(QualityInputs(False, 0, 0, 0, 0))
            if self.pipeline:
                self.pipeline.process(None, 0.0, t)
            else:
                self.safety.report_tracking_quality(0.0)
            self._publish(None, t)
            return None
        feats = extract_frame_features(lm)
        fvec = gaze_feature_vector(feats)
        ear = (feats["ear_left"] + feats["ear_right"]) / 2
        width = abs(float(lm[ff.CHEEK_R, 0] - lm[ff.CHEEK_L, 0]))
        q = self.quality_monitor.update(QualityInputs(True, ear, feats["yaw"], feats["pitch"], width), (fvec[0], fvec[1]))
        self.face_present, self.quality = True, q
        blink = self.blink.update(ear, t)
        deliberate = bool(blink and blink.deliberate)
        full = vector(feats)
        with self._lock:
            if self.baseline_collecting and q >= self.settings.min_quality:
                self.baseline.update(full)
            cap = self._capture
            if cap is not None and q >= self.settings.min_quality and not cap.done.is_set():
                cap.vectors.append(fvec)
                if len(cap.vectors) >= cap.needed:
                    cap.done.set()
            if self._active_trials and self.baseline.n >= 2:
                z = self.baseline.zscore(full)
                for tid in self._active_trials:
                    self._trial_window[tid].append((t, z))
                    if blink:
                        self._trial_blinks[tid] += 1
        sample = self.pipeline.process(fvec, q, t) if self.pipeline else None
        self.gaze = None if sample is None else {"x": sample.x, "y": sample.y, "dwell": sample.dwell.progress}
        if sample is not None:
            self._act_on_gaze(sample, q, deliberate)
        else:
            self.latest = {"phase": "idle", "suggestions": [], "reason": "no reliable gaze" if self.pipeline else "not calibrated"}
        self._publish(sample, t)
        return self.gaze

    def _act_on_gaze(self, sample, q: float, deliberate: bool) -> None:  # type: ignore[no-untyped-def]
        s = self.settings
        allowed = self.safety.is_execution_allowed()
        if s.cursor_control and allowed:
            self.controller.execute(Command(kind=ActionKind.MOVE_CURSOR, source=ActionSource.DWELL, x=sample.x, y=sample.y))
        if not (sample.dwell.fired or deliberate) and time.monotonic() - self._last_decision_at < 0.05:
            return  # throttle the brain, but never skip the one-shot dwell/gesture frame
        self._last_decision_at = time.monotonic()
        try:
            index = ElementIndex(self.screen.snapshot())
        except Exception as exc:
            self.last_error = f"screen context unavailable: {exc!r}"
            index = ElementIndex(StaticScreenProvider().snapshot())
        dec = self.brain.observe(index, sample.x, sample.y, self.gaze_error_px(), sample.dwell.progress, q,
                                 FaceSignal(deliberate, s.gestures_enabled), tracking_allowed=allowed)
        self._remember(dec)
        if s.dwell_click and dec.select_target is not None and (sample.dwell.fired or (s.gestures_enabled and deliberate)):
            tgt = dec.select_target
            source = ActionSource.DWELL if sample.dwell.fired else ActionSource.GESTURE
            res = self.controller.execute(OracleBrain.command_for(tgt, source))
            if res.status.value == "executed":
                self.brain.record_outcome(tgt, "confirmed")

    def _remember(self, dec: Decision) -> None:
        self.latest = jsonable(dec)
        self._suggestions_by_key = {sg.element_key: sg for sg in dec.suggestions}

    def _publish(self, sample, t: float) -> None:  # type: ignore[no-untyped-def]
        self.emit({"type": "frame", "t": t, "face": self.face_present, "quality": round(self.quality, 3), "gaze": self.gaze,
                   "decision": {k: self.latest.get(k) for k in ("phase", "reason", "ambiguous")}, "safety": self.safety.state.value})

    # ---- calibration ---------------------------------------------------------------------------------
    def calibration_targets(self) -> list[tuple[float, float]]:
        return nine_point_targets()

    def calibration_begin(self) -> None:
        with self._lock:
            self._cal_samples = []
            self._capture = None

    def calibration_capture(self, tx: float, ty: float, frames: int = 36, settle: int = 6, timeout_s: float = 8.0) -> int:
        """Blocks until ``frames`` good frames were seen for this dot. Returns number of samples stored (3)."""
        if not self.tracking:
            raise CalibrationError("start tracking before calibrating")
        cap = _Capture((tx, ty), frames + settle)
        with self._lock:
            self._capture = cap
        ok = cap.done.wait(timeout_s)
        with self._lock:
            self._capture = None
        if not ok:
            raise CalibrationError("not enough good frames for this point (face lost or tracking quality too low)")
        usable = np.array(cap.vectors[settle:])
        for chunk in np.array_split(usable, 3):  # 3 sub-samples/point -> 27 samples for 9 points
            self._cal_samples.append((chunk.mean(axis=0), (tx, ty)))
        return len(self._cal_samples)

    def calibration_finish(self) -> dict:
        if not self._cal_samples:
            raise CalibrationError("no calibration samples collected")
        feats = np.array([f for f, _ in self._cal_samples])
        targets = np.array([t for _, t in self._cal_samples])
        cal = GazeCalibration()
        report = cal.fit(feats, targets, (self.monitor.width, self.monitor.height))
        with self._lock:
            self.calibration = cal
            self.db.set_setting("calibration", cal.to_json())
            self._rebuild_pipeline()
        out = {"n_samples": report.n_samples, "mean_error_px": report.loo_mean_error_px,
               "p90_error_px": report.loo_p90_error_px, "relative_error": report.relative_error,
               "monitor": {"id": self.monitor.id, "width": self.monitor.width, "height": self.monitor.height}}
        self.emit({"type": "calibration", "report": out})
        return out

    def calibration_info(self) -> dict | None:
        c = self.calibration
        if not c or not c.report:
            return None
        r = c.report
        return {"n_samples": r.n_samples, "mean_error_px": r.loo_mean_error_px, "p90_error_px": r.loo_p90_error_px,
                "relative_error": r.relative_error}

    # ---- baseline ---------------------------------------------------------------------------------------
    def baseline_start(self) -> None:
        with self._lock:
            self.baseline, self.baseline_collecting = PersonalBaseline(), True

    def baseline_finish(self) -> dict:
        with self._lock:
            self.baseline_collecting = False
            if self.baseline.n < 2:
                raise ValueError("no baseline frames collected (is the face visible?)")
            self.db.execute("INSERT INTO baseline(id, updated_at, json) VALUES(1, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                            "updated_at = excluded.updated_at, json = excluded.json", (time.time(), json.dumps(self.baseline.to_dict())))
        return self.baseline_info()

    def baseline_info(self) -> dict:
        return {"n": self.baseline.n, "ready": self.baseline.is_ready(), "collecting": self.baseline_collecting,
                "features": FEATURE_NAMES}

    # ---- experiments -------------------------------------------------------------------------------------
    def trial_begin(self, trial_id: str) -> None:
        if not self.baseline.is_ready():
            raise ProtocolError("collect a personal baseline first (not enough frames)")
        self.trials._row(trial_id)
        with self._lock:
            self._trial_window[trial_id], self._trial_blinks[trial_id] = [], 0
            self._active_trials.add(trial_id)

    def trial_lock(self, trial_id: str) -> dict:
        """Computes features, makes (or abstains from) a prediction, and commits it BEFORE any answer exists."""
        with self._lock:
            self._active_trials.discard(trial_id)
            frames = self._trial_window.pop(trial_id, [])
            blinks = self._trial_blinks.pop(trial_id, 0)
        if len(frames) < 10:
            raise ProtocolError("not enough face frames during deliberation (face lost?)")
        ts = np.array([f[0] for f in frames])
        feat = summarise_window(np.stack([f[1] for f in frames]), ts, blinks)
        self.trials.add_features(trial_id, feat)
        if self.model is None:
            pred = {"side": None, "abstain": True, "reason": "no trained model yet", "p_right": None}
        else:
            p = self.model.predict(feat, self.quality)
            pred = {"side": p.side, "abstain": p.abstain, "reason": p.reason, "p_right": p.p_right, "confidence": p.confidence,
                    "model": self.model.name}
        digest = self.trials.lock_prediction(trial_id, pred)
        return {"prediction": pred, "commitment": digest, "locked": True}

    def train_model(self, n_test_sessions: int = 1) -> dict:
        records = load_records(self.db)
        if not records:
            raise InsufficientData("no completed trials yet")
        train, test = chronological_session_split(records, n_test_sessions)
        model, report = evaluate_personal_model(train, test, abstain_below=self.settings.abstain_below)
        version = self.registry.save(model, {"n_train": report.n_train, "n_test": report.n_test})
        self.model = model
        self.last_evaluation = jsonable(report) | {"version": version}
        return self.last_evaluation

    # ---- brain feedback ---------------------------------------------------------------------------------------
    def feedback(self, key: str, outcome: str, corrected_to_key: str | None = None) -> None:
        s = self._suggestions_by_key.get(key)
        if s is None:
            raise ValueError("unknown or expired suggestion")
        other = self._suggestions_by_key.get(corrected_to_key) if corrected_to_key else None
        self.brain.record_outcome(s, outcome, corrected_to=other)
        self.emit({"type": "feedback", "label": s.label, "outcome": outcome})

    # ---- privacy ------------------------------------------------------------------------------------------------
    def delete_personal_data(self) -> dict:
        self.stop_tracking()
        counts = self.db.delete_personal_data()
        self.registry.delete_all()
        self.db.execute("DELETE FROM settings WHERE key = 'calibration'")
        self.model, self.calibration, self.pipeline, self.baseline = None, None, None, PersonalBaseline()
        self.last_evaluation = None
        self.brain.log.clear()
        return counts

    # ---- state snapshot ---------------------------------------------------------------------------------------------
    def state(self) -> dict:
        return {"safety": {"state": self.safety.state.value, "reason": self.safety.reason.value if self.safety.reason else None,
                           "shortcut": self.settings.emergency_shortcut},
                "tracking": self.tracking, "face": self.face_present, "quality": round(self.quality, 3), "gaze": self.gaze,
                "calibrated": self.calibration is not None and self.calibration.is_fitted,
                "calibration": self.calibration_info(), "cursor_control": self.settings.cursor_control,
                "dwell_click": self.settings.dwell_click, "decision": self.latest, "baseline": self.baseline_info(),
                "model": None if self.model is None else {"name": self.model.name, "calibrated": self.model.calibrated},
                "monitor": {"id": self.monitor.id, "width": self.monitor.width, "height": self.monitor.height},
                "monitors": jsonable(self.monitors), "recent_actions": list(self.recent_actions)[:10],
                "last_error": self.last_error}

    def close(self) -> None:
        self.stop_tracking()
        self.db.close()
