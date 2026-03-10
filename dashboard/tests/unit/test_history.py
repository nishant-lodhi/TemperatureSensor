"""Granular tests for history page callbacks — sensors, history, compliance."""


from app.data.mock_provider import MockProvider

# ── populate_sensors ──────────────────────────────────────


class TestPopulateSensors:
    def test_returns_options_and_default(self):
        from app.pages.history import populate_sensors
        options, default = populate_sensors(1, None)
        assert isinstance(options, list)
        assert len(options) > 0
        assert default is not None

    def test_options_have_label_value(self):
        from app.pages.history import populate_sensors
        options, _ = populate_sensors(1, None)
        for opt in options:
            assert "label" in opt
            assert "value" in opt

    def test_default_is_first_device(self):
        from app.pages.history import populate_sensors
        options, default = populate_sensors(1, None)
        assert default == options[0]["value"]

    def test_option_count_matches_devices(self):
        from app.pages.history import populate_sensors
        options, _ = populate_sensors(1, None)
        assert len(options) == 20


# ── update_history ────────────────────────────────────────


class TestUpdateHistory:
    def test_with_valid_device(self):
        from app.pages.history import update_history
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_history(did, 6, "30min")
        assert result is not None

    def test_with_no_device(self):
        from app.pages.history import update_history
        result = update_history(None, 6, "30min")
        assert result == ""

    def test_with_empty_device(self):
        from app.pages.history import update_history
        result = update_history("", 6, "30min")
        assert result == ""

    def test_contains_kpi_cards(self):
        from app.pages.history import update_history
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_history(did, 6, "30min")
        html_str = str(result)
        assert "Current" in html_str
        assert "High" in html_str
        assert "Low" in html_str
        assert "Average" in html_str

    def test_contains_compliance_section(self):
        from app.pages.history import update_history
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_history(did, 6, "30min")
        html_str = str(result)
        assert "Compliance" in html_str

    def test_contains_alert_history(self):
        from app.pages.history import update_history
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_history(did, 6, "30min")
        html_str = str(result)
        assert "Alert History" in html_str

    def test_different_time_ranges(self):
        from app.pages.history import update_history
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        for hours in (6, 12, 24, 48):
            result = update_history(did, hours, "30min")
            assert result is not None

    def test_different_horizons(self):
        from app.pages.history import update_history
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        for horizon in ("30min", "2hr"):
            result = update_history(did, 6, horizon)
            assert result is not None

    def test_contains_forecast_kpi(self):
        from app.pages.history import update_history
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_history(did, 6, "30min")
        html_str = str(result)
        assert "Forecast" in html_str

    def test_in_range_percentage(self):
        from app.pages.history import update_history
        prov = MockProvider("demo_client_1")
        did = prov.get_all_devices()[0]
        result = update_history(did, 6, "30min")
        html_str = str(result)
        assert "In Range" in html_str


# ── _fmt_time helper ──────────────────────────────────────


class TestHistoryFmtTime:
    def test_valid_iso(self):
        from app.pages.history import _fmt_time
        result = _fmt_time("2026-03-09T14:30:00+00:00")
        assert "Mar" in result

    def test_invalid_returns_empty(self):
        from app.pages.history import _fmt_time
        assert _fmt_time("bad") == ""

    def test_empty_returns_empty(self):
        from app.pages.history import _fmt_time
        assert _fmt_time("") == ""


# ── _kpi helper ───────────────────────────────────────────


class TestKpiHelper:
    def test_kpi_returns_div(self):
        from app.pages.history import _kpi
        result = _kpi("Test Label", "42.0°F", "#FF6B00")
        html_str = str(result)
        assert "Test Label" in html_str
        assert "42.0°F" in html_str


# ── _stat helper ──────────────────────────────────────────


class TestStatHelper:
    def test_stat_returns_div(self):
        from app.pages.history import _stat
        result = _stat("Total", "100", "#43A047")
        html_str = str(result)
        assert "Total" in html_str
        assert "100" in html_str
