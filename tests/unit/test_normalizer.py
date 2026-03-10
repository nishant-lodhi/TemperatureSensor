"""Unit tests for ingestion/normalizer.py."""


from ingestion.normalizer import normalize_event, normalize_csv_row


class TestNormalizeEvent:
    """Tests for normalize_event function."""

    def test_normalize_lambda_event(self, sample_event):
        """Event already in standard format passes through."""
        result = normalize_event(sample_event)
        assert result["device_id"] == sample_event["device_id"]
        assert result["temperature"] == sample_event["temperature"]
        assert result["rssi"] == sample_event["rssi"]
        assert result["power"] == sample_event["power"]
        assert result["timestamp"] == sample_event["timestamp"]
        assert result["gateway_id"] == sample_event["gateway_id"]

    def test_normalize_csv_format(self):
        """CSV columns mac→device_id, body_temperature→temperature mapping."""
        raw = {
            "mac": "C30000301A80",
            "body_temperature": "82.7",
            "rssi": "-44",
            "power": "87",
            "timestamp": "2024-10-01T17:25:16.000Z",
            "gateway_mac": "AC233FC170F4",
        }
        result = normalize_event(raw)
        assert result["device_id"] == "C30000301A80"
        assert result["temperature"] == 82.7
        assert result["rssi"] == -44
        assert result["power"] == 87
        assert result["timestamp"] == "2024-10-01T17:25:16.000Z"
        assert result["gateway_id"] == "AC233FC170F4"

    def test_normalize_csv_row(self):
        """Full CSV row with all mapped columns normalizes correctly."""
        row = {
            "mac": "C30000301A80",
            "body_temperature": "82.7",
            "rssi": "-44",
            "power": "87",
            "timestamp": "2024-10-01T17:25:16.000",
            "gateway_mac": "AC233FC170F4",
        }
        result = normalize_csv_row(row)
        assert result["device_id"] == "C30000301A80"
        assert result["temperature"] == 82.7
        assert result["rssi"] == -44
        assert result["power"] == 87
        assert "timestamp" in result
        assert result["timestamp"].endswith("Z") or "T" in result["timestamp"]
        assert result["gateway_id"] == "AC233FC170F4"

    def test_float_conversion(self):
        """String '82.7' converts to float 82.7."""
        raw = {"mac": "X", "body_temperature": "82.7", "timestamp": "2024-10-01T12:00:00Z"}
        result = normalize_event(raw)
        assert result["temperature"] == 82.7
        assert isinstance(result["temperature"], float)

    def test_int_conversion(self):
        """String '-44' converts to int -44."""
        raw = {
            "mac": "X",
            "body_temperature": "80",
            "rssi": "-44",
            "timestamp": "2024-10-01T12:00:00Z",
        }
        result = normalize_event(raw)
        assert result["rssi"] == -44
        assert isinstance(result["rssi"], int)

    def test_empty_power(self):
        """Empty string power becomes None."""
        raw = {
            "mac": "X",
            "body_temperature": "80",
            "rssi": -44,
            "power": "",
            "timestamp": "2024-10-01T12:00:00Z",
        }
        result = normalize_event(raw)
        assert result.get("power") is None

    def test_quoted_empty_power(self):
        """Power value '""' becomes None."""
        raw = {
            "mac": "X",
            "body_temperature": "80",
            "power": '""',
            "timestamp": "2024-10-01T12:00:00Z",
        }
        result = normalize_event(raw)
        assert result.get("power") is None

    def test_timestamp_normalization(self):
        """Timestamp without Z suffix gets Z appended."""
        raw = {
            "mac": "X",
            "body_temperature": "80",
            "timestamp": "2024-10-01T17:25:16.000",
        }
        result = normalize_event(raw)
        assert result["timestamp"].endswith("Z")
        assert "T" in result["timestamp"]

    def test_timestamp_already_has_z(self):
        """Timestamp with Z suffix is preserved."""
        raw = {
            "mac": "X",
            "body_temperature": "80",
            "timestamp": "2024-10-01T17:25:16.000Z",
        }
        result = normalize_event(raw)
        assert result["timestamp"] == "2024-10-01T17:25:16.000Z"

    def test_csv_row_missing_optional_fields(self):
        """CSV row with only required fields normalizes."""
        row = {"mac": "X", "body_temperature": "80", "timestamp": "2024-10-01T12:00:00Z"}
        result = normalize_csv_row(row)
        assert result["device_id"] == "X"
        assert result["temperature"] == 80.0
        assert result["timestamp"].endswith("Z")
        assert result.get("rssi") is None or result.get("power") is None
