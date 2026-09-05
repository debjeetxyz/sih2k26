"""
Background asyncio task listening for telemetry on udp:127.0.0.1:14550 and
feeding verified frames into the shared pipeline.

Every inbound datagram MUST be a signed envelope:
    {"payload": {...TelemetryFrame fields...}, "timestamp": <float>, "signature": "<hex>"}

The signature is HMAC-SHA256 over (timestamp || canonical JSON of payload),
keyed by SHA256(MAVLINK_SHARED_SECRET) — see security.py for the full
rationale and the real-MAVLink-v2-signing upgrade path. Anything that fails
signature verification, freshness, or replay checks is dropped and logged;
it never reaches the ring buffer or the HUD.

TODO (Debjeet): once the wire format moves to real encoded MAVLink v2
messages via pymavlink, replace this JSON envelope + HMAC scheme with
pymavlink's native mav.signing (set_key/sign_outgoing), and decode
HIGHRES_IMU / SCALED_PRESSURE / a custom Rotax dialect into TelemetryFrame
here instead of json.loads.
"""

import asyncio
import json
import logging
import os
from typing import Awaitable, Callable

from pydantic import ValidationError

from app.schemas import TelemetryFrame
from app.security import ReplayGuard, verify_signature

log = logging.getLogger("vayudev.mavlink")

MAVLINK_HOST = os.getenv("MAVLINK_HOST", "127.0.0.1")
MAVLINK_PORT = int(os.getenv("MAVLINK_PORT", "14550"))
MAVLINK_SHARED_SECRET = os.getenv("MAVLINK_SHARED_SECRET", "")
SIGNATURE_MAX_AGE_SECONDS = float(os.getenv("MAVLINK_SIGNATURE_MAX_AGE", "5.0"))

if not MAVLINK_SHARED_SECRET:
    log.warning(
        "MAVLINK_SHARED_SECRET is not set — every inbound UDP telemetry "
        "packet will be rejected as unsigned. Set it in .env before "
        "expecting real telemetry to flow."
    )


def _canonical_payload_bytes(payload: dict) -> bytes:
    """Deterministic byte encoding so sender and receiver sign/verify the
    exact same bytes regardless of dict key order."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class _MavlinkProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_frame: Callable[[TelemetryFrame], Awaitable[None]]):
        self._on_frame = on_frame
        self._loop = asyncio.get_event_loop()
        self._replay_guard = ReplayGuard(window_seconds=SIGNATURE_MAX_AGE_SECONDS)

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            envelope = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("Dropped unparseable UDP packet from %s", addr)
            return

        payload = envelope.get("payload")
        timestamp = envelope.get("timestamp")
        signature = envelope.get("signature")
        if payload is None or timestamp is None or signature is None:
            log.warning(
                "Dropped packet from %s: missing payload/timestamp/signature "
                "(unsigned packets are never accepted)",
                addr,
            )
            return

        ok, reason = verify_signature(
            canonical_payload=_canonical_payload_bytes(payload),
            timestamp=float(timestamp),
            signature_hex=str(signature),
            shared_secret=MAVLINK_SHARED_SECRET,
            max_age_seconds=SIGNATURE_MAX_AGE_SECONDS,
        )
        if not ok:
            log.warning("Rejected packet from %s: %s", addr, reason)
            return

        if not self._replay_guard.check_and_record(str(signature)):
            log.warning("Rejected packet from %s: replay of a valid signature", addr)
            return

        try:
            frame = TelemetryFrame.model_validate(payload)
        except ValidationError as exc:
            log.warning(
                "Rejected packet from %s: failed telemetry bounds validation: %s",
                addr,
                exc,
            )
            return

        asyncio.run_coroutine_threadsafe(self._on_frame(frame), self._loop)


async def mavlink_udp_listener(
    on_frame: Callable[[TelemetryFrame], Awaitable[None]],
) -> None:
    loop = asyncio.get_event_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _MavlinkProtocol(on_frame),
        local_addr=(MAVLINK_HOST, MAVLINK_PORT),
    )
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        transport.close()
