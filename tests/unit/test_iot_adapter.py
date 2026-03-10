"""Unit tests for src/handlers/iot_adapter.py — BLE decode, filtering, Kinesis write."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

os.environ.setdefault("SENSOR_DATA_STREAM", "test-stream")
os.environ.setdefault("DEPLOYMENT_ID", "test00dep0")

from handlers.iot_adapter import (
    lambda_handler,
    _decode_ble_record,
    _decode_temperature,
    _estimate_battery,
    _put_to_kinesis,
)


# ── Temperature decoding ────────────────────────────────────────────


class TestDecodeTemperature:
    def test_known_value_from_csv(self):
        raw = "02010613FF3906CA03201C2D0380008000800047F8321E"
        temp_f = _decode_temperature(raw)
        assert temp_f is not None
        assert abs(temp_f - 82.7164) < 0.01

    def test_zero_celsius(self):
        raw = "0201060000000000000000000000000000000000000000"
        temp_f = _decode_temperature(raw)
        assert temp_f is not None
        assert abs(temp_f - 32.0) < 0.01

    def test_returns_none_for_short_hex(self):
        assert _decode_temperature("0102") is None

    def test_returns_none_for_invalid_hex(self):
        assert _decode_temperature("ZZZZZZ") is None

    def test_returns_none_for_out_of_range_temp(self):
        raw = "02010613FF3906CA0320FF000380008000800047F8321E"
        result = _decode_temperature(raw)
        assert result is None

    def test_returns_none_for_empty_string(self):
        assert _decode_temperature("") is None


class TestEstimateBattery:
    def test_returns_int(self):
        raw = "02010613FF3906CA03201C2D0380008000800047F8321E"
        result = _estimate_battery(raw)
        assert isinstance(result, int)
        assert 0 <= result <= 100

    def test_short_payload_returns_50(self):
        assert _estimate_battery("0102030405") == 50

    def test_invalid_hex_returns_50(self):
        assert _estimate_battery("ZZZZ") == 50


# ── Record decoding ─────────────────────────────────────────────────


class TestDecodeBLERecord:
    def test_valid_sensor_record(self):
        rec = {
            "type": "Sensor",
            "mac": "AA:BB:CC:DD:EE:FF",
            "rssi": -55,
            "rawData": "02010613FF3906CA03201C2D0380008000800047F8321E",
            "timestamp": "2025-06-15T10:30:00Z",
            "bleName": "TEMP_01",
        }
        result = _decode_ble_record(rec)
        assert result is not None
        assert result["device_id"] == "AA:BB:CC:DD:EE:FF"
        assert result["rssi"] == -55
        assert result["signal_dbm"] == -55
        assert abs(result["temperature"] - 82.7164) < 0.01
        assert result["source"] == "iot_adapter"

    def test_gateway_record_filtered(self):
        rec = {"type": "Gateway", "mac": "GW:01", "rawData": "aabbccdd"}
        assert _decode_ble_record(rec) is None

    def test_missing_rawdata_filtered(self):
        rec = {"type": "Sensor", "mac": "AA:BB"}
        assert _decode_ble_record(rec) is None

    def test_short_rawdata_filtered(self):
        rec = {"type": "Sensor", "mac": "AA:BB", "rawData": "0102"}
        assert _decode_ble_record(rec) is None

    def test_auto_generates_timestamp(self):
        rec = {
            "type": "Sensor",
            "mac": "AA:BB:CC:DD:EE:FF",
            "rssi": -55,
            "rawData": "02010613FF3906CA03201C2D0380008000800047F8321E",
        }
        result = _decode_ble_record(rec)
        assert result is not None
        assert "timestamp" in result
        assert "T" in result["timestamp"]


# ── Lambda handler ──────────────────────────────────────────────────


class TestLambdaHandler:
    @patch("handlers.iot_adapter.kinesis")
    def test_processes_list_of_records(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        event = [
            {
                "type": "Sensor",
                "mac": "AA:BB:CC:DD:EE:01",
                "rssi": -40,
                "rawData": "02010613FF3906CA03201C2D0380008000800047F8321E",
                "timestamp": "2025-06-15T10:30:00Z",
            },
            {
                "type": "Sensor",
                "mac": "AA:BB:CC:DD:EE:02",
                "rssi": -60,
                "rawData": "02010613FF3906CA03201C2D0380008000800047F8321E",
                "timestamp": "2025-06-15T10:30:01Z",
            },
        ]
        result = lambda_handler(event, None)
        assert result["decoded"] == 2
        mock_kinesis.put_records.assert_called_once()

    @patch("handlers.iot_adapter.kinesis")
    def test_processes_single_record(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        event = {
            "type": "Sensor",
            "mac": "AA:BB:CC:DD:EE:01",
            "rssi": -40,
            "rawData": "02010613FF3906CA03201C2D0380008000800047F8321E",
            "timestamp": "2025-06-15T10:30:00Z",
        }
        result = lambda_handler(event, None)
        assert result["decoded"] == 1

    @patch("handlers.iot_adapter.kinesis")
    def test_filters_gateway_records(self, mock_kinesis):
        event = [{"type": "Gateway", "mac": "GW:01"}]
        result = lambda_handler(event, None)
        assert result["decoded"] == 0
        mock_kinesis.put_records.assert_not_called()

    @patch("handlers.iot_adapter.kinesis")
    def test_handles_malformed_records(self, mock_kinesis):
        event = [{"garbage": True}]
        result = lambda_handler(event, None)
        assert result["decoded"] == 0


# ── Kinesis write ───────────────────────────────────────────────────


class TestPutToKinesis:
    @patch("handlers.iot_adapter.kinesis")
    def test_writes_single_batch(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        records = [{"device_id": f"dev-{i}", "temperature": 72.0} for i in range(10)]
        _put_to_kinesis(records)
        mock_kinesis.put_records.assert_called_once()
        args = mock_kinesis.put_records.call_args
        assert len(args[1]["Records"]) == 10

    @patch("handlers.iot_adapter.kinesis")
    def test_batches_over_500(self, mock_kinesis):
        mock_kinesis.put_records = MagicMock()
        records = [{"device_id": f"dev-{i}", "temperature": 72.0} for i in range(510)]
        _put_to_kinesis(records)
        assert mock_kinesis.put_records.call_count == 2
