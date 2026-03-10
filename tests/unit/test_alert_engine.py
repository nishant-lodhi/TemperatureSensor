"""Unit tests for alerts/alert_engine.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")

from datetime import datetime, timedelta, timezone


from alerts.alert_engine import (
    aggregate_zone_alerts,
    check_auto_resolve,
    check_escalation,
    evaluate_analytics_alerts,
    evaluate_critical,
    evaluate_thresholds,
    should_fire,
)


def test_evaluate_critical_high():
    """temp 96 → alert dict."""
    event = {"temperature": 96, "device_id": "dev1"}
    result = evaluate_critical(event)
    assert result is not None
    assert result["severity"] == "CRITICAL"
    assert result["alert_type"] == "EXTREME_TEMPERATURE"
    assert result["temperature"] == 96


def test_evaluate_critical_normal():
    """temp 80 → None."""
    event = {"temperature": 80, "device_id": "dev1"}
    result = evaluate_critical(event)
    assert result is None


def test_evaluate_thresholds_sustained():
    """device with sustained high readings → alerts."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    readings = [
        {"temperature": 86.0, "timestamp": (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(15)
    ]
    sensor_state = {"rate_of_change_f_per_min": None}
    thresholds = {"temp_high": 85, "sustained_duration_min": 10}
    result = evaluate_thresholds("dev1", sensor_state, readings, thresholds)
    assert len(result) >= 1
    assert any(a["alert_type"] == "SUSTAINED_HIGH_TEMPERATURE" for a in result)


def test_evaluate_thresholds_normal():
    """normal readings → empty list."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    readings = [
        {"temperature": 78.0, "timestamp": (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(15)
    ]
    sensor_state = {"rate_of_change_f_per_min": 1.0}
    thresholds = {"temp_high": 85, "sustained_duration_min": 10, "rapid_change_threshold_f": 4.0}
    result = evaluate_thresholds("dev1", sensor_state, readings, thresholds)
    assert result == []


def test_aggregate_single_device():
    """1 alert → adds zone/facility info."""
    device_alerts = [
        {
            "alert_type": "EXTREME_TEMPERATURE",
            "severity": "CRITICAL",
            "message": "Temp high",
            "triggered_at": "2024-10-01T12:00:00Z",
            "status": "ACTIVE",
            "device_id": "dev1",
        }
    ]
    result = aggregate_zone_alerts(device_alerts, "zone_b", "facility_A")
    assert len(result) == 1
    assert result[0]["zone_id"] == "zone_b"
    assert result[0]["facility_id"] == "facility_A"
    assert result[0]["facility_zone"] == "facility_A/zone_b"


def test_aggregate_multiple_devices():
    """3 alerts same type → merged with affected_devices."""
    device_alerts = [
        {
            "alert_type": "SUSTAINED_HIGH_TEMPERATURE",
            "severity": "HIGH",
            "message": "High temp",
            "triggered_at": "2024-10-01T12:00:00Z",
            "status": "ACTIVE",
            "device_id": "dev1",
        },
        {
            "alert_type": "SUSTAINED_HIGH_TEMPERATURE",
            "severity": "HIGH",
            "message": "High temp",
            "triggered_at": "2024-10-01T12:00:00Z",
            "status": "ACTIVE",
            "device_id": "dev2",
        },
        {
            "alert_type": "SUSTAINED_HIGH_TEMPERATURE",
            "severity": "HIGH",
            "message": "High temp",
            "triggered_at": "2024-10-01T12:00:00Z",
            "status": "ACTIVE",
            "device_id": "dev3",
        },
    ]
    result = aggregate_zone_alerts(device_alerts, "zone_b", "facility_A")
    assert len(result) == 1
    assert result[0]["device_count"] == 3
    assert set(result[0]["affected_devices"]) == {"dev1", "dev2", "dev3"}


def test_aggregate_different_types():
    """2 different alert types → 2 separate alerts."""
    device_alerts = [
        {
            "alert_type": "EXTREME_TEMPERATURE",
            "severity": "CRITICAL",
            "message": "Temp high",
            "triggered_at": "2024-10-01T12:00:00Z",
            "status": "ACTIVE",
            "device_id": "dev1",
        },
        {
            "alert_type": "SENSOR_OFFLINE",
            "severity": "MEDIUM",
            "message": "Sensor offline",
            "triggered_at": "2024-10-01T12:00:00Z",
            "status": "ACTIVE",
            "device_id": "dev2",
        },
    ]
    result = aggregate_zone_alerts(device_alerts, "zone_b", "facility_A")
    assert len(result) == 2
    types = {a["alert_type"] for a in result}
    assert types == {"EXTREME_TEMPERATURE", "SENSOR_OFFLINE"}


def test_should_fire_new():
    """no active alerts → True."""
    new_alert = {"alert_type": "EXTREME_TEMPERATURE", "device_id": "dev1"}
    active_alerts = []
    assert should_fire(new_alert, active_alerts) is True


def test_should_fire_duplicate():
    """same type+device active → False."""
    new_alert = {"alert_type": "EXTREME_TEMPERATURE", "device_id": "dev1"}
    active_alerts = [
        {"alert_type": "EXTREME_TEMPERATURE", "device_id": "dev1", "status": "ACTIVE"}
    ]
    assert should_fire(new_alert, active_alerts) is False


def test_should_fire_zone_covered():
    """zone-level alert active → False."""
    new_alert = {"alert_type": "SUSTAINED_HIGH_TEMPERATURE", "device_id": "dev1", "zone_id": "zone_b"}
    active_alerts = [
        {
            "alert_type": "SUSTAINED_HIGH_TEMPERATURE",
            "zone_id": "zone_b",
            "device_count": 3,
            "status": "ACTIVE",
        }
    ]
    assert should_fire(new_alert, active_alerts) is False


def test_check_escalation_not_due():
    """recent alert → None."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    alert = {"triggered_at": base.strftime("%Y-%m-%dT%H:%M:%SZ"), "acknowledged": False}
    current_time = base + timedelta(seconds=120)
    result = check_escalation(alert, current_time)
    assert result is None


def test_check_escalation_supervisor():
    """6 min old → "supervisor"."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    alert = {"triggered_at": base.strftime("%Y-%m-%dT%H:%M:%SZ"), "acknowledged": False}
    current_time = base + timedelta(seconds=360)
    result = check_escalation(alert, current_time)
    assert result == "supervisor"


def test_check_escalation_manager():
    """16 min old → "facility_manager"."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    alert = {"triggered_at": base.strftime("%Y-%m-%dT%H:%M:%SZ"), "acknowledged": False}
    current_time = base + timedelta(seconds=960)
    result = check_escalation(alert, current_time)
    assert result == "facility_manager"


def test_check_escalation_acknowledged():
    """acknowledged alert → None."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    alert = {"triggered_at": base.strftime("%Y-%m-%dT%H:%M:%SZ"), "acknowledged": True}
    current_time = base + timedelta(seconds=1200)
    result = check_escalation(alert, current_time)
    assert result is None


def test_auto_resolve_sustained():
    """rolling_avg below threshold-hysteresis → True."""
    alert = {"alert_type": "SUSTAINED_HIGH_TEMPERATURE"}
    sensor_state = {"rolling_avg_10m": 82.0}
    thresholds = {"temp_high": 85}
    result = check_auto_resolve(alert, sensor_state, thresholds)
    assert result is True


def test_auto_resolve_not_yet():
    """still high → False."""
    alert = {"alert_type": "SUSTAINED_HIGH_TEMPERATURE"}
    sensor_state = {"rolling_avg_10m": 86.0}
    thresholds = {"temp_high": 85}
    result = check_auto_resolve(alert, sensor_state, thresholds)
    assert result is False


# ── Feature flag tests ────────────────────────────────────


ALL_ENABLED = {
    "alerts_enabled": True,
    "alert_extreme_temp": True,
    "alert_sustained_high": True,
    "alert_rapid_change": True,
    "alert_sensor_offline": True,
    "alert_anomaly": True,
    "alert_forecast_breach": True,
}

ALL_DISABLED = {k: False for k in ALL_ENABLED}


def test_evaluate_critical_disabled_by_master_flag():
    """Master flag off → None even for extreme temp."""
    event = {"temperature": 96, "device_id": "dev1"}
    result = evaluate_critical(event, features={"alerts_enabled": False, "alert_extreme_temp": True})
    assert result is None


def test_evaluate_critical_disabled_by_type_flag():
    """Specific type flag off → None."""
    event = {"temperature": 96, "device_id": "dev1"}
    result = evaluate_critical(event, features={"alerts_enabled": True, "alert_extreme_temp": False})
    assert result is None


def test_evaluate_critical_enabled_by_flags():
    """Flags on → alert fires normally."""
    event = {"temperature": 96, "device_id": "dev1"}
    result = evaluate_critical(event, features=ALL_ENABLED)
    assert result is not None
    assert result["severity"] == "CRITICAL"


def test_evaluate_thresholds_disabled_by_master():
    """Master flag off → empty list."""
    from datetime import datetime, timedelta, timezone
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    readings = [
        {"temperature": 86.0, "timestamp": (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(15)
    ]
    sensor_state = {"rate_of_change_f_per_min": 5.0}
    thresholds = {"temp_high": 85, "sustained_duration_min": 10, "rapid_change_threshold_f": 4.0}
    result = evaluate_thresholds("dev1", sensor_state, readings, thresholds, features=ALL_DISABLED)
    assert result == []


def test_evaluate_thresholds_selective_disable():
    """Sustained disabled, rapid enabled → only rapid change alert."""
    from datetime import datetime, timedelta, timezone
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    readings = [
        {"temperature": 86.0, "timestamp": (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(15)
    ]
    sensor_state = {"rate_of_change_f_per_min": 5.0}
    thresholds = {"temp_high": 85, "sustained_duration_min": 10, "rapid_change_threshold_f": 4.0}
    features = {**ALL_ENABLED, "alert_sustained_high": False}
    result = evaluate_thresholds("dev1", sensor_state, readings, thresholds, features=features)
    types = {a["alert_type"] for a in result}
    assert "SUSTAINED_HIGH_TEMPERATURE" not in types
    assert "RAPID_TEMPERATURE_CHANGE" in types


def test_evaluate_analytics_alerts_disabled():
    """All alerts disabled → empty list."""
    from datetime import datetime, timezone
    now = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    sensor_state = {"last_seen": "2024-10-01T11:00:00Z"}
    anomaly_result = {"is_anomaly": True, "score": 4.5}
    forecast = {"forecast_30min": {"predicted_temp": 96.0}}
    thresholds = {"temp_high": 85, "sensor_offline_sec": 60}
    result = evaluate_analytics_alerts(
        "dev1", sensor_state, anomaly_result, forecast, thresholds, now, features=ALL_DISABLED,
    )
    assert result == []


def test_evaluate_analytics_alerts_selective():
    """Offline disabled, anomaly enabled → only anomaly alert."""
    from datetime import datetime, timezone
    now = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    sensor_state = {"last_seen": "2024-10-01T11:00:00Z"}
    anomaly_result = {"is_anomaly": True, "score": 4.5}
    features = {**ALL_ENABLED, "alert_sensor_offline": False, "alert_forecast_breach": False}
    thresholds = {"temp_high": 85, "sensor_offline_sec": 60}
    result = evaluate_analytics_alerts(
        "dev1", sensor_state, anomaly_result, None, thresholds, now, features=features,
    )
    types = {a["alert_type"] for a in result}
    assert "SENSOR_OFFLINE" not in types
    assert "ANOMALY_DETECTED" in types
