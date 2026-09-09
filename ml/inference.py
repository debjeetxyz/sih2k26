"""
VayuDev - inference.py
=======================
Local inference server. Listens for telemetry frames from flight_injector.py
on ws://localhost:8000/ws/telemetry, runs the XGBoost RUL model, computes
real-time SHAP-equivalent feature attributions (via XGBoost's native
pred_contribs) for transparency, and separately determines primary_root_cause
via a deterministic physical-deviation check (reliable even at low fault
severity, where the SHAP decomposition can be ambiguous). Applies the
deterministic Physics Fallback Engine when ML confidence < 75%, and
broadcasts the enriched payload to any dashboard clients connected on
ws://localhost:8000/ws/dashboard.

Run:
    pip install fastapi uvicorn "xgboost>=2.0.0" joblib numpy
    uvicorn inference:app --host 0.0.0.0 --port 8000
"""

import json
import time
import logging
import glob
import asyncio
from collections import deque
from typing import Optional

import numpy as np
import joblib
import xgboost as xgb
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("vayu_inference")

MODEL_PATH = "vayu_xgboost_model.pkl"
CONFIDENCE_THRESHOLD_PCT = 75.0
SMOOTHING_WINDOW = 40  # frames (~2s at 20Hz) averaged before inference to
                       # damp sensor-noise excursions from reading as a fault

SMOOTHED_FIELDS = [
    "cyl_1_temp", "cyl_2_temp", "cyl_3_temp", "cyl_4_temp", "oil_pressure", "rpm",
    "egt_1_temp", "egt_2_temp", "egt_3_temp", "egt_4_temp", "vibration_rms",
    "fuel_flow_1", "fuel_flow_2", "fuel_flow_3", "fuel_flow_4", "oil_temp",
]


def smooth_frame(buffer: deque, latest_raw_frame: dict) -> dict:
    """Rolling average of the last SMOOTHING_WINDOW frames for the numeric
    sensor fields. timestamp always comes from the latest raw frame."""
    smoothed = {"timestamp": latest_raw_frame["timestamp"]}
    for field in SMOOTHED_FIELDS:
        smoothed[field] = float(np.mean([f[field] for f in buffer]))
    return smoothed

# ---------------------------------------------------------------------------
# Feature engineering (KEEP IN SYNC WITH vayu_colab_train.py)
# ---------------------------------------------------------------------------

FEATURE_COLUMNS = [
    "cyl_1_temp", "cyl_2_temp", "cyl_3_temp", "cyl_4_temp",
    "oil_pressure", "rpm",
    "egt_1_temp", "egt_2_temp", "egt_3_temp", "egt_4_temp", "vibration_rms",
    "fuel_flow_1", "fuel_flow_2", "fuel_flow_3", "fuel_flow_4", "oil_temp",
    "max_cyl_temp", "cyl_temp_range", "mean_cyl_temp",
    "cyl1_dev", "cyl2_dev", "cyl3_dev", "cyl4_dev",
    "mean_egt", "egt_range",
    "egt1_dev", "egt2_dev", "egt3_dev", "egt4_dev",
    "mean_fuel_flow", "fuel_flow_range",
    "fuel1_dev", "fuel2_dev", "fuel3_dev", "fuel4_dev",
]


def engineer_features(row: dict) -> dict:
    t1, t2, t3, t4 = row["cyl_1_temp"], row["cyl_2_temp"], row["cyl_3_temp"], row["cyl_4_temp"]
    mean_t = (t1 + t2 + t3 + t4) / 4.0
    max_t = max(t1, t2, t3, t4)
    min_t = min(t1, t2, t3, t4)
    out = dict(row)
    out["max_cyl_temp"] = max_t
    out["cyl_temp_range"] = max_t - min_t
    out["mean_cyl_temp"] = mean_t
    out["cyl1_dev"] = t1 - mean_t
    out["cyl2_dev"] = t2 - mean_t
    out["cyl3_dev"] = t3 - mean_t
    out["cyl4_dev"] = t4 - mean_t

    e1, e2, e3, e4 = row["egt_1_temp"], row["egt_2_temp"], row["egt_3_temp"], row["egt_4_temp"]
    mean_e = (e1 + e2 + e3 + e4) / 4.0
    out["mean_egt"] = mean_e
    out["egt_range"] = max(e1, e2, e3, e4) - min(e1, e2, e3, e4)
    out["egt1_dev"] = e1 - mean_e
    out["egt2_dev"] = e2 - mean_e
    out["egt3_dev"] = e3 - mean_e
    out["egt4_dev"] = e4 - mean_e

    f1, f2, f3, f4 = row["fuel_flow_1"], row["fuel_flow_2"], row["fuel_flow_3"], row["fuel_flow_4"]
    mean_f = (f1 + f2 + f3 + f4) / 4.0
    out["mean_fuel_flow"] = mean_f
    out["fuel_flow_range"] = max(f1, f2, f3, f4) - min(f1, f2, f3, f4)
    out["fuel1_dev"] = f1 - mean_f
    out["fuel2_dev"] = f2 - mean_f
    out["fuel3_dev"] = f3 - mean_f
    out["fuel4_dev"] = f4 - mean_f
    return out


def to_feature_vector(engineered_row: dict) -> np.ndarray:
    return np.array([[engineered_row[c] for c in FEATURE_COLUMNS]], dtype=float)


# ---------------------------------------------------------------------------
# Load model artifacts
# ---------------------------------------------------------------------------

