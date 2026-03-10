"""Analyze real CSV data to extract statistical profile for synthetic generation."""

import csv
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_CSV = DATA_DIR / "temp_sensor.csv"


def _load_csv(csv_path: Path | str | None = None) -> list[dict]:
    """Load CSV and return list of dicts with temperature (float), rssi (int|None), timestamp (datetime)."""
    path = Path(csv_path) if csv_path else DEFAULT_CSV
    if not path.exists():
        return []

    readings = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            temp_val = row.get("body_temperature", "").strip()
            rssi_val = row.get("rssi", "").strip()
            ts_val = row.get("timestamp", "").strip()

            temperature = None
            if temp_val:
                try:
                    temperature = float(temp_val)
                except ValueError:
                    pass

            rssi = None
            if rssi_val:
                try:
                    rssi = int(float(rssi_val))
                except ValueError:
                    pass

            timestamp = None
            if ts_val:
                try:
                    ts_clean = ts_val.replace("Z", "+00:00")
                    timestamp = datetime.fromisoformat(ts_clean)
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                except ValueError:
                    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                        try:
                            timestamp = datetime.strptime(ts_val[:19], fmt).replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue

            if temperature is not None and timestamp is not None:
                readings.append({"temperature": temperature, "rssi": rssi, "timestamp": timestamp})

    return readings


def _compute_hourly_pattern(readings: list[dict]) -> dict[int, float]:
    """Return dict mapping hour (0-23) to average temperature for that hour."""
    by_hour = {}
    for r in readings:
        hour = r["timestamp"].hour
        if hour not in by_hour:
            by_hour[hour] = []
        by_hour[hour].append(r["temperature"])

    return {h: float(np.mean(vals)) for h, vals in by_hour.items()}


def extract_profile(csv_path: Path | str | None = None) -> dict:
    """Extract statistical profile from CSV for synthetic generation.

    Returns dict with keys:
        temperature: mean, std, min, max
        noise: mean_diff, std_diff (from consecutive temp diffs)
        rssi: mean, std
        interval_sec: mean, std
        hourly_pattern: dict hour -> avg_temp
        total_readings: int
        time_span_hours: float
    """
    readings = _load_csv(csv_path)
    if not readings:
        return _empty_profile()

    temps = np.array([r["temperature"] for r in readings])
    rssi_vals = [r["rssi"] for r in readings if r["rssi"] is not None]
    timestamps = sorted([r["timestamp"] for r in readings])

    diffs = np.diff(temps) if len(temps) > 1 else np.array([0.0])
    intervals = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if 0 < delta < 3600:
            intervals.append(delta)

    time_span = (timestamps[-1] - timestamps[0]).total_seconds() / 3600.0 if len(timestamps) > 1 else 0.0

    profile = {
        "temperature": {
            "mean": float(np.mean(temps)),
            "std": float(np.std(temps)) if len(temps) > 1 else 0.5,
            "min": float(np.min(temps)),
            "max": float(np.max(temps)),
        },
        "noise": {
            "mean_diff": float(np.mean(np.abs(diffs))),
            "std_diff": float(np.std(diffs)) if len(diffs) > 1 else 0.2,
        },
        "rssi": {
            "mean": float(np.mean(rssi_vals)) if rssi_vals else -50.0,
            "std": float(np.std(rssi_vals)) if len(rssi_vals) > 1 else 5.0,
        },
        "interval_sec": {
            "mean": float(np.mean(intervals)) if intervals else 5.0,
            "std": float(np.std(intervals)) if len(intervals) > 1 else 1.0,
        },
        "hourly_pattern": _compute_hourly_pattern(readings),
        "total_readings": len(readings),
        "time_span_hours": time_span,
    }
    return profile


def _empty_profile() -> dict:
    """Return minimal profile when no CSV data available."""
    return {
        "temperature": {"mean": 80.0, "std": 2.0, "min": 75.0, "max": 90.0},
        "noise": {"mean_diff": 0.1, "std_diff": 0.2},
        "rssi": {"mean": -50.0, "std": 5.0},
        "interval_sec": {"mean": 5.0, "std": 1.0},
        "hourly_pattern": {},
        "total_readings": 0,
        "time_span_hours": 0.0,
    }
