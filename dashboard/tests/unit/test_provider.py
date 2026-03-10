"""Tests for app.data.provider — factory function and caching."""

from unittest.mock import patch


class TestGetProvider:
    def setup_method(self):
        from app.data import provider
        provider._providers.clear()

    def test_returns_mock_provider_when_aws_false(self):
        from app.data.mock_provider import MockProvider
        from app.data.provider import get_provider
        p = get_provider("demo_client_1")
        assert isinstance(p, MockProvider)

    def test_default_client_id_is_demo_client_1(self):
        from app.data.provider import get_provider
        p = get_provider(None)
        states = p.get_all_sensor_states()
        assert all(s["client_id"] == "demo_client_1" for s in states)

    def test_caches_per_client_id(self):
        from app.data.provider import get_provider
        p1 = get_provider("demo_client_1")
        p2 = get_provider("demo_client_1")
        assert p1 is p2

    def test_different_clients_get_different_providers(self):
        from app.data.provider import get_provider
        p1 = get_provider("demo_client_1")
        p2 = get_provider("demo_client_2")
        assert p1 is not p2

    def test_provider_has_required_methods(self):
        from app.data.provider import get_provider
        p = get_provider("demo_client_1")
        required = [
            "get_all_sensor_states", "get_readings", "get_active_alerts",
            "get_all_alerts", "get_forecast", "get_forecast_series",
            "get_compliance_report", "get_compliance_history",
            "get_zones", "get_devices_in_zone", "get_all_devices",
        ]
        for method_name in required:
            assert hasattr(p, method_name), f"Missing method: {method_name}"
            assert callable(getattr(p, method_name))

    @patch("app.config.AWS_MODE", True)
    def test_aws_mode_imports_aws_provider(self):
        from app.data import provider
        provider._providers.clear()
        with patch("app.data.aws_provider.AWSProvider") as MockAWS:
            MockAWS.return_value = MockAWS
            from importlib import reload
            reload(provider)
            provider.get_provider("test_client")
            MockAWS.assert_called_once_with("test_client")
