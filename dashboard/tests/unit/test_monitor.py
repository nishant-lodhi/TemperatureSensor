"""Tests for unified monitor page — banner, grid, kpis, chart, compliance, alerts."""

from tests.mock_provider import MockProvider

_prov = MockProvider("test_client")


def _states():
    return _prov.get_all_sensor_states()


def _alerts():
    return _prov.get_live_alerts()


def _comp():
    return _prov.get_compliance_history(7)


def _readings_data(device_id=None, range_mode="live"):
    """Build a readings_data dict matching the data pump output."""
    if not device_id:
        device_id = _prov.get_all_sensor_states()[0]["device_id"]
    return {
        "device_id": device_id,
        "readings": _prov.get_readings(device_id, ""),
        "forecast": _prov.get_forecast_series(device_id, "30min", 10),
        "offline": False,
        "alerts": _prov.get_alert_history(device_id),
        "range_mode": range_mode,
    }


class TestRenderBanner:
    def test_returns_div(self):
        from app.pages.monitor import render_banner
        result = render_banner(_states(), _alerts())
        assert result is not None

    def test_banner_contains_sensor_count(self):
        from app.pages.monitor import render_banner
        html_str = str(render_banner(_states(), _alerts()))
        assert "Sensors" in html_str

    def test_banner_contains_avg_temp(self):
        from app.pages.monitor import render_banner
        html_str = str(render_banner(_states(), _alerts()))
        assert "°F" in html_str

    def test_banner_contains_alerts(self):
        from app.pages.monitor import render_banner
        html_str = str(render_banner(_states(), _alerts()))
        assert "Alert" in html_str

    def test_empty_states(self):
        from app.pages.monitor import render_banner
        result = render_banner([], [])
        assert result is not None


class TestRenderGrid:
    def test_show_all(self):
        from app.pages.monitor import render_grid
        result = render_grid(_states(), _alerts(), None, True)
        assert result is not None
        assert "Sensors" in str(result)

    def test_critical_only(self):
        from app.pages.monitor import render_grid
        result = render_grid(_states(), _alerts(), None, False)
        html_str = str(result)
        assert "Critical" in html_str or "No critical" in html_str

    def test_none_defaults_to_all(self):
        from app.pages.monitor import render_grid
        result = render_grid(_states(), _alerts(), None, None)
        html_str = str(result)
        assert "Sensors" in html_str

    def test_selected_sensor_highlighted(self):
        from app.pages.monitor import render_grid
        did = _states()[0]["device_id"]
        result = render_grid(_states(), _alerts(), did, True)
        html_str = str(result)
        assert did in html_str

    def test_empty_states(self):
        from app.pages.monitor import render_grid
        result = render_grid([], [], None, True)
        assert result is not None


class TestRenderKpis:
    def test_with_data(self):
        from app.pages.monitor import render_kpis
        rd = _readings_data()
        result = render_kpis(rd, _states(), rd["device_id"])
        html_str = str(result)
        assert "°F" in html_str
        assert "High" in html_str
        assert "Low" in html_str

    def test_with_offline_sensor(self):
        from app.pages.monitor import render_kpis
        states = _states()
        offline = next((s for s in states if s["status"] == "offline"), None)
        if offline:
            did = offline["device_id"]
            rd = {"device_id": did, "readings": _prov.get_readings(did, ""),
                  "forecast": [], "offline": True, "alerts": [], "range_mode": "live"}
            result = render_kpis(rd, states, did)
            html_str = str(result)
            assert "OFFLINE" in html_str or "Last Reading" in html_str

    def test_empty_readings(self):
        from app.pages.monitor import render_kpis
        result = render_kpis(None, _states(), None)
        assert str(result).strip() != ""

    def test_anomaly_displayed(self):
        from app.pages.monitor import render_kpis
        states = _states()
        anom_s = next((s for s in states if s.get("anomaly")), None)
        if anom_s:
            did = anom_s["device_id"]
            rd = {"device_id": did, "readings": _prov.get_readings(did, ""),
                  "forecast": [], "offline": False, "alerts": [], "range_mode": "live"}
            result = render_kpis(rd, states, did)
            assert "Anomaly" in str(result)


