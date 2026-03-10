"""Unit tests for config/resource_naming.py."""

import pytest

from config.resource_naming import build_name, build_all_names


class TestBuildName:
    """Tests for build_name function."""

    def test_build_name_default(self):
        """Default prefix, deployment_id, env produce expected name."""
        result = build_name("platform-config")
        assert result == "temp-sensor-platform-config-0000000000-dev"

    def test_build_name_custom(self):
        """Custom prefix, deployment_id, env produce expected name."""
        result = build_name(
            "sensor-data",
            prefix="my-project",
            deployment_id="abc123xyz",
            environment="prod",
        )
        assert result == "my-project-sensor-data-abc123xyz-prod"

    def test_build_name_empty_type_raises(self):
        """Empty resource_type raises ValueError."""
        with pytest.raises(ValueError, match="resource_type is required"):
            build_name("")


class TestBuildAllNames:
    """Tests for build_all_names function."""

    def test_build_all_names(self):
        """All expected keys are returned with correct values."""
        result = build_all_names()
        expected_keys = {
            "stack_name",
            "platform_config_table",
            "sensor_data_table",
            "alerts_table",
            "data_stream",
            "data_bucket",
            "critical_alert_topic",
            "standard_alert_topic",
            "batch_processor_fn",
            "critical_alert_fn",
            "scheduled_processor_fn",
            "lambda_layer",
        }
        assert set(result.keys()) == expected_keys
        assert result["platform_config_table"] == "temp-sensor-platform-config-0000000000-dev"
        assert result["sensor_data_table"] == "temp-sensor-sensor-data-0000000000-dev"
        assert result["data_bucket"] == "temp-sensor-data-lake-0000000000-dev"

    def test_build_all_names_consistency(self):
        """All values start with prefix and end with env."""
        prefix = "my-sensor"
        deployment_id = "deploy99"
        env = "staging"
        result = build_all_names(prefix=prefix, deployment_id=deployment_id, environment=env)
        for key, value in result.items():
            assert value.startswith(prefix), f"{key}={value} should start with {prefix}"
            assert value.endswith(env), f"{key}={value} should end with {env}"