logger.info("Loading model bundle from %s ...", MODEL_PATH)
model_bundle = joblib.load(MODEL_PATH)
median_model = model_bundle["median_model"]
lower_model = model_bundle["lower_model"]
upper_model = model_bundle["upper_model"]
RUL_CAP = float(model_bundle["rul_cap"])
NOMINAL_CYL_TEMP = float(model_bundle["nominal_cyl_temp"])
FAULT_CYL_TEMP = float(model_bundle["fault_cyl_temp"])
OIL_NOMINAL_MIN = float(model_bundle["oil_nominal_min"])
OIL_NOMINAL_MAX = float(model_bundle["oil_nominal_max"])
OIL_HARD_MIN = float(model_bundle["oil_hard_min"])
RPM_MIN = float(model_bundle["rpm_min"])
RPM_MAX = float(model_bundle["rpm_max"])
NOMINAL_EGT = float(model_bundle["nominal_egt"])
MISFIRE_EGT_TARGET = float(model_bundle["misfire_egt_target"])
INSTABILITY_EGT_TARGET = float(model_bundle["instability_egt_target"])
NOMINAL_VIBRATION = float(model_bundle["nominal_vibration"])
MISFIRE_VIBRATION_TARGET = float(model_bundle["misfire_vibration_target"])
INSTABILITY_VIBRATION_TARGET = float(model_bundle["instability_vibration_target"])
NOMINAL_FUEL_FLOW = float(model_bundle["nominal_fuel_flow"])
INJECTOR_FAULT_TARGET = float(model_bundle["injector_fault_target"])
NOMINAL_OIL_TEMP = float(model_bundle["nominal_oil_temp"])
OIL_TEMP_FAULT_TARGET = float(model_bundle["oil_temp_fault_target"])
COKING_EGT_TARGET = float(model_bundle["coking_egt_target"])
COKING_FUEL_FLOW_TARGET = float(model_bundle["coking_fuel_flow_target"])
IMBALANCE_VIBRATION_TARGET = float(model_bundle["imbalance_vibration_target"])

# --- Missing-sensor-field handling ---
REQUIRED_FIELDS = [
    "cyl_1_temp", "cyl_2_temp", "cyl_3_temp", "cyl_4_temp", "oil_pressure", "rpm",
    "egt_1_temp", "egt_2_temp", "egt_3_temp", "egt_4_temp", "vibration_rms",
    "fuel_flow_1", "fuel_flow_2", "fuel_flow_3", "fuel_flow_4", "oil_temp",
]
DEFAULT_FALLBACKS = {
    "cyl_1_temp": NOMINAL_CYL_TEMP, "cyl_2_temp": NOMINAL_CYL_TEMP,
    "cyl_3_temp": NOMINAL_CYL_TEMP, "cyl_4_temp": NOMINAL_CYL_TEMP,
    "oil_pressure": (OIL_NOMINAL_MIN + OIL_NOMINAL_MAX) / 2.0,
    "rpm": (RPM_MIN + RPM_MAX) / 2.0,
    "egt_1_temp": NOMINAL_EGT, "egt_2_temp": NOMINAL_EGT,
    "egt_3_temp": NOMINAL_EGT, "egt_4_temp": NOMINAL_EGT,
    "vibration_rms": NOMINAL_VIBRATION,
    "fuel_flow_1": NOMINAL_FUEL_FLOW, "fuel_flow_2": NOMINAL_FUEL_FLOW,
    "fuel_flow_3": NOMINAL_FUEL_FLOW, "fuel_flow_4": NOMINAL_FUEL_FLOW,
    "oil_temp": NOMINAL_OIL_TEMP,
}
SUSTAINED_MISSING_FRAMES = 40  # ~2s at 20Hz - beyond this it's a real sensor failure, not a blip

TREND_WINDOW_FRAMES = 200  # ~10s at 20Hz - long enough to smooth past momentary noise,
                            # short enough to react to a genuinely developing fault
TREND_MIN_FRAMES = 40      # don't report a trend until we have at least ~2s of history
CRITICAL_RUL_THRESHOLD = 50.0  # matches the "critical" severity tier used in recommend_action


def compute_trend(rul_history: deque) -> dict:
    """Fits a straight line to recent (timestamp, predicted_rul) pairs to
    report whether health is declining, stable, or improving, and - if
    declining - how long until it would hit the critical threshold at the
    current rate. This is separate from predicted_rul itself: RUL is the
    model's instant snapshot, trend is what's been happening over the last
    ~10 seconds."""
    if len(rul_history) < TREND_MIN_FRAMES:
        return {"direction": "Insufficient Data", "slope_per_sec": 0.0, "seconds_to_critical": None}

    times = np.array([t for t, _ in rul_history])
    ruls = np.array([r for _, r in rul_history])
    # Guard against a degenerate (near-zero-duration) window
    if times[-1] - times[0] < 0.5:
        return {"direction": "Insufficient Data", "slope_per_sec": 0.0, "seconds_to_critical": None}

    slope, intercept = np.polyfit(times, ruls, 1)

    if slope < -0.5:
        direction = "Declining"
    elif slope > 0.5:
        direction = "Improving"
    else:
        direction = "Stable"

    seconds_to_critical = None
    if slope < -0.01:
        current_rul = float(ruls[-1])
        if current_rul > CRITICAL_RUL_THRESHOLD:
            seconds_to_critical = round(float((current_rul - CRITICAL_RUL_THRESHOLD) / (-slope)), 1)
        else:
            seconds_to_critical = 0.0

    return {
        "direction": direction,
        "slope_per_sec": round(float(slope), 3),
        "seconds_to_critical": seconds_to_critical,
    }


