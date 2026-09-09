"""
VayuDev - flight_injector.py
=============================
Reads Dataset 2 (dataset_2_playback.csv) frame-by-frame and streams it over
WebSockets to the inference server at 20 Hz (0.05s interval), simulating a
real-time flight with an injected Cylinder 3 thermal anomaly.

Run:
    pip install websockets pandas
    python flight_injector.py --csv dataset_2_playback.csv --uri ws://localhost:8000/ws/telemetry
"""

import argparse
import asyncio
import json
import logging
import ssl
import time

import pandas as pd
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("flight_injector")

HZ = 20
INTERVAL_SECONDS = 1.0 / HZ
ACCESS_TOKEN = "vayudev-2026-demo"  # must match ACCESS_TOKEN in inference.py

PAYLOAD_FIELDS = [
    "timestamp", "cyl_1_temp", "cyl_2_temp", "cyl_3_temp", "cyl_4_temp",
    "oil_pressure", "rpm",
    "egt_1_temp", "egt_2_temp", "egt_3_temp", "egt_4_temp", "vibration_rms",
    "fuel_flow_1", "fuel_flow_2", "fuel_flow_3", "fuel_flow_4", "oil_temp",
]


def load_dataset(csv_path: str) -> list[dict]:
    df = pd.read_csv(csv_path)
    missing = [c for c in PAYLOAD_FIELDS if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")
    return df[PAYLOAD_FIELDS].to_dict("records")


async def stream_flight(csv_path: str, uri: str, loop_playback: bool, reconnect_delay: float):
    frames = load_dataset(csv_path)
    logger.info("Loaded %d frames from %s", len(frames), csv_path)

    ssl_context = None
    if uri.startswith("wss://"):
        # Self-signed local cert - encrypt the connection without requiring
        # a real trusted CA (fine for a local demo, not for production).
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    while True:
        try:
            async with websockets.connect(uri, ssl=ssl_context) as ws:
                logger.info("Connected to %s - starting stream at %d Hz", uri, HZ)
                start_wall_clock = time.perf_counter()

                while True:
                    for i, frame in enumerate(frames):
                        tick_start = time.perf_counter()

                        outgoing = dict(frame)
                        # Use live wall-clock time so the receiver sees a real
                        # monotonically increasing timestamp during the demo.
                        outgoing["timestamp"] = round(
                            start_wall_clock + i * INTERVAL_SECONDS, 3
                        )

                        await ws.send(json.dumps(outgoing))

                        elapsed = time.perf_counter() - tick_start
                        sleep_time = max(0.0, INTERVAL_SECONDS - elapsed)
                        await asyncio.sleep(sleep_time)

                    logger.info("Reached end of dataset_2 playback (%d frames sent)", len(frames))
                    if not loop_playback:
                        return
                    logger.info("Looping playback from the start...")
                    start_wall_clock = time.perf_counter()

        except (ConnectionRefusedError, websockets.exceptions.WebSocketException, OSError) as exc:
            logger.warning("Connection issue (%s). Retrying in %.1fs...", exc, reconnect_delay)
            await asyncio.sleep(reconnect_delay)


def main():
    parser = argparse.ArgumentParser(description="VayuDev flight telemetry injector")
    parser.add_argument("--csv", default="dataset_2_playback.csv", help="Path to Dataset 2 CSV")
    parser.add_argument("--uri", default=f"wss://localhost:8000/ws/telemetry?token={ACCESS_TOKEN}", help="Telemetry websocket URI")
    parser.add_argument("--loop", action="store_true", help="Loop playback indefinitely")
    parser.add_argument("--reconnect-delay", type=float, default=2.0, help="Seconds between reconnect attempts")
    args = parser.parse_args()

    try:
        asyncio.run(stream_flight(args.csv, args.uri, args.loop, args.reconnect_delay))
    except KeyboardInterrupt:
        logger.info("Injector stopped by user.")


if __name__ == "__main__":
    main()
