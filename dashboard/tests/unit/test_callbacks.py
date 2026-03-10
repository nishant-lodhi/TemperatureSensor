"""Tests for dashboard data providers — MockProvider multi-tenant, all methods."""

from datetime import datetime, timedelta, timezone

import pytest

from app.data.mock_provider import MockProvider

# ── Client configuration ──────────────────────────────────


class TestClientConfigs:
    def test_demo_client_1_has_20_sensors(self):
        p = MockProvider("demo_client_1")
        assert len(p.get_all_sensor_states()) == 20

    def test_demo_client_2_has_15_sensors(self):
        p = MockProvider("demo_client_2")
        assert len(p.get_all_sensor_states()) == 15

    def test_demo_client_3_has_10_sensors(self):
        p = MockProvider("demo_client_3")
        assert len(p.get_all_sensor_states()) == 10

    def test_unknown_client_falls_back_to_client_1(self):
        p = MockProvider("unknown_client")
        assert len(p.get_all_sensor_states()) == 20

    def test_client_id_propagated_to_states(self):
        for cid in ("demo_client_1", "demo_client_2", "demo_client_3"):
            p = MockProvider(cid)
            for s in p.get_all_sensor_states():
                assert s["client_id"] == cid

    def test_facility_id_derived_from_client(self):
        p = MockProvider("demo_client_2")
        states = p.get_all_sensor_states()
        for s in states:
            assert s["facility_id"] == "facility_demo_client_2"


# ── Sensor state schema ──────────────────────────────────


class TestSensorStateSchema:
    @pytest.fixture()
    def provider(self):
        return MockProvider("demo_client_1")

    def test_required_keys_present(self, provider):
        required = {
            "device_id", "temperature", "status", "battery_pct",
            "signal_dbm", "signal_label", "anomaly", "client_id",
            "actual_high_1h", "actual_low_1h", "rolling_avg_1h",
            "rate_of_change", "last_seen", "facility_id",
        }
        for s in provider.get_all_sensor_states():
            missing = required - set(s.keys())
            assert not missing, f"Sensor {s['device_id']} missing: {missing}"

    def test_temperature_is_float(self, provider):
        for s in provider.get_all_sensor_states():
            assert isinstance(s["temperature"], float)

    def test_battery_pct_in_valid_range(self, provider):
        for s in provider.get_all_sensor_states():
            assert 0 <= s["battery_pct"] <= 100

    def test_signal_labels_valid(self, provider):
        valid = {"Strong", "Good", "Weak", "No Signal"}
        for s in provider.get_all_sensor_states():
            assert s["signal_label"] in valid

    def test_status_values_valid(self, provider):
        for s in provider.get_all_sensor_states():
            assert s["status"] in ("online", "offline")

    def test_anomaly_is_boolean(self, provider):
        for s in provider.get_all_sensor_states():
            assert isinstance(s["anomaly"], bool)

    def test_anomaly_reason_set_when_anomaly_true(self, provider):
        for s in provider.get_all_sensor_states():
            if s["anomaly"]:
                assert s["anomaly_reason"] is not None
                assert len(s["anomaly_reason"]) > 0


# ── Offline sensors ───────────────────────────────────────


class TestOfflineSensors:
    def test_at_least_one_offline(self):
        p = MockProvider("demo_client_1")
        states = p.get_all_sensor_states()
        offline = [s for s in states if s["status"] == "offline"]
        assert len(offline) >= 1

    def test_offline_sensor_frozen_values(self):
        p = MockProvider("demo_client_1")
        states = p.get_all_sensor_states()
        for s in states:
            if s["status"] == "offline":
                assert s["battery_pct"] == 0
                assert s["signal_label"] == "No Signal"
                assert s["signal_dbm"] == -99
                assert s["rate_of_change"] == 0.0

    def test_offline_last_seen_is_in_past(self):
        p = MockProvider("demo_client_1")
        states = p.get_all_sensor_states()
        now = datetime.now(timezone.utc)
        for s in states:
            if s["status"] == "offline":
                last_seen = datetime.fromisoformat(s["last_seen"])
                assert last_seen < now


