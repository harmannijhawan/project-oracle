"""FastAPI application: loopback-only, token-authenticated REST + WebSocket."""

from __future__ import annotations

import asyncio
import hmac
import json
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import TypeAdapter, ValidationError

from engine import __version__
from engine.experiments import ProtocolError
from engine.face.simulated import SimulatedLandmarkSource
from engine.gaze import CalibrationError
from engine.prediction import InsufficientData
from engine.safety import StopReason
from engine.storage import StorageError

from . import schemas as S
from .service import OracleService, jsonable

ALLOWED_ORIGINS = {None, "null", "file://", "app://oracle", "http://127.0.0.1:5173", "http://localhost:5173"}
_client_msg = TypeAdapter(S.ClientMessage)


def create_app(service: OracleService, token: str, camera_factory: Callable[[int, OracleService], object] | None = None) -> FastAPI:
    app = FastAPI(title="ORACLE engine", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)

    def auth(request: Request) -> None:
        supplied = request.headers.get("x-oracle-token", "")
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid token")

    api = Depends(auth)

    @app.exception_handler(ProtocolError)
    async def _p(_: Request, e: ProtocolError):  # noqa: ANN202
        return JSONResponse({"error": "protocol", "message": str(e)}, 409)

    @app.exception_handler(CalibrationError)
    async def _c(_: Request, e: CalibrationError):  # noqa: ANN202
        return JSONResponse({"error": "calibration", "message": str(e)}, 422)

    @app.exception_handler(InsufficientData)
    async def _i(_: Request, e: InsufficientData):  # noqa: ANN202
        return JSONResponse({"error": "insufficient_data", "message": str(e)}, 422)

    @app.exception_handler(StorageError)
    async def _s(_: Request, e: StorageError):  # noqa: ANN202
        return JSONResponse({"error": "storage", "message": str(e)}, 500)

    @app.exception_handler(ValueError)
    async def _v(_: Request, e: ValueError):  # noqa: ANN202
        return JSONResponse({"error": "invalid", "message": str(e)}, 422)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    # ---- state & settings -------------------------------------------------------------------------------
    @app.get("/api/state", dependencies=[api])
    def state() -> dict:
        return jsonable(service.state())

    @app.get("/api/settings", dependencies=[api])
    def get_settings() -> dict:
        return service.settings.model_dump()

    @app.put("/api/settings", dependencies=[api])
    def put_settings(patch: S.SettingsPatch) -> dict:
        return service.update_settings(patch).model_dump()

    # ---- safety ----------------------------------------------------------------------------------------------
    @app.post("/api/safety/stop", dependencies=[api])
    def stop() -> dict:
        service.emergency_stop(StopReason.USER_BUTTON)
        return {"state": service.safety.state.value}

    @app.post("/api/safety/resume", dependencies=[api])
    def resume(body: S.Resume) -> dict:
        ok = service.resume(body.confirmed)
        return {"resumed": ok, "state": service.safety.state.value}

    @app.get("/api/safety/events", dependencies=[api])
    def safety_events() -> list:
        return [dict(r) for r in service.db.query("SELECT * FROM safety_events ORDER BY id DESC LIMIT 100")]

    # ---- tracking ----------------------------------------------------------------------------------------------
    @app.post("/api/tracking/start", dependencies=[api])
    def tracking_start(body: S.StartTracking) -> dict:
        if body.simulate:
            service.simulator = SimulatedLandmarkSource()  # type: ignore[attr-defined]
            service.start_tracking(service.simulator)  # type: ignore[attr-defined]
        else:
            idx = service.settings.camera_index if body.camera_index is None else body.camera_index
            if camera_factory is None:
                raise HTTPException(503, "camera support is not available in this build")
            try:
                source = camera_factory(idx, service)
            except Exception as exc:
                service.on_camera_error(str(exc))
                raise HTTPException(503, f"camera unavailable: {exc}") from exc
            service.start_tracking(source)  # type: ignore[arg-type]
        return {"tracking": True}

    @app.post("/api/tracking/stop", dependencies=[api])
    def tracking_stop() -> dict:
        service.stop_tracking()
        return {"tracking": False}

    @app.post("/api/simulate/look", dependencies=[api])
    def simulate_look(body: S.CalibrationTarget) -> dict:
        sim = getattr(service, "simulator", None)
        if sim is None or not service.tracking:
            raise ValueError("simulation is not running")
        sim.look_at(body.tx, body.ty)
        return {"ok": True}

    # ---- calibration ---------------------------------------------------------------------------------------------
    @app.get("/api/calibration", dependencies=[api])
    def calibration() -> dict:
        return {"targets": service.calibration_targets(), "current": service.calibration_info()}

    @app.post("/api/calibration/start", dependencies=[api])
    def cal_start() -> dict:
        service.calibration_begin()
        return {"targets": service.calibration_targets()}

    @app.post("/api/calibration/capture", dependencies=[api])
    def cal_capture(body: S.CalibrationTarget) -> dict:
        return {"samples": service.calibration_capture(body.tx, body.ty)}

    @app.post("/api/calibration/finish", dependencies=[api])
    def cal_finish() -> dict:
        return service.calibration_finish()

    @app.post("/api/cursor-control", dependencies=[api])
    def cursor_control(body: S.ControlToggle) -> dict:
        return {"cursor_control": service.update_settings(S.SettingsPatch(cursor_control=body.enabled)).cursor_control}

    # ---- face / experiments -------------------------------------------------------------------------------------------
    @app.post("/api/baseline/start", dependencies=[api])
    def baseline_start() -> dict:
        service.baseline_start()
        return service.baseline_info()

    @app.post("/api/baseline/finish", dependencies=[api])
    def baseline_finish() -> dict:
        return service.baseline_finish()

    @app.post("/api/experiments/session", dependencies=[api])
    def new_session() -> dict:
        return {"session_id": service.trials.start_session()}

    @app.post("/api/experiments/trial", dependencies=[api])
    def new_trial(body: S.NewTrial) -> dict:
        t = service.trials.new_trial(body.session_id, body.option_a, body.option_b)
        return jsonable(t)

    @app.post("/api/experiments/trial/{trial_id}/begin", dependencies=[api])
    def trial_begin(trial_id: str) -> dict:
        service.trial_begin(trial_id)
        return {"recording": True}

    @app.post("/api/experiments/trial/{trial_id}/lock", dependencies=[api])
    def trial_lock(trial_id: str) -> dict:
        return service.trial_lock(trial_id)

    @app.post("/api/experiments/trial/{trial_id}/answer", dependencies=[api])
    def trial_answer(trial_id: str, body: S.Answer) -> dict:
        service.trials.reveal_label(trial_id, body.side)
        return {"verified": service.trials.verify_commitment(trial_id)}

    @app.get("/api/experiments/audit", dependencies=[api])
    def audit() -> dict:
        bad = service.trials.audit_all()
        total = service.db.query("SELECT COUNT(*) FROM trials WHERE label IS NOT NULL")[0][0]
        return {"completed_trials": total, "unverifiable": bad}

    @app.get("/api/experiments/trials", dependencies=[api])
    def trials(limit: int = 100) -> list:
        rows = service.db.query("SELECT id, session_id, idx, left_option, right_option, prediction_json, label, locked_at, "
                                "revealed_at FROM trials ORDER BY created_at DESC LIMIT ?", (min(limit, 500),))
        return [{**dict(r), "prediction": json.loads(r["prediction_json"]) if r["prediction_json"] else None} for r in rows]

    @app.post("/api/model/train", dependencies=[api])
    def train() -> dict:
        return service.train_model()

    @app.get("/api/model/versions", dependencies=[api])
    def versions() -> dict:
        return {"versions": service.registry.versions(), "evaluation": service.last_evaluation}

    # ---- brain / screen ----------------------------------------------------------------------------------------------------
    @app.get("/api/brain/decision", dependencies=[api])
    def decision() -> dict:
        return service.latest

    @app.post("/api/brain/feedback", dependencies=[api])
    def feedback(body: S.Feedback) -> dict:
        service.feedback(body.suggestion_key, body.outcome, body.corrected_to_key)
        return {"ok": True}

    @app.get("/api/brain/log", dependencies=[api])
    def brain_log() -> list:
        return list(service.brain.log)

    @app.get("/api/screen/snapshot", dependencies=[api])
    def screen_snapshot() -> dict:
        snap = service.screen.snapshot()
        return {"windows": jsonable(snap.windows), "elements": jsonable([e for e in snap.elements if e.interactive][:300]),
                "foreground": jsonable(snap.foreground)}

    @app.get("/api/actions/recent", dependencies=[api])
    def actions_recent() -> list:
        return service.db.recent_actions(100)

    # ---- privacy -----------------------------------------------------------------------------------------------------------------
    @app.post("/api/privacy/delete", dependencies=[api])
    def privacy_delete(body: S.DeleteRequest) -> dict:
        return service.delete_personal_data()

    # ---- websocket ----------------------------------------------------------------------------------------------------------------
    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        origin = sock.headers.get("origin")
        if origin not in ALLOWED_ORIGINS or not hmac.compare_digest(sock.query_params.get("token", ""), token):
            await sock.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await sock.accept()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)
        last_frame = {"t": 0.0}

        def push(ev: dict) -> None:
            def put() -> None:
                if ev.get("type") == "frame":  # frames are droppable; everything else is not
                    if queue.qsize() > 20 or ev["t"] - last_frame["t"] < 0.04:
                        return
                    last_frame["t"] = ev["t"]
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(jsonable(ev))
            loop.call_soon_threadsafe(put)

        unsubscribe = service.subscribe(push)

        async def sender() -> None:
            await sock.send_json({"type": "state", "state": jsonable(service.state())})
            while True:
                await sock.send_json(await queue.get())

        send_task = asyncio.create_task(sender())
        try:
            while True:
                raw = await sock.receive_text()
                try:
                    msg = _client_msg.validate_json(raw)
                except ValidationError as exc:
                    await sock.send_json({"type": "error", "message": "invalid message", "detail": exc.errors(include_url=False, include_context=False)[:3]})
                    continue
                if isinstance(msg, S.WsEmergencyStop):
                    service.emergency_stop(StopReason.USER_BUTTON)  # synchronous, never waits on anything else
                elif isinstance(msg, S.WsResume):
                    await run_in_threadpool(service.resume, msg.confirmed)
                elif isinstance(msg, S.WsCursorControl):
                    await run_in_threadpool(service.update_settings, S.SettingsPatch(cursor_control=msg.enabled))
                elif isinstance(msg, S.WsFeedback):
                    try:
                        await run_in_threadpool(service.feedback, msg.suggestion_key, msg.outcome)
                    except ValueError as exc:
                        await sock.send_json({"type": "error", "message": str(exc)})
                elif isinstance(msg, S.WsPing):
                    await sock.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()
            send_task.cancel()

    return app