def fill_missing_fields(raw_frame: dict, last_known_good: dict, missing_streak: dict):
    """Hold-last-value imputation for any field missing from an incoming
    telemetry frame. Returns the completed frame and the list of fields
    that were missing on THIS frame (empty list if the frame was complete)."""
    filled = dict(raw_frame)
    missing_now = []
    for field in REQUIRED_FIELDS:
        value = raw_frame.get(field)
        if value is None:
            missing_now.append(field)
            missing_streak[field] = missing_streak.get(field, 0) + 1
            filled[field] = last_known_good.get(field, DEFAULT_FALLBACKS[field])
        else:
            missing_streak[field] = 0
            last_known_good[field] = value
    if filled.get("timestamp") is None:
        filled["timestamp"] = last_known_good.get("timestamp", 0.0)
    else:
        last_known_good["timestamp"] = filled["timestamp"]
    return filled, missing_now

logger.info("Computing real-time SHAP-equivalent feature attributions via XGBoost's "
            "native pred_contribs (shown for transparency), while primary_root_cause "
            "uses a deterministic physical-deviation check (reliable at all severities).")

logger.info("Model + explainer loaded successfully.")

# ---------------------------------------------------------------------------
# Root cause grouping for SHAP attribution
# ---------------------------------------------------------------------------

NOMINAL_HEALTH_FRACTION = 0.9  # above this fraction of RUL_CAP => call it nominal


def compute_shap_feature_attributions(feature_vec: np.ndarray) -> dict:
    """Real per-feature SHAP values (via XGBoost's native pred_contribs -
    mathematically identical to shap.TreeExplainer's output). Informational
    only: shows the model's reasoning, but the final primary_root_cause
    decision uses the deterministic physical-deviation check instead, since
    that's provably reliable while this can occasionally be ambiguous at
    low severity when correlated features shift together."""
    dmatrix = xgb.DMatrix(feature_vec, feature_names=FEATURE_COLUMNS)
    contribs = median_model.get_booster().predict(dmatrix, pred_contribs=True)
    contrib_row = contribs[0][:-1]  # last column is the bias term
    return {f: round(float(v), 3) for f, v in zip(FEATURE_COLUMNS, contrib_row)}


def recommend_action(root_cause: str, predicted_rul: float) -> str:
    """Rule-based operator guidance: combines WHICH subsystem (root_cause)
    with HOW SEVERE (predicted_rul, as a fraction of RUL_CAP) to produce a
    concrete recommended action. Not a separate model - a decision table,
    the same approach real aviation/industrial alerting systems use."""
    if root_cause in ("Nominal Operation", "Undetermined"):
        return "No action required - engine operating within normal parameters."

    health_frac = predicted_rul / RUL_CAP

    if health_frac >= 0.70:
        tier = "mild"
    elif health_frac >= 0.40:
        tier = "moderate"
    elif health_frac >= 0.10:
        tier = "severe"
    else:
        tier = "critical"

    if root_cause.startswith("Cylinder") and "Thermal" in root_cause:
        cyl_num = next((c for c in "1234" if c in root_cause), "?")
        actions = {
            "mild": f"Monitor Cylinder {cyl_num} temperature closely. Reduce throttle by ~15% to ease thermal load.",
            "moderate": f"Reduce throttle to ~55-60% power. Cylinder {cyl_num} temperature trending toward critical.",
            "severe": "Reduce throttle to minimum safe setting (~30% power). Prepare for precautionary landing.",
            "critical": f"Cylinder {cyl_num} thermal limit imminent. Abort mission - execute emergency landing immediately.",
        }
    elif "Oil" in root_cause:
        actions = {
            "mild": "Monitor oil pressure trend. Reduce throttle by ~15% to reduce engine load.",
            "moderate": "Reduce throttle to ~50% power. Check for a possible oil leak or pump issue on landing.",
            "severe": "Reduce power to minimum safe level. Land as soon as practical - oil pressure critical.",
            "critical": "Oil pressure at failure threshold. Abort mission - execute emergency landing immediately.",
        }
    elif "Misfire" in root_cause:
        cyl_num = next((c for c in "1234" if c in root_cause), "?")
        actions = {
            "mild": f"Cylinder {cyl_num} EGT drop detected. Monitor closely, reduce throttle by ~10-15%.",
            "moderate": f"Cylinder {cyl_num} misfire confirmed. Reduce throttle to ~50% power, monitor vibration trend.",
            "severe": f"Cylinder {cyl_num} misfire worsening, rough running. Reduce to minimum safe power, prepare for precautionary landing.",
            "critical": f"Cylinder {cyl_num} sustained misfire - vibration critical. Abort mission - execute emergency landing immediately.",
        }
    elif "Injector" in root_cause:
        cyl_num = next((c for c in "1234" if c in root_cause), "?")
        actions = {
            "mild": f"Cylinder {cyl_num} fuel flow reduced. Monitor closely, check injector on next inspection.",
            "moderate": f"Cylinder {cyl_num} injector abnormality confirmed. Reduce throttle to ~50% power.",
            "severe": f"Cylinder {cyl_num} fuel delivery critically low. Reduce to minimum safe power, prepare for precautionary landing.",
            "critical": f"Cylinder {cyl_num} injector failure - fuel delivery lost. Abort mission - execute emergency landing immediately.",
        }
    elif "Mechanical Imbalance" in root_cause or "Bearing Wear" in root_cause:
        actions = {
            "mild": "Slight vibration increase detected. Note for inspection - check propeller balance and mounts.",
            "moderate": "Vibration trending up with no combustion-side cause. Reduce throttle by ~15%, inspect mounts/balance on landing.",
            "severe": "Significant unexplained vibration. Reduce power to minimum safe level, prepare for precautionary landing.",
            "critical": "Severe mechanical vibration - structural risk. Abort mission - execute emergency landing immediately.",
        }
    elif "Coking Degradation" in root_cause:
        actions = {
            "mild": "Early carbon buildup signs. Note for next scheduled maintenance - no immediate action needed.",
            "moderate": "Coking degradation progressing. Schedule injector/valve cleaning at next maintenance window.",
            "severe": "Significant efficiency loss from coking. Reduce throttle by ~20%, schedule maintenance urgently.",
            "critical": "Severe coking - engine efficiency critically degraded. Reduce power, plan for maintenance before next flight.",
        }
    elif "Combustion Instability" in root_cause:
        actions = {
            "mild": "Combustion irregularity detected across cylinders. Monitor EGT spread and vibration trend.",
            "moderate": "Combustion instability increasing. Reduce throttle to ~55% power and monitor.",
            "severe": "Significant combustion instability. Reduce power to minimum safe level, prepare for precautionary landing.",
            "critical": "Severe combustion instability - engine damage risk. Abort mission - execute emergency landing immediately.",
        }
    elif "RPM" in root_cause:
        actions = {
            "mild": "RPM drifting from nominal band. Adjust throttle to recenter.",
            "moderate": "RPM instability increasing. Reduce throttle and monitor for further drift.",
            "severe": "RPM significantly out of band. Reduce power and prepare for precautionary landing.",
            "critical": "RPM critically unstable. Abort mission - execute emergency landing immediately.",
        }
    else:
        actions = {
            "mild": "Anomaly detected. Monitor closely.",
            "moderate": "Anomaly worsening. Reduce throttle and monitor.",
            "severe": "Significant anomaly. Reduce power and prepare for landing.",
            "critical": "Critical anomaly. Abort mission - execute emergency landing immediately.",
        }
    return actions[tier]


