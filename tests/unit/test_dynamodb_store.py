"""Unit tests for storage/dynamodb_store.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")

from decimal import Decimal


from storage.dynamodb_store import (
    get_active_alerts,
    get_all_sensor_states,
    get_forecast,
    get_readings,
    get_sensor_state,
    put_alert,
    put_forecast,
    put_reading,
    update_alert_status,
    update_sensor_state,
)


def _decimal_to_float(obj):
    """Recursively convert Decimal to float for assertions."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(v) for v in obj]
    return obj


def test_update_and_get_sensor_state(aws_mock):
    """update state, get it back, verify fields."""
    device_id = "dev1"
    state = {"temperature": 78.5, "humidity": 45.0, "last_seen": "2024-10-01T12:00:00Z"}
    update_sensor_state(device_id, state)
    result = get_sensor_state(device_id)
    assert result is not None
    result_f = _decimal_to_float(result)
    assert result_f.get("temperature") == 78.5
    assert result_f.get("humidity") == 45.0
    assert result.get("last_seen") == "2024-10-01T12:00:00Z"


def test_get_sensor_state_not_found(aws_mock):
    """unknown device → None."""
    result = get_sensor_state("unknown_device_xyz")
    assert result is None


def test_get_all_sensor_states(aws_mock):
    """insert 3 states, verify all returned."""
    for i, dev_id in enumerate(["dev1", "dev2", "dev3"]):
        update_sensor_state(dev_id, {"temperature": 70.0 + i, "last_seen": "2024-10-01T12:00:00Z"})
    result = get_all_sensor_states()
    assert len(result) == 3
    device_ids = {r["pk"] for r in result}
    assert device_ids == {"dev1", "dev2", "dev3"}


def test_put_and_get_reading(aws_mock):
    """store reading with TTL, query back."""
    device_id = "dev1"
    timestamp = "2024-10-01T12:00:00Z"
    reading = {"temperature": 82.5, "humidity": 50.0}
    put_reading(device_id, timestamp, reading)
    result = get_readings(device_id, "2024-10-01T11:00:00Z")
    assert len(result) >= 1
    found = next(r for r in result if r.get("sk") == f"R#{timestamp}")
    result_f = _decimal_to_float(found)
    assert result_f.get("temperature") == 82.5
    assert result_f.get("humidity") == 50.0


def test_get_readings_since(aws_mock):
    """store readings at different times, query since specific time."""
    device_id = "dev1"
    put_reading(device_id, "2024-10-01T12:00:00Z", {"temperature": 80.0})
    put_reading(device_id, "2024-10-01T12:05:00Z", {"temperature": 81.0})
    put_reading(device_id, "2024-10-01T12:10:00Z", {"temperature": 82.0})
    result = get_readings(device_id, "2024-10-01T12:06:00Z")
    timestamps = [r["sk"].replace("R#", "") for r in result]
    assert "2024-10-01T12:10:00Z" in timestamps
    assert "2024-10-01T12:05:00Z" not in timestamps


def test_put_and_get_forecast(aws_mock):
    """store forecast, retrieve by horizon."""
    device_id = "dev1"
    horizon = "forecast_30min"
    forecast = {"predicted_temp": 84.5, "confidence": 0.9}
    put_forecast(device_id, horizon, forecast)
    result = get_forecast(device_id, horizon)
    assert result is not None
    result_f = _decimal_to_float(result)
    assert result_f.get("predicted_temp") == 84.5
    assert result_f.get("confidence") == 0.9


def test_put_and_get_alert(aws_mock):
    """store alert, verify retrieval."""
    facility_zone = "facility_A/zone_b"
    alert = {
        "alert_type": "EXTREME_TEMPERATURE",
        "severity": "CRITICAL",
        "message": "Temp high",
        "triggered_at": "2024-10-01T12:00:00Z",
        "status": "ACTIVE",
    }
    put_alert(facility_zone, alert)
    active = get_active_alerts(facility_zone)
    assert len(active) >= 1
    found = next(a for a in active if a.get("alert_type") == "EXTREME_TEMPERATURE")
    assert found["severity"] == "CRITICAL"


def test_get_active_alerts(aws_mock):
    """store active and resolved, verify only active returned."""
    facility_zone = "facility_A/zone_b"
    put_alert(facility_zone, {
        "alert_type": "ALERT_A",
        "severity": "HIGH",
        "message": "Active",
        "triggered_at": "2024-10-01T12:00:00Z",
        "status": "ACTIVE",
    })
    put_alert(facility_zone, {
        "alert_type": "ALERT_B",
        "severity": "MEDIUM",
        "message": "Resolved",
        "triggered_at": "2024-10-01T12:01:00Z",
        "status": "RESOLVED",
    })
    active = get_active_alerts(facility_zone)
    assert len(active) == 1
    assert active[0]["alert_type"] == "ALERT_A"
    assert active[0]["status"] == "ACTIVE"


def test_update_alert_status(aws_mock):
    """update from ACTIVE to RESOLVED."""
    facility_zone = "facility_A/zone_b"
    triggered_at = "2024-10-01T12:00:00Z"
    alert_type = "EXTREME_TEMPERATURE"
    alert = {
        "alert_type": alert_type,
        "severity": "CRITICAL",
        "message": "Temp high",
        "triggered_at": triggered_at,
        "status": "ACTIVE",
    }
    put_alert(facility_zone, alert)
    sk = f"{triggered_at}#{alert_type}"
    update_alert_status(facility_zone, sk, "RESOLVED", acknowledged=True)
    active = get_active_alerts(facility_zone)
    assert not any(a.get("alert_type") == alert_type for a in active)
