"""Test-only mock provider — deterministic data, no I/O."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


class MockProvider:
    """Satisfies the DataProvider protocol with deterministic in-memory data."""

    def __init__(self, client_id: str = "test_client"):
        self._client_id = client_id
        self._sensors = ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02", "AA:BB:CC:DD:EE:03"]
        self._dismissed: set[str] = set()
        self._notes: list[dict] = []

    def get_all_sensor_states(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        return [
            {"device_id": self._sensors[0], "temperature": 74.5, "actual_high_1h": 76.2,
             "actual_low_1h": 72.1, "rolling_avg_1h": 73.8, "rate_of_change": 0.3,
             "status": "online", "last_seen": now.isoformat(), "battery_pct": 92,
             "signal_dbm": -42, "signal_label": "Strong", "anomaly": False, "anomaly_reason": None,
             "zone_id": "zone-A", "zone_label": "Cell Block A", "facility_id": "fac-1", "client_id": self._client_id},
            {"device_id": self._sensors[1], "temperature": 88.0, "actual_high_1h": 89.5,
             "actual_low_1h": 85.0, "rolling_avg_1h": 87.0, "rate_of_change": 1.5,
             "status": "online", "last_seen": now.isoformat(), "battery_pct": 15,
             "signal_dbm": -70, "signal_label": "Weak", "anomaly": True, "anomaly_reason": "Temperature above high limit",
             "zone_id": "zone-B", "zone_label": "Cell Block B", "facility_id": "fac-1", "client_id": self._client_id},
            {"device_id": self._sensors[2], "temperature": 70.1, "actual_high_1h": 71.0,
             "actual_low_1h": 69.0, "rolling_avg_1h": 70.0, "rate_of_change": 0.0,
             "status": "offline", "last_seen": (now - timedelta(hours=2)).isoformat(), "battery_pct": 0,
             "signal_dbm": -99, "signal_label": "No Signal", "anomaly": False, "anomaly_reason": None,
             "zone_id": "zone-A", "zone_label": "Cell Block A", "facility_id": "fac-1", "client_id": self._client_id},
        ]

    def get_readings(self, device_id: str, since_iso: str, until_iso: str | None = None) -> list[dict]:
        now = datetime.now(timezone.utc)
        base = 74.0 if "01" in device_id else (88.0 if "02" in device_id else 70.1)
        return [{"timestamp": (now - timedelta(minutes=30 - i)).strftime("%Y-%m-%dT%H:%M:00Z"),
                 "temperature": round(base + (i % 5) * 0.1, 2)} for i in range(31)]

    def get_forecast(self, device_id: str, horizon: str) -> dict | None:
        return {"predicted_temp": 75.2, "ci_lower": 73.8, "ci_upper": 76.6, "steps": 30,
                "model_params": {"level": 74.5, "trend": 0.02, "residual_std": 0.5, "n_points": 31}}

    def get_forecast_series(self, device_id: str, horizon: str, steps: int) -> list[dict]:
        now = datetime.now(timezone.utc)
        return [{"step": i, "timestamp": (now + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:00Z"),
                 "predicted": round(74.5 + 0.02 * i, 2), "ci_lower": round(73.5 + 0.02 * i, 2),
                 "ci_upper": round(75.5 + 0.02 * i, 2)} for i in range(1, steps + 1)]

    def get_compliance_history(self, days: int) -> list[dict]:
        now = datetime.now(timezone.utc)
        return [{"date": (now - timedelta(days=i)).strftime("%Y-%m-%d"), "compliance_pct": round(96.5 - i * 0.3, 1)}
                for i in range(days)]

    def get_all_devices(self) -> list[str]:
        return self._sensors[:]

    def get_zones(self) -> list[str]:
        return ["zone-A", "zone-B"]

    def get_live_alerts(self) -> list[dict]:
        alerts = [
            {"PK": "ALERT#AA:BB:CC:DD:EE:02#SUSTAINED_HIGH", "SK": "2026-03-09T12:00:00+00:00",
             "device_id": "AA:BB:CC:DD:EE:02", "alert_type": "SUSTAINED_HIGH", "severity": "HIGH",
             "message": "Temperature 88.0°F — above normal range", "temperature": "88.0",
             "triggered_at": "2026-03-09T12:00:00+00:00", "state": "ACTIVE",
             "client_id": self._client_id},
        ]
        return [a for a in alerts if a["PK"] not in self._dismissed]

    def get_alert_history(self, device_id: Optional[str] = None, days: int = 7) -> list[dict]:
        all_alerts = [
            {"PK": "ALERT#AA:BB:CC:DD:EE:02#SUSTAINED_HIGH", "SK": "2026-03-09T12:00:00+00:00",
             "device_id": "AA:BB:CC:DD:EE:02", "alert_type": "SUSTAINED_HIGH", "severity": "HIGH",
             "message": "Temperature 88.0°F — above normal range", "temperature": "88.0",
             "triggered_at": "2026-03-09T12:00:00+00:00", "state": "ACTIVE",
             "client_id": self._client_id},
            {"PK": "ALERT#AA:BB:CC:DD:EE:01#RAPID_CHANGE", "SK": "2026-03-08T10:00:00+00:00",
             "device_id": "AA:BB:CC:DD:EE:01", "alert_type": "RAPID_CHANGE", "severity": "MEDIUM",
             "message": "Temperature changed 5.2°F in 10 min", "temperature": "74.5",
             "triggered_at": "2026-03-08T10:00:00+00:00", "state": "RESOLVED",
             "client_id": self._client_id},
        ]
        if device_id:
            all_alerts = [a for a in all_alerts if a.get("device_id") == device_id]
        return all_alerts

    def dismiss_alert(self, device_id: str, alert_type: str) -> None:
        self._dismissed.add(f"ALERT#{device_id}#{alert_type}")

    def send_alert_note(self, device_id: str, alert_type: str, context: dict) -> bool:
        self._notes.append(context)
        self._dismissed.add(f"ALERT#{device_id}#{alert_type}")
        return True
