"""
VayuDev GCS Backend — main entrypoint.

Responsibilities wired up here (scaffold level, fill in per-module TODOs):
  - WebSocket ingestion from the injector (bridges MAVLink/serial -> JSON frames)
  - WebSocket broadcast to HUD clients (3D WebGL frontend)
  - In-memory sliding ring buffer (100 frames / 5s @ 20Hz)
  - GET /api/telemetry/history for timeline scrubbing
  - JWT-based RBAC stub (Operator vs Propulsion Engineer)
  - Background UDP MAVLink listener task (udp:127.0.0.1:14550)

This is a scaffold meant to make the Docker/deployment setup runnable end to
end. Replace stub logic (inference call, MAVLink decode, signing validation)
with the real implementations from the ingestion / inference / security work.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import Role, create_access_token, get_current_role, validate_ws_token
from app.mavlink_listener import mavlink_udp_listener
from app.ring_buffer import RingBuffer
from app.schemas import TelemetryFrame
from app.smoothing import TelemetrySmoother

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("vayudev")

RING_BUFFER_SIZE = int(os.getenv("RING_BUFFER_SIZE", "100"))
ring_buffer = RingBuffer(maxsize=RING_BUFFER_SIZE)

# Single global smoother instance — it tracks per-channel Kalman state over
# time, so it must persist across frames rather than being recreated per
# request. There is only one engine's telemetry stream here, so one global
# instance is the right scope.
smoother = TelemetrySmoother()

# There's no real user database yet, so token issuance below is gated by a
# separate bootstrap secret rather than actual credential checking. This is
# explicitly a dev/bring-up mechanism — replace with real login against a
# local user store before this is anything but a hackathon demo.
BOOTSTRAP_SECRET = os.getenv("BOOTSTRAP_SECRET", "")


class ConnectionManager:
    """Tracks HUD (subscriber) WebSocket clients for broadcast fan-out."""

    def __init__(self) -> None:
        self.hud_clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.hud_clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.hud_clients.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        async with self._lock:
            targets = list(self.hud_clients)
        for client in targets:
            try:
                await client.send_json(payload)
            except Exception:
                dead.append(client)
        if dead:
            async with self._lock:
                for d in dead:
                    self.hud_clients.discard(d)


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Background task: listen for MAVLink UDP frames and feed them into the
    # same pipeline as WS-injected frames (signature validation happens inside).
    task = asyncio.create_task(mavlink_udp_listener(on_frame=handle_inbound_frame))
    log.info("MAVLink UDP listener started on udp:127.0.0.1:14550")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="VayuDev GCS Backend", version="0.1.0", lifespan=lifespan)


async def handle_inbound_frame(frame: TelemetryFrame) -> None:
    """Single choke point for every inbound frame, regardless of transport.

    TODO: call inference.py here (XGBoost + physics guardrail fallback) to
    enrich with predicted_rul / ml_confidence / source / primary_root_cause
    before it lands in the ring buffer and gets broadcast.
    """
    enriched = frame.model_dump()

    smoothing_result = smoother.process(enriched)
    enriched["smoothed"] = smoothing_result.smoothed
    enriched["kalman_estimate"] = smoothing_result.kalman_estimate
    enriched["anomaly_flags"] = smoothing_result.anomaly_flags
    if smoothing_result.any_anomaly:
        flagged = [
            ch for ch, is_anom in smoothing_result.anomaly_flags.items() if is_anom
        ]
        log.warning(
            "Anomalous reading (statistical outlier, NOT auto-dropped) on: %s "
            "(sigma=%s)",
            flagged,
            {ch: round(smoothing_result.anomaly_sigma[ch], 2) for ch in flagged},
        )

    enriched.update(
        {
            "predicted_rul": None,
            "ml_confidence": None,
            "source": "unenriched",  # "ml" | "physics" | "unenriched"
            "primary_root_cause": None,
        }
    )
    ring_buffer.push(enriched)
    await manager.broadcast(enriched)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "buffered_frames": len(ring_buffer)})


class TokenRequest(BaseModel):
    role: Role
    subject: str = "dev-user"
    bootstrap_secret: str


@app.post("/auth/token")
async def issue_dev_token(req: TokenRequest):
    """Mint a real signed JWT for the given role.

    DEV-ONLY BRING-UP ENDPOINT: gated by BOOTSTRAP_SECRET (a separate shared
    secret, not a real credential check) because there's no user database
    yet. Anyone holding BOOTSTRAP_SECRET can mint a token for ANY role,
    including propulsion_engineer's full-access role. This must be replaced
    with real authentication (checked against an actual user store) before
    this is exposed anywhere beyond a local dev/demo environment — do not
    ship this endpoint as-is.
    """
    if not BOOTSTRAP_SECRET or req.bootstrap_secret != BOOTSTRAP_SECRET:
        raise HTTPException(status_code=403, detail="Invalid bootstrap secret")
    token = create_access_token(req.role, subject=req.subject)
    return {"access_token": token, "token_type": "bearer", "role": req.role.value}


@app.get("/api/telemetry/history")
async def telemetry_history(role: Role = Depends(get_current_role)):
    # Both roles may view history; raw export restricted elsewhere.
    return {"frames": ring_buffer.snapshot()}


@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket, client_type: str = Query(...)):
    """Single WS endpoint multiplexed by client_type=injector|hud.

    Auth: expects a `token` query param or `Authorization` header carrying a
    JWT; validated in auth.validate_ws_token before accepting the socket.
    """
    role = await validate_ws_token(websocket)
    if role is None:
        await websocket.close(code=4401)  # custom: unauthorized
        return

    if client_type not in ("injector", "hud"):
        await websocket.close(code=4400)  # custom: bad request
        return

    await websocket.accept()

    if client_type == "hud":
        await manager.connect(websocket)
        try:
            while True:
                # HUD clients are broadcast-only; drain any pings/keepalives.
                await websocket.receive_text()
        except WebSocketDisconnect:
            await manager.disconnect(websocket)
        return

    # client_type == "injector"
    if role != Role.PROPULSION_ENGINEER and role != Role.SYSTEM:
        # Tighten as needed — who is allowed to inject raw frames.
        await websocket.close(code=4403)
        return
    try:
        while True:
            raw = await websocket.receive_json()
            try:
                frame = TelemetryFrame.model_validate(raw)
            except Exception as exc:
                log.warning("Rejected malformed frame: %s", exc)
                continue
            await handle_inbound_frame(frame)
    except WebSocketDisconnect:
        log.info("Injector client disconnected")
