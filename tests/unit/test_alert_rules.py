"""Unit tests for alerts/alert_rules.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")

from datetime import datetime, timedelta, timezone


from alerts.alert_rules import (
    check_anomaly,
    check_extreme_temperature,
    check_forecast_breach,
    check_rapid_change,
    check_sensor_offline,
    check_sustained_high,
)


def test_extreme_high():
    """temp 96 with threshold 95 → CRITICAL alert."""
    thresholds = {"temp_critical_high": 95, "temp_critical_low": 50}
    result = check_extreme_temperature(96.0, thresholds)
    assert result is not None
    assert result["severity"] == "CRITICAL"
    assert result["alert_type"] == "EXTREME_TEMPERATURE"
    assert result["temperature"] == 96.0
    assert result["threshold"] == 95
    assert result["direction"] == "high"


def test_extreme_low():
    """temp 49 with threshold 50 → CRITICAL alert."""
    thresholds = {"temp_critical_high": 95, "temp_critical_low": 50}
    result = check_extreme_temperature(49.0, thresholds)
    assert result is not None
    assert result["severity"] == "CRITICAL"
    assert result["alert_type"] == "EXTREME_TEMPERATURE"
    assert result["temperature"] == 49.0
    assert result["threshold"] == 50
    assert result["direction"] == "low"


def test_extreme_normal():
    """temp 80 → None."""
    thresholds = {"temp_critical_high": 95, "temp_critical_low": 50}
    result = check_extreme_temperature(80.0, thresholds)
    assert result is None


def test_sustained_high_triggered():
    """15 readings all above 85 spanning 12 min → alert with duration."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    readings = [
        {"temperature": 86.0, "timestamp": (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(15)
    ]
    thresholds = {"temp_high": 85, "sustained_duration_min": 10}
    result = check_sustained_high(readings, thresholds)
    assert result is not None
    assert result["alert_type"] == "SUSTAINED_HIGH_TEMPERATURE"
    assert result["severity"] == "HIGH"
    assert result["duration_min"] == 14.0
    assert result["avg_temp"] == 86.0
    assert result["peak_temp"] == 86.0


def test_sustained_high_not_enough_time():
    """all above but only 5 min → None."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    readings = [
        {"temperature": 86.0, "timestamp": (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(6)
    ]
    thresholds = {"temp_high": 85, "sustained_duration_min": 10}
    result = check_sustained_high(readings, thresholds)
    assert result is None


def test_sustained_high_mixed():
    """some below threshold → None."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    readings = [
        {"temperature": 86.0 if i < 10 else 82.0, "timestamp": (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(15)
    ]
    thresholds = {"temp_high": 85, "sustained_duration_min": 10}
    result = check_sustained_high(readings, thresholds)
    assert result is None


def test_rapid_change_rising():
    """rate 5.0 with threshold 4.0 → alert with direction "rising"."""
    thresholds = {"rapid_change_threshold_f": 4.0}
    result = check_rapid_change(5.0, thresholds)
    assert result is not None
    assert result["alert_type"] == "RAPID_TEMPERATURE_CHANGE"
    assert result["severity"] == "MEDIUM"
    assert result["rate_of_change"] == 5.0
    assert result["direction"] == "rising"


def test_rapid_change_falling():
    """rate -5.0 → alert with direction "falling"."""
    thresholds = {"rapid_change_threshold_f": 4.0}
    result = check_rapid_change(-5.0, thresholds)
    assert result is not None
    assert result["direction"] == "falling"
    assert result["rate_of_change"] == -5.0


def test_rapid_change_normal():
    """rate 2.0 → None."""
    thresholds = {"rapid_change_threshold_f": 4.0}
    result = check_rapid_change(2.0, thresholds)
    assert result is None


def test_rapid_change_none():
    """rate None → None."""
    thresholds = {"rapid_change_threshold_f": 4.0}
    result = check_rapid_change(None, thresholds)
    assert result is None


def test_sensor_offline_triggered():
    """last_seen 120s ago with threshold 60 → MEDIUM."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    last_seen = base.strftime("%Y-%m-%dT%H:%M:%SZ")
    current_time = base + timedelta(seconds=120)
    thresholds = {"sensor_offline_sec": 60}
    result = check_sensor_offline(last_seen, current_time, thresholds)
    assert result is not None
    assert result["severity"] == "MEDIUM"
    assert result["alert_type"] == "SENSOR_OFFLINE"
    assert result["gap_sec"] == 120


def test_sensor_offline_long():
    """600s → HIGH."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    last_seen = base.strftime("%Y-%m-%dT%H:%M:%SZ")
    current_time = base + timedelta(seconds=600)
    thresholds = {"sensor_offline_sec": 60}
    result = check_sensor_offline(last_seen, current_time, thresholds)
    assert result is not None
    assert result["severity"] == "HIGH"
    assert result["gap_sec"] == 600


def test_sensor_offline_very_long():
    """2000s → CRITICAL."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    last_seen = base.strftime("%Y-%m-%dT%H:%M:%SZ")
    current_time = base + timedelta(seconds=2000)
    thresholds = {"sensor_offline_sec": 60}
    result = check_sensor_offline(last_seen, current_time, thresholds)
    assert result is not None
    assert result["severity"] == "CRITICAL"
    assert result["gap_sec"] == 2000


def test_sensor_offline_ok():
    """30s → None."""
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    last_seen = base.strftime("%Y-%m-%dT%H:%M:%SZ")
    current_time = base + timedelta(seconds=30)
    thresholds = {"sensor_offline_sec": 60}
    result = check_sensor_offline(last_seen, current_time, thresholds)
    assert result is None


def test_anomaly_triggered():
    """anomaly_result with is_anomaly=True → MEDIUM."""
    anomaly_result = {"is_anomaly": True, "score": 3.5}
    result = check_anomaly(anomaly_result)
    assert result is not None
    assert result["severity"] == "MEDIUM"
    assert result["alert_type"] == "ANOMALY_DETECTED"
    assert result["anomaly_score"] == 3.5


def test_anomaly_normal():
    """is_anomaly=False → None."""
    anomaly_result = {"is_anomaly": False, "score": 1.2}
    result = check_anomaly(anomaly_result)
    assert result is None


def test_forecast_breach():
    """predicted_temp=87 with temp_high=85 → WARNING."""
    forecast = {"predicted_temp": 87}
    thresholds = {"temp_high": 85}
    result = check_forecast_breach(forecast, thresholds)
    assert result is not None
    assert result["severity"] == "WARNING"
    assert result["alert_type"] == "FORECAST_BREACH"
    assert result["predicted_temp"] == 87
    assert result["threshold"] == 85


def test_forecast_normal():
    """predicted_temp=82 → None."""
    forecast = {"predicted_temp": 82}
    thresholds = {"temp_high": 85}
    result = check_forecast_breach(forecast, thresholds)
    assert result is None
