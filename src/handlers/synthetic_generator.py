"""Synthetic Data Generator Lambda — generates fake sensor data for testing.

Triggered by EventBridge on a schedule (every 1 minute). Creates realistic
temperature sensor data and writes it to Kinesis in the same format as the
IoT Adapter output, so the downstream pipeline is identical.
"""

import hashlib
import json
import logging
import math
import os
import random
import time

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

STREAM_NAME = os.environ.get("SENSOR_DATA_STREAM", "")
SENSOR_COUNT = int(os.environ.get("SYNTHETIC_SENSOR_COUNT", "20"))
DEPLOYMENT_ID = os.environ.get("DEPLOYMENT_ID", "")
SYNTHETIC_CLIENT_ID = os.environ.get("SYNTHETIC_CLIENT_ID", DEPLOYMENT_ID or "synthetic")

kinesis = boto3.client("kinesis")

ZONES = ["Block-A", "Block-B", "Block-C", "Medical", "Admin", "Kitchen", "Yard"]
ANOMALY_PROBABILITY = 0.05
BASE_TEMP_F = 74.0
TEMP_RANGE_F = 8.0


def lambda_handler(event, context):
    """Generate synthetic sensor data and write to Kinesis."""
    now = time.time()
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    records = []

    for i in range(SENSOR_COUNT):
        sensor = _generate_sensor_reading(i, now, ts)
        records.append(sensor)

    _put_to_kinesis(records)
    logger.info("Generated %d synthetic sensor records", len(records))
    return {"statusCode": 200, "generated": len(records)}


def _generate_sensor_reading(index: int, epoch: float, ts: str) -> dict:
    """Create a single sensor reading with realistic values."""
    mac = _stable_mac(index)
    zone = ZONES[index % len(ZONES)]

    is_anomaly = random.random() < ANOMALY_PROBABILITY
    if is_anomaly:
        temp = random.choice([
            random.uniform(40.0, 50.0),
            random.uniform(95.0, 110.0),
        ])
    else:
        hour_angle = (epoch % 86400) / 86400.0 * 2 * math.pi
        diurnal = math.sin(hour_angle - math.pi / 3) * TEMP_RANGE_F / 2
        noise = random.gauss(0, 0.5)
        temp = BASE_TEMP_F + diurnal + noise

    rssi = random.randint(-80, -30)
    battery = max(10, min(100, 80 + random.randint(-30, 20)))

    signal_quality = "Strong"
    if rssi < -70:
        signal_quality = "Weak"
    elif rssi < -50:
        signal_quality = "Good"

    return {
        "device_id": mac,
        "client_id": SYNTHETIC_CLIENT_ID,
        "temperature": round(temp, 4),
        "rssi": rssi,
        "signal_dbm": rssi,
        "battery_pct": battery,
        "zone_id": zone,
        "timestamp": ts,
        "source": "synthetic",
        "signal_quality": signal_quality,
    }


def _stable_mac(index: int) -> str:
    """Generate a deterministic MAC-style device ID (no colons, uppercase)."""
    seed = f"synth-{DEPLOYMENT_ID}-{index}"
    h = hashlib.md5(seed.encode()).hexdigest()[:12].upper()
    return f"C3{h[:10]}"


def _put_to_kinesis(records: list[dict]):
    """Write records to Kinesis in batches of 500."""
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
