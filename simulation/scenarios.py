"""Predefined test scenarios for simulation. Each class has apply(readings) -> modified readings."""

import random
from datetime import datetime, timezone


def _parse_ts(ts_str: str) -> datetime | None:
    """Parse timestamp from reading['timestamp'][:19] using %Y-%m-%dT%H:%M:%S."""
    try:
        s = ts_str[:19] if isinstance(ts_str, str) else ""
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


class HVACFailure:
    """Add temperature rise proportional to time since start for matching zone devices."""

    def __init__(self, zone_id: str, start_hour: int, duration_hours: float = 2.0, rise_rate_per_hour: float = 2.0):
        self.zone_id = zone_id
        self.start_hour = start_hour
        self.duration_hours = duration_hours
        self.rise_rate_per_hour = rise_rate_per_hour

    def apply(self, readings: list[dict]) -> list[dict]:
        zone_prefix = f"TEMP_{self.zone_id.upper().replace('-', '_')}_"
        result = []
        for r in readings:
            if not r["device_id"].startswith(zone_prefix):
                result.append(r)
                continue
            ts = _parse_ts(r.get("timestamp", ""))
            if ts is None:
                result.append(r)
                continue
            hours_since_start = ts.hour + ts.minute / 60.0 - self.start_hour
            if 0 <= hours_since_start <= self.duration_hours:
                rise = hours_since_start * self.rise_rate_per_hour
                r = dict(r)
                r["temperature"] = round(r["temperature"] + rise, 4)
            result.append(r)
        return result


class SensorOffline:
    """Remove readings in the offline window for the given device."""

    def __init__(self, device_id: str, start_hour: int, duration_min: int = 30):
        self.device_id = device_id
        self.start_hour = start_hour
        self.duration_min = duration_min

    def apply(self, readings: list[dict]) -> list[dict]:
        return [
            r
            for r in readings
            if r["device_id"] != self.device_id
            or not _in_window(r.get("timestamp", ""), self.start_hour, self.duration_min)
        ]


def _in_window(ts_str: str, start_hour: int, duration_min: int) -> bool:
    ts = _parse_ts(ts_str)
    if ts is None:
        return False
    end_min = start_hour * 60 + duration_min
    start_min = start_hour * 60
    current_min = ts.hour * 60 + ts.minute
    return start_min <= current_min < end_min


class SensorTamper:
    """Add random temp offset and drop RSSI during the tamper window."""

    def __init__(self, device_id: str, start_hour: int, duration_min: int = 20):
        self.device_id = device_id
        self.start_hour = start_hour
        self.duration_min = duration_min

    def apply(self, readings: list[dict]) -> list[dict]:
        result = []
        for r in readings:
            if r["device_id"] != self.device_id:
                result.append(r)
                continue
            if not _in_window(r.get("timestamp", ""), self.start_hour, self.duration_min):
                result.append(r)
                continue
            r = dict(r)
            r["temperature"] = round(r["temperature"] + random.uniform(-5, 8), 4)
            rssi = r.get("rssi")
            if rssi is not None:
                r["rssi"] = int(rssi - random.uniform(15, 30))
                r["rssi"] = max(-100, r["rssi"])
            result.append(r)
        return result


class GradualRise:
    """Gradually blend temperature toward target over the specified hours."""

    def __init__(self, zone_id: str, start_hour: int, target_temp: float = 86.0, hours: float = 4.0):
        self.zone_id = zone_id
        self.start_hour = start_hour
        self.target_temp = target_temp
        self.hours = hours

    def apply(self, readings: list[dict]) -> list[dict]:
        zone_prefix = f"TEMP_{self.zone_id.upper().replace('-', '_')}_"
        result = []
        for r in readings:
            if not r["device_id"].startswith(zone_prefix):
                result.append(r)
                continue
            ts = _parse_ts(r.get("timestamp", ""))
            if ts is None:
                result.append(r)
                continue
            hours_since_start = ts.hour + ts.minute / 60.0 - self.start_hour
            if hours_since_start <= 0:
                result.append(r)
                continue
            if hours_since_start >= self.hours:
                r = dict(r)
                r["temperature"] = round(self.target_temp, 4)
                result.append(r)
                continue
            blend = hours_since_start / self.hours
            new_temp = r["temperature"] * (1 - blend) + self.target_temp * blend
            r = dict(r)
            r["temperature"] = round(new_temp, 4)
            result.append(r)
        return result
