"""Shared utility functions used across modules."""

from datetime import datetime, timezone

TIMESTAMP_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
]


def parse_timestamp(ts) -> datetime | None:
    """Parse a timestamp string to UTC-aware datetime.

    Supports ISO 8601 variants with/without fractional seconds,
    and 'YYYY-MM-DD HH:MM:SS' format from CSV exports.
    """
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not isinstance(ts, str):
        return None
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
