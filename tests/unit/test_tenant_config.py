"""Unit tests for config/tenant_config.py."""



class TestTenantConfig:
    """Tests for multi-tenant configuration management."""

    def test_get_device_info_found(self, aws_mock, seed_device):
        """Verify get_device_info returns correct client_id, facility_id, zone_id."""
        from config.tenant_config import get_device_info

        info = get_device_info("C30000301A80")
        assert info is not None
        assert info["device_id"] == "C30000301A80"
        assert info["client_id"] == "client_1"
        assert info["facility_id"] == "facility_A"
        assert info["zone_id"] == "zone_b"
        assert info.get("sensor_type", "temp_sensor") == "temp_sensor"
        assert info.get("status", "active") == "active"

    def test_get_device_info_not_found(self, aws_mock):
        """Unknown device returns None."""
        from config.tenant_config import get_device_info

        info = get_device_info("UNKNOWN_DEVICE_XYZ")
        assert info is None

    def test_get_tenant_thresholds_found(self, aws_mock, seed_device):
        """Verify get_tenant_thresholds returns tenant-specific values."""
        from config.tenant_config import get_tenant_thresholds

        thresholds = get_tenant_thresholds("client_1")
        assert thresholds["temp_high"] == 85
        assert thresholds["temp_low"] == 65
        assert thresholds["temp_critical_high"] == 95
        assert thresholds["temp_critical_low"] == 50
        assert thresholds["rapid_change_threshold_f"] == 4
        assert thresholds["rapid_change_window_min"] == 10
        assert thresholds["sustained_duration_min"] == 10
        assert thresholds["sensor_offline_sec"] == 60
        assert thresholds["battery_low_pct"] == 20
        assert thresholds["anomaly_z_threshold"] == 3

    def test_get_tenant_thresholds_fallback(self, aws_mock):
        """Unknown client returns default thresholds."""
        from config.tenant_config import get_tenant_thresholds, default_thresholds

        defaults = default_thresholds()
        result = get_tenant_thresholds("unknown_client_xyz")
        assert result == defaults

    def test_default_thresholds(self):
        """Verify default_thresholds returns all expected keys."""
        from config.tenant_config import default_thresholds

        result = default_thresholds()
        expected_keys = {
            "temp_critical_high",
            "temp_critical_low",
            "temp_high",
            "temp_low",
            "rapid_change_threshold_f",
            "rapid_change_window_min",
            "sustained_duration_min",
            "sensor_offline_sec",
            "battery_low_pct",
            "anomaly_z_threshold",
        }
        assert set(result.keys()) == expected_keys
        for k, v in result.items():
            assert v is not None, f"{k} should not be None"

    def test_default_features_all_keys(self):
        """Verify default_features returns all expected feature flag keys."""
        from config.tenant_config import default_features

        result = default_features()
        expected_keys = {
            "alerts_enabled", "alert_extreme_temp", "alert_sustained_high",
            "alert_rapid_change", "alert_sensor_offline", "alert_anomaly",
            "alert_forecast_breach", "analytics_enabled", "forecasting_enabled",
            "compliance_enabled", "archival_enabled", "notifications_enabled",
            "auto_provision",
        }
        assert set(result.keys()) == expected_keys
        for k in expected_keys - {"auto_provision"}:
            assert result[k] is True, f"{k} should default to True"
        assert result["auto_provision"] is False

    def test_get_tenant_features_fallback(self, aws_mock):
        """Unknown tenant returns global default feature flags."""
        from config.tenant_config import get_tenant_features, default_features

        defaults = default_features()
        result = get_tenant_features("nonexistent_client")
        assert result == defaults

    def test_get_tenant_features_override(self, aws_mock, seed_device):
        """Tenant-specific FEATURES record overrides globals."""
        import boto3
        from config import settings
        from config.tenant_config import get_tenant_features

        dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
        table = dynamodb.Table(settings.PLATFORM_CONFIG_TABLE)
        table.put_item(Item={
            "pk": "TENANT#client_1",
            "sk": "FEATURES",
            "alerts_enabled": False,
            "alert_anomaly": False,
            "notifications_enabled": False,
        })

        result = get_tenant_features("client_1")
        assert result["alerts_enabled"] is False
        assert result["alert_anomaly"] is False
        assert result["notifications_enabled"] is False
        assert result["analytics_enabled"] is True
        assert result["forecasting_enabled"] is True
