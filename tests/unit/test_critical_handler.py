"""Unit tests for handlers/critical_handler.py — IoT Core critical alert path."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")


from handlers.critical_handler import lambda_handler
from storage import dynamodb_store


def _critical_event(temperature=96.5, device_id="C30000301A80"):
    return {
        "device_id": device_id,
        "temperature": temperature,
        "rssi": -44,
        "power": 87,
        "timestamp": "2024-10-01T12:00:00.000Z",
        "gateway_id": "AC233FC170F4",
    }


class TestCriticalHandler:
    def test_critical_high_temp_fires_alert(self, seed_device):
        result = lambda_handler(_critical_event(96.5), None)
        assert result["statusCode"] == 200
        assert result["alert"] is not None
        assert result["alert"]["severity"] == "CRITICAL"
        assert result["alert"]["alert_type"] == "EXTREME_TEMPERATURE"

    def test_critical_low_temp_fires_alert(self, seed_device):
        result = lambda_handler(_critical_event(45.0), None)
        assert result["statusCode"] == 200
        assert result["alert"] is not None
        assert result["alert"]["severity"] == "CRITICAL"

    def test_normal_temp_no_alert(self, seed_device):
        result = lambda_handler(_critical_event(80.0), None)
        assert result["statusCode"] == 200
        assert result["alert"] is None

    def test_alert_stored_in_dynamodb(self, seed_device):
        lambda_handler(_critical_event(96.5), None)
        active = dynamodb_store.get_active_alerts("facility_A#zone_b")
        critical = [a for a in active if a.get("severity") == "CRITICAL"]
        assert len(critical) >= 1

    def test_unregistered_device_still_uses_defaults(self, aws_mock):
        result = lambda_handler(_critical_event(96.5, "UNREGISTERED_XYZ"), None)
        assert result["statusCode"] == 200
        assert result["alert"] is not None

    def test_invalid_event_returns_400(self, seed_device):
        result = lambda_handler({"device_id": "C30000301A80", "temperature": "not-a-number",
                                 "timestamp": "2024-10-01T12:00:00Z"}, None)
        assert result["statusCode"] == 400
        assert "error" in result

    def test_missing_fields_returns_400(self, seed_device):
        result = lambda_handler({"temperature": 96.5}, None)
        assert result["statusCode"] == 400

    def test_alert_includes_device_and_zone(self, seed_device):
        result = lambda_handler(_critical_event(96.5), None)
        alert = result["alert"]
        assert alert["device_id"] == "C30000301A80"
        assert "zone_id" in alert
        assert "facility_id" in alert

    def test_boundary_temp_just_above_critical(self, seed_device):
        """95.1°F should trigger (critical_high=95)."""
        result = lambda_handler(_critical_event(95.1), None)
        assert result["alert"] is not None

    def test_boundary_temp_at_critical(self, seed_device):
        """95.0°F should NOT trigger (> not >=)."""
        result = lambda_handler(_critical_event(95.0), None)
        assert result["alert"] is None

    def test_boundary_temp_just_below_critical_low(self, seed_device):
        """49.9°F should trigger (critical_low=50)."""
        result = lambda_handler(_critical_event(49.9), None)
        assert result["alert"] is not None
