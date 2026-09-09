"""
Dev-only telemetry simulator. Sends 20Hz signed JSON envelopes over UDP
shaped like the real inbound schema, so the backend + HUD can be exercised
without real Rotax 912 ULS hardware or a radio link. Not used in
production/air-gapped deployment — enabled only via `docker compose
--profile dev up`.

Signs each frame with the same shared secret the backend expects
(MAVLINK_SHARED_SECRET) — the backend now rejects unsigned packets outright,
so this simulator has to play by the same rules as a real sender. The
signing logic is duplicated (not imported from app.security) so this
container's image doesn't need the rest of the backend package bundled in.
"""

import hashlib
import hmac
import json
import os
import socket
import time

TARGET_HOST = os.getenv("TARGET_HOST", "backend")
TARGET_PORT = int(os.getenv("TARGET_PORT", "14550"))
MAVLINK_SHARED_SECRET = os.getenv("MAVLINK_SHARED_SECRET", "")
HZ = 20
PERIOD = 1.0 / HZ


def _canonical_payload_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(payload: dict, timestamp: float) -> str:
    key = hashlib.sha256(MAVLINK_SHARED_SECRET.encode("utf-8")).digest()
    message = (
        f"{timestamp:.6f}".encode("utf-8") + b"|" + _canonical_payload_bytes(payload)
    )
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def main() -> None:
    if not MAVLINK_SHARED_SECRET:
        print(
            "WARNING: MAVLINK_SHARED_SECRET is not set — the backend will "
            "reject every packet this simulator sends as unsigned."
        )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t = 0.0
    print(f"Simulating signed telemetry -> udp://{TARGET_HOST}:{TARGET_PORT} @ {HZ}Hz")
    while True:
        payload = {
            "timestamp": time.time(),
            "cyl_1_temp": 120.0 + 3 * (t % 5),
            "cyl_2_temp": 121.0 + 2 * (t % 5),
            "cyl_3_temp": 122.0 + 4 * (t % 5),
            "cyl_4_temp": 119.5 + 3 * (t % 5),
            "oil_pressure": 3.6,
            "rpm": 5200.0,
        }
        timestamp = time.time()
        envelope = {
            "payload": payload,
            "timestamp": timestamp,
            "signature": _sign(payload, timestamp),
        }
        sock.sendto(json.dumps(envelope).encode("utf-8"), (TARGET_HOST, TARGET_PORT))
        t += PERIOD
        time.sleep(PERIOD)


if __name__ == "__main__":
    main()
