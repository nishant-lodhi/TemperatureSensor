"""Unit tests for ingestion/validator.py."""


from ingestion.validator import validate_event


class TestValidator:
    """Tests for sensor event validation."""

    def test_valid_event(self, sample_event):
        """Sample event with all required fields passes validation."""
        valid, msg = validate_event(sample_event)
        assert valid is True
        assert msg == ""

    def test_missing_device_id(self, sample_event):
        """Missing device_id returns False with message."""
        evt = {k: v for k, v in sample_event.items() if k != "device_id"}
        valid, msg = validate_event(evt)
        assert valid is False
        assert "device_id" in msg or "Missing" in msg

    def test_missing_temperature(self, sample_event):
        """Missing temperature returns False."""
        evt = {k: v for k, v in sample_event.items() if k != "temperature"}
        valid, msg = validate_event(evt)
        assert valid is False
        assert "temperature" in msg or "Missing" in msg

    def test_missing_timestamp(self, sample_event):
        """Missing timestamp returns False."""
        evt = {k: v for k, v in sample_event.items() if k != "timestamp"}
        valid, msg = validate_event(evt)
        assert valid is False
        assert "timestamp" in msg or "Missing" in msg

    def test_invalid_temperature_type(self, sample_event):
        """String temperature fails validation."""
        evt = {**sample_event, "temperature": "82.7"}
        valid, msg = validate_event(evt)
        assert valid is False
        assert "number" in msg or "Temperature" in msg

    def test_temperature_too_high(self, sample_event):
        """Temperature 200°F fails (above valid max)."""
        evt = {**sample_event, "temperature": 200}
        valid, msg = validate_event(evt)
        assert valid is False
        assert "200" in msg or "range" in msg.lower()

    def test_temperature_too_low(self, sample_event):
        """Temperature -50°F fails (below valid min)."""
        evt = {**sample_event, "temperature": -50}
        valid, msg = validate_event(evt)
        assert valid is False
        assert "-50" in msg or "range" in msg.lower()

    def test_invalid_device_id_format(self, sample_event):
        """Device ID with special chars fails."""
        for bad_id in ["dev@ice", "dev ice", "dev!ce", "ab", "a" * 31]:
            evt = {**sample_event, "device_id": bad_id}
            valid, msg = validate_event(evt)
            assert valid is False, f"device_id={bad_id!r} should fail"
            assert "device_id" in msg or "Invalid" in msg or "format" in msg

    def test_future_timestamp(self, sample_event):
        """Timestamp far in future fails."""
        evt = {**sample_event, "timestamp": "2099-01-01T12:00:00.000Z"}
        valid, msg = validate_event(evt)
        assert valid is False
        assert "future" in msg.lower() or "2099" in msg

    def test_invalid_rssi_type(self, sample_event):
        """String rssi fails validation."""
        evt = {**sample_event, "rssi": "-44"}
        valid, msg = validate_event(evt)
        assert valid is False
        assert "RSSI" in msg or "number" in msg

    def test_none_rssi_is_ok(self, sample_event):
        """rssi=None passes (optional field)."""
        evt = {**sample_event, "rssi": None}
        valid, msg = validate_event(evt)
        assert valid is True
        assert msg == ""

    def test_rssi_omitted_is_ok(self, sample_event):
        """rssi omitted passes (optional field)."""
        evt = {k: v for k, v in sample_event.items() if k != "rssi"}
        valid, msg = validate_event(evt)
        assert valid is True
        assert msg == ""

    def test_edge_valid_temperature(self, sample_event):
        """Boundary temperatures -40 and 150 should pass."""
        for temp in (-40.0, 150.0):
            evt = {**sample_event, "temperature": temp}
            valid, msg = validate_event(evt)
            assert valid is True, f"temperature={temp} should pass: {msg}"
            assert msg == ""

    def test_invalid_timestamp_format(self, sample_event):
        """Unparseable timestamp fails."""
        evt = {**sample_event, "timestamp": "not-a-date"}
        valid, msg = validate_event(evt)
        assert valid is False
        assert "timestamp" in msg.lower() or "Unparseable" in msg or "parse" in msg
