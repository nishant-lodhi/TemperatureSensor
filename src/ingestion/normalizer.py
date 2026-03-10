"""Normalize raw sensor data to the standard event schema.

Handles two input formats:
1. Raw CSV/gateway data (columns: mac, body_temperature, rssi, etc.)
2. IoT Core Lambda events (already in target format)

Target schema:
    device_id   : str
    temperature : float
    rssi        : int | None
    power       : int | None
    timestamp   : str (ISO 8601 with Z suffix)
    gateway_id  : str | None
"""

import logging
from datetime import datetime

from config.settings import CSV_COLUMN_MAP

logger = logging.getLogger(__name__)


def normalize_event(raw: dict) -> dict:
    """Normalize a raw event dict to the standard schema.

    Handles both CSV-style (mac, body_temperature) and
    Lambda-style (device_id, temperature) field names.
    """
    event = {}

    for raw_key, standard_key in CSV_COLUMN_MAP.items():
        if raw_key in raw and standard_key not in raw:
            event[standard_key] = raw[raw_key]

    for key in ("device_id", "temperature", "rssi", "power", "timestamp", "gateway_id",
                 "client_id", "battery_pct", "signal_dbm", "zone_id", "facility_id"):
        if key in raw:
            event[key] = raw[key]

    event["temperature"] = _to_float(event.get("temperature"))
    if "rssi" in event:
        event["rssi"] = _to_int(event.get("rssi"))
    event["power"] = (
        _to_int(event["power"]) if event.get("power") not in (None, "", '""') else None
    )
    if "battery_pct" in event:
        event["battery_pct"] = _to_int(event.get("battery_pct")) or 0
    if "signal_dbm" in event:
        event["signal_dbm"] = _to_int(event.get("signal_dbm")) or 0
    if "timestamp" in event:
        event["timestamp"] = _normalize_timestamp(event["timestamp"])

    return event


def normalize_csv_row(row: dict) -> dict:
    """Normalize a single CSV row (from csv.DictReader) to standard schema."""
    mapped = {}
    for csv_col, standard_key in CSV_COLUMN_MAP.items():
        value = row.get(csv_col, "")
        if value not in (None, "", '""'):
            mapped[standard_key] = value

    mapped["temperature"] = _to_float(mapped.get("temperature"))
    mapped["rssi"] = _to_int(mapped.get("rssi"))
    mapped["power"] = _to_int(mapped.get("power")) if mapped.get("power") else None
    mapped["timestamp"] = _normalize_timestamp(mapped.get("timestamp", ""))
    return mapped


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_timestamp(ts) -> str:
    """Ensure timestamp is ISO 8601 string with Z suffix."""
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if not isinstance(ts, str):
        return ""
    ts = ts.strip()
    if ts and "T" in ts and not ts.endswith("Z"):
        ts += "Z"
    return ts
