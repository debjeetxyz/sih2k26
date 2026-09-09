"""
Telemetry smoothing + statistical anomaly detection.

Two distinct techniques, per spec:
  1. Moving-average smoothing — a simple rolling-window mean per channel,
     purely for noise reduction (e.g. cleaner HUD display / more stable
     model input). Does not affect what's considered anomalous.
  2. Kalman filter anomaly detection — a per-channel scalar Kalman filter
     tracks an expected state + uncertainty; a reading whose "innovation"
     (distance from the predicted state) is large relative to that
     uncertainty gets FLAGGED as anomalous.

Design choice: anomalous readings are FLAGGED, not dropped. A real,
fast-developing engine fault (e.g. oil pressure collapsing) can trigger the
exact same statistical signal as a sensor glitch. Silently discarding it
would hide the one reading a predictive-maintenance system most needs to
surface. Downstream (physics guardrail / inference / HUD alerting) is
where a decision about severity should be made, not here.

TODO (tuning): the process/measurement variance defaults below are
illustrative engineering estimates, not derived from real flight-test data.
Revisit with actual sensor noise characteristics once available.
"""

from collections import deque
from dataclasses import dataclass, field

TELEMETRY_CHANNELS = (
    "cyl_1_temp",
    "cyl_2_temp",
    "cyl_3_temp",
    "cyl_4_temp",
    "oil_pressure",
    "rpm",
)

# (process_variance, measurement_variance) per channel.
# - process_variance: how much we expect the TRUE value to drift between
#   samples on its own (higher = filter trusts new measurements more).
# - measurement_variance: expected sensor noise (higher = filter trusts its
#   own running estimate more, smooths harder).
_KALMAN_PARAMS: dict[str, tuple[float, float]] = {
    "cyl_1_temp": (0.05, 0.5),  # CHT changes slowly
    "cyl_2_temp": (0.05, 0.5),
    "cyl_3_temp": (0.05, 0.5),
    "cyl_4_temp": (0.05, 0.5),
    "oil_pressure": (0.01, 0.05),  # normally very stable
    "rpm": (50.0, 25.0),  # can change quickly under throttle input
}

# Normalized-innovation threshold (in standard deviations) above which a
# reading is flagged anomalous. Higher = fewer false positives, but slower
# to catch a real fast-onset fault.
_ANOMALY_SIGMA_THRESHOLD = 4.0

_MOVING_AVERAGE_WINDOW = 5  # samples; at 20Hz that's 250ms of smoothing


class _KalmanFilter1D:
    """Minimal scalar Kalman filter: one instance tracks one channel."""

    def __init__(self, process_variance: float, measurement_variance: float):
        self.q = process_variance
        self.r = measurement_variance
        self.x = 0.0  # current state estimate
        self.p = 1.0  # current estimate variance
        self._initialized = False

    def update(self, measurement: float) -> tuple[float, float]:
        """Feed in a new measurement, return (estimate, normalized_innovation).

        normalized_innovation is roughly "how many standard deviations away
        from predicted was this reading" — that's what anomaly detection
        thresholds against.
        """
        if not self._initialized:
            self.x = measurement
            self._initialized = True
            return self.x, 0.0

        # Predict step
        p_pred = self.p + self.q

        # Innovation: difference between measurement and prior estimate
        innovation = measurement - self.x
        innovation_variance = p_pred + self.r
        normalized_innovation = (
            innovation / (innovation_variance**0.5) if innovation_variance > 0 else 0.0
        )

        # Update step
        k = p_pred / innovation_variance if innovation_variance > 0 else 0.0
        self.x = self.x + k * innovation
        self.p = (1 - k) * p_pred

        return self.x, normalized_innovation


@dataclass
class SmoothingResult:
    smoothed: dict[str, float] = field(default_factory=dict)
    kalman_estimate: dict[str, float] = field(default_factory=dict)
    anomaly_flags: dict[str, bool] = field(default_factory=dict)
    anomaly_sigma: dict[str, float] = field(default_factory=dict)

    @property
    def any_anomaly(self) -> bool:
        return any(self.anomaly_flags.values())


class TelemetrySmoother:
    """Owns one moving-average buffer + one Kalman filter per channel.

    Single instance is meant to track ONE engine's telemetry stream over
    time — create one instance globally (see main.py), not per-frame.
    """

    def __init__(self) -> None:
        self._ma_buffers: dict[str, deque] = {
            ch: deque(maxlen=_MOVING_AVERAGE_WINDOW) for ch in TELEMETRY_CHANNELS
        }
        self._kalman: dict[str, _KalmanFilter1D] = {
            ch: _KalmanFilter1D(*_KALMAN_PARAMS[ch]) for ch in TELEMETRY_CHANNELS
        }

    def process(self, frame_dict: dict) -> SmoothingResult:
        result = SmoothingResult()
        for channel in TELEMETRY_CHANNELS:
            raw_value = frame_dict[channel]

            # Moving average
            buf = self._ma_buffers[channel]
            buf.append(raw_value)
            result.smoothed[channel] = sum(buf) / len(buf)

            # Kalman estimate + anomaly check
            estimate, normalized_innovation = self._kalman[channel].update(raw_value)
            result.kalman_estimate[channel] = estimate
            result.anomaly_sigma[channel] = normalized_innovation
            result.anomaly_flags[channel] = (
                abs(normalized_innovation) > _ANOMALY_SIGMA_THRESHOLD
            )

        return result
