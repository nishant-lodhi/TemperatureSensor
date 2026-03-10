"""Synthetic data generator for temperature sensor simulation."""

from datetime import datetime, timedelta, timezone

import numpy as np


DEFAULT_PROFILE = {
    "temperature": {"mean": 80.0, "std": 2.0, "min": 75.0, "max": 90.0},
    "noise": {"mean_diff": 0.1, "std_diff": 0.2},
    "rssi": {"mean": -50.0, "std": 5.0},
    "interval_sec": {"mean": 5.0, "std": 1.0},
    "hourly_pattern": {},
    "total_readings": 0,
    "time_span_hours": 0.0,
}


def _get_hourly_adjustment(hour: int, profile: dict) -> float:
    """Return temperature adjustment for the given hour from hourly_pattern."""
    pattern = profile.get("hourly_pattern") or {}
    if not pattern:
        return 0.0
    base_mean = profile["temperature"]["mean"]
    hour_avg = pattern.get(hour)
    if hour_avg is None:
        return 0.0
    return float(hour_avg - base_mean)


def generate_reading(
    device_id: str,
    timestamp: datetime,
    base_temp: float,
    profile: dict | None = None,
    noise_scale: float = 1.0,
) -> dict:
    """Generate a single synthetic reading."""
    prof = profile or DEFAULT_PROFILE
    temp_params = prof["temperature"]
    rssi_params = prof["rssi"]
    noise_params = prof["noise"]

    noise = np.random.normal(0, noise_params["std_diff"] * noise_scale)
    temp = base_temp + noise
    temp = max(temp_params["min"], min(temp_params["max"], temp))
    temp = round(temp, 4)

    rssi_raw = np.random.normal(rssi_params["mean"], rssi_params["std"])
    rssi = int(np.clip(rssi_raw, -100, 0))

    ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return {
        "device_id": device_id,
        "temperature": temp,
        "rssi": rssi,
        "power": None,
        "timestamp": ts_str,
        "gateway_id": "GATEWAY_SIM",
    }


def generate_device_stream(
    device_id: str,
    start_time: datetime,
    hours: float,
    base_temp_offset: float = 0.0,
    profile: dict | None = None,
    interval_sec: float = 5,
) -> list[dict]:
    """Generate a stream of readings for one device with mean reversion toward daily pattern + noise."""
    prof = profile or DEFAULT_PROFILE
    base_mean = prof["temperature"]["mean"]
    base_temp = base_mean + base_temp_offset
    noise_std = prof["noise"]["std_diff"]
    mean_reversion = 0.3

    readings = []
    current = base_temp
    t = start_time
    end_time = start_time + timedelta(hours=hours)

    while t < end_time:
        hour = t.hour
        target = base_temp + _get_hourly_adjustment(hour, prof)
        current = current + mean_reversion * (target - current) + np.random.normal(0, noise_std)
        current = max(prof["temperature"]["min"], min(prof["temperature"]["max"], current))

        readings.append(generate_reading(device_id, t, current, prof, noise_scale=1.0))
        t += timedelta(seconds=interval_sec)

    return readings


def generate_facility(
    zone_config: dict,
    start_time: datetime,
    hours: float,
    profile: dict | None = None,
    interval_sec: float = 5,
    scenarios: list | None = None,
) -> list[dict]:
    """Generate readings for all zones. zone_config: {zone_id: {"count": N, "temp_offset": float}}."""
    all_readings = []
    for zone_id, cfg in zone_config.items():
        count = cfg.get("count", 1)
        temp_offset = cfg.get("temp_offset", 0.0)
        zone_upper = zone_id.upper().replace("-", "_")

        for i in range(1, count + 1):
            device_id = f"TEMP_{zone_upper}_{i:03d}"
            stream = generate_device_stream(
                device_id, start_time, hours, base_temp_offset=temp_offset, profile=profile, interval_sec=interval_sec
            )
            all_readings.extend(stream)

    if scenarios:
        for scenario in scenarios:
            all_readings = scenario.apply(all_readings)

    all_readings.sort(key=lambda r: r["timestamp"])
    return all_readings
