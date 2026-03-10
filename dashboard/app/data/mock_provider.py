"""Mock data provider — multi-tenant, realistic, time-varying data.

Three demo clients with different sensor counts:
  demo_client_1: 20 sensors  (default for local dev)
  demo_client_2: 15 sensors
  demo_client_3: 10 sensors
"""

import hashlib
import math
import random
import time
from datetime import datetime, timedelta, timezone

import numpy as np

_CLIENT_CONFIGS = {
    "demo_client_1": {"name": "Central Facility", "groups": [(74.0, 8), (78.0, 5), (80.5, 5), (75.0, 2)]},
    "demo_client_2": {"name": "North Wing", "groups": [(73.0, 6), (77.0, 5), (79.0, 4)]},
    "demo_client_3": {"name": "East Complex", "groups": [(76.0, 4), (79.0, 3), (82.0, 3)]},
}

_ANOMALY_REASONS = [
    "Rapid temperature spike detected",
    "Reading significantly above average",
    "Unusual pattern — possible HVAC issue",
    "Temperature dropping faster than expected",
    "Sensor reading inconsistent with neighbors",
    "Sustained high reading over 15 minutes",
]


def _time_factor(t: datetime) -> float:
    hour = t.hour + t.minute / 60
    return 2.5 * math.sin(math.pi * (hour - 6) / 12)


