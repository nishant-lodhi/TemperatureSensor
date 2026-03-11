"""Pure analytics — stats, anomaly detection, forecasting.

All functions are stateless: numpy in, dicts out. No DB, no I/O.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np


def signal_label(rssi: float) -> str:
    if rssi >= -50:
        return "Strong"
    if rssi >= -65:
        return "Good"
    if rssi >= -80:
        return "Weak"
    return "No Signal"


def compute_rolling(temps: list[float]) -> dict:
    """1-hour rolling stats from a list of temperature floats."""
    if not temps:
        return {"avg": 0.0, "std": 0.0, "high": 0.0, "low": 0.0}
    arr = np.array(temps, dtype=float)
    return {
        "avg": round(float(np.mean(arr)), 2),
        "std": round(float(np.std(arr, ddof=1)), 4) if len(arr) > 1 else 0.0,
        "high": round(float(np.max(arr)), 2),
        "low": round(float(np.min(arr)), 2),
    }


def compute_rate_of_change(temp_now: float, hist_rows: list[dict],
                           ref_time: datetime, window_min: int = 10) -> float:
    """Rate of change over the last N minutes."""
    cutoff = ref_time - timedelta(minutes=window_min)
    for r in hist_rows:
        ts = r.get("date_added")
        if isinstance(ts, datetime) and ts <= cutoff:
            try:
                return round(temp_now - float(r["body_temperature"]), 2)
            except (ValueError, TypeError):
                pass
            break
    return 0.0


def is_anomaly(temp: float, avg: float, std: float,
               critical_high: float, critical_low: float) -> tuple[bool, str | None]:
    """Z-score + threshold anomaly detection. Returns (is_anomaly, reason)."""
    if temp > critical_high:
        return True, f"Temperature {temp:.1f}°F exceeds critical high ({critical_high}°F)"
    if temp < critical_low:
        return True, f"Temperature {temp:.1f}°F below critical low ({critical_low}°F)"
    if std > 0:
        z = abs(temp - avg) / std
        if z > 2.5:
            return True, f"Statistical anomaly (z-score {z:.1f})"
    return False, None


def compute_sensor_status(age_sec: float, degraded_thresh: float, offline_thresh: float) -> str:
    """Three-state: online / degraded / offline."""
    if age_sec > offline_thresh:
        return "offline"
    if age_sec > degraded_thresh:
        return "degraded"
    return "online"


def build_sensor_state(row: dict, hist_rows: list[dict], now: datetime,
                       cfg_thresholds: dict, client_id: str, loc_info: dict) -> dict:
    """Build a complete sensor state dict from a latest-row + history."""
    mac = row["mac"]
    try:
        temp = float(row["body_temperature"])
    except (ValueError, TypeError):
        return {}

    last_seen = row["date_added"]
    age_sec = (now - last_seen.replace(tzinfo=timezone.utc)).total_seconds() if isinstance(last_seen, datetime) else 99999

    status = compute_sensor_status(
        age_sec, cfg_thresholds["degraded_sec"], cfg_thresholds["offline_sec"],
    )

    temps = []
    sensor_cutoff = row["date_added"] - timedelta(hours=1) if isinstance(row["date_added"], datetime) else None
    for hr in hist_rows:
        if sensor_cutoff and hr["date_added"] < sensor_cutoff:
            continue
        try:
            temps.append(float(hr["body_temperature"]))
        except (ValueError, TypeError):
            continue
    if not temps:
        temps = [temp]

    rolling = compute_rolling(temps)
    roc = compute_rate_of_change(temp, hist_rows, row["date_added"]) if isinstance(row["date_added"], datetime) else 0.0
    anomaly, reason = is_anomaly(temp, rolling["avg"], rolling["std"],
                                 cfg_thresholds["critical_high"], cfg_thresholds["critical_low"])

    try:
        rssi = float(row["rssi"])
    except (ValueError, TypeError):
        rssi = -99.0

    battery = 100
    if row.get("power") and str(row["power"]).strip():
        try:
            battery = max(0, min(100, int(float(row["power"]))))
        except (ValueError, TypeError):
            pass

    last_seen_str = last_seen.replace(tzinfo=timezone.utc).isoformat() if isinstance(last_seen, datetime) else str(last_seen)

    return {
        "device_id": mac, "temperature": round(temp, 2),
        "actual_high_1h": rolling["high"], "actual_low_1h": rolling["low"],
        "rolling_avg_1h": rolling["avg"], "rate_of_change": roc,
        "status": status, "last_seen": last_seen_str,
        "battery_pct": battery, "signal_dbm": rssi, "signal_label": signal_label(rssi),
        "anomaly": anomaly, "anomaly_reason": reason,
        "zone_id": loc_info.get("zone_id", "default"),
        "zone_label": loc_info.get("zone_label"),
        "facility_id": loc_info.get("facility_id", "default"),
        "client_id": client_id,
    }


# ── Forecasting ─────────────────────────────────────────────────────────────

def forecast_params(readings: list[dict]) -> dict | None:
    """Compute forecast model from recent readings. Returns params or None."""
    if len(readings) < 5:
        return None
    temps = [r["temperature"] for r in readings]
    n = len(temps)
    x = np.arange(n, dtype=float)
    y = np.array(temps, dtype=float)
    level = float(y[-1])
    trend = float(np.polyfit(x, y, 1)[0]) if n >= 2 else 0.0
    std = float(np.std(y, ddof=1)) if n > 1 else 0.5
    return {"level": round(level, 4), "trend": round(trend, 6), "residual_std": round(std, 4), "n_points": n}


def forecast_point(params: dict, horizon: str) -> dict:
    """Single-point forecast with confidence interval."""
    steps = 30 if horizon == "30min" else 120
    final = params["level"] + params["trend"] * steps
    ci = 1.96 * params["residual_std"] * (steps ** 0.5) * 0.1
    return {
        "predicted_temp": round(final, 2), "ci_lower": round(final - ci, 2),
        "ci_upper": round(final + ci, 2), "steps": steps, "model_params": params,
    }


def forecast_series(params: dict, ref_time: datetime, steps: int) -> list[dict]:
    """Time-series forecast from params."""
    lvl, trend, std = params["level"], params["trend"], params["residual_std"]
    return [
        {
            "step": h,
            "timestamp": (ref_time + timedelta(minutes=h)).strftime("%Y-%m-%dT%H:%M:00Z"),
            "predicted": round(lvl + trend * h, 2),
            "ci_lower": round(lvl + trend * h - 1.96 * std * (h ** 0.5) * 0.1, 2),
            "ci_upper": round(lvl + trend * h + 1.96 * std * (h ** 0.5) * 0.1, 2),
        }
        for h in range(1, steps + 1)
    ]
