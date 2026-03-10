"""Granular tests for monitor page callbacks — banner, grid, detail, alerts."""


from app.data.mock_provider import MockProvider

# ── update_banner ─────────────────────────────────────────


class TestUpdateBanner:
    def test_returns_div(self):
        from app.pages.monitor import update_banner
        result = update_banner(1)
        assert result is not None

    def test_banner_contains_sensor_count(self):
        from app.pages.monitor import update_banner
        result = update_banner(1)
        html_str = str(result)
        assert "Sensors" in html_str

    def test_banner_contains_avg_temp(self):
        from app.pages.monitor import update_banner
        result = update_banner(1)
        html_str = str(result)
        assert "°F" in html_str

    def test_banner_contains_alerts_section(self):
        from app.pages.monitor import update_banner
        result = update_banner(1)
        html_str = str(result)
        assert "Alert" in html_str


# ── update_grid ───────────────────────────────────────────


class TestUpdateGrid:
    def test_returns_div(self):
        from app.pages.monitor import update_grid
        result = update_grid(1, None)
        assert result is not None

    def test_grid_shows_sensor_count_header(self):
        from app.pages.monitor import update_grid
        result = update_grid(1, None)
        html_str = str(result)
        assert "Sensors" in html_str
        assert "20" in html_str


# ── update_detail ─────────────────────────────────────────


class TestUpdateDetail:
    def test_with_valid_device(self):
        from app.pages.monitor import update_detail
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_detail(did, 1)
        assert result is not None

    def test_with_none_selects_first(self):
        from app.pages.monitor import update_detail
        result = update_detail(None, 1)
        assert result is not None

    def test_with_unknown_device(self):
        from app.pages.monitor import update_detail
        result = update_detail("NONEXISTENT_DEVICE", 1)
        html_str = str(result)
        assert "not found" in html_str.lower()

    def test_detail_shows_temperature(self):
        from app.pages.monitor import update_detail
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_detail(did, 1)
        html_str = str(result)
        assert "°F" in html_str

    def test_detail_shows_battery(self):
        from app.pages.monitor import update_detail
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_detail(did, 1)
        html_str = str(result)
        assert "Battery" in html_str

    def test_detail_shows_signal(self):
        from app.pages.monitor import update_detail
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_detail(did, 1)
        html_str = str(result)
        assert "Signal" in html_str

    def test_offline_device_shows_offline_status(self):
        from app.pages.monitor import update_detail
        prov = MockProvider("demo_client_1")
        states = prov.get_all_sensor_states()
        offline = next((s for s in states if s["status"] == "offline"), None)
        if offline:
            result = update_detail(offline["device_id"], 1)
            html_str = str(result)
            assert "OFFLINE" in html_str or "offline" in html_str.lower()


# ── render_alert_drawer ───────────────────────────────────


class TestAlertDrawer:
    def test_hidden_returns_empty(self):
        from app.pages.monitor import render_alert_drawer
        result = render_alert_drawer(False, 1)
        html_str = str(result)
        assert "Active Alerts" not in html_str

    def test_shown_contains_alerts(self):
        from app.pages.monitor import render_alert_drawer
        result = render_alert_drawer(True, 1)
        html_str = str(result)
        assert "Active Alerts" in html_str or "No active alerts" in html_str

    def test_shown_alerts_sorted_by_severity(self):
        from app.pages.monitor import render_alert_drawer
        result = render_alert_drawer(True, 1)
        html_str = str(result)
        if "Urgent" in html_str and "Notice" in html_str:
            urgent_pos = html_str.index("Urgent")
            notice_pos = html_str.index("Notice")
            assert urgent_pos < notice_pos


# ── toggle_alerts ─────────────────────────────────────────


class TestToggleAlerts:
    def test_first_click_opens(self):
        from app.pages.monitor import toggle_alerts
        assert toggle_alerts(1) is True

    def test_second_click_closes(self):
        from app.pages.monitor import toggle_alerts
        assert toggle_alerts(2) is False

    def test_zero_clicks(self):
        from app.pages.monitor import toggle_alerts
        assert toggle_alerts(0) is False

    def test_none_clicks(self):
        from app.pages.monitor import toggle_alerts
        assert toggle_alerts(None) is False


# ── _fmt_time helper ──────────────────────────────────────


class TestFmtTime:
    def test_valid_iso(self):
        from app.pages.monitor import _fmt_time
        result = _fmt_time("2026-03-09T14:30:00+00:00")
        assert "Mar" in result
        assert "14:30" in result

    def test_iso_with_z(self):
        from app.pages.monitor import _fmt_time
        result = _fmt_time("2026-03-09T14:30:00Z")
        assert "Mar" in result

    def test_invalid_returns_empty(self):
        from app.pages.monitor import _fmt_time
        assert _fmt_time("not-a-date") == ""

    def test_empty_returns_empty(self):
        from app.pages.monitor import _fmt_time
        assert _fmt_time("") == ""
