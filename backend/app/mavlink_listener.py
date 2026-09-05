"""
Background asyncio task listening for MAVLink v2 frames on
udp:127.0.0.1:14550 and feeding decoded telemetry into the shared pipeline.

TODO (Sagar): validate MAVLink v2 packet signing / shared-secret token here
before frames are accepted, to prevent spoofed telemetry on the local link.

TODO (Debjeet): replace the JSON-passthrough decode below with real MAVLink
decoding via pymavlink (mavutil), mapping HIGHRES_IMU / SCALED_PRESSURE /
custom Rotax telemetry messages into TelemetryFrame fields.
"""

import asyncio
import json
import logging
import os
from typing import Awaitable, Callable

from app.schemas import TelemetryFrame

log = logging.getLogger("vayudev.mavlink")

MAVLINK_HOST = os.getenv("MAVLINK_HOST", "127.0.0.1")
MAVLINK_PORT = int(os.getenv("MAVLINK_PORT", "14550"))


class _MavlinkProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_frame: Callable[[TelemetryFrame], Awaitable[None]]):
        self._on_frame = on_frame
        self._loop = asyncio.get_event_loop()

    def datagram_received(self, data: bytes, addr) -> None:
        # Placeholder: expects JSON-encoded frames for now so the scaffold is
        # testable without a real MAVLink source. Swap for pymavlink parsing.
        try:
            payload = json.loads(data.decode("utf-8"))
            frame = TelemetryFrame.model_validate(payload)
        except Exception as exc:
            log.debug("Dropped unparseable UDP packet from %s: %s", addr, exc)
            return
        asyncio.run_coroutine_threadsafe(self._on_frame(frame), self._loop)


async def mavlink_udp_listener(
    on_frame: Callable[[TelemetryFrame], Awaitable[None]]
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
