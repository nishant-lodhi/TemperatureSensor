"""Tests for app.data.analytics — pure computation functions."""

from datetime import datetime, timedelta, timezone

from app.data.analytics import (
    build_sensor_state,
    compute_rate_of_change,
    compute_rolling,
    compute_sensor_status,
    forecast_params,
    forecast_point,
    forecast_series,
    is_anomaly,
    signal_label,
)


class TestSignalLabel:
    def test_strong(self):
        assert signal_label(-40) == "Strong"

    def test_good(self):
        assert signal_label(-55) == "Good"

    def test_weak(self):
        assert signal_label(-75) == "Weak"

    def test_no_signal(self):
        assert signal_label(-90) == "No Signal"

    def test_boundary_strong(self):
        assert signal_label(-50) == "Strong"

    def test_boundary_good(self):
        assert signal_label(-65) == "Good"


class TestComputeRolling:
    def test_basic(self):
        r = compute_rolling([70.0, 72.0, 74.0, 76.0])
        assert r["avg"] == 73.0
        assert r["high"] == 76.0
        assert r["low"] == 70.0
        assert r["std"] > 0

    def test_empty(self):
        r = compute_rolling([])
        assert r["avg"] == 0.0

    def test_single(self):
        r = compute_rolling([75.0])
        assert r["avg"] == 75.0
        assert r["std"] == 0.0


class TestRateOfChange:
    def test_positive(self):
        now = datetime.now(timezone.utc)
        hist = [{"body_temperature": "70.0", "date_added": now - timedelta(minutes=15)}]
        roc = compute_rate_of_change(75.0, hist, now, window_min=10)
        assert roc == 5.0

    def test_no_history(self):
        now = datetime.now(timezone.utc)
        roc = compute_rate_of_change(75.0, [], now)
        assert roc == 0.0


class TestIsAnomaly:
    def test_critical_high(self):
        anom, reason = is_anomaly(100.0, 75.0, 2.0, 95.0, 50.0)
        assert anom is True
        assert "critical high" in reason.lower()

    def test_critical_low(self):
        anom, reason = is_anomaly(45.0, 75.0, 2.0, 95.0, 50.0)
        assert anom is True
        assert "critical low" in reason.lower()

    def test_normal(self):
        anom, reason = is_anomaly(74.0, 74.5, 1.0, 95.0, 50.0)
        assert anom is False
        assert reason is None

    def test_z_score_anomaly(self):
        anom, reason = is_anomaly(82.0, 74.0, 2.0, 95.0, 50.0)
        assert anom is True
        assert "z-score" in reason.lower()


class TestSensorStatus:
    def test_online(self):
        assert compute_sensor_status(30, 120, 300) == "online"

    def test_degraded(self):
        assert compute_sensor_status(150, 120, 300) == "degraded"

    def test_offline(self):
        assert compute_sensor_status(400, 120, 300) == "offline"


class TestBuildSensorState:
    def test_builds_complete_state(self):
        now = datetime.now(timezone.utc)
        row = {"mac": "AA:BB:CC:DD:EE:01", "body_temperature": "74.5",
               "rssi": "-45", "power": "90", "date_added": now, "tags_id": 1, "gateway_mac": "GW01"}
        hist = [{"body_temperature": "73.0", "date_added": now - timedelta(minutes=5)},
                {"body_temperature": "74.0", "date_added": now - timedelta(minutes=10)}]
        cfg = {"temp_high": 85, "temp_low": 65, "critical_high": 95, "critical_low": 50,
               "degraded_sec": 120, "offline_sec": 300}
        s = build_sensor_state(row, hist, now, cfg, "c1", {"zone_id": "z1", "zone_label": "Block A"})
        assert s["device_id"] == "AA:BB:CC:DD:EE:01"
        assert s["temperature"] == 74.5
        assert s["status"] == "online"
        assert s["client_id"] == "c1"
        assert s["zone_id"] == "z1"

    def test_invalid_temp_returns_empty(self):
        now = datetime.now(timezone.utc)
        row = {"mac": "XX", "body_temperature": "bad", "rssi": "-50", "power": "",
               "date_added": now, "tags_id": 1, "gateway_mac": "GW"}
        s = build_sensor_state(row, [], now, {"temp_high": 85, "temp_low": 65,
            "critical_high": 95, "critical_low": 50, "degraded_sec": 120, "offline_sec": 300}, "c", {})
        assert s == {}


class TestForecast:
    def test_params_with_enough_data(self):
        readings = [{"temperature": 70 + i * 0.1} for i in range(10)]
        p = forecast_params(readings)
        assert p is not None
        assert "level" in p and "trend" in p

    def test_params_insufficient(self):
        assert forecast_params([{"temperature": 70}]) is None

    def test_point_forecast(self):
        params = {"level": 74.5, "trend": 0.02, "residual_std": 0.5, "n_points": 30}
        f = forecast_point(params, "30min")
        assert "predicted_temp" in f
        assert f["ci_lower"] < f["predicted_temp"] < f["ci_upper"]

    def test_series_forecast(self):
        params = {"level": 74.5, "trend": 0.02, "residual_std": 0.5, "n_points": 30}
        ref = datetime.now(timezone.utc)
        s = forecast_series(params, ref, 5)
        assert len(s) == 5
        assert all("timestamp" in p and "predicted" in p for p in s)
