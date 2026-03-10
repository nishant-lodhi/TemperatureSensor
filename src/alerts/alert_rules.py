"""Alert rule definitions for temperature sensor analytics."""

from datetime import datetime, timezone

from utils import parse_timestamp

# Severity constants
CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
WARNING = "WARNING"
LOW = "LOW"

# Alert type constants
EXTREME_TEMP = "EXTREME_TEMPERATURE"
SUSTAINED_HIGH = "SUSTAINED_HIGH_TEMPERATURE"
RAPID_CHANGE = "RAPID_TEMPERATURE_CHANGE"
SENSOR_OFFLINE = "SENSOR_OFFLINE"
ANOMALY = "ANOMALY_DETECTED"
FORECAST_BREACH = "FORECAST_BREACH"


def _alert(alert_type: str, severity: str, message: str, **extra) -> dict:
    """Build alert dict with standard fields."""
    d = {
        "alert_type": alert_type,
        "severity": severity,
        "message": message,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "status": "ACTIVE",
        **extra,
    }
    return d


def check_extreme_temperature(temperature: float, thresholds: dict) -> dict | None:
    """Return alert if temp exceeds critical high or low."""
    high = thresholds.get("temp_critical_high")
    low = thresholds.get("temp_critical_low")
    if high is not None and temperature > high:
        return _alert(
            EXTREME_TEMP, CRITICAL,
            f"Temperature {temperature:.1f}°F exceeds critical high {high}°F",
            temperature=temperature, threshold=high, direction="high",
        )
    if low is not None and temperature < low:
        return _alert(
            EXTREME_TEMP, CRITICAL,
            f"Temperature {temperature:.1f}°F below critical low {low}°F",
            temperature=temperature, threshold=low, direction="low",
        )
    return None


def check_sustained_high(readings: list[dict], thresholds: dict) -> dict | None:
    """Check if all readings exceed temp_high for sustained_duration_min."""
    if not readings:
        return None
    temp_high = thresholds.get("temp_high")
    duration_min = thresholds.get("sustained_duration_min", 10)
    if temp_high is None:
        return None

    temps = [float(r["temperature"]) for r in readings if "temperature" in r]
    if not temps:
        return None
    if not all(t > temp_high for t in temps):
        return None

    first_ts = parse_timestamp(readings[0].get("timestamp"))
    last_ts = parse_timestamp(readings[-1].get("timestamp"))
    if first_ts is None or last_ts is None:
        return None
    span_min = (last_ts - first_ts).total_seconds() / 60
    if span_min < duration_min:
        return None

    avg_temp = sum(temps) / len(temps)
    peak_temp = max(temps)
    return _alert(
        SUSTAINED_HIGH, HIGH,
        f"Sustained high temperature {avg_temp:.1f}°F for {span_min:.0f} min (peak {peak_temp:.1f}°F)",
        avg_temp=avg_temp, peak_temp=peak_temp, duration_min=round(span_min, 1),
    )


def check_rapid_change(rate_of_change: float | None, thresholds: dict) -> dict | None:
    """Return alert if rate of change exceeds threshold."""
    if rate_of_change is None:
        return None
    thresh = thresholds.get("rapid_change_threshold_f")
    if thresh is None:
        return None
    if abs(rate_of_change) <= thresh:
        return None
    direction = "rising" if rate_of_change > 0 else "falling"
    return _alert(
        RAPID_CHANGE, MEDIUM,
        f"Rapid temperature change ({direction}): {rate_of_change:.1f}°F/min",
        rate_of_change=rate_of_change, direction=direction,
    )


def check_sensor_offline(last_seen_iso: str | None, current_time, thresholds: dict) -> dict | None:
    """Return alert if sensor offline gap exceeds threshold."""
    if last_seen_iso is None:
        return _alert(SENSOR_OFFLINE, CRITICAL, "Sensor has no last_seen timestamp")
    last_seen = parse_timestamp(last_seen_iso)
    if last_seen is None:
        return None
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    gap_sec = (now - last_seen).total_seconds()
    offline_sec = thresholds.get("sensor_offline_sec", 60)
    if gap_sec <= offline_sec:
        return None

    if gap_sec > 1800:
        severity = CRITICAL
    elif gap_sec > 300:
        severity = HIGH
    else:
        severity = MEDIUM

    return _alert(
        SENSOR_OFFLINE, severity,
        f"Sensor offline for {gap_sec:.0f}s (threshold {offline_sec}s)",
        gap_sec=round(gap_sec, 0), last_seen=last_seen_iso,
    )


def check_anomaly(anomaly_result: dict) -> dict | None:
    """Return MEDIUM alert if anomaly detected."""
    if not anomaly_result.get("is_anomaly"):
        return None
    return _alert(
        ANOMALY, MEDIUM,
        "Anomaly detected in temperature readings",
        anomaly_score=anomaly_result.get("score"),
    )


def check_forecast_breach(forecast: dict, thresholds: dict) -> dict | None:
    """Return WARNING if predicted temp exceeds temp_high."""
    pred = forecast.get("predicted_temp")
    temp_high = thresholds.get("temp_high")
    if pred is None or temp_high is None:
        return None
    if pred <= temp_high:
        return None
    return _alert(
        FORECAST_BREACH, WARNING,
        f"Forecast breach: predicted {pred:.1f}°F exceeds {temp_high}°F",
        predicted_temp=pred, threshold=temp_high,
    )
