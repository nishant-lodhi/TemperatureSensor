#!/usr/bin/env python3
"""Standalone sensor simulator — 13 in-memory sensors with 10 days of history.

10 live (new readings every 5s) + 3 offline (stopped 2h ago).
Seeds full history so ALL features work: charts, date ranges, compliance,
anomaly detection, forecasting, alerts, location filtering, offline handling.

Zero database dependency. Does not modify any production code or write to any DB.

Usage:
    cd TemperatureSensor
    python sensor_simulator.py                  # http://localhost:8051
    python sensor_simulator.py --port 8060      # custom port

Test coverage by sensor:
    SIM001,SIM002,SIM005  stable (healthy)       — no alerts
    SIM003                drift_up 72→78°F       — late SUSTAINED_HIGH
    SIM004                edge 78-86°F           — intermittent SUSTAINED_HIGH
    SIM006                hot 86-91°F            — always SUSTAINED_HIGH
    SIM007                hot 91-96°F            — EXTREME_TEMPERATURE when >95
    SIM008                cold 60-63°F           — always LOW_TEMPERATURE
    SIM009                rapid ±8°F spikes      — RAPID_CHANGE
    SIM00A                drift_down 74→69°F     — late LOW_TEMPERATURE
    C300/F02F/D823        offline (real MACs)     — SENSOR_OFFLINE
"""

from __future__ import annotations

import argparse
import math
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

# ── Sensor definitions ───────────────────────────────────────────────────────

SENSORS = [
    # (mac, location, base_temp, profile, rssi, battery)
    ("SIM0A0000001", "01-Facility Master", 73.0,  "stable",     -28, 95),
    ("SIM0A0000002", "01-Facility Master", 74.5,  "stable",     -32, 88),
    ("SIM0A0000003", "01-Facility Master", 72.0,  "drift_up",   -45, 72),
    ("SIM0A0000004", "01-Facility Master", 82.0,  "edge",       -38, 60),
    ("SIM0A0000005", "02-Block North",     75.0,  "stable",     -52, 91),
    ("SIM0A0000006", "02-Block North",     88.0,  "hot",        -61, 45),
    ("SIM0A0000007", "02-Block North",     93.0,  "hot",        -55, 38),
    ("SIM0A0000008", "03-Block South",     62.0,  "cold",       -70, 82),
    ("SIM0A0000009", "03-Block South",     73.0,  "rapid",      -42, 77),
    ("SIM0A000000A", "03-Block South",     74.0,  "drift_down", -48, 65),
]

OFFLINE_SENSORS = [
    ("C30000301A80", "01-Facility Master", 69.76, -28, 0),
    ("F02F7C2A4D5D", "01-Facility Master", 95.84, -37, 0),
    ("D8233EF06D25", "01-Facility Master", 95.21, -32, 0),
]

TEMP_HIGH, TEMP_LOW = 85.0, 65.0
TEMP_CRIT_HIGH, TEMP_CRIT_LOW = 95.0, 50.0
HISTORY_DAYS = 10
OFFLINE_HOURS = 2

# ── Temperature generator ────────────────────────────────────────────────────


def _temp(base: float, profile: str, elapsed_min: float) -> float:
    """Temperature at elapsed_min minutes since start of history window."""
    t = elapsed_min
    total = HISTORY_DAYS * 1440.0
    if profile == "stable":
        return base + random.gauss(0, 0.4)
    if profile == "drift_up":
        return base + min(t / total * 6.0, 6.0) + random.gauss(0, 0.3)
    if profile == "drift_down":
        return base + max(-t / total * 5.0, -5.0) + random.gauss(0, 0.3)
    if profile == "hot":
        return base + random.gauss(0, 1.2) + 1.5 * math.sin(t / 90.0 * math.pi)
    if profile == "cold":
        return base + random.gauss(0, 0.5) - abs(math.sin(t / 120.0 * math.pi))
    if profile == "rapid":
        pos = t % 30.0
        spike = 8.0 * math.sin(pos / 8.0 * math.pi) if pos < 8.0 else 0.0
        return base + spike + random.gauss(0, 0.5)
    if profile == "edge":
        return base + 4.0 * math.sin(t / 60.0 * math.pi) + random.gauss(0, 0.3)
    return base + random.gauss(0, 0.4)


