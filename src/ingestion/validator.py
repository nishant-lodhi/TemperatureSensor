"""Validate incoming sensor events.

Rejects events that:
- Miss required fields (device_id, temperature, timestamp)
- Have temperature outside physical range (-40°F to 150°F)
- Have unparseable or future timestamps
- Have invalid device_id format
"""

import logging
import re
from datetime import datetime, timezone

from config import settings
from utils import parse_timestamp

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {"device_id", "temperature", "timestamp"}
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,30}$")


def validate_event(event: dict) -> tuple[bool, str]:
    """Validate a sensor event.

    Returns:
        (is_valid, error_message) — error_message is empty string when valid.
    """
    missing = REQUIRED_FIELDS - set(event.keys())
    if missing:
        return False, f"Missing required fields: {missing}"

    device_id = str(event.get("device_id", ""))
    if not DEVICE_ID_PATTERN.match(device_id):
        return False, f"Invalid device_id format: {device_id}"

    temp = event.get("temperature")
    if not isinstance(temp, (int, float)):
        return False, f"Temperature must be a number, got: {type(temp).__name__}"
    if temp < settings.TEMP_VALID_MIN or temp > settings.TEMP_VALID_MAX:
        return False, (
            f"Temperature {temp}°F outside valid range "
            f"[{settings.TEMP_VALID_MIN}, {settings.TEMP_VALID_MAX}]"
        )

    ts = event.get("timestamp")
    parsed_ts = parse_timestamp(ts)
    if parsed_ts is None:
        return False, f"Unparseable timestamp: {ts}"
    if parsed_ts > datetime.now(timezone.utc):
        return False, f"Timestamp in the future: {ts}"

    rssi = event.get("rssi")
    if rssi is not None and not isinstance(rssi, (int, float)):
        return False, f"RSSI must be a number, got: {type(rssi).__name__}"

    return True, ""
