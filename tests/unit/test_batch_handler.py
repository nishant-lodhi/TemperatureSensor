"""Unit tests for handlers/batch_handler.py — Kinesis batch processing pipeline."""

import base64
import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")


from handlers.batch_handler import (
    _auto_provision,
    _check_alerts,
    _decode_records,
    _enrich_batch,
    _store_aggregates,
    _update_states,
    _validate_batch,
    lambda_handler,
)
from storage import dynamodb_store


def _kinesis_record(event: dict) -> dict:
    payload = json.dumps(event).encode()
    return {"kinesis": {"data": base64.b64encode(payload).decode()}}


def _sample_event(device_id="C30000301A80", temperature=82.7, ts_offset_sec=0):
    base = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    ts = (base + timedelta(seconds=ts_offset_sec)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return {
        "device_id": device_id,
        "temperature": temperature,
        "rssi": -44,
        "power": 87,
        "timestamp": ts,
        "gateway_id": "AC233FC170F4",
    }


# ── _decode_records ───────────────────────────────────────


class TestDecodeRecords:
    def test_valid_records(self):
        events = [_sample_event(), _sample_event(temperature=83.0)]
        records = [_kinesis_record(e) for e in events]
        decoded = _decode_records(records)
        assert len(decoded) == 2
        assert decoded[0]["temperature"] == 82.7

    def test_invalid_base64_skipped(self):
        payload = base64.b64encode(b"{{not-json-at-all").decode()
        records = [{"kinesis": {"data": payload}}]
        decoded = _decode_records(records)
        assert len(decoded) == 0

    def test_invalid_json_skipped(self):
        payload = base64.b64encode(b"not-json").decode()
        records = [{"kinesis": {"data": payload}}]
        decoded = _decode_records(records)
        assert len(decoded) == 0

    def test_missing_kinesis_key_skipped(self):
        records = [{"bad_key": {"data": "something"}}]
        decoded = _decode_records(records)
        assert len(decoded) == 0

    def test_mixed_valid_invalid(self):
        valid = _kinesis_record(_sample_event())
        invalid = {"bad_key": {"data": "something"}}
        decoded = _decode_records([valid, invalid])
        assert len(decoded) == 1

    def test_empty_records(self):
        assert _decode_records([]) == []


# ── _validate_batch ───────────────────────────────────────


class TestValidateBatch:
    def test_all_valid(self):
        events = [_sample_event(), _sample_event(temperature=79.0)]
        valid, invalid = _validate_batch(events)
        assert len(valid) == 2
        assert len(invalid) == 0

    def test_invalid_temp_rejected(self):
        events = [_sample_event(), {"device_id": "dev1", "temperature": "bad", "timestamp": "2024-01-01T00:00:00Z"}]
        valid, invalid = _validate_batch(events)
        assert len(valid) == 1
        assert len(invalid) == 1

    def test_missing_fields_rejected(self):
        events = [{"temperature": 80.0}]
        valid, invalid = _validate_batch(events)
        assert len(valid) == 0
        assert len(invalid) == 1

    def test_invalid_records_include_reason(self):
        events = [{"temperature": 80.0}]
        _, invalid = _validate_batch(events)
        assert "reason" in invalid[0]


# ── _enrich_batch ─────────────────────────────────────────


class TestEnrichBatch:
    def test_registered_device_enriched(self, seed_device):
        events = [_sample_event()]
        enriched = _enrich_batch(events)
        assert len(enriched) == 1
        assert "client_id" in enriched[0]
        assert enriched[0]["client_id"] == "client_1"

    def test_unregistered_device_skipped(self, aws_mock):
        events = [_sample_event(device_id="UNKNOWN_DEVICE_XYZ")]
        enriched = _enrich_batch(events)
        assert len(enriched) == 0


# ── _auto_provision ───────────────────────────────────────


class TestAutoProvision:
    def test_creates_state_entry(self, aws_mock):
        info = _auto_provision("NEW_DEVICE_001")
        assert info["device_id"] == "NEW_DEVICE_001"
        assert info["client_id"] == "unassigned"
        state = dynamodb_store.get_sensor_state("NEW_DEVICE_001")
        assert state is not None
        assert state.get("auto_provisioned") is True


# ── _update_states ────────────────────────────────────────


class TestUpdateStates:
    def test_deduplicates_by_device(self, aws_mock):
        events = [
            {**_sample_event(ts_offset_sec=0), "client_id": "c1", "zone_id": "z1", "facility_id": "f1"},
            {**_sample_event(ts_offset_sec=10), "client_id": "c1", "zone_id": "z1", "facility_id": "f1"},
        ]
        _update_states(events)
        state = dynamodb_store.get_sensor_state("C30000301A80")
        assert state is not None
        assert state["status"] == "online"

    def test_multiple_devices(self, aws_mock):
        events = [
            {**_sample_event(device_id="DEV_A", ts_offset_sec=0), "client_id": "c1", "zone_id": "z1", "facility_id": "f1"},
            {**_sample_event(device_id="DEV_B", ts_offset_sec=0), "client_id": "c1", "zone_id": "z1", "facility_id": "f1"},
        ]
        _update_states(events)
        assert dynamodb_store.get_sensor_state("DEV_A") is not None
        assert dynamodb_store.get_sensor_state("DEV_B") is not None


# ── _store_aggregates ─────────────────────────────────────


class TestStoreAggregates:
    def test_stores_reading_per_minute_bucket(self, aws_mock):
        events = [{**_sample_event(ts_offset_sec=i * 5), "client_id": "c1"} for i in range(5)]
        _store_aggregates(events)
        readings = dynamodb_store.get_readings("C30000301A80", "2024-10-01T11:00:00Z")
        assert len(readings) >= 1

    def test_aggregates_temperature(self, aws_mock):
        events = [
            {**_sample_event(temperature=80.0), "client_id": "c1"},
            {**_sample_event(temperature=82.0), "client_id": "c1"},
        ]
        _store_aggregates(events)
        readings = dynamodb_store.get_readings("C30000301A80", "2024-10-01T11:00:00Z")
        for r in readings:
            temp = float(r.get("temperature", 0))
            assert 79 < temp < 83


# ── _check_alerts ─────────────────────────────────────────


class TestCheckAlerts:
    def test_no_crash_with_registered_device(self, seed_device):
        events = [{
            **_sample_event(temperature=87.0, ts_offset_sec=i * 60),
            "client_id": "client_1",
            "zone_id": "zone_b",
            "facility_id": "facility_A",
        } for i in range(15)]
        _check_alerts(events, {})

    def test_alerts_disabled_by_feature_flag(self, seed_device):
        events = [{
            **_sample_event(temperature=96.0),
            "client_id": "client_1",
            "zone_id": "zone_b",
            "facility_id": "facility_A",
        }]
        cache = {"client_1": {"alerts_enabled": False}}
        _check_alerts(events, cache)
        active = dynamodb_store.get_active_alerts("facility_A#zone_b")
        assert len(active) == 0


# ── lambda_handler ────────────────────────────────────────


class TestLambdaHandler:
    def test_empty_records(self, aws_mock):
        result = lambda_handler({"Records": []}, None)
        assert result["statusCode"] == 200
        assert result["processed"] == 0
        assert result["rejected"] == 0

    def test_valid_batch(self, seed_device):
        events = [_sample_event(ts_offset_sec=i * 5) for i in range(5)]
        records = [_kinesis_record(e) for e in events]
        result = lambda_handler({"Records": records}, None)
        assert result["statusCode"] == 200
        assert result["processed"] == 5

    def test_mixed_valid_invalid(self, seed_device):
        good = _kinesis_record(_sample_event())
        bad = _kinesis_record({"device_id": "dev1", "temperature": "bad", "timestamp": "2024-01-01T00:00:00Z"})
        result = lambda_handler({"Records": [good, bad]}, None)
        assert result["processed"] >= 1
        assert result["rejected"] >= 1

    def test_no_records_key(self, aws_mock):
        result = lambda_handler({}, None)
        assert result["statusCode"] == 200
        assert result["processed"] == 0
