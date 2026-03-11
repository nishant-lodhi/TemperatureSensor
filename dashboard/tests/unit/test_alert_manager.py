"""Tests for app.data.alert_manager — lifecycle, moto DynamoDB, officer actions."""

import os
import time
from datetime import datetime, timezone

import pytest

os.environ["AWS_MODE"] = "false"
os.environ["ALERTS_TABLE"] = "test-alerts-unit"
os.environ["ALERT_COOLDOWN_SEC"] = "1"

from app.data.alert_manager import AlertManager


def _make_state(did="AA:BB:CC:DD:EE:01", temp=74.5, status="online", roc=0.0):
    return {
        "device_id": did, "temperature": temp, "status": status,
        "rate_of_change": roc, "battery_pct": 90, "signal_dbm": -45,
        "facility_id": "fac-1", "client_id": "test-client",
    }


@pytest.fixture
def mgr():
    return AlertManager(
        "test-client", "test-alerts-unit",
        {"temp_high": 85, "temp_low": 65, "critical_high": 95,
         "critical_low": 50, "degraded_sec": 120, "offline_sec": 300},
    )


class TestEvaluate:
    def test_no_alerts_for_normal(self, mgr):
        alerts = mgr.evaluate([_make_state()])
        assert len(alerts) == 0

    def test_critical_high_creates_alert(self, mgr):
        alerts = mgr.evaluate([_make_state(temp=98.0)])
        assert any(a["alert_type"] == "EXTREME_TEMPERATURE" for a in alerts)

    def test_critical_low_creates_alert(self, mgr):
        alerts = mgr.evaluate([_make_state(temp=45.0)])
        assert any(a["alert_type"] == "EXTREME_TEMPERATURE_LOW" for a in alerts)

    def test_sustained_high(self, mgr):
        alerts = mgr.evaluate([_make_state(temp=90.0)])
        assert any(a["alert_type"] == "SUSTAINED_HIGH" for a in alerts)

    def test_offline_creates_alert(self, mgr):
        alerts = mgr.evaluate([_make_state(status="offline")])
        assert any(a["alert_type"] == "SENSOR_OFFLINE" for a in alerts)

    def test_rapid_change(self, mgr):
        alerts = mgr.evaluate([_make_state(roc=5.5)])
        assert any(a["alert_type"] == "RAPID_CHANGE" for a in alerts)

    def test_auto_resolve_on_recovery(self, mgr):
        mgr.evaluate([_make_state(temp=98.0)])
        assert len(mgr.get_live_alerts()) > 0
        alerts = mgr.evaluate([_make_state(temp=74.0)])
        assert len(alerts) == 0


class TestDismiss:
    def test_dismiss_removes_from_live(self, mgr):
        mgr.evaluate([_make_state(temp=98.0)])
        assert len(mgr.get_live_alerts()) > 0
        mgr.dismiss("AA:BB:CC:DD:EE:01", "EXTREME_TEMPERATURE")
        assert len(mgr.get_live_alerts()) == 0

    def test_cooldown_prevents_re_trigger(self, mgr):
        mgr.evaluate([_make_state(temp=98.0)])
        mgr.dismiss("AA:BB:CC:DD:EE:01", "EXTREME_TEMPERATURE")
        alerts = mgr.evaluate([_make_state(temp=98.0)])
        assert not any(a["alert_type"] == "EXTREME_TEMPERATURE" for a in alerts)

    def test_cooldown_expires(self, mgr):
        mgr.evaluate([_make_state(temp=98.0)])
        mgr.dismiss("AA:BB:CC:DD:EE:01", "EXTREME_TEMPERATURE")
        time.sleep(1.5)
        alerts = mgr.evaluate([_make_state(temp=98.0)])
        assert any(a["alert_type"] == "EXTREME_TEMPERATURE" for a in alerts)


class TestSendNoteAndDismiss:
    def test_no_arn_logs_locally(self, mgr):
        os.environ.pop("NOTE_LAMBDA_ARN", None)
        mgr.evaluate([_make_state(temp=98.0)])
        result = mgr.send_note_and_dismiss(
            "AA:BB:CC:DD:EE:01", "EXTREME_TEMPERATURE",
            {"device_id": "AA:BB:CC:DD:EE:01", "alert_type": "EXTREME_TEMPERATURE"},
        )
        assert result is True
        assert len(mgr.get_live_alerts()) == 0

    def test_auto_dismiss_after_note(self, mgr):
        mgr.evaluate([_make_state(temp=98.0)])
        assert len(mgr.get_live_alerts()) > 0
        mgr.send_note_and_dismiss(
            "AA:BB:CC:DD:EE:01", "EXTREME_TEMPERATURE",
            {"device_id": "AA:BB:CC:DD:EE:01", "alert_type": "EXTREME_TEMPERATURE",
             "timestamp": datetime.now(timezone.utc).isoformat()},
        )
        assert len(mgr.get_live_alerts()) == 0


class TestGetHistory:
    def test_empty_history(self, mgr):
        h = mgr.get_history()
        assert isinstance(h, list)

    def test_history_after_evaluate_and_resolve(self, mgr):
        mgr.evaluate([_make_state(temp=98.0)])
        mgr.evaluate([_make_state(temp=74.0)])
        h = mgr.get_history()
        assert isinstance(h, list)
        assert len(h) >= 1

    def test_history_filter_by_device(self, mgr):
        mgr.evaluate([_make_state(temp=98.0)])
        mgr.evaluate([_make_state(temp=74.0)])
        h = mgr.get_history(device_id="AA:BB:CC:DD:EE:01")
        assert all(a.get("device_id") == "AA:BB:CC:DD:EE:01" for a in h)

    def test_history_after_dismiss(self, mgr):
        mgr.evaluate([_make_state(temp=98.0)])
        mgr.dismiss("AA:BB:CC:DD:EE:01", "EXTREME_TEMPERATURE")
        h = mgr.get_history()
        dismissed = [a for a in h if a.get("state") == "DISMISSED"]
        assert len(dismissed) >= 1
