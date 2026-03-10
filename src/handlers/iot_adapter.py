"""IoT Adapter Lambda — decodes BLE rawData hex from IoT Core and writes to Kinesis.

Triggered by an IoT Rule on the gateway MQTT topic (e.g. /gw/+/lpsogateway1).
Receives raw BLE advertisement payloads, extracts temperature, RSSI, and battery,
then writes decoded records to the Kinesis data stream in the standard pipeline format.
"""

import json
import logging
import os
import time

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

STREAM_NAME = os.environ.get("SENSOR_DATA_STREAM", "")
DEPLOYMENT_ID = os.environ.get("DEPLOYMENT_ID", "")

kinesis = boto3.client("kinesis")


def lambda_handler(event, context):
    """Process IoT Core event containing one or more BLE sensor records."""
    records = event if isinstance(event, list) else [event]
    decoded = []

    for rec in records:
        try:
            result = _decode_ble_record(rec)
            if result:
                decoded.append(result)
        except Exception:
            logger.exception("Failed to decode record: %s", rec)

    if not decoded:
        logger.info("No valid sensor records in batch")
        return {"statusCode": 200, "decoded": 0}

    _put_to_kinesis(decoded)
    logger.info("Wrote %d decoded records to Kinesis", len(decoded))
    return {"statusCode": 200, "decoded": len(decoded)}


def _decode_ble_record(rec: dict) -> dict | None:
    """Decode a single BLE advertisement record from IoT Core.

    Expected fields: mac, rssi, rawData, timestamp, type, bleName.
    Returns None for gateway/non-sensor records.
    """
    rec_type = rec.get("type", "")
    if rec_type.lower() == "gateway":
        return None

    raw_data = rec.get("rawData", "")
    if not raw_data or len(raw_data) < 24:
        return None

    temp_f = _decode_temperature(raw_data)
    if temp_f is None:
        return None

    mac = rec.get("mac", "unknown")
    rssi = rec.get("rssi", 0)
    ts = rec.get("timestamp")
    if ts is None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return {
        "device_id": mac,
        "client_id": DEPLOYMENT_ID or "default",
        "temperature": round(temp_f, 4),
        "rssi": rssi,
        "signal_dbm": rssi,
        "battery_pct": _estimate_battery(raw_data),
        "timestamp": ts,
        "source": "iot_adapter",
    }


def _decode_temperature(raw_hex: str) -> float | None:
    """Extract temperature from BLE rawData hex string.

    Bytes 10-11 encode Celsius: byte[10] + byte[11]/256.
    Convert to Fahrenheit: C * 9/5 + 32.
    """
    try:
        raw_bytes = bytes.fromhex(raw_hex)
        if len(raw_bytes) < 12:
            return None
        temp_c = raw_bytes[10] + raw_bytes[11] / 256.0
        if temp_c < -40 or temp_c > 80:
            return None
        return temp_c * 9.0 / 5.0 + 32.0
    except (ValueError, IndexError):
        return None


def _estimate_battery(raw_hex: str) -> int:
    """Rough battery estimation from raw payload length/signal. Returns 0-100."""
    try:
        raw_bytes = bytes.fromhex(raw_hex)
        if len(raw_bytes) > 20:
            return min(100, max(0, raw_bytes[20]))
        return 50
    except (ValueError, IndexError):
        return 50


def _put_to_kinesis(records: list[dict]):
    """Write decoded records to Kinesis in batches of 500."""
    batch = []
    for rec in records:
        batch.append({
            "Data": json.dumps(rec).encode("utf-8"),
            "PartitionKey": rec.get("device_id", "unknown"),
        })
        if len(batch) >= 500:
            kinesis.put_records(StreamName=STREAM_NAME, Records=batch)
            batch = []

    if batch:
        kinesis.put_records(StreamName=STREAM_NAME, Records=batch)