class MockProvider:
    def __init__(self, client_id: str = "demo_client_1"):
        self._client_id = client_id
        conf = _CLIENT_CONFIGS.get(client_id, _CLIENT_CONFIGS["demo_client_1"])
        self._facility = f"facility_{client_id}"
        self._sensors: list[dict] = []
        self._offline_frozen: dict[str, float] = {}
        self._cache: dict = {"states": None, "states_ts": 0, "ttl": 3}
        self._init_sensors(conf["groups"])
        self._seed_alerts()

    def _init_sensors(self, groups: list[tuple]):
        idx = 0
        for group_idx, (base, count) in enumerate(groups):
            for i in range(count):
                h = hashlib.md5(f"{self._client_id}_sensor_{idx}".encode()).hexdigest()[:12].upper()
                did = f"C3{h[:10]}"
                self._sensors.append({
                    "device_id": did, "base_temp": base + (i - count / 2) * 0.3,
                    "battery_base": random.randint(40, 100), "signal_base": random.randint(-70, -30),
                    "group": group_idx, "index": i, "zone_id": None, "zone_label": None,
                })
                idx += 1
        last = self._sensors[-1] if self._sensors else None
        if last:
            self._offline_frozen[last["device_id"]] = round(last["base_temp"] + 1.2, 2)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _sensor_temp(self, sensor: dict, t: datetime) -> float:
        base = sensor["base_temp"]
        diurnal = _time_factor(t)
        noise = random.gauss(0, 0.4)
        warming = 0.0
        if sensor["group"] == 0 and sensor["index"] in (3, 5):
            minutes_ago = (self._now() - t).total_seconds() / 60
            if minutes_ago < 30:
                warming = max(0, 6.0 - minutes_ago * 0.15)
        return round(base + diurnal + noise + warming, 2)

    def _is_offline(self, sensor: dict) -> bool:
        return sensor["device_id"] in self._offline_frozen

    def get_zones(self) -> list[str]:
        zones = {s["zone_id"] for s in self._sensors if s.get("zone_id")}
        return sorted(zones) if zones else []

    def get_all_devices(self) -> list[str]:
        return [s["device_id"] for s in self._sensors]

    def get_devices_in_zone(self, zone_id: str) -> list[str]:
        return [s["device_id"] for s in self._sensors if s.get("zone_id") == zone_id]

    def get_all_sensor_states(self) -> list[dict]:
        now_ts = time.time()
        if self._cache["states"] and (now_ts - self._cache["states_ts"]) < self._cache["ttl"]:
            return self._cache["states"]

        now = self._now()
        states = []
        for sensor in self._sensors:
            did = sensor["device_id"]
            offline = self._is_offline(sensor)

            if offline:
                frozen = self._offline_frozen.get(did, sensor["base_temp"])
                last_seen = (now - timedelta(minutes=15)).isoformat()
                states.append({
                    "device_id": did, "temperature": frozen,
                    "actual_high_1h": frozen, "actual_low_1h": frozen,
                    "rolling_avg_1h": frozen, "rate_of_change": 0.0,
                    "status": "offline", "last_seen": last_seen,
                    "battery_pct": 0, "signal_dbm": -99, "signal_label": "No Signal",
                    "anomaly": False, "anomaly_reason": None,
                    "zone_id": sensor.get("zone_id"), "zone_label": sensor.get("zone_label"),
                    "facility_id": self._facility, "client_id": self._client_id,
                })
                continue

            temp = self._sensor_temp(sensor, now)
            readings_1h = [self._sensor_temp(sensor, now - timedelta(minutes=m)) for m in range(0, 60, 3)]
            avg_1h = float(np.mean(readings_1h))
            std_1h = float(np.std(readings_1h, ddof=1)) if len(readings_1h) > 1 else 0.0
            roc = readings_1h[0] - readings_1h[3] if len(readings_1h) > 3 else 0
            z = (temp - avg_1h) / std_1h if std_1h > 0 else 0.0
            anomaly = abs(z) > 2.5 or temp > 88 or temp < 60

            battery = max(0, min(100, sensor["battery_base"] - int((now.hour + now.minute / 60) * 0.3)))
            signal_dbm = sensor["signal_base"] + random.randint(-5, 5)
            if signal_dbm >= -50:
                signal_label = "Strong"
            elif signal_dbm >= -65:
                signal_label = "Good"
            elif signal_dbm >= -80:
                signal_label = "Weak"
            else:
                signal_label = "No Signal"

            states.append({
                "device_id": did, "temperature": temp,
                "actual_high_1h": round(float(np.max(readings_1h)), 2),
                "actual_low_1h": round(float(np.min(readings_1h)), 2),
                "rolling_avg_1h": round(avg_1h, 2), "rate_of_change": round(roc, 2),
                "status": "online", "last_seen": now.isoformat(),
                "battery_pct": battery, "signal_dbm": signal_dbm, "signal_label": signal_label,
                "anomaly": anomaly, "anomaly_reason": random.choice(_ANOMALY_REASONS) if anomaly else None,
                "zone_id": sensor.get("zone_id"), "zone_label": sensor.get("zone_label"),
                "facility_id": self._facility, "client_id": self._client_id,
            })
        self._cache["states"] = states
        self._cache["states_ts"] = now_ts
        return states

    def get_readings(self, device_id: str, since_iso: str) -> list[dict]:
        sensor = self._find(device_id)
        if not sensor:
            return []
        now = self._now()
        since = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        minutes = int((now - since).total_seconds() / 60)
        readings = []
        for m in range(minutes, -1, -1):
            t = now - timedelta(minutes=m)
            readings.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M:00Z"), "temperature": self._sensor_temp(sensor, t)})
        return readings

    def get_active_alerts(self, facility_zone: str | None = None) -> list[dict]:
        return [a for a in self._alerts if a["status"] == "ACTIVE"]

    def get_all_alerts(self) -> list[dict]:
        return list(self._alerts)

    def get_forecast(self, device_id: str, horizon: str) -> dict | None:
        sensor = self._find(device_id)
        if not sensor:
            return None
        base = self._sensor_temp(sensor, self._now())
        trend = 0.02 if sensor["group"] == 0 else -0.005
        steps = 30 if horizon == "30min" else 120
        final = base + trend * steps
        std = 0.8
        return {"predicted_temp": round(final, 2),
                "ci_lower": round(final - 1.96 * std * (steps ** 0.5) * 0.1, 2),
                "ci_upper": round(final + 1.96 * std * (steps ** 0.5) * 0.1, 2),
                "steps": steps, "model_params": {"level": base, "trend": trend, "residual_std": std, "n_points": 120}}

    def get_forecast_series(self, device_id: str, horizon: str, steps: int) -> list[dict]:
        sensor = self._find(device_id)
        if not sensor:
            return []
        now = self._now()
        base = self._sensor_temp(sensor, now)
        trend = 0.02 if sensor["group"] == 0 else -0.005
        std = 0.8
        return [{"step": h, "timestamp": (now + timedelta(minutes=h)).strftime("%Y-%m-%dT%H:%M:00Z"),
                 "predicted": round(base + trend * h, 2),
                 "ci_lower": round(base + trend * h - 1.96 * std * (h ** 0.5) * 0.1, 2),
                 "ci_upper": round(base + trend * h + 1.96 * std * (h ** 0.5) * 0.1, 2)} for h in range(1, steps + 1)]

    def get_compliance_report(self, date_str: str) -> dict | None:
        random.seed(f"{self._client_id}_{date_str}")
        total = len(self._sensors) * 1440
        compliant = int(total * (0.95 + random.uniform(0, 0.049)))
        pct = round(compliant / total * 100, 1)
        random.seed()
        return {"overall_compliance_pct": pct, "total_readings": total, "compliant_readings": compliant, "date": date_str}

    def get_compliance_history(self, days: int) -> list[dict]:
        now = self._now()
        history = []
        for d in range(days, 0, -1):
            ds = (now - timedelta(days=d)).strftime("%Y-%m-%d")
            random.seed(f"{self._client_id}_{ds}")
            history.append({"date": ds, "compliance_pct": round(min(96.5 + random.uniform(0, 3.5), 100.0), 1)})
        random.seed()
        return history

    def _find(self, device_id: str) -> dict | None:
        for s in self._sensors:
            if s["device_id"] == device_id:
                return s
        return None

    def _seed_alerts(self):
        now = self._now()
        ns = len(self._sensors)

        def _a(atype, sev, msg, td, status, idx, **extra):
            return {"alert_type": atype, "severity": sev, "message": msg,
                    "triggered_at": (now - td).isoformat(), "status": status,
                    "device_id": self._sensors[idx % ns]["device_id"],
                    "facility_id": self._facility, "client_id": self._client_id, **extra}

        self._alerts = []
        if ns >= 4:
            self._alerts = [
                _a("EXTREME_TEMPERATURE", "CRITICAL", "Temperature 96.1\u00b0F \u2014 exceeds safe limit", timedelta(minutes=3), "ACTIVE", ns - 4, temperature=96.1),
                _a("SUSTAINED_HIGH", "HIGH", "Stayed above 85\u00b0F for 12 minutes", timedelta(minutes=12), "ACTIVE", ns - 3),
                _a("SENSOR_OFFLINE", "HIGH", "Sensor not responding for 15 minutes", timedelta(minutes=15), "ACTIVE", ns - 1),
                _a("RAPID_CHANGE", "MEDIUM", "Temperature changed 4.5\u00b0F in 1 minute", timedelta(hours=1, minutes=15), "RESOLVED", 2),
                _a("FORECAST_BREACH", "WARNING", "Forecast: expected to exceed 85\u00b0F in 30 min", timedelta(minutes=25), "ACTIVE", ns - 4),
            ]
        atypes = ["EXTREME_TEMPERATURE", "SUSTAINED_HIGH", "RAPID_CHANGE", "SENSOR_OFFLINE"]
        for d in range(1, 8):
            for _ in range(random.randint(2, 5)):
                idx = random.randint(0, ns - 1)
                self._alerts.append(_a(random.choice(atypes), random.choice(["CRITICAL", "HIGH", "MEDIUM", "WARNING"]),
                                       "Historical alert", timedelta(days=d, hours=-random.randint(0, 23)), "RESOLVED", idx))
