"""Tests for unified monitor page — banner, grid, kpis, chart, compliance, alerts, filters."""

import dash

from tests.mock_provider import MockProvider

_prov = MockProvider("test_client")


def _states():
    return _prov.get_all_sensor_states()


def _alerts():
    return _prov.get_live_alerts()


def _comp():
    return _prov.get_compliance_history(7)


def _readings_data(device_id=None, range_mode="live"):
    if not device_id:
        device_id = _prov.get_all_sensor_states()[0]["device_id"]
    return {
        "device_id": device_id,
        "readings": _prov.get_readings(device_id, ""),
        "forecast": _prov.get_forecast_series(device_id, "30min", 10),
        "offline": False,
        "alerts": _prov.get_alert_history(device_id),
        "range_mode": range_mode,
        "forecast_alert_count": 0,
    }


class TestRenderBanner:
    def test_returns_div(self):
        from app.pages.monitor import render_banner
        assert render_banner(_states(), _alerts(), None, None) is not None

    def test_sensor_count(self):
        from app.pages.monitor import render_banner
        assert "Sensors" in str(render_banner(_states(), _alerts(), None, None))

    def test_avg_temp(self):
        from app.pages.monitor import render_banner
        assert "°F" in str(render_banner(_states(), _alerts(), None, None))

    def test_alerts(self):
        from app.pages.monitor import render_banner
        assert "Alert" in str(render_banner(_states(), _alerts(), None, None))

    def test_empty(self):
        from app.pages.monitor import render_banner
        assert render_banner([], [], None, None) is not None

    def test_facility_name(self):
        from app.pages.monitor import render_banner
        assert "Block A" in str(render_banner(_states(), _alerts(), "Block A", None))

    def test_all_facilities_default(self):
        from app.pages.monitor import render_banner
        assert "All Facilities" in str(render_banner(_states(), _alerts(), None, None))

    def test_facility_filters_alerts(self):
        from app.pages.monitor import render_banner
        full = str(render_banner(_states(), _alerts(), None, None))
        filtered = str(render_banner(_states(), _alerts(), "Block B", None))
        assert full != filtered


class TestStatusBar:
    def test_returns_div(self):
        from app.pages.monitor import render_status_bar
        assert render_status_bar(_states(), _alerts(), "all", None) is not None

    def test_shows_counts(self):
        from app.pages.monitor import render_status_bar
        html_str = str(render_status_bar(_states(), _alerts(), "all", None))
        assert "Sensors" in html_str
        assert "All" in html_str
        assert "Critical" in html_str
        assert "Normal" in html_str

    def test_active_filter(self):
        from app.pages.monitor import render_status_bar
        html_str = str(render_status_bar(_states(), _alerts(), "red", None))
        assert "fpill-on" in html_str


class TestRenderGrid:
    def test_show_all(self):
        from app.pages.monitor import render_grid
        result = render_grid(_states(), _alerts(), None, "all", None)
        assert result is not None

    def test_red_filter(self):
        from app.pages.monitor import render_grid
        result = render_grid(_states(), _alerts(), None, "red", None)
        assert result is not None

    def test_green_filter(self):
        from app.pages.monitor import render_grid
        result = render_grid(_states(), _alerts(), None, "green", None)
        assert result is not None

    def test_selected_highlighted(self):
        from app.pages.monitor import render_grid
        did = _states()[0]["device_id"]
        assert did in str(render_grid(_states(), _alerts(), did, "all", None))

    def test_empty(self):
        from app.pages.monitor import render_grid
        assert render_grid([], [], None, "all", None) is not None

    def test_location_filter(self):
        from app.pages.monitor import render_grid
        html_str = str(render_grid(_states(), _alerts(), None, "all", "Block A"))
        assert "AA:BB:CC:DD:EE:01" in html_str
        assert "AA:BB:CC:DD:EE:02" not in html_str

    def test_location_no_match(self):
        from app.pages.monitor import render_grid
        assert "No sensors" in str(render_grid(_states(), _alerts(), None, "all", "Nonexistent"))

    def test_location_on_tile(self):
        from app.pages.monitor import render_grid
        html_str = str(render_grid(_states(), _alerts(), None, "all", None))
        assert "Block A" in html_str or "Block B" in html_str