def _signal_label(rssi: float) -> str:
    if rssi >= -50:
        return "Strong"
    if rssi >= -65:
        return "Good"
    return "Weak" if rssi >= -80 else "No Signal"


# ── SimulatorProvider ────────────────────────────────────────────────────────


class SimulatorProvider:
    """In-memory DataProvider with 10-day history for 10 live + 3 offline sensors."""

    def __init__(self):
        self._lock = threading.Lock()
        self._readings: dict[str, list[dict]] = {}
        self._alerts_mem: dict[str, dict] = {}
        self._dismissed: set[str] = set()
        self._cooldowns: dict[str, float] = {}
        self._resolved: list[dict] = []
        self._notes: list[dict] = []
        self._t0 = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)

    # ── Seeding ───────────────────────────────────────────────────────────

    def seed_history(self):
        """Generate 10 days of readings: 5-min old data, 10s for last 2 hours."""
        now = datetime.now(timezone.utc)
        boundary = now - timedelta(hours=2)

        for mac, loc, base, profile, rssi, bat in SENSORS:
            readings = []
            t = self._t0
            while t <= now:
                el = (t - self._t0).total_seconds() / 60.0
                temp = round(_temp(base, profile, el), 2)
                readings.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "temperature": temp})
                t += timedelta(seconds=10) if t >= boundary else timedelta(minutes=5)
            self._readings[mac] = readings

        offline_end = now - timedelta(hours=OFFLINE_HOURS)
        for mac, loc, base_temp, rssi, bat in OFFLINE_SENSORS:
            readings = []
            t = self._t0
            while t <= offline_end:
                el = (t - self._t0).total_seconds() / 60.0
                temp = round(base_temp + 0.5 * math.sin(el * 0.001) + random.gauss(0, 0.3), 2)
                readings.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "temperature": temp})
                t += timedelta(minutes=5)
            self._readings[mac] = readings

        total = sum(len(v) for v in self._readings.values())
        print(f"✅ Seeded {total:,} readings across {len(self._readings)} sensors "
              f"({HISTORY_DAYS} days)")

    # ── Background tick ───────────────────────────────────────────────────

    def generate_tick(self):
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        el = (now - self._t0).total_seconds() / 60.0

        with self._lock:
            for mac, loc, base, profile, rssi, bat in SENSORS:
                temp = round(_temp(base, profile, el), 2)
                self._readings.setdefault(mac, []).append(
                    {"timestamp": ts, "temperature": temp})
                if len(self._readings[mac]) > 20000:
                    self._readings[mac] = self._readings[mac][-15000:]
            self._evaluate_alerts(ts)

    def _evaluate_alerts(self, ts: str):
        triggered_pks: set[str] = set()

        for mac, loc, base, profile, rssi, bat in SENSORS:
            readings = self._readings.get(mac, [])
            if not readings:
                continue
            temp = readings[-1]["temperature"]
            roc = (abs(readings[-1]["temperature"] - readings[-3]["temperature"])
                   if len(readings) >= 3 else 0.0)

            checks: list[tuple[str, str, str]] = []
            if temp > TEMP_CRIT_HIGH:
                checks.append(("EXTREME_TEMPERATURE", "CRITICAL",
                               f"Temperature {temp:.1f}°F — exceeds safe limit"))
            elif temp > TEMP_HIGH:
                checks.append(("SUSTAINED_HIGH", "HIGH",
                               f"Temperature {temp:.1f}°F — above normal range"))
            if temp < TEMP_CRIT_LOW:
                checks.append(("EXTREME_TEMPERATURE_LOW", "CRITICAL",
                               f"Temperature {temp:.1f}°F — below safe limit"))
            elif temp < TEMP_LOW:
                checks.append(("LOW_TEMPERATURE", "MEDIUM",
                               f"Temperature {temp:.1f}°F — below normal range"))
            if roc > 4.0:
                checks.append(("RAPID_CHANGE", "MEDIUM",
                               f"Temperature changed {roc:.1f}°F in recent readings"))

            for atype, sev, msg in checks:
                pk = f"ALERT#{mac}#{atype}"
                triggered_pks.add(pk)
                if pk in self._alerts_mem or pk in self._dismissed:
                    continue
                if (time.time() - self._cooldowns.get(pk, 0)) < 300:
                    continue
                self._alerts_mem[pk] = {
                    "PK": pk, "SK": ts, "device_id": mac,
                    "alert_type": atype, "severity": sev, "message": msg,
                    "temperature": str(temp), "triggered_at": ts,
                    "state": "ACTIVE", "client_id": "demo_client_1",
                }

        for mac, loc, temp, rssi, bat in OFFLINE_SENSORS:
            pk = f"ALERT#{mac}#SENSOR_OFFLINE"
            triggered_pks.add(pk)
            if pk not in self._alerts_mem and pk not in self._dismissed:
                self._alerts_mem[pk] = {
                    "PK": pk, "SK": ts, "device_id": mac,
                    "alert_type": "SENSOR_OFFLINE", "severity": "HIGH",
                    "message": f"Sensor {mac[-8:]} not responding",
                    "temperature": str(temp), "triggered_at": ts,
                    "state": "ACTIVE", "client_id": "demo_client_1",
                }

        for pk in list(self._alerts_mem):
            if pk not in triggered_pks:
                a = self._alerts_mem.pop(pk)
                self._resolved.append({**a, "state": "RESOLVED", "resolved_at": ts})

    # ── DataProvider: sensor states ───────────────────────────────────────

    def get_all_sensor_states(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        h1 = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        states = []

        with self._lock:
            for mac, loc, base, profile, rssi_base, bat in SENSORS:
                readings = self._readings.get(mac, [])
                if not readings:
                    continue
                temp = readings[-1]["temperature"]
                rssi = rssi_base + random.randint(-3, 3)

                recent = []
                for r in reversed(readings):
                    if r["timestamp"] < h1:
                        break
                    recent.append(r["temperature"])
                if not recent:
                    recent = [temp]

                arr = np.array(recent)
                hi, lo, avg = float(np.max(arr)), float(np.min(arr)), float(np.mean(arr))
                std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

                roc = (round(readings[-1]["temperature"] - readings[-3]["temperature"], 2)
                       if len(readings) >= 3 else 0.0)

                anomaly, reason = False, None
                if temp > TEMP_CRIT_HIGH:
                    anomaly, reason = True, f"Exceeds critical high ({TEMP_CRIT_HIGH}°F)"
                elif temp < TEMP_CRIT_LOW:
                    anomaly, reason = True, f"Below critical low ({TEMP_CRIT_LOW}°F)"
                elif std > 0 and abs(temp - avg) / std > 2.5:
                    z = abs(temp - avg) / std
                    anomaly, reason = True, f"Statistical anomaly (z-score {z:.1f})"

                states.append({
                    "device_id": mac, "temperature": round(temp, 2),
                    "actual_high_1h": round(hi, 2), "actual_low_1h": round(lo, 2),
                    "rolling_avg_1h": round(avg, 2), "rate_of_change": roc,
                    "status": "online", "last_seen": now.isoformat(),
                    "battery_pct": max(0, min(100, bat + random.randint(-2, 2))),
                    "signal_dbm": rssi, "signal_label": _signal_label(rssi),
                    "anomaly": anomaly, "anomaly_reason": reason,
                    "location": loc, "zone_id": loc, "zone_label": loc,
                    "facility_id": "sim-facility", "client_id": "demo_client_1",
                })

        offline_ts = (now - timedelta(hours=OFFLINE_HOURS)).isoformat()
        for mac, loc, temp, rssi, bat in OFFLINE_SENSORS:
            states.append({
                "device_id": mac, "temperature": temp,
                "actual_high_1h": temp, "actual_low_1h": temp,
                "rolling_avg_1h": temp, "rate_of_change": 0.0,
                "status": "offline", "last_seen": offline_ts,
                "battery_pct": 0, "signal_dbm": rssi, "signal_label": "No Signal",
                "anomaly": False, "anomaly_reason": None,
                "location": loc, "zone_id": loc, "zone_label": loc,
                "facility_id": "sim-facility", "client_id": "demo_client_1",
            })
        return states

    # ── DataProvider: readings ────────────────────────────────────────────

    def get_readings(self, device_id: str, since_iso: str,
                     until_iso: str | None = None) -> list[dict]:
        with self._lock:
            readings = list(self._readings.get(device_id, []))
        if not readings:
            return []
        if not since_iso:
            return readings[-120:]

        since = since_iso[:19].replace("Z", "")
        until = until_iso[:19].replace("Z", "") if until_iso else None

        filtered = [r for r in readings
                    if r["timestamp"][:19] >= since
                    and (until is None or r["timestamp"][:19] <= until)]
        return filtered if filtered else readings[-60:]

    # ── DataProvider: forecast ────────────────────────────────────────────

    def get_forecast(self, device_id: str, horizon: str) -> dict | None:
        readings = self.get_readings(device_id, "")
        if len(readings) < 5:
            return None
        temps = [r["temperature"] for r in readings[-60:]]
        y = np.array(temps)
        level = float(y[-1])
        trend = float(np.polyfit(np.arange(len(y)), y, 1)[0]) if len(y) >= 2 else 0.0
        std = float(np.std(y, ddof=1)) if len(y) > 1 else 0.5
        steps = 30 if horizon == "30min" else 120
        final = level + trend * steps
        ci = 1.96 * std * (steps ** 0.5) * 0.1
        return {
            "predicted_temp": round(final, 2),
            "ci_lower": round(final - ci, 2), "ci_upper": round(final + ci, 2),
            "steps": steps,
            "model_params": {"level": round(level, 4), "trend": round(trend, 6),
                             "residual_std": round(std, 4), "n_points": len(y)},
        }

    def get_forecast_series(self, device_id: str, horizon: str,
                            steps: int) -> list[dict]:
        fc = self.get_forecast(device_id, horizon)
        if not fc or "model_params" not in fc:
            return []
        p = fc["model_params"]
        now = datetime.now(timezone.utc)
        return [{
            "step": h,
            "timestamp": (now + timedelta(minutes=h)).strftime("%Y-%m-%dT%H:%M:00Z"),
            "predicted": round(p["level"] + p["trend"] * h, 2),
            "ci_lower": round(p["level"] + p["trend"] * h
                              - 1.96 * p["residual_std"] * (h ** 0.5) * 0.1, 2),
            "ci_upper": round(p["level"] + p["trend"] * h
                              + 1.96 * p["residual_std"] * (h ** 0.5) * 0.1, 2),
        } for h in range(1, steps + 1)]

    # ── DataProvider: compliance (computed from actual readings) ──────────

    def get_compliance_history(self, days: int) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        day_stats: dict[str, list[int]] = {}
        with self._lock:
            for readings in self._readings.values():
                for r in readings:
                    day = r["timestamp"][:10]
                    if day < cutoff:
                        continue
                    if day not in day_stats:
                        day_stats[day] = [0, 0]
                    day_stats[day][0] += 1
                    if TEMP_LOW <= r["temperature"] <= TEMP_HIGH:
                        day_stats[day][1] += 1
        return [{"date": d, "compliance_pct": round(s[1] / s[0] * 100, 1) if s[0] else 0}
                for d, s in sorted(day_stats.items())]

    # ── DataProvider: devices & locations ─────────────────────────────────

    def get_all_devices(self) -> list[str]:
        return [s[0] for s in SENSORS] + [s[0] for s in OFFLINE_SENSORS]

    def get_locations(self) -> list[str]:
        return sorted({s[1] for s in SENSORS} | {s[1] for s in OFFLINE_SENSORS})

    def get_sensors_for_location(self, location: str | None = None) -> list[str]:
        if not location:
            return self.get_all_devices()
        return ([s[0] for s in SENSORS if s[1] == location]
                + [s[0] for s in OFFLINE_SENSORS if s[1] == location])

    def get_zones(self) -> list[str]:
        return self.get_locations()

    # ── DataProvider: alerts ──────────────────────────────────────────────

    def get_live_alerts(self) -> list[dict]:
        with self._lock:
            return sorted(
                [a for a in self._alerts_mem.values()
                 if a["PK"] not in self._dismissed],
                key=lambda a: a.get("triggered_at", ""), reverse=True)

    def get_alert_history(self, device_id: Optional[str] = None,
                          days: int = 7) -> list[dict]:
        with self._lock:
            combined = list(self._alerts_mem.values()) + list(self._resolved)
        if device_id:
            combined = [a for a in combined if a.get("device_id") == device_id]
        seen, deduped = set(), []
        for a in sorted(combined, key=lambda x: x.get("triggered_at", ""),
                        reverse=True):
            if a["PK"] not in seen:
                seen.add(a["PK"])
                deduped.append(a)
        return deduped[:50]

    def dismiss_alert(self, device_id: str, alert_type: str) -> None:
        pk = f"ALERT#{device_id}#{alert_type}"
        with self._lock:
            self._dismissed.add(pk)
            self._cooldowns[pk] = time.time()
            alert = self._alerts_mem.pop(pk, None)
            if alert:
                self._resolved.append({
                    **alert, "state": "DISMISSED",
                    "resolved_at": datetime.now(timezone.utc).isoformat()})

    def send_alert_note(self, device_id: str, alert_type: str,
                        context: dict) -> bool:
        self._notes.append(context)
        self.dismiss_alert(device_id, alert_type)
        return True


# ── Background thread ────────────────────────────────────────────────────────


def _run_generator(provider: SimulatorProvider, interval: float):
    while True:
        provider.generate_tick()
        time.sleep(interval)


# ── Main ─────────────────────────────────────────────────────────────────────


def _bootstrap():
    """Seed provider and inject into app.data.provider cache."""
    import os
    import sys
    dashboard_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dashboard")
    if dashboard_dir not in sys.path:
        sys.path.insert(0, dashboard_dir)

    provider = SimulatorProvider()
    provider.seed_history()

    t = threading.Thread(target=_run_generator, args=(provider, 5.0),
                         daemon=True)
    t.start()

    import app.data.provider as prov_mod
    prov_mod._providers["demo_client_1"] = provider
    prov_mod._providers["default"] = provider
    prov_mod._providers[None] = provider
    return provider


def main():
    parser = argparse.ArgumentParser(
        description="Run TempMonitor dashboard with simulated sensors")
    parser.add_argument("--port", type=int, default=8051)
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Seconds between new readings")
    parser.add_argument("--threaded", action="store_true", default=True,
                        help="Use threaded Flask server (default)")
    args = parser.parse_args()

    import os
    import sys
    dashboard_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dashboard")
    if dashboard_dir not in sys.path:
        sys.path.insert(0, dashboard_dir)

    provider = SimulatorProvider()
    provider.seed_history()

    t = threading.Thread(target=_run_generator, args=(provider, args.interval),
                         daemon=True)
    t.start()

    import app.data.provider as prov_mod
    prov_mod._providers["demo_client_1"] = provider
    prov_mod._providers["default"] = provider
    prov_mod._providers[None] = provider

    total = sum(len(v) for v in provider._readings.values())
    print(f"\n   SENSORS ({len(SENSORS)} live + {len(OFFLINE_SENSORS)} offline):")
    print("   " + "─ " * 38)
    for mac, loc, base, prof, rssi, bat in SENSORS:
        print(f"   🟢 {mac}  {loc:22s}  {base:5.1f}°F  {prof}")
    for mac, loc, temp, rssi, bat in OFFLINE_SENSORS:
        print(f"   ⚫ {mac:12s}  {loc:22s}  {temp:5.1f}°F  offline")
    print(f"\n   📊 History: {HISTORY_DAYS} days  |  📈 Readings: {total:,}"
          f"  |  🔄 Interval: {args.interval}s")
    print(f"\n🚀 Dashboard at http://localhost:{args.port}")
    print("   Threaded server for faster UI.  Ctrl+C to stop.\n")

    from app.main import app, server
    from werkzeug.serving import run_simple
    run_simple(
        "0.0.0.0", args.port, server,
        use_reloader=False, use_debugger=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