def determine_root_cause(raw_frame: dict, predicted_rul: float) -> str:
    """Deterministic root cause: since each fault type maps to exactly one
    known sensor, just check which sensor has drifted furthest (as a
    fraction of its known fault range) from its healthy value. This avoids
    the ML contribution decomposition getting confused by correlated
    features at low-to-moderate severity."""
    if predicted_rul >= NOMINAL_HEALTH_FRACTION * RUL_CAP:
        return "Nominal Operation"

    rpm_center = (RPM_MIN + RPM_MAX) / 2.0
    rpm_half_range = (RPM_MAX - RPM_MIN) / 2.0

    misfire_scores = {
        f"Cylinder {i} Misfire": (NOMINAL_EGT - raw_frame[f"egt_{i}_temp"]) / (NOMINAL_EGT - MISFIRE_EGT_TARGET)
        for i in range(1, 5)
    }
    # Combustion instability is a UNIFORM, all-cylinder EGT sag - not a
    # vibration comparison (both faults raise vibration, so vibration alone
    # can't reliably tell them apart, especially at higher severity where
    # misfire's own vibration can numerically look like "leftover instability").
    # The real discriminator is the SHAPE of the EGT drop: spread evenly
    # across all 4 cylinders (instability) vs concentrated in one (misfire).
    egt_values = [raw_frame[f"egt_{i}_temp"] for i in range(1, 5)]
    instability_scale = NOMINAL_EGT - INSTABILITY_EGT_TARGET
    avg_egt_drop_frac = sum((NOMINAL_EGT - e) / instability_scale for e in egt_values) / 4.0
    concentration = (max(egt_values) - min(egt_values)) / instability_scale
    instability_score = avg_egt_drop_frac - concentration

    injector_scores = {
        f"Cylinder {i} Injector Abnormality": (NOMINAL_FUEL_FLOW - raw_frame[f"fuel_flow_{i}"]) / (NOMINAL_FUEL_FLOW - INJECTOR_FAULT_TARGET)
        for i in range(1, 5)
    }

    # Coking is a UNIFORM, all-cylinder EGT RISE (opposite direction from
    # misfire/instability's drop, so no sign conflict) plus a mild, uniform
    # fuel flow reduction - penalized for concentration so a real injector
    # fault (severe, single-cylinder) doesn't get mistaken for coking.
    coking_egt_scale = COKING_EGT_TARGET - NOMINAL_EGT
    avg_egt_rise_frac = sum((e - NOMINAL_EGT) for e in egt_values) / 4.0 / coking_egt_scale
    fuel_values = [raw_frame[f"fuel_flow_{i}"] for i in range(1, 5)]
    coking_fuel_scale = NOMINAL_FUEL_FLOW - COKING_FUEL_FLOW_TARGET
    avg_fuel_drop_frac = sum((NOMINAL_FUEL_FLOW - f) for f in fuel_values) / 4.0 / coking_fuel_scale
    fuel_concentration = (max(fuel_values) - min(fuel_values)) / coking_fuel_scale
    coking_fuel_component = max(0.0, avg_fuel_drop_frac - fuel_concentration)
    coking_score = (avg_egt_rise_frac + coking_fuel_component) / 2.0

    # Oil diagnosis uses whichever corroborating sensor shows the bigger
    # problem - pressure OR temperature - so the fault is still caught even
    # if one of the two sensors has failed or is reading ambiguously.
    oil_pressure_score = (OIL_NOMINAL_MIN - raw_frame["oil_pressure"]) / (OIL_NOMINAL_MIN - OIL_HARD_MIN)
    oil_temp_score = (raw_frame["oil_temp"] - NOMINAL_OIL_TEMP) / (OIL_TEMP_FAULT_TARGET - NOMINAL_OIL_TEMP)
    oil_score = max(oil_pressure_score, oil_temp_score)

    # Mechanical imbalance is vibration rising with NO combustion-side
    # cause - penalized by how much EGT has moved (either direction), so a
    # real misfire/instability/coking event (which DOES move EGT) doesn't
    # get mistaken for a purely mechanical issue.
    egt_max_deviation_frac = max(abs(e - NOMINAL_EGT) for e in egt_values) / (NOMINAL_EGT - MISFIRE_EGT_TARGET)
    imbalance_score = (raw_frame["vibration_rms"] - NOMINAL_VIBRATION) / (IMBALANCE_VIBRATION_TARGET - NOMINAL_VIBRATION)
    imbalance_score -= egt_max_deviation_frac

    scores = {
        "Cylinder 1 Thermal Degradation": (raw_frame["cyl_1_temp"] - NOMINAL_CYL_TEMP) / (FAULT_CYL_TEMP - NOMINAL_CYL_TEMP),
        "Cylinder 2 Thermal Degradation": (raw_frame["cyl_2_temp"] - NOMINAL_CYL_TEMP) / (FAULT_CYL_TEMP - NOMINAL_CYL_TEMP),
        "Cylinder 3 Thermal Degradation": (raw_frame["cyl_3_temp"] - NOMINAL_CYL_TEMP) / (FAULT_CYL_TEMP - NOMINAL_CYL_TEMP),
        "Cylinder 4 Thermal Degradation": (raw_frame["cyl_4_temp"] - NOMINAL_CYL_TEMP) / (FAULT_CYL_TEMP - NOMINAL_CYL_TEMP),
        "Oil System Pressure Loss": oil_score,
        "Mechanical Imbalance / Bearing Wear": imbalance_score,
        "RPM Instability": (abs(raw_frame["rpm"] - rpm_center) - rpm_half_range * 0.5) / (rpm_half_range * 0.5),
        "Combustion Instability": instability_score,
        "Coking Degradation": coking_score,
        **misfire_scores,
        **injector_scores,
    }
    best_cause = max(scores, key=scores.get)
    if scores[best_cause] <= 0:
        return "Undetermined"
    return best_cause


