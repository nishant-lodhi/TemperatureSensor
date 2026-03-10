"""Zone-level analytics: aggregation, outlier detection, condition classification."""

import numpy as np

from config import settings


def compute_zone_summary(device_states: list[dict]) -> dict:
    """Aggregate zone summary from sensor state dicts."""
    if not device_states:
        return {
            "sensor_count": 0,
            "online_count": 0,
            "offline_count": 0,
            "avg_temp": None,
            "min_temp": None,
            "max_temp": None,
            "std_temp": None,
            "avg_rate_of_change": None,
            "trend": "unknown",
        }

    online = [s for s in device_states if s.get("status") == "online"]
    offline_count = len(device_states) - len(online)

    temps = []
    rates = []
    for s in device_states:
        t = s.get("last_temp")
        if t is not None:
            temps.append(float(t))
        r = s.get("rate_of_change_10m")
        if r is not None:
            rates.append(float(r))

    avg_temp = float(np.mean(temps)) if temps else None
    min_temp = float(np.min(temps)) if temps else None
    max_temp = float(np.max(temps)) if temps else None
    std_temp = float(np.std(temps, ddof=1)) if len(temps) >= 2 else None
    avg_rate = float(np.mean(rates)) if rates else None

    if avg_rate is not None:
        if avg_rate > 0.3:
            trend = "rising"
        elif avg_rate < -0.3:
            trend = "falling"
        else:
            trend = "stable"
    else:
        trend = "unknown"

    return {
        "sensor_count": len(device_states),
        "online_count": len(online),
        "offline_count": offline_count,
        "avg_temp": avg_temp,
        "min_temp": min_temp,
        "max_temp": max_temp,
        "std_temp": std_temp,
        "avg_rate_of_change": avg_rate,
        "trend": trend,
    }


def detect_zone_outliers(
    device_states: list[dict],
    std_threshold: float = 2.0,
) -> list[dict]:
    """Find sensors deviating from zone mean by > std_threshold stds."""
    if len(device_states) < 3:
        return []

    temps = []
    for s in device_states:
        t = s.get("last_temp")
        if t is not None:
            temps.append((s.get("device_id", "unknown"), float(t)))

    if len(temps) < 3:
        return []

    temps_arr = np.array([t[1] for t in temps])
    zone_mean = float(np.mean(temps_arr))
    zone_std = float(np.std(temps_arr, ddof=1))
    if zone_std == 0:
        return []

    outliers = []
    for device_id, temp in temps:
        deviation_std = abs(temp - zone_mean) / zone_std
        if deviation_std > std_threshold:
            likely_cause = "sensor_fault" if deviation_std > 3 else "environmental"
            outliers.append({
                "device_id": device_id,
                "temperature": temp,
                "zone_mean": zone_mean,
                "deviation_std": round(deviation_std, 2),
                "likely_cause": likely_cause,
            })
    return outliers


def classify_zone_condition(zone_summary: dict, thresholds: dict) -> dict:
    """Classify zone status: normal, warning, alert, critical, unknown."""
    critical_high = thresholds.get("temp_critical_high", settings.TEMP_CRITICAL_HIGH)
    critical_low = thresholds.get("temp_critical_low", settings.TEMP_CRITICAL_LOW)
    high = thresholds.get("temp_high", settings.TEMP_HIGH)
    low = thresholds.get("temp_low", settings.TEMP_LOW)

    online = zone_summary.get("online_count", 0)
    total = zone_summary.get("sensor_count", 0)
    avg_temp = zone_summary.get("avg_temp")

    if total == 0:
        return {"status": "unknown", "reason": "no_sensors"}

    if online == 0:
        return {"status": "critical", "reason": "all_offline"}

    offline_ratio = (total - online) / total
    if offline_ratio > 0.3:
        return {"status": "critical", "reason": "high_offline_ratio"}

    if avg_temp is None:
        return {"status": "unknown", "reason": "no_temperature_data"}

    if avg_temp >= critical_high:
        return {"status": "critical", "reason": "temp_critical_high"}
    if avg_temp <= critical_low:
        return {"status": "critical", "reason": "temp_critical_low"}
    if avg_temp >= high:
        return {"status": "alert", "reason": "temp_high"}
    if avg_temp <= low:
        return {"status": "alert", "reason": "temp_low"}

    # Warning if within 3°F of threshold
    if avg_temp >= high - 3:
        return {"status": "warning", "reason": "approaching_temp_high"}
    if avg_temp <= low + 3:
        return {"status": "warning", "reason": "approaching_temp_low"}

    return {"status": "normal", "reason": "within_range"}