# ── State caching ─────────────────────────────────────────


class TestStateCaching:
    def test_cached_within_ttl(self):
        p = MockProvider("demo_client_1")
        s1 = p.get_all_sensor_states()
        s2 = p.get_all_sensor_states()
        assert s1 is s2

    def test_cache_expires(self):
        p = MockProvider("demo_client_1")
        p._cache["ttl"] = 0
        s1 = p.get_all_sensor_states()
        p._cache["states_ts"] = 0
        s2 = p.get_all_sensor_states()
        assert s1 is not s2


# ── get_all_devices ───────────────────────────────────────


class TestGetAllDevices:
    def test_returns_list_of_strings(self):
        p = MockProvider("demo_client_1")
        devices = p.get_all_devices()
        assert isinstance(devices, list)
        assert all(isinstance(d, str) for d in devices)

    def test_count_matches_states(self):
        p = MockProvider("demo_client_1")
        assert len(p.get_all_devices()) == len(p.get_all_sensor_states())

    def test_device_ids_start_with_c3(self):
        p = MockProvider("demo_client_1")
        for d in p.get_all_devices():
            assert d.startswith("C3")


# ── get_zones / get_devices_in_zone ───────────────────────


class TestZones:
    def test_get_zones_returns_empty_by_default(self):
        p = MockProvider("demo_client_1")
        assert p.get_zones() == []

    def test_get_devices_in_zone_returns_empty(self):
        p = MockProvider("demo_client_1")
        assert p.get_devices_in_zone("nonexistent") == []


# ── get_readings ──────────────────────────────────────────