class TestRenderKpis:
    def test_with_data(self):
        from app.pages.monitor import render_kpis
        rd = _readings_data()
        html_str = str(render_kpis(rd, _states(), rd["device_id"]))
        assert "°F" in html_str and "High" in html_str

    def test_offline(self):
        from app.pages.monitor import render_kpis
        states = _states()
        off = next((s for s in states if s["status"] == "offline"), None)
        if off:
            rd = {"device_id": off["device_id"], "readings": _prov.get_readings(off["device_id"], ""),
                  "forecast": [], "offline": True, "alerts": [], "range_mode": "live", "forecast_alert_count": 0}
            assert "OFFLINE" in str(render_kpis(rd, states, off["device_id"])) or "Last" in str(render_kpis(rd, states, off["device_id"]))

    def test_empty(self):
        from app.pages.monitor import render_kpis
        assert str(render_kpis(None, _states(), None)).strip() != ""

    def test_location_in_header(self):
        from app.pages.monitor import render_kpis
        rd = _readings_data()
        assert "Block A" in str(render_kpis(rd, _states(), rd["device_id"]))


class TestRenderChart:
    def test_with_data(self):
        from app.pages.monitor import render_chart
        assert render_chart(_readings_data()) is not None

    def test_no_data(self):
        from app.pages.monitor import render_chart
        assert "Select a sensor" in str(render_chart(None))

    def test_empty_readings(self):
        from app.pages.monitor import render_chart
        assert "Select a sensor" in str(render_chart({"device_id": "x", "readings": [], "forecast": [],
                                                       "offline": False, "alerts": [], "range_mode": "live",
                                                       "forecast_alert_count": 0}))


class TestRenderAlerts:
    def test_no_selection(self):
        from app.pages.monitor import render_alerts
        assert "Alert" not in str(render_alerts(_alerts(), None, None))

    def test_with_alerts(self):
        from app.pages.monitor import render_alerts
        alerts = _alerts()
        if alerts:
            assert "Alert" in str(render_alerts(alerts, alerts[0]["device_id"], None))

    def test_empty(self):
        from app.pages.monitor import render_alerts
        assert str(render_alerts([], _states()[0]["device_id"], None)).strip() != ""


class TestRenderCompliance:
    def test_returns(self):
        from app.pages.monitor import render_compliance
        assert render_compliance(_states(), _comp(), None) is not None

    def test_labels(self):
        from app.pages.monitor import render_compliance
        html_str = str(render_compliance(_states(), _comp(), None))
        assert "Compliance" in html_str

    def test_empty(self):
        from app.pages.monitor import render_compliance
        assert str(render_compliance([], [], None)).strip() != ""

    def test_all_offline(self):
        from app.pages.monitor import render_compliance
        states = _states()
        for s in states:
            s["status"] = "offline"
        assert "Last Known" in str(render_compliance(states, _comp(), None))


class TestRenderAlertTable:
    def test_with_alerts(self):
        from app.pages.monitor import render_alert_table
        assert "Alert History" in str(render_alert_table(_readings_data("AA:BB:CC:DD:EE:02")))

    def test_no_readings(self):
        from app.pages.monitor import render_alert_table
        assert str(render_alert_table(None)).strip() != ""


class TestRangeBar:
    def test_render(self):
        from app.pages.monitor import render_range_bar
        html_str = str(render_range_bar("live"))
        assert "LIVE" in html_str and "24" in html_str

    def test_active(self):
        from app.pages.monitor import render_range_bar
        assert "rbtn-on" in str(render_range_bar("6"))

    def test_no_old_ranges(self):
        from app.pages.monitor import render_range_bar
        html_str = str(render_range_bar("live"))
        assert "48h" not in html_str and "120d" not in html_str