# ---------------------------------------------------------------------------
# Physics Fallback Engine (deterministic thermodynamic limits)
# ---------------------------------------------------------------------------

def physics_fallback(raw_frame: dict) -> dict:
    """Deterministic, model-free RUL estimate based on hard thermodynamic
    and mechanical limits. Used whenever ML confidence is too low to trust."""
    cyl_temps = {
        1: raw_frame["cyl_1_temp"],
        2: raw_frame["cyl_2_temp"],
        3: raw_frame["cyl_3_temp"],
        4: raw_frame["cyl_4_temp"],
    }
    oil_pressure = raw_frame["oil_pressure"]
    rpm_val = raw_frame["rpm"]

    # Thermal margin per cylinder: 1.0 = fully nominal, 0.0 = at/over hard limit
    thermal_margins = {
        idx: float(np.clip(
            (FAULT_CYL_TEMP - temp) / (FAULT_CYL_TEMP - NOMINAL_CYL_TEMP), 0.0, 1.0
        ))
        for idx, temp in cyl_temps.items()
    }
    worst_cyl_idx = min(thermal_margins, key=thermal_margins.get)
    worst_thermal_margin = thermal_margins[worst_cyl_idx]

    # EGT margin per cylinder (misfire indicator): 1.0 = nominal, 0.0 = at/below misfire floor
    egt_margins = {
        idx: float(np.clip(
            (raw_frame[f"egt_{idx}_temp"] - MISFIRE_EGT_TARGET) / (NOMINAL_EGT - MISFIRE_EGT_TARGET), 0.0, 1.0
        ))
        for idx in range(1, 5)
    }
    worst_egt_idx = min(egt_margins, key=egt_margins.get)
    worst_egt_margin = egt_margins[worst_egt_idx]

    # Oil pressure margin: 1.0 = nominal, 0.0 = at hard minimum
    oil_pressure_margin = float(np.clip(
        (oil_pressure - OIL_HARD_MIN) / (OIL_NOMINAL_MIN - OIL_HARD_MIN), 0.0, 1.0
    ))
    # Oil temperature margin: 1.0 = nominal, 0.0 = at fault target - a
    # corroborating check, so an oil problem is still caught if the
    # pressure sensor itself has failed.
    oil_temp_margin = float(np.clip(
        (OIL_TEMP_FAULT_TARGET - raw_frame["oil_temp"]) / (OIL_TEMP_FAULT_TARGET - NOMINAL_OIL_TEMP), 0.0, 1.0
    ))
    oil_margin = min(oil_pressure_margin, oil_temp_margin)

    # Fuel flow margin per cylinder (injector indicator): 1.0 = nominal, 0.0 = at/below injector fault floor
    fuel_margins = {
        idx: float(np.clip(
            (raw_frame[f"fuel_flow_{idx}"] - INJECTOR_FAULT_TARGET) / (NOMINAL_FUEL_FLOW - INJECTOR_FAULT_TARGET), 0.0, 1.0
        ))
        for idx in range(1, 5)
    }
    worst_fuel_idx = min(fuel_margins, key=fuel_margins.get)
    worst_fuel_margin = fuel_margins[worst_fuel_idx]

    # RPM out-of-band flag (informational; doesn't drive RUL directly here)
    rpm_out_of_band = not (RPM_MIN <= rpm_val <= RPM_MAX)

    # Conservative worst-case governs across all subsystems
    margins = {
        ("thermal", worst_cyl_idx): worst_thermal_margin,
        ("egt", worst_egt_idx): worst_egt_margin,
        ("oil", None): oil_margin,
        ("fuel", worst_fuel_idx): worst_fuel_margin,
    }
    worst_key = min(margins, key=margins.get)
    worst_kind, worst_idx = worst_key
    fallback_rul = margins[worst_key] * RUL_CAP

    if margins[worst_key] >= NOMINAL_HEALTH_FRACTION:
        root_cause = "Nominal Operation"
    elif worst_kind == "thermal":
        root_cause = f"Cylinder {worst_idx} Thermal Limit Exceeded (Physics Bound)"
    elif worst_kind == "egt":
        root_cause = f"Cylinder {worst_idx} Misfire (Physics Bound)"
    elif worst_kind == "fuel":
        root_cause = f"Cylinder {worst_idx} Injector Abnormality (Physics Bound)"
    else:
        root_cause = "Oil Pressure Critical (Physics Bound)"

    if rpm_out_of_band and fallback_rul > 0.2 * RUL_CAP:
        root_cause = "RPM Out of Operating Band (Physics Bound)"

    return {"predicted_rul": float(fallback_rul), "primary_root_cause": root_cause}


