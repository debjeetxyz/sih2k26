from pydantic import BaseModel, Field

# Sanity bounds — physically impossible values for a Rotax 912 ULS, used to
# reject garbage/malicious telemetry at the door (input sanitization).
# These are DELIBERATELY wide compared to real operating limits (e.g. normal
# CHT redline is ~150°C, normal oil pressure 2-5 bar) — tight operational
# thresholds are the inference/physics guardrail's job, not this layer's.
# This layer only catches "that's not a real sensor reading" territory.
_CHT_MIN_C, _CHT_MAX_C = -40.0, 300.0
_OIL_PRESSURE_MIN_BAR, _OIL_PRESSURE_MAX_BAR = 0.0, 10.0
_RPM_MAX = 7000.0  # Rotax 912 ULS redline is ~5800 RPM


class TelemetryFrame(BaseModel):
    """Inbound Rotax 912 ULS telemetry frame, 20Hz cadence."""

    timestamp: float
    cyl_1_temp: float = Field(
        ..., ge=_CHT_MIN_C, le=_CHT_MAX_C, description="CHT cylinder 1, degC"
    )
    cyl_2_temp: float = Field(
        ..., ge=_CHT_MIN_C, le=_CHT_MAX_C, description="CHT cylinder 2, degC"
    )
    cyl_3_temp: float = Field(
        ..., ge=_CHT_MIN_C, le=_CHT_MAX_C, description="CHT cylinder 3, degC"
    )
    cyl_4_temp: float = Field(
        ..., ge=_CHT_MIN_C, le=_CHT_MAX_C, description="CHT cylinder 4, degC"
    )
    oil_pressure: float = Field(
        ...,
        ge=_OIL_PRESSURE_MIN_BAR,
        le=_OIL_PRESSURE_MAX_BAR,
        description="Oil pressure, bar",
    )
    rpm: float = Field(..., ge=0, le=_RPM_MAX)
