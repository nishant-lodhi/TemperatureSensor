"""Rolling metrics for sensor time series data."""

from datetime import timedelta

import numpy as np

from config import settings
from utils import parse_timestamp


def _cutoff_time(readings: list[dict], window_minutes: int):
    """Return cutoff datetime based on latest reading's timestamp minus window."""
    if not readings:
        return None
    latest_ts = readings[-1].get("timestamp")
    latest_dt = parse_timestamp(latest_ts)
    if latest_dt is None:
        return None
    return latest_dt - timedelta(minutes=window_minutes)


def _count_in_window(readings: list[dict], window_minutes: int) -> int:
    """Count readings within the rolling window."""
    cutoff = _cutoff_time(readings, window_minutes)
    if cutoff is None:
        return 0
    count = 0
    for r in readings:
        dt = parse_timestamp(r.get("timestamp"))
        if dt is not None and dt >= cutoff:
            count += 1
    return count


def compute_rolling_average(readings: list[dict], window_minutes: int) -> float | None:
    """Compute average temperature in the rolling window."""
    cutoff = _cutoff_time(readings, window_minutes)
    if cutoff is None:
        return None
    temps = []
    for r in readings:
        dt = parse_timestamp(r.get("timestamp"))
        if dt is not None and dt >= cutoff and "temperature" in r:
            temps.append(float(r["temperature"]))
    if not temps:
        return None
    return float(np.mean(temps))


def compute_rolling_std(readings: list[dict], window_minutes: int) -> float | None:
    """Compute standard deviation in the rolling window (ddof=1)."""
    cutoff = _cutoff_time(readings, window_minutes)
    if cutoff is None:
        return None
    temps = []
    for r in readings:
        dt = parse_timestamp(r.get("timestamp"))
        if dt is not None and dt >= cutoff and "temperature" in r:
            temps.append(float(r["temperature"]))
    if len(temps) < 2:
        return None
    return float(np.std(temps, ddof=1))


def compute_rate_of_change(readings: list[dict], lookback_minutes: int) -> float | None:
    """Temperature diff between latest and reading from lookback_minutes ago."""
    if not readings:
        return None
    cutoff = _cutoff_time(readings, lookback_minutes)
    if cutoff is None:
        return None
    latest = readings[-1]
    latest_temp = latest.get("temperature")
    if latest_temp is None:
        return None
    latest_temp = float(latest_temp)
    # Find reading at or just after cutoff
    for r in readings:
        dt = parse_timestamp(r.get("timestamp"))
        if dt is not None and dt >= cutoff and "temperature" in r:
            past_temp = float(r["temperature"])
            return latest_temp - past_temp
    return None


def compute_min_max(readings: list[dict], window_minutes: int) -> dict | None:
    """Return min and max temperature in the rolling window."""
    cutoff = _cutoff_time(readings, window_minutes)
    if cutoff is None:
        return None
    temps = []
    for r in readings:
        dt = parse_timestamp(r.get("timestamp"))
        if dt is not None and dt >= cutoff and "temperature" in r:
            temps.append(float(r["temperature"]))
    if not temps:
        return None
    return {"min": float(np.min(temps)), "max": float(np.max(temps))}


def compute_all_metrics(readings: list[dict]) -> dict:
    """Compute all rolling metrics using config window settings."""
    w10 = settings.ROLLING_WINDOW_10M_MIN
    w60 = settings.ROLLING_WINDOW_1H_MIN
    rapid = settings.RAPID_CHANGE_WINDOW_MIN

    result = {
        "rolling_avg_10m": compute_rolling_average(readings, w10),
        "rolling_avg_1h": compute_rolling_average(readings, w60),
        "rolling_std_10m": compute_rolling_std(readings, w10),
        "rolling_std_1h": compute_rolling_std(readings, w60),
        "rate_of_change_10m": compute_rate_of_change(readings, rapid),
        "min_max_10m": compute_min_max(readings, w10),
        "min_max_1h": compute_min_max(readings, w60),
        "reading_count_1h": _count_in_window(readings, w60),
    }
    return result