# ---------------------------------------------------------------------------
# Core evaluation logic
# ---------------------------------------------------------------------------

def run_inference(raw_frame: dict, missing_fields: Optional[list] = None) -> dict:
    """raw_frame must contain: timestamp, cyl_1..4_temp, oil_pressure, rpm.
    missing_fields (if provided) lists any fields that were imputed for this
    frame - used to penalize confidence, since a prediction built partly on
    a held-over last-known value is less trustworthy than one built on live
    sensor data."""
    engineered = engineer_features(raw_frame)
    feature_vec = to_feature_vector(engineered)

    median_pred = float(median_model.predict(feature_vec)[0])
    lower_pred = float(lower_model.predict(feature_vec)[0])
    upper_pred = float(upper_model.predict(feature_vec)[0])

    interval_width = max(0.0, upper_pred - lower_pred)
    confidence_frac = float(np.clip(1.0 - (interval_width / (2.0 * RUL_CAP)), 0.0, 1.0))
    confidence_pct = confidence_frac * 100.0

    if missing_fields:
        # Compound penalty per missing field - one imputed field is a mild
        # ding, several at once should push confidence down hard.
        confidence_pct *= 0.7 ** len(missing_fields)

    # Out-of-training-range override: tree-based models don't extrapolate
    # reliably - beyond the trained range they can be confidently WRONG
    # instead of correctly recognizing things got worse. If any sensor is
    # more extreme than anything seen in training, don't trust the ML
    # answer at all - force the Physics Fallback Engine, which uses plain
    # linear math and has no such limitation.
    out_of_training_range = (
        raw_frame["oil_pressure"] < OIL_HARD_MIN
        or any(raw_frame[f"cyl_{i}_temp"] > FAULT_CYL_TEMP for i in range(1, 5))
        or any(raw_frame[f"egt_{i}_temp"] < MISFIRE_EGT_TARGET for i in range(1, 5))
        or any(raw_frame[f"egt_{i}_temp"] > COKING_EGT_TARGET for i in range(1, 5))
        or raw_frame["vibration_rms"] > MISFIRE_VIBRATION_TARGET
        or not (RPM_MIN <= raw_frame["rpm"] <= RPM_MAX)
        or any(raw_frame[f"fuel_flow_{i}"] < INJECTOR_FAULT_TARGET for i in range(1, 5))
        or raw_frame["oil_temp"] > OIL_TEMP_FAULT_TARGET
    )
    if out_of_training_range:
        confidence_pct = min(confidence_pct, CONFIDENCE_THRESHOLD_PCT - 0.01)

    # Real-time SHAP-equivalent feature attributions - computed every frame,
    # shown for transparency, independent of which path (ML/fallback) or
    # root-cause decision below.
    shap_attrs = compute_shap_feature_attributions(feature_vec)

    if confidence_pct < CONFIDENCE_THRESHOLD_PCT:
        fb = physics_fallback(raw_frame)
        payload = {
            "timestamp": raw_frame["timestamp"],
            "cyl_1_temp": raw_frame["cyl_1_temp"],
            "cyl_2_temp": raw_frame["cyl_2_temp"],
            "cyl_3_temp": raw_frame["cyl_3_temp"],
            "cyl_4_temp": raw_frame["cyl_4_temp"],
            "oil_pressure": raw_frame["oil_pressure"],
            "rpm": raw_frame["rpm"],
            "egt_1_temp": raw_frame["egt_1_temp"],
            "egt_2_temp": raw_frame["egt_2_temp"],
            "egt_3_temp": raw_frame["egt_3_temp"],
            "egt_4_temp": raw_frame["egt_4_temp"],
            "vibration_rms": raw_frame["vibration_rms"],
            "fuel_flow_1": raw_frame["fuel_flow_1"],
            "fuel_flow_2": raw_frame["fuel_flow_2"],
            "fuel_flow_3": raw_frame["fuel_flow_3"],
            "fuel_flow_4": raw_frame["fuel_flow_4"],
            "oil_temp": raw_frame["oil_temp"],
            "predicted_rul": fb["predicted_rul"],
            "ml_confidence": round(confidence_pct, 2),
            "source": "PHYSICS_FALLBACK",
            "primary_root_cause": fb["primary_root_cause"],
            "recommended_action": recommend_action(fb["primary_root_cause"], fb["predicted_rul"]),
            "shap_feature_attributions": shap_attrs,
            "missing_fields": missing_fields or [],
        }
    else:
        root_cause = determine_root_cause(raw_frame, median_pred)
        payload = {
            "timestamp": raw_frame["timestamp"],
            "cyl_1_temp": raw_frame["cyl_1_temp"],
            "cyl_2_temp": raw_frame["cyl_2_temp"],
            "cyl_3_temp": raw_frame["cyl_3_temp"],
            "cyl_4_temp": raw_frame["cyl_4_temp"],
            "oil_pressure": raw_frame["oil_pressure"],
            "rpm": raw_frame["rpm"],
            "egt_1_temp": raw_frame["egt_1_temp"],
            "egt_2_temp": raw_frame["egt_2_temp"],
            "egt_3_temp": raw_frame["egt_3_temp"],
            "egt_4_temp": raw_frame["egt_4_temp"],
            "vibration_rms": raw_frame["vibration_rms"],
            "fuel_flow_1": raw_frame["fuel_flow_1"],
            "fuel_flow_2": raw_frame["fuel_flow_2"],
            "fuel_flow_3": raw_frame["fuel_flow_3"],
            "fuel_flow_4": raw_frame["fuel_flow_4"],
            "oil_temp": raw_frame["oil_temp"],
            "predicted_rul": round(max(0.0, median_pred), 2),
            "ml_confidence": round(confidence_pct, 2),
            "source": "XGBOOST_ML",
            "primary_root_cause": root_cause,
            "recommended_action": recommend_action(root_cause, median_pred),
            "shap_feature_attributions": shap_attrs,
            "missing_fields": missing_fields or [],
        }
    return payload