class TestSensorColor:
    def test_green(self):
        from app.pages.monitor import _sensor_color
        assert _sensor_color({"device_id": "t", "status": "online", "temperature": 73.0, "anomaly": False, "battery_pct": 90}, set()) == "green"

    def test_red_alert(self):
        from app.pages.monitor import _sensor_color
        assert _sensor_color({"device_id": "t", "status": "online", "temperature": 73.0, "anomaly": False, "battery_pct": 90}, {"t"}) == "red"

    def test_red_temp(self):
        from app.pages.monitor import _sensor_color
        assert _sensor_color({"device_id": "t", "status": "online", "temperature": 90.0, "anomaly": False, "battery_pct": 90}, set()) == "red"

    def test_yellow_anomaly(self):
        from app.pages.monitor import _sensor_color
        assert _sensor_color({"device_id": "t", "status": "online", "temperature": 73.0, "anomaly": True, "battery_pct": 90}, set()) == "yellow"

    def test_yellow_battery(self):
        from app.pages.monitor import _sensor_color
        assert _sensor_color({"device_id": "t", "status": "online", "temperature": 73.0, "anomaly": False, "battery_pct": 30}, set()) == "yellow"


class TestForecastAlerts:
    def test_high(self):
        from app.pages.monitor import _build_forecast_alerts
        r = _build_forecast_alerts([{"timestamp": "2026-03-11T20:00:00Z", "predicted": 90.0}], "SIM001")
        assert len(r) == 1 and r[0]["severity"] == "FORECAST"

    def test_low(self):
        from app.pages.monitor import _build_forecast_alerts
        r = _build_forecast_alerts([{"timestamp": "2026-03-11T20:00:00Z", "predicted": 60.0}], "SIM001")
        assert r[0]["alert_type"] == "FORECAST_LOW"

    def test_none(self):
        from app.pages.monitor import _build_forecast_alerts
        assert len(_build_forecast_alerts([{"timestamp": "2026-03-11T20:00:00Z", "predicted": 73.0}], "SIM001")) == 0


class TestLocationFilter:
    def test_options_with_data(self):
        from app.pages.monitor import update_location_options
        r = update_location_options(["Block A", "Block B"])
        assert len(r) == 2 and r[0]["value"] == "Block A"

    def test_options_empty(self):
        from app.pages.monitor import update_location_options
        assert update_location_options([]) == []

    def test_mac_all(self):
        from app.pages.monitor import update_mac_options
        assert len(update_mac_options(None, _states())) == 3

    def test_mac_filtered(self):
        from app.pages.monitor import update_mac_options
        r = update_mac_options("Block A", _states())
        assert len(r) == 2 and "AA:BB:CC:DD:EE:01" in [x["value"] for x in r]

    def test_mac_empty(self):
        from app.pages.monitor import update_mac_options
        assert update_mac_options(None, []) == []


class TestProviderLocations:
    def test_has_locations(self):
        assert _prov.get_locations() == ["Block A", "Block B"]

    def test_sensors_for_location(self):
        sensors = _prov.get_sensors_for_location("Block A")
        assert "AA:BB:CC:DD:EE:01" in sensors and "AA:BB:CC:DD:EE:02" not in sensors

    def test_sensors_none(self):
        assert len(_prov.get_sensors_for_location(None)) == 3


class TestFmtTime:
    def test_valid(self):
        from app.pages.monitor import _fmt_time
        assert "Mar" in _fmt_time("2026-03-09T14:30:00+00:00")

    def test_z(self):
        from app.pages.monitor import _fmt_time
        assert "Mar" in _fmt_time("2026-03-09T14:30:00Z")

    def test_invalid(self):
        from app.pages.monitor import _fmt_time
        assert _fmt_time("bad") == ""

    def test_empty(self):
        from app.pages.monitor import _fmt_time
        assert _fmt_time("") == ""
