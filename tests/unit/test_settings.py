"""Unit tests for config/settings.py."""

import importlib
import os



class TestSettings:
    """Tests for central configuration settings."""

    def test_default_values(self):
        """Verify default temperature and alert threshold values."""
        from config import settings

        assert settings.TEMP_HIGH == 85.0
        assert settings.TEMP_LOW == 65.0
        assert settings.TEMP_CRITICAL_HIGH == 95.0
        assert settings.TEMP_CRITICAL_LOW == 50.0
        assert settings.RAPID_CHANGE_THRESHOLD_F == 4.0
        assert settings.RAPID_CHANGE_WINDOW_MIN == 10
        assert settings.SUSTAINED_DURATION_MIN == 10
        assert settings.SENSOR_OFFLINE_SEC == 60
        assert settings.BATTERY_LOW_PCT == 20
        assert settings.ANOMALY_Z_THRESHOLD == 3.0

    def test_env_override(self):
        """Setting os.environ and reloading settings should change values."""
        from config import settings

        # Save originals
        orig_temp_high = os.environ.get("TEMP_HIGH")
        orig_temp_low = os.environ.get("TEMP_LOW")

        try:
            os.environ["TEMP_HIGH"] = "92.5"
            os.environ["TEMP_LOW"] = "58.0"
            importlib.reload(settings)
            assert settings.TEMP_HIGH == 92.5
            assert settings.TEMP_LOW == 58.0
        finally:
            if orig_temp_high is not None:
                os.environ["TEMP_HIGH"] = orig_temp_high
            else:
                os.environ.pop("TEMP_HIGH", None)
            if orig_temp_low is not None:
                os.environ["TEMP_LOW"] = orig_temp_low
            else:
                os.environ.pop("TEMP_LOW", None)
            importlib.reload(settings)

    def test_csv_column_map(self):
        """Verify all expected CSV column mapping keys are present."""
        from config.settings import CSV_COLUMN_MAP

        expected_keys = {"mac", "body_temperature", "rssi", "power", "timestamp", "gateway_mac"}
        assert set(CSV_COLUMN_MAP.keys()) == expected_keys
        assert CSV_COLUMN_MAP["mac"] == "device_id"
        assert CSV_COLUMN_MAP["body_temperature"] == "temperature"
        assert CSV_COLUMN_MAP["rssi"] == "rssi"
        assert CSV_COLUMN_MAP["power"] == "power"
        assert CSV_COLUMN_MAP["timestamp"] == "timestamp"
        assert CSV_COLUMN_MAP["gateway_mac"] == "gateway_id"

    def test_feature_flags_default_enabled(self):
        """All feature flags should be True by default (except auto_provision)."""
        from config import settings

        assert settings.FEATURE_ALERTS_ENABLED is True
        assert settings.FEATURE_ALERT_EXTREME_TEMP is True
        assert settings.FEATURE_ALERT_SUSTAINED_HIGH is True
        assert settings.FEATURE_ALERT_RAPID_CHANGE is True
        assert settings.FEATURE_ALERT_SENSOR_OFFLINE is True
        assert settings.FEATURE_ALERT_ANOMALY is True
        assert settings.FEATURE_ALERT_FORECAST_BREACH is True
        assert settings.FEATURE_ANALYTICS_ENABLED is True
        assert settings.FEATURE_FORECASTING_ENABLED is True
        assert settings.FEATURE_COMPLIANCE_ENABLED is True
        assert settings.FEATURE_ARCHIVAL_ENABLED is True
        assert settings.FEATURE_NOTIFICATIONS_ENABLED is True
        assert settings.FEATURE_AUTO_PROVISION is False

    def test_feature_flag_env_override(self):
        """Feature flags can be toggled via env vars."""
        from config import settings

        orig = os.environ.get("FEATURE_ALERTS_ENABLED")
        orig_auto = os.environ.get("FEATURE_AUTO_PROVISION")
        try:
            os.environ["FEATURE_ALERTS_ENABLED"] = "false"
            os.environ["FEATURE_AUTO_PROVISION"] = "true"
            importlib.reload(settings)
            assert settings.FEATURE_ALERTS_ENABLED is False
            assert settings.FEATURE_AUTO_PROVISION is True
        finally:
            if orig is not None:
                os.environ["FEATURE_ALERTS_ENABLED"] = orig
            else:
                os.environ.pop("FEATURE_ALERTS_ENABLED", None)
            if orig_auto is not None:
                os.environ["FEATURE_AUTO_PROVISION"] = orig_auto
            else:
                os.environ.pop("FEATURE_AUTO_PROVISION", None)
            importlib.reload(settings)