# ---------------------------------------------------------------------------
# FastAPI app: telemetry ingest + dashboard broadcast
# ---------------------------------------------------------------------------

app = FastAPI(title="VayuDev Inference Service")

# Shared-secret token required on both websocket connections. This is
# genuine server-side enforcement (not just UI) - it stops other devices on
# the network from connecting even if they find the port. It is NOT full
# authentication (no per-user identity, no expiry) - that remains the
# team's real auth system to build separately.
ACCESS_TOKEN = "vayudev-2026-demo"


class DashboardHub:
    def __init__(self):
        self.clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, payload: dict):
        stale = []
        for client in self.clients:
            try:
                await client.send_text(json.dumps(payload))
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(client)


dashboard_hub = DashboardHub()


@app.websocket("/ws/telemetry")
async def telemetry_endpoint(websocket: WebSocket):
    """Receives raw telemetry frames from flight_injector.py at 20 Hz."""
    if websocket.query_params.get("token") != ACCESS_TOKEN:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    logger.info("flight_injector connected on /ws/telemetry")
    last_root_cause = None
    pending_cause = None
    pending_count = 0
    CONFIRM_FRAMES_ENTER = 15  # frames of a NEW cause before declaring it (0.75s)
    CONFIRM_FRAMES_CLEAR = 100  # frames of Nominal before clearing an active fault (5s) -
                                # much stricter than entering, so brief within-episode
                                # dips don't repeatedly reset and re-trigger the same fault
    buffer: deque = deque(maxlen=SMOOTHING_WINDOW)
    last_known_good: dict = {}
    missing_streak: dict = {}
    sensor_failure_logged: set = set()
    rul_history: deque = deque(maxlen=TREND_WINDOW_FRAMES)
    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                raw_frame_in = json.loads(raw_text)
                filled_frame, missing_now = fill_missing_fields(raw_frame_in, last_known_good, missing_streak)

                if missing_now:
                    logger.warning("Missing fields this frame (imputed via last-known-value): %s", missing_now)

                # Sustained failure check - a field silent for SUSTAINED_MISSING_FRAMES
                # in a row is a real sensor failure, not a transient dropout.
                newly_failed = [
                    f for f in REQUIRED_FIELDS
                    if missing_streak.get(f, 0) >= SUSTAINED_MISSING_FRAMES and f not in sensor_failure_logged
                ]
                for f in newly_failed:
                    sensor_failure_logged.add(f)
                    logger.warning(
                        "SENSOR FAILURE: '%s' has not reported for %.1fs - relying on last-known-value/physics estimate.",
                        f, missing_streak[f] / 20.0,
                    )
                recovered = [f for f in list(sensor_failure_logged) if missing_streak.get(f, 0) == 0]
                for f in recovered:
                    sensor_failure_logged.discard(f)
                    logger.info("SENSOR RECOVERED: '%s' is reporting again.", f)

                buffer.append(filled_frame)
                # Wait until the buffer is full so the average isn't skewed
                # by a partial window right after connecting.
                if len(buffer) < SMOOTHING_WINDOW:
                    continue
                smoothed = smooth_frame(buffer, filled_frame)
                payload = run_inference(smoothed, missing_fields=missing_now)

                if sensor_failure_logged:
                    failed_field = next(iter(sensor_failure_logged))
                    payload["primary_root_cause"] = f"Sensor Failure: {failed_field} not reporting"
                    payload["recommended_action"] = (
                        f"Sensor '{failed_field}' has not reported valid data for "
                        f"{missing_streak[failed_field] / 20.0:.1f}s. Relying on last-known-value/physics "
                        "estimate. Flag for ground maintenance inspection on landing."
                    )

                rul_history.append((payload["timestamp"], payload["predicted_rul"]))
                payload["trend"] = compute_trend(rul_history)
            except Exception as exc:
                logger.exception("Inference error on frame: %s", exc)
                continue

            if payload["source"] == "PHYSICS_FALLBACK":
                logger.warning(
                    "t=%.2f FALLBACK rul=%.1f cause=%s conf=%.1f%%  ACTION: %s",
                    payload["timestamp"], payload["predicted_rul"],
                    payload["primary_root_cause"], payload["ml_confidence"],
                    payload["recommended_action"],
                )

            cause = payload["primary_root_cause"]
            required_frames = CONFIRM_FRAMES_CLEAR if cause == "Nominal Operation" else CONFIRM_FRAMES_ENTER

            if cause == last_root_cause:
                pending_cause, pending_count = None, 0
            else:
                if cause == pending_cause:
                    pending_count += 1
                else:
                    pending_cause, pending_count = cause, 1

                if pending_count >= required_frames:
                    if cause != "Nominal Operation":
                        logger.info(
                            "FAULT DETECTED: %s  ACTION: %s  TREND: %s (%.1f RUL/s%s)  (t=%.2f rul=%.1f conf=%.1f%% source=%s "
                            "cyl_temps=[%.1f,%.1f,%.1f,%.1f] oil=%.2f egt=[%.1f,%.1f,%.1f,%.1f] vib=%.2f)",
                            cause, payload["recommended_action"],
                            payload["trend"]["direction"], payload["trend"]["slope_per_sec"],
                            f", critical in {payload['trend']['seconds_to_critical']}s" if payload["trend"]["seconds_to_critical"] is not None else "",
                            payload["timestamp"], payload["predicted_rul"],
                            payload["ml_confidence"], payload["source"],
                            payload["cyl_1_temp"], payload["cyl_2_temp"],
                            payload["cyl_3_temp"], payload["cyl_4_temp"],
                            payload["oil_pressure"],
                            payload["egt_1_temp"], payload["egt_2_temp"],
                            payload["egt_3_temp"], payload["egt_4_temp"],
                            payload["vibration_rms"],
                        )
                    last_root_cause = cause
                    pending_cause, pending_count = None, 0

            await dashboard_hub.broadcast(payload)
    except WebSocketDisconnect:
        logger.info("flight_injector disconnected from /ws/telemetry")


