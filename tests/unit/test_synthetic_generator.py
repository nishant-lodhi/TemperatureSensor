"""Unit tests for src/handlers/synthetic_generator.py — data format, anomaly, Kinesis write."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

os.environ.setdefault("SENSOR_DATA_STREAM", "test-stream")
os.environ.setdefault("DEPLOYMENT_ID", "test00dep0")
os.environ.setdefault("SYNTHETIC_SENSOR_COUNT", "20")

from handlers.synthetic_generator import (
    lambda_handler,
    _generate_sensor_reading,
    _stable_mac,
    _put_to_kinesis,
    ZONES,
)


# ── Stable MAC ──────────────────────────────────────────────────────


class TestStableMAC:
    def test_format(self):
        mac = _stable_mac(0)
        parts = mac.split(":")
        assert len(parts) == 6
        for p in parts:
            assert len(p) == 2
            int(p, 16)

    def test_deterministic(self):
        assert _stable_mac(5) == _stable_mac(5)

    def test_different_indexes_different_macs(self):
        assert _stable_mac(0) != _stable_mac(1)


# ── Sensor reading generation ───────────────────────────────────────


class TestGenerateSensorReading:
    def test_required_fields(self):
        reading = _generate_sensor_reading(0, 1700000000.0, "2025-06-15T10:30:00Z")
        assert "device_id" in reading
        assert "client_id" in reading
        assert "temperature" in reading
        assert "rssi" in reading
        assert "signal_dbm" in reading
        assert "battery_pct" in reading
        assert "zone_id" in reading
        assert "timestamp" in reading
        assert "source" in reading
        assert reading["source"] == "synthetic"

    def test_temperature_reasonable_range(self):
        readings = [_generate_sensor_reading(i, 1700000000.0, "2025-06-15T10:30:00Z")
                     for i in range(100)]
        temps = [r["temperature"] for r in readings]
        assert min(temps) >= 30.0
        assert max(temps) <= 120.0

    def test_rssi_range(self):
        reading = _generate_sensor_reading(0, 1700000000.0, "2025-06-15T10:30:00Z")
        assert -80 <= reading["rssi"] <= -30

    def test_battery_range(self):
        reading = _generate_sensor_reading(0, 1700000000.0, "2025-06-15T10:30:00Z")
        assert 10 <= reading["battery_pct"] <= 100

    def test_zone_assignment(self):
        for i in range(len(ZONES)):
            reading = _generate_sensor_reading(i, 1700000000.0, "2025-06-15T10:30:00Z")
            assert reading["zone_id"] in ZONES

    def test_signal_quality_field(self):
        reading = _generate_sensor_reading(0, 1700000000.0, "2025-06-15T10:30:00Z")
        assert reading["signal_quality"] in ("Strong", "Good", "Weak")


# ── Lambda handler ──────────────────────────────────────────────────


class TestLambdaHandler:
    @patch("handlers.synthetic_generator.kinesis")
    def test_generates_correct_count(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        result = lambda_handler({}, None)
        assert result["generated"] == 20
        mock_kinesis.put_records.assert_called_once()
        args = mock_kinesis.put_records.call_args
        assert len(args[1]["Records"]) == 20

    @patch("handlers.synthetic_generator.kinesis")
    def test_records_are_valid_json(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        lambda_handler({}, None)
        args = mock_kinesis.put_records.call_args
        for record in args[1]["Records"]:
            data = json.loads(record["Data"])
            assert "device_id" in data
            assert "temperature" in data

    @patch("handlers.synthetic_generator.kinesis")
    def test_partition_keys_set(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        lambda_handler({}, None)
        args = mock_kinesis.put_records.call_args
        for record in args[1]["Records"]:
            assert len(record["PartitionKey"]) > 0

    @patch("handlers.synthetic_generator.SENSOR_COUNT", 510)
    @patch("handlers.synthetic_generator.kinesis")
    def test_batches_over_500(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        lambda_handler({}, None)
        assert mock_kinesis.put_records.call_count == 2


# ── Kinesis write ───────────────────────────────────────────────────


class TestPutToKinesis:
    @patch("handlers.synthetic_generator.kinesis")
    def test_writes_records(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        records = [{"device_id": f"dev-{i}", "temperature": 72.0} for i in range(5)]
        _put_to_kinesis(records)
        mock_kinesis.put_records.assert_called_once()
        args = mock_kinesis.put_records.call_args
        assert len(args[1]["Records"]) == 5

    @patch("handlers.synthetic_generator.kinesis")
    def test_empty_list_no_call(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        _put_to_kinesis([])
        mock_kinesis.put_records.assert_not_called()
