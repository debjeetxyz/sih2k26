from pydantic import BaseModel, Field


class TelemetryFrame(BaseModel):
    """Inbound Rotax 912 ULS telemetry frame, 20Hz cadence."""

    timestamp: float
    cyl_1_temp: float = Field(..., description="CHT cylinder 1, degC")
    cyl_2_temp: float = Field(..., description="CHT cylinder 2, degC")
    cyl_3_temp: float = Field(..., description="CHT cylinder 3, degC")
    cyl_4_temp: float = Field(..., description="CHT cylinder 4, degC")
    oil_pressure: float = Field(..., description="Oil pressure, bar")
    rpm: float = Field(..., ge=0)