@app.websocket("/ws/dashboard")
async def dashboard_endpoint(websocket: WebSocket):
    """3D digital-twin frontend connects here to receive enriched payloads."""
    if websocket.query_params.get("token") != ACCESS_TOKEN:
        await websocket.close(code=4401)
        return
    await dashboard_hub.connect(websocket)
    try:
        while True:
            # Dashboard is read-only; just keep the connection alive.
            await websocket.receive_text()
    except WebSocketDisconnect:
        dashboard_hub.disconnect(websocket)


@app.get("/health")
async def health():
    return {"status": "ok", "time": time.time(), "dashboard_clients": len(dashboard_hub.clients)}


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the dashboard directly - visiting https://localhost:8000/ opens
    the full app, no separate HTML file to locate or open manually."""
    try:
        with open("vayudev_dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>vayudev_dashboard.html not found</h1>"
            "<p>Make sure it's in the same folder as inference.py.</p>",
            status_code=404,
        )


# ---------------------------------------------------------------------------
# Connect UAV - lets the browser pick a flight and start streaming it,
# instead of needing a separate terminal/injector process to be run manually.
# ---------------------------------------------------------------------------
_injector_task: Optional[asyncio.Task] = None
_injector_dataset: Optional[str] = None


@app.get("/api/datasets")
async def list_datasets():
    files = sorted(glob.glob("dataset_2_*.csv"))
    return {"datasets": files, "active": _injector_dataset}


@app.post("/api/connect_uav")
async def connect_uav(request: Request):
    global _injector_task, _injector_dataset
    body = await request.json()
    dataset = body.get("dataset")

    valid = sorted(glob.glob("dataset_2_*.csv"))
    if dataset not in valid:
        return JSONResponse({"error": "Unknown dataset"}, status_code=400)

    # Import here (not top-level) to avoid a circular import, since
    # flight_injector.py doesn't need to know about inference.py at all.
    import flight_injector

    if _injector_task and not _injector_task.done():
        _injector_task.cancel()

    uri = f"wss://localhost:8000/ws/telemetry?token={ACCESS_TOKEN}"
    _injector_task = asyncio.create_task(
        flight_injector.stream_flight(dataset, uri, loop_playback=False, reconnect_delay=2.0)
    )
    _injector_dataset = dataset
    logger.info("UAV connected via browser - streaming %s", dataset)
    return {"status": "connected", "dataset": dataset}


if __name__ == "__main__":
    import uvicorn
    import os
    ssl_args = {}
    if os.path.exists("cert.pem") and os.path.exists("key.pem"):
        ssl_args = {"ssl_certfile": "cert.pem", "ssl_keyfile": "key.pem"}
        logger.info("TLS certificate found - serving over wss:// (encrypted)")
    else:
        logger.warning("No cert.pem/key.pem found - serving unencrypted ws://. "
                        "Place both files next to inference.py to enable encryption.")
    uvicorn.run("inference:app", host="0.0.0.0", port=8000, log_level="info", **ssl_args)