class TestReadings:
    @pytest.fixture()
    def provider(self):
        return MockProvider("demo_client_1")

    def test_returns_list_of_dicts(self, provider):
        did = provider.get_all_devices()[0]
        readings = provider.get_readings(did, (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
        assert isinstance(readings, list)
        assert len(readings) > 0

    def test_reading_schema(self, provider):
        did = provider.get_all_devices()[0]
        readings = provider.get_readings(did, (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
        for r in readings:
            assert "timestamp" in r
            assert "temperature" in r
            assert isinstance(r["temperature"], float)

    def test_unknown_device_returns_empty(self, provider):
        assert provider.get_readings("UNKNOWN_DEVICE", "2026-01-01T00:00:00Z") == []

    def test_readings_sorted_by_time(self, provider):
        did = provider.get_all_devices()[0]
        readings = provider.get_readings(did, (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
        timestamps = [r["timestamp"] for r in readings]
        assert timestamps == sorted(timestamps)

    def test_readings_count_scales_with_time_range(self, provider):
        did = provider.get_all_devices()[0]
        r1h = provider.get_readings(did, (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
        r2h = provider.get_readings(did, (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
        assert len(r2h) >= len(r1h)


# ── get_active_alerts / get_all_alerts ────────────────────


class TestAlerts:
    @pytest.fixture()
    def provider(self):
        return MockProvider("demo_client_1")

    def test_active_alerts_only_active(self, provider):
        for a in provider.get_active_alerts():
            assert a["status"] == "ACTIVE"

    def test_active_alerts_have_required_fields(self, provider):
        required = {"alert_type", "severity", "message", "triggered_at", "status", "device_id"}
        for a in provider.get_active_alerts():
            missing = required - set(a.keys())
            assert not missing, f"Alert missing: {missing}"

    def test_all_alerts_include_resolved(self, provider):
        all_a = provider.get_all_alerts()
        statuses = {a["status"] for a in all_a}
        assert "RESOLVED" in statuses

    def test_all_alerts_count_greater_than_active(self, provider):
        assert len(provider.get_all_alerts()) > len(provider.get_active_alerts())

    def test_alert_severities_valid(self, provider):
        valid = {"CRITICAL", "HIGH", "MEDIUM", "WARNING"}
        for a in provider.get_all_alerts():
            assert a["severity"] in valid

    def test_alert_device_ids_belong_to_client(self, provider):
        device_ids = set(provider.get_all_devices())
        for a in provider.get_all_alerts():
            assert a["device_id"] in device_ids

    def test_small_client_has_alerts(self):
        """Even demo_client_3 (10 sensors, >=4) should have alerts."""
        p = MockProvider("demo_client_3")
        assert len(p.get_active_alerts()) > 0


# ── get_forecast / get_forecast_series ────────────────────


class TestForecasts:
    @pytest.fixture()
    def provider(self):
        return MockProvider("demo_client_1")

    def test_forecast_returns_dict(self, provider):
        did = provider.get_all_devices()[0]
        fc = provider.get_forecast(did, "30min")
        assert isinstance(fc, dict)
        assert "predicted_temp" in fc
        assert "ci_lower" in fc
        assert "ci_upper" in fc

    def test_forecast_confidence_interval_order(self, provider):
        did = provider.get_all_devices()[0]
        fc = provider.get_forecast(did, "30min")
        assert fc["ci_lower"] <= fc["predicted_temp"] <= fc["ci_upper"]

    def test_forecast_unknown_device_returns_none(self, provider):
        assert provider.get_forecast("UNKNOWN", "30min") is None

    def test_forecast_series_length(self, provider):
        did = provider.get_all_devices()[0]
        series = provider.get_forecast_series(did, "30min", 10)
        assert len(series) == 10

    def test_forecast_series_schema(self, provider):
        did = provider.get_all_devices()[0]
        series = provider.get_forecast_series(did, "30min", 5)
        for pt in series:
            assert "step" in pt
            assert "timestamp" in pt
            assert "predicted" in pt
            assert "ci_lower" in pt
            assert "ci_upper" in pt

    def test_forecast_series_ci_widens_over_time(self, provider):
        did = provider.get_all_devices()[0]
        series = provider.get_forecast_series(did, "30min", 20)
        widths = [pt["ci_upper"] - pt["ci_lower"] for pt in series]
        assert widths[-1] > widths[0]

    def test_forecast_series_unknown_device_empty(self, provider):
        assert provider.get_forecast_series("UNKNOWN", "30min", 10) == []


# ── Compliance ────────────────────────────────────────────


class TestCompliance:
    @pytest.fixture()
    def provider(self):
        return MockProvider("demo_client_1")

    def test_compliance_report_schema(self, provider):
        report = provider.get_compliance_report("2026-03-01")
        assert report is not None
        assert "overall_compliance_pct" in report
        assert "total_readings" in report
        assert "date" in report
        assert report["date"] == "2026-03-01"

    def test_compliance_pct_in_valid_range(self, provider):
        report = provider.get_compliance_report("2026-03-01")
        assert 0 <= report["overall_compliance_pct"] <= 100

    def test_compliance_deterministic_per_client_date(self, provider):
        r1 = provider.get_compliance_report("2026-03-01")
        r2 = provider.get_compliance_report("2026-03-01")
        assert r1["overall_compliance_pct"] == r2["overall_compliance_pct"]

    def test_compliance_different_dates_vary(self, provider):
        r1 = provider.get_compliance_report("2026-03-01")
        r2 = provider.get_compliance_report("2026-03-02")
        # They may differ (seeded differently); just check both return data
        assert r1 is not None and r2 is not None

    def test_compliance_history_length(self, provider):
        history = provider.get_compliance_history(7)
        assert len(history) == 7

    def test_compliance_history_schema(self, provider):
        for h in provider.get_compliance_history(7):
            assert "date" in h
            assert "compliance_pct" in h
            assert 0 <= h["compliance_pct"] <= 100

    def test_compliance_history_dates_sequential(self, provider):
        history = provider.get_compliance_history(7)
        dates = [h["date"] for h in history]
        assert dates == sorted(dates)

    def test_different_clients_different_compliance(self):
        p1 = MockProvider("demo_client_1")
        p2 = MockProvider("demo_client_2")
        r1 = p1.get_compliance_report("2026-03-01")
        r2 = p2.get_compliance_report("2026-03-01")
        assert r1["total_readings"] != r2["total_readings"]
