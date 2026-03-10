"""Unit tests for handlers/scheduled_handler.py — scheduled analytics pipeline."""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")

import boto3

from handlers.scheduled_handler import (
    _handle_analytics,
    _handle_compliance,
    _handle_forecast,
    _handle_shift,
    _to_reading_dicts,
    lambda_handler,
)
from storage import dynamodb_store


def _seed_readings(device_id, count, aws_mock):
    """Insert `count` minute-level readings for the device."""
    now = datetime.now(timezone.utc)
    for i in range(count):
        ts = now - timedelta(minutes=count - i)
        minute_key = ts.strftime("%Y-%m-%dT%H:%M:00Z")
        temp = 79.0 + (i % 4)
        dynamodb_store.put_reading(device_id, minute_key, {
            "temperature": temp,
            "temp_min": temp - 0.2,
            "temp_max": temp + 0.2,
            "reading_count": 1,
        })


def _seed_state(device_id, aws_mock):
    """Insert a STATE entry for the device."""
    from config import settings
    dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    table = dynamodb.Table(settings.SENSOR_DATA_TABLE)
    table.put_item(Item={
        "pk": device_id,
        "sk": "STATE",
        "client_id": "client_1",
        "facility_id": "facility_A",
        "zone_id": "zone_b",
        "last_temp": Decimal("80.5"),
        "last_seen": datetime.now(timezone.utc).isoformat(),
    })


# ── Mode routing ──────────────────────────────────────────


class TestModeRouting:
    def test_unknown_mode_returns_400(self, aws_mock):
        result = lambda_handler({"mode": "nonexistent"}, None)
        assert result["statusCode"] == 400
        assert "Unknown mode" in result.get("error", "")

    def test_analytics_mode(self, aws_mock):
        result = lambda_handler({"mode": "analytics"}, None)
        assert result["statusCode"] == 200
        assert result["mode"] == "analytics"

    def test_forecast_mode(self, aws_mock):
        result = lambda_handler({"mode": "forecast"}, None)
        assert result["statusCode"] == 200
        assert result["mode"] == "forecast"

    def test_compliance_mode(self, aws_mock):
        result = lambda_handler({"mode": "compliance"}, None)
        assert result["statusCode"] == 200
        assert result["mode"] == "compliance"

    def test_shift_mode_placeholder(self, aws_mock):
        result = lambda_handler({"mode": "shift"}, None)
        assert result["statusCode"] == 200
        assert result["mode"] == "shift"
        assert result.get("status") == "placeholder"

    def test_default_mode_is_analytics(self, aws_mock):
        result = lambda_handler({}, None)
        assert result["mode"] == "analytics"


# ── Analytics handler ─────────────────────────────────────


class TestAnalyticsHandler:
    def test_processes_device_with_readings(self, seed_device, aws_mock):
        _seed_state("C30000301A80", aws_mock)
        _seed_readings("C30000301A80", 60, aws_mock)
        result = _handle_analytics({})
        assert result["statusCode"] == 200
        assert result["devices_processed"] >= 1

    def test_updates_rolling_metrics(self, seed_device, aws_mock):
        _seed_state("C30000301A80", aws_mock)
        _seed_readings("C30000301A80", 60, aws_mock)
        _handle_analytics({})
        state = dynamodb_store.get_sensor_state("C30000301A80")
        assert state.get("rolling_avg_1h") is not None or state.get("rolling_avg_10m") is not None

    @patch("handlers.scheduled_handler.settings.FEATURE_ANALYTICS_ENABLED", False)
    def test_disabled_by_feature_flag(self, aws_mock):
        result = _handle_analytics({})
        assert result["statusCode"] == 200
        assert result.get("skipped") is True

    def test_no_devices_returns_zero(self, aws_mock):
        result = _handle_analytics({})
        assert result["devices_processed"] == 0


# ── Forecast handler ──────────────────────────────────────


class TestForecastHandler:
    def test_processes_device_with_readings(self, seed_device, aws_mock):
        _seed_state("C30000301A80", aws_mock)
        _seed_readings("C30000301A80", 120, aws_mock)
        result = _handle_forecast({})
        assert result["statusCode"] == 200
        assert result["devices_processed"] >= 1

    @patch("handlers.scheduled_handler.settings.FEATURE_FORECASTING_ENABLED", False)
    def test_disabled_by_feature_flag(self, aws_mock):
        result = _handle_forecast({})
        assert result["statusCode"] == 200
        assert result.get("skipped") is True


# ── Compliance handler ────────────────────────────────────


class TestComplianceHandler:
    @patch("handlers.scheduled_handler.settings.FEATURE_COMPLIANCE_ENABLED", False)
    def test_disabled_by_feature_flag(self, aws_mock):
        result = _handle_compliance({})
        assert result["statusCode"] == 200
        assert result.get("skipped") is True


# ── Shift handler ─────────────────────────────────────────


class TestShiftHandler:
    def test_returns_placeholder(self, aws_mock):
        result = _handle_shift({})
        assert result["statusCode"] == 200
        assert result["status"] == "placeholder"


# ── _to_reading_dicts ─────────────────────────────────────


class TestToReadingDicts:
    def test_converts_dynamodb_items(self):
        items = [
            {"pk": "dev1", "sk": "R#2024-10-01T12:00:00Z", "temperature": Decimal("80.5")},
            {"pk": "dev1", "sk": "R#2024-10-01T12:01:00Z", "temperature": Decimal("81.0")},
        ]
        result = _to_reading_dicts(items)
        assert len(result) == 2
        assert result[0]["temperature"] == 80.5
        assert result[0]["timestamp"] == "2024-10-01T12:00:00Z"

    def test_skips_non_reading_items(self):
        items = [
            {"pk": "dev1", "sk": "STATE", "temperature": Decimal("80.0")},
            {"pk": "dev1", "sk": "R#2024-10-01T12:00:00Z", "temperature": Decimal("80.5")},
            {"pk": "dev1", "sk": "F#30min", "predicted_temp": Decimal("82.0")},
        ]
        result = _to_reading_dicts(items)
        assert len(result) == 1

    def test_empty_input(self):
        assert _to_reading_dicts([]) == []

    def test_handles_missing_temperature(self):
        items = [{"pk": "dev1", "sk": "R#2024-10-01T12:00:00Z"}]
        result = _to_reading_dicts(items)
        assert len(result) == 1
        assert result[0]["temperature"] == 0.0