class TestRenderChart:
    def test_with_data(self):
        from app.pages.monitor import render_chart
        rd = _readings_data()
        result = render_chart(rd)
        assert result is not None

    def test_no_data(self):
        from app.pages.monitor import render_chart
        result = render_chart(None)
        assert "Select a sensor" in str(result)

    def test_empty_readings(self):
        from app.pages.monitor import render_chart
        result = render_chart({"device_id": "x", "readings": [], "forecast": [], "offline": False, "alerts": [], "range_mode": "live"})
        assert "Select a sensor" in str(result)


class TestRenderAlerts:
    def test_no_selection(self):
        from app.pages.monitor import render_alerts
        result = render_alerts(_alerts(), None, None)
        assert "Alert" not in str(result)

    def test_with_alerts(self):
        from app.pages.monitor import render_alerts
        alerts = _alerts()
        if alerts:
            did = alerts[0]["device_id"]
            result = render_alerts(alerts, did, None)
            html_str = str(result)
            assert "Alert" in html_str

    def test_sensor_no_alerts(self):
        from app.pages.monitor import render_alerts
        result = render_alerts([], _states()[0]["device_id"], None)
        assert str(result).strip() != ""


class TestRenderCompliance:
    def test_returns_content(self):
        from app.pages.monitor import render_compliance
        result = render_compliance(_states(), _comp())
        assert result is not None

    def test_contains_labels(self):
        from app.pages.monitor import render_compliance
        html_str = str(render_compliance(_states(), _comp()))
        assert "Compliance" in html_str
        assert "Trend" in html_str

    def test_empty_states(self):
        from app.pages.monitor import render_compliance
        result = render_compliance([], [])
        assert str(result).strip() != ""

    def test_all_offline_shows_last_known(self):
        """Compliance should show for all sensors, including offline."""
        from app.pages.monitor import render_compliance
        states = _states()
        for s in states:
            s["status"] = "offline"
        html_str = str(render_compliance(states, _comp()))
        assert "Last Known Compliance" in html_str


class TestRenderAlertTable:
    def test_with_alerts(self):
        from app.pages.monitor import render_alert_table
        rd = _readings_data("AA:BB:CC:DD:EE:02")
        result = render_alert_table(rd)
        html_str = str(result)
        assert "Alert History" in html_str

    def test_no_readings(self):
        from app.pages.monitor import render_alert_table
        result = render_alert_table(None)
        assert str(result).strip() != ""


class TestRangeBar:
    def test_render(self):
        from app.pages.monitor import render_range_bar
        result = render_range_bar("live")
        html_str = str(result)
        assert "LIVE" in html_str
        assert "7d" in html_str

    def test_active_button(self):
        from app.pages.monitor import render_range_bar
        result = render_range_bar("168")
        html_str = str(result)
        assert "7d" in html_str


class TestToggleFilter:
    def test_true(self):
        from app.pages.monitor import toggle_filter
        assert toggle_filter(True) is True

    def test_false(self):
        from app.pages.monitor import toggle_filter
        assert toggle_filter(False) is False

    def test_none(self):
        from app.pages.monitor import toggle_filter
        assert toggle_filter(None) is False


class TestFmtTime:
    def test_valid(self):
        from app.pages.monitor import _fmt_time
        assert "Mar" in _fmt_time("2026-03-09T14:30:00+00:00")

    def test_z_suffix(self):
        from app.pages.monitor import _fmt_time
        assert "Mar" in _fmt_time("2026-03-09T14:30:00Z")

    def test_invalid(self):
        from app.pages.monitor import _fmt_time
        assert _fmt_time("bad") == ""

    def test_empty(self):
        from app.pages.monitor import _fmt_time
        assert _fmt_time("") == ""
