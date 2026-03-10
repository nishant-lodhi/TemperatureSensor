"""Integration tests for the temperature sensor analytics pipeline.

Exercises the full pipeline end-to-end using moto for AWS mocking.
"""

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")

import boto3
from boto3.dynamodb.conditions import Key

from handlers import batch_handler, critical_handler, scheduled_handler
from storage import dynamodb_store


def _make_kinesis_records(events: list[dict]) -> list[dict]:
    """Encode events as base64 Kinesis records."""
    records = []
    for evt in events:
        payload = json.dumps(evt).encode("utf-8")
        records.append({
            "kinesis": {"data": base64.b64encode(payload).decode("ascii")},
        })
    return records


def test_batch_processing_end_to_end(aws_mock, seed_device):
    """Create 10 events, process through batch_handler, verify state and readings."""
    base_ts = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    events = []
    for i in range(10):
        ts = base_ts + timedelta(seconds=i * 5)
        events.append({
            "device_id": "C30000301A80",
            "temperature": 80.0 + (i % 3),  # 80, 81, 82, 80, 81, ...
            "rssi": -44,
            "power": 87,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "gateway_id": "AC233FC170F4",
        })

    kinesis_event = {"Records": _make_kinesis_records(events)}
    result = batch_handler.lambda_handler(kinesis_event, None)

    assert result["statusCode"] == 200
    assert result["processed"] == 10

    state = dynamodb_store.get_sensor_state("C30000301A80")
    assert state is not None
    assert "last_temp" in state
    assert state["last_temp"] in (80, 81, 82)
    assert "last_seen" in state
    assert state["status"] == "online"

    # Verify at least 1 minute aggregate stored (10 events over 50 sec → 1–2 minute buckets)
    from config import settings
    dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    table = dynamodb.Table(settings.SENSOR_DATA_TABLE)
    resp = table.query(
        KeyConditionExpression=Key("pk").eq("C30000301A80")
        & Key("sk").begins_with("R#"),
    )
    readings = resp.get("Items", [])
    assert len(readings) >= 1


def test_critical_alert_fires(aws_mock, seed_device):
    """Create event with temp 96.5 (above critical 95), verify alert stored."""
    event = {
        "device_id": "C30000301A80",
        "temperature": 96.5,
        "rssi": -44,
        "power": 87,
        "timestamp": "2024-10-01T12:00:00.000Z",
        "gateway_id": "AC233FC170F4",
    }

    result = critical_handler.lambda_handler(event, None)

    assert result["statusCode"] == 200
    assert result["alert"] is not None
    assert result["alert"]["severity"] == "CRITICAL"

    active = dynamodb_store.get_active_alerts("facility_A#zone_b")
    assert len(active) >= 1
    critical_alerts = [a for a in active if a.get("severity") == "CRITICAL"]
    assert len(critical_alerts) >= 1


def test_analytics_processing(aws_mock, seed_device):
    """Store 60 readings + STATE, run analytics mode, verify rolling metrics."""
    from config import settings

    now = datetime.now(timezone.utc)
    base_time = now - timedelta(minutes=60)

    # Store 60 readings, 1 per minute, temps 79–82°F
    for i in range(60):
        ts = base_time + timedelta(minutes=i)
        minute_key = ts.strftime("%Y-%m-%dT%H:%M:00Z")
        temp = 79.0 + (i % 4)  # 79, 80, 81, 82, 79, ...
        dynamodb_store.put_reading("C30000301A80", minute_key, {
            "temperature": temp,
            "temp_min": temp - 0.2,
            "temp_max": temp + 0.2,
            "reading_count": 1,
        })

    # Create STATE entry (required for get_all_sensor_states)
    dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    table = dynamodb.Table(settings.SENSOR_DATA_TABLE)
    table.put_item(
        Item={
            "pk": "C30000301A80",
            "sk": "STATE",
            "client_id": "client_1",
            "facility_id": "facility_A",
            "zone_id": "zone_b",
            "last_temp": Decimal("81.0"),
            "last_seen": now.isoformat(),
        }
    )

    result = scheduled_handler.lambda_handler({"mode": "analytics"}, None)

    assert result["statusCode"] == 200
    assert result["mode"] == "analytics"
    assert result["devices_processed"] >= 1

    state = dynamodb_store.get_sensor_state("C30000301A80")
    assert state is not None
    assert "rolling_avg_10m" in state or state.get("rolling_avg_10m") is not None
    assert "rolling_avg_1h" in state or state.get("rolling_avg_1h") is not None


def test_forecast_processing(aws_mock, seed_device):
    """Store 120 readings (2 hours) + STATE, run forecast mode, verify forecast stored."""
    from config import settings

    now = datetime.now(timezone.utc)
    base_time = now - timedelta(hours=2)

    # Store 120 readings, 1 per minute
    for i in range(120):
        ts = base_time + timedelta(minutes=i)
        minute_key = ts.strftime("%Y-%m-%dT%H:%M:00Z")
        temp = 79.0 + (i % 5) * 0.5  # 79–81.5 range
        dynamodb_store.put_reading("C30000301A80", minute_key, {
            "temperature": temp,
            "temp_min": temp - 0.2,
            "temp_max": temp + 0.2,
            "reading_count": 1,
        })

    # Create STATE entry
    dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    table = dynamodb.Table(settings.SENSOR_DATA_TABLE)
    table.put_item(
        Item={
            "pk": "C30000301A80",
            "sk": "STATE",
            "client_id": "client_1",
            "facility_id": "facility_A",
            "zone_id": "zone_b",
            "last_temp": Decimal("80.5"),
            "last_seen": now.isoformat(),
        }
    )

    result = scheduled_handler.lambda_handler({"mode": "forecast"}, None)

    assert result["statusCode"] == 200
    assert result["mode"] == "forecast"
    assert result["devices_processed"] >= 1

    forecast_30 = dynamodb_store.get_forecast("C30000301A80", "30min")
    forecast_2hr = dynamodb_store.get_forecast("C30000301A80", "2hr")
    assert forecast_30 is not None or forecast_2hr is not None


def test_full_pipeline_with_high_temp(aws_mock, seed_device):
    """Create 30 events at 87°F spanning 15 min, verify sustained high temp alert if applicable."""
    base_ts = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    events = []
    for i in range(30):
        ts = base_ts + timedelta(seconds=i * 30)  # 30 sec apart → 15 min span
        events.append({
            "device_id": "C30000301A80",
            "temperature": 87.0,
            "rssi": -44,
            "power": 87,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "gateway_id": "AC233FC170F4",
        })

    kinesis_event = {"Records": _make_kinesis_records(events)}
    result = batch_handler.lambda_handler(kinesis_event, None)

    assert result["statusCode"] == 200
    assert result["processed"] == 30

    # Sustained high (87 > 85 for 15 min) should trigger SUSTAINED_HIGH alert
    active = dynamodb_store.get_active_alerts("facility_A#zone_b")
    sustained = [a for a in active if "SUSTAINED" in str(a.get("alert_type", ""))]
    assert len(sustained) >= 1, "Expected sustained high temp alert for 87°F over 15 min"
