"""Tests for app.data.provider — factory function and mock provider."""

from tests.mock_provider import MockProvider


class TestGetProvider:
    def setup_method(self):
        from app.data import provider
        provider._providers.clear()

    def test_returns_provider(self):
        from app.data.provider import get_provider
        assert get_provider("test") is not None

    def test_default_client(self):
        from app.data.provider import get_provider
        assert get_provider(None) is not None

    def test_caches_per_client(self):
        from app.data.provider import get_provider
        assert get_provider("a") is get_provider("a")

    def test_different_clients_both_resolve(self):
        from app.data.provider import get_provider
        assert get_provider("a") is not None
        assert get_provider("b") is not None

    def test_has_required_methods(self):
        from app.data.provider import get_provider
        p = get_provider("test")
        for m in ("get_all_sensor_states", "get_readings", "get_live_alerts",
                   "get_alert_history", "get_forecast", "get_forecast_series",
                   "get_compliance_history", "get_all_devices", "get_zones",
                   "dismiss_alert", "send_alert_note"):
            assert callable(getattr(p, m, None)), f"Missing: {m}"


class TestMockProviderBasics:
    def test_has_3_sensors(self):
        p = MockProvider("c1")
        assert len(p.get_all_sensor_states()) == 3

    def test_client_id_propagated(self):
        for cid in ("c1", "c2"):
            for s in MockProvider(cid).get_all_sensor_states():
                assert s["client_id"] == cid

    def test_required_keys(self):
        required = {"device_id", "temperature", "status", "battery_pct",
                     "signal_dbm", "signal_label", "anomaly", "client_id",
                     "actual_high_1h", "actual_low_1h", "rolling_avg_1h",
                     "rate_of_change", "last_seen", "facility_id"}
        for s in MockProvider("c1").get_all_sensor_states():
            assert not (required - set(s.keys())), f"Missing keys in {s['device_id']}"

    def test_at_least_one_offline(self):
        assert any(s["status"] == "offline" for s in MockProvider("c1").get_all_sensor_states())

    def test_alerts_have_required_fields(self):
        for a in MockProvider("c1").get_live_alerts():
            assert "device_id" in a and "alert_type" in a and "severity" in a

    def test_dismiss_removes_alert(self):
        p = MockProvider("c1")
        alerts = p.get_live_alerts()
        if alerts:
            p.dismiss_alert(alerts[0]["device_id"], alerts[0]["alert_type"])
            assert len(p.get_live_alerts()) < len(alerts)

    def test_send_note_and_dismiss(self):
        p = MockProvider("c1")
        result = p.send_alert_note("X", "TEST", {"device_id": "X", "alert_type": "TEST"})
        assert result is True
        assert len(p._notes) == 1
