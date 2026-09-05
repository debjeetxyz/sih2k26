"""
Dev-only telemetry simulator. Sends 20Hz JSON frames over UDP shaped like
the real inbound schema, so the backend + HUD can be exercised without real
Rotax 912 ULS hardware or a radio link. Not used in production/air-gapped
deployment — enabled only via `docker compose --profile dev up`.
"""

import json
import os
import socket
import time

TARGET_HOST = os.getenv("TARGET_HOST", "backend")
TARGET_PORT = int(os.getenv("TARGET_PORT", "14550"))
HZ = 20
PERIOD = 1.0 / HZ


def main() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t = 0.0
    print(f"Simulating telemetry -> udp://{TARGET_HOST}:{TARGET_PORT} @ {HZ}Hz")
    while True:
        frame = {
            "timestamp": time.time(),
            "cyl_1_temp": 120.0 + 3 * (t % 5),
            "cyl_2_temp": 121.0 + 2 * (t % 5),
            "cyl_3_temp": 122.0 + 4 * (t % 5),
            "cyl_4_temp": 119.5 + 3 * (t % 5),
            "oil_pressure": 3.6,
            "rpm": 5200.0,
        }
        sock.sendto(json.dumps(frame).encode("utf-8"), (TARGET_HOST, TARGET_PORT))
        t += PERIOD
        time.sleep(PERIOD)


if __name__ == "__main__":
    main()
